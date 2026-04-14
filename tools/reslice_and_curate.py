#!/usr/bin/env python3
"""
Re-slice Hot Pants drums into bars (4 beats), analyze, and run Plan A curation.
"""
import sys, shutil
sys.path.insert(0, "/Users/zak/zacharysbrown/stemforge")

import numpy as np
from pathlib import Path
from stemforge.slicer import detect_bpm_and_beats, slice_at_beats
from tools.beat_curator import (
    analyze_all_beats, greedy_diverse_select, composite_distance,
    format_beat_report, export_curated_set,
)

TRACK_DIR = Path.home() / "stemforge/processed/hot_pants_i_m_coming_i_m_coming"
DRUMS_WAV = TRACK_DIR / "drums.wav"
OUTPUT_DIR = Path.home() / "stemforge/curated/hot_pants"

# ── Step 1: Re-slice into bars ──
print("Step 1: Re-slicing drums into 4-beat bars...")

# Clear old beat files
beats_dir = TRACK_DIR / "drums_beats"
if beats_dir.exists():
    shutil.rmtree(beats_dir)
    print(f"  Cleared old {beats_dir}")

# Detect beats
bpm, beat_times = detect_bpm_and_beats(DRUMS_WAV)
print(f"  BPM: {bpm:.2f}")
print(f"  Total beats detected: {len(beat_times)}")
print(f"  Expected bar duration (4/4): {4 * 60.0/bpm:.3f}s")

# Slice at every 4 beats (= 1 bar)
created = slice_at_beats(
    DRUMS_WAV, beat_times, TRACK_DIR, "drums",
    beats_per_slice=4,
    silence_threshold=0.001,
)
print(f"  Created {len(created)} bar-length slices")

# ── Step 2: Verify bar durations ──
print("\nStep 2: Verifying bar durations...")
import soundfile as sf

durations = []
for f in sorted(beats_dir.glob("*.wav")):
    data, sr = sf.read(str(f))
    durations.append(len(data) / sr)

durations = np.array(durations)
bar_dur = 4 * 60.0 / bpm

print(f"  Expected bar: {bar_dur:.3f}s")
print(f"  Actual mean:  {durations.mean():.3f}s")
print(f"  Actual range: {durations.min():.3f}s - {durations.max():.3f}s")
print(f"  Within ±10% of bar: {np.sum((durations > bar_dur*0.9) & (durations < bar_dur*1.1))} / {len(durations)}")

# Show first 10
print("\n  First 10 bars:")
for i, d in enumerate(durations[:10]):
    beats_in = d / (60.0 / bpm)
    print(f"    bar_{i+1:03d}: {d:.3f}s = {beats_in:.2f} beats")

# ── Step 3: Transient timing analysis ──
print("\nStep 3: Transient consistency analysis...")
from tools.beat_curator import analyze_beat

profiles = analyze_all_beats(beats_dir)
active = [p for p in profiles if p.rms > 0.005 and p.onset_count > 0]
print(f"  {len(profiles)} bars total, {len(active)} active")

# Check if we see consistent transient patterns
print("\n  Rhythm fingerprints (first 16 bars):")
for p in active[:16]:
    fp = ''.join(['X' if b else '.' for b in p.rhythm_fingerprint])
    print(f"    bar_{p.index:03d}: [{fp}]  onsets={p.onset_count}  crest={p.crest_factor:.1f}")

unique_patterns = set(p.rhythm_fingerprint for p in active)
print(f"\n  Unique rhythm patterns: {len(unique_patterns)} (from {len(active)} bars)")

# ── Step 4: Run Plan A on bars ──
print("\n" + "="*60)
print("  PLAN A (BARS): Maximum Diversity")
print("="*60)

plan_a = greedy_diverse_select(active, n=14, dist_fn=composite_distance)
plan_a.sort(key=lambda p: p.index)

report = format_beat_report(plan_a, "Plan A (Bars) — Maximum Diversity")
print(report)

# Clear old curated output
old_plan_a = OUTPUT_DIR / "plan_a_max_diversity"
if old_plan_a.exists():
    shutil.rmtree(old_plan_a)

out = export_curated_set(plan_a, OUTPUT_DIR, "plan_a_bars_max_diversity")
print(f"  Exported to: {out}")

# ── Stats ──
print("\n  STATS:")
patterns = len(set(p.rhythm_fingerprint for p in plan_a))
avg_crest = np.mean([p.crest_factor for p in plan_a])
print(f"  - {len(plan_a)} bars selected, {patterns} unique patterns")
print(f"  - Avg crest: {avg_crest:.1f}")
print(f"  - Each bar ≈ {bar_dur:.2f}s = perfect for break loops")
print(f"  - Output: {out}")
print("\nDone!")
