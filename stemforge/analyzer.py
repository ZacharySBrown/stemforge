"""
Audio analyzer — detect genre and instruments, recommend stem split settings.

Uses three layers:
  1. CLAP (laion/clap-htsat-unfused) — zero-shot genre classification
  2. AST (MIT/ast-finetuned-audioset) — instrument detection (527 AudioSet labels)
  3. Librosa — BPM, spectral features, percussive ratio (fast, no model needed)

Models are lazy-loaded on first use and cached for subsequent calls.
"""
import numpy as np
import librosa
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class AudioProfile:
    """Summary of audio characteristics."""
    # Librosa features
    bpm: float
    energy: float
    bass_ratio: float
    mid_ratio: float
    high_ratio: float
    percussive_ratio: float
    spectral_complexity: float
    dynamic_range_db: float
    onset_density: float

    # ML model results
    genre: str
    genre_confidence: float
    genre_scores: dict             # all genre scores from CLAP
    instruments_detected: list     # top instruments from AST
    instrument_scores: dict        # all instrument scores

    # Recommendations
    recommended_backend: str
    recommended_model: str
    recommended_stems: list
    reason: str


# ── Genre labels for CLAP ──────────────────────────────────────────────────────

GENRE_LABELS = [
    "electronic dance music",
    "hip hop",
    "rock",
    "jazz",
    "acoustic folk",
    "pop",
    "orchestral classical",
    "r&b soul",
    "metal",
    "ambient",
    "latin",
    "country",
    "reggae",
]

# Map CLAP labels back to our internal genre keys
GENRE_LABEL_MAP = {
    "electronic dance music": "electronic",
    "hip hop": "hip_hop",
    "rock": "rock",
    "jazz": "jazz",
    "acoustic folk": "acoustic",
    "pop": "pop",
    "orchestral classical": "orchestral",
    "r&b soul": "hip_hop",      # similar stem needs
    "metal": "rock",             # similar stem needs
    "ambient": "electronic",     # synth-heavy
    "latin": "jazz",             # similar instrumentation (brass, percussion)
    "country": "acoustic",
    "reggae": "pop",
}

# ── Instrument labels for AST filtering ────────────────────────────────────────

INSTRUMENT_LABELS = {
    # Strings
    "Guitar", "Electric guitar", "Acoustic guitar", "Bass guitar",
    "Steel guitar, slide guitar",
    # Keys
    "Piano", "Electric piano", "Organ", "Keyboard (musical)",
    "Synthesizer, electronic instrument",
    # Drums & percussion
    "Drum", "Drum kit", "Snare drum", "Bass drum", "Hi-hat",
    "Cymbal", "Tambourine", "Percussion",
    # Brass & wind
    "Trumpet", "Saxophone", "Flute", "Clarinet", "Trombone",
    "French horn", "Harmonica", "Brass instrument",
    # Strings (orchestral)
    "Violin, fiddle", "Cello", "Harp", "String section",
    # Vocals
    "Singing", "Male singing, male speech", "Female singing, female speech",
    "Choir",
    # Other
    "Banjo", "Mandolin", "Ukulele", "Accordion", "Bagpipes",
    "Turntablism", "Scratching (performance technique)",
}

# ── Stem recommendations per genre ─────────────────────────────────────────────

GENRE_STEM_MAP = {
    "electronic": {
        "demucs_model": "htdemucs",
        "musicai_workflow": "music-ai/stem-separation-suite",
        "musicai_stems": ["vocals", "drums", "bass", "keys", "strings", "other"],
        "reason": "Electronic — heavy synth layering. Music AI 9-stem recommended to separate synths, keys, and textures individually.",
    },
    "hip_hop": {
        "demucs_model": "htdemucs",
        "musicai_workflow": "music-ai/stem-separation-suite",
        "musicai_stems": ["vocals", "drums", "bass", "keys", "other"],
        "reason": "Hip hop — 808s and vocals are key. 9-stem captures vocal layers and bass separately.",
    },
    "rock": {
        "demucs_model": "htdemucs_6s",
        "musicai_workflow": "music-ai/stem-separation-suite",
        "musicai_stems": ["vocals", "drums", "bass", "guitars", "piano", "other"],
        "reason": "Rock — guitar separation is critical. Demucs 6-stem or Music AI 9-stem recommended.",
    },
    "jazz": {
        "demucs_model": "htdemucs_6s",
        "musicai_workflow": "music-ai/stem-separation-suite",
        "musicai_stems": ["vocals", "drums", "bass", "piano", "guitars", "strings", "wind", "other"],
        "reason": "Jazz — complex instrumentation. 6-stem Demucs for guitar+piano, or Music AI for full separation including wind/strings.",
    },
    "acoustic": {
        "demucs_model": "htdemucs_6s",
        "musicai_workflow": "music-ai/stem-separation-suite",
        "musicai_stems": ["vocals", "guitars", "piano", "strings", "other"],
        "reason": "Acoustic — guitar and vocal clarity matter most. 6-stem Demucs to isolate guitar.",
    },
    "pop": {
        "demucs_model": "htdemucs",
        "musicai_workflow": "music-ai/stems-vocals-accompaniment",
        "musicai_stems": ["vocals", "drums", "bass", "other"],
        "reason": "Pop — vocals are the focus. Standard 4-stem split works well.",
    },
    "orchestral": {
        "demucs_model": "htdemucs",
        "musicai_workflow": "music-ai/stem-separation-suite",
        "musicai_stems": ["strings", "wind", "drums", "piano", "bass", "other"],
        "reason": "Orchestral — Demucs struggles here. Music AI 9-stem recommended for strings, wind, and keys.",
    },
}

# ── Model cache ────────────────────────────────────────────────────────────────

_clap_pipeline = None
_ast_pipeline = None


def _get_clap():
    global _clap_pipeline
    if _clap_pipeline is None:
        from transformers import pipeline
        _clap_pipeline = pipeline(
            "zero-shot-audio-classification",
            model="laion/clap-htsat-unfused",
            device="cpu",
        )
    return _clap_pipeline


def _get_ast():
    global _ast_pipeline
    if _ast_pipeline is None:
        from transformers import pipeline
        _ast_pipeline = pipeline(
            "audio-classification",
            model="MIT/ast-finetuned-audioset-10-10-0.4593",
            device="cpu",
        )
    return _ast_pipeline


# ── Main analysis ──────────────────────────────────────────────────────────────

def analyze(audio_path: Path, duration_limit: float = 30.0) -> AudioProfile:
    """
    Analyze an audio file and return a profile with ML-based genre detection,
    instrument identification, and stem split recommendations.
    """
    # ── Load audio ─────────────────────────────────────────────────────────
    y_full, sr_native = librosa.load(str(audio_path), sr=None, mono=True)
    total_duration = len(y_full) / sr_native

    # Sample a representative segment (middle 30s or full if shorter)
    sample_duration = min(duration_limit, total_duration)
    mid_start = max(0, int((total_duration / 2 - sample_duration / 2) * sr_native))
    mid_end = min(len(y_full), mid_start + int(sample_duration * sr_native))
    y_sample = y_full[mid_start:mid_end]

    # ── Librosa features (at 22050 Hz) ─────────────────────────────────────
    y_lr = librosa.resample(y_sample, orig_sr=sr_native, target_sr=22050)
    sr_lr = 22050
    librosa_features = _extract_librosa_features(y_lr, sr_lr)

    # ── CLAP genre classification (at 48000 Hz) ────────────────────────────
    y_clap = librosa.resample(y_sample, orig_sr=sr_native, target_sr=48000)
    genre, genre_confidence, genre_scores = _classify_genre_clap(y_clap)

    # ── AST instrument detection (at 16000 Hz) ────────────────────────────
    y_ast = librosa.resample(y_sample, orig_sr=sr_native, target_sr=16000)
    instruments_detected, instrument_scores = _detect_instruments_ast(y_ast)

    # ── Refine genre based on instruments ──────────────────────────────────
    genre, reason_suffix = _refine_genre_with_instruments(
        genre, genre_confidence, instruments_detected, librosa_features
    )

    # ── Build recommendations ──────────────────────────────────────────────
    stem_map = GENRE_STEM_MAP.get(genre, GENRE_STEM_MAP["pop"])
    reason = stem_map["reason"]
    if reason_suffix:
        reason += " " + reason_suffix

    # Upgrade to 6-stem Demucs if guitar or piano detected
    has_guitar = any("guitar" in i.lower() for i in instruments_detected)
    has_piano = any("piano" in i.lower() for i in instruments_detected)
    demucs_model = stem_map["demucs_model"]
    if (has_guitar or has_piano) and demucs_model == "htdemucs":
        demucs_model = "htdemucs_6s"
        reason += " Guitar/piano detected — upgrading to 6-stem Demucs."

    if genre in ("electronic", "orchestral", "jazz"):
        recommended_backend = "musicai"
        recommended_model = stem_map["musicai_workflow"]
        recommended_stems = stem_map["musicai_stems"]
    else:
        recommended_backend = "demucs"
        recommended_model = demucs_model
        if demucs_model == "htdemucs_6s":
            recommended_stems = ["drums", "bass", "vocals", "guitar", "piano", "other"]
        else:
            recommended_stems = ["drums", "bass", "vocals", "other"]

    return AudioProfile(
        bpm=librosa_features["bpm"],
        energy=librosa_features["energy"],
        bass_ratio=librosa_features["bass_ratio"],
        mid_ratio=librosa_features["mid_ratio"],
        high_ratio=librosa_features["high_ratio"],
        percussive_ratio=librosa_features["percussive_ratio"],
        spectral_complexity=librosa_features["spectral_complexity"],
        dynamic_range_db=librosa_features["dynamic_range_db"],
        onset_density=librosa_features["onset_density"],
        genre=genre,
        genre_confidence=round(genre_confidence, 2),
        genre_scores=genre_scores,
        instruments_detected=instruments_detected,
        instrument_scores=instrument_scores,
        recommended_backend=recommended_backend,
        recommended_model=recommended_model,
        recommended_stems=recommended_stems,
        reason=reason,
    )


# ── Librosa feature extraction ─────────────────────────────────────────────────

def _extract_librosa_features(y, sr) -> dict:
    """Extract spectral features using librosa."""
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])

    rms = librosa.feature.rms(y=y)[0]
    energy = float(np.mean(rms))
    rms_nonzero = rms[rms > 0]
    if len(rms_nonzero) > 0:
        dynamic_range_db = float(20 * np.log10(np.max(rms) / (np.min(rms_nonzero) + 1e-10)))
    else:
        dynamic_range_db = 0.0

    S = np.abs(librosa.stft(y))
    freqs = librosa.fft_frequencies(sr=sr)

    total_energy = np.sum(S ** 2) + 1e-10
    bass_ratio = float(np.sum(S[freqs < 250] ** 2) / total_energy)
    mid_ratio = float(np.sum(S[(freqs >= 250) & (freqs < 4000)] ** 2) / total_energy)
    high_ratio = float(np.sum(S[freqs >= 4000] ** 2) / total_energy)

    H, P = librosa.decompose.hpss(S)
    harmonic_e = np.sum(H ** 2)
    percussive_e = np.sum(P ** 2)
    percussive_ratio = float(percussive_e / (harmonic_e + percussive_e + 1e-10))

    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    bandwidth = librosa.feature.spectral_bandwidth(S=S, sr=sr)[0]
    centroid_var = float(np.std(centroid) / (np.mean(centroid) + 1e-10))
    bandwidth_norm = float(np.mean(bandwidth) / (sr / 2))
    spectral_complexity = round(min(1.0, (centroid_var + bandwidth_norm) / 2), 3)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    duration = len(y) / sr
    onset_density = round(float(len(onsets) / duration) if duration > 0 else 0, 2)

    return {
        "bpm": round(bpm, 1),
        "energy": round(energy, 4),
        "bass_ratio": round(bass_ratio, 3),
        "mid_ratio": round(mid_ratio, 3),
        "high_ratio": round(high_ratio, 3),
        "percussive_ratio": round(percussive_ratio, 3),
        "spectral_complexity": spectral_complexity,
        "dynamic_range_db": round(dynamic_range_db, 1),
        "onset_density": onset_density,
    }


# ── CLAP genre classification ─────────────────────────────────────────────────

def _classify_genre_clap(y_48k: np.ndarray) -> tuple[str, float, dict]:
    """
    Use CLAP zero-shot classification for genre detection.
    Input: audio at 48kHz mono.
    Returns: (genre_key, confidence, {label: score}).
    """
    clap = _get_clap()

    results = clap(
        y_48k,
        candidate_labels=GENRE_LABELS,
        hypothesis_template="This is {} music.",
    )

    scores = {r["label"]: round(r["score"], 3) for r in results}
    top_label = results[0]["label"]
    top_score = results[0]["score"]

    genre_key = GENRE_LABEL_MAP.get(top_label, "pop")

    return genre_key, top_score, scores


# ── AST instrument detection ──────────────────────────────────────────────────

def _detect_instruments_ast(y_16k: np.ndarray) -> tuple[list[str], dict]:
    """
    Use AST AudioSet model for instrument detection.
    Input: audio at 16kHz mono.
    Returns: (top_instruments, {label: score}).
    """
    ast = _get_ast()

    # AST returns top_k results from 527 AudioSet classes
    results = ast(y_16k, top_k=30)

    # Filter for instrument-related labels
    all_scores = {r["label"]: round(r["score"], 3) for r in results}
    instrument_results = [
        r for r in results
        if r["label"] in INSTRUMENT_LABELS and r["score"] > 0.05
    ]

    top_instruments = [r["label"] for r in instrument_results[:10]]

    return top_instruments, all_scores


# ── Genre refinement using instruments ─────────────────────────────────────────

def _refine_genre_with_instruments(
    genre: str,
    confidence: float,
    instruments: list[str],
    librosa_features: dict,
) -> tuple[str, str]:
    """
    Cross-check CLAP genre with detected instruments.
    Returns (refined_genre, extra_reason).
    """
    instr_lower = [i.lower() for i in instruments]
    extra = ""

    # Low confidence — let instruments inform the decision
    if confidence < 0.3:
        has_synth = any("synth" in i or "electronic" in i for i in instr_lower)
        has_sax = any("saxophone" in i for i in instr_lower)
        has_violin = any("violin" in i or "cello" in i or "string" in i for i in instr_lower)
        has_guitar = any("guitar" in i for i in instr_lower)

        if has_synth and not has_guitar:
            genre = "electronic"
            extra = "Low genre confidence — synth detected, treating as electronic."
        elif has_sax:
            genre = "jazz"
            extra = "Low genre confidence — saxophone detected, treating as jazz."
        elif has_violin:
            genre = "orchestral"
            extra = "Low genre confidence — strings detected, treating as orchestral."

    # Specific overrides when instruments strongly contradict genre
    has_saxophone = any("saxophone" in i for i in instr_lower)
    has_brass = any("brass" in i or "trumpet" in i or "trombone" in i for i in instr_lower)

    if genre != "jazz" and (has_saxophone or has_brass):
        # Saxophone or brass strongly suggests jazz — override if genre is close
        genre = "jazz"
        extra = "Reclassified: saxophone/brass detected → jazz."

    return genre, extra
