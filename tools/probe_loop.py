#!/usr/bin/env python3
"""probe_loop.py — Extract a 4-bar loop from the source mix at user-specified
BPM + first_downbeat. For iterating tempo/downbeat values quickly without
re-running Demucs.

Workflow when auto-detection is wrong:
  1. Run with default bpm/downbeat → drag .wav into Ableton → see how it lines up
  2. Adjust bpm or first_downbeat → re-run → check again
  3. When the loop is seamless AND the kick is on bar 1, those are your values
  4. Use them in `stemforge split --bpm X --first-downbeat Y ...`

Usage:
    uv run python tools/probe_loop.py <source_wav> --bpm 85.11 --first-downbeat 0.5
    uv run python tools/probe_loop.py <source_wav> --bpm 85.11 --first-downbeat 0.5 \\
        --start-bar 28 --bars 4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import soundfile as sf


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path, help="Source mix WAV")
    p.add_argument("--bpm", type=float, required=True, help="Tempo in BPM")
    p.add_argument(
        "--first-downbeat", type=float, default=0.0,
        help="Seconds from start of file to musical bar 1 (default 0)"
    )
    p.add_argument(
        "--start-bar", type=int, default=1,
        help="Which musical bar to start the loop on (1-indexed, default 1)"
    )
    p.add_argument(
        "--bars", type=int, default=4,
        help="Loop length in bars (default 4)"
    )
    p.add_argument(
        "--beats-per-bar", type=int, default=4,
        help="4 for 4/4 (default), 3 for 3/4, etc."
    )
    p.add_argument(
        "--out", type=Path, default=None,
        help="Output WAV path (default: ./probe_<bpm>_<downbeat>_<bar>.wav)"
    )
    args = p.parse_args()

    if not args.source.exists():
        print(f"FATAL: {args.source} not found")
        return 1

    seconds_per_beat = 60.0 / args.bpm
    seconds_per_bar = seconds_per_beat * args.beats_per_bar
    bar_offset_sec = args.first_downbeat + (args.start_bar - 1) * seconds_per_bar
    loop_duration_sec = args.bars * seconds_per_bar

    y, sr = sf.read(str(args.source), always_2d=True)
    start_frame = int(round(bar_offset_sec * sr))
    end_frame = start_frame + int(round(loop_duration_sec * sr))
    end_frame = min(end_frame, y.shape[0])

    if start_frame >= y.shape[0]:
        print(f"FATAL: bar_offset_sec={bar_offset_sec:.4f}s past end of audio")
        return 1

    loop = y[start_frame:end_frame, :]

    out = args.out or Path(
        f"probe_bpm{args.bpm:.3f}_dn{args.first_downbeat:.3f}_bar{args.start_bar}.wav"
    )
    sf.write(str(out), loop, sr, subtype="PCM_24")

    print(f"Source:           {args.source}")
    print(f"BPM:              {args.bpm}")
    print(f"first_downbeat:   {args.first_downbeat}s")
    print(f"start_bar:        {args.start_bar} ({args.bars} bars × {args.beats_per_bar} beats)")
    print(f"computed offset:  {bar_offset_sec:.4f}s in source")
    print(f"loop duration:    {loop_duration_sec:.4f}s")
    print(f"frames extracted: {loop.shape[0]} @ {sr} Hz = {loop.shape[0]/sr:.4f}s")
    print(f"Wrote:            {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
