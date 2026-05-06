"""Tests for `--pipeline` → `layout_mode: production` override.

Regression: passing `--pipeline pipelines/production_idm.yaml` injects
`processing_config` into the curated manifest, but the curation YAML's
`layout_mode` defaulted to `"stems"`. The M4L loader dispatcher
(stemforge_loader.v0.js) routes to the rack-aware `loadSong()` path
ONLY when `layout_mode === "production"`, so the `processing_config`
was silently ignored — no Drum Racks, no Simplers, no curated content
loaded.

Fix: detect when `--pipeline` will inject a non-empty `processing_config`
and override `layout_mode` to `"production"` automatically. Removes the
"remember both flags" footgun. Believer-bug regression 2026-05-06.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
CURATE_BARS_PATH = REPO_ROOT / "v0" / "src" / "stemforge_curate_bars.py"


@pytest.fixture(scope="module")
def curate_bars():
    """Load the curate_bars script as a module via importlib."""
    spec = importlib.util.spec_from_file_location("stemforge_curate_bars", CURATE_BARS_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── _pipeline_injects_processing_config ──────────────────────────────────────


def test_returns_false_when_pipeline_path_is_none(curate_bars):
    assert curate_bars._pipeline_injects_processing_config(None) is False


def test_returns_false_when_pipeline_file_missing(curate_bars, tmp_path: Path):
    assert curate_bars._pipeline_injects_processing_config(tmp_path / "missing.yaml") is False


def test_returns_true_for_yaml_with_stems_block(curate_bars, tmp_path: Path):
    pipeline = tmp_path / "p.yaml"
    pipeline.write_text("name: test\nstems:\n  drums:\n    targets: []\n")
    assert curate_bars._pipeline_injects_processing_config(pipeline) is True


def test_returns_false_for_yaml_without_stems_block(curate_bars, tmp_path: Path):
    pipeline = tmp_path / "p.yaml"
    pipeline.write_text("name: test\nglobal:\n  strategy: max-diversity\n")
    assert curate_bars._pipeline_injects_processing_config(pipeline) is False


def test_returns_false_for_yaml_with_empty_stems(curate_bars, tmp_path: Path):
    pipeline = tmp_path / "p.yaml"
    pipeline.write_text("name: test\nstems: null\n")
    assert curate_bars._pipeline_injects_processing_config(pipeline) is False


def test_returns_true_for_json_pipeline(curate_bars, tmp_path: Path):
    pipeline = tmp_path / "p.json"
    pipeline.write_text(json.dumps({"name": "test", "stems": {"drums": {}}}))
    assert curate_bars._pipeline_injects_processing_config(pipeline) is True


def test_falls_back_to_json_when_yaml_path_missing(curate_bars, tmp_path: Path):
    """`--pipeline foo.yaml` works when only `foo.json` exists (compiled output)."""
    json_path = tmp_path / "p.json"
    json_path.write_text(json.dumps({"stems": {"drums": {}}}))
    yaml_path_that_doesnt_exist = tmp_path / "p.yaml"
    assert curate_bars._pipeline_injects_processing_config(yaml_path_that_doesnt_exist) is True


def test_returns_false_on_malformed_yaml(curate_bars, tmp_path: Path):
    pipeline = tmp_path / "p.yaml"
    pipeline.write_text("not: valid: yaml: ::: stuff")
    assert curate_bars._pipeline_injects_processing_config(pipeline) is False


# ── Real-world fixture: production_idm.yaml ──────────────────────────────────


def test_real_production_idm_yaml_returns_true(curate_bars):
    """The production_idm.yaml that ships with the repo MUST trigger override."""
    pipeline = REPO_ROOT / "pipelines" / "production_idm.yaml"
    if not pipeline.exists():
        pytest.skip("pipelines/production_idm.yaml not present in this checkout")
    assert curate_bars._pipeline_injects_processing_config(pipeline) is True


# ── Acceptance regression sentinel ───────────────────────────────────────────


def test_believer_bug_anchor():
    """Documentary anchor for the 2026-05-06 believer-bug regression.

    User flow that broke:
        stemforge_curate_bars.py --stems-dir ... --pipeline production_idm.yaml
        # (no --curation flag — defaults curation_config.layout.mode to "stems")

    Manifest produced (pre-fix):
        layout_mode: "stems"           ← wrong: M4L routes to _loadCuratedV2
        processing_config: {drums: ..} ← present but ignored by the dispatcher

    Manifest expected (post-fix):
        layout_mode: "production"      ← M4L routes to loadSong() / buildDrumRack
        processing_config: {drums: ..} ← honored by loadSong()
    """
    # Sentinel: assert the implementation surface exists.
    assert CURATE_BARS_PATH.exists()
    src = CURATE_BARS_PATH.read_text()
    assert "_pipeline_injects_processing_config" in src
    assert 'layout_mode = "production"' in src
