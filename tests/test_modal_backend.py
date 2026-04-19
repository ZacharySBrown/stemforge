"""Tests for the Modal backend — mocks the Modal SDK to verify the integration
pattern without requiring a deployed function or network access."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from stemforge.backends.modal_backend import ModalBackend, MODAL_APP_NAME, MODAL_FUNCTION_NAME


def _make_wav_bytes(duration_s: float = 1.0, sr: int = 44100) -> bytes:
    """Generate a short WAV file in memory and return its bytes."""
    samples = int(duration_s * sr)
    audio = np.random.randn(samples, 2).astype(np.float32) * 0.1
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="FLOAT")
    return buf.getvalue()


def _make_audio_file(path: Path, duration_s: float = 1.0, sr: int = 44100):
    """Write a short WAV file to disk."""
    samples = int(duration_s * sr)
    audio = np.random.randn(samples, 2).astype(np.float32) * 0.1
    sf.write(str(path), audio, sr, subtype="PCM_24")


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "test_track.wav"
    _make_audio_file(p)
    return p


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "output"


class TestModalBackend:
    def test_name(self):
        be = ModalBackend()
        assert be.name == "Modal (cloud GPU)"

    def test_separate_writes_stems(self, audio_file, output_dir):
        """Mock modal.Function.lookup to return fake stem bytes, verify disk output."""
        # Read bytes before mock replaces module
        expected_bytes = audio_file.read_bytes()

        fake_stems = {
            "drums": _make_wav_bytes(),
            "bass": _make_wav_bytes(),
            "vocals": _make_wav_bytes(),
            "other": _make_wav_bytes(),
        }

        mock_fn = MagicMock()
        mock_fn.remote.return_value = fake_stems

        mock_modal = MagicMock()
        mock_modal.Function.lookup.return_value = mock_fn

        with patch("stemforge.backends.modal_backend.modal", mock_modal):
            be = ModalBackend()
            result = be.separate(audio_file, output_dir)

        # Verify lookup was called with correct app/function names
        mock_modal.Function.lookup.assert_called_once_with(
            MODAL_APP_NAME, MODAL_FUNCTION_NAME
        )

        # Verify remote was called with audio bytes and filename
        call_args = mock_fn.remote.call_args
        assert call_args[0][0] == expected_bytes  # audio_bytes
        assert call_args[0][1] == "test_track.wav"  # filename
        assert call_args[1]["sample_rate"] == 44100  # default

        # Verify output
        assert set(result.keys()) == {"drums", "bass", "vocals", "other"}
        for stem_name, stem_path in result.items():
            assert stem_path.exists()
            assert stem_path.parent == output_dir
            assert stem_path.name == f"{stem_name}.wav"
            assert stem_path.stat().st_size > 0

    def test_separate_custom_sample_rate(self, audio_file, output_dir):
        """Verify sample_rate kwarg is passed through to Modal."""
        fake_stems = {s: _make_wav_bytes() for s in ["drums", "bass", "vocals", "other"]}
        mock_fn = MagicMock()
        mock_fn.remote.return_value = fake_stems
        mock_modal = MagicMock()
        mock_modal.Function.lookup.return_value = mock_fn

        with patch("stemforge.backends.modal_backend.modal", mock_modal):
            be = ModalBackend()
            be.separate(audio_file, output_dir, sample_rate=48000)

        assert mock_fn.remote.call_args[1]["sample_rate"] == 48000

    def test_modal_not_installed(self, audio_file, output_dir):
        """Verify helpful error when modal package is missing."""
        with patch("stemforge.backends.modal_backend.modal", None):
            be = ModalBackend()
            with pytest.raises(RuntimeError, match="modal"):
                be.separate(audio_file, output_dir)

    def test_function_not_deployed(self, audio_file, output_dir):
        """Verify helpful error when Modal app isn't deployed."""
        mock_modal = MagicMock()
        mock_modal.Function.lookup.side_effect = Exception("App not found")
        with patch("stemforge.backends.modal_backend.modal", mock_modal):
            be = ModalBackend()
            with pytest.raises(RuntimeError, match="Deploy first"):
                be.separate(audio_file, output_dir)

    def test_remote_call_failure(self, audio_file, output_dir):
        """Verify error propagation when remote function fails."""
        mock_fn = MagicMock()
        mock_fn.remote.side_effect = Exception("GPU OOM")
        mock_modal = MagicMock()
        mock_modal.Function.lookup.return_value = mock_fn

        with patch("stemforge.backends.modal_backend.modal", mock_modal):
            be = ModalBackend()
            with pytest.raises(RuntimeError, match="GPU OOM"):
                be.separate(audio_file, output_dir)

    def test_output_dir_created(self, audio_file, tmp_path):
        """Verify output directory is created if it doesn't exist."""
        nested = tmp_path / "a" / "b" / "c"
        assert not nested.exists()

        fake_stems = {s: _make_wav_bytes() for s in ["drums", "bass", "vocals", "other"]}
        mock_fn = MagicMock()
        mock_fn.remote.return_value = fake_stems
        mock_modal = MagicMock()
        mock_modal.Function.lookup.return_value = mock_fn

        with patch("stemforge.backends.modal_backend.modal", mock_modal):
            be = ModalBackend()
            be.separate(audio_file, nested)

        assert nested.exists()
        assert (nested / "drums.wav").exists()
