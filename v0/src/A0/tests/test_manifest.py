"""Tests for manifest writer — uses a trivial synthetic ONNX model."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper

from v0.src.A0 import manifest


def _make_toy_onnx(path: Path) -> None:
    """Build a single-op (Identity) ONNX model for testing."""
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 224, 224])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 3, 224, 224])
    node = helper.make_node("Identity", ["x"], ["y"])
    graph = helper.make_graph([node], "toy", [x], [y])
    m = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    m.ir_version = 10
    onnx.save(m, str(path))


def test_sha256_deterministic(tmp_path):
    p = tmp_path / "toy.onnx"
    _make_toy_onnx(p)
    h1 = manifest.sha256_of_file(p)
    h2 = manifest.sha256_of_file(p)
    assert h1 == h2
    assert len(h1) == 64  # hex digest


def test_build_entry_fields(tmp_path, monkeypatch):
    p = tmp_path / "toy.onnx"
    _make_toy_onnx(p)
    # Pin REPO_ROOT so the relative-path logic doesn't explode outside the repo.
    monkeypatch.setattr(manifest.config, "REPO_ROOT", tmp_path)
    entry = manifest.build_entry(
        p,
        torch_ref_checkpoint="my/toy",
        max_abs_err=5e-5,
        max_rel_err=1e-4,
        precision="fp32",
        coreml_ep_supported=True,
        cpu_fallback_ops=[],
        optimized_cache=None,
    )
    assert entry["path"].endswith("toy.onnx")
    assert entry["torch_ref_checkpoint"] == "my/toy"
    assert entry["precision"] == "fp32"
    assert entry["coreml_ep_supported"] is True
    assert entry["input_shape"] == {"x": [1, 3, 224, 224]}
    assert entry["output_shape"] == {"y": [1, 3, 224, 224]}
    assert entry["size"] > 0


def test_write_and_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "toy.onnx"
    _make_toy_onnx(p)
    monkeypatch.setattr(manifest.config, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(manifest.config, "BUILD_MODELS_DIR", tmp_path)
    monkeypatch.setattr(manifest.config, "MANIFEST_PATH",
                        tmp_path / "manifest.json")
    entry = manifest.build_entry(
        p, torch_ref_checkpoint="x",
        max_abs_err=0.0, max_rel_err=0.0,
        precision="fp32", coreml_ep_supported=False,
        cpu_fallback_ops=[], optimized_cache=None,
    )
    manifest.write({"toy": entry})
    loaded = manifest.load()
    assert loaded["schema_version"] == manifest.SCHEMA_VERSION
    assert "toy" in loaded["models"]
    assert loaded["models"]["toy"]["sha256"] == entry["sha256"]
