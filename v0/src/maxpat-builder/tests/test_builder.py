"""Unit tests for the maxpat builder.

Verifies that every UI element declared in v0/interfaces/device.yaml ends up
in the generated patcher, and that the patchlines wire progress/error/complete
paths correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from builder import build_patcher

REPO_ROOT = Path(__file__).resolve().parents[4]
DEVICE_YAML = REPO_ROOT / "v0" / "interfaces" / "device.yaml"


@pytest.fixture(scope="module")
def patcher() -> dict:
    return build_patcher(DEVICE_YAML)


def test_top_level_patcher_shape(patcher):
    assert "patcher" in patcher
    p = patcher["patcher"]
    # Must be marked modernui so Live 11+ renders correctly.
    assert p["appversion"]["modernui"] == 1
    assert p["openinpresentation"] == 1
    assert isinstance(p["boxes"], list)
    assert isinstance(p["lines"], list)
    assert p["boxes"], "patcher has no boxes"


def test_every_device_yaml_ui_element_is_represented(patcher):
    with open(DEVICE_YAML) as f:
        spec = yaml.safe_load(f)
    # Collect box ids — both canonical "obj-<id>" and free-form.
    box_ids = {b["box"]["id"] for b in patcher["patcher"]["boxes"]}
    for el in spec["ui"]["elements"]:
        expected = f"obj-{el['id'].replace('_', '-')}"
        assert expected in box_ids, f"missing UI element {el['id']} (looked for {expected})"


def test_bridge_node_script_is_present(patcher):
    texts = [b["box"].get("text", "") for b in patcher["patcher"]["boxes"]]
    bridges = [t for t in texts if "node.script" in t and "stemforge_bridge.v0.js" in t]
    assert bridges, "bridge node.script box missing"


def test_loader_js_is_present(patcher):
    texts = [b["box"].get("text", "") for b in patcher["patcher"]["boxes"]]
    assert any("stemforge_loader.v0.js" in t for t in texts), "loader js box missing"


def test_route_object_splits_event_types(patcher):
    texts = [b["box"].get("text", "") for b in patcher["patcher"]["boxes"]]
    route_lines = [t for t in texts if t.startswith("route ")]
    assert route_lines, "no route object found"
    tokens = set(route_lines[0].split())
    # Every NDJSON event we care to surface must appear in the route.
    for needed in ("progress", "stem", "bpm", "slice_dir", "complete", "error"):
        assert needed in tokens, f"route object missing branch for {needed}"


def test_dependency_cache_lists_both_js_files(patcher):
    dep = {e["name"] for e in patcher["patcher"]["dependency_cache"]}
    assert "stemforge_bridge.v0.js" in dep
    assert "stemforge_loader.v0.js" in dep


def test_patchline_connects_button_to_bridge(patcher):
    lines = patcher["patcher"]["lines"]
    # split_button → pack-split → bridge chain must exist.
    sources = {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0]) for ln in lines
    }
    assert ("obj-split-button", "obj-pack-split") in sources
    assert ("obj-pack-split", "obj-bridge") in sources
    assert ("obj-bridge", "obj-route-events") in sources


def test_progress_pct_routed_to_progress_bar(patcher):
    lines = patcher["patcher"]["lines"]
    sources = {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0]) for ln in lines
    }
    assert ("obj-progress-route", "obj-progress-bar") in sources


def test_complete_routed_to_loader(patcher):
    lines = patcher["patcher"]["lines"]
    # complete branch of the route → prepend loadManifest → loader js
    sources = {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0]) for ln in lines
    }
    assert ("obj-route-events", "obj-complete-prepend") in sources
    assert ("obj-complete-prepend", "obj-loader") in sources


def test_device_width_matches_yaml(patcher):
    with open(DEVICE_YAML) as f:
        spec = yaml.safe_load(f)
    assert patcher["patcher"]["devicewidth"] == float(spec["ui"]["size"]["width"])
