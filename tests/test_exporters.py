"""Tests for hardware sample exporters (EP-133 + Chompi)."""

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stemforge.exporters import ExportTarget, ExportWorkflow
from stemforge.exporters.base import (
    resample_audio, to_mono, to_stereo, peak_normalize,
    trim_to_duration, write_export_wav, ExportManifest, ExportSlot,
)
from stemforge.exporters.ep133 import EP133Exporter
from stemforge.exporters.chompi import ChompiExporter, _bar_align_trim

SR = 44100


def _make_stem(path, sr=SR, duration=3.0, freq=440.0):
    """Write a synthetic stereo WAV."""
    n = int(duration * sr)
    t = np.arange(n) / sr
    mono = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    stereo = np.stack([mono, mono], axis=1)
    sf.write(str(path), stereo, sr, subtype="PCM_24")


def _make_track_dir(tmp_path, track_name="test_track", bpm=120.0):
    """Create a minimal processed track directory with stems + beats."""
    td = tmp_path / track_name
    td.mkdir(parents=True)

    # Create stems
    for stem, freq in [("drums", 100), ("bass", 80), ("vocals", 300), ("other", 500)]:
        _make_stem(td / f"{stem}.wav", freq=freq)

    # Create beat slices
    for stem in ["drums", "bass", "vocals"]:
        beats_dir = td / f"{stem}_beats"
        beats_dir.mkdir()
        for i in range(8):
            _make_stem(beats_dir / f"{stem}_beat_{i+1:03d}.wav", duration=0.5, freq=100 + i * 50)

    # Create curated bars
    curated = td / "curated"
    for stem in ["drums", "bass", "vocals", "other"]:
        stem_dir = curated / stem
        stem_dir.mkdir(parents=True)
        for i in range(4):
            _make_stem(stem_dir / f"bar_{i+1:03d}.wav", duration=2.0, freq=100 + i * 30)

        # Oneshots subdir for drums
        if stem == "drums":
            os_dir = stem_dir / "oneshots"
            os_dir.mkdir()
            for i in range(6):
                _make_stem(os_dir / f"os_{i+1:03d}.wav", duration=0.3, freq=60 + i * 100)

    # Write manifest with BPM
    manifest = {"track": track_name, "bpm": bpm, "stems": {}}
    (curated / "manifest.json").write_text(json.dumps(manifest))
    (td / "stems.json").write_text(json.dumps({"bpm": bpm, "track_name": track_name}))

    return td


# ── Base utilities ───────────────────────────────────────────────────────

class TestBaseUtilities:
    def test_resample_mono(self):
        audio = np.random.randn(44100).astype(np.float32)
        resampled = resample_audio(audio, 44100, 22050)
        assert len(resampled) == 22050

    def test_resample_stereo(self):
        audio = np.random.randn(2, 44100).astype(np.float32)
        resampled = resample_audio(audio, 44100, 48000)
        assert resampled.shape[0] == 2
        assert abs(resampled.shape[1] - 48000) < 10  # close to expected

    def test_resample_noop(self):
        audio = np.random.randn(1000).astype(np.float32)
        result = resample_audio(audio, 44100, 44100)
        np.testing.assert_array_equal(result, audio)

    def test_to_mono(self):
        stereo = np.array([[1.0, 2.0, 3.0], [3.0, 2.0, 1.0]])
        mono = to_mono(stereo)
        np.testing.assert_array_almost_equal(mono, [2.0, 2.0, 2.0])

    def test_to_mono_already_mono(self):
        mono = np.array([1.0, 2.0, 3.0])
        result = to_mono(mono)
        np.testing.assert_array_equal(result, mono)

    def test_to_stereo(self):
        mono = np.array([1.0, 2.0, 3.0])
        stereo = to_stereo(mono)
        assert stereo.shape == (2, 3)
        np.testing.assert_array_equal(stereo[0], stereo[1])

    def test_to_stereo_already_stereo(self):
        stereo = np.array([[1.0, 2.0], [3.0, 4.0]])
        result = to_stereo(stereo)
        np.testing.assert_array_equal(result, stereo)

    def test_peak_normalize(self):
        audio = np.array([0.0, 0.25, 0.5, -0.5])
        normalized = peak_normalize(audio, headroom_db=-1.0)
        target = 10 ** (-1.0 / 20)
        assert abs(np.max(np.abs(normalized)) - target) < 0.001

    def test_peak_normalize_silence(self):
        audio = np.zeros(100)
        result = peak_normalize(audio)
        np.testing.assert_array_equal(result, audio)

    def test_trim_to_duration_mono(self):
        audio = np.random.randn(44100 * 5).astype(np.float32)
        trimmed = trim_to_duration(audio, 44100, 2.0)
        assert len(trimmed) == 44100 * 2

    def test_trim_to_duration_stereo(self):
        audio = np.random.randn(2, 44100 * 5).astype(np.float32)
        trimmed = trim_to_duration(audio, 44100, 3.0)
        assert trimmed.shape == (2, 44100 * 3)

    def test_write_export_wav_16bit(self, tmp_path):
        audio = np.random.randn(1000).astype(np.float32) * 0.5
        path = tmp_path / "test.wav"
        size = write_export_wav(audio, 44100, path, bit_depth=16)
        assert path.exists()
        assert size > 0
        info = sf.info(str(path))
        assert info.subtype == "PCM_16"

    def test_write_export_wav_stereo(self, tmp_path):
        audio = np.random.randn(2, 1000).astype(np.float32) * 0.5
        path = tmp_path / "test_stereo.wav"
        size = write_export_wav(audio, 48000, path, bit_depth=16)
        info = sf.info(str(path))
        assert info.channels == 2
        assert info.samplerate == 48000


class TestExportManifest:
    def test_memory_pct(self):
        m = ExportManifest(device="test", workflow="compose",
                          memory_used_bytes=1024, memory_total_bytes=4096)
        assert m.memory_pct == 25.0

    def test_memory_pct_zero(self):
        m = ExportManifest(device="test", workflow="compose",
                          memory_used_bytes=0, memory_total_bytes=0)
        assert m.memory_pct == 0

    def test_to_dict(self):
        m = ExportManifest(device="ep133", workflow="compose",
                          sample_rate=46875, slots=[
                              ExportSlot(slot=1, group="A", pad=1, file="test.wav",
                                        duration_s=0.5, size_bytes=1024)
                          ])
        d = m.to_dict()
        assert d["device"] == "ep133"
        assert len(d["slots"]) == 1
        assert d["slots"][0]["group"] == "A"

    def test_write(self, tmp_path):
        m = ExportManifest(device="chompi", workflow="perform",
                          exported_at="2026-04-19T00:00:00Z")
        path = tmp_path / "export.json"
        m.write(path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["device"] == "chompi"


# ── EP-133 ───────────────────────────────────────────────────────────────

class TestEP133Exporter:
    def test_properties(self):
        e = EP133Exporter()
        assert e.device_name == "ep133"
        assert e.target_sample_rate == 46875
        assert e.target_channels == 1
        assert e.target_bit_depth == 16
        assert e.max_sample_duration_s == 20.0

    def test_budget_mode(self):
        e = EP133Exporter(budget=True)
        assert e.target_sample_rate == 22050

    def test_export_compose(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "ep133_out"
        e = EP133Exporter()
        manifest = e.export_compose(td, output)

        assert output.exists()
        assert (output / "export.json").exists()
        assert len(manifest.slots) > 0
        assert manifest.device == "ep133"
        assert manifest.workflow == "compose"
        assert manifest.memory_used_bytes > 0

        # All output files should be mono 46875 Hz 16-bit
        for slot in manifest.slots[:3]:
            info = sf.info(str(output / slot.file))
            assert info.channels == 1, f"{slot.file} should be mono"
            assert info.samplerate == 46875
            assert info.subtype == "PCM_16"

    def test_export_compose_budget(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "ep133_budget"
        e = EP133Exporter(budget=True)
        manifest = e.export_compose(td, output)

        for slot in manifest.slots[:3]:
            info = sf.info(str(output / slot.file))
            assert info.samplerate == 22050

    def test_export_compose_groups(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "ep133_groups"
        e = EP133Exporter()
        manifest = e.export_compose(td, output)

        groups = {s.group for s in manifest.slots}
        assert "A" in groups  # drums
        assert "D" in groups  # loops

    def test_export_compose_max_pads(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "ep133_pads"
        e = EP133Exporter()
        manifest = e.export_compose(td, output)

        # No group should exceed 12 pads
        from collections import Counter
        group_counts = Counter(s.group for s in manifest.slots)
        for group, count in group_counts.items():
            assert count <= 12, f"Group {group} has {count} slots (max 12)"

    def test_export_perform(self, tmp_path):
        # Create 3 track dirs
        for i in range(3):
            _make_track_dir(tmp_path / "tracks", f"track_{i+1}")
        output = tmp_path / "ep133_perform"
        e = EP133Exporter()
        manifest = e.export_perform(tmp_path / "tracks", output)

        assert len(manifest.source_tracks) == 3
        assert manifest.workflow == "perform"
        assert len(manifest.slots) > 0

    def test_memory_budget_tracking(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "ep133_mem"
        e = EP133Exporter()
        manifest = e.export_compose(td, output)

        # Memory should be sum of all file sizes
        total_from_slots = sum(s.size_bytes for s in manifest.slots)
        assert manifest.memory_used_bytes == total_from_slots
        assert manifest.memory_pct < 100  # should be well under limit


# ── Chompi ───────────────────────────────────────────────────────────────

class TestChompiExporter:
    def test_properties(self):
        e = ChompiExporter()
        assert e.device_name == "chompi"
        assert e.target_sample_rate == 48000
        assert e.target_channels == 2
        assert e.target_bit_depth == 16
        assert e.max_sample_duration_s == 10.0

    def test_export_compose(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "chompi_out"
        e = ChompiExporter()
        manifest = e.export_compose(td, output)

        assert output.exists()
        assert (output / "export.json").exists()
        assert manifest.device == "chompi"
        assert len(manifest.slots) > 0

        # All output files should be stereo 48000 Hz 16-bit
        for slot in manifest.slots[:3]:
            info = sf.info(str(output / slot.file))
            assert info.channels == 2, f"{slot.file} should be stereo"
            assert info.samplerate == 48000
            assert info.subtype == "PCM_16"

    def test_chompi_naming_convention(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "chompi_naming"
        e = ChompiExporter()
        manifest = e.export_compose(td, output)

        filenames = [s.file for s in manifest.slots]
        slice_files = [f for f in filenames if f.startswith("slice_a")]
        chroma_files = [f for f in filenames if f.startswith("chroma_a")]

        assert len(slice_files) > 0, "Should have slice files"
        # Verify naming: slice_a1.wav through slice_a14.wav
        for f in slice_files:
            assert f.startswith("slice_a"), f"Bad naming: {f}"
            assert f.endswith(".wav"), f"Bad extension: {f}"

    def test_chompi_flat_directory(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "chompi_flat"
        e = ChompiExporter()
        e.export_compose(td, output)

        # No subdirectories — Chompi requires flat SD root
        subdirs = [p for p in output.iterdir() if p.is_dir()]
        assert len(subdirs) == 0, f"Chompi output must be flat, found dirs: {subdirs}"

    def test_chompi_max_slots(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "chompi_slots"
        e = ChompiExporter()
        manifest = e.export_compose(td, output)

        slice_count = sum(1 for s in manifest.slots if s.group == "slice")
        chroma_count = sum(1 for s in manifest.slots if s.group == "chroma")
        assert slice_count <= 14, f"Too many slice slots: {slice_count}"
        assert chroma_count <= 14, f"Too many chroma slots: {chroma_count}"

    def test_chompi_max_duration(self, tmp_path):
        td = _make_track_dir(tmp_path)
        output = tmp_path / "chompi_dur"
        e = ChompiExporter()
        manifest = e.export_compose(td, output)

        for slot in manifest.slots:
            assert slot.duration_s <= 10.0, f"{slot.file}: {slot.duration_s}s exceeds 10s max"

    def test_export_perform(self, tmp_path):
        for i in range(3):
            _make_track_dir(tmp_path / "tracks", f"track_{i+1}")
        output = tmp_path / "chompi_perform"
        e = ChompiExporter()
        manifest = e.export_perform(tmp_path / "tracks", output)

        assert len(manifest.source_tracks) == 3
        assert manifest.workflow == "perform"


class TestBarAlignTrim:
    def test_trim_at_120bpm(self):
        sr = 48000
        bpm = 120.0
        # 4 bars at 120 BPM, 4/4 = 8 seconds
        audio = np.random.randn(sr * 12).astype(np.float32)  # 12 seconds
        trimmed = _bar_align_trim(audio, sr, bpm, time_sig=4)
        bar_dur = (60.0 / bpm) * 4  # 2.0 seconds per bar
        expected_bars = int(min(12, 10.0) / bar_dur)  # 5 bars in 10s
        expected_samples = int(expected_bars * bar_dur * sr)
        assert len(trimmed) == expected_samples

    def test_trim_preserves_stereo(self):
        sr = 48000
        audio = np.random.randn(2, sr * 8).astype(np.float32)
        trimmed = _bar_align_trim(audio, sr, 120.0)
        assert trimmed.shape[0] == 2

    def test_zero_bpm_fallback(self):
        sr = 48000
        audio = np.random.randn(sr * 15).astype(np.float32)
        trimmed = _bar_align_trim(audio, sr, 0)
        assert len(trimmed) == sr * 10  # falls back to max duration


# ── CLI ──────────────────────────────────────────────────────────────────

class TestExportCLI:
    def test_help(self, tmp_path):
        from click.testing import CliRunner
        from stemforge.cli import cli
        result = CliRunner().invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert "ep133" in result.output
        assert "chompi" in result.output

    def test_dry_run(self, tmp_path):
        td = _make_track_dir(tmp_path)
        from click.testing import CliRunner
        from stemforge.cli import cli
        result = CliRunner().invoke(cli, [
            "export", str(td), "--target", "ep133", "--dry-run",
        ])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
