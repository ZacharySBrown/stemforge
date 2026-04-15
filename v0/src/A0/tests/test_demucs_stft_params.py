"""
Lock the Demucs STFT parameters the external-STFT wrapper must replicate.

If the upstream `demucs/spec.py` ever changes these, this test explodes and
Track A knows the C++ STFT kernel needs updating.
"""
from __future__ import annotations

from v0.src.A0 import demucs_export


def test_stft_params_known_values():
    params = demucs_export.stft_params()
    assert params["n_fft"] == 4096
    assert params["hop_length"] == 1024
    assert params["window"] == "hann"
    assert params["center"] is True
    assert params["pad_mode"] == "reflect"
    assert params["normalized"] is False
    assert params["onesided"] is True
    assert params["expected_input_sr"] == 44_100
    assert params["expected_channels"] == 2


def test_stft_config_immutable():
    # STFT is a frozen dataclass — ensure no accidental mutation.
    import dataclasses
    assert dataclasses.is_dataclass(demucs_export.STFT)
    # Attempting to mutate should raise.
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        demucs_export.STFT.n_fft = 2048   # type: ignore[misc]
