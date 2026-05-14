#!/usr/bin/env python3
"""find_first_drum_cut.py — Score each candidate first_downbeat by checking
whether (a) there's a kick onset AT it, and (b) subsequent bars at the same
phase also have kicks. Skips the manual A/B-in-Ableton step.

The score for a candidate `first_downbeat` is:
    sum of kick onset strengths at positions {first_downbeat + n × bar_period
    for n in [0, 1, ..., N]}

The candidate that lands on the song's actual main-beat downbeat will score
highest because it taps into a sustained rhythmic pattern. Pre-beat
candidates (e.g. before the drums drop) will score lower because subsequent
"bars" don't have kicks aligned.

Uses LarsNet-isolated kick when available (cleanest kick stem). Falls back
to lowpass <120Hz on the drums stem.

Usage:
    uv run python tools/find_first_drum_cut.py SOURCE.wav --bpm 85.11 \\
        --candidates 0.1 2.92 5.74 8.56 11.38
    uv run python tools/find_first_drum_cut.py TRACK_DIR --bpm 85.11 \\
        --candidates 0.1 2.92 5.74 8.56 11.38
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def get_kick_onset_envelope(audio_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (kick_onset_envelope, onset_times_sec). Tries LarsNet kick
    isolation first; falls back to kick-band onset_strength_multi."""
    import librosa

    # If audio_path is a track_dir, look for LarsNet substems
    if audio_path.is_dir():
        # Look for an existing kick stem from a previous LarsNet run, OR
        # run LarsNet on this dir's drums.wav.
        kick_path = audio_path / "tempo_substems" / "kick.wav"
        if not kick_path.exists():
            drums = audio_path / "drums.wav"
            if drums.exists():
                from stemforge.drum_separator import is_available, separate_drums

                if is_available():
                    kick_path = separate_drums(drums, audio_path / "find_drum_cut_substems").get(
                        "kick"
                    )
        if kick_path and kick_path.exists():
            y, sr = librosa.load(str(kick_path), sr=None, mono=True)
            onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
            onset_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr, hop_length=512)
            return onset_env, onset_times

    # Fallback path — kick-band onset on the audio file itself
    target = audio_path
    if audio_path.is_dir():
        target = audio_path / "drums.wav"
    y, sr = librosa.load(str(target), sr=None, mono=True)
    onset_multi = librosa.onset.onset_strength_multi(y=y, sr=sr, channels=[0, 32, 64, 96, 128])
    kick_onset = onset_multi[0]
    onset_times = librosa.frames_to_time(np.arange(len(kick_onset)), sr=sr, hop_length=512)
    return kick_onset, onset_times


def score_candidate(
    onset_env: np.ndarray,
    onset_times: np.ndarray,
    first_downbeat: float,
    bar_period: float,
    n_bars: int = 16,
) -> tuple[float, list[float]]:
    """Sum kick onset strength at each of the n_bars bar-1 positions starting
    from first_downbeat. Returns (total_score, per_bar_strengths)."""
    duration = float(onset_times[-1])
    strengths: list[float] = []
    for i in range(n_bars):
        t = first_downbeat + i * bar_period
        if t >= duration:
            break
        idx = min(int(np.searchsorted(onset_times, t)), len(onset_env) - 1)
        # Look ±20ms for the local peak (kick onset isn't always sample-exact)
        window_frames = int(0.02 * (1.0 / (onset_times[1] - onset_times[0])))
        lo = max(0, idx - window_frames)
        hi = min(len(onset_env), idx + window_frames + 1)
        strengths.append(float(onset_env[lo:hi].max()))
    return float(np.sum(strengths)), strengths


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "source",
        type=Path,
        help="Source audio file or forged track directory",
    )
    p.add_argument("--bpm", type=float, required=True)
    p.add_argument(
        "--candidates",
        type=float,
        nargs="+",
        required=True,
        help="Candidate first_downbeat values to score",
    )
    p.add_argument(
        "--n-bars",
        type=int,
        default=16,
        help="How many bars ahead to look at each candidate (default 16)",
    )
    args = p.parse_args()

    if not args.source.exists():
        print(f"FATAL: {args.source} not found")
        return 1

    bar_period = 60.0 * 4 / args.bpm
    print(f"\nBar period at {args.bpm} BPM: {bar_period:.4f}s")
    print(f"Probing {args.n_bars} bar positions per candidate")
    print()

    onset_env, onset_times = get_kick_onset_envelope(args.source)
    print(f"Kick envelope: {len(onset_env)} frames, {onset_times[-1]:.1f}s total")
    print()

    print(
        f"{'candidate':>12s}  {'total score':>12s}  {'avg/bar':>10s}    per-bar strengths (first 8)"
    )
    print("-" * 88)
    results = []
    for candidate in args.candidates:
        total, strengths = score_candidate(
            onset_env, onset_times, candidate, bar_period, n_bars=args.n_bars
        )
        avg = total / len(strengths) if strengths else 0
        first8 = " ".join(f"{s:5.1f}" for s in strengths[:8])
        print(f"  {candidate:>10.4f}  {total:>12.2f}  {avg:>10.3f}  {first8}")
        results.append((candidate, total, avg, strengths))

    # Two musical interpretations of "bar 1":
    # 1. FIRST AUDIBLE drum cut (= first candidate with bar-1 strength
    #    above an absolute threshold, indicating ANY audible drum hit)
    # 2. MAIN BEAT DROP (= candidate with the highest bar-1 strength,
    #    indicating the loudest/most-emphatic kick that anchors the song)
    print()
    # Compute global threshold from the maximum strength observed
    max_strength = max((s for _, _, _, sts in results for s in sts), default=0)
    if max_strength == 0:
        print("(no kick onsets detected — silent track?)")
        return 0

    audible_threshold = 0.15 * max_strength

    first_audible = next(
        (c for c, _, _, sts in results if sts and sts[0] >= audible_threshold),
        None,
    )
    main_beat = max(
        results, key=lambda r: r[3][0] if r[3] else 0
    )  # candidate with highest bar-1 strength

    print(
        f"FIRST AUDIBLE drum cut: first_downbeat={first_audible:.4f}s"
        if first_audible is not None
        else "FIRST AUDIBLE drum cut: no candidate above audible threshold"
    )
    print(f"  (= first candidate where bar-1 strength >= 15% of max ({audible_threshold:.2f}))")
    print(
        f"MAIN BEAT DROP:         first_downbeat={main_beat[0]:.4f}s  "
        f"(bar-1 strength {main_beat[3][0]:.2f})"
    )
    print()
    print(
        "Pick FIRST AUDIBLE if you want bar 1 = where drums first kick in.\n"
        "Pick MAIN BEAT DROP if you want bar 1 = the song's loudest beat anchor.\n"
        "For beat-matching against another song, MAIN BEAT DROP is usually right."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
