#!/usr/bin/env python3
"""extract_loop_test.py — Cut a single mid-song 4-bar loop from a forged
track and save as WAV. Tells the user immediately whether the manifest's
BPM + first_downbeat are correct: drag the resulting WAV into Ableton with
loop on, and if it loops seamlessly + the first kick lands on bar 1, the
detection is right.

Pulls the loop directly from the SOURCE mix at the chunk's `source_offset_sec`
so we test the actual prechop math (BPM + first_downbeat), not the chunk WAV
extraction itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import soundfile as sf


def extract(track_dir: Path, source_mix: Path, chunk_index: int, out_path: Path) -> None:
    pm = json.loads((track_dir / "prechop_manifest.json").read_text())
    bpm = pm["bpm"]
    bars = pm["bars"]
    beats_per_bar = pm["beats_per_bar"]
    chunks = pm["stems"]["drums"]["chunks"]

    if chunk_index < 1 or chunk_index > len(chunks):
        print(f"  chunk {chunk_index} out of range (1..{len(chunks)})")
        return

    chunk = chunks[chunk_index - 1]
    source_offset_sec = chunk["source_offset_sec"]
    loop_duration_sec = bars * beats_per_bar * 60.0 / bpm

    # Read source mix
    y, sr = sf.read(str(source_mix), always_2d=True)
    start_frame = int(round(source_offset_sec * sr))
    end_frame = start_frame + int(round(loop_duration_sec * sr))
    end_frame = min(end_frame, y.shape[0])

    loop = y[start_frame:end_frame, :]
    sf.write(str(out_path), loop, sr, subtype="PCM_24")

    print(f"  {track_dir.name} chunk {chunk_index}/{len(chunks)}:")
    print(f"    BPM:                {bpm:.4f}")
    print(f"    source_offset_sec:  {source_offset_sec:.4f}")
    print(f"    loop duration:      {loop_duration_sec:.4f}s ({bars} bars × {beats_per_bar} beats)")
    print(f"    frames extracted:   {loop.shape[0]} @ {sr} Hz = {loop.shape[0] / sr:.4f}s")
    print(f"    written to:         {out_path}")


def main() -> int:
    out_dir = Path.home() / "stemforge/processed/UPDATE/loop_tests"
    out_dir.mkdir(parents=True, exist_ok=True)

    tracks = [
        # (track_dir, source_mix, mid_chunk_index)
        (
            Path.home() / "stemforge/processed/UPDATE/definition_test",
            Path.home() / "Downloads/03 - Definition [Explicit].wav",
            10,  # middle of 20 chunks
        ),
        (
            Path.home() / "stemforge/processed/UPDATE/ooh_la_la_test",
            Path.home() / "Downloads/02 - ooh la la (feat. Greg Nice & DJ Premier) [Explicit].wav",
            8,  # middle of 17 chunks
        ),
    ]

    print(f"Writing 4-bar mid-song loops to {out_dir}/\n")

    for track_dir, source_mix, idx in tracks:
        if not source_mix.exists():
            print(f"  skip {track_dir.name}: source missing at {source_mix}")
            continue
        if not track_dir.exists():
            print(f"  skip {track_dir.name}: missing at {track_dir}")
            continue

        out = out_dir / f"{track_dir.name}_loop_chunk_{idx}.wav"
        extract(track_dir, source_mix, idx, out)
        print()

    print("Test instructions:")
    print(f"  1. Drag any .wav from {out_dir}/ into Ableton")
    print("  2. Enable looping on the clip")
    print("  3. Set project tempo to the BPM printed above")
    print("  4. If the loop has a clean seam (no gap or stutter) AND the first kick")
    print("     lands on bar 1, the manifest's BPM + first_downbeat are correct.")
    print("     If it drifts or the kick is offset, BPM and/or first_downbeat are off.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
