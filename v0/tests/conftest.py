"""Shared pytest fixtures for v0 integration tests (Track G).

Fixture resolution is designed to be tolerant across development stages:
- Binary: prefer in-tree build; fall back to the installed symlink.
- Amxd / Als: in-tree only; skip if absent so upstream gaps don't fail G.
- Schema / yaml: always read from interfaces/ — required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# v0/tests/conftest.py → parents[2] = repo root (worktree root)
REPO = Path(__file__).resolve().parents[2]
V0 = REPO / "v0"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture(scope="session")
def v0_root() -> Path:
    return V0


@pytest.fixture(scope="session")
def binary_path() -> Path:
    """Resolve the native binary. Prefer in-tree, fall back to install."""
    candidates = [
        V0 / "build" / "stemforge-native",
        Path.home() / "Library" / "Application Support" / "StemForge" / "bin" / "stemforge-native",
    ]
    for c in candidates:
        try:
            if c.exists():
                return c
        except OSError:
            continue
    pytest.skip(
        "stemforge-native binary not found in any known location "
        f"(tried: {[str(c) for c in candidates]})"
    )


@pytest.fixture(scope="session")
def amxd_path() -> Path:
    p = V0 / "build" / "StemForge.amxd"
    if not p.exists():
        pytest.skip("StemForge.amxd not built (Track C output missing)")
    return p


@pytest.fixture(scope="session")
def als_path() -> Path:
    p = V0 / "build" / "StemForge.als"
    if not p.exists():
        pytest.skip(
            "StemForge.als not built yet — skeleton.als asset pending "
            "(see v0/state/D/blocker.md)"
        )
    return p


@pytest.fixture(scope="session")
def test_wav() -> Path:
    p = V0 / "tests" / "fixtures" / "short_loop.wav"
    if not p.exists():
        pytest.skip(f"short_loop.wav fixture missing: {p}")
    return p


@pytest.fixture(scope="session")
def ndjson_schema() -> dict:
    return json.loads((V0 / "interfaces" / "ndjson.schema.json").read_text())


@pytest.fixture(scope="session")
def tracks_yaml() -> dict:
    import yaml
    return yaml.safe_load((V0 / "interfaces" / "tracks.yaml").read_text())


@pytest.fixture(scope="session")
def device_yaml() -> dict:
    import yaml
    return yaml.safe_load((V0 / "interfaces" / "device.yaml").read_text())


@pytest.fixture(scope="session")
def expected_stems_schema() -> dict:
    """Golden structural template for stems.json — values are type sentinels."""
    p = V0 / "tests" / "fixtures" / "expected_stems.json"
    if not p.exists():
        pytest.skip(f"expected_stems.json fixture missing: {p}")
    return json.loads(p.read_text())


@pytest.fixture(scope="session", autouse=True)
def _ensure_maxpat_builder_importable() -> None:
    """Make v0/src/maxpat-builder importable as a flat module for amxd_pack reuse.

    The directory name contains a hyphen, so we add it directly to sys.path and
    import amxd_pack as a top-level module inside test_amxd.py.
    """
    path = str(V0 / "src" / "maxpat-builder")
    if path not in sys.path:
        sys.path.insert(0, path)
