#!/usr/bin/env python3
"""m4l_export_clips — bounce Ableton clips listed in a spec.json into sidecars.

Invoked from `sf_clip_export.js` (the M4L device) via `[shell]`. Reads a JSON
spec describing each clip the user wants exported, slices the source audio for
each, and writes per-clip `.manifest_<hash>.json` sidecars + a directory-level
`.manifest.json` BatchManifest using `stemforge.manifest_schema`.

Spec format (written by sf_clip_export.js):

    {
      "version": 1,
      "project_tempo": 120.0,
      "oneshot_bars_threshold": 0.5,
      "export_dir": "/abs/path/to/exports/<timestamp>",
      "clips": [
        {
          "track_idx": 2,
          "slot_idx": 0,
          "name": "Kick Loop",
          "file_path": "/abs/path/to/source.wav",
          "warping": true,
          "length_beats": 16.0,
          "loop_start_beats": 0.0,
          "loop_end_beats": 16.0,
          "signature_numerator": 4,
          "clip_warp_bpm": 120.0,
          "gain": 0.0,
          "suggested_group": "A",
          "suggested_pad": "."
        },
        ...
      ]
    }

Output (per spec.export_dir):
  - `<group><slot>.wav`        — bounced clip audio (e.g. A01.wav, A02.wav, ...)
  - `.manifest_<hash>.json`    — per-file sidecar
  - `.manifest.json`           — directory-level BatchManifest

V1 LIMITATION: warped clips are bounced from the SOURCE audio (no warp baking).
True freeze-and-export is V2. We trim to the active loop region only.

Emits NDJSON events on stdout when --json-events is set, so the M4L device
can route them back to sf_clip_export's onProgress/onClipDone/onExportComplete
handlers via stemforge_ndjson_parser.v0.js.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

# Path-juggle so this script can run as a standalone (not via uv) — the M4L
# device just calls `python3 tools/m4l_export_clips.py spec.json` and we want
# `import stemforge.manifest_schema` to work from a clean checkout.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from stemforge.manifest_schema import (  # noqa: E402
    BatchManifest,
    SampleMeta,
    display_name,
    write_batch,
    write_sidecar,
)


def _emit(events: bool, event: str, **data) -> None:
    if not events:
        return
    payload = {"event": event, **data}
    print(json.dumps(payload), flush=True)


def beats_to_seconds(beats: float, tempo_bpm: float) -> float:
    return beats * 60.0 / tempo_bpm


def slice_clip(
    source_path: Path,
    out_path: Path,
    *,
    start_seconds: float,
    end_seconds: float,
    gain_db: float = 0.0,
) -> tuple[float, int]:
    """Read `[start..end]` seconds of `source_path`, apply gain, write to `out_path`.

    Wraps around the source's length when the requested window extends past
    the end. This matches Ableton's loop semantics: a clip with
    `loop_start = 8`, `loop_end = 24`, `length = 16` plays beats 8..16 of
    source, then wraps to beats 0..8 — so the bounced WAV is the second
    half of the source followed by the first half (the "rotation" the user
    set by moving the loop_start marker). Without this wrap the EP-133 only
    gets half the loop.

    Returns (duration_seconds, sample_rate).
    """
    info = sf.info(str(source_path))
    sr = info.samplerate
    source_frames = info.frames
    if source_frames <= 0:
        raise ValueError(f"empty source: {source_path}")

    requested_frames = int(round((end_seconds - start_seconds) * sr))
    if requested_frames <= 0:
        raise ValueError(
            f"empty slice: start={start_seconds:.3f}s end={end_seconds:.3f}s"
        )

    # Normalize start into the source's [0, source_frames) range — Live can
    # set loop_start beyond the source if the user moved the marker into the
    # repeated tail.
    start_frame = int(round(start_seconds * sr)) % source_frames

    # Read in chunks, wrapping at source end. Handles arbitrary loop lengths
    # including loops that span multiple source repetitions.
    chunks: list[np.ndarray] = []
    position = start_frame
    remaining = requested_frames
    while remaining > 0:
        available = source_frames - position
        n = min(available, remaining)
        chunk, _ = sf.read(str(source_path), start=position, frames=n,
                           always_2d=True, dtype="float32")
        chunks.append(chunk)
        remaining -= n
        position = 0  # subsequent passes always start at sample 0

    audio = chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)

    if gain_db != 0.0:
        gain_linear = 10.0 ** (gain_db / 20.0)
        audio = audio * gain_linear

    sf.write(str(out_path), audio, sr, subtype="FLOAT")
    return requested_frames / sr, sr


def determine_playmode(bars: float, threshold: float) -> str:
    return "oneshot" if bars < threshold else "key"


def build_meta_for_clip(
    clip: dict,
    *,
    project_tempo: float,
    out_filename: str,
    duration_seconds: float,
    threshold: float,
) -> SampleMeta:
    """Build the SampleMeta for one bounced clip.

    The producer fills everything resolved — `suggested_pad`, `suggested_group`,
    `playmode`, `bpm`, `time_mode` — so the consumer just places.
    """
    sig_num = float(clip.get("signature_numerator") or 4)
    # Bars reflects the BOUNCED audio length, which is the loop region
    # (loop_end - loop_start), not the source length. They diverge when
    # the user has moved the loop_start marker so the loop wraps around
    # the source — the bounce is a rotated full-loop, not a chopped slice.
    loop_start = float(clip.get("loop_start_beats") or 0.0)
    loop_end = float(clip.get("loop_end_beats") or 0.0)
    loop_length_beats = max(0.0, loop_end - loop_start)
    if loop_length_beats <= 0.0:
        loop_length_beats = float(clip.get("length_beats") or 0.0)
    bars = loop_length_beats / sig_num if sig_num else 0.0

    # Source BPM: prefer the clip's warp BPM if warped, else project tempo.
    src_bpm = clip.get("clip_warp_bpm") or project_tempo

    playmode = determine_playmode(bars, threshold)
    role = "one_shot" if playmode == "oneshot" else "loop"

    raw_name = clip.get("name") or Path(out_filename).stem
    name = display_name(raw_name)

    # `time_mode = bpm` only makes sense for stretchable loops; one-shots run
    # at native sample rate (skip time_mode so the device defaults to "off").
    time_mode = "bpm" if playmode == "key" and src_bpm else None

    return SampleMeta(
        name=name,
        bpm=float(src_bpm) if time_mode else None,
        time_mode=time_mode,
        bars=bars if bars > 0 else None,
        playmode=playmode,
        source_track=str(clip.get("track_idx", "")) or None,
        role=role,
        suggested_group=clip.get("suggested_group"),
        suggested_pad=clip.get("suggested_pad"),
    )


def slice_and_write_one(
    clip: dict,
    *,
    export_dir: Path,
    project_tempo: float,
    threshold: float,
) -> tuple[Path, SampleMeta]:
    """Slice one clip, write the WAV + sidecar. Returns (wav_path, meta)."""
    source_path = Path(clip["file_path"])
    if not source_path.exists():
        raise FileNotFoundError(f"clip source not found: {source_path}")

    # Tempo for the beats→seconds conversion: warped clips advance their
    # internal beat-clock at clip_warp_bpm; un-warped clips use the source
    # sample's natural tempo (we treat it as project_tempo as a best guess).
    src_bpm = clip.get("clip_warp_bpm") or project_tempo

    start_seconds = beats_to_seconds(float(clip["loop_start_beats"]), src_bpm)
    end_seconds = beats_to_seconds(float(clip["loop_end_beats"]), src_bpm)

    group = clip.get("suggested_group") or "X"
    slot = int(clip.get("slot_idx", 0))
    out_filename = f"{group}{slot:02d}.wav"
    out_path = export_dir / out_filename

    duration, _sr = slice_clip(
        source_path, out_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        gain_db=float(clip.get("gain") or 0.0),
    )

    meta = build_meta_for_clip(
        clip,
        project_tempo=project_tempo,
        out_filename=out_filename,
        duration_seconds=duration,
        threshold=threshold,
    )

    write_sidecar(out_path, meta)
    return out_path, meta


_STALE_OUTPUT_GLOBS = (
    ".manifest.json",     # batch manifest
    ".manifest_*.json",   # per-WAV sidecars (filename uses content hash)
    "[ABCD][0-9][0-9].wav",  # bounced WAVs (e.g. A00.wav, D11.wav)
)


def wipe_stale_outputs(export_dir: Path) -> int:
    """Remove prior bounce outputs from `export_dir` before writing new ones.

    Re-bouncing the same Live arrangement leaves orphan files behind:
      - Sidecar filenames embed the content hash, so changed audio writes
        a NEW sidecar without overwriting the old one.
      - If the user removed a clip slot between bounces, the prior WAV
        for that slot stays on disk forever.

    Glob is conservative — only removes files matching the producer's own
    output patterns. Anything else in the dir (user notes, etc.) is left.
    Returns the number of files removed.
    """
    removed = 0
    for pattern in _STALE_OUTPUT_GLOBS:
        for p in export_dir.glob(pattern):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def run(spec_path: Path, *, json_events: bool = False) -> Path:
    """Process spec.json end-to-end. Returns the BatchManifest path."""
    spec = json.loads(spec_path.read_text())

    export_dir = Path(spec["export_dir"]).expanduser()
    export_dir.mkdir(parents=True, exist_ok=True)
    wiped = wipe_stale_outputs(export_dir)
    if wiped:
        _emit(json_events, "export_wiped", count=wiped, dir=str(export_dir))

    project_tempo = float(spec.get("project_tempo") or 120.0)
    threshold = float(spec.get("oneshot_bars_threshold") or 0.5)
    clips = spec.get("clips") or []

    _emit(json_events, "export_started", clips=len(clips), export_dir=str(export_dir))

    samples: list[SampleMeta] = []
    for i, clip in enumerate(clips, start=1):
        _emit(json_events, "export_progress", n=i, of=len(clips))
        try:
            wav_path, meta = slice_and_write_one(
                clip,
                export_dir=export_dir,
                project_tempo=project_tempo,
                threshold=threshold,
            )
        except Exception as e:
            _emit(json_events, "export_clip_error", n=i, of=len(clips), message=str(e))
            print(f"  ✗ clip {i}/{len(clips)}: {e}", file=sys.stderr)
            continue

        # Batch entry uses the path relative to export_dir (the manifest dir)
        samples.append(meta.model_copy(update={"file": wav_path.name}))
        _emit(json_events, "export_clip_done", n=i, of=len(clips), file=wav_path.name)

    batch = BatchManifest(
        version=1,
        track=spec.get("track"),
        bpm=project_tempo,
        samples=samples,
    )
    batch_path = write_batch(export_dir, batch)

    _emit(json_events, "export_complete", batch_manifest=str(batch_path), clips=len(samples))
    return batch_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", type=Path, help="Path to spec.json written by sf_clip_export.js")
    ap.add_argument("--json-events", action="store_true",
                    help="Emit NDJSON progress events on stdout for the M4L parser")
    args = ap.parse_args(argv)

    if not args.spec.exists():
        ap.error(f"spec not found: {args.spec}")

    try:
        out = run(args.spec, json_events=args.json_events)
    except Exception as e:
        _emit(args.json_events, "export_error", message=str(e))
        print(f"  ✗ FATAL: {e}", file=sys.stderr)
        return 2

    if not args.json_events:
        print(f"  ✓ Done. Batch manifest at {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
