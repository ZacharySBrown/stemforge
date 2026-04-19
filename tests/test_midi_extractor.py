"""Tests for MIDI extraction (pitch detection, note segmentation, key detection)."""

import numpy as np
import pytest
import soundfile as sf

from stemforge.midi_extractor import (
    detect_pitches,
    segment_notes,
    extract_root_sample,
    detect_key,
    build_chromatic_pads,
    build_scale_pads,
    split_notes_by_sections,
    extract_midi,
    hz_to_midi,
    midi_to_hz,
    midi_to_name,
    DetectedNote,
    MIDIClip,
)
from stemforge.segmenter import SongStructure, SongSegment

SR = 22050


def _write_pitched_stem(path, sr=SR, duration=4.0, freq=110.0):
    """Generate a simple pitched tone (A2 = 110 Hz by default)."""
    n = int(duration * sr)
    t = np.arange(n) / sr
    # Add some harmonics for realism
    audio = (
        0.5 * np.sin(2 * np.pi * freq * t)
        + 0.2 * np.sin(2 * np.pi * freq * 2 * t)
        + 0.1 * np.sin(2 * np.pi * freq * 3 * t)
    ).astype(np.float32)
    stereo = np.stack([audio, audio], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_24")


def _write_two_note_stem(path, sr=SR, duration=4.0, freq1=110.0, freq2=146.83):
    """Generate a stem with two distinct notes (A2 then D3 by default)."""
    n = int(duration * sr)
    mid = n // 2
    t1 = np.arange(mid) / sr
    t2 = np.arange(n - mid) / sr
    note1 = (0.5 * np.sin(2 * np.pi * freq1 * t1)).astype(np.float32)
    note2 = (0.5 * np.sin(2 * np.pi * freq2 * t2)).astype(np.float32)
    audio = np.concatenate([note1, note2])
    stereo = np.stack([audio, audio], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_24")


class TestUtilities:
    def test_hz_to_midi(self):
        assert hz_to_midi(440.0) == 69   # A4
        assert hz_to_midi(261.63) == 60  # C4
        assert hz_to_midi(110.0) == 45   # A2

    def test_midi_to_hz(self):
        assert abs(midi_to_hz(69) - 440.0) < 0.1
        assert abs(midi_to_hz(60) - 261.63) < 1.0

    def test_midi_to_name(self):
        assert midi_to_name(60) == "C4"
        assert midi_to_name(69) == "A4"
        assert midi_to_name(36) == "C2"
        assert midi_to_name(45) == "A2"

    def test_hz_to_midi_zero(self):
        assert hz_to_midi(0) == 0


class TestPitchDetection:
    def test_detects_pitch(self, tmp_path):
        stem = tmp_path / "pitched.wav"
        _write_pitched_stem(stem, freq=110.0)
        f0, voiced, prob, sr = detect_pitches(stem, "bass")

        # Should detect some voiced frames
        voiced_count = np.sum(voiced)
        assert voiced_count > 10, f"Expected voiced frames, got {voiced_count}"

        # Detected pitch should be near 110 Hz
        voiced_f0 = f0[voiced & ~np.isnan(f0)]
        if len(voiced_f0) > 0:
            median_f0 = float(np.median(voiced_f0))
            assert 90 < median_f0 < 130, f"Expected ~110 Hz, got {median_f0:.1f}"

    def test_unvoiced_silence(self, tmp_path):
        stem = tmp_path / "silence.wav"
        audio = np.zeros((int(2.0 * SR), 2), dtype=np.float32)
        sf.write(str(stem), audio, SR, subtype="PCM_24")
        f0, voiced, prob, sr = detect_pitches(stem, "bass")

        voiced_count = np.sum(voiced)
        assert voiced_count < len(voiced) * 0.1  # mostly unvoiced


class TestNoteSegmentation:
    def test_segments_single_note(self, tmp_path):
        stem = tmp_path / "note.wav"
        _write_pitched_stem(stem, freq=110.0, duration=2.0)
        f0, voiced, prob, sr = detect_pitches(stem, "bass")
        notes = segment_notes(f0, voiced, prob, sr)

        assert len(notes) >= 1
        # Should detect A2 (MIDI 45)
        assert any(44 <= n.midi_note <= 46 for n in notes), \
            f"Expected A2 (45), got {[n.midi_note for n in notes]}"

    def test_segments_two_notes(self, tmp_path):
        stem = tmp_path / "two_notes.wav"
        _write_two_note_stem(stem, freq1=110.0, freq2=146.83)
        f0, voiced, prob, sr = detect_pitches(stem, "bass")
        notes = segment_notes(f0, voiced, prob, sr)

        midi_notes = set(n.midi_note for n in notes)
        # Should detect at least 2 distinct pitches
        assert len(midi_notes) >= 2, f"Expected 2+ pitches, got {midi_notes}"

    def test_quantization(self, tmp_path):
        stem = tmp_path / "quantize.wav"
        _write_pitched_stem(stem, freq=110.0, duration=2.0)
        f0, voiced, prob, sr = detect_pitches(stem, "bass")

        notes = segment_notes(f0, voiced, prob, sr, quantize="1/16", bpm=120.0)
        if notes:
            # Grid at 120 BPM, 1/16 = 0.125s
            for n in notes:
                remainder = n.start_time % 0.125
                assert remainder < 0.001 or abs(remainder - 0.125) < 0.001, \
                    f"Note at {n.start_time} not quantized to 1/16 grid"

    def test_min_duration_filter(self, tmp_path):
        stem = tmp_path / "short.wav"
        _write_pitched_stem(stem, freq=110.0, duration=2.0)
        f0, voiced, prob, sr = detect_pitches(stem, "bass")

        # Very long min duration should filter most notes
        notes = segment_notes(f0, voiced, prob, sr, min_duration_s=5.0)
        assert len(notes) == 0  # nothing lasts 5 seconds


class TestRootSampleExtraction:
    def test_extracts_sample(self, tmp_path):
        stem = tmp_path / "stem.wav"
        _write_pitched_stem(stem, freq=110.0)

        notes = [
            DetectedNote(midi_note=45, start_time=0.5, end_time=1.5,
                        duration=1.0, velocity=100, confidence=0.9),
            DetectedNote(midi_note=45, start_time=2.0, end_time=2.5,
                        duration=0.5, velocity=80, confidence=0.7),
        ]

        out = tmp_path / "root.wav"
        path, root_midi = extract_root_sample(stem, notes, out)

        assert path.exists()
        assert root_midi == 45  # best note (highest score)
        info = sf.info(str(path))
        assert info.duration > 0
        assert info.duration <= 2.1  # max duration (+ pre-attack margin)

    def test_empty_notes(self, tmp_path):
        stem = tmp_path / "stem.wav"
        _write_pitched_stem(stem)
        out = tmp_path / "root.wav"
        path, root_midi = extract_root_sample(stem, [], out)
        assert root_midi == 60  # default


class TestKeyDetection:
    def test_detects_key(self, tmp_path):
        stem = tmp_path / "c_major.wav"
        # C major: C + E + G
        n = int(4.0 * SR)
        t = np.arange(n) / SR
        audio = (
            0.3 * np.sin(2 * np.pi * 261.63 * t)   # C4
            + 0.3 * np.sin(2 * np.pi * 329.63 * t)  # E4
            + 0.3 * np.sin(2 * np.pi * 392.00 * t)  # G4
        ).astype(np.float32)
        sf.write(str(stem), np.stack([audio, audio], axis=1), SR, subtype="PCM_24")

        key, mode = detect_key(stem)
        # Should detect C major (or relative A minor)
        assert key in ["C", "A"], f"Expected C or A, got {key}"


class TestPadMappings:
    def test_chromatic_12_pads(self):
        pads = build_chromatic_pads(36, n_pads=12)  # C2
        assert len(pads) == 12
        assert pads[0]["note_name"] == "C2"
        assert pads[11]["note_name"] == "B2"
        assert pads[0]["midi_note"] == 36
        assert pads[11]["midi_note"] == 47

    def test_scale_major(self):
        pads = build_scale_pads(36, key="C", mode="major", n_pads=8)
        assert len(pads) == 8
        # C major scale from C2: C D E F G A B C
        expected_names = ["C2", "D2", "E2", "F2", "G2", "A2", "B2", "C3"]
        actual_names = [p["note_name"] for p in pads]
        assert actual_names == expected_names, f"Expected {expected_names}, got {actual_names}"

    def test_scale_minor(self):
        pads = build_scale_pads(45, key="A", mode="minor", n_pads=8)
        assert len(pads) == 8
        # A minor from A2: A B C D E F G A
        assert pads[0]["note_name"] == "A2"
        assert pads[2]["note_name"] == "C3"  # minor 3rd

    def test_scale_degrees(self):
        pads = build_scale_pads(36, key="C", mode="major", n_pads=8)
        degrees = [p["scale_degree"] for p in pads]
        assert degrees == [1, 2, 3, 4, 5, 6, 7, 8]


class TestSectionSplitting:
    def test_no_structure_single_clip(self):
        notes = [DetectedNote(45, 0, 1, 1, 100, 0.9)]
        clips = split_notes_by_sections(notes, None)
        assert len(clips) == 1
        assert clips[0].section_label == "full"

    def test_splits_by_section(self):
        notes = [
            DetectedNote(45, 0.5, 1.0, 0.5, 100, 0.9),
            DetectedNote(47, 1.5, 2.0, 0.5, 90, 0.8),
            DetectedNote(48, 3.5, 4.0, 0.5, 80, 0.7),
        ]
        structure = SongStructure(
            segments=[
                SongSegment("A", 1, 2, 0.0, 2.5, 0.5, False),
                SongSegment("B", 3, 4, 2.5, 5.0, 0.5, False),
            ],
            form="AB", boundaries_bars=[3],
            bar_importance={}, total_bars=4,
        )
        clips = split_notes_by_sections(notes, structure)
        assert len(clips) == 2
        assert clips[0].section_label == "A"
        assert len(clips[0].notes) == 2  # notes at 0.5 and 1.5
        assert clips[1].section_label == "B"
        assert len(clips[1].notes) == 1  # note at 3.5

    def test_adjusts_time_to_section_relative(self):
        notes = [DetectedNote(45, 5.0, 6.0, 1.0, 100, 0.9)]
        structure = SongStructure(
            segments=[SongSegment("B", 3, 4, 4.0, 8.0, 0.5, False)],
            form="B", boundaries_bars=[], bar_importance={}, total_bars=4,
        )
        clips = split_notes_by_sections(notes, structure)
        assert len(clips) == 1
        # Note at 5.0 in section starting at 4.0 → relative time 1.0
        assert abs(clips[0].notes[0].start_time - 1.0) < 0.01


class TestFullExtraction:
    def test_extract_midi_basic(self, tmp_path):
        stem = tmp_path / "bass.wav"
        _write_pitched_stem(stem, freq=110.0, duration=4.0)
        output = tmp_path / "output"

        result = extract_midi(stem, output, stem_name="bass", bpm=120.0)

        assert result.root_sample_path is not None
        assert result.root_sample_path.exists()
        assert result.detected_key in ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        assert len(result.chromatic_pads) == 12
        assert len(result.scale_pads) == 8
        assert len(result.clips) >= 1

        # Check MIDI dir structure
        midi_dir = output / "midi"
        assert midi_dir.exists()
        assert (midi_dir / "midi_manifest.json").exists()
        assert (midi_dir / "bass_root.wav").exists()

    def test_extract_midi_with_structure(self, tmp_path):
        stem = tmp_path / "bass.wav"
        _write_two_note_stem(stem, freq1=110.0, freq2=146.83, duration=4.0)
        output = tmp_path / "output"

        structure = SongStructure(
            segments=[
                SongSegment("A", 1, 2, 0.0, 2.0, 0.5, False),
                SongSegment("B", 3, 4, 2.0, 4.0, 0.5, False),
            ],
            form="AB", boundaries_bars=[3],
            bar_importance={}, total_bars=4,
        )

        result = extract_midi(stem, output, stem_name="bass", bpm=120.0,
                            song_structure=structure)

        assert len(result.clips) == 2
        assert result.clips[0].section_label == "A"
        assert result.clips[1].section_label == "B"
