"""Unit tests for the Configurator Strip patcher builder.

Static-analysis only — these run without Max installed. They assert on the
generated .maxpat JSON structure: every operation button is wired, the
HTTP/[jweb]/[shell] infrastructure is present, the strip's audio-effect
container fields are correct, and the JS dependency cache is set.

Phase 3 acceptance gate: `pytest v0/src/m4l-devices/configurator-strip/tests`
plus the Node-based JS suite must both pass before .amxd packaging.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from builder import (
    OBJ_JS,
    OBJ_JWEB,
    OBJ_LOADBANG,
    OBJ_PLUGIN_IN,
    OBJ_PLUGOUT,
    OBJ_SHELL,
    OBJ_STATUS_DOT,
    OBJ_STATUS_TEXT,
    OBJ_FOOTER_TEXT,
    OBJ_VERSION_TEXT,
    VERB_TO_HANDLER,
    _btn_box_id,
    _btn_msg_id,
    _btn_tb_id,
    build_patcher,
)

HERE = Path(__file__).resolve().parent
DEVICE_YAML = HERE.parent / "device.yaml"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def spec() -> dict:
    with open(DEVICE_YAML) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def patcher() -> dict:
    return build_patcher(DEVICE_YAML)


@pytest.fixture(scope="module")
def boxes(patcher) -> list[dict]:
    return [b["box"] for b in patcher["patcher"]["boxes"]]


@pytest.fixture(scope="module")
def box_by_id(boxes) -> dict[str, dict]:
    return {b["id"]: b for b in boxes}


@pytest.fixture(scope="module")
def line_pairs(patcher) -> set[tuple[str, str]]:
    """Return set of (src_id, dst_id) pairs across all patchlines."""
    return {
        (ln["patchline"]["source"][0], ln["patchline"]["destination"][0])
        for ln in patcher["patcher"]["lines"]
    }


# ── Top-level shape ─────────────────────────────────────────────────────────


def test_patcher_has_required_top_level_fields(patcher):
    p = patcher["patcher"]
    assert p["openinpresentation"] == 1
    assert p["appversion"]["modernui"] == 1
    assert isinstance(p["boxes"], list) and p["boxes"]
    assert isinstance(p["lines"], list) and p["lines"]


def test_devicewidth_matches_yaml(spec, patcher):
    assert patcher["patcher"]["devicewidth"] == float(spec["ui"]["size"]["width"])


def test_project_field_present_with_audio_effect_amxdtype(patcher):
    """Pitfall #6 — without `project`, Max rejects the device. Pitfall #14 —
    amxdtype must be 0x61616161 ('aaaa') for audio effects."""
    proj = patcher["patcher"]["project"]
    assert proj["version"] == 1
    # 0x61616161 = 1633771873 = b'aaaa' as u32 LE.
    assert proj["amxdtype"] == 1633771873


# ── Audio passthrough — pitfall #7 ──────────────────────────────────────────


def test_plugin_in_and_plugout_present(box_by_id, line_pairs):
    assert OBJ_PLUGIN_IN in box_by_id
    assert OBJ_PLUGOUT in box_by_id
    assert box_by_id[OBJ_PLUGIN_IN]["text"] == "plugin~ 2"
    assert box_by_id[OBJ_PLUGOUT]["text"] == "plugout~ 2"
    assert (OBJ_PLUGIN_IN, OBJ_PLUGOUT) in line_pairs


# ── Buttons: exactly seven, each wired ──────────────────────────────────────


def test_exactly_seven_operation_buttons(spec, boxes):
    button_ids = {b["id"] for b in spec["ui"]["buttons"]["items"]}
    assert len(button_ids) == 7, "device.yaml must declare exactly 7 buttons"
    btn_boxes = [b for b in boxes if b["id"].startswith("obj-btn-")]
    assert len(btn_boxes) == 7, "patcher must contain exactly 7 button boxes"


def test_every_button_is_live_text_with_label_and_accent(spec, box_by_id):
    palette = spec["palette"]
    for btn in spec["ui"]["buttons"]["items"]:
        bid = _btn_box_id(btn["id"])
        assert bid in box_by_id, f"missing button box {bid}"
        b = box_by_id[bid]
        assert b["maxclass"] == "live.text"
        assert b["presentation"] == 1
        assert b["text"] == btn["label"]
        # Accent matches the orange brand color.
        assert b["activebgcolor"] == palette["accent"]
        # Display-only — opt out of M4L parameter enrollment.
        assert b["parameter_enable"] == 0


DIALOG_VERBS = {"load-manifest", "export"}


def test_every_button_has_tb_and_message_handler(spec, box_by_id, line_pairs):
    """Pitfall #17 — buttons need [t b] to convert label-symbol into a bang
    before firing the JS handler.

    Dialog-bearing verbs (load-manifest, export) route the bang through a
    file picker first; see `test_dialog_bearing_buttons_have_file_picker`.
    """
    for btn in spec["ui"]["buttons"]["items"]:
        verb = btn["verb"]
        handler = VERB_TO_HANDLER[verb]

        btn_box = _btn_box_id(btn["id"])
        tb_box = _btn_tb_id(btn["id"])

        assert tb_box in box_by_id
        assert box_by_id[tb_box]["text"] == "t b"
        # button → t b is shared by all verbs.
        assert (btn_box, tb_box) in line_pairs

        if verb in DIALOG_VERBS:
            # Picker variants have no [message handler] box; their wiring is
            # asserted in test_dialog_bearing_buttons_have_file_picker.
            continue

        msg_box = _btn_msg_id(btn["id"])
        assert msg_box in box_by_id
        assert box_by_id[msg_box]["text"] == handler
        # t b → message → JS for the standard path.
        assert (tb_box, msg_box) in line_pairs
        assert (msg_box, OBJ_JS) in line_pairs


def test_dialog_bearing_buttons_have_file_picker(spec, box_by_id, line_pairs):
    """Load Manifest and Export pop native file dialogs ([opendialog] /
    [savedialog]) and pipe the chosen path into the JS via [prepend H].
    Without the picker the user has to type an absolute path by hand.
    """
    items = {b["verb"]: b for b in spec["ui"]["buttons"]["items"]}

    # ── load-manifest → [opendialog] → [prepend loadManifest] → JS ──────────
    if "load-manifest" in items:
        btn = items["load-manifest"]
        tb_box = _btn_tb_id(btn["id"])
        dlg_id = f"{_btn_msg_id(btn['id'])}-opendialog"
        prep_id = f"{_btn_msg_id(btn['id'])}-prep"
        assert dlg_id in box_by_id, "load-manifest missing [opendialog]"
        assert box_by_id[dlg_id]["text"] == "opendialog"
        assert prep_id in box_by_id, "load-manifest missing [prepend loadManifest]"
        assert box_by_id[prep_id]["text"] == "prepend loadManifest"
        assert (tb_box, dlg_id) in line_pairs
        assert (dlg_id, prep_id) in line_pairs
        assert (prep_id, OBJ_JS) in line_pairs

    # ── export → [savedialog] → [prepend exportPpak] → JS ───────────────────
    if "export" in items:
        btn = items["export"]
        tb_box = _btn_tb_id(btn["id"])
        dlg_id = f"{_btn_msg_id(btn['id'])}-savedialog"
        prep_id = f"{_btn_msg_id(btn['id'])}-prep"
        assert dlg_id in box_by_id, "export missing [savedialog]"
        assert box_by_id[dlg_id]["text"].startswith("savedialog")
        assert prep_id in box_by_id, "export missing [prepend exportPpak]"
        assert box_by_id[prep_id]["text"] == "prepend exportPpak"
        assert (tb_box, dlg_id) in line_pairs
        assert (dlg_id, prep_id) in line_pairs
        assert (prep_id, OBJ_JS) in line_pairs


# ── JS dispatcher object ────────────────────────────────────────────────────


def test_js_object_present_with_scripting_name(spec, box_by_id):
    js_cfg = spec["js"]
    assert OBJ_JS in box_by_id
    text = box_by_id[OBJ_JS]["text"]
    assert text.startswith(f"js {js_cfg['filename']}")
    assert f"@scripting_name {js_cfg['scripting_name']}" in text
    assert box_by_id[OBJ_JS]["numoutlets"] == js_cfg["numoutlets"]


def test_js_dependency_cache_points_at_stemforge_package(spec, patcher):
    js_cfg = spec["js"]
    cache = patcher["patcher"]["dependency_cache"]
    names = [entry["name"] for entry in cache]
    assert js_cfg["filename"] in names
    entry = next(e for e in cache if e["name"] == js_cfg["filename"])
    assert "StemForge/javascript" in entry["bootpath"]


def test_loadbang_fires_into_js(box_by_id, line_pairs):
    assert OBJ_LOADBANG in box_by_id
    assert box_by_id[OBJ_LOADBANG]["text"] == "loadbang"
    assert (OBJ_LOADBANG, OBJ_JS) in line_pairs


# ── jweb (popup) ────────────────────────────────────────────────────────────


def test_jweb_object_present_and_sized(spec, box_by_id, line_pairs):
    assert OBJ_JWEB in box_by_id
    jweb_box = box_by_id[OBJ_JWEB]
    assert jweb_box["maxclass"] == "jweb"
    # Default URL is about:blank — script sends openurl on user click.
    assert jweb_box["url"] == "about:blank"
    # Size matches device.yaml.
    expected_w = float(spec["jweb"]["size"]["width"])
    expected_h = float(spec["jweb"]["size"]["height"])
    assert jweb_box["patching_rect"][2] == expected_w
    assert jweb_box["patching_rect"][3] == expected_h
    # JS outlet 3 → jweb.
    assert (OBJ_JS, OBJ_JWEB) in line_pairs


# ── shell (HTTP via curl + start-server) ────────────────────────────────────


def test_shell_object_present_and_wired(box_by_id, line_pairs):
    assert OBJ_SHELL in box_by_id
    assert box_by_id[OBJ_SHELL]["text"] == "shell"
    # JS outlet 4 → shell.
    assert (OBJ_JS, OBJ_SHELL) in line_pairs


# ── Status indicator + footer + version ─────────────────────────────────────


def test_status_indicator_present_in_presentation(spec, box_by_id):
    palette = spec["palette"]
    assert OBJ_STATUS_DOT in box_by_id
    dot = box_by_id[OBJ_STATUS_DOT]
    assert dot["maxclass"] == "live.text"
    assert dot["presentation"] == 1
    # Initial state is "checking" (warn).
    assert dot["bgcolor"] == palette["dot_warn"]
    assert dot["parameter_enable"] == 0


def test_status_text_and_footer_and_version_present(box_by_id, line_pairs):
    for obj_id in (OBJ_STATUS_TEXT, OBJ_FOOTER_TEXT, OBJ_VERSION_TEXT):
        assert obj_id in box_by_id
        assert box_by_id[obj_id]["maxclass"] == "live.comment"
        assert box_by_id[obj_id]["presentation"] == 1
        assert box_by_id[obj_id]["parameter_enable"] == 0

    # JS outlets 0/1/2 must reach the live.* widgets.
    # outlet 0 → status_text (via [prepend set])
    # outlet 1 → footer_text (via [prepend set])
    # outlet 2 → status_dot
    js_outlet_destinations = {dst for src, dst in line_pairs if src == OBJ_JS}
    assert OBJ_STATUS_DOT in js_outlet_destinations
    # status_text and footer_text receive via prepend boxes — assert each is
    # reachable from JS through one hop.
    prep_targets = {dst for src, dst in line_pairs if src.startswith("obj-prep-")}
    assert OBJ_STATUS_TEXT in prep_targets
    assert OBJ_FOOTER_TEXT in prep_targets


# ── Verb table integrity ────────────────────────────────────────────────────


def test_every_yaml_verb_has_handler_mapping(spec):
    for btn in spec["ui"]["buttons"]["items"]:
        assert btn["verb"] in VERB_TO_HANDLER, (
            f"device.yaml verb {btn['verb']!r} has no handler in VERB_TO_HANDLER"
        )


def test_commit_handler_exists_even_though_not_a_button():
    """COMMIT walks LOM and POSTs /intent/commit. The big device's COMMIT
    button fires it via the shared message dispatcher — the strip script
    exposes the same function name so future wiring is one-line."""
    assert VERB_TO_HANDLER["commit"] == "commit"


# ── Patcher pack sanity ─────────────────────────────────────────────────────


def test_patcher_is_json_serialisable(patcher):
    import json

    s = json.dumps(patcher)
    assert "ConfiguratorStrip" in s or "Phase 3" in s
