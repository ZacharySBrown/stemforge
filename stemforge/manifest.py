"""
stems.json schema — written by CLI, read by M4L device.
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StemInfo:
    name: str  # e.g. "drums"
    wav_path: str  # absolute path to full stem WAV
    beats_dir: str  # absolute path to beat slices folder
    beat_count: int  # number of beat slice files written


@dataclass
class TempoProvenance:
    """Where the BPM came from + every estimate that ran. Lets future detector
    work treat each manual override or low-confidence reading as a labeled
    example without re-running the pipeline."""

    source: str  # e.g. "beat-this:mix", "librosa:drums", "user-override"
    confidence: str  # high | medium | low
    first_downbeat_sec: float | None = None
    n_downbeats: int = 0
    warning: str | None = None
    all_estimates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class InputAudio:
    """Sample-accurate fingerprint of the input file. Catches silent resamples
    by recording exact frame count + sample rate; the sha256 lets future code
    detect when the source file changed under us."""

    sample_rate: int
    duration_samples: int
    sha256: str  # full sha256, lowercase hex


@dataclass
class StemManifest:
    track_name: str
    source_file: str
    backend: str
    bpm: float
    beat_count: int
    stems: list[StemInfo]
    output_dir: str
    pipeline: str
    processed_at: str
    tempo: TempoProvenance | None = None
    input_audio: InputAudio | None = None


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _input_audio_for(path: Path) -> InputAudio | None:
    try:
        import soundfile as sf

        info = sf.info(str(path))
        return InputAudio(
            sample_rate=int(info.samplerate),
            duration_samples=int(info.frames),
            sha256=_compute_sha256(path),
        )
    except Exception:
        return None


def write_manifest(
    output_dir: Path,
    track_name: str,
    source_file: Path,
    backend: str,
    bpm: float,
    beat_count: int,
    stem_paths: dict[str, Path],
    slice_counts: dict[str, int],
    pipeline: str = "default",
    tempo: TempoProvenance | None = None,
    input_audio: InputAudio | None = None,
) -> Path:
    stems = []
    for stem_name, stem_path in stem_paths.items():
        beats_dir = output_dir / f"{stem_name}_beats"
        stems.append(
            StemInfo(
                name=stem_name,
                wav_path=str(stem_path.resolve()),
                beats_dir=str(beats_dir.resolve()),
                beat_count=slice_counts.get(stem_name, 0),
            )
        )

    if input_audio is None:
        input_audio = _input_audio_for(source_file)

    manifest = StemManifest(
        track_name=track_name,
        source_file=str(source_file.resolve()),
        backend=backend,
        bpm=round(bpm, 2),
        beat_count=beat_count,
        stems=stems,
        output_dir=str(output_dir.resolve()),
        pipeline=pipeline,
        processed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        tempo=tempo,
        input_audio=input_audio,
    )

    path = output_dir / "stems.json"
    path.write_text(json.dumps(asdict(manifest), indent=2))

    # Update index.json in the parent (processed/) dir for M4L device discovery
    update_index(output_dir.parent, track_name)

    return path


def update_index(processed_dir: Path, track_name: str):
    """Maintain index.json — a list of track names for M4L device discovery."""
    index_path = processed_dir / "index.json"
    if index_path.exists():
        try:
            entries = json.loads(index_path.read_text())
        except (json.JSONDecodeError, ValueError):
            entries = []
    else:
        entries = []
    if track_name not in entries:
        entries.append(track_name)
    index_path.write_text(json.dumps(entries, indent=2))


def read_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text())
