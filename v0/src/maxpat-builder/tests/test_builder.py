"""Unit tests for the v0.1.0 v8ui-matrix maxpat builder.

Verifies that the patcher contains the v8ui canvas, all required modular JS
objects, the preserved NDJSON/LOM-loader objects, the status-bar widgets, and
the key patchlines from sf_state → v8ui and sf_forge → [shell]/LOM.
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


@pytest.fixture(scope="module")
def boxes(patcher) -> list[dict]:
    return [b["box"] for b in patcher["patcher"]["boxes"]]


@pytest.fixture(scope="module")
def line_pairs(patcher) -> set[tuple[str, str]]:
    """Return set of (src_id, dst_id) pairs, ignoring inlet/outlet indexes."""
    return {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0])
        for ln in patcher["patcher"]["lines"]
    }


def _texts(boxes: list[dict]) -> list[str]:
    return [b.get("text", "") for b in boxes]


def _box_ids(boxes: list[dict]) -> set[str]:
    return {b["id"] for b in boxes}


# ── Top-level shape ──────────────────────────────────────────────────────────


def test_top_level_patcher_shape(patcher):
    assert "patcher" in patcher
    p = patcher["patcher"]
    assert p["appversion"]["modernui"] == 1
    assert p["openinpresentation"] == 1
    assert isinstance(p["boxes"], list) and p["boxes"]
    assert isinstance(p["lines"], list) and p["lines"]


def test_device_width_matches_yaml(patcher):
    with open(DEVICE_YAML) as f:
        spec = yaml.safe_load(f)
    assert patcher["patcher"]["devicewidth"] == float(spec["ui"]["size"]["width"])
    assert patcher["patcher"]["devicewidth"] == 820.0


# ── v8ui canvas (the heart of the new UI) ────────────────────────────────────


def test_v8ui_canvas_present(boxes):
    v8s = [b for b in boxes if b["maxclass"] == "v8ui"]
    assert len(v8s) == 1, "expected exactly one v8ui box"
    v8 = v8s[0]
    assert v8["filename"] == "sf_ui.js"
    # Full-canvas patching_rect (820×149) per contract §1 — script still
    # renders/measures the whole canvas.
    assert v8["patching_rect"][2:] == [820, 149]
    # Presentation-mode rect is narrowed to middle+right columns only
    # (x=212..820, w=608) so the left column can host visible native
    # preset/source umenus without visual collision.
    assert v8["presentation_rect"][0] == 212.0
    assert v8["presentation_rect"][1] == 0
    assert v8["presentation_rect"][2:] == [608.0, 149]
    assert v8.get("presentation") == 1


def test_preset_and_source_umenus_visible(boxes):
    """The two dropdowns must be in presentation mode with visible native
    chrome (no transparency overrides) and a clickable arrow — this is the
    reliability fix for the Ableton popup-click regression."""
    preset = next((b for b in boxes if b.get("varname") == "sf_preset_menu"), None)
    source = next((b for b in boxes if b.get("varname") == "sf_source_menu"), None)
    assert preset is not None, "sf_preset_menu umenu missing"
    assert source is not None, "sf_source_menu umenu missing"

    for menu, expected_y in [(preset, 8.0), (source, 54.0)]:
        assert menu["maxclass"] == "umenu"
        assert menu.get("presentation") == 1
        rect = menu["presentation_rect"]
        assert rect[0] == 8.0
        assert rect[1] == expected_y
        assert rect[2] == 196.0
        assert rect[3] == 40.0
        assert menu.get("arrow") == 1
        # No transparency overrides — rely on default visible chrome.
        assert "bgcolor" not in menu
        assert "textcolor" not in menu
        assert "bordercolor" not in menu
        assert "elementcolor" not in menu


def test_v8ui_emits_events_via_route(boxes, line_pairs):
    # There must be a [route ... preset_click ... forge_click ...] wired
    # from the v8ui outlet.
    route = next(
        (b for b in boxes if b.get("text", "").startswith("route preset_click")),
        None,
    )
    assert route is not None, "missing route for v8ui events"
    tokens = set(route["text"].split())
    for required in (
        "preset_click", "source_click", "forge_click",
        "cancel_click", "retry_click", "done_click", "settings_click",
    ):
        assert required in tokens, f"route missing branch for {required}"
    assert ("obj-sf-ui", route["id"]) in line_pairs


# ── Modular JS objects ───────────────────────────────────────────────────────


REQUIRED_JS_FILES = [
    "sf_state.js",
    "sf_forge.js",
    "sf_preset_loader.js",
    "sf_manifest_loader.js",
    "sf_settings.js",
    "sf_logger.js",
    "stemforge_ndjson_parser.v0.js",
    "stemforge_loader.v0.js",
]


@pytest.mark.parametrize("js_file", REQUIRED_JS_FILES)
def test_each_js_module_has_a_box(boxes, js_file):
    texts = _texts(boxes)
    hits = [t for t in texts if t.startswith(f"js {js_file}")]
    assert hits, f"no [js {js_file}] box found"


def test_dependency_cache_lists_every_js(patcher):
    dep = {e["name"] for e in patcher["patcher"]["dependency_cache"]}
    # sf_ui.js is an attribute on the v8ui, but should still be declared
    # as a dependency so Max can locate it at device load.
    for needed in ["sf_ui.js"] + REQUIRED_JS_FILES:
        assert needed in dep, f"dependency_cache missing {needed}"


# ── Dicts ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dict_name",
    ["sf_state", "sf_preset", "sf_manifest", "sf_settings"],
)
def test_each_canonical_dict_is_declared(boxes, dict_name):
    texts = _texts(boxes)
    assert any(t == f"dict {dict_name}" for t in texts), (
        f"missing [dict {dict_name}] box"
    )


# ── Status bar native objects ────────────────────────────────────────────────


def test_status_dot_widget(boxes):
    dot = next((b for b in boxes if b.get("varname") == "sf_status_dot"), None)
    assert dot is not None, "missing sf_status_dot"
    assert dot["maxclass"] == "live.text"


def test_status_text_widget(boxes):
    txt = next((b for b in boxes if b.get("varname") == "sf_status_text"), None)
    assert txt is not None, "missing sf_status_text"
    assert txt["maxclass"] == "live.comment"


def test_version_text_widget(boxes):
    ver = next((b for b in boxes if b.get("varname") == "sf_version_text"), None)
    assert ver is not None, "missing sf_version_text"
    assert ver["maxclass"] == "live.comment"
    assert ver.get("text", "").startswith("v"), "version text should start with 'v'"


# ── Wiring ───────────────────────────────────────────────────────────────────


def test_state_mgr_redraws_v8ui(line_pairs):
    # sf_state → prepend refresh → v8ui
    assert ("obj-sf-state", "obj-refresh-prepend") in line_pairs
    assert ("obj-refresh-prepend", "obj-sf-ui") in line_pairs


def test_forge_outlets_wired(line_pairs):
    # outlet 0 → state mgr, outlet 1 → shell, outlet 2 → lom loader
    assert ("obj-sf-forge", "obj-sf-state") in line_pairs
    assert ("obj-sf-forge", "obj-shell") in line_pairs
    assert ("obj-sf-forge", "obj-sf-lom-loader") in line_pairs


def test_preset_loader_to_state(line_pairs):
    # outlet 0 → umenu, outlet 1 → state
    assert ("obj-sf-preset-loader", "obj-umenu-preset") in line_pairs
    assert ("obj-sf-preset-loader", "obj-sf-state") in line_pairs


def test_manifest_loader_to_state_and_popup(line_pairs, boxes):
    assert ("obj-sf-manifest-loader", "obj-umenu-source") in line_pairs
    # outlet 1 → route setSource browseAudio
    route = next(
        (b for b in boxes if b.get("text", "").startswith("route setSource")), None
    )
    assert route is not None
    assert ("obj-sf-manifest-loader", route["id"]) in line_pairs


def test_ndjson_parser_wired_from_shell(line_pairs):
    assert ("obj-shell", "obj-sf-ndjson-parser") in line_pairs


def test_ndjson_route_object_splits_events(boxes):
    route = next(
        (b for b in boxes if b.get("text", "").startswith("route progress stem")),
        None,
    )
    assert route is not None, "ndjson route object missing"
    tokens = set(route["text"].split())
    for needed in ("progress", "stem", "bpm", "slice_dir", "complete", "curated", "error"):
        assert needed in tokens


def test_loadbang_kickstarts_scans(line_pairs):
    assert ("obj-loadbang", "obj-load-deferlow") in line_pairs
    # deferlow → sequencer → scan messages into each loader
    assert ("obj-load-deferlow", "obj-load-seq") in line_pairs


# ── Audio passthrough (required for M4L audio effect) ────────────────────────


def test_audio_passthrough_present(boxes, line_pairs):
    texts = _texts(boxes)
    assert any("plugin~ 2" in t for t in texts)
    assert any("plugout~ 2" in t for t in texts)
    assert ("obj-plugin-in", "obj-plugout") in line_pairs


# ── No old-layout leftovers (regression guards) ──────────────────────────────


def test_no_live_slider_progress_bar(boxes):
    """v0.1.0 removed the live.slider progress bar — v8ui draws its own."""
    texts = _texts(boxes)
    assert not any("StemForge Progress" in str(b) for b in boxes), (
        "old progress-bar live.slider should be gone"
    )


def test_no_old_forge_textbutton(boxes):
    """v0.1.0 removed the legacy FORGE textbutton — button lives in v8ui."""
    # A `textbutton` with text 'FORGE' would mean we regressed.
    for b in boxes:
        if b.get("maxclass") == "textbutton" and b.get("text") == "FORGE":
            pytest.fail("stray FORGE textbutton — should be drawn by v8ui")
