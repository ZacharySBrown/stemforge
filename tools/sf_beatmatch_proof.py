#!/usr/bin/env python3
"""sf_beatmatch_proof — render two drum stems beat-matched on CALIBRATED values
and measure the residual kick flam.

This is the acceptance test for sf_calibrate_drums. taste's earlier test
(Still D.R.E. x The Next Episode, both stretched to 94 BPM, aligned on the
*detected* downbeats) locked on tempo but left the two kicks ~65 ms apart — an
audible flam. Here we redo that alignment using each stem's calibrated bpm +
downbeat (from its calib.json sidecar) and measure how far apart the kicks
actually land, by cross-correlating the two kick-band onset envelopes.

A tight calibration should pull the flam well under taste's 65 ms.

Usage:
    uv run python tools/sf_beatmatch_proof.py STEMDIR_A STEMDIR_B \
        --target-bpm 94 --out beatmatch_calibrated.wav
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt

SR = 22050
HOP = 128  # finer than calibration — we're measuring sub-beat offset here


def _load_calib(stemdir: Path) -> dict:
    c = stemdir / "calib.json"
    if not c.is_file():
        raise SystemExit(f"no calib.json in {stemdir} — run sf_calibrate_drums first")
    return json.loads(c.read_text())


def _kick_env(y: np.ndarray, sr: int) -> np.ndarray:
    sos = butter(4, 160, btype="low", fs=sr, output="sos")
    yl = sosfiltfilt(sos, y).astype(np.float32)
    return librosa.onset.onset_strength(y=yl, sr=sr, hop_length=HOP)


def _prep(stemdir: Path, target_bpm: float, bars: int) -> tuple[np.ndarray, dict]:
    """Load drums, stretch from calibrated bpm -> target, slice `bars` bars
    starting at the calibrated downbeat so t=0 is the song's '1'."""
    c = _load_calib(stemdir)
    y, sr = librosa.load(str(Path(c["drums_path"])), sr=SR, mono=True)
    rate = c["bpm"] / target_bpm
    y = librosa.effects.time_stretch(y, rate=rate)
    # the downbeat moves with the stretch
    db = c["downbeat_sec"] / rate
    start = int(db * sr)
    bar_sec = 4.0 * 60.0 / target_bpm
    length = int(bars * bar_sec * sr)
    seg = y[start : start + length]
    if len(seg) < length:
        seg = np.pad(seg, (0, length - len(seg)))
    return seg, c


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sf-beatmatch-proof", description=__doc__)
    ap.add_argument("stem_a", type=Path)
    ap.add_argument("stem_b", type=Path)
    ap.add_argument("--target-bpm", type=float, default=94.0)
    ap.add_argument("--bars", type=int, default=8)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    a, ca = _prep(args.stem_a, args.target_bpm, args.bars)
    b, cb = _prep(args.stem_b, args.target_bpm, args.bars)

    print(f"\n  target {args.target_bpm} BPM, {args.bars} bars, aligned on calibrated downbeats")
    print(f"  A {args.stem_a.name}: {ca['bpm']:.2f} BPM  db={ca['downbeat_sec']:.3f}s  conf={ca['confidence']}")
    print(f"  B {args.stem_b.name}: {cb['bpm']:.2f} BPM  db={cb['downbeat_sec']:.3f}s  conf={cb['confidence']}")

    # Residual flam = sub-beat phase difference of the two kick patterns. For DJ
    # play only sub-beat offset flams; a whole-beat offset still lands kicks
    # together. So we fold each track's kick onsets into one beat period and take
    # the (strength-weighted, circular) mean phase — the flam is the circular
    # distance between the two phases.
    beat = 60.0 / args.target_bpm

    def kick_phase(seg: np.ndarray) -> float:
        env = _kick_env(seg, SR)
        t = librosa.frames_to_time(np.arange(len(env)), sr=SR, hop_length=HOP)
        ang = 2 * np.pi * (t % beat) / beat
        w = np.clip(env, 0, None)
        c = np.sum(w * np.cos(ang))
        s = np.sum(w * np.sin(ang))
        return float(np.arctan2(s, c))  # radians

    pa, pb = kick_phase(a), kick_phase(b)
    d = abs(pa - pb)
    d = min(d, 2 * np.pi - d)  # circular distance
    flam_ms = d / (2 * np.pi) * beat * 1000.0

    print(f"\n  residual kick flam: {flam_ms:.1f} ms   (taste baseline was ~65 ms)")
    verdict = "TIGHT — under a typical 20 ms flam threshold" if flam_ms < 20 else (
        "improved vs baseline" if flam_ms < 65 else "still loose — check downbeats/octave")
    print(f"  verdict: {verdict}")

    if args.out:
        mix = np.stack([a[: min(len(a), len(b))], b[: min(len(a), len(b))]])
        mix = mix.sum(axis=0)
        mix /= max(np.abs(mix).max(), 1e-9)
        sf.write(str(args.out), mix, SR)
        print(f"  mix -> {args.out}  (listen: the two kicks should sit as one)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
