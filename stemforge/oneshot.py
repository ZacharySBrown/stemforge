"""
stemforge.oneshot — Transient-level one-shot extraction from stem audio.

Detects individual hits (kicks, snare cracks, vocal stabs, texture fragments)
using multi-band onset detection, extracts windowed audio around each transient,
and selects a diverse subset via the same greedy farthest-point algorithm as
the bar curator.

Output: per-stem one-shot WAVs suitable for Drum Rack pads (Simpler, one-shot mode).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from .config import StemCurationConfig


# ── LarsNet drum sub-stem separation ─────────────────────────────────────

def extract_drum_oneshots_via_larsnet(
    drums_path: Path,
    output_dir: Path,
    config: StemCurationConfig | None = None,
    device: str = "auto",
) -> list["OneshotProfile"]:
    """
    Extract drum one-shots using LarsNet sub-stem separation.

    Instead of onset detection on a mixed drum stem, LarsNet separates
    into kick/snare/hihat/toms/cymbals sub-stems first. Then simple
    onset detection on each clean sub-stem produces high-quality one-shots
    with correct classification for free.

    Returns list of OneshotProfile with classification already set.
    """
    from .drum_separator import separate_drums, is_available

    if not is_available():
        return []  # fall back to spectral heuristic path

    if config is None:
        config = StemCurationConfig()

    # Step 1: Separate drum stem into sub-stems
    substem_dir = output_dir / "drum_substems"
    substems = separate_drums(drums_path, substem_dir, device=device)

    # Step 2: Simple onset detection + extraction on each clean sub-stem
    all_profiles: list[OneshotProfile] = []

    # Map LarsNet stem names to our classification labels
    stem_to_class = {
        "kick": "kick",
        "snare": "snare",
        "hihat": "hat_closed",  # will refine by duration
        "toms": "perc",
        "cymbals": "hat_open",  # cymbals → open hat category
    }

    # Tighter windows for clean sub-stems (no bleed = can be more precise)
    substem_params = {
        "kick":    {"max_window_ms": 250, "min_gap_ms": 80},
        "snare":   {"max_window_ms": 200, "min_gap_ms": 60},
        "hihat":   {"max_window_ms": 150, "min_gap_ms": 40},
        "toms":    {"max_window_ms": 300, "min_gap_ms": 100},
        "cymbals": {"max_window_ms": 400, "min_gap_ms": 100},
    }

    for stem_name, wav_path in substems.items():
        if not wav_path.exists():
            continue

        params = substem_params.get(stem_name, {"max_window_ms": 300, "min_gap_ms": 80})
        classification = stem_to_class.get(stem_name, "perc")

        # Load sub-stem
        y, sr = librosa.load(str(wav_path), sr=None, mono=True)
        rms_total = float(np.sqrt(np.mean(y ** 2)))

        # Skip if sub-stem is too quiet (not present in this track)
        if rms_total < 0.003:
            continue

        # Simple onset detection (clean signal = reliable)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        hop_length = 512
        wait = max(1, int(params["min_gap_ms"] * sr / (1000 * hop_length)))
        onsets = librosa.onset.onset_detect(
            onset_envelope=onset_env, sr=sr,
            hop_length=hop_length, wait=wait, backtrack=True,
        )
        onset_times = librosa.frames_to_time(onsets, sr=sr, hop_length=hop_length)

        # Load stereo for extraction
        y_stereo, sr = sf.read(str(wav_path), always_2d=True)
        y_stereo = y_stereo.T  # (samples, channels) → (channels, samples)
        total_samples = y_stereo.shape[-1]

        max_window = _ms_to_samples(params["max_window_ms"], sr)
        pre_attack = _ms_to_samples(PRE_ATTACK_MS, sr)

        for i, onset_sec in enumerate(onset_times):
            onset_sample = int(onset_sec * sr)
            start = max(0, onset_sample - pre_attack)

            if i + 1 < len(onset_times):
                next_onset = int(onset_times[i + 1] * sr)
                end = min(start + max_window, next_onset, total_samples)
            else:
                end = min(start + max_window, total_samples)

            if end - start < _ms_to_samples(MIN_DURATION_MS, sr):
                continue

            chunk = y_stereo[:, start:end]
            chunk = _apply_fades(chunk, sr)

            # Peak normalize
            peak = float(np.max(np.abs(chunk)))
            if peak > 0:
                chunk = chunk * (0.891 / peak)

            chunk_mono = chunk.mean(axis=0)
            rms = float(np.sqrt(np.mean(chunk_mono ** 2)))

            if rms < config.rms_floor:
                continue

            peak_val = float(np.max(np.abs(chunk_mono)))
            crest = peak_val / (rms + 1e-10)
            peak_idx = int(np.argmax(np.abs(chunk_mono)))
            attack_time = peak_idx / sr
            duration = (end - start) / sr
            spec = _spectral_features(chunk_mono, sr)

            # Refine hi-hat classification by duration
            cls = classification
            if stem_name == "hihat":
                cls = "hat_closed" if duration < 0.12 else "hat_open"

            out_path = output_dir / f"{stem_name}_oneshots" / f"{stem_name}_os_{i + 1:03d}.wav"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            write_data = chunk.T if chunk.ndim > 1 else chunk
            sf.write(str(out_path), write_data, sr, subtype="PCM_24")

            profile = OneshotProfile(
                path=out_path,
                index=i + 1,
                onset_time=onset_sec,
                duration=duration,
                spectral_centroid=spec["centroid"],
                spectral_bandwidth=spec["bandwidth"],
                spectral_flatness=spec["flatness"],
                crest_factor=crest,
                attack_time=attack_time,
                rms=rms,
                classification=cls,
            )
            profile.feature_vector = _oneshot_feature_vector(profile).tolist()
            all_profiles.append(profile)

    return all_profiles


# ── Per-stem extraction parameters ───────────────────────────────────────

STEM_PARAMS = {
    "drums": {
        "min_onset_gap_ms": 50,     # fast hi-hats
        "max_window_ms": 500,       # tight one-shots
        "use_hpss": True,           # isolate percussive component
        "band_weights": [0.4, 0.2, 0.4],  # low, mid, high — emphasize kick+hat bands
    },
    "bass": {
        "min_onset_gap_ms": 100,
        "max_window_ms": 1000,
        "use_hpss": False,
        "band_weights": [0.6, 0.3, 0.1],  # emphasize low end
    },
    "vocals": {
        "min_onset_gap_ms": 150,    # avoid splitting syllables
        "max_window_ms": 2000,      # capture full words
        "use_hpss": False,
        "band_weights": [0.1, 0.7, 0.2],  # emphasize mid (voice range)
    },
    "other": {
        "min_onset_gap_ms": 100,
        "max_window_ms": 1000,
        "use_hpss": False,
        "band_weights": [0.3, 0.4, 0.3],  # balanced
    },
}

DEFAULT_PARAMS = STEM_PARAMS["other"]

# Frequency band boundaries for multi-band onset detection
BAND_EDGES = [20, 250, 4000, 16000]  # low | mid | high

FADE_IN_MS = 2
FADE_OUT_MS = 20
PRE_ATTACK_MS = 5
MIN_DURATION_MS = 20


@dataclass
class OneshotProfile:
    path: Path
    index: int
    onset_time: float           # position in source stem (seconds)
    duration: float             # seconds
    spectral_centroid: float    # Hz
    spectral_bandwidth: float   # Hz
    spectral_flatness: float
    crest_factor: float
    attack_time: float          # seconds from start to peak
    rms: float
    classification: str = ""    # filled by drum_classifier
    feature_vector: list[float] = field(default_factory=list)


def _ms_to_samples(ms: float, sr: int) -> int:
    return max(1, int(ms * sr / 1000))


def _apply_fades(audio: np.ndarray, sr: int) -> np.ndarray:
    """Apply short fade-in and fade-out to prevent clicks."""
    fade_in = _ms_to_samples(FADE_IN_MS, sr)
    fade_out = _ms_to_samples(FADE_OUT_MS, sr)

    if audio.ndim == 1:
        audio = audio.copy()
        audio[:fade_in] *= np.linspace(0, 1, fade_in)
        audio[-fade_out:] *= np.linspace(1, 0, fade_out)
    else:
        # (channels, samples)
        audio = audio.copy()
        audio[:, :fade_in] *= np.linspace(0, 1, fade_in)
        audio[:, -fade_out:] *= np.linspace(1, 0, fade_out)
    return audio


def _spectral_features(audio_mono: np.ndarray, sr: int) -> dict:
    """Compute spectral features for a one-shot."""
    n_fft = min(2048, len(audio_mono))
    if n_fft < 64:
        return {"centroid": 0.0, "bandwidth": 0.0, "flatness": 0.0}
    spec = np.abs(np.fft.rfft(audio_mono[:n_fft] * np.hanning(n_fft)))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    total = np.sum(spec) + 1e-10
    centroid = float(np.sum(freqs * spec) / total)
    bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * spec) / total))
    log_spec = np.log(spec + 1e-10)
    geo_mean = np.exp(np.mean(log_spec))
    arith_mean = np.mean(spec)
    flatness = float(geo_mean / (arith_mean + 1e-10))
    return {"centroid": centroid, "bandwidth": bandwidth, "flatness": flatness}


def _oneshot_feature_vector(profile: OneshotProfile) -> np.ndarray:
    """8D feature vector for one-shot diversity selection."""
    return np.array([
        profile.spectral_centroid,
        profile.spectral_bandwidth,
        profile.spectral_flatness,
        profile.crest_factor,
        profile.attack_time,
        profile.rms,
        profile.duration,
        1.0 if profile.classification == "kick" else 0.0,  # crude type signal
    ], dtype=float)


def detect_onsets_multiband(
    audio_mono: np.ndarray,
    sr: int,
    band_weights: list[float] | None = None,
    min_gap_ms: float = 50,
) -> np.ndarray:
    """Multi-band onset detection. Returns onset times in seconds."""
    if band_weights is None:
        band_weights = [0.33, 0.34, 0.33]

    hop_length = 512

    # Compute multi-band onset strength
    onset_env = librosa.onset.onset_strength_multi(
        y=audio_mono, sr=sr, hop_length=hop_length,
        channels=[0, 1, 2],  # 3 mel bands (low, mid, high)
    )

    # Weighted combination of bands
    weights = np.array(band_weights[:len(onset_env)])
    weights = weights / (weights.sum() + 1e-10)
    combined_env = np.sum(onset_env * weights[:, np.newaxis], axis=0)

    # Peak-pick with minimum gap
    wait = max(1, int(min_gap_ms * sr / (1000 * hop_length)))
    onsets = librosa.onset.onset_detect(
        onset_envelope=combined_env,
        sr=sr, hop_length=hop_length,
        wait=wait, backtrack=True,
    )

    return librosa.frames_to_time(onsets, sr=sr, hop_length=hop_length)


def extract_kicks_from_bass(
    bass_path: Path,
    output_dir: Path,
    config: StemCurationConfig | None = None,
) -> list[OneshotProfile]:
    """
    Extract kick drum hits from the bass stem.

    htdemucs routes kick energy into the bass separation. This function
    extracts low-frequency transients from the bass stem and returns
    them as kick-classified one-shots for the drum pad layout.
    """
    if config is None:
        config = StemCurationConfig(rms_floor=0.003, crest_min=1.5)

    # Use drum params but with bass-specific onset detection
    profiles = extract_oneshots(
        bass_path, output_dir, "bass_kicks",
        config=StemCurationConfig(
            rms_floor=config.rms_floor,
            crest_min=max(1.5, config.crest_min * 0.5),  # lower crest for bass-embedded kicks
        ),
    )

    # Keep only low-frequency hits (kick range)
    kicks = [p for p in profiles if p.spectral_centroid < 400 and p.duration > 0.040]
    for k in kicks:
        k.classification = "kick"
    return kicks


def extract_oneshots(
    stem_path: Path,
    output_dir: Path,
    stem_name: str,
    config: StemCurationConfig | None = None,
) -> list[OneshotProfile]:
    """
    Extract one-shot transients from a stem WAV.

    Returns list of OneshotProfile with written WAV paths.
    Output dir: {output_dir}/{stem_name}_oneshots/
    """
    params = STEM_PARAMS.get(stem_name, DEFAULT_PARAMS)
    if config is None:
        from .config import StemCurationConfig
        config = StemCurationConfig()

    # Load audio
    y, sr = librosa.load(str(stem_path), sr=None, mono=False)
    if y.ndim == 1:
        y = y[np.newaxis, :]  # (1, samples) for consistent indexing
    y_mono = y.mean(axis=0) if y.ndim > 1 else y

    # Optional HPSS for drums (isolate percussive component for onset detection)
    detect_signal = y_mono
    if params["use_hpss"]:
        _, detect_signal = librosa.effects.hpss(y_mono)

    # Detect onsets
    onset_times = detect_onsets_multiband(
        detect_signal, sr,
        band_weights=params["band_weights"],
        min_gap_ms=params["min_onset_gap_ms"],
    )

    if len(onset_times) == 0:
        return []

    # Extract windows around each onset
    oneshots_dir = output_dir / f"{stem_name}_oneshots"
    oneshots_dir.mkdir(parents=True, exist_ok=True)

    pre_attack = _ms_to_samples(PRE_ATTACK_MS, sr)
    max_window = _ms_to_samples(params["max_window_ms"], sr)
    min_duration = _ms_to_samples(MIN_DURATION_MS, sr)
    total_samples = y.shape[-1]

    profiles: list[OneshotProfile] = []

    for i, onset_sec in enumerate(onset_times):
        onset_sample = int(onset_sec * sr)

        # Window: pre-attack to next onset or max window
        start = max(0, onset_sample - pre_attack)
        if i + 1 < len(onset_times):
            next_onset = int(onset_times[i + 1] * sr)
            end = min(start + max_window, next_onset, total_samples)
        else:
            end = min(start + max_window, total_samples)

        if end - start < min_duration:
            continue

        # Extract and apply fades
        chunk = y[:, start:end]
        chunk = _apply_fades(chunk, sr)

        # Peak normalize to -1dB
        peak = float(np.max(np.abs(chunk)))
        if peak > 0:
            target = 10 ** (-1.0 / 20)
            chunk = chunk * (target / peak)

        # Compute features on mono
        chunk_mono = chunk.mean(axis=0) if chunk.ndim > 1 else chunk
        rms = float(np.sqrt(np.mean(chunk_mono ** 2)))

        if rms < config.rms_floor:
            continue

        peak_val = float(np.max(np.abs(chunk_mono)))
        crest = peak_val / (rms + 1e-10)

        if crest < config.crest_min:
            continue

        peak_idx = int(np.argmax(np.abs(chunk_mono)))
        attack_time = peak_idx / sr
        duration = (end - start) / sr

        spec = _spectral_features(chunk_mono, sr)

        # Write WAV
        out_path = oneshots_dir / f"{stem_name}_os_{i + 1:03d}.wav"
        write_data = chunk.T if chunk.ndim > 1 else chunk
        sf.write(str(out_path), write_data, sr, subtype="PCM_24")

        profile = OneshotProfile(
            path=out_path,
            index=i + 1,
            onset_time=onset_sec,
            duration=duration,
            spectral_centroid=spec["centroid"],
            spectral_bandwidth=spec["bandwidth"],
            spectral_flatness=spec["flatness"],
            crest_factor=crest,
            attack_time=attack_time,
            rms=rms,
        )
        profile.feature_vector = _oneshot_feature_vector(profile).tolist()
        profiles.append(profile)

    return profiles


def select_diverse_oneshots(
    profiles: list[OneshotProfile],
    n: int,
) -> list[OneshotProfile]:
    """Select N most diverse one-shots via greedy farthest-point."""
    if len(profiles) <= n:
        return list(profiles)

    features = np.array([_oneshot_feature_vector(p) for p in profiles])

    # Z-score normalize
    mu = features.mean(axis=0)
    sd = features.std(axis=0)
    sd = np.where(sd < 1e-10, 1.0, sd)
    features = (features - mu) / sd

    # Seed with highest crest factor (punchiest hit)
    seed = int(np.argmax([p.crest_factor for p in profiles]))

    # Greedy farthest-point selection
    selected = [seed]
    min_dist = np.linalg.norm(features - features[seed], axis=1)
    min_dist[seed] = -np.inf

    while len(selected) < min(n, len(profiles)):
        nxt = int(np.argmax(min_dist))
        if min_dist[nxt] == -np.inf:
            break
        selected.append(nxt)
        new_dist = np.linalg.norm(features - features[nxt], axis=1)
        min_dist = np.minimum(min_dist, new_dist)
        min_dist[nxt] = -np.inf

    return [profiles[i] for i in selected]
