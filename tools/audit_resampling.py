#!/usr/bin/env python3
"""audit_resampling.py — Verify a forged track's WAV files match the
metadata claims in stems.json and prechop_manifest.json. Catches silent
resampling between the input audio and the chunked output.

The manifest enrichment in cli.py / manifest.py records:
  - input_audio.sample_rate / duration_samples / sha256 (input fingerprint)
  - prechop_manifest chunks[].chunk_duration_samples / sample_rate
    (output fingerprint per chunk)

This audit reads each WAV's actual metadata (via soundfile.info) and
compares against the recorded values. Any mismatch is a bug — either the
manifest is lying, or something between the recorded value and the file
on disk silently resampled. Either way, you want to know.

Usage:
    uv run python tools/audit_resampling.py <track_dir>
    uv run python tools/audit_resampling.py ~/stemforge/processed/UPDATE/definition_test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import soundfile as sf


def audit_track(track_dir: Path) -> int:
    failures = 0

    stems_json = track_dir / "stems.json"
    if not stems_json.exists():
        print(f"FATAL: no stems.json at {stems_json}")
        return 1
    sj = json.loads(stems_json.read_text())

    print(f"\n=== {track_dir.name} ===")

    # Input audio fingerprint
    if sj.get("input_audio"):
        ia = sj["input_audio"]
        src = Path(sj["source_file"])
        if src.exists():
            info = sf.info(str(src))
            ok_sr = info.samplerate == ia["sample_rate"]
            ok_dur = info.frames == ia["duration_samples"]
            print(
                f"  input_audio: sr={info.samplerate} (manifest: {ia['sample_rate']}) "
                f"{'OK' if ok_sr else 'MISMATCH'}; "
                f"frames={info.frames} (manifest: {ia['duration_samples']}) "
                f"{'OK' if ok_dur else 'MISMATCH'}"
            )
            if not (ok_sr and ok_dur):
                failures += 1
        else:
            print(f"  [warn] source_file {src} not on disk; cannot verify input_audio")
    else:
        print("  [warn] no input_audio block in stems.json (older forge?)")

    # Stem WAVs — compare sample rate against input
    for s in sj.get("stems", []):
        wav = Path(s["wav_path"])
        if not wav.exists():
            print(f"  [warn] missing stem {s['name']}: {wav}")
            continue
        info = sf.info(str(wav))
        # Stems should match input sample rate (Demucs preserves it)
        expected_sr = (sj.get("input_audio") or {}).get("sample_rate", info.samplerate)
        ok = info.samplerate == expected_sr
        print(
            f"  stem {s['name']}: sr={info.samplerate} (expected: {expected_sr}) "
            f"{'OK' if ok else 'MISMATCH'}"
        )
        if not ok:
            failures += 1

    # Prechop chunks — full sample-accurate audit
    pm_path = track_dir / "prechop_manifest.json"
    if pm_path.exists():
        pm = json.loads(pm_path.read_text())
        bad_chunks = 0
        total_chunks = 0
        for stem_name, sb in pm.get("stems", {}).items():
            for chunk in sb.get("chunks", []):
                total_chunks += 1
                wav = track_dir / chunk["file"]
                if not wav.exists():
                    bad_chunks += 1
                    print(f"  [missing] {chunk['file']}")
                    continue
                info = sf.info(str(wav))
                claimed_samples = chunk.get("chunk_duration_samples")
                claimed_sr = chunk.get("sample_rate")
                if claimed_samples is not None and info.frames != claimed_samples:
                    bad_chunks += 1
                    print(
                        f"  [mismatch] {chunk['file']}: frames={info.frames} "
                        f"vs manifest {claimed_samples}"
                    )
                if claimed_sr is not None and info.samplerate != claimed_sr:
                    bad_chunks += 1
                    print(
                        f"  [mismatch] {chunk['file']}: sr={info.samplerate} "
                        f"vs manifest {claimed_sr}"
                    )
        print(f"  prechop chunks: {total_chunks} total, {bad_chunks} mismatched")
        failures += bad_chunks
    else:
        print("  [warn] no prechop_manifest.json")

    print(f"  {'PASS' if failures == 0 else f'{failures} FAILURES'}")
    return 0 if failures == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("track_dir", type=Path)
    args = p.parse_args()
    return audit_track(args.track_dir)


if __name__ == "__main__":
    sys.exit(main())
