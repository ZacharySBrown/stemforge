"""Tests for Phase 1 forge pipeline: slicer bar mode + curator."""

import json
from pathlib import Path

import numpy as np
import soundfile as sf
import pytest

from stemforge.slicer import slice_at_bars_from_analysis, slice_at_bars
from stemforge.curator import curate


SR = 22050


def _write_click_track(path: Path, n_beats: int = 32, beat_dur: float = 0.25):
    """Sine bursts at regular intervals — gives clean onsets + crest factor."""
    total = int(n_beats * beat_dur * SR)
    y = np.zeros(total, dtype=np.float32)
    t = np.arange(int(beat_dur * SR)) / SR
    for b in range(n_beats):
        start = int(b * beat_dur * SR)
        # Vary amplitude and frequency per bar so bars are distinguishable.
        bar_idx = b // 4
        freq = 220.0 + 40.0 * (bar_idx % 6)
        amp = 0.3 + 0.1 * ((bar_idx * 3) % 5)
        env = np.exp(-np.linspace(0, 6, len(t)))
        y[start:start + len(t)] += (amp * np.sin(2 * np.pi * freq * t) * env).astype(np.float32)
    # Stereo
    stereo = np.stack([y, y], axis=1)
    sf.write(str(path), stereo, SR, subtype="PCM_24")


def test_slice_at_bars_from_analysis(tmp_path):
    stem = tmp_path / "drums.wav"
    _write_click_track(stem, n_beats=32, beat_dur=0.25)

    # 8 bars of 4/4 at beat_dur = 0.25s → beat_time=0..31
    warp_markers = [
        {"beat_time": 0.0, "sample_time": 0},
        {"beat_time": 31.0, "sample_time": int(31 * 0.25 * SR)},
    ]
    analysis = {
        "warp_markers": warp_markers,
        "time_signature": {"numerator": 4, "denominator": 4},
        "tempo": 240.0,
        "sample_rate": SR,
    }

    bars = slice_at_bars_from_analysis(stem, analysis, tmp_path, "drums",
                                       silence_threshold=0.0)
    assert len(bars) >= 6, f"expected ~8 bars, got {len(bars)}"
    for b in bars:
        assert b.exists()
        assert b.name.startswith("drums_bar_")


def test_slice_at_bars_librosa_fallback(tmp_path):
    stem = tmp_path / "drums.wav"
    _write_click_track(stem, n_beats=32, beat_dur=0.25)

    bars = slice_at_bars(stem, tmp_path, "drums",
                        time_sig_numerator=4, silence_threshold=0.0)
    assert len(bars) >= 2
    assert all(p.exists() for p in bars)


def test_curate_selects_n_bars(tmp_path):
    bar_dir = tmp_path / "drums_bars"
    bar_dir.mkdir()
    # Generate 12 varied bars so curator has filter headroom.
    rng = np.random.default_rng(0)
    for i in range(12):
        dur = 0.5
        n = int(dur * SR)
        t = np.arange(n) / SR
        freq = 200 + i * 35
        env = np.exp(-np.linspace(0, 5 + (i % 3), n))
        noise = rng.standard_normal(n) * 0.02
        y = (0.6 * np.sin(2 * np.pi * freq * t) * env + noise).astype(np.float32)
        stereo = np.stack([y, y], axis=1)
        sf.write(str(bar_dir / f"drums_bar_{i+1:03d}.wav"), stereo, SR, subtype="PCM_24")

    selected = curate(bar_dir, n_bars=5, strategy="max-diversity",
                     rms_floor=0.001, crest_min=1.0)
    assert 1 <= len(selected) <= 5
    for s in selected:
        assert s.exists()

    manifest = json.loads((bar_dir / "manifest.json").read_text())
    assert manifest["strategy"] == "max-diversity"
    assert len(manifest["bars"]) == len(selected)
    assert all("feature_vector" in b for b in manifest["bars"])


def test_curate_strategy_fallback_warns(tmp_path):
    bar_dir = tmp_path / "drums_bars"
    bar_dir.mkdir()
    dur = 0.4
    n = int(dur * SR)
    t = np.arange(n) / SR
    for i in range(4):
        y = (0.5 * np.sin(2 * np.pi * (200 + i * 50) * t)).astype(np.float32)
        sf.write(str(bar_dir / f"drums_bar_{i+1:03d}.wav"),
                np.stack([y, y], axis=1), SR, subtype="PCM_24")

    with pytest.warns(UserWarning):
        selected = curate(bar_dir, n_bars=2, strategy="rhythm-taxonomy",
                         rms_floor=0.0, crest_min=0.0)
    assert len(selected) >= 1
