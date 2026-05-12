"""Pytest bridge: runs Node-based JS regression suites as subprocesses.

This lets ``uv run pytest`` cover both Python and JS tests in one command.
No new deps required — each suite is just spawned via ``node tests/js_mocks/<file>``.

All ``tests/js_mocks/*.test.js`` files are auto-discovered and parametrized
below; adding a new ``foo.test.js`` is enough to enroll it. See
``docs/issues/hardening-test-coverage-gaps.md`` for the gap that motivated
the refactor (we used to wire each file by hand, leaving 4-of-7 unrun).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_MOCKS_DIR = REPO_ROOT / "tests" / "js_mocks"


def _discover_js_suites() -> list[Path]:
    """Return every ``*.test.js`` file under tests/js_mocks/, sorted by name.

    Sorting keeps pytest output deterministic across runs / platforms.
    """
    if not JS_MOCKS_DIR.is_dir():
        return []
    return sorted(JS_MOCKS_DIR.glob("*.test.js"))


_SUITES = _discover_js_suites()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
@pytest.mark.parametrize(
    "suite_path",
    _SUITES,
    # Drop the redundant ``.test`` suffix from the parametrize id so
    # pytest reports e.g. ``[test_bounce]`` not ``[test_bounce.test]``.
    ids=[p.name.removesuffix(".test.js") for p in _SUITES],
)
def test_js_suite(suite_path: Path) -> None:
    """Run a single Node-based JS test file and assert exit 0.

    Each ``tests/js_mocks/*.test.js`` becomes its own pytest case via
    parametrize; the case id is the file stem (e.g. ``test_bounce``).
    """
    assert suite_path.is_file(), f"missing JS test file: {suite_path}"

    result = subprocess.run(
        ["node", str(suite_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        pytest.fail(
            f"JS suite '{suite_path.name}' failed\n"
            f"exit code: {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    # Sanity: confirm tests actually ran (not a silent no-op).
    assert "pass " in result.stdout, (
        f"expected test summary in stdout for {suite_path.name}; got:\n{result.stdout}"
    )


def test_js_suite_discovery_nonempty() -> None:
    """Guard against an empty discovery (e.g. directory renamed).

    If this asserts, the parametrize above silently produced zero cases
    and JS coverage would be invisible.
    """
    assert len(_SUITES) >= 1, (
        f"no JS test suites discovered under {JS_MOCKS_DIR}; expected at least one *.test.js file"
    )
