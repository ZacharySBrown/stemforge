#!/usr/bin/env python3
"""verify_tempo.py — Run the full diagnostic suite on a track to determine
the true tempo. Used when we suspect *both* librosa and beat-this might be
wrong on a particular track and need ground truth.

Runs:
- librosa beat_track on drums
- beat-this on mix (if provided)
- beat-this on drums
- LarsNet kick isolation → librosa + beat-this on kick
- kick onset autocorrelation (the gold-standard "what is the actual kick
  period" measurement)

Usage:
    uv run python tools/verify_tempo.py <track_dir> [--mix PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import librosa
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stemforge.slicer import detect_bpm_and_beats  # noqa: E402


def beat_this_one(path: Path) -> tuple[float, int, int]:
    from beat_this.inference import File2Beats

    from stemforge.beat_detect import _select_device

    model = File2Beats(checkpoint_path="final0", device=_select_device("auto"), dbn=False)
    beats, downbeats = model(path)
    if len(beats) < 2:
        return 0.0, 0, 0
    return 60.0 / float(np.median(np.diff(beats))), len(beats), len(downbeats)


def kick_autocorr(kick_path: Path) -> dict:
    y, sr = librosa.load(str(kick_path), sr=None, mono=True)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    onset_env = onset_env - onset_env.mean()
    max_lag = int(4.0 * sr / 512)
    ac = np.correlate(onset_env, onset_env, mode="full")
    ac = ac[len(ac) // 2 :][:max_lag]
    lags_sec = np.arange(len(ac)) * 512 / sr
    min_idx = int(0.25 * sr / 512)
    max_idx = int(2.0 * sr / 512)
    from scipy.signal import find_peaks  # type: ignore[import-untyped]

    peaks, _ = find_peaks(ac[min_idx:max_idx], distance=int(0.05 * sr / 512))
    peaks = peaks + min_idx
    by_strength = sorted(((int(p), float(ac[p])) for p in peaks), key=lambda x: -x[1])[:5]
    return {
        "top_peaks": [
            {"lag_sec": float(lags_sec[p]), "bpm": 60.0 / float(lags_sec[p]), "strength": s}
            for p, s in by_strength
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("track_dir", type=Path)
    p.add_argument("--mix", type=Path, default=None)
    p.add_argument("--label", type=str, default=None, help="Human label for output")
    args = p.parse_args()

    track = args.track_dir
    drums = track / "drums.wav"
    if not drums.exists():
        print(f"FATAL: missing {drums}")
        return 1

    label = args.label or track.name
    print(f"\n{'=' * 70}\n  {label}\n{'=' * 70}")

    # librosa drums
    bpm_lr, beats_lr = detect_bpm_and_beats(drums)
    print(f"  librosa drums:        {bpm_lr:7.2f} BPM  ({len(beats_lr)} beats)")

    # beat-this drums
    try:
        bpm_bt_d, n_b, n_d = beat_this_one(drums)
        print(f"  beat-this drums:      {bpm_bt_d:7.2f} BPM  ({n_b} beats, {n_d} downbeats)")
    except ImportError:
        print("  beat-this not installed")
        bpm_bt_d = 0

    # beat-this mix
    if args.mix and args.mix.exists():
        try:
            bpm_bt_m, n_b, n_d = beat_this_one(args.mix)
            print(f"  beat-this mix:        {bpm_bt_m:7.2f} BPM  ({n_b} beats, {n_d} downbeats)")
        except ImportError:
            pass
    else:
        bpm_bt_m = None
        if args.mix:
            print(f"  mix not found at {args.mix}")

    # LarsNet kick
    try:
        from stemforge.drum_separator import is_available, separate_drums

        if is_available():
            substem_dir = track / "verify_substems"
            substems = separate_drums(drums, substem_dir, device="auto")
            kick = substems.get("kick")
            if kick and kick.exists():
                # librosa on kick
                bpm_lr_k, _ = detect_bpm_and_beats(kick)
                print(f"  librosa on kick:      {bpm_lr_k:7.2f} BPM")
                # beat-this on kick
                try:
                    bpm_bt_k, n_b, n_d = beat_this_one(kick)
                    print(
                        f"  beat-this on kick:    {bpm_bt_k:7.2f} BPM  "
                        f"({n_b} beats, {n_d} downbeats)"
                    )
                except ImportError:
                    pass
                # autocorr
                ac = kick_autocorr(kick)
                print("  kick autocorr top peaks:")
                for tp in ac["top_peaks"]:
                    print(
                        f"    lag={tp['lag_sec']:.4f}s  bpm={tp['bpm']:7.2f}  "
                        f"strength={tp['strength']:.0f}"
                    )
        else:
            print("  LarsNet not available")
    except Exception as e:
        print(f"  LarsNet path failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
