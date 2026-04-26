"""Tests for stemforge.prechop — bar-aligned stem chunking."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stemforge.prechop import (
    chunk_count_for,
    prechop,
    prechop_stem,
)
from stemforge.manifest_schema import BATCH_FILENAME, load_batch


def _write_stem(path: Path, *, seconds: float, sr: int = 44100, freq: float = 440.0):
    t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False, dtype=np.float32)
    audio = 0.05 * np.sin(2 * np.pi * freq * t)
    sf.write(str(path), audio, sr, subtype="FLOAT")


def _make_stems_dir(tmp_path: Path, *, bpm: float = 120.0, stems_seconds: dict[str, float] | None = None):
    """Build a fake stems.json with real stem WAVs."""
    stems_dir = tmp_path / "track_x"
    stems_dir.mkdir()
    stems = stems_seconds or {"drums": 8.0, "bass": 8.0}
    entries = []
    for name, secs in stems.items():
        wav = stems_dir / f"{name}.wav"
        _write_stem(wav, seconds=secs, freq=200 + 100 * len(name))
        entries.append({"name": name, "wav_path": str(wav), "beats_dir": "", "beat_count": 0})
    (stems_dir / "stems.json").write_text(json.dumps({
        "track_name": "Test Track",
        "bpm": bpm,
        "stems": entries,
    }, indent=2))
    return stems_dir


# ── chunk_count_for ────────────────────────────────────────────────────────

def test_chunk_count_exact():
    assert chunk_count_for(8.0, 2.0) == 4


def test_chunk_count_round_up_partial():
    assert chunk_count_for(8.5, 2.0) == 5


def test_chunk_count_zero_total():
    assert chunk_count_for(0.0, 2.0) == 0


# ── single-stem prechop ────────────────────────────────────────────────────

def test_prechop_stem_creates_correct_chunks(tmp_path):
    wav = tmp_path / "drums.wav"
    _write_stem(wav, seconds=8.0)  # 8 sec @ 120bpm = 4 bars; 2 bars/chunk = 2 chunks
    out = tmp_path / "out"

    bpm = 120.0
    chunk_seconds = 2 * 4 * (60.0 / bpm)  # 2 bars × 4 beats × 0.5 sec/beat = 4 sec
    result = prechop_stem("drums", wav, out,
                           chunk_seconds=chunk_seconds, bars_per_chunk=2,
                           bpm=bpm, track_name="Test")
    assert result.chunk_count == 2
    assert (out / "001.wav").exists()
    assert (out / "002.wav").exists()
    assert (out / BATCH_FILENAME).exists()


def test_prechop_stem_includes_partial_final_chunk(tmp_path):
    wav = tmp_path / "drums.wav"
    _write_stem(wav, seconds=10.0)  # 10s; 4s chunks → 2 full + 1 partial = 3 chunks
    out = tmp_path / "out"
    result = prechop_stem("drums", wav, out,
                           chunk_seconds=4.0, bars_per_chunk=2,
                           bpm=120.0, track_name="Test")
    assert result.chunk_count == 3
    assert result.last_chunk_seconds == pytest.approx(2.0, abs=0.01)


def test_prechop_stem_writes_sidecars(tmp_path):
    wav = tmp_path / "drums.wav"
    _write_stem(wav, seconds=8.0)
    out = tmp_path / "out"
    prechop_stem("drums", wav, out,
                  chunk_seconds=4.0, bars_per_chunk=2,
                  bpm=120.0, track_name="Test")
    sidecars = list(out.glob(".manifest_*.json"))
    assert len(sidecars) == 2  # one per chunk


def test_prechop_stem_batch_manifest_lists_all_chunks(tmp_path):
    wav = tmp_path / "drums.wav"
    _write_stem(wav, seconds=12.0)
    out = tmp_path / "out"
    prechop_stem("drums", wav, out,
                  chunk_seconds=4.0, bars_per_chunk=2,
                  bpm=120.0, track_name="Test")
    batch = load_batch(out / BATCH_FILENAME)
    assert len(batch.samples) == 3
    files = sorted(s.file for s in batch.samples)
    assert files == ["001.wav", "002.wav", "003.wav"]
    # All entries carry stem + bpm
    for s in batch.samples:
        assert s.stem == "drums"
        assert s.bpm == 120.0


# ── full prechop (stems.json driven) ───────────────────────────────────────

def test_prechop_reads_stems_json(tmp_path):
    stems_dir = _make_stems_dir(tmp_path, bpm=120.0,
                                 stems_seconds={"drums": 8.0, "bass": 8.0})
    out = tmp_path / "prechop_out"
    result = prechop(stems_dir, bars_per_chunk=2, output=out)

    assert result.track_name == "Test Track"
    assert result.bpm == 120.0
    assert {s.stem_name for s in result.stems} == {"drums", "bass"}
    for sr in result.stems:
        assert (sr.output_dir / "001.wav").exists()


def test_prechop_writes_top_level_summary(tmp_path):
    stems_dir = _make_stems_dir(tmp_path)
    out = tmp_path / "prechop_out"
    prechop(stems_dir, bars_per_chunk=2, output=out)

    summary = json.loads((out / "prechop_manifest.json").read_text())
    assert summary["track_name"] == "Test Track"
    assert summary["bars_per_chunk"] == 2
    assert summary["chunk_seconds"] == pytest.approx(4.0, abs=0.001)


def test_prechop_skips_missing_stem_paths(tmp_path):
    stems_dir = tmp_path / "track_x"
    stems_dir.mkdir()
    (stems_dir / "stems.json").write_text(json.dumps({
        "track_name": "Test",
        "bpm": 120.0,
        "stems": [
            {"name": "drums", "wav_path": "/nope.wav", "beats_dir": "", "beat_count": 0},
        ],
    }))
    out = tmp_path / "prechop_out"
    result = prechop(stems_dir, bars_per_chunk=2, output=out)
    assert result.stems == []


def test_prechop_missing_stems_json_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        prechop(tmp_path, bars_per_chunk=2, output=tmp_path / "out")


def test_prechop_default_output_is_stems_dir_subdir(tmp_path):
    stems_dir = _make_stems_dir(tmp_path)
    result = prechop(stems_dir, bars_per_chunk=2, output=None)
    assert result.output_root == (stems_dir / "prechop").resolve()
    assert result.output_root.exists()
