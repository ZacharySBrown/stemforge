"""prechop — slice each full stem WAV into N-bar aligned chunks.

Produces a directory tree:

    <output>/
        drums/
            001.wav   (bars 1-N)
            002.wav   (bars N+1..2N)
            ...
            .manifest_<hash>.json sidecars per chunk
            .manifest.json  (per-stem BatchManifest)
        bass/, vocals/, other/...
        prechop_manifest.json  (top-level summary)

The chunks are byte-equivalent to splitting one big clip at bar boundaries
in Ableton's arrangement view. Drag a stem's folder onto an arrangement
track and Live will place 001/002/... head-to-tail in name order — useful
for testing song-mode export pipelines that consume arrangement-view
clip geometry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .manifest_schema import (
    BatchManifest,
    SampleMeta,
    write_batch,
    write_sidecar,
)


@dataclass
class StemPrechopResult:
    stem_name: str
    output_dir: Path
    chunk_count: int
    chunk_seconds: float
    last_chunk_seconds: float


@dataclass
class PrechopResult:
    track_name: str
    bpm: float
    bars_per_chunk: int
    output_root: Path
    stems: list[StemPrechopResult]


def _read_stems_json(stems_dir: Path) -> dict:
    path = stems_dir / "stems.json"
    if not path.exists():
        raise FileNotFoundError(f"No stems.json in {stems_dir}")
    return json.loads(path.read_text())


def chunk_count_for(total_seconds: float, chunk_seconds: float) -> int:
    """How many chunks fit, including a possibly-shorter final chunk."""
    if total_seconds <= 0:
        return 0
    return int(np.ceil(total_seconds / chunk_seconds))


def prechop_stem(
    stem_name: str,
    stem_wav: Path,
    output_dir: Path,
    *,
    chunk_seconds: float,
    bars_per_chunk: int,
    bpm: float,
    track_name: str,
) -> StemPrechopResult:
    """Slice one stem WAV into chunks at fixed bar boundaries."""
    output_dir.mkdir(parents=True, exist_ok=True)

    info = sf.info(str(stem_wav))
    sr = info.samplerate
    total_frames = info.frames
    chunk_frames = int(round(chunk_seconds * sr))
    if chunk_frames <= 0:
        raise ValueError(f"chunk_frames <= 0 for chunk_seconds={chunk_seconds}, sr={sr}")

    n = chunk_count_for(total_frames / sr, chunk_seconds)
    metas: list[SampleMeta] = []
    last_seconds = chunk_seconds

    for i in range(n):
        start_frame = i * chunk_frames
        end_frame = min(start_frame + chunk_frames, total_frames)
        if end_frame <= start_frame:
            break

        chunk, _ = sf.read(str(stem_wav), start=start_frame, frames=end_frame - start_frame,
                           always_2d=True, dtype="float32")
        out_path = output_dir / f"{i + 1:03d}.wav"
        sf.write(str(out_path), chunk, sr, subtype="FLOAT")

        chunk_dur = (end_frame - start_frame) / sr
        if i == n - 1:
            last_seconds = chunk_dur

        meta = SampleMeta(
            name=f"{track_name[:8]} {stem_name[:3]} {i + 1:03d}"[:16],
            bpm=bpm,
            time_mode="bpm",
            bars=float(bars_per_chunk) if i < n - 1 else (chunk_dur * bpm) / (60.0 * 4),
            playmode="key",
            stem=stem_name if stem_name in {"drums", "bass", "vocals", "other", "full"} else "other",
            role="loop",
            source_track=track_name,
        )
        write_sidecar(out_path, meta)
        # Stamp the file name onto the meta we'll write into the batch
        metas.append(meta.model_copy(update={"file": out_path.name}))

    write_batch(output_dir, BatchManifest(version=1, track=track_name, bpm=bpm, samples=metas))

    return StemPrechopResult(
        stem_name=stem_name,
        output_dir=output_dir,
        chunk_count=n,
        chunk_seconds=chunk_seconds,
        last_chunk_seconds=last_seconds,
    )


def prechop(
    stems_dir: Path,
    *,
    bars_per_chunk: int = 4,
    output: Path | None = None,
    time_signature: int = 4,
) -> PrechopResult:
    """Slice every stem in `stems_dir` (must contain stems.json) into bar-chunks."""
    stems_dir = Path(stems_dir).expanduser()
    data = _read_stems_json(stems_dir)

    bpm = float(data.get("bpm") or 120.0)
    if bpm <= 0:
        raise ValueError(f"Invalid bpm in stems.json: {bpm}")
    track_name = data.get("track_name") or stems_dir.name

    seconds_per_beat = 60.0 / bpm
    chunk_seconds = bars_per_chunk * time_signature * seconds_per_beat

    output_root = (output.expanduser() if output else stems_dir / "prechop").resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    stems_results: list[StemPrechopResult] = []
    for entry in data.get("stems") or []:
        stem_name = entry.get("name")
        wav_path = Path(entry.get("wav_path") or "")
        if not stem_name or not wav_path.exists():
            continue
        stem_out = output_root / stem_name
        result = prechop_stem(
            stem_name, wav_path, stem_out,
            chunk_seconds=chunk_seconds,
            bars_per_chunk=bars_per_chunk,
            bpm=bpm,
            track_name=track_name,
        )
        stems_results.append(result)

    summary = {
        "version": 1,
        "track_name": track_name,
        "bpm": bpm,
        "bars_per_chunk": bars_per_chunk,
        "time_signature": time_signature,
        "chunk_seconds": chunk_seconds,
        "stems": [
            {
                "name": r.stem_name,
                "dir": str(r.output_dir.resolve()),
                "chunk_count": r.chunk_count,
                "last_chunk_seconds": r.last_chunk_seconds,
            }
            for r in stems_results
        ],
    }
    (output_root / "prechop_manifest.json").write_text(json.dumps(summary, indent=2))

    return PrechopResult(
        track_name=track_name, bpm=bpm, bars_per_chunk=bars_per_chunk,
        output_root=output_root, stems=stems_results,
    )
