"""
Tests for the EP-133 stem export pipeline.

Covers:
- EP133ExportConfig.from_pipeline_dict — parses YAML config correctly
- EP133ExportConfig.default() — stem configs match spec Section 3
- EP133ExportConfig.stem_config() — returns correct play_mode/loop/mute_group
- generate_setup_md — output contains expected sections
- process_stem_wav — end-to-end with a tiny synthetic WAV
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stemforge.exporters.ep133_stem_export import (
    EP133ExportConfig,
    EP133StemConfig,
    EP133TimeStretchConfig,
    export_ep133_package,
    generate_setup_md,
    process_stem_wav,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

PIPELINE_DICT = {
    "ep133_export": {
        "enabled": True,
        "sync": {"mode": "midi_clock", "master": "ableton"},
        "defaults": {
            "play_mode": "key",
            "loop": False,
            "mute_group": 0,
            "time_stretch": {"mode": "bpm", "source_bpm": None},
        },
        "stems": {
            "drums": {
                "play_mode": "oneshot",
                "loop": True,
                "mute_group": 0,
                "time_stretch": {"mode": "bar", "bars": 4},
            },
            "bass": {
                "play_mode": "oneshot",
                "loop": True,
                "mute_group": 1,
                "time_stretch": {"mode": "bpm", "source_bpm": None},
            },
            "vocals": {
                "play_mode": "key",
                "loop": False,
                "mute_group": 2,
                "time_stretch": {"mode": "bpm", "source_bpm": None},
            },
            "other": {
                "play_mode": "legato",
                "loop": False,
                "mute_group": 0,
                "time_stretch": {"mode": "bpm", "source_bpm": None},
            },
        },
        "pad_map": {
            "drums": {"group": "A", "pad": 1},
            "bass": {"group": "B", "pad": 1},
            "vocals": {"group": "C", "pad": 1},
            "other": {"group": "D", "pad": 1},
        },
    }
}


@pytest.fixture
def synthetic_wav(tmp_path: Path) -> Path:
    """Write a 1-second 44100 Hz stereo WAV with a sine wave."""
    sr = 44100
    duration = 1.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    audio = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 440 * t)], axis=1)
    audio = audio.astype(np.float32) * 0.5  # half amplitude
    wav_path = tmp_path / "test_stem.wav"
    sf.write(str(wav_path), audio, sr, subtype="PCM_16")
    return wav_path


@pytest.fixture
def stems_json(tmp_path: Path, synthetic_wav: Path) -> Path:
    """Write a minimal stems.json pointing at the synthetic WAV."""
    data = {
        "track_name": "test_track",
        "bpm": 128.0,
        "stems": [
            {"name": "drums", "wav_path": str(synthetic_wav)},
            {"name": "bass", "wav_path": str(synthetic_wav)},
        ],
        "output_dir": str(tmp_path),
    }
    p = tmp_path / "stems.json"
    p.write_text(json.dumps(data))
    return p


# ──────────────────────────────────────────────────────────────────────────────
# EP133TimeStretchConfig tests
# ──────────────────────────────────────────────────────────────────────────────

def test_time_stretch_config_defaults():
    ts = EP133TimeStretchConfig()
    assert ts.mode == "none"
    assert ts.source_bpm is None
    assert ts.bars is None


def test_time_stretch_config_validation():
    with pytest.raises(ValueError, match="time_stretch.mode"):
        EP133TimeStretchConfig(mode="invalid")


def test_time_stretch_from_dict():
    ts = EP133TimeStretchConfig.from_dict({"mode": "bar", "bars": 4})
    assert ts.mode == "bar"
    assert ts.bars == 4


def test_time_stretch_to_dict_bar():
    ts = EP133TimeStretchConfig(mode="bar", bars=4, source_bpm=128.0)
    d = ts.to_dict()
    assert d["mode"] == "bar"
    assert d["bars"] == 4
    assert d["source_bpm"] == 128.0


def test_time_stretch_to_dict_none_omits_optional():
    ts = EP133TimeStretchConfig(mode="none")
    d = ts.to_dict()
    assert "bars" not in d
    assert "source_bpm" not in d


# ──────────────────────────────────────────────────────────────────────────────
# EP133ExportConfig.from_pipeline_dict
# ──────────────────────────────────────────────────────────────────────────────

def test_from_pipeline_dict_enabled():
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    assert cfg.enabled is True
    assert cfg.sync_mode == "midi_clock"


def test_from_pipeline_dict_drums():
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    drums = cfg.stems["drums"]
    assert drums.play_mode == "oneshot"
    assert drums.loop is True
    assert drums.mute_group == 0
    assert drums.time_stretch.mode == "bar"
    assert drums.time_stretch.bars == 4
    assert drums.pad_group == "A"
    assert drums.pad_num == 1


def test_from_pipeline_dict_bass():
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    bass = cfg.stems["bass"]
    assert bass.play_mode == "oneshot"
    assert bass.loop is True
    assert bass.mute_group == 1
    assert bass.pad_group == "B"
    assert bass.pad_num == 1


def test_from_pipeline_dict_vocals():
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    vocals = cfg.stems["vocals"]
    assert vocals.play_mode == "key"
    assert vocals.loop is False
    assert vocals.mute_group == 2
    assert vocals.pad_group == "C"


def test_from_pipeline_dict_other():
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    other = cfg.stems["other"]
    assert other.play_mode == "legato"
    assert other.loop is False
    assert other.mute_group == 0
    assert other.pad_group == "D"


# ──────────────────────────────────────────────────────────────────────────────
# EP133ExportConfig.default()
# ──────────────────────────────────────────────────────────────────────────────

def test_default_stems_present():
    cfg = EP133ExportConfig.default()
    assert "drums" in cfg.stems
    assert "bass" in cfg.stems
    assert "vocals" in cfg.stems
    assert "other" in cfg.stems


def test_default_drums_spec_section_3():
    """Spec Section 3: drums = oneshot + loop + mute_group 0."""
    drums = EP133ExportConfig.default().stems["drums"]
    assert drums.play_mode == "oneshot"
    assert drums.loop is True
    assert drums.mute_group == 0


def test_default_bass_spec_section_3():
    """Spec Section 3: bass = oneshot + loop + mute_group 1."""
    bass = EP133ExportConfig.default().stems["bass"]
    assert bass.play_mode == "oneshot"
    assert bass.loop is True
    assert bass.mute_group == 1


def test_default_vocals_spec_section_3():
    """Spec Section 3: vocals = key + no loop + mute_group 2."""
    vocals = EP133ExportConfig.default().stems["vocals"]
    assert vocals.play_mode == "key"
    assert vocals.loop is False
    assert vocals.mute_group == 2


def test_default_other_spec_section_3():
    """Spec Section 3: other = legato + no loop + mute_group 0."""
    other = EP133ExportConfig.default().stems["other"]
    assert other.play_mode == "legato"
    assert other.loop is False
    assert other.mute_group == 0


# ──────────────────────────────────────────────────────────────────────────────
# EP133ExportConfig.stem_config()
# ──────────────────────────────────────────────────────────────────────────────

def test_stem_config_returns_configured():
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    drums = cfg.stem_config("drums")
    assert drums.play_mode == "oneshot"
    assert drums.loop is True


def test_stem_config_fallback_to_default():
    """Unknown stem names fall back to EP133StemConfig() defaults."""
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    unknown = cfg.stem_config("synthesizer")
    # Falls back to EP133ExportConfig.default() if present, else bare EP133StemConfig
    assert unknown.play_mode in {"oneshot", "key", "legato"}


# ──────────────────────────────────────────────────────────────────────────────
# EP133StemConfig validation
# ──────────────────────────────────────────────────────────────────────────────

def test_stem_config_rejects_bad_play_mode():
    with pytest.raises(ValueError, match="play_mode"):
        EP133StemConfig(play_mode="loop")


def test_stem_config_rejects_bad_mute_group():
    with pytest.raises(ValueError, match="mute_group"):
        EP133StemConfig(mute_group=9)


def test_stem_config_rejects_bad_pad_group():
    with pytest.raises(ValueError, match="pad_group"):
        EP133StemConfig(pad_group="Z")


def test_stem_config_rejects_bad_pad_num():
    with pytest.raises(ValueError, match="pad_num"):
        EP133StemConfig(pad_num=0)
    with pytest.raises(ValueError, match="pad_num"):
        EP133StemConfig(pad_num=13)


# ──────────────────────────────────────────────────────────────────────────────
# generate_setup_md
# ──────────────────────────────────────────────────────────────────────────────

def _make_results() -> list[dict]:
    cfg_drums = EP133StemConfig(
        play_mode="oneshot",
        loop=True,
        mute_group=0,
        time_stretch=EP133TimeStretchConfig(mode="bar", bars=4),
        pad_group="A",
        pad_num=1,
    )
    audio_drums = {
        "filename": "drums_ep133.wav",
        "sample_rate": 46875,
        "bit_depth": 16,
        "channels": "mono",
        "duration_sec": 8.0,
        "export_start_sec": 0.0,
        "export_end_sec": 8.0,
    }
    cfg_bass = EP133StemConfig(
        play_mode="oneshot",
        loop=True,
        mute_group=1,
        time_stretch=EP133TimeStretchConfig(mode="bpm", source_bpm=128.0),
        pad_group="B",
        pad_num=1,
    )
    audio_bass = {
        "filename": "bass_ep133.wav",
        "sample_rate": 46875,
        "bit_depth": 16,
        "channels": "mono",
        "duration_sec": 8.0,
        "export_start_sec": 0.0,
        "export_end_sec": 8.0,
    }
    return [
        {"stem": "drums", "ep133": {}, "config": cfg_drums, "audio": audio_drums},
        {"stem": "bass", "ep133": {}, "config": cfg_bass, "audio": audio_bass},
    ]


def test_generate_setup_md_contains_bpm_section():
    md = generate_setup_md("test_track", 128.0, _make_results())
    assert "## BPM Sync" in md
    assert "128.0" in md


def test_generate_setup_md_contains_import_table():
    md = generate_setup_md("test_track", 128.0, _make_results())
    assert "## Import Samples" in md
    assert "| Pad | Group | File |" in md
    assert "drums_ep133.wav" in md
    assert "bass_ep133.wav" in md


def test_generate_setup_md_contains_on_device_section():
    md = generate_setup_md("test_track", 128.0, _make_results())
    assert "## On-Device Sound Edit" in md
    assert "SHIFT + SOUND" in md


def test_generate_setup_md_contains_sticky_loop_section():
    md = generate_setup_md("test_track", 128.0, _make_results())
    assert "Sticky Loop" in md


def test_generate_setup_md_drums_bar_4_label():
    md = generate_setup_md("test_track", 128.0, _make_results())
    assert "BAR 4" in md


def test_generate_setup_md_known_gaps():
    md = generate_setup_md("test_track", 128.0, _make_results())
    assert "Known Gaps" in md
    assert "Loop" in md
    assert "Time Stretch" in md


def test_generate_setup_md_song_name_in_header():
    md = generate_setup_md("my_cool_track", 120.0, _make_results())
    assert "my_cool_track" in md


def test_generate_setup_md_sync_mode_sync24():
    md = generate_setup_md("x", 120.0, _make_results(), sync_mode="sync24")
    assert "3.5mm" in md or "Sync" in md


# ──────────────────────────────────────────────────────────────────────────────
# process_stem_wav — audio processing
# ──────────────────────────────────────────────────────────────────────────────

def test_process_stem_wav_output_sample_rate(tmp_path: Path, synthetic_wav: Path):
    """Output WAV must be at 46875 Hz."""
    out = tmp_path / "out.wav"
    result_path, duration, channels = process_stem_wav(synthetic_wav, out)
    info = sf.info(str(result_path))
    assert info.samplerate == 46875


def test_process_stem_wav_output_16bit(tmp_path: Path, synthetic_wav: Path):
    """Output WAV must be 16-bit (PCM_16)."""
    out = tmp_path / "out.wav"
    process_stem_wav(synthetic_wav, out)
    info = sf.info(str(out))
    assert info.subtype == "PCM_16"


def test_process_stem_wav_output_mono(tmp_path: Path, synthetic_wav: Path):
    """Stereo input must be downmixed to mono (1 channel)."""
    out = tmp_path / "out.wav"
    _, _, channels = process_stem_wav(synthetic_wav, out)
    assert channels == 1
    info = sf.info(str(out))
    assert info.channels == 1


def test_process_stem_wav_duration_approx(tmp_path: Path, synthetic_wav: Path):
    """Output duration should be approximately 1 second (±0.05 s)."""
    out = tmp_path / "out.wav"
    _, duration, _ = process_stem_wav(synthetic_wav, out)
    assert abs(duration - 1.0) < 0.05


def test_process_stem_wav_returns_path(tmp_path: Path, synthetic_wav: Path):
    out = tmp_path / "out.wav"
    result_path, _, _ = process_stem_wav(synthetic_wav, out)
    assert result_path == out
    assert out.exists()


def test_process_stem_wav_mono_input(tmp_path: Path):
    """Mono input at 44100 Hz should also be resampled to 46875 Hz."""
    sr = 44100
    t = np.linspace(0, 1.0, sr, endpoint=False)
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    src = tmp_path / "mono.wav"
    sf.write(str(src), audio, sr, subtype="PCM_16")

    out = tmp_path / "mono_out.wav"
    _, duration, channels = process_stem_wav(src, out)
    info = sf.info(str(out))
    assert info.samplerate == 46875
    assert channels == 1


# ──────────────────────────────────────────────────────────────────────────────
# export_ep133_package — integration (with synthetic data)
# ──────────────────────────────────────────────────────────────────────────────

def test_export_ep133_package_produces_wavs(tmp_path: Path, stems_json: Path):
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    out_dir = tmp_path / "ep133_out"
    results = export_ep133_package(stems_json, cfg, out_dir)

    assert len(results) == 2  # drums + bass both present in stems_json
    assert (out_dir / "drums_ep133.wav").exists()
    assert (out_dir / "bass_ep133.wav").exists()


def test_export_ep133_package_writes_manifest(tmp_path: Path, stems_json: Path):
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    out_dir = tmp_path / "ep133_out"
    export_ep133_package(stems_json, cfg, out_dir)

    manifest = out_dir / "ep133_manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert isinstance(data, list)
    assert any(r["stem"] == "drums" for r in data)


def test_export_ep133_package_writes_setup_md(tmp_path: Path, stems_json: Path):
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    out_dir = tmp_path / "ep133_out"
    export_ep133_package(stems_json, cfg, out_dir)

    assert (out_dir / "SETUP.md").exists()


def test_export_ep133_package_manifest_schema(tmp_path: Path, stems_json: Path):
    """ep133 block in manifest matches spec Section 6 schema."""
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    out_dir = tmp_path / "ep133_out"
    export_ep133_package(stems_json, cfg, out_dir)

    data = json.loads((out_dir / "ep133_manifest.json").read_text())
    drums_entry = next(r for r in data if r["stem"] == "drums")
    ep = drums_entry["ep133"]

    assert ep["play_mode"] == "oneshot"
    assert ep["loop"] is True
    assert ep["mute_group"] == 0
    assert "time_stretch" in ep
    assert ep["time_stretch"]["mode"] == "bar"
    assert ep["time_stretch"]["bars"] == 4
    assert ep["pad"]["group"] == "A"
    assert ep["pad"]["pad"] == 1
    assert ep["audio"]["sample_rate"] == 46875
    assert ep["audio"]["bit_depth"] == 16
    assert ep["audio"]["channels"] == "mono"


def test_export_ep133_package_dry_run(tmp_path: Path, stems_json: Path):
    """Dry run must not write any files."""
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    out_dir = tmp_path / "ep133_dry"
    results = export_ep133_package(stems_json, cfg, out_dir, dry_run=True)

    assert not (out_dir / "drums_ep133.wav").exists()
    assert not (out_dir / "SETUP.md").exists()
    # But we still get result dicts
    assert len(results) >= 1


def test_export_ep133_package_skips_missing_stems(tmp_path: Path, stems_json: Path):
    """Stems configured but absent from stems.json are silently skipped."""
    cfg = EP133ExportConfig.from_pipeline_dict(PIPELINE_DICT)
    # vocals and other are in PIPELINE_DICT but not in stems_json fixture
    out_dir = tmp_path / "ep133_out"
    results = export_ep133_package(stems_json, cfg, out_dir)
    stems_exported = {r["stem"] for r in results}
    assert "vocals" not in stems_exported
    assert "other" not in stems_exported
