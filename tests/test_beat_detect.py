"""Tests for neural beat + downbeat detection (beat_detect.py)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import soundfile as sf

from stemforge.beat_detect import (
    _fallback_librosa,
    _select_device,
    detect_beats_and_downbeats,
)


class TestSelectDevice:
    def test_explicit_cpu(self):
        assert _select_device("cpu") == "cpu"

    def test_explicit_mps(self):
        assert _select_device("mps") == "mps"

    def test_explicit_cuda(self):
        assert _select_device("cuda") == "cuda"

    def test_invalid_device_returns_cpu(self):
        assert _select_device("tpu") == "cpu"

    def test_auto_without_torch_returns_cpu(self):
        """When torch is not importable, auto should fall back to cpu."""
        with mock.patch.dict(sys.modules, {"torch": None}):
            assert _select_device("auto") == "cpu"


class TestFallbackLibrosa:
    def test_returns_three_element_tuple(self, tmp_path):
        """Librosa fallback should return (bpm, beats, empty_downbeats)."""
        sr = 22050
        duration = 4.0
        bpm = 120.0
        beat_interval = 60.0 / bpm

        # Synthesize a click track
        y = np.zeros(int(sr * duration))
        n_beats = int(duration / beat_interval)
        for i in range(n_beats):
            sample = int(i * beat_interval * sr)
            if sample < len(y):
                end = min(sample + 100, len(y))
                y[sample:end] = 0.8

        audio_path = tmp_path / "clicks.wav"
        sf.write(str(audio_path), y, sr)

        result_bpm, beats, downbeats = _fallback_librosa(audio_path)

        assert isinstance(result_bpm, float)
        assert result_bpm > 0
        assert len(beats) > 0
        # Fallback returns empty downbeats array
        assert len(downbeats) == 0
        assert downbeats.dtype == float


class TestBpmFromInterBeatIntervals:
    def test_bpm_calculation_accuracy(self):
        """Verify BPM = 60 / median(IBI) works for known tempo."""
        # Simulate 120 BPM: beats every 0.5 seconds
        beats = np.arange(0, 10.0, 0.5)
        ibis = np.diff(beats)
        bpm = 60.0 / float(np.median(ibis))
        assert abs(bpm - 120.0) < 0.01

    def test_bpm_calculation_with_jitter(self):
        """BPM should be robust to small timing jitter."""
        rng = np.random.default_rng(42)
        # 140 BPM with +/- 10ms jitter
        interval = 60.0 / 140.0
        beats = np.arange(0, 8.0, interval)
        beats += rng.uniform(-0.01, 0.01, size=len(beats))
        beats[0] = 0.0  # keep first beat at zero
        beats.sort()

        ibis = np.diff(beats)
        bpm = 60.0 / float(np.median(ibis))
        assert abs(bpm - 140.0) < 2.0  # within 2 BPM


class TestDetectBeatsAndDownbeats:
    def test_fallback_when_beat_this_not_installed(self, tmp_path):
        """When beat-this is not installed, should fall back to librosa."""
        sr = 22050
        duration = 4.0
        bpm = 120.0
        beat_interval = 60.0 / bpm

        y = np.zeros(int(sr * duration))
        n_beats = int(duration / beat_interval)
        for i in range(n_beats):
            sample = int(i * beat_interval * sr)
            if sample < len(y):
                end = min(sample + 100, len(y))
                y[sample:end] = 0.8

        audio_path = tmp_path / "clicks.wav"
        sf.write(str(audio_path), y, sr)

        # Force ImportError for beat_this
        with mock.patch.dict(sys.modules, {"beat_this": None, "beat_this.inference": None}):
            result_bpm, beats, downbeats = detect_beats_and_downbeats(audio_path)

        assert isinstance(result_bpm, float)
        assert result_bpm > 0
        assert len(beats) > 0
        # Fallback returns empty downbeats
        assert len(downbeats) == 0

    def test_with_mock_beat_this(self, tmp_path):
        """When beat-this is available, should return beats + downbeats."""
        sr = 22050
        duration = 8.0

        y = np.zeros(int(sr * duration))
        audio_path = tmp_path / "test.wav"
        sf.write(str(audio_path), y, sr)

        # Mock beat-this to return known values
        mock_beats = np.arange(0, 8.0, 0.5)      # 120 BPM
        mock_downbeats = np.arange(0, 8.0, 2.0)   # every 4 beats

        mock_model_instance = mock.MagicMock()
        mock_model_instance.return_value = (mock_beats, mock_downbeats)

        mock_file2beats = mock.MagicMock(return_value=mock_model_instance)

        mock_inference = mock.MagicMock()
        mock_inference.File2Beats = mock_file2beats

        with mock.patch.dict(sys.modules, {"beat_this": mock.MagicMock(), "beat_this.inference": mock_inference}):
            result_bpm, beats, downbeats = detect_beats_and_downbeats(audio_path)

        assert abs(result_bpm - 120.0) < 0.01
        np.testing.assert_array_equal(beats, mock_beats)
        np.testing.assert_array_equal(downbeats, mock_downbeats)

    def test_handles_beat_this_runtime_error(self, tmp_path):
        """If beat-this raises at runtime, should fall back gracefully."""
        sr = 22050
        duration = 4.0
        bpm = 120.0
        beat_interval = 60.0 / bpm

        y = np.zeros(int(sr * duration))
        n_beats = int(duration / beat_interval)
        for i in range(n_beats):
            sample = int(i * beat_interval * sr)
            if sample < len(y):
                end = min(sample + 100, len(y))
                y[sample:end] = 0.8

        audio_path = tmp_path / "clicks.wav"
        sf.write(str(audio_path), y, sr)

        # Mock beat-this to raise RuntimeError
        mock_inference = mock.MagicMock()
        mock_inference.File2Beats.side_effect = RuntimeError("model load failed")

        with mock.patch.dict(sys.modules, {"beat_this": mock.MagicMock(), "beat_this.inference": mock_inference}):
            result_bpm, beats, downbeats = detect_beats_and_downbeats(audio_path)

        # Should have fallen back to librosa
        assert isinstance(result_bpm, float)
        assert result_bpm > 0


class TestSliceAtBarsWithBarStartTimes:
    """Test that slice_at_bars accepts explicit bar_start_times."""

    def test_bar_start_times_used_when_provided(self, tmp_path):
        """When bar_start_times is given, beat_times stride is bypassed."""
        from stemforge.slicer import slice_at_bars

        sr = 22050
        duration = 8.0
        # Generate a simple tone so bars aren't silent
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        y = 0.5 * np.sin(2 * np.pi * 440 * t)

        stem_path = tmp_path / "tone.wav"
        sf.write(str(stem_path), y, sr)

        # Provide explicit bar starts at 0, 2, 4, 6 seconds (2-second bars)
        bar_starts = np.array([0.0, 2.0, 4.0, 6.0])

        result = slice_at_bars(
            stem_path=stem_path,
            output_dir=tmp_path,
            stem_name="test",
            bar_start_times=bar_starts,
        )

        assert len(result) == 4
        # Verify output files exist
        for p in result:
            assert p.exists()

    def test_falls_back_to_stride_without_bar_start_times(self, tmp_path):
        """Without bar_start_times, should use beat_times[::numerator]."""
        from stemforge.slicer import slice_at_bars

        sr = 22050
        duration = 8.0
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        y = 0.5 * np.sin(2 * np.pi * 440 * t)

        stem_path = tmp_path / "tone.wav"
        sf.write(str(stem_path), y, sr)

        # 120 BPM beats, 4/4 time -> bars every 2 seconds
        beat_times = np.arange(0, 8.0, 0.5)

        result = slice_at_bars(
            stem_path=stem_path,
            output_dir=tmp_path,
            stem_name="test",
            time_sig_numerator=4,
            beat_times=beat_times,
        )

        # 16 beats / 4 = 4 bars
        assert len(result) == 4
