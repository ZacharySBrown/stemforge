"""Test fixtures for configurator tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


@pytest.fixture
def make_wav(tmp_path: Path):
    """Return a callable that writes a deterministic WAV and returns its path.

    Default: 0.5 s of mono 1 kHz sine at 22050 Hz. Override via kwargs.
    """

    def _make(
        name: str = "test.wav",
        *,
        duration_sec: float = 0.5,
        sample_rate: int = 22050,
        channels: int = 1,
        freq_hz: float = 1000.0,
    ) -> Path:
        path = tmp_path / name
        n = int(duration_sec * sample_rate)
        t = np.arange(n) / sample_rate
        tone = (0.5 * np.sin(2 * np.pi * freq_hz * t)).astype("float32")
        if channels == 1:
            data = tone
        else:
            data = np.stack([tone] * channels, axis=1)
        sf.write(str(path), data, sample_rate, subtype="PCM_16")
        return path

    return _make


@pytest.fixture
def small_manifest(tmp_path: Path, make_wav):
    """A 4-group manifest with one entry per group."""
    groups = {}
    for letter in ("A", "B", "C", "D"):
        wav = make_wav(f"{letter}.wav")
        groups[letter] = [
            {
                "slot": 0,
                "file_path": str(wav),
                "clip_length_sec": 0.5,
                "name": f"clip_{letter}",
            }
        ]
    manifest = {
        "version": 1,
        "bpm": 100.0,
        "session_tracks": groups,
    }
    path = tmp_path / "manifest.json"
    path.write_text(__import__("json").dumps(manifest))
    return path
