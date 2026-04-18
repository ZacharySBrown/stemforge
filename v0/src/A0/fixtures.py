"""
Audio fixtures for A0 parity tests.

The brief requires parity validation on:
  * a 10-second drum loop
  * a 30-second full mix

If `tests/fixtures/short_loop.wav` exists we use it; otherwise we synthesize
deterministic test audio (silence + click track, tonal sweep) so the pipeline
is runnable on a fresh checkout. The synthetic fixtures are reproducible
given a fixed random seed so parity numbers are comparable across runs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


DEFAULT_SR = 44_100
DRUM_LOOP_SECS = 10.0
FULL_MIX_SECS = 30.0


@dataclass(frozen=True)
class Fixture:
    name: str
    sr: int
    samples: np.ndarray   # shape (channels, samples)

    @property
    def seconds(self) -> float:
        return self.samples.shape[-1] / self.sr


def _click_track(seconds: float, sr: int, bpm: float = 120.0,
                 seed: int = 1234) -> np.ndarray:
    """Deterministic percussive click at `bpm` with soft noise floor."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    y = rng.normal(0, 0.003, size=n).astype(np.float32)  # -50 dBFS floor
    beat_period = 60.0 / bpm
    click_len = int(0.02 * sr)
    env = np.exp(-np.linspace(0, 8, click_len)).astype(np.float32)
    t = 0.0
    while t < seconds:
        start = int(t * sr)
        end = start + click_len
        if end > n:
            break
        # Band-limited click: filtered white burst.
        burst = rng.normal(0, 0.6, size=click_len).astype(np.float32) * env
        y[start:end] += burst
        t += beat_period
    # Stereo copy
    return np.stack([y, y], axis=0)


def _full_mix(seconds: float, sr: int, bpm: float = 128.0,
              seed: int = 4321) -> np.ndarray:
    """Synthetic multi-band mix: click + bass sine + mid pad + stereo decor."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float32) / sr

    # Bass line (60 Hz fundamental, 1/16-note amplitude env keyed to bpm/2).
    bass = 0.25 * np.sin(2 * math.pi * 60.0 * t).astype(np.float32)
    step = (60.0 / bpm) / 4.0  # 16th note
    env_mod = 0.5 + 0.5 * np.cos(2 * math.pi * (t / step))
    bass *= env_mod.astype(np.float32)

    # Pad (filtered noise band around 800 Hz).
    freqs = np.linspace(400, 1200, 5)
    pad = sum(0.05 * np.sin(2 * math.pi * f * t + rng.uniform(0, 2 * math.pi))
              for f in freqs).astype(np.float32)

    # Click on top.
    click = _click_track(seconds, sr, bpm=bpm, seed=seed + 1)[0]

    left = (bass + pad + click).astype(np.float32)
    # Decorrelate a touch for stereo.
    right = (bass + pad * 0.9 + click * 0.95).astype(np.float32)
    mix = np.stack([left, right], axis=0)
    # Normalize to -3 dBFS peak.
    peak = float(np.max(np.abs(mix)))
    if peak > 0:
        mix *= 0.707 / peak
    return mix.astype(np.float32)


def drum_loop(sr: int = DEFAULT_SR) -> Fixture:
    return Fixture(name="drum_loop_10s", sr=sr,
                   samples=_click_track(DRUM_LOOP_SECS, sr).astype(np.float32))


def full_mix(sr: int = DEFAULT_SR) -> Fixture:
    return Fixture(name="full_mix_30s", sr=sr,
                   samples=_full_mix(FULL_MIX_SECS, sr).astype(np.float32))


def all_fixtures(sr: int = DEFAULT_SR) -> list[Fixture]:
    return [drum_loop(sr), full_mix(sr)]


def save_wav(fixture: Fixture, path: Path) -> None:
    import soundfile as sf
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), fixture.samples.T, fixture.sr, subtype="PCM_24")


def load_external_fixture(path: Path) -> Fixture | None:
    """Load `tests/fixtures/short_loop.wav` etc if caller has a real file."""
    if not path.exists():
        return None
    import soundfile as sf
    data, sr = sf.read(str(path), always_2d=True)
    # soundfile returns (samples, channels) — transpose to (channels, samples).
    arr = np.asarray(data, dtype=np.float32).T
    if arr.shape[0] == 1:
        arr = np.concatenate([arr, arr], axis=0)
    elif arr.shape[0] > 2:
        arr = arr[:2]
    return Fixture(name=path.stem, sr=int(sr), samples=arr)
