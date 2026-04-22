"""Tests for experimental beat alignment correction."""

import numpy as np
import pytest

from stemforge.beat_align import (
    find_best_downbeat_offset,
    apply_downbeat_offset,
    filter_ghost_beats,
    diagnose_drift,
)


class TestApplyDownbeatOffset:
    def test_zero_offset_returns_same_array(self):
        beats = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
        result = apply_downbeat_offset(beats, 0)
        np.testing.assert_array_equal(result, beats)

    def test_positive_offset_trims_start(self):
        beats = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
        result = apply_downbeat_offset(beats, 2)
        np.testing.assert_array_equal(result, np.array([1.0, 1.5, 2.0]))

    def test_offset_beyond_length_returns_same(self):
        beats = np.array([0.0, 0.5, 1.0])
        result = apply_downbeat_offset(beats, 10)
        np.testing.assert_array_equal(result, beats)

    def test_negative_offset_returns_same(self):
        beats = np.array([0.0, 0.5, 1.0])
        result = apply_downbeat_offset(beats, -1)
        np.testing.assert_array_equal(result, beats)


class TestFilterGhostBeats:
    def test_clean_grid_unchanged(self):
        """Evenly spaced beats should not be modified."""
        beats = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
        result, removed = filter_ghost_beats(beats)
        assert removed == 0
        np.testing.assert_array_equal(result, beats)

    def test_ghost_beat_removed(self):
        """A beat too close to the previous one should be filtered out."""
        # Regular 0.5s spacing, with a ghost at 1.15s (only 0.15s after 1.0)
        beats = np.array([0.0, 0.5, 1.0, 1.15, 1.5, 2.0, 2.5])
        result, removed = filter_ghost_beats(beats)
        assert removed == 1
        # 1.15 should be gone
        assert 1.15 not in result
        # The rest should survive
        assert len(result) == 6

    def test_multiple_ghosts_removed(self):
        """Multiple ghost beats in sequence."""
        # Ghosts at 0.6 and 1.6 (only 0.1s after real beats)
        beats = np.array([0.0, 0.5, 0.6, 1.0, 1.5, 1.6, 2.0, 2.5])
        result, removed = filter_ghost_beats(beats)
        assert removed == 2
        assert len(result) == 6

    def test_preserves_beat_after_gap(self):
        """If ghost removal creates a gap, the next beat is kept."""
        # 0.5s spacing, ghost at 0.85, then normal at 1.0
        beats = np.array([0.0, 0.5, 0.85, 1.0, 1.5, 2.0])
        result, removed = filter_ghost_beats(beats)
        # 0.85 removed (0.35s from 0.5, below 0.375 threshold at 0.75 * 0.5)
        assert removed >= 1
        # 1.0 should be kept (gap from 0.5 to 1.0 = 0.5s = normal)
        assert 1.0 in result

    def test_too_few_beats_unchanged(self):
        """Arrays with <3 beats should pass through."""
        beats = np.array([0.0, 0.5])
        result, removed = filter_ghost_beats(beats)
        assert removed == 0
        np.testing.assert_array_equal(result, beats)

    def test_definition_style_syncopation(self):
        """Simulate definition_explicit pattern: mostly 0.5s IBI with
        occasional 0.37s ghost snare hits."""
        # 8 beats at 120 BPM (0.5s), with ghosts at positions 3 and 7
        regular = [0.0, 0.5, 1.0, 1.37, 1.5, 2.0, 2.5, 2.87, 3.0, 3.5, 4.0]
        beats = np.array(regular)
        result, removed = filter_ghost_beats(beats)
        assert removed == 2  # 1.37 and 2.87 should be removed
        # Cleaned grid should be approximately even
        cleaned_ibis = np.diff(result)
        assert cleaned_ibis.std() / cleaned_ibis.mean() < 0.1  # CV < 10%


class TestFindBestDownbeatOffset:
    def test_returns_int_in_valid_range(self, tmp_path):
        """Synthesize a simple click track and verify offset is in range."""
        sr = 22050
        duration = 4.0
        bpm = 120.0
        beat_interval = 60.0 / bpm
        n_beats = int(duration / beat_interval)

        # Generate clicks on every beat
        y = np.zeros(int(sr * duration))
        for i in range(n_beats):
            sample = int(i * beat_interval * sr)
            if sample < len(y):
                # Short click impulse
                end = min(sample + 100, len(y))
                y[sample:end] = 0.8

        audio_path = tmp_path / "clicks.wav"
        import soundfile as sf
        sf.write(str(audio_path), y, sr)

        beat_times = np.array([i * beat_interval for i in range(n_beats)])
        offset = find_best_downbeat_offset(audio_path, beat_times, time_sig=4)

        assert isinstance(offset, int)
        assert 0 <= offset < 4


class TestDiagnoseDrift:
    def test_stable_tempo_has_low_drift(self, tmp_path):
        """A constant-tempo click track should show near-zero drift."""
        sr = 22050
        bpm = 120.0
        duration = 12.0  # long enough for 6 segments
        beat_interval = 60.0 / bpm

        y = np.zeros(int(sr * duration))
        n_beats = int(duration / beat_interval)
        for i in range(n_beats):
            sample = int(i * beat_interval * sr)
            if sample < len(y):
                end = min(sample + 100, len(y))
                y[sample:end] = 0.8

        audio_path = tmp_path / "stable.wav"
        import soundfile as sf
        sf.write(str(audio_path), y, sr)

        result = diagnose_drift(audio_path, n_segments=4)

        assert "drift_score" in result
        assert "tempos" in result
        assert len(result["tempos"]) > 0
        # Stable tempo should have low std relative to mean
        assert result["std"] < 5.0  # within 5 BPM
