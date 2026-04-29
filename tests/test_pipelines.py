"""Tests for `stemforge.pipelines` — pipeline-yaml loading + prechop runner."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from stemforge.pipelines import (
    PIPELINES_DIR,
    PipelineConfig,
    PrechopConfig,
    load_pipeline,
    run_post_split_steps,
)


SR = 22050
BPM = 120.0


def _write_silent_stem(path: Path, n_frames: int, n_chan: int = 2):
    y = np.zeros((n_frames, n_chan), dtype=np.float32)
    sf.write(str(path), y, SR, subtype="PCM_24")


def test_arrangement_yaml_loads_with_prechop_block():
    cfg = load_pipeline("arrangement")
    assert cfg.name == "arrangement"
    assert cfg.prechop is not None
    assert cfg.prechop.bars == 4
    assert cfg.prechop.pad_bars == 1
    assert cfg.prechop.pad_last is True


def test_default_yaml_has_no_prechop_block():
    cfg = load_pipeline("default")
    # default.yaml exists but has no Python-side prechop step.
    assert cfg.prechop is None


def test_unknown_pipeline_returns_no_op_config():
    cfg = load_pipeline("does_not_exist_anywhere")
    assert cfg.prechop is None
    assert cfg.raw is None


def test_prechop_config_from_dict_defaults():
    cfg = PrechopConfig.from_dict({})
    assert cfg.bars == 4
    assert cfg.pad_bars == 1
    assert cfg.pad_last is True
    assert cfg.beats_per_bar == 4


def test_prechop_config_from_none_returns_none():
    assert PrechopConfig.from_dict(None) is None


def test_run_post_split_steps_emits_prechop_manifest(tmp_path):
    # Two stems, 4 bars each → with bars=2, pad_bars=1, pad_last=True → 2 chunks.
    fpb = int(round(60.0 / BPM * 4 * SR))
    n_frames = fpb * 4
    drums = tmp_path / "drums.wav"
    bass = tmp_path / "bass.wav"
    _write_silent_stem(drums, n_frames)
    _write_silent_stem(bass, n_frames)

    cfg = PipelineConfig(
        name="test",
        prechop=PrechopConfig(bars=2, pad_bars=1, pad_last=True),
    )

    out = tmp_path / "out"
    out.mkdir()
    status = run_post_split_steps(cfg, {"drums": drums, "bass": bass}, out, bpm=BPM)
    assert "prechop" in status
    manifest_path = Path(status["prechop"]["manifest"])
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert data["bars"] == 2
    assert data["pad_bars"] == 1
    assert "drums" in data["stems"]
    assert "bass" in data["stems"]
    assert (out / "drums_prechop").is_dir()
    assert (out / "bass_prechop").is_dir()


def test_run_post_split_steps_noop_without_prechop_block(tmp_path):
    cfg = PipelineConfig(name="test", prechop=None)
    drums = tmp_path / "drums.wav"
    _write_silent_stem(drums, 1024)
    status = run_post_split_steps(cfg, {"drums": drums}, tmp_path, bpm=BPM)
    assert status == {}


def test_pipelines_dir_exists():
    # Sanity: the pipelines directory the loader hits exists.
    assert PIPELINES_DIR.exists()
    assert (PIPELINES_DIR / "arrangement.yaml").exists()
