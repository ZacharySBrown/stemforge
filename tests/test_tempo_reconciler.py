"""Tests for stemforge.tempo_reconciler — multi-source BPM detection."""

from __future__ import annotations

from unittest import mock

import numpy as np

from stemforge.tempo_reconciler import (
    RATIO_TOLERANCE,
    SUSPICIOUS_RATIOS,
    ReconciledTempo,
    TempoEstimate,
    _bar_period_from_downbeats,
    _is_suspicious_ratio,
    _phase_equivalence,
    reconcile_tempo,
    refine_bpm,
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


# ── _phase_equivalence (GH #55 picker helper) ───────────────────────────────


class TestPhaseEquivalence:
    """The Definition fix (GH #55) hinges on this helper: given two
    first_downbeat candidates, decide whether they're "same grid, different
    bar 1 picks" (phase-equivalent at non-zero bar offset) vs "actually
    misaligned grids" (sub-bar offset, no integer bar count fits).
    """

    def test_zero_offset_when_first_downbeats_match(self):
        # Same fdb → 0 bars apart, phase-equivalent.
        is_eq, n = _phase_equivalence(0.28, 0.28, bar_period=2.66)
        assert is_eq
        assert n == 0

    def test_within_tolerance_still_zero_offset(self):
        # 5% of 2.66 = 0.133s. Diff of 0.05s is well within tolerance.
        is_eq, n = _phase_equivalence(0.28, 0.33, bar_period=2.66)
        assert is_eq
        assert n == 0

    def test_phase_equivalent_at_two_bars(self):
        # The Definition pattern: drums fdb is exactly 2 bars after mix.
        is_eq, n = _phase_equivalence(3.78, 3.78 + 2 * 2.66, bar_period=2.66)
        assert is_eq
        assert n == 2

    def test_phase_equivalent_negative_offset(self):
        # If drums lands BEFORE mix on the grid, n is negative.
        is_eq, n = _phase_equivalence(8.94, 8.94 - 2 * 2.66, bar_period=2.66)
        assert is_eq
        assert n == -2

    def test_not_equivalent_when_off_by_sub_bar(self):
        # Diff of 0.7s at bar_period 2.0s = 0.35 bars: nearest int = 0,
        # residual 0.35 = 35%, well outside 5% tolerance.
        is_eq, n = _phase_equivalence(0.5, 1.2, bar_period=2.0)
        assert not is_eq
        # n is the rounded value but is_eq=False guards callers from acting on it.
        assert n == 0

    def test_handles_zero_bar_period_safely(self):
        # Defensive — zero bar_period would otherwise divide-by-zero.
        is_eq, n = _phase_equivalence(0.28, 5.0, bar_period=0.0)
        assert not is_eq
        assert n == 0


# ── reconcile_tempo behavior with mocked detectors ──────────────────────────


def _make_estimate(
    source: str,
    bpm: float,
    n_beats: int = 100,
    *,
    first_downbeat_sec: float = 0.0,
) -> TempoEstimate:
    """Build a TempoEstimate stand-in. Beat times are evenly spaced to match BPM,
    starting at `first_downbeat_sec` (= where downbeat[0] lives).
    """
    beat_period = 60.0 / bpm
    beats = first_downbeat_sec + np.arange(n_beats, dtype=float) * beat_period
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

    def test_high_confidence_when_mix_and_drums_fully_agree(self, tmp_path):
        """When mix and drums agree on BOTH BPM and first_downbeat → use
        mix at high confidence. Believer pattern: bpm 125, fdb ~0.28s on
        both detectors.
        """
        mix = tmp_path / "mix.wav"
        drums = tmp_path / "drums.wav"
        # Files don't need real audio — we mock the detectors.
        mix.touch()
        drums.touch()

        with mock.patch("stemforge.tempo_reconciler._detect_beat_this") as m:
            m.side_effect = [
                _make_estimate("beat-this:mix", 125.0, first_downbeat_sec=0.28),
                _make_estimate("beat-this:drums", 125.0, first_downbeat_sec=0.28),
            ]
            result = reconcile_tempo(mix, drums, kick_tiebreaker=False)

        assert result.confidence == "high"
        assert abs(result.bpm - 125.0) < 0.01
        assert result.source == "beat-this:mix"
        assert result.warning is None
        assert len(result.all_estimates) == 2

    def test_phase_equivalent_first_downbeat_disagreement_prefers_drums(self, tmp_path):
        """The Definition pattern (GH #55, fixed 2026-05-08):

        mix and drums agree on BPM (90) but mix locks onto a phantom
        downbeat 5.16s before the song's true bar 1; drums correctly
        identifies the actual first kick. Both pick "bar 1" on the same
        underlying grid (offset = 2 bars), so the picks are phase-equivalent
        — prefer drums.
        """
        mix = tmp_path / "mix.wav"
        drums = tmp_path / "drums.wav"
        mix.touch()
        drums.touch()

        # Mix says fdb=3.78s, drums says fdb=8.94s. bar_period = 60/90*4 = 2.667s.
        # Diff = 5.16s = 1.94 bars; rounds to 2 bars; residual is 0.06 bars
        # = 6%, just outside the 5% tolerance band. To make this cleanly
        # phase-equivalent (within tolerance), use mix=3.78s drums=3.78s+2*2.667=9.114s.
        bar_period = 60.0 * 4 / 90.0
        mix_fdb = 3.78
        drums_fdb = mix_fdb + 2 * bar_period

        with mock.patch("stemforge.tempo_reconciler._detect_beat_this") as m:
            m.side_effect = [
                _make_estimate("beat-this:mix", 90.0, first_downbeat_sec=mix_fdb),
                _make_estimate("beat-this:drums", 90.0, first_downbeat_sec=drums_fdb),
            ]
            result = reconcile_tempo(mix, drums, kick_tiebreaker=False)

        assert result.source == "beat-this:drums", "phase-equivalent disagreement → drums must win"
        assert result.confidence == "high"
        # Returned downbeat[0] should be drums' pick.
        assert abs(float(result.downbeat_times[0]) - drums_fdb) < 1e-6
        assert result.warning is not None and "Preferred drums" in result.warning
        assert "+2 bars apart" in result.warning

    def test_non_phase_equivalent_first_downbeat_keeps_mix_with_warning(self, tmp_path):
        """When mix and drums agree on BPM but their first_downbeats are
        OFF BY A SUB-BAR AMOUNT (= they don't align on the same grid at any
        integer bar offset), keep mix but flag medium confidence.

        This is the rare case where one detector locked onto a syncopated
        hit and the other onto a true downbeat. Hard to disambiguate
        automatically — defer to the user via --first-downbeat override.
        """
        mix = tmp_path / "mix.wav"
        drums = tmp_path / "drums.wav"
        mix.touch()
        drums.touch()

        # bar_period = 60/120*4 = 2.0s. Diff of 0.7s = 0.35 bars (= residual
        # 0.35 from nearest int 0; well outside the 5% tolerance).
        with mock.patch("stemforge.tempo_reconciler._detect_beat_this") as m:
            m.side_effect = [
                _make_estimate("beat-this:mix", 120.0, first_downbeat_sec=0.5),
                _make_estimate("beat-this:drums", 120.0, first_downbeat_sec=1.2),
            ]
            result = reconcile_tempo(mix, drums, kick_tiebreaker=False)

        assert result.source == "beat-this:mix", (
            "non-phase-equivalent disagreement → mix kept (no auto-pick possible)"
        )
        assert result.confidence == "medium"
        assert result.warning is not None
        assert "NOT phase-equivalent" in result.warning

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
            mock.patch("stemforge.tempo_reconciler._detect_librosa", return_value=librosa_estimate),
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


# ── _bar_period_from_downbeats: locks in mean (not median) of clean IBIs ────


class TestBarPeriodFromDownbeats:
    """The estimator was switched from median to mean on 2026-05-06.

    beat-this's downbeat positions are quantized to its internal frame rate,
    so most IBIs land on a single quantum (e.g. 2.660s exactly = 90.226 BPM).
    The median locks onto that quantum even when the true bar period sits
    BETWEEN quanta. The mean averages across them and recovers a more
    accurate true period.

    These tests fail if anyone "refactors back to median" later.
    """

    def test_mean_not_median_when_ibis_cluster(self):
        # Twelve downbeats. The helper skips the first downbeat, so it sees
        # diffs between downbeats[1..11] -> 10 IBIs. Construct so those 10 are
        # 8 at exactly 2.660s + 2 at 2.680s.
        # Median(those 10) = 2.660 (the cluster). Mean = 2.664. Function must
        # return the mean.
        first = 8.934
        # IBI #1 (between downbeats[0] and downbeats[1]) is dropped by the
        # helper. Make it 2.660 so the array is realistic; the 10 IBIs the
        # helper actually sees are everything *after* that.
        ibis_seen_by_function = [2.660] * 8 + [2.680] * 2
        ibis = [2.660] + ibis_seen_by_function  # 11 IBIs total -> 12 downbeats
        downbeats = [first]
        for ibi in ibis:
            downbeats.append(downbeats[-1] + ibi)

        period = _bar_period_from_downbeats(np.asarray(downbeats))

        assert period is not None
        # Mean of clean IBIs (all within 20% of rough median = 2.660):
        expected_mean = sum(ibis_seen_by_function) / len(ibis_seen_by_function)
        assert abs(period - expected_mean) < 1e-6, f"expected mean({expected_mean}), got {period}"

        # Sanity: median of the same array would have been 2.660 (the cluster),
        # materially different from the mean.
        median_of_clean = float(np.median(ibis_seen_by_function))
        assert abs(period - median_of_clean) > 0.001, (
            "function returned a value indistinguishable from the median — "
            "did the implementation regress to median(clean)?"
        )

    def test_outlier_rejection_still_uses_median_anchor(self):
        # The outlier filter compares against the rough median (= 2.660).
        # An IBI at 5.00 (= ~88% off) is rejected; an IBI at 3.06 (= 15% off)
        # is kept.
        # First downbeat is skipped by the helper, so design the array so the
        # SEEN IBIs include the outlier. Visible IBIs after skip:
        # [2.660, 2.660, 5.00, 2.660, 3.06, 2.660, 2.660] -> 7 IBIs.
        # Outlier 5.00 rejected (88% off rough median 2.660).
        # 3.06 kept (15% off, within 20% tolerance).
        # Mean of survivors: (5*2.660 + 3.06)/6 = 2.7267.
        first = 0.0
        ibis = [2.660] + [2.660, 2.660, 5.00, 2.660, 3.06, 2.660, 2.660]
        downbeats = [first]
        for ibi in ibis:
            downbeats.append(downbeats[-1] + ibi)

        period = _bar_period_from_downbeats(np.asarray(downbeats))
        assert period is not None

        survivors = [2.660, 2.660, 2.660, 3.06, 2.660, 2.660]
        expected = sum(survivors) / len(survivors)
        assert abs(period - expected) < 1e-3, f"expected mean of survivors {expected}, got {period}"

    def test_returns_none_with_too_few_downbeats(self):
        assert _bar_period_from_downbeats(np.array([0.0])) is None
        assert _bar_period_from_downbeats(np.array([0.0, 2.66])) is None
        assert _bar_period_from_downbeats(np.array([0.0, 2.66, 5.32])) is None
        # 4 downbeats = 3 IBIs total = 2 IBIs after skipping the first downbeat.
        # Survives the early bailout.
        assert _bar_period_from_downbeats(np.array([0.0, 2.66, 5.32, 7.98])) is not None

    def test_returns_none_when_all_outliers(self):
        # Pathological: rough median is 1.0, but no IBI is within 20% of it
        # because 5/6 IBIs differ wildly. (rough_median used as anchor.)
        # Construct so median(IBIs) sits at 1.0 but mean(clean) would be empty.
        # The clean filter is "abs(ibi - rough_median) < 0.2 * rough_median",
        # i.e. within +/- 0.2 of 1.0 = [0.8, 1.2]. If all IBIs are outside
        # that band, clean is empty and the function returns None.
        downbeats = np.array([0.0, 0.5, 1.0, 1.5, 2.5, 4.0])  # IBIs after
        # Skip first downbeat -> ibis from [0.5, 1.0, 1.5, 2.5, 4.0]:
        # diffs = [0.5, 0.5, 1.0, 1.5]. Median = 0.75.
        # Clean filter: within 20% of 0.75 = [0.6, 0.9]. None of [0.5, 0.5, 1.0, 1.5]
        # sits in [0.6, 0.9], so clean is empty -> return None.
        assert _bar_period_from_downbeats(downbeats) is None


# ── refine_bpm: cross-correlation refinement vs synthesized truth ───────────


import pytest as _pytest  # noqa: E402  -- inside-module pytest reference for fixtures


@_pytest.fixture(scope="module")
def long_synth_song(tmp_path_factory):
    """24-bar synth song at 120.0 BPM (= 48s) for refine_bpm tests.

    refine_bpm requires at least 8 bars to score; even a 2% wrong candidate
    BPM must leave >=8 bars in the search window. The default 8-bar fixture
    is too short for ±2% sweeps. 24 bars gives plenty of headroom.
    """
    from fixtures.synth_song import make_synth_song

    out_dir = tmp_path_factory.mktemp("long_synth_song")
    return make_synth_song(out_dir / "long_synth_song.wav", bars=24)


class TestRefineBpm:
    """refine_bpm() should recover the true BPM of a track to within a small
    tolerance, even when seeded with a deliberately wrong candidate.

    Uses a 24-bar deterministic synth song at 120.0 BPM. The fixture has
    kicks on beats 1+3 of every bar — an ideal kick-comb signature.
    """

    def test_recovers_truth_from_low_candidate(self, long_synth_song):
        # Synth fixture is 120.0 BPM. Seed with 119.0 (= 0.83% low).
        refined = refine_bpm(
            long_synth_song.path,
            candidate_bpm=119.0,
            first_downbeat=0.0,
            bpm_tolerance_pct=2.0,
            bpm_step=0.01,
        )
        truth = long_synth_song.bpm
        assert abs(refined - truth) < 0.05, f"refined {refined} not within 0.05 of truth {truth}"

    def test_recovers_truth_from_high_candidate(self, long_synth_song):
        # Symmetric test from the other side — start at 121.5 (= 1.25% high).
        refined = refine_bpm(
            long_synth_song.path,
            candidate_bpm=121.5,
            first_downbeat=0.0,
            bpm_tolerance_pct=2.0,
            bpm_step=0.01,
        )
        truth = long_synth_song.bpm
        assert abs(refined - truth) < 0.05, f"refined {refined} not within 0.05 of truth {truth}"

    def test_falls_back_to_candidate_when_too_few_bars(self, long_synth_song):
        # If first_downbeat is so late that fewer than 8 bars remain in the
        # audio, refine_bpm has too little signal and returns the candidate
        # unchanged (graceful degrade). 24-bar song = 48s. first_downbeat=44
        # leaves 4s -- ~2 bars at 120 BPM, below the 8-bar minimum.
        refined = refine_bpm(
            long_synth_song.path,
            candidate_bpm=130.0,  # arbitrary
            first_downbeat=44.0,
            bpm_tolerance_pct=2.0,
            bpm_step=0.01,
        )
        assert refined == 130.0, (
            "refine_bpm should return candidate unchanged when too few bars remain"
        )

    def test_returns_grid_point(self, long_synth_song):
        # Every searched candidate sits on bpm_lo + k * bpm_step for integer
        # k. So the returned BPM must lie on that grid (no interpolation).
        candidate = 119.0
        step = 0.5
        refined = refine_bpm(
            long_synth_song.path,
            candidate_bpm=candidate,
            first_downbeat=0.0,
            bpm_tolerance_pct=2.0,
            bpm_step=step,
        )
        bpm_lo = candidate * 0.98
        offset = (refined - bpm_lo) / step
        assert abs(offset - round(offset)) < 1e-3, (
            f"refined {refined} not on the step grid (offset={offset})"
        )
