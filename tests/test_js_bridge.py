"""Pytest bridge: runs the Node-based JS regression tests as a subprocess.

This lets `uv run pytest` cover both Python and JS tests in one command.
No new deps required — just spawns `node tests/js_mocks/test_preset_resolution.test.js`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_TEST = REPO_ROOT / "tests" / "js_mocks" / "test_preset_resolution.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_js_preset_resolution_suite() -> None:
    """Run the Node test suite and assert exit 0."""
    assert JS_TEST.is_file(), f"missing JS test file: {JS_TEST}"

    result = subprocess.run(
        ["node", str(JS_TEST)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Surface the full output on failure so pytest reports it.
    if result.returncode != 0:
        pytest.fail(
            "JS test suite failed\n"
            f"exit code: {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    # Sanity: confirm tests actually ran (not a silent no-op).
    assert "pass 6" in result.stdout or "pass " in result.stdout, (
        "expected test summary in stdout; got:\n" + result.stdout
    )
