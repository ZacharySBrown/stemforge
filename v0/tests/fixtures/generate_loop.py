"""Reference generator for ``short_loop.wav``.

The actual ``short_loop.wav`` fixture was committed by Track A's validator
(see ``v0/state/A/artifacts.json`` for the committed metadata: 10s, 44.1kHz,
stereo, PCM_16, 1.76MB). This script documents a *reproducible* recipe that
produces an equivalent loop — useful for regression-testing the binary on
clean inputs or for sanity-checking the fixture isn't stale.

The generated signal intentionally mimics a DAW-like tempo fixture:
- 8 beats at 120 BPM (4 seconds), looped to fill the target duration
- Kick on every beat (sine 60Hz exponentially decayed ~200ms)
- Hi-hat noise bursts on offbeats (filtered noise ~50ms)

Librosa's beat tracker should lock onto 120 BPM with this input; the A
validator observed 117.45 BPM on the committed 10s loop — close enough
given the stochasticity of beat tracking on synthetic material.

Usage (regenerate from scratch; DO NOT overwrite committed short_loop.wav):

    python v0/tests/fixtures/generate_loop.py /tmp/synthetic_loop.wav

Track G does not call this at test time — it uses the committed WAV.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


SAMPLE_RATE = 44100
BPM = 120
NUM_BEATS = 8  # 2 bars at 4/4
TARGET_DURATION_SEC = 10.0  # A-validator committed a 10s loop


def render_loop(sr: int = SAMPLE_RATE, bpm: int = BPM, duration_sec: float = TARGET_DURATION_SEC) -> np.ndarray:
    """Render a mono float32 drum-like loop."""
    beat_sec = 60.0 / bpm
    base_dur = NUM_BEATS * beat_sec  # 4.0s @ 120 BPM

    t = np.linspace(0.0, base_dur, int(sr * base_dur), endpoint=False)
    sig = np.zeros_like(t)

    for i in range(NUM_BEATS):
        beat_t = i * beat_sec
        # Kick: low sine with fast decay
        mask = (t >= beat_t) & (t < beat_t + 0.2)
        sig += np.sin(2 * np.pi * 60 * t) * np.exp(-5 * (t - beat_t)) * mask

    # Offbeat hi-hats — noise bursts
    rng = np.random.default_rng(seed=12345)  # deterministic
    for i in range(NUM_BEATS):
        hat_t = (i + 0.5) * beat_sec
        mask = (t >= hat_t) & (t < hat_t + 0.05)
        sig += rng.standard_normal(len(t)) * 0.2 * np.exp(-30 * (t - hat_t)) * mask

    # Tile to target length
    reps = int(np.ceil(duration_sec * sr / len(sig)))
    tiled = np.tile(sig, reps)
    out = tiled[: int(duration_sec * sr)]

    # Normalize
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak
    return out.astype(np.float32)


def write_wav(path: Path, signal: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    import soundfile as sf

    # Stereo to match the committed fixture
    stereo = np.stack([signal, signal], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_16")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: generate_loop.py <output_wav_path>", file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    if out.name == "short_loop.wav" and out.parent.name == "fixtures":
        print(
            "refusing to overwrite the committed fixture — Track A owns short_loop.wav",
            file=sys.stderr,
        )
        return 1
    write_wav(out, render_loop())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
