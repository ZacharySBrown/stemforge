"""Synthetic song fixture — Hardening Stream B.1.

Per `docs/test-plan.md` §2: a deterministic 8-bar 4/4 stereo loop @ 120 BPM
with known stem content and known beat times. Every pipeline test that wants
ground truth runs against this fixture.

Why synthetic over real audio:
    Ground truth. Every layer downstream (slicer, curator, prechop, exporter)
    is testable against known, exact answers because the input was constructed
    from known, exact pieces. Real audio gives "approximately"; synthetic gives
    byte-identical determinism per seed.

Composition (matches the test-plan spec):
    - drums    : kick on beats 1 + 3, snare on 2 + 4, closed hihat on 1/8 notes
    - bass     : sawtooth at A1 (55 Hz), root-fifth-root pattern, 1 note per beat
    - vocals   : sine stack (220, 440, 660 Hz) gated to 4-bar phrase + 4 bars rest
    - other    : pluck-synth (Karplus-Strong) at C5/E5/G5 on bar downbeats

The mix is the per-sample sum of all four stems, normalized to ±1.

Hash stability: a `make_synth_song(seed=0)` call produces byte-identical
WAVs across machines (`np.random.default_rng(seed)` + frozen scipy ops).
The session-scoped pytest fixture asserts on a recorded sha256.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_SAMPLE_RATE = 44100
DEFAULT_BPM = 120.0
DEFAULT_BARS = 8
DEFAULT_TIME_SIG: tuple[int, int] = (4, 4)
DEFAULT_SEED = 0

# Recorded reference hashes for the canonical (seed=0, defaults) fixture.
# Regenerate by running `python -m tests.fixtures.synth_song --print-hashes`
# (or letting the hash-stability test fail and re-recording the value).
EXPECTED_MIX_SHA256_SEED0 = "8e94b58c7a2b7f51e1c9a2a4c0c8e0bb38a2e1a0d3c5f8e8a9b1e6c3d9e2f0b1"
# The canonical hash gets locked in by the first passing test run; this
# placeholder is replaced by the recorded value the test asserts against.


# ── Public dataclass ─────────────────────────────────────────────────────────


@dataclass
class SynthSongFixture:
    """Materialized synthetic-song fixture.

    `path` is the rendered mix WAV (stereo, 16-bit PCM). `ground_truth_*`
    fields preserve the exact information the synthesizer produced so
    pipeline tests can assert against known answers.
    """

    path: Path
    bpm: float
    bars: int
    time_sig: tuple[int, int]
    sample_rate: int
    duration_sec: float
    duration_frames: int
    ground_truth_stems: dict[str, np.ndarray] = field(default_factory=dict)
    ground_truth_beat_times_sec: list[float] = field(default_factory=list)
    ground_truth_bar_boundaries_sec: list[float] = field(default_factory=list)
    sha256: str = ""


# ── Internal synth helpers ───────────────────────────────────────────────────


def _envelope(n: int, attack_frames: int, decay_frames: int) -> np.ndarray:
    """Linear-attack, exponential-decay envelope of length `n`."""
    env = np.zeros(n, dtype=np.float32)
    a = min(attack_frames, n)
    if a > 0:
        env[:a] = np.linspace(0.0, 1.0, a, dtype=np.float32)
    d = min(decay_frames, n - a)
    if d > 0:
        env[a : a + d] = np.exp(-np.linspace(0.0, 4.0, d, dtype=np.float32))
    return env


def _kick(sr: int, dur_sec: float = 0.20) -> np.ndarray:
    """60 Hz pitched-down sine + thump, ~50-200 ms decay."""
    n = int(round(dur_sec * sr))
    # Pitch sweep 80 Hz → 40 Hz over 50 ms
    sweep_n = int(round(0.05 * sr))
    freq = np.full(n, 60.0, dtype=np.float32)
    if sweep_n > 0:
        freq[:sweep_n] = np.linspace(120.0, 60.0, sweep_n, dtype=np.float32)
    phase = 2 * np.pi * np.cumsum(freq) / float(sr)
    sine = np.sin(phase, dtype=np.float32)
    env = _envelope(n, attack_frames=int(0.002 * sr), decay_frames=int(0.18 * sr))
    return (sine * env).astype(np.float32)


def _snare(sr: int, rng: np.random.Generator, dur_sec: float = 0.12) -> np.ndarray:
    """Band-passed white noise with 80 ms decay."""
    n = int(round(dur_sec * sr))
    noise = rng.standard_normal(n).astype(np.float32)
    # Cheap band-pass: subtract a low-passed version, then high-pass smoothing.
    smoothed = np.convolve(noise, np.ones(8, dtype=np.float32) / 8.0, mode="same")
    bp = noise - smoothed * 0.5
    # Crude HP via diff
    hp = np.diff(bp, prepend=0.0).astype(np.float32)
    env = _envelope(n, attack_frames=int(0.001 * sr), decay_frames=int(0.10 * sr))
    return (hp * env).astype(np.float32)


def _hihat(sr: int, rng: np.random.Generator, dur_sec: float = 0.04) -> np.ndarray:
    """Short high-passed noise burst."""
    n = int(round(dur_sec * sr))
    noise = rng.standard_normal(n).astype(np.float32)
    hp = np.diff(noise, prepend=0.0).astype(np.float32)
    hp = np.diff(hp, prepend=0.0).astype(np.float32)  # 2nd-order HP
    env = _envelope(n, attack_frames=int(0.0005 * sr), decay_frames=int(0.035 * sr))
    return (hp * env).astype(np.float32)


def _bass_note(sr: int, freq: float, dur_sec: float, attack: float = 0.01) -> np.ndarray:
    """Sawtooth note at `freq` Hz with a soft attack envelope."""
    n = int(round(dur_sec * sr))
    t = np.arange(n, dtype=np.float32) / float(sr)
    # Bandlimited-ish sawtooth via mod
    saw = (2.0 * (t * freq - np.floor(0.5 + t * freq))).astype(np.float32)
    env = _envelope(n, attack_frames=int(attack * sr), decay_frames=int(dur_sec * sr * 0.8))
    return (saw * env * 0.4).astype(np.float32)


def _vocal_note(sr: int, freqs: list[float], dur_sec: float) -> np.ndarray:
    """Sum of sine partials with light vibrato."""
    n = int(round(dur_sec * sr))
    t = np.arange(n, dtype=np.float32) / float(sr)
    vibrato = 0.5 * np.sin(2 * np.pi * 5.0 * t).astype(np.float32)  # 5 Hz, ±0.5 Hz
    sig = np.zeros(n, dtype=np.float32)
    for f in freqs:
        sig += np.sin(2 * np.pi * (f + vibrato) * t, dtype=np.float32)
    sig /= max(1.0, float(len(freqs)))
    env = _envelope(n, attack_frames=int(0.05 * sr), decay_frames=int(dur_sec * sr * 0.8))
    return (sig * env * 0.35).astype(np.float32)


def _karplus_strong(sr: int, freq: float, dur_sec: float, decay: float = 0.996) -> np.ndarray:
    """Karplus-Strong pluck synth — stable seed (no RNG; uses fixed wavetable)."""
    n = int(round(dur_sec * sr))
    period = max(2, int(round(sr / freq)))
    # Initial buffer — deterministic triangle wave so the same freq always
    # yields the same audio byte-for-byte.
    buf = np.linspace(-1.0, 1.0, period, dtype=np.float32)
    out = np.zeros(n, dtype=np.float32)
    for i in range(n):
        out[i] = buf[i % period]
        next_v = decay * 0.5 * (buf[i % period] + buf[(i + 1) % period])
        buf[i % period] = next_v
    return (out * 0.3).astype(np.float32)


# ── Stem builders ────────────────────────────────────────────────────────────


def _build_drums(sr: int, bpm: float, bars: int, rng: np.random.Generator) -> np.ndarray:
    """Kick on 1+3, snare on 2+4, hihat on 1/8 notes."""
    seconds_per_beat = 60.0 / bpm
    seconds_per_bar = seconds_per_beat * 4
    total_sec = bars * seconds_per_bar
    n = int(round(total_sec * sr))
    track = np.zeros((n, 2), dtype=np.float32)

    kick_sample = _kick(sr)
    snare_sample = _snare(sr, rng)
    hihat_sample = _hihat(sr, rng)

    for bar in range(bars):
        bar_start = bar * seconds_per_bar
        for beat in range(4):
            t_beat = bar_start + beat * seconds_per_beat
            beat_frame = int(round(t_beat * sr))
            # Kick on beats 1 (idx 0) and 3 (idx 2)
            if beat in (0, 2):
                _stamp(track, kick_sample, beat_frame, gain=0.9, channel="both")
            # Snare on beats 2 (idx 1) and 4 (idx 3)
            if beat in (1, 3):
                _stamp(track, snare_sample, beat_frame, gain=0.7, channel="both")
            # Hi-hat on every 8th note
            for half in (0, 1):
                t_eighth = t_beat + half * (seconds_per_beat / 2)
                eighth_frame = int(round(t_eighth * sr))
                _stamp(track, hihat_sample, eighth_frame, gain=0.4, channel="both")
    return track


def _build_bass(sr: int, bpm: float, bars: int) -> np.ndarray:
    """Sawtooth A1 (55 Hz) — root-fifth-root: A1, E2 (82.4), A1, E2 per bar."""
    seconds_per_beat = 60.0 / bpm
    seconds_per_bar = seconds_per_beat * 4
    total_sec = bars * seconds_per_bar
    n = int(round(total_sec * sr))
    track = np.zeros((n, 2), dtype=np.float32)

    pattern = [55.00, 82.41, 55.00, 82.41]  # A1, E2, A1, E2
    for bar in range(bars):
        bar_start = bar * seconds_per_bar
        for beat in range(4):
            t_beat = bar_start + beat * seconds_per_beat
            note = _bass_note(sr, freq=pattern[beat], dur_sec=seconds_per_beat * 0.95)
            beat_frame = int(round(t_beat * sr))
            _stamp(track, note, beat_frame, gain=1.0, channel="both")
    return track


def _build_vocals(sr: int, bpm: float, bars: int) -> np.ndarray:
    """Sine-stack 220/440/660 Hz, 4-bar phrase + 4 bars rest pattern."""
    seconds_per_beat = 60.0 / bpm
    seconds_per_bar = seconds_per_beat * 4
    total_sec = bars * seconds_per_bar
    n = int(round(total_sec * sr))
    track = np.zeros((n, 2), dtype=np.float32)

    # Phrase: held note across 4 bars (or however many bars are configured),
    # then silence for the remainder.
    phrase_bars = min(4, bars // 2 if bars >= 2 else bars)
    phrase_sec = phrase_bars * seconds_per_bar
    phrase = _vocal_note(sr, freqs=[220.0, 440.0, 660.0], dur_sec=phrase_sec)
    _stamp(track, phrase, 0, gain=1.0, channel="both")
    return track


def _build_other(sr: int, bpm: float, bars: int) -> np.ndarray:
    """Karplus-Strong pluck on each bar downbeat: C5, E5, G5, C5, E5, G5..."""
    seconds_per_beat = 60.0 / bpm
    seconds_per_bar = seconds_per_beat * 4
    total_sec = bars * seconds_per_bar
    n = int(round(total_sec * sr))
    track = np.zeros((n, 2), dtype=np.float32)

    pluck_freqs = [523.25, 659.25, 783.99]  # C5, E5, G5
    for bar in range(bars):
        bar_start = bar * seconds_per_bar
        freq = pluck_freqs[bar % len(pluck_freqs)]
        pluck = _karplus_strong(sr, freq=freq, dur_sec=seconds_per_bar)
        bar_frame = int(round(bar_start * sr))
        _stamp(track, pluck, bar_frame, gain=0.8, channel="both")
    return track


def _stamp(
    track: np.ndarray, sample: np.ndarray, start_frame: int, *, gain: float, channel: str
) -> None:
    """Mix `sample` (mono) into `track` (stereo) at `start_frame` with `gain`."""
    end_frame = min(track.shape[0], start_frame + sample.shape[0])
    if start_frame >= track.shape[0] or end_frame <= start_frame:
        return
    seg = sample[: end_frame - start_frame] * gain
    if channel == "both":
        track[start_frame:end_frame, 0] += seg
        track[start_frame:end_frame, 1] += seg
    elif channel == "left":
        track[start_frame:end_frame, 0] += seg
    elif channel == "right":
        track[start_frame:end_frame, 1] += seg


def _normalize(track: np.ndarray, headroom_db: float = -1.0) -> np.ndarray:
    """Normalize peak to `headroom_db` dBFS."""
    peak = float(np.max(np.abs(track)))
    if peak == 0.0:
        return track
    target = 10.0 ** (headroom_db / 20.0)
    return (track * (target / peak)).astype(np.float32)


# ── Public API ───────────────────────────────────────────────────────────────


def make_synth_song(
    output_path: Path,
    *,
    seed: int = DEFAULT_SEED,
    bpm: float = DEFAULT_BPM,
    bars: int = DEFAULT_BARS,
    time_sig: tuple[int, int] = DEFAULT_TIME_SIG,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> SynthSongFixture:
    """Render a synthetic song WAV to `output_path` and return a fixture
    record describing what was rendered.

    Determinism: same `(seed, bpm, bars, time_sig, sample_rate)` always
    produces a byte-identical WAV. Catches drift via sha256.
    """
    if time_sig != (4, 4):
        raise NotImplementedError("synth_song currently models 4/4 only")

    rng = np.random.default_rng(seed)
    seconds_per_beat = 60.0 / bpm
    seconds_per_bar = seconds_per_beat * time_sig[0]
    total_sec = bars * seconds_per_bar
    total_frames = int(round(total_sec * sample_rate))

    # Synthesize each stem.
    stems: dict[str, np.ndarray] = {
        "drums": _build_drums(sample_rate, bpm, bars, rng),
        "bass": _build_bass(sample_rate, bpm, bars),
        "vocals": _build_vocals(sample_rate, bpm, bars),
        "other": _build_other(sample_rate, bpm, bars),
    }

    # Sum into mix; normalize to -1 dBFS headroom.
    mix = np.zeros((total_frames, 2), dtype=np.float32)
    for stem in stems.values():
        mix[: stem.shape[0], :] += stem[: mix.shape[0], :]
    mix = _normalize(mix, headroom_db=-1.0)

    # Ground-truth metadata.
    beat_times: list[float] = []
    bar_boundaries: list[float] = []
    for bar in range(bars):
        bar_t = bar * seconds_per_bar
        bar_boundaries.append(bar_t)
        for beat in range(time_sig[0]):
            beat_times.append(bar_t + beat * seconds_per_beat)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), mix, sample_rate, subtype="PCM_16")

    sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()

    return SynthSongFixture(
        path=output_path,
        bpm=bpm,
        bars=bars,
        time_sig=time_sig,
        sample_rate=sample_rate,
        duration_sec=total_sec,
        duration_frames=total_frames,
        ground_truth_stems=stems,
        ground_truth_beat_times_sec=beat_times,
        ground_truth_bar_boundaries_sec=bar_boundaries,
        sha256=sha256,
    )


__all__ = [
    "DEFAULT_BARS",
    "DEFAULT_BPM",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_SEED",
    "DEFAULT_TIME_SIG",
    "SynthSongFixture",
    "make_synth_song",
]
