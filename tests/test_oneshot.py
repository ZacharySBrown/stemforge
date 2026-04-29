"""Tests for one-shot extraction and drum classification."""

import numpy as np
import pytest
import soundfile as sf

from stemforge.oneshot import (
    extract_oneshots,
    extract_kicks_from_bass,
    select_diverse_oneshots,
    detect_onsets_multiband,
    OneshotProfile,
)
from stemforge.drum_classifier import (
    classify_drum_hit,
    classify_and_assign,
    arrange_drum_pads,
)
from stemforge.config import load_curation_config, StemCurationConfig

SR = 22050


def _write_drum_pattern(path, sr=SR, duration=2.0):
    """Generate synthetic drum pattern with distinct kick, snare, hat sounds."""
    n = int(duration * sr)
    audio = np.zeros(n, dtype=np.float32)
    t = np.arange(int(0.05 * sr)) / sr

    # Kick at beat 1 (0.0s) and beat 3 (0.5s) — low freq sine burst
    for offset in [0.0, 0.5, 1.0, 1.5]:
        start = int(offset * sr)
        kick = 0.8 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 30)
        end = min(start + len(kick), n)
        audio[start:end] += kick[:end - start]

    # Snare at beat 2 (0.25s) and beat 4 (0.75s) — mid freq + noise burst
    for offset in [0.25, 0.75, 1.25, 1.75]:
        start = int(offset * sr)
        snare_tone = 0.4 * np.sin(2 * np.pi * 900 * t) * np.exp(-t * 40)
        snare_noise = 0.3 * np.random.randn(len(t)).astype(np.float32) * np.exp(-t * 50)
        snare = snare_tone + snare_noise
        end = min(start + len(snare), n)
        audio[start:end] += snare[:end - start]

    # Hi-hat every 1/8th — high freq noise burst
    for i in range(int(duration / 0.125)):
        offset = i * 0.125
        start = int(offset * sr)
        hat_len = int(0.02 * sr)  # very short
        hat_t = np.arange(hat_len) / sr
        hat = 0.2 * np.random.randn(hat_len).astype(np.float32) * np.exp(-hat_t * 100)
        end = min(start + len(hat), n)
        audio[start:end] += hat[:end - start]

    stereo = np.stack([audio, audio], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_24")


def _write_bass_stem(path, sr=SR, duration=2.0):
    """Generate synthetic bass stem with distinct plucks."""
    n = int(duration * sr)
    audio = np.zeros(n, dtype=np.float32)
    t = np.arange(int(0.15 * sr)) / sr

    for i, offset in enumerate([0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75]):
        start = int(offset * sr)
        freq = 80 + (i % 4) * 20  # vary pitch
        pluck = 0.6 * np.sin(2 * np.pi * freq * t) * np.exp(-t * 15)
        end = min(start + len(pluck), n)
        audio[start:end] += pluck[:end - start]

    stereo = np.stack([audio, audio], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_24")


class TestOneshotExtraction:
    def test_extract_from_drums(self, tmp_path):
        stem = tmp_path / "drums.wav"
        _write_drum_pattern(stem)
        output = tmp_path / "output"

        profiles = extract_oneshots(stem, output, "drums")

        assert len(profiles) > 0
        assert all(p.path.exists() for p in profiles)
        assert all(p.duration > 0 for p in profiles)
        assert all(p.rms > 0 for p in profiles)
        assert (output / "drums_oneshots").is_dir()

    def test_extract_from_bass(self, tmp_path):
        stem = tmp_path / "bass.wav"
        _write_bass_stem(stem)
        output = tmp_path / "output"

        profiles = extract_oneshots(stem, output, "bass")

        assert len(profiles) > 0
        assert all(p.spectral_centroid > 0 for p in profiles)

    def test_respects_rms_floor(self, tmp_path):
        stem = tmp_path / "drums.wav"
        _write_drum_pattern(stem)
        output = tmp_path / "output"

        config = StemCurationConfig(rms_floor=0.5)  # very high floor
        profiles = extract_oneshots(stem, output, "drums", config=config)

        # High rms_floor should filter out most quiet hits
        assert len(profiles) < 20  # some may pass, but fewer

    def test_select_diverse(self, tmp_path):
        stem = tmp_path / "drums.wav"
        _write_drum_pattern(stem, duration=4.0)
        output = tmp_path / "output"

        all_profiles = extract_oneshots(stem, output, "drums")
        selected = select_diverse_oneshots(all_profiles, n=4)

        assert len(selected) <= 4
        assert len(selected) > 0

    def test_extract_kicks_from_bass(self, tmp_path):
        stem = tmp_path / "bass.wav"
        _write_bass_stem(stem)  # has low-freq plucks that should classify as kicks
        output = tmp_path / "output"

        kicks = extract_kicks_from_bass(stem, output)
        # Bass plucks at 80-140 Hz should be detected as kicks
        assert len(kicks) > 0
        assert all(k.classification == "kick" for k in kicks)
        assert all(k.spectral_centroid < 400 for k in kicks)

    def test_multiband_onset_detection(self, tmp_path):
        stem = tmp_path / "drums.wav"
        _write_drum_pattern(stem)
        audio = np.zeros(int(2.0 * SR), dtype=np.float32)
        # Add a clear transient
        audio[int(0.5 * SR)] = 1.0

        onsets = detect_onsets_multiband(audio, SR, min_gap_ms=50)
        assert len(onsets) >= 1


class TestDrumClassifier:
    def _make_profile(self, centroid, flatness, crest, bandwidth, duration, attack=0.005):
        return OneshotProfile(
            path=None, index=0, onset_time=0,
            duration=duration,
            spectral_centroid=centroid,
            spectral_bandwidth=bandwidth,
            spectral_flatness=flatness,
            crest_factor=crest,
            attack_time=attack,
            rms=0.1,
        )

    def test_kick_acoustic(self):
        p = self._make_profile(centroid=120, flatness=0.2, crest=8.0, bandwidth=200, duration=0.15)
        assert classify_drum_hit(p) == "kick"

    def test_kick_808(self):
        p = self._make_profile(centroid=80, flatness=0.4, crest=6.0, bandwidth=150, duration=0.3)
        assert classify_drum_hit(p) == "kick"

    def test_snare(self):
        p = self._make_profile(centroid=2000, flatness=0.3, crest=7.0, bandwidth=3000, duration=0.1)
        assert classify_drum_hit(p) == "snare"

    def test_hat_closed(self):
        p = self._make_profile(centroid=8000, flatness=0.6, crest=5.0, bandwidth=4000, duration=0.05)
        assert classify_drum_hit(p) == "hat_closed"

    def test_hat_open(self):
        p = self._make_profile(centroid=7000, flatness=0.5, crest=4.0, bandwidth=3000, duration=0.25)
        assert classify_drum_hit(p) == "hat_open"

    def test_rim(self):
        p = self._make_profile(centroid=3000, flatness=0.3, crest=12.0, bandwidth=2000, duration=0.02)
        assert classify_drum_hit(p) == "rim"

    def test_perc_fallback(self):
        p = self._make_profile(centroid=1000, flatness=0.3, crest=3.0, bandwidth=500, duration=0.1)
        assert classify_drum_hit(p) == "perc"

    def test_classify_and_assign(self):
        profiles = [
            self._make_profile(centroid=100, flatness=0.2, crest=8.0, bandwidth=200, duration=0.15),
            self._make_profile(centroid=8000, flatness=0.6, crest=5.0, bandwidth=4000, duration=0.05),
        ]
        classified = classify_and_assign(profiles)
        assert classified[0].classification == "kick"
        assert classified[1].classification == "hat_closed"

    def test_arrange_drum_pads(self):
        profiles = [
            self._make_profile(centroid=100, flatness=0.2, crest=8.0, bandwidth=200, duration=0.15),
            self._make_profile(centroid=2000, flatness=0.3, crest=7.0, bandwidth=3000, duration=0.1),
            self._make_profile(centroid=8000, flatness=0.6, crest=5.0, bandwidth=4000, duration=0.05),
        ]
        classify_and_assign(profiles)
        pads = arrange_drum_pads(profiles, n_pads=8)

        assert len(pads) == 8
        # Kick should be at pad 0 (bottom-left)
        assert pads[0] is not None
        assert pads[0].classification == "kick"


class TestCurationConfig:
    def test_load_default_config(self):
        cfg = load_curation_config()
        assert cfg.version == 2
        assert cfg.layout.mode in ("stems", "loops-only", "production", "dj", "dual-deck", "session")
        assert "drums" in cfg.stems
        assert cfg.stems["drums"].phrase_bars == 1

    def test_per_stem_weights(self):
        cfg = load_curation_config()
        drums_w = cfg.for_stem("drums").distance_weights
        bass_w = cfg.for_stem("bass").distance_weights
        assert drums_w["rhythm"] > bass_w["rhythm"]  # drums emphasize rhythm

    def test_unknown_stem_defaults(self):
        cfg = load_curation_config()
        unknown = cfg.for_stem("guitar")
        assert unknown.phrase_bars == 1  # default
        assert unknown.strategy == "max-diversity"

    def test_midi_extract_config(self):
        cfg = load_curation_config()
        assert cfg.for_stem("bass").midi_extract is True
        assert cfg.for_stem("drums").midi_extract is False
