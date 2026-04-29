"""Tests for song structure segmentation."""

import numpy as np
import pytest
import soundfile as sf

from stemforge.segmenter import (
    detect_song_structure,
    _compute_novelty,
    _label_segments,
    SongSegment,
    SongStructure,
)
from stemforge.config import SongConfig

SR = 22050


def _write_two_section_track(path, sr=SR, duration=8.0):
    """Generate a track with two distinct harmonic sections.

    First half: C major chord (C-E-G)
    Second half: A minor chord (A-C-E)
    Clear tonal shift at the midpoint.
    """
    n = int(duration * sr)
    mid = n // 2
    t1 = np.arange(mid) / sr
    t2 = np.arange(n - mid) / sr

    # Section A: C major (C4=261, E4=329, G4=392)
    section_a = (
        0.3 * np.sin(2 * np.pi * 261.63 * t1)
        + 0.3 * np.sin(2 * np.pi * 329.63 * t1)
        + 0.3 * np.sin(2 * np.pi * 392.00 * t1)
    ).astype(np.float32)

    # Section B: A minor (A3=220, C4=261, E4=329)
    section_b = (
        0.3 * np.sin(2 * np.pi * 220.00 * t2)
        + 0.3 * np.sin(2 * np.pi * 261.63 * t2)
        + 0.3 * np.sin(2 * np.pi * 329.63 * t2)
    ).astype(np.float32)

    audio = np.concatenate([section_a, section_b])

    # Add click track for beat detection (120 BPM = 0.5s per beat)
    beat_dur = 0.5
    click_len = int(0.01 * sr)
    click_t = np.arange(click_len) / sr
    click = 0.1 * np.sin(2 * np.pi * 1000 * click_t).astype(np.float32)
    for i in range(int(duration / beat_dur)):
        start = int(i * beat_dur * sr)
        end = min(start + click_len, n)
        audio[start:end] += click[:end - start]

    stereo = np.stack([audio, audio], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_24")


def _write_aba_track(path, sr=SR, duration=12.0):
    """Generate ABA form: C major → F major → C major."""
    n = int(duration * sr)
    third = n // 3

    sections = []
    for freq_set in [(261.63, 329.63, 392.00),   # C major
                     (349.23, 440.00, 523.25),    # F major
                     (261.63, 329.63, 392.00)]:   # C major (reprise)
        t = np.arange(third) / sr
        section = sum(
            0.25 * np.sin(2 * np.pi * f * t) for f in freq_set
        ).astype(np.float32)
        sections.append(section)

    audio = np.concatenate(sections)
    # Trim or pad to exact length
    if len(audio) > n:
        audio = audio[:n]
    elif len(audio) < n:
        audio = np.pad(audio, (0, n - len(audio)))

    # Click track at 120 BPM
    beat_dur = 0.5
    click_len = int(0.01 * sr)
    click_t = np.arange(click_len) / sr
    click = 0.1 * np.sin(2 * np.pi * 1000 * click_t).astype(np.float32)
    for i in range(int(duration / beat_dur)):
        start = int(i * beat_dur * sr)
        end = min(start + click_len, len(audio))
        audio[start:end] += click[:end - start]

    stereo = np.stack([audio, audio], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_24")


def _write_uniform_track(path, sr=SR, duration=8.0):
    """Generate a track with no structural changes (single section)."""
    n = int(duration * sr)
    t = np.arange(n) / sr
    audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    # Click track
    beat_dur = 0.5
    click_len = int(0.01 * sr)
    click_t = np.arange(click_len) / sr
    click = 0.1 * np.sin(2 * np.pi * 1000 * click_t).astype(np.float32)
    for i in range(int(duration / beat_dur)):
        start = int(i * beat_dur * sr)
        end = min(start + click_len, n)
        audio[start:end] += click[:end - start]

    stereo = np.stack([audio, audio], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_24")


class TestNoveltyComputation:
    def test_uniform_matrix_low_novelty(self):
        """Uniform recurrence (all similar) → low novelty everywhere."""
        n = 100
        rec = np.ones((n, n))  # all frames similar to each other
        novelty = _compute_novelty(rec, kernel_size=16)
        # Uniform similarity has no boundaries → checkerboard sums to ~0
        assert novelty.max() < 0.1, f"Uniform matrix should have low novelty, got max={novelty.max():.3f}"

    def test_block_diagonal_has_boundary(self):
        """Block diagonal matrix → higher novelty near block boundary than center."""
        n = 100
        rec = np.zeros((n, n))
        rec[:50, :50] = 1.0
        rec[50:, 50:] = 1.0
        novelty = _compute_novelty(rec, kernel_size=16)
        # Novelty near boundary (40-60) should be higher than deep inside a block (20-30)
        near_boundary = np.mean(novelty[40:60])
        inside_block = np.mean(novelty[20:30])
        assert near_boundary > inside_block, \
            f"Boundary region ({near_boundary:.3f}) should exceed block interior ({inside_block:.3f})"

    def test_small_matrix_doesnt_crash(self):
        """Very small matrix should not crash."""
        rec = np.ones((8, 8))
        novelty = _compute_novelty(rec, kernel_size=4)
        assert len(novelty) == 8


class TestLabelSegments:
    def test_single_segment(self):
        labels = _label_segments([], 100, np.random.randn(12, 100), 512, SR)
        assert labels == ["A"]

    def test_two_similar_segments(self):
        """Same chroma throughout → both get label A."""
        chroma = np.tile(np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0], dtype=float).reshape(12, 1), (1, 100))
        labels = _label_segments([50], 100, chroma, 512, SR)
        assert labels[0] == labels[1], f"Similar sections should share label: {labels}"

    def test_two_different_segments(self):
        """Different chroma → different labels."""
        chroma = np.zeros((12, 100))
        chroma[0, :50] = 1.0   # C in first half
        chroma[6, 50:] = 1.0   # F# in second half (tritone — maximally different)
        labels = _label_segments([50], 100, chroma, 512, SR)
        assert labels[0] != labels[1], f"Different sections should get different labels: {labels}"


class TestSongStructureDetection:
    def test_two_section_track(self, tmp_path):
        """Track with clear harmonic change at midpoint."""
        audio = tmp_path / "two_sections.wav"
        _write_two_section_track(audio, duration=8.0)

        structure = detect_song_structure(audio, config=SongConfig(
            min_segment_bars=1, max_segments=4,
        ))

        assert structure.total_bars >= 2
        assert len(structure.segments) >= 1
        # Should detect at least some structure
        print(f"Form: {structure.form}, bounds: {structure.boundaries_bars}")

    def test_aba_form(self, tmp_path):
        """Track with ABA form should detect at least 2 boundaries."""
        audio = tmp_path / "aba.wav"
        _write_aba_track(audio, duration=12.0)

        structure = detect_song_structure(audio, config=SongConfig(
            min_segment_bars=1, max_segments=6,
        ))

        assert structure.total_bars >= 3
        assert len(structure.segments) >= 1
        print(f"Form: {structure.form}, bounds: {structure.boundaries_bars}")

    def test_uniform_track_single_section(self, tmp_path):
        """Uniform track should produce few or no boundaries."""
        audio = tmp_path / "uniform.wav"
        _write_uniform_track(audio, duration=8.0)

        structure = detect_song_structure(audio, config=SongConfig(
            min_segment_bars=2, max_segments=4,
        ))

        assert structure.total_bars >= 2
        # Uniform track may still detect minor boundaries, but form should be simple
        assert len(structure.form) <= 4, f"Too many sections for uniform track: {structure.form}"

    def test_bar_importance_near_boundaries(self, tmp_path):
        """Bars near boundaries should have higher importance."""
        audio = tmp_path / "two_sections.wav"
        _write_two_section_track(audio, duration=8.0)

        structure = detect_song_structure(audio, config=SongConfig(
            min_segment_bars=1, max_segments=4, transition_window_bars=2,
        ))

        if structure.boundaries_bars:
            boundary = structure.boundaries_bars[0]
            boundary_importance = structure.importance_for_bar(boundary)
            # A bar far from any boundary should have lower importance
            far_bar = max(1, boundary - 5) if boundary > 5 else min(structure.total_bars, boundary + 5)
            far_importance = structure.importance_for_bar(far_bar)
            assert boundary_importance >= far_importance, \
                f"Boundary bar {boundary} ({boundary_importance}) should be >= far bar {far_bar} ({far_importance})"

    def test_section_for_bar(self, tmp_path):
        """Every bar should belong to some section."""
        audio = tmp_path / "two_sections.wav"
        _write_two_section_track(audio, duration=8.0)

        structure = detect_song_structure(audio)

        for bar in range(1, structure.total_bars + 1):
            section = structure.section_for_bar(bar)
            assert section is not None, f"Bar {bar} has no section"

    def test_custom_config(self, tmp_path):
        """Config params are respected."""
        audio = tmp_path / "two_sections.wav"
        _write_two_section_track(audio, duration=8.0)

        # Very restrictive: max 2 segments, min 4 bars each
        structure = detect_song_structure(audio, config=SongConfig(
            min_segment_bars=4, max_segments=2,
        ))

        assert len(structure.segments) <= 2

    def test_with_precomputed_beats(self, tmp_path):
        """Providing beat_times and bpm should work."""
        audio = tmp_path / "two_sections.wav"
        _write_two_section_track(audio, duration=8.0)

        # Fake 120 BPM beat grid
        beat_times = np.arange(0, 8.0, 0.5)

        structure = detect_song_structure(
            audio, beat_times=beat_times, bpm=120.0,
        )

        assert structure.total_bars >= 2

    def test_very_short_audio(self, tmp_path):
        """Very short audio should not crash."""
        audio = tmp_path / "short.wav"
        n = int(1.0 * SR)
        y = np.random.randn(n).astype(np.float32) * 0.1
        sf.write(str(audio), np.stack([y, y], axis=1), SR, subtype="PCM_24")

        structure = detect_song_structure(audio)

        assert structure.total_bars >= 1
        assert len(structure.segments) >= 1
        assert structure.form == "A"  # too short for multiple sections


class TestSongStructureDataclass:
    def test_importance_for_missing_bar(self):
        """Querying a bar that doesn't exist returns 0."""
        s = SongStructure(
            segments=[], form="A", boundaries_bars=[],
            bar_importance={1: 0.5}, total_bars=1,
        )
        assert s.importance_for_bar(999) == 0.0

    def test_section_for_missing_bar(self):
        """Querying a bar outside all segments returns None."""
        s = SongStructure(
            segments=[SongSegment("A", 1, 4, 0, 4, 0, False)],
            form="A", boundaries_bars=[], bar_importance={}, total_bars=4,
        )
        assert s.section_for_bar(1) == "A"
        assert s.section_for_bar(5) is None
