#!/usr/bin/env python3
"""find_main_beat_drop.py — Auto-detect where a song's main beat actually
drops, by finding the first SUSTAINED cluster of high-strength kick onsets.

Pattern empirically observed on Black Star "Definition" + Greg Nice
"Ooh La La" — both have ~22 seconds of intro material (DJ scratching,
sparse hits) before the actual main beat drops with a sustained run of
strong kicks. Auto-detection on beat-this-detected downbeats falls onto
A bar grid that includes the intro, but only a HUMAN can tell which bar
of the grid is musically bar 1.

This tool replaces the human eyeballing with a heuristic: find the first
absolute kick onset whose strength is in the top quintile AND is followed
by another strong onset within 1 bar. That's the main beat drop.

Usage:
    uv run python tools/find_main_beat_drop.py SONG.wav --bpm 85.11
    uv run python tools/find_main_beat_drop.py TRACK_DIR --bpm 85.11
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def detect_strong_kicks(
    audio_path: Path, *, threshold_quantile: float = 0.80
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return (onset_times, strengths, threshold) — only onsets at or above
    the given strength quantile of all detected onsets in the song."""
    import librosa

    target = audio_path
    if audio_path.is_dir():
        target = audio_path / "drums.wav"

    y, sr = librosa.load(str(target), sr=None, mono=True)
    onset_multi = librosa.onset.onset_strength_multi(
        y=y, sr=sr, channels=[0, 32, 64, 96, 128]
    )
    kick_env = onset_multi[0]
    times = librosa.frames_to_time(
        np.arange(len(kick_env)), sr=sr, hop_length=512
    )

    peaks = librosa.util.peak_pick(
        kick_env, pre_max=3, post_max=3, pre_avg=3, post_avg=5, delta=0.5, wait=10
    )
    peak_strengths = kick_env[peaks]
    peak_times = times[peaks]

    # Filter to top quantile — these are the song's strongest hits.
    threshold = float(np.quantile(peak_strengths, threshold_quantile))
    strong = peak_strengths >= threshold
    return peak_times[strong], peak_strengths[strong], threshold


def find_main_beat_drop(
    onset_times: np.ndarray,
    strengths: np.ndarray,
    bar_period: float,
    *,
    min_cluster_size: int = 3,
) -> float | None:
    """Find the first onset that's part of a sustained cluster.

    A cluster = `min_cluster_size` consecutive strong onsets where each pair
    is within 1 bar of each other. Returns the time of the FIRST onset in
    that cluster — the song's main beat drop.
    """
    if len(onset_times) < min_cluster_size:
        return None

    # Walk through onsets; a "cluster start" is the first index where the
    # next `min_cluster_size - 1` strong onsets all land within 1 bar.
    for i in range(len(onset_times) - min_cluster_size + 1):
        # Window of cluster_size strong onsets starting at i.
        window_times = onset_times[i : i + min_cluster_size]
        # All consecutive gaps within 1 bar?
        gaps = np.diff(window_times)
        if np.all(gaps < bar_period):
            return float(window_times[0])
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("--bpm", type=float, required=True)
    p.add_argument(
        "--quantile",
        type=float,
        default=0.80,
        help="Strength quantile threshold (default 0.80 = top 20%%)",
    )
    p.add_argument(
        "--cluster-size",
        type=int,
        default=3,
        help="Minimum consecutive strong onsets to call a cluster (default 3)",
    )
    args = p.parse_args()

    if not args.source.exists():
        print(f"FATAL: {args.source} not found")
        return 1

    bar_period = 60.0 * 4 / args.bpm
    onset_times, strengths, threshold = detect_strong_kicks(
        args.source, threshold_quantile=args.quantile
    )
    print(f"Bar period: {bar_period:.4f}s @ {args.bpm} BPM")
    print(
        f"Strong-onset threshold: {threshold:.2f} (top {(1-args.quantile)*100:.0f}%)"
    )
    print(f"Detected {len(onset_times)} strong onsets")
    print()

    main_drop = find_main_beat_drop(
        onset_times, strengths, bar_period, min_cluster_size=args.cluster_size
    )

    if main_drop is None:
        print("Could not find a sustained kick cluster.")
        return 1

    # Show context — strong onsets near the recommendation
    print(f"Main beat drop detected at: [bold]{main_drop:.4f}s[/bold]")
    print()
    print("Context (strong onsets near recommendation):")
    near_idx = np.searchsorted(onset_times, main_drop)
    for j in range(max(0, near_idx - 2), min(len(onset_times), near_idx + 8)):
        marker = " <-- recommended bar 1" if j == near_idx else ""
        print(f"  {onset_times[j]:.4f}s  strength={strengths[j]:6.2f}{marker}")

    print()
    print(f"Recommended: --first-downbeat {main_drop:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
