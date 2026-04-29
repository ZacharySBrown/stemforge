"""
beat_align.py — Experimental beat grid correction.

Status: EXPERIMENTAL — may change or be removed.

Two corrections for librosa beat_track() output:

1. Downbeat alignment: beat 0 may not be the actual downbeat.
   Fix: try offsets 0..time_sig-1, pick the one where bar starts
   have maximum onset energy.

2. Ghost beat filtering: syncopated hits (snare ghost notes, hi-hat
   anticipations) get detected as beats, creating extra short IBIs
   that throw off bar boundaries.
   Fix: reject beats whose IBI is <75% of the median IBI, then
   fill gaps where consecutive beats are too far apart.
"""

from __future__ import annotations

import numpy as np
import librosa
from pathlib import Path


def find_best_downbeat_offset(
    audio_path: Path,
    beat_times: np.ndarray,
    time_sig: int = 4,
) -> int:
    """Find the beat offset that maximizes kick-band onset energy at bar boundaries.

    Tries offsets 0..time_sig-1 on the beat array. For each offset,
    computes where bar starts would land and sums the LOW-FREQUENCY onset
    strength (kick drum region, 20-200 Hz) at those positions. Returns the
    offset with the highest total energy.

    Uses band-separated onset detection via librosa.onset.onset_strength_multi()
    to isolate kick drum energy. This is more robust than full-spectrum onset
    energy because kicks almost always land on beat 1, even in syncopated music
    where snare ghosts and hi-hat anticipations can mislead full-spectrum scoring.

    Args:
        audio_path: Path to audio file (typically the drums stem).
        beat_times: Array of beat timestamps in seconds from beat_track().
        time_sig: Beats per bar (e.g. 4 for 4/4, 7 for 7/8).

    Returns:
        Best offset (0 to time_sig-1). Apply as: beat_times[offset:]
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)

    # Band-separated onset detection: isolate low frequencies (kick region).
    # channels define mel band boundaries. Channel 0 = lowest band (kick/sub).
    # Using 5 channels: [0-32, 32-64, 64-96, 96-128] mel bins.
    onset_multi = librosa.onset.onset_strength_multi(
        y=y, sr=sr, channels=[0, 32, 64, 96, 128]
    )
    # Use the lowest band (kick drum region, ~20-200 Hz)
    kick_onset = onset_multi[0]
    onset_times = librosa.frames_to_time(np.arange(len(kick_onset)), sr=sr)

    best_offset = 0
    best_score = -1.0

    for offset in range(min(time_sig, len(beat_times))):
        shifted = beat_times[offset:]
        bar_starts = shifted[::time_sig]

        if len(bar_starts) < 2:
            continue

        # Sum kick-band onset energy at each bar start (nearest frame)
        score = 0.0
        for t in bar_starts:
            idx = np.searchsorted(onset_times, t)
            idx = min(idx, len(kick_onset) - 1)
            score += kick_onset[idx]

        if score > best_score:
            best_score = score
            best_offset = offset

    return best_offset


def apply_downbeat_offset(
    beat_times: np.ndarray,
    offset: int,
) -> np.ndarray:
    """Shift beat array by offset to align with detected downbeat.

    Args:
        beat_times: Original beat timestamps from beat_track().
        offset: Number of beats to skip (from find_best_downbeat_offset).

    Returns:
        Shifted beat array starting from the corrected downbeat.
    """
    if offset <= 0 or offset >= len(beat_times):
        return beat_times
    return beat_times[offset:]


def filter_ghost_beats(
    beat_times: np.ndarray,
    min_ibi_ratio: float = 0.75,
    max_ibi_ratio: float = 1.5,
) -> tuple[np.ndarray, int]:
    """Remove ghost beats caused by syncopation detection artifacts.

    Librosa's beat_track() sometimes detects syncopated hits (ghost snares,
    anticipated hi-hats) as beats. These create abnormally short inter-beat
    intervals (IBIs) that shift bar boundaries.

    Strategy:
    1. Compute median IBI from the full beat array.
    2. Walk the beats: if the IBI from the previous kept beat is too short
       (<min_ibi_ratio * median), skip the current beat (it's a ghost).
    3. If the IBI is too long (>max_ibi_ratio * median), the previous
       "ghost" removal may have over-pruned — keep the beat anyway to
       avoid gaps.

    Args:
        beat_times: Array of beat timestamps in seconds.
        min_ibi_ratio: Minimum IBI as fraction of median (default 0.75).
            Beats closer than this to the previous beat are ghosts.
        max_ibi_ratio: Maximum IBI as fraction of median (default 1.5).
            If gap exceeds this, accept the next beat regardless.

    Returns:
        Tuple of (cleaned beat array, number of beats removed).
    """
    if len(beat_times) < 3:
        return beat_times, 0

    ibis = np.diff(beat_times)
    median_ibi = np.median(ibis)
    min_ibi = median_ibi * min_ibi_ratio
    max_ibi = median_ibi * max_ibi_ratio

    kept = [beat_times[0]]
    removed = 0

    for i in range(1, len(beat_times)):
        gap = beat_times[i] - kept[-1]

        if gap < min_ibi:
            # Too close to previous kept beat — ghost detection
            removed += 1
        elif gap > max_ibi:
            # Gap too large — we over-pruned, accept this beat
            kept.append(beat_times[i])
        else:
            # Normal spacing
            kept.append(beat_times[i])

    return np.array(kept), removed


def diagnose_drift(
    audio_path: Path,
    n_segments: int = 6,
) -> dict:
    """Segment-based tempo estimation for drift detection.

    Divides audio into N segments, estimates tempo per segment,
    returns variance metrics. High variance suggests tempo drift.

    Args:
        audio_path: Path to audio file.
        n_segments: Number of segments to analyze.

    Returns:
        Dict with keys: tempos, mean, std, range, drift_score.
        drift_score > 2.0 suggests significant drift.
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    segment_len = len(y) // n_segments
    tempos = []

    for i in range(n_segments):
        start = i * segment_len
        end = start + segment_len
        segment = y[start:end]
        if len(segment) < sr:  # skip segments shorter than 1 second
            continue
        tempo, _ = librosa.beat.beat_track(y=segment, sr=sr)
        tempos.append(float(np.atleast_1d(tempo)[0]))

    if not tempos:
        return {"tempos": [], "mean": 0, "std": 0, "range": 0, "drift_score": 0}

    arr = np.array(tempos)
    return {
        "tempos": tempos,
        "mean": float(arr.mean()),
        "std": float(arr.std()),
        "range": float(arr.max() - arr.min()),
        "drift_score": float(arr.std() / max(arr.mean(), 1e-10) * 100),
    }
