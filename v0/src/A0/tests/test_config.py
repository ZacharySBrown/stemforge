"""Smoke tests for A0 config + parity constants."""
from __future__ import annotations

from v0.src.A0 import config


def test_parity_targets_match_track_brief():
    # These numbers are lifted directly from v0/tracks/A0-onnx-conversion.md
    # and v0/PIVOT.md §E. If the brief tightens, update config + this test
    # so the regression is visible in CI.
    assert config.PARITY.demucs_max_abs_err == 1e-3
    assert config.PARITY.demucs_max_rel_err == 1e-2
    assert config.PARITY.clap_min_cosine == 0.999
    assert config.PARITY.ast_max_logit_diff == 1e-3
    assert config.PARITY.ast_topk_labels == 5
    assert config.PARITY.fp16_null_rms_dbfs_max == -60.0


def test_opset_supports_stft():
    # The brief requires opset ≥ 17 for STFT op support (even though we fall
    # back to external STFT for Demucs, the in-graph attempt must first try).
    assert config.OPSET_VERSION >= 17


def test_paths_are_under_repo_root():
    for p in (config.A0_STATE_DIR, config.BUILD_MODELS_DIR,
              config.MANIFEST_PATH):
        assert str(p).startswith(str(config.REPO_ROOT))


def test_demucs_models_registry_complete():
    # PIVOT.md names these three as the required export set.
    assert set(config.DEMUCS_MODELS) == {"htdemucs_ft", "htdemucs_6s",
                                         "htdemucs"}
    assert config.DEMUCS_MODELS["htdemucs_ft"][2] == "primary"
