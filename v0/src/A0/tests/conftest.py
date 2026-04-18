"""
Shared test fixtures — kept light so CI doesn't need to download torch
reference models. Every test here runs in under a second and uses only
numpy + onnx (no torch, no transformers, no demucs).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Tests in this tree import the A0 package via `v0.src.A0.*`. Pytest runs
# from the repo root so the v0/ package must be importable — add an empty
# `__init__.py` in v0/ and v0/src/ at discovery time without polluting git.

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _ensure_v0_package(monkeypatch, tmp_path):
    """
    The `v0/` tree is not a proper Python package (to avoid polluting the
    stemforge repo layout). For test isolation we prepend repo root to
    sys.path and create shim `__init__.py` files at `v0/` and `v0/src/`
    in-memory via `sys.modules` monkey-patching.
    """
    import types
    if "v0" not in sys.modules:
        v0 = types.ModuleType("v0")
        v0.__path__ = [str(REPO_ROOT / "v0")]
        sys.modules["v0"] = v0
    if "v0.src" not in sys.modules:
        src = types.ModuleType("v0.src")
        src.__path__ = [str(REPO_ROOT / "v0" / "src")]
        sys.modules["v0.src"] = src
