"""Stability test for scripts/gen_typescript_types.py.

Runs the generator into a tempfile and asserts:
1. The output is non-empty.
2. The banner is present.
3. Re-running produces a byte-identical file (deterministic).
4. The committed file matches what the generator produces right now
   (catches "someone changed the schema but forgot to regen TS").

The third assertion is the acceptance gate from EXECUTION_PLAN_v1 line 95.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "gen_typescript_types.py"
_OUTPUT_PATH = _REPO_ROOT / "web" / "configurator" / "src" / "lib" / "api-types.generated.ts"


def _import_script_module():
    spec = importlib.util.spec_from_file_location("gen_typescript_types", _SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_typescript_types"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generator_produces_output_with_banner() -> None:
    mod = _import_script_module()
    schemas = mod.export_all_json_schemas()
    rendered = mod.render_typescript(schemas)
    assert rendered.startswith("// AUTO-GENERATED")
    assert "export interface Curation" in rendered
    assert "export interface ForgeManifest" in rendered
    assert "export interface StemforgeState" in rendered


def test_generator_is_deterministic() -> None:
    """Acceptance gate: re-generating produces byte-identical output."""
    mod = _import_script_module()
    schemas = mod.export_all_json_schemas()
    first = mod.render_typescript(schemas)
    second = mod.render_typescript(schemas)
    assert first == second


def test_committed_file_matches_current_schemas() -> None:
    """If this fails, run `uv run python scripts/gen_typescript_types.py` and commit."""
    if not _OUTPUT_PATH.exists():
        pytest.fail(f"{_OUTPUT_PATH} missing; run the generator and commit it")
    mod = _import_script_module()
    schemas = mod.export_all_json_schemas()
    expected = mod.render_typescript(schemas)
    actual = _OUTPUT_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        "Committed api-types.generated.ts is stale. "
        "Run `uv run python scripts/gen_typescript_types.py` and commit the result."
    )
