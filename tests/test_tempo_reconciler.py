"""Tests for stemforge.tempo_reconciler — multi-source BPM detection."""
from __future__ import annotations

from unittest import mock

import numpy as np

from stemforge.tempo_reconciler import (
    RATIO_TOLERANCE,
    SUSPICIOUS_RATIOS,
    ReconciledTempo,
    TempoEstimate,
    _is_suspicious_ratio,
    reconcile_tempo,
)


# ── Pure-logic helpers ──────────────────────────────────────────────────────


class TestSuspiciousRatio:
    def test_half_time_detected(self):
        # 60/120 = 0.5 exactly — clean half-time
        suspicious, ratio = _is_suspicious_ratio(60.0, 120.0)
        assert suspicious
        assert ratio == 0.5

    def test_double_time_detected(self):
        suspicious, ratio = _is_suspicious_ratio(180.0, 90.0)
        assert suspicious
        assert ratio == 2.0

    def test_definition_pattern_detected(self):
        # The exact failure mode from Black Star — Definition: 120 / 90 = 1.333
        suspicious, ratio = _is_suspicious_ratio(120.0, 90.0)
        assert suspicious
        assert ratio is not None
        assert abs(ratio - 4 / 3) < 0.01

    def test_triplet_dotted_detected(self):
        # 0.667 ratio — triplet/dotted relationship
        suspicious, _ = _is_suspicious_ratio(80.0, 120.0)
        assert suspicious

    def test_close_but_not_round_not_suspicious(self):
        # 1.038 — Alright case (mix=111.11 vs drums=115.38). Not a clean ratio.
        suspicious, _ = _is_suspicious_ratio(115.38, 111.11)
        assert not suspicious

    def test_within_tolerance_match(self):
        # 1.0% off from 0.5 — should still match given RATIO_TOLERANCE = 0.01
        # (boundary case — use a value clearly inside tolerance)
        suspicious, _ = _is_suspicious_ratio(60.1, 120.0)  # 0.50083, ~0.17% off
        assert suspicious

    def test_outside_tolerance_no_match(self):
        # 5% off from 0.5 — well outside tolerance
        suspicious, _ = _is_suspicious_ratio(63.0, 120.0)  # 0.525
        assert not suspicious

    def test_zero_inputs_safe(self):
        suspicious, ratio = _is_suspicious_ratio(0.0, 120.0)
        assert not suspicious
        assert ratio is None

    def test_all_canonical_ratios_match_themselves(self):
        # Every ratio in the set should be detected against a perfect example
        for r in SUSPICIOUS_RATIOS:
            suspicious, matched = _is_suspicious_ratio(100.0 * r, 100.0)
            assert suspicious, f"ratio {r} not detected"
            assert matched is not None
            assert abs(matched - r) / r < RATIO_TOLERANCE


# ── reconcile_tempo behavior with mocked detectors ──────────────────────────


def _make_estimate(source: str, bpm: float, n_beats: int = 100) -> TempoEstimate:
    """Build a TempoEstimate stand-in. Beat times are evenly spaced to match BPM."""
    beats = np.arange(n_beats, dtype=float) * (60.0 / bpm)
    detector = "beat-this" if "beat-this" in source else "librosa"
    audio_label = source.split(":")[-1]
    return TempoEstimate(
        source=source,  # type: ignore[arg-type]
        bpm=bpm,
        beat_times=beats,
        downbeat_times=beats[::4] if detector == "beat-this" else np.array([], dtype=float),
        detector=detector,  # type: ignore[arg-type]
        audio_label=audio_label,  # type: ignore[arg-type]
    )


class TestReconcileTempo:
    def test_requires_at_least_one_source(self):
        import pytest

        with pytest.raises(ValueError):
            reconcile_tempo(mix_path=None, drums_path=None)

    def test_high_confidence_when_mix_and_drums_agree(self, tmp_path):
        """The Definition case: mix and drums both at 90 BPM → high confidence."""
        mix = tmp_path / "mix.wav"
        drums = tmp_path / "drums.wav"
        # Files don't need real audio — we mock the detectors.
        mix.touch()
        drums.touch()

        with mock.patch("stemforge.tempo_reconciler._detect_beat_this") as m:
            m.side_effect = [
                _make_estimate("beat-this:mix", 90.91),
                _make_estimate("beat-this:drums", 90.91),
            ]
            result = reconcile_tempo(mix, drums, kick_tiebreaker=False)

        assert result.confidence == "high"
        assert abs(result.bpm - 90.91) < 0.01
        assert result.source == "beat-this:mix"
        assert result.warning is None
        assert len(result.all_estimates) == 2

    def test_low_confidence_with_fuzzy_disagreement(self, tmp_path):
        """The Alright case: mix=111 vs drums=115. Not a round factor — falls
        through to 'prefer mix, low confidence' without firing the tiebreaker."""
        mix = tmp_path / "mix.wav"
        drums = tmp_path / "drums.wav"
        mix.touch()
        drums.touch()

        with mock.patch("stemforge.tempo_reconciler._detect_beat_this") as m:
            m.side_effect = [
                _make_estimate("beat-this:mix", 111.11),
                _make_estimate("beat-this:drums", 115.38),
            ]
            result = reconcile_tempo(mix, drums, kick_tiebreaker=False)

        assert result.confidence == "low"
        assert abs(result.bpm - 111.11) < 0.01
        assert result.warning is not None
        assert "disagreed" in result.warning
        assert "not a clean" in result.warning

    def test_kick_tiebreaker_fires_on_round_factor(self, tmp_path):
        """When mix and drums disagree by exactly 1.5×, kick tiebreaker should
        run and pick the candidate closest to the kick estimate."""
        mix = tmp_path / "mix.wav"
        drums = tmp_path / "drums.wav"
        kick = tmp_path / "kick.wav"
        for p in (mix, drums, kick):
            p.touch()

        # mix=120, drums=80 → ratio 1.5 (suspicious). kick=120 → mix wins.
        with (
            mock.patch("stemforge.tempo_reconciler._detect_beat_this") as m_bt,
            mock.patch("stemforge.tempo_reconciler._isolate_kick", return_value=kick),
        ):
            m_bt.side_effect = [
                _make_estimate("beat-this:mix", 120.0),
                _make_estimate("beat-this:drums", 80.0),
                _make_estimate("beat-this:kick", 120.0),  # tiebreaker call
            ]
            result = reconcile_tempo(
                mix, drums, kick_tiebreaker=True, kick_workdir=tmp_path / "substems"
            )

        assert result.confidence == "medium"
        assert abs(result.bpm - 120.0) < 0.01
        assert result.source == "beat-this:mix"
        assert result.warning is not None
        assert "tiebreaker" in result.warning.lower()
        assert len(result.all_estimates) == 3  # mix + drums + kick

    def test_kick_tiebreaker_picks_drums_when_kick_matches_drums(self, tmp_path):
        """Inverse: kick matches drums (not mix) → drums wins."""
        mix = tmp_path / "mix.wav"
        drums = tmp_path / "drums.wav"
        kick = tmp_path / "kick.wav"
        for p in (mix, drums, kick):
            p.touch()

        # mix=180, drums=90 → ratio 2.0. kick=90 → drums wins.
        with (
            mock.patch("stemforge.tempo_reconciler._detect_beat_this") as m_bt,
            mock.patch("stemforge.tempo_reconciler._isolate_kick", return_value=kick),
        ):
            m_bt.side_effect = [
                _make_estimate("beat-this:mix", 180.0),
                _make_estimate("beat-this:drums", 90.0),
                _make_estimate("beat-this:kick", 90.0),
            ]
            result = reconcile_tempo(
                mix, drums, kick_tiebreaker=True, kick_workdir=tmp_path / "substems"
            )

        assert result.source == "beat-this:drums"
        assert abs(result.bpm - 90.0) < 0.01

    def test_librosa_fallback_when_beat_this_unavailable(self, tmp_path):
        """If beat-this can't run (returns None), fall back to librosa."""
        mix = tmp_path / "mix.wav"
        drums = tmp_path / "drums.wav"
        mix.touch()
        drums.touch()

        librosa_estimate = _make_estimate("librosa:drums", 100.0)

        with (
            mock.patch("stemforge.tempo_reconciler._detect_beat_this", return_value=None),
            mock.patch(
                "stemforge.tempo_reconciler._detect_librosa", return_value=librosa_estimate
            ),
        ):
            result = reconcile_tempo(mix, drums, kick_tiebreaker=False)

        assert result.source == "librosa:drums"
        assert result.confidence == "low"
        assert result.warning is not None
        assert "beat-this unavailable" in result.warning

    def test_drums_only_input_works(self, tmp_path):
        """Caller passes only drums (no mix): should still work, single-source."""
        drums = tmp_path / "drums.wav"
        drums.touch()

        with mock.patch("stemforge.tempo_reconciler._detect_beat_this") as m:
            m.side_effect = [_make_estimate("beat-this:drums", 95.0)]
            result = reconcile_tempo(mix_path=None, drums_path=drums, kick_tiebreaker=False)

        assert result.source == "beat-this:drums"
        assert result.confidence == "medium"
        assert abs(result.bpm - 95.0) < 0.01

    def test_to_dict_serializable(self, tmp_path):
        """Manifest writers JSON-encode the result — make sure to_dict produces
        plain Python types."""
        import json

        result = ReconciledTempo(
            bpm=90.91,
            beat_times=np.array([0.0, 0.66, 1.32]),
            downbeat_times=np.array([0.0, 2.64]),
            source="beat-this:mix",
            confidence="high",
            all_estimates=[_make_estimate("beat-this:mix", 90.91)],
        )
        d = result.to_dict()
        # Round-trips through json without TypeError
        s = json.dumps(d)
        assert "90.91" in s
        assert json.loads(s) == d
