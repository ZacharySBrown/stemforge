"""Tests for the channel-collapse-invariant audio hash."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stemforge.configurator.audio_hash import HASH_LENGTH, audio_hash


def test_hash_is_deterministic(make_wav, tmp_path: Path):
    wav = make_wav("a.wav", duration_sec=0.25, freq_hz=440.0)
    cache = tmp_path / "cache.json"
    h1 = audio_hash(wav, cache_path=cache)
    h2 = audio_hash(wav, cache_path=cache)
    assert h1 == h2
    assert len(h1) == HASH_LENGTH
    assert all(c in "0123456789abcdef" for c in h1)


def test_mono_vs_identical_stereo_hash_equal(tmp_path: Path):
    """Stereo with L == R must hash the same as the mono version."""
    sr = 22050
    t = np.arange(int(sr * 0.25)) / sr
    tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32")

    mono = tmp_path / "mono.wav"
    sf.write(str(mono), tone, sr, subtype="PCM_16")

    stereo = tmp_path / "stereo.wav"
    sf.write(str(stereo), np.stack([tone, tone], axis=1), sr, subtype="PCM_16")

    cache = tmp_path / "cache.json"
    h_mono = audio_hash(mono, cache_path=cache)
    h_stereo = audio_hash(stereo, cache_path=cache)
    assert h_mono == h_stereo


def test_different_content_hashes_differ(make_wav, tmp_path: Path):
    a = make_wav("a.wav", freq_hz=440.0)
    b = make_wav("b.wav", freq_hz=880.0)
    cache = tmp_path / "cache.json"
    assert audio_hash(a, cache_path=cache) != audio_hash(b, cache_path=cache)


def test_cache_hit_avoids_re_reading_file(make_wav, tmp_path: Path, monkeypatch):
    wav = make_wav("a.wav")
    cache = tmp_path / "cache.json"

    # Prime the cache.
    expected = audio_hash(wav, cache_path=cache)
    assert cache.is_file()

    # Now monkeypatch soundfile.read to explode if invoked again.
    import stemforge.configurator.audio_hash as ah

    def boom(*args, **kwargs):
        raise AssertionError("soundfile.read should not be called on cache hit")

    monkeypatch.setattr(ah.sf, "read", boom)
    second = audio_hash(wav, cache_path=cache)
    assert second == expected


def test_cache_miss_when_mtime_changes(make_wav, tmp_path: Path):
    wav = make_wav("a.wav")
    cache = tmp_path / "cache.json"
    first = audio_hash(wav, cache_path=cache)

    # Rewrite the file with different content; mtime / size will change.
    import soundfile as _sf

    t = np.arange(int(22050 * 0.25)) / 22050
    different = (0.5 * np.sin(2 * np.pi * 1500 * t)).astype("float32")
    _sf.write(str(wav), different, 22050, subtype="PCM_16")

    second = audio_hash(wav, cache_path=cache)
    assert second != first


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        audio_hash(tmp_path / "does_not_exist.wav", cache_path=tmp_path / "c.json")


def test_use_cache_false_bypasses(make_wav, tmp_path: Path):
    wav = make_wav("a.wav")
    cache = tmp_path / "cache.json"
    h = audio_hash(wav, cache_path=cache, use_cache=False)
    assert len(h) == HASH_LENGTH
    # No write should happen when use_cache is False.
    assert not cache.exists()


def test_cache_prunes_stale_paths(make_wav, tmp_path: Path):
    """Cache entries that point at missing files should be trimmed."""
    wav = make_wav("a.wav")
    cache = tmp_path / "cache.json"
    audio_hash(wav, cache_path=cache)

    # Seed the cache with a bogus entry pointing at a non-existent path.
    raw = json.loads(cache.read_text())
    raw[f"{tmp_path}/missing.wav|0|0"] = "deadbeef" * 2
    cache.write_text(json.dumps(raw))
    assert "missing.wav" in cache.read_text()

    # Trigger a recompute (different file → cache miss → prune).
    other = make_wav("b.wav", freq_hz=550.0)
    audio_hash(other, cache_path=cache)
    final = json.loads(cache.read_text())
    assert not any("missing.wav" in k for k in final)
