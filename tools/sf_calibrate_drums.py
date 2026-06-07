#!/usr/bin/env python3
"""sf_calibrate_drums — drift-free global-tempo + downbeat calibration from the
drum stem.

Why this exists
---------------
setforge warps each clip with a 2-marker grid (beat 0 -> first_downbeat,
beat 1 -> first_downbeat + 60/bpm). The slope between those markers IS the
clip's tempo, and Live extrapolates that single grid across the WHOLE clip. So
two things sink a mix:

  1. wrong tempo octave  -> the deck plays half/double time, and
  2. a tempo that is even ~0.1 BPM off -> the grid DRIFTS. At 95 BPM a 0.1 BPM
     error walks ~190 ms over a 3-minute track: tight at the start, a flam by
     the end.

beat-this reports a per-beat median tempo (good to ~0.3 BPM) and a downbeat that
is frequently wrong (mix vs drums disagreeing by whole beats — see the
`warning` field stemforge already writes into stems.json). Neither is good
enough for simultaneous-deck play.

This tool calibrates from the DRUM stem only, because kicks are the cleanest,
least-syncopated transients in the mix:

  * isolate the kick band, detect kick onsets across the FULL track,
  * assign each onset to a beat index using a coarse seed period, then
  * fit ONE global grid by robust (Theil-Sen) regression of onset-time vs
    beat-index. The slope is a drift-free tempo; the intercept is beat 0.
  * octave-disambiguate against onset density + the beat-this seed,
  * re-anchor the downbeat to the first strong kick consistent with the grid,
  * REPORT residual drift (ms) so we can see the grid is actually locked.

Output is non-destructive: a `calib.json` sidecar next to each stems.json, plus
a summary table. Wire it into the manifest emit only once the numbers look good.

Usage
-----
    # calibrate every drum stem referenced by a manifests dir (default: hiphop)
    uv run python tools/sf_calibrate_drums.py --manifests \
        ~/zacharysbrown/taste/setlist_out/hiphop/manifests

    # or point at explicit stem dirs / drums.wav files
    uv run python tools/sf_calibrate_drums.py ~/.cache/setforge/stems/5924 ...
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import butter, sosfiltfilt
from scipy.stats import theilslopes

SR = 22050
HOP = 256  # ~11.6 ms frames at 22050 — fine enough to seed, fit refines past it
DJ_LO, DJ_HI = 70.0, 180.0  # musical band we fold tempos into
KICK_FMAX = 160.0  # kick fundamental + first harmonics live below this


@dataclass
class Calib:
    track_id: str
    drums_path: str
    bpm: float  # drift-free global tempo (octave-corrected)
    bpm_raw_fit: float  # the fit before octave correction
    octave_candidates: list[float]  # in-band ½×/1×/2× — for the octave decision
    downbeat_sec: float  # first musical "1" near the start
    tempo_drift_bpm: float  # |bpm(first half) - bpm(second half)| — the real drift
    grid_med_ms: float  # median |residual| of kicks vs grid (robust tightness)
    grid_p90_ms: float  # 90th-pct |residual| — how bad the off-grid tail is
    n_beats_fit: int  # kick onsets that landed on the grid
    confidence: str  # high | medium | low
    seed_bpm: float | None  # beat-this drums estimate we seeded from
    seed_source: str
    note: str = ""


def _kick_onsets(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Kick-band onset envelope + detected onset times + per-onset strength.

    Lowpass < KICK_FMAX so snares/hats/voc-bleed don't pollute the grid fit;
    kicks carry the bar pulse in nearly all hip-hop / pop / rock drum stems.
    """
    sos = butter(4, KICK_FMAX, btype="low", fs=sr, output="sos")
    y_low = sosfiltfilt(sos, y).astype(np.float32)
    oenv = librosa.onset.onset_strength(y=y_low, sr=sr, hop_length=HOP)
    times = librosa.frames_to_time(np.arange(len(oenv)), sr=sr, hop_length=HOP)
    peaks = librosa.onset.onset_detect(
        onset_envelope=oenv, sr=sr, hop_length=HOP, units="frames", backtrack=True
    )
    if len(peaks) == 0:
        return oenv, times, np.array([])
    onset_times = times[peaks]
    onset_str = oenv[peaks]
    return oenv, onset_times, onset_str


def _comb_tempo(oenv: np.ndarray, sr: int, duration: float) -> float:
    """Global tempo as the uniform beat grid that best explains the kick envelope.

    For each candidate BPM we lay a comb across the WHOLE track and take the best
    phase; the score is per-beat mean kick energy (normalised by beat count, so a
    doubled tempo whose extra beats land on silence is penalised — this is what
    lets it prefer 84.7 over 169.3 on Big Poppa). Coarse 0.1-BPM sweep, then a
    fine 0.01-BPM sweep around the winner. Drift-aware by construction: it scores
    a single constant period over the entire signal."""
    fps = sr / HOP

    def score(bpm: float) -> float:
        per = 60.0 / bpm
        fpb = per * fps
        n = int(duration / per)
        if n < 8:
            return 0.0
        base = np.arange(n) * fpb
        best = 0.0
        for ph in np.linspace(0, fpb, 12, endpoint=False):
            idx = np.round(base + ph).astype(int)
            idx = idx[idx < len(oenv)]
            if len(idx):
                best = max(best, float(oenv[idx].sum()) / len(idx))
        return best

    coarse = np.arange(DJ_LO, DJ_HI, 0.1)
    e = np.array([score(b) for b in coarse])
    peak = coarse[int(np.argmax(e))]
    fine = np.arange(peak - 0.2, peak + 0.2, 0.01)
    ef = np.array([score(b) for b in fine])
    return float(fine[int(np.argmax(ef))])


def _seed_period(drums_dir: Path, fallback_onsets: np.ndarray) -> tuple[float, str]:
    """Seed the coarse beat period from beat-this drums (already in stems.json),
    else fall back to the median kick inter-onset interval."""
    sj = drums_dir / "stems.json"
    if sj.is_file():
        try:
            d = json.loads(sj.read_text())
            for est in (d.get("tempo") or {}).get("all_estimates", []):
                if est.get("audio_label") == "drums" and est.get("bpm"):
                    return 60.0 / float(est["bpm"]), "beat-this:drums"
            if d.get("bpm"):
                return 60.0 / float(d["bpm"]), "stems.json:bpm"
        except (OSError, json.JSONDecodeError):
            pass
    # last resort: dominant inter-onset interval
    if len(fallback_onsets) > 4:
        iois = np.diff(fallback_onsets)
        iois = iois[(iois > 0.2) & (iois < 1.2)]
        if len(iois):
            return float(np.median(iois)), "ioi-median"
    return 60.0 / 120.0, "default-120"


def _fold_octave(bpm: float, onset_rate: float) -> tuple[float, str]:
    """Fold into [DJ_LO, DJ_HI), then correct a doubled/halved estimate using
    kick onset density vs the implied beats/sec (mirrors taste's heuristic but on
    the kick band, where onset density is a cleaner tell)."""
    if bpm <= 0:
        return 0.0, "zero"
    t = bpm
    while t < DJ_LO:
        t *= 2
    while t >= DJ_HI:
        t /= 2
    note = ""
    bps = t / 60.0
    if onset_rate > 0:
        # On the kick band ~1-2 kicks/beat is typical. Far fewer => doubled.
        if onset_rate < 0.45 * bps and t / 2 >= DJ_LO:
            t /= 2
            note = "halved (sparse kicks)"
        elif onset_rate > 3.0 * bps and t * 2 < DJ_HI:
            t *= 2
            note = "doubled (dense kicks)"
    return round(t, 3), note


def _fit_grid(onset_times: np.ndarray, onset_str: np.ndarray, seed_period: float):
    """Robustly fit one global grid: time = a + b*index over kick onsets.

    Assign each onset to its nearest beat index using the seed period, drop
    onsets that fall far off any beat (syncopated hits), keep the strongest
    onset per index, then Theil-Sen regress time vs index. Returns
    (period, beat0_time, residuals_sec, n_used) or None if too few beats.
    """
    if len(onset_times) < 8:
        return None
    t0 = onset_times[0]
    raw_idx = (onset_times - t0) / seed_period
    nearest = np.round(raw_idx)
    # keep onsets within 22% of a beat of a grid line (rejects off-beat hits)
    on_grid = np.abs(raw_idx - nearest) < 0.22
    idx = nearest[on_grid].astype(int)
    tms = onset_times[on_grid]
    strs = onset_str[on_grid]
    if len(idx) < 8:
        return None
    # one onset per index: keep the strongest
    keep: dict[int, tuple[float, float]] = {}
    for k, tt, ss in zip(idx, tms, strs):
        if k not in keep or ss > keep[k][1]:
            keep[k] = (tt, ss)
    ks = np.array(sorted(keep))
    ts = np.array([keep[k][0] for k in ks])
    if len(ks) < 8:
        return None
    b, a, _, _ = theilslopes(ts, ks)  # ts ~ a + b*ks
    resid = ts - (a + b * ks)
    return float(b), float(a), resid, ks, ts


def _pick_downbeat(
    oenv: np.ndarray,
    period: float,
    beat0: float,
    duration: float,
    sr: int,
) -> float:
    """Earliest beat that anchors a strong 4-beat bar pattern in the kick band.

    Score each of the first 8 beats by summing kick energy at beat + n*4*period
    (n bars). The song's real "1" sustains across bars and scores high; pick the
    EARLIEST beat whose bar-score is within 70% of the best (an early true 1 beats
    a slightly louder drop deeper in)."""
    bar = 4.0 * period
    n_bars = min(16, max(2, int((duration - beat0) / bar)))
    frame_t = lambda t: min(int(round(t * sr / HOP)), len(oenv) - 1)  # noqa: E731
    win = max(1, int(0.03 * sr / HOP))  # ±30 ms

    def bar_score(start: float) -> float:
        tot = 0.0
        for n in range(n_bars):
            t = start + n * bar
            if t >= duration:
                break
            c = frame_t(t)
            tot += float(oenv[max(0, c - win) : c + win + 1].max())
        return tot

    # candidate beats: beat0 + j*period for the first 8 beats, folded to >= 0
    first = beat0
    while first - period >= 0:
        first -= period
    cands = [first + j * period for j in range(8) if first + j * period < duration]
    scores = [bar_score(c) for c in cands]
    if not scores:
        return max(0.0, beat0)
    best = max(scores)
    for c, s in zip(cands, scores):
        if s >= 0.7 * best:
            return round(max(0.0, c), 4)
    return round(max(0.0, cands[int(np.argmax(scores))]), 4)


def calibrate(drums_path: Path, track_id: str) -> Calib:
    y, sr = librosa.load(str(drums_path), sr=SR, mono=True)
    duration = len(y) / sr
    oenv, onset_times, onset_str = _kick_onsets(y, sr)
    onset_rate = len(onset_times) / duration if duration > 0 else 0.0

    # beat-this:drums (from stems.json) kept only as a cross-check column.
    seed_bpm_raw, seed_src = _seed_period(drums_path.parent, onset_times)
    seed_bpm = round(60.0 / seed_bpm_raw, 3) if seed_bpm_raw > 0 else None

    # Primary period: comb sweep over the kick envelope (octave-resolving, drift-aware).
    comb_bpm = _comb_tempo(oenv, sr, duration)
    comb_period = 60.0 / comb_bpm

    fit = _fit_grid(onset_times, onset_str, comb_period)
    if fit is None:
        return Calib(
            track_id, str(drums_path), 0.0, 0.0, [], 0.0, 0.0, 0.0, 0.0, 0,
            "low", seed_bpm, seed_src, note="too few kick onsets to fit a grid",
        )
    period, beat0, resid, ks, ts = fit
    n_used = len(ks)
    bpm_raw = 60.0 / period
    bpm, octnote = _fold_octave(bpm_raw, onset_rate)
    # octave correction may rescale the period; recompute grid spacing for downbeat
    period_corr = 60.0 / bpm if bpm > 0 else period

    downbeat = _pick_downbeat(oenv, period_corr, beat0 % period_corr, duration, sr)

    # In-band octave candidates (½×, 1×, 2×) so the octave call is explicit, not
    # silently guessed — this is the one genuinely ambiguous part (Big Poppa etc).
    cands = sorted({
        round(c, 2) for c in (bpm / 2, bpm, bpm * 2) if DJ_LO <= c < DJ_HI
    })

    # Grid tightness: robust spread of residuals (median + p90), in ms. Median is
    # immune to the occasional syncopated kick that slips inside the window.
    ares = np.abs(resid) * 1000.0
    grid_med = float(np.median(ares))
    grid_p90 = float(np.percentile(ares, 90))

    # THE drift number: fit the tempo on the first vs second half of the track and
    # compare. A steady track barely moves; a beat-switch (DNA.) or rubato lights up.
    tempo_drift = 0.0
    if n_used >= 16:
        mid = ks[0] + (ks[-1] - ks[0]) / 2
        lo_m, hi_m = ks <= mid, ks > mid
        if lo_m.sum() >= 6 and hi_m.sum() >= 6:
            b_lo = theilslopes(ts[lo_m], ks[lo_m])[0]
            b_hi = theilslopes(ts[hi_m], ks[hi_m])[0]
            tempo_drift = abs(60.0 / b_lo - 60.0 / b_hi)

    conf = "high"
    if grid_med > 18 or tempo_drift > 0.6 or n_used < 30:
        conf = "medium"
    if grid_med > 35 or tempo_drift > 1.5 or n_used < 15:
        conf = "low"
    notes = [octnote] if octnote else []
    if tempo_drift > 1.5:
        notes.append(f"tempo varies {tempo_drift:.1f} BPM half-to-half")
    if len(cands) > 1:
        notes.append(f"octave? {'/'.join(str(c) for c in cands)}")

    return Calib(
        track_id=track_id,
        drums_path=str(drums_path),
        bpm=bpm,
        bpm_raw_fit=round(bpm_raw, 3),
        octave_candidates=cands,
        downbeat_sec=downbeat,
        tempo_drift_bpm=round(tempo_drift, 3),
        grid_med_ms=round(grid_med, 1),
        grid_p90_ms=round(grid_p90, 1),
        n_beats_fit=n_used,
        confidence=conf,
        seed_bpm=seed_bpm,
        seed_source=seed_src,
        note="; ".join(notes),
    )


def _resolve_targets(args) -> list[tuple[str, Path]]:
    """Return [(track_id, drums.wav path)] from explicit paths or a manifests dir."""
    out: list[tuple[str, Path]] = []
    if args.manifests:
        mdir = Path(args.manifests).expanduser()
        seen = set()
        for mf in sorted(mdir.glob("*.json")):
            try:
                d = json.loads(mf.read_text())
                ap = d["stems"]["drums"]["clips"][0]["audio_path"]
            except (OSError, json.JSONDecodeError, KeyError, IndexError):
                continue
            m = re.search(r"/stems/(\d+)/", ap)
            tid = m.group(1) if m else Path(ap).parent.name
            if tid in seen:
                continue
            seen.add(tid)
            out.append((tid, Path(ap)))
    for p in args.targets:
        p = Path(p).expanduser()
        drums = p / "drums.wav" if p.is_dir() else p
        tid = drums.parent.name
        out.append((tid, drums))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sf-calibrate-drums", description=__doc__)
    ap.add_argument("targets", nargs="*", help="stem dirs or drums.wav files")
    ap.add_argument("--manifests", help="manifests dir; calibrate every referenced drum stem")
    ap.add_argument("--report", help="write a JSON report here (default: stdout only)")
    ap.add_argument("--write-sidecar", action="store_true",
                    help="also write calib.json next to each stems.json (non-destructive)")
    args = ap.parse_args(argv)

    targets = _resolve_targets(args)
    if not targets:
        print("error: no targets (pass stem dirs or --manifests DIR)", file=sys.stderr)
        return 2

    print(f"\n  calibrating {len(targets)} drum stems\n  {'=' * 84}")
    print(f"  {'id':>6}  {'bpm':>7}  {'dnbeat':>7}  {'drift':>6}  "
          f"{'tight':>6}  {'p90':>6}  {'n':>4}  {'conf':>6}  note")
    print(f"  (drift=|½-½| BPM   tight=median |kick-grid|   p90=tail)\n  {'-' * 84}")
    results: list[Calib] = []
    for tid, drums in targets:
        if not drums.is_file():
            print(f"  {tid:>6}  MISSING {drums}")
            continue
        try:
            c = calibrate(drums, tid)
        except Exception as e:  # noqa: BLE001 - surface per-track, keep going
            print(f"  {tid:>6}  FAILED  {type(e).__name__}: {e}")
            continue
        results.append(c)
        print(f"  {c.track_id:>6}  {c.bpm:>7.2f}  {c.downbeat_sec:>7.3f}  "
              f"{c.tempo_drift_bpm:>5.2f}  {c.grid_med_ms:>5.1f}m  {c.grid_p90_ms:>5.1f}m  "
              f"{c.n_beats_fit:>4}  {c.confidence:>6}  {c.note}")
        if args.write_sidecar:
            (drums.parent / "calib.json").write_text(json.dumps(asdict(c), indent=2) + "\n")

    if results:
        tight = np.array([c.grid_med_ms for c in results])
        print(f"  {'-' * 84}")
        print(f"  grid tightness: median {np.median(tight):.1f} ms, "
              f"{int((tight < 15).sum())}/{len(results)} under 15 ms")
        varies = [c.track_id for c in results if c.tempo_drift_bpm > 1.5]
        if varies:
            print(f"  tempo varies (>1.5 BPM half-to-half): {', '.join(varies)}")
        octs = [c.track_id for c in results if len(c.octave_candidates) > 1]
        if octs:
            print(f"  octave ambiguous (needs a call): {', '.join(octs)}")
        lows = [c.track_id for c in results if c.confidence == "low"]
        if lows:
            print(f"  low-confidence: {', '.join(lows)}")

    if args.report:
        Path(args.report).expanduser().write_text(
            json.dumps([asdict(c) for c in results], indent=2) + "\n"
        )
        print(f"\n  report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
