"""Tests for the fp16 null-test harness (no ONNX inference needed)."""
from __future__ import annotations

import math

import numpy as np

from v0.src.A0 import fp16


def test_rms_dbfs_of_silence_is_neg_inf():
    assert fp16.rms_dbfs(np.zeros(1000, dtype=np.float32)) == -math.inf


def test_rms_dbfs_of_full_scale_is_zero():
    # RMS of a ±1 square wave is 1.0 → 0 dBFS.
    sq = np.tile([1.0, -1.0], 512).astype(np.float32)
    assert abs(fp16.rms_dbfs(sq)) < 1e-9


def test_null_test_passes_on_identical_arrays():
    a = np.random.default_rng(1).standard_normal(1024).astype(np.float32)
    r = fp16.null_test(a, a.copy(), model_name="toy", fixture="id")
    assert r.passed
    assert r.rms_dbfs == -math.inf
    assert r.peak_abs == 0.0


def test_null_test_fails_on_gross_perturbation():
    a = np.random.default_rng(2).standard_normal(1024).astype(np.float32)
    b = a + 0.1  # gross perturbation — RMS(diff) = 0.1 ≈ -20 dBFS
    r = fp16.null_test(a, b, model_name="toy", fixture="bad")
    assert not r.passed
    assert -21.0 < r.rms_dbfs < -19.0


def test_null_test_passes_on_quiet_perturbation():
    # 1e-4 noise → -80 dBFS, well below the -60 dBFS threshold.
    rng = np.random.default_rng(3)
    a = rng.standard_normal(16_000).astype(np.float32)
    b = a + rng.normal(0, 1e-4, size=a.shape).astype(np.float32)
    r = fp16.null_test(a, b, model_name="toy", fixture="quiet")
    assert r.passed, f"unexpected fail at rms={r.rms_dbfs}"
    assert r.rms_dbfs < -60.0


def test_null_test_shape_mismatch_raises():
    import pytest
    with pytest.raises(ValueError):
        fp16.null_test(np.zeros(10), np.zeros(11),
                       model_name="x", fixture="y")
