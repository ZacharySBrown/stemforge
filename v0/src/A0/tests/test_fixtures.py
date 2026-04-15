"""Tests for synthetic audio fixture generation."""
from __future__ import annotations

import numpy as np

from v0.src.A0 import fixtures


def test_drum_loop_shape_and_duration():
    fx = fixtures.drum_loop(sr=44_100)
    assert fx.sr == 44_100
    assert fx.samples.shape[0] == 2        # stereo
    assert fx.seconds == 10.0
    assert fx.samples.dtype == np.float32


def test_full_mix_shape_and_duration():
    fx = fixtures.full_mix(sr=44_100)
    assert fx.sr == 44_100
    assert fx.samples.shape[0] == 2
    assert fx.seconds == 30.0


def test_fixtures_are_deterministic():
    a = fixtures.drum_loop(sr=22_050).samples
    b = fixtures.drum_loop(sr=22_050).samples
    # Same seed → bit-identical repro (crucial for regression tests).
    np.testing.assert_array_equal(a, b)


def test_full_mix_has_nonzero_energy():
    fx = fixtures.full_mix(sr=22_050)
    rms = float(np.sqrt(np.mean(fx.samples ** 2)))
    assert rms > 0.01   # should be well above noise floor


def test_all_fixtures_returns_both():
    all_fx = fixtures.all_fixtures(sr=22_050)
    names = sorted(f.name for f in all_fx)
    assert names == sorted(["drum_loop_10s", "full_mix_30s"])
