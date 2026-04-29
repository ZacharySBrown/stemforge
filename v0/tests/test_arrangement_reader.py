"""Pytest bridge for the Track-B JS regression suite.

Runs ``tests/js_mocks/test_arrangement_reader.test.js`` (Node + node:test)
as a subprocess so ``uv run pytest`` covers Track B alongside the existing
v0 + Python tests. Mirrors the pattern in ``tests/test_js_bridge.py``.

The JS suite exercises ``v0/src/m4l-js/sf_arrangement_reader.js`` (the
arrangement-view → snapshot.json reader) under a Node-vm sandbox with
mock LiveAPI/File so no Max install or Ableton instance is required.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# v0/tests/test_arrangement_reader.py → parents[2] = repo root (worktree root)
REPO_ROOT = Path(__file__).resolve().parents[2]
JS_TEST = REPO_ROOT / "tests" / "js_mocks" / "test_arrangement_reader.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_js_arrangement_reader_suite() -> None:
    """Run the Track-B JS suite via node and assert exit 0."""
    assert JS_TEST.is_file(), f"missing JS test file: {JS_TEST}"

    result = subprocess.run(
        ["node", str(JS_TEST)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        pytest.fail(
            "Track-B JS suite failed\n"
            f"exit code: {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    # Sanity: confirm tests actually ran (not a silent no-op). node:test prints
    # a "pass <N>" summary line.
    assert "pass " in result.stdout, (
        "expected 'pass N' summary in node test stdout; got:\n" + result.stdout
    )
