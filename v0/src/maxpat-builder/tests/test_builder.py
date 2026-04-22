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
    box_ids = {b["box"]["id"] for b in patcher["patcher"]["boxes"]}
    # Some elements use variant IDs: audio_in → browse-btn, preset uses obj-preset
    # Some YAML ids map to different box ids in the builder
    id_aliases = {
        "load_button": "obj-load-btn",
        "forge_button": "obj-forge-button",
        "progress_bar": "obj-progress-bar",
        "status_text": "obj-status-text",
    }
    # Elements removed from UI but may still be in yaml for config purposes
    skip_ids = {"title"}  # Ableton device header shows the title
    for el in spec["ui"]["elements"]:
        if el["id"] in skip_ids:
            continue
        expected = id_aliases.get(el["id"], f"obj-{el['id'].replace('_', '-')}")
        assert expected in box_ids, f"missing UI element {el['id']} (looked for {expected})"


def test_bridge_shell_is_present(patcher):
    texts = [b["box"].get("text", "") for b in patcher["patcher"]["boxes"]]
    assert any("shell" == t for t in texts), "shell bridge box missing"


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


def test_dependency_cache_lists_js_files(patcher):
    dep = {e["name"] for e in patcher["patcher"]["dependency_cache"]}
    assert "stemforge_loader.v0.js" in dep
    assert "stemforge_ndjson_parser.v0.js" in dep


def test_patchline_connects_split_to_bridge(patcher):
    lines = patcher["patcher"]["lines"]
    sources = {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0]) for ln in lines
    }
    # cmd fmt → shell bridge → ndjson parser → route events
    assert ("obj-cmd-fmt", "obj-bridge") in sources
    assert ("obj-bridge", "obj-ndjson-parser") in sources
    assert ("obj-ndjson-parser", "obj-route-events") in sources


def test_progress_pct_routed_to_progress_bar(patcher):
    lines = patcher["patcher"]["lines"]
    sources = {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0]) for ln in lines
    }
    assert ("obj-progress-route", "obj-progress-bar") in sources


def test_complete_routed_to_curate(patcher):
    lines = patcher["patcher"]["lines"]
    # complete → unpack → stems dir extract → curate cmd → bridge
    sources = {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0]) for ln in lines
    }
    assert ("obj-route-events", "obj-complete-unpack") in sources
    assert ("obj-complete-unpack", "obj-stems-dir-extract") in sources


def test_version_label_exists(patcher):
    box_ids = {b["box"]["id"] for b in patcher["patcher"]["boxes"]}
    assert "version-label" in box_ids


def test_preset_dict_exists(patcher):
    texts = [b["box"].get("text", "") for b in patcher["patcher"]["boxes"]]
    assert any("dict sf_preset" in t for t in texts), "preset dict missing"


def test_preset_umenu_wired_to_loader(patcher):
    lines = patcher["patcher"]["lines"]
    sources = {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0]) for ln in lines
    }
    assert ("obj-preset-prepend", "obj-loader") in sources


def test_loadbang_triggers_scan_presets(patcher):
    lines = patcher["patcher"]["lines"]
    sources = {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0]) for ln in lines
    }
    assert ("obj-loadbang", "obj-scan-deferlow") in sources
    assert ("obj-scan-deferlow", "obj-scan-presets-msg") in sources
    assert ("obj-scan-presets-msg", "obj-loader") in sources


def test_loader_outlet2_feeds_preset_umenu(patcher):
    lines = patcher["patcher"]["lines"]
    # Loader outlet 2 → preset umenu
    for ln in lines:
        pl = ln["patchline"]
        if pl["source"] == ["obj-loader", 2] and pl["destination"][0] == "obj-preset":
            return
    pytest.fail("loader outlet 2 not wired to preset umenu")


def test_device_width_matches_yaml(patcher):
    with open(DEVICE_YAML) as f:
        spec = yaml.safe_load(f)
    assert patcher["patcher"]["devicewidth"] == float(spec["ui"]["size"]["width"])
