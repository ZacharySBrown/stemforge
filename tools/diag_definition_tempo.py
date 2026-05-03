#!/usr/bin/env python3
"""diag_definition_tempo.py — Phase-1 diagnostic for the half-time-hip-hop bug.

Runs the full matrix of detectors against Black Star "Definition" so we can
decide empirically whether the source tempo is 90 or 120 before touching the
production path. Standalone: only depends on stemforge + librosa + beat-this
(if installed) + LarsNet (if installed).

Usage:
    uv run python tools/diag_definition_tempo.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import librosa
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from stemforge.slicer import detect_bpm_and_beats  # noqa: E402

DRUMS = Path.home() / "stemforge/processed/definition_explicit/drums.wav"
MIX = Path.home() / "Downloads/03 - Definition [Explicit].wav"
DIAG_OUT = Path.home() / "stemforge/processed/definition_explicit/diag_phase1"


def hr(label: str) -> None:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")


def beat_this_detect(
    audio_path: Path,
    *,
    dbn: bool,
    device: str = "auto",
) -> dict:
    """Run beat-this with explicit dbn flag. Returns dict of stats."""
    from beat_this.inference import File2Beats

    from stemforge.beat_detect import _select_device

    resolved_device = _select_device(device)
    t0 = time.time()
    model = File2Beats(checkpoint_path="final0", device=resolved_device, dbn=dbn)
    beats, downbeats = model(audio_path)
    elapsed = time.time() - t0

    beats = np.asarray(beats, dtype=float)
    downbeats = np.asarray(downbeats, dtype=float)

    bpm = 60.0 / float(np.median(np.diff(beats))) if len(beats) > 1 else 0.0
    db_period = (
        float(np.median(np.diff(downbeats))) if len(downbeats) > 1 else None
    )
    db_bpm = 60.0 * 4 / db_period if db_period else None  # 4 beats/bar assumption

    return {
        "bpm_from_ibi": round(bpm, 3),
        "bpm_from_downbeat_period": round(db_bpm, 3) if db_bpm else None,
        "n_beats": int(len(beats)),
        "n_downbeats": int(len(downbeats)),
        "first_downbeat_sec": float(downbeats[0]) if len(downbeats) else None,
        "elapsed_s": round(elapsed, 2),
    }


def kick_autocorrelation(kick_path: Path) -> dict:
    """Autocorrelate the kick onset envelope, find dominant lag → BPM."""
    y, sr = librosa.load(str(kick_path), sr=None, mono=True)

    # Onset strength on the kick stem itself (already isolated)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    # Demean so DC doesn't dominate the autocorr
    onset_env = onset_env - onset_env.mean()

    # Autocorrelate; max lag = 4 seconds (covers 15..240 BPM range)
    max_lag_frames = int(4.0 * sr / 512)
    ac = np.correlate(onset_env, onset_env, mode="full")
    ac = ac[len(ac) // 2 :]  # positive lags
    ac = ac[:max_lag_frames]

    # Convert lag-in-frames to lag-in-seconds, then to BPM (lag = beat period)
    lags_sec = np.arange(len(ac)) * 512 / sr

    # Search for the dominant peak in the plausible kick-period window
    # (kicks typically don't fire faster than 16th notes at 200 BPM = 0.075s,
    #  but we want the bar/quarter period — search 0.25s..2.0s for safety).
    min_idx = int(0.25 * sr / 512)  # 240 BPM upper bound for quarter
    max_idx = int(2.0 * sr / 512)  # 30 BPM lower bound for quarter
    search = ac[min_idx:max_idx]
    if len(search) == 0:
        return {"error": "search range empty"}

    peak_idx = int(np.argmax(search)) + min_idx
    peak_lag_sec = float(lags_sec[peak_idx])
    peak_bpm = 60.0 / peak_lag_sec if peak_lag_sec > 0 else 0.0

    # Also: top 5 peaks (local maxima) for inspection
    from scipy.signal import find_peaks  # type: ignore[import-untyped]

    peaks, _ = find_peaks(ac[min_idx:max_idx], distance=int(0.05 * sr / 512))
    peaks = peaks + min_idx
    peaks_with_strength = sorted(
        [(int(p), float(ac[p])) for p in peaks],
        key=lambda x: -x[1],
    )[:5]
    top_peaks = [
        {
            "lag_sec": round(lags_sec[p], 4),
            "bpm": round(60.0 / lags_sec[p], 2),
            "strength": round(s, 2),
        }
        for p, s in peaks_with_strength
    ]

    # IBI histogram of detected kick onsets directly (different lens on the
    # same data — this is the "is the fundamental kick period 0.667s or 0.5s"
    # test that resolves the ambiguity once and for all).
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=librosa.onset.onset_strength(y=y, sr=sr),
        sr=sr,
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    if len(onset_times) > 1:
        ibis = np.diff(onset_times)
        ibi_median = float(np.median(ibis))
        ibi_mode_bins, ibi_mode_edges = np.histogram(ibis, bins=40, range=(0, 2.0))
        mode_idx = int(np.argmax(ibi_mode_bins))
        ibi_mode_center = float((ibi_mode_edges[mode_idx] + ibi_mode_edges[mode_idx + 1]) / 2)
    else:
        ibi_median = ibi_mode_center = 0.0

    return {
        "dominant_peak": {
            "lag_sec": round(peak_lag_sec, 4),
            "bpm": round(peak_bpm, 2),
        },
        "top_5_peaks": top_peaks,
        "n_kick_onsets": int(len(onset_times)),
        "kick_ibi_median_sec": round(ibi_median, 4),
        "kick_ibi_mode_sec": round(ibi_mode_center, 4),
        "kick_ibi_median_bpm": round(60.0 / ibi_median, 2) if ibi_median > 0 else 0,
        "kick_ibi_mode_bpm": round(60.0 / ibi_mode_center, 2) if ibi_mode_center > 0 else 0,
    }


def main() -> None:
    DIAG_OUT.mkdir(parents=True, exist_ok=True)

    if not DRUMS.exists():
        print(f"FATAL: missing {DRUMS}")
        sys.exit(1)

    results: dict = {"sources": {}}

    # ── librosa baseline on drums + mix ─────────────────────────────────────
    hr("librosa beat_track")
    for label, path in (("drums", DRUMS), ("mix", MIX)):
        if not path.exists():
            print(f"  {label}: SKIP (missing {path})")
            continue
        bpm, beats = detect_bpm_and_beats(path)
        print(f"  {label}: {bpm:.2f} BPM ({len(beats)} beats)")
        results.setdefault("librosa", {})[label] = {
            "bpm": round(float(bpm), 3),
            "n_beats": int(len(beats)),
        }

    # ── beat-this dbn=False (current behavior) and dbn=True ─────────────────
    try:
        for dbn_flag in (False, True):
            hr(f"beat-this dbn={dbn_flag}")
            results.setdefault("beat_this", {})[f"dbn={dbn_flag}"] = {}
            for label, path in (("drums", DRUMS), ("mix", MIX)):
                if not path.exists():
                    print(f"  {label}: SKIP")
                    continue
                stats = beat_this_detect(path, dbn=dbn_flag)
                print(
                    f"  {label}: {stats['bpm_from_ibi']:.2f} BPM "
                    f"(IBI), downbeat-period BPM={stats['bpm_from_downbeat_period']}, "
                    f"{stats['n_beats']} beats, {stats['n_downbeats']} downbeats, "
                    f"first_db={stats['first_downbeat_sec']}, {stats['elapsed_s']}s"
                )
                results["beat_this"][f"dbn={dbn_flag}"][label] = stats
    except ImportError as e:
        print(f"\nbeat-this not installed: {e}")
        results["beat_this"] = {"error": str(e)}

    # ── LarsNet kick isolation, then librosa + autocorr on kick ─────────────
    hr("LarsNet kick isolation")
    try:
        from stemforge.drum_separator import is_available, separate_drums

        if not is_available():
            print("  LarsNet not available (models missing). SKIP kick path.")
            results["larsnet"] = {"error": "models missing"}
        else:
            t0 = time.time()
            substems = separate_drums(DRUMS, DIAG_OUT / "substems", device="auto")
            print(f"  Separated in {time.time() - t0:.1f}s: {list(substems.keys())}")
            kick = substems.get("kick")
            if kick and kick.exists():
                # librosa on kick
                hr("librosa on isolated kick")
                bpm_kick, beats_kick = detect_bpm_and_beats(kick)
                print(f"  kick (librosa): {bpm_kick:.2f} BPM ({len(beats_kick)} beats)")

                # beat-this dbn=True on kick
                try:
                    hr("beat-this dbn=True on isolated kick")
                    bt_kick = beat_this_detect(kick, dbn=True)
                    print(
                        f"  kick (beat-this dbn=True): {bt_kick['bpm_from_ibi']:.2f} BPM, "
                        f"{bt_kick['n_beats']} beats, {bt_kick['n_downbeats']} downbeats"
                    )
                    results.setdefault("kick", {})["beat_this_dbn_true"] = bt_kick
                except Exception as e:
                    print(f"  beat-this on kick failed: {e}")

                # autocorrelation
                hr("kick autocorrelation")
                ac = kick_autocorrelation(kick)
                print(f"  dominant peak: {ac['dominant_peak']}")
                print(f"  top-5 peaks: {ac['top_5_peaks']}")
                print(
                    f"  kick onset IBI median={ac['kick_ibi_median_sec']}s "
                    f"({ac['kick_ibi_median_bpm']} BPM)"
                )
                print(
                    f"  kick onset IBI mode={ac['kick_ibi_mode_sec']}s "
                    f"({ac['kick_ibi_mode_bpm']} BPM)"
                )

                results.setdefault("kick", {})["librosa"] = {
                    "bpm": round(float(bpm_kick), 3),
                    "n_beats": int(len(beats_kick)),
                }
                results["kick"]["autocorrelation"] = ac
    except Exception as e:
        print(f"  LarsNet path failed: {e}")
        import traceback

        traceback.print_exc()
        results["larsnet"] = {"error": str(e)}

    # ── Final verdict ───────────────────────────────────────────────────────
    hr("VERDICT")
    print(
        "  If kick-onset-IBI-mode lands ~0.667s (~90 BPM): source is 90,\n"
        "  detectors are misled by some other layer at 120.\n\n"
        "  If kick-onset-IBI-mode lands ~0.500s (~120 BPM): source IS 120 and\n"
        "  90 was a database error.\n\n"
        "  If beat-this with dbn=True returns 90 BPM on the kick stem (and\n"
        "  ideally on the mix too), that's the strongest single signal."
    )

    out_json = DIAG_OUT / "results.json"
    import json

    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nFull results: {out_json}")


if __name__ == "__main__":
    main()
