#!/usr/bin/env python3
"""m4l_locator_anchor — re-anchor a forged track from a user-placed locator.

Invoked from `sf_locator_anchor.js` (the M4L device) via `[shell]`. The JS
back-computes the source-time the locator points at (using the loaded
prechop_manifest.json), then shells here with the values to re-cut.

Args mirror what the JS emits on outlet 1:

    --track-dir   <abs path to processed/<track>/>
    --bpm         <float, BPM the user wants the track anchored at>
    --first-downbeat <float, source-time of bar 1, in seconds>
    --manifest-out   <abs path to prechop_manifest.json — passed back in
                      `anchor_complete` so the JS can hand it to
                      sf_arrangement_loader.runArrangementLoad()>

The actual re-cut goes through `stemforge re-anchor`, which skips Demucs
re-run (Demucs output already on disk). Round-trip is ~1-2s.

Emits NDJSON on stdout that the patcher's [route] forwards to:
    anchor_started        → onAnchorStarted (no payload)
    anchor_complete       → onAnchorComplete <manifest_path>
    anchor_error          → onAnchorError <message>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _emit(event: str, **data) -> None:
    print(json.dumps({"event": event, **data}), flush=True)


def _run_re_anchor(track_dir: Path, bpm: float, first_downbeat: float) -> None:
    """Invoke `stemforge re-anchor` as a subprocess.

    Why subprocess: keeps `tools/` decoupled from CLI internals, and matches
    what the user runs by hand from the terminal. Adds ~150 ms of Python
    startup but the human-side of this loop is dragging an Ableton locator,
    so we don't care.
    """
    # `python -m stemforge.cli` — works from any cwd that has the repo on
    # sys.path. Avoids depending on the `stemforge` console script being
    # on the user's PATH inside Max's shell environment.
    cmd = [
        sys.executable,
        "-m",
        "stemforge.cli",
        "re-anchor",
        str(track_dir),
        "--bpm",
        f"{bpm:.6f}",
        "--first-downbeat",
        f"{first_downbeat:.6f}",
    ]
    proc = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "re-anchor failed").strip().splitlines()
        tail = " | ".join(msg[-3:]) if msg else "re-anchor failed"
        raise RuntimeError(f"stemforge re-anchor exited {proc.returncode}: {tail}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--track-dir", required=True, type=Path)
    ap.add_argument("--bpm", required=True, type=float)
    ap.add_argument("--first-downbeat", required=True, type=float)
    ap.add_argument(
        "--manifest-out",
        required=True,
        type=Path,
        help="Path the JS will reload after success (typically <track-dir>/prechop_manifest.json).",
    )
    args = ap.parse_args(argv)

    if not args.track_dir.exists():
        _emit("anchor_error", message=f"track dir not found: {args.track_dir}")
        return 2
    if args.bpm <= 0:
        _emit("anchor_error", message=f"bpm must be > 0, got {args.bpm}")
        return 2
    if args.first_downbeat < 0:
        _emit("anchor_error", message=f"first-downbeat must be >= 0, got {args.first_downbeat}")
        return 2

    _emit(
        "anchor_started",
        track_dir=str(args.track_dir),
        bpm=args.bpm,
        first_downbeat=args.first_downbeat,
    )

    try:
        _run_re_anchor(args.track_dir, args.bpm, args.first_downbeat)
    except Exception as e:
        _emit("anchor_error", message=str(e))
        return 2

    if not args.manifest_out.exists():
        _emit("anchor_error", message=f"re-anchor finished but manifest not at {args.manifest_out}")
        return 2

    _emit(
        "anchor_complete",
        manifest=str(args.manifest_out),
        bpm=args.bpm,
        first_downbeat=args.first_downbeat,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
