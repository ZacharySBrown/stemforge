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


# ── v8ui canvas (background only — Configurator v1 §3.1 lifts UI to natives) ─


def test_v8ui_canvas_present_in_patching_only(boxes):
    """v0.0.3 removes v8ui from presentation mode — the Configurator v1
    picker/primary/verb live.text widgets own the presentation surface."""
    v8s = [b for b in boxes if b["maxclass"] == "v8ui"]
    assert len(v8s) == 1, "expected exactly one v8ui box"
    v8 = v8s[0]
    assert v8["filename"] == "sf_ui.js"
    # Full-canvas patching_rect (820×149) — sf_state still emits `refresh`
    # to it so the in-script debug surface keeps working.
    assert v8["patching_rect"][2:] == [820, 149]
    # NOT in presentation mode any more — there's no presentation_rect and
    # the `presentation` flag must be absent (or 0).
    assert not v8.get("presentation"), (
        "v8ui must NOT be in presentation mode in Configurator v1 (live.text "
        "buttons own the user surface)"
    )


# ── P0-5 — Configurator v1 picker (spec §3.1) ────────────────────────────────


def test_pick_source_button_present(boxes):
    """The 'Pick source…' button must be a live.text mode-1 widget in
    presentation mode, with varname sf_pick_source_btn."""
    btn = next((b for b in boxes if b.get("varname") == "sf_pick_source_btn"), None)
    assert btn is not None, "missing sf_pick_source_btn"
    assert btn["maxclass"] == "live.text"
    assert btn.get("mode") == 1, "Pick source… button must be momentary (mode 1)"
    assert btn.get("presentation") == 1
    # Spec §3.1 uses the unicode-ellipsis label so the user sees the same
    # visual that the popup advertises.
    assert btn.get("text", "").startswith("Pick source"), (
        "Pick source button text must start with 'Pick source'"
    )


def test_pick_source_wired_to_loader(boxes, line_pairs):
    """Pick source button → [message pickSource] → js sf_lom_loader."""
    msg = next(
        (
            b
            for b in boxes
            if b.get("maxclass") == "message" and b.get("text") == "pickSource"
        ),
        None,
    )
    assert msg is not None, "missing [message pickSource] box"
    assert ("obj-sf-pick-source-btn", msg["id"]) in line_pairs
    assert (msg["id"], "obj-sf-lom-loader") in line_pairs


def test_primary_button_present(boxes):
    """The primary button must be a live.text mode-1 widget. Its label is
    driven by [r primary-btn-label] from the loader; its active state by
    [r primary-btn-enabled]."""
    btn = next((b for b in boxes if b.get("varname") == "sf_primary_btn"), None)
    assert btn is not None, "missing sf_primary_btn"
    assert btn["maxclass"] == "live.text"
    assert btn.get("mode") == 1
    assert btn.get("presentation") == 1


def test_primary_button_wired_via_messnamed(boxes, line_pairs):
    """The loader's `_emitPrimaryButtonState` writes to messnamed receivers
    `primary-btn-label` and `primary-btn-enabled`; the patcher must have
    `[r primary-btn-label]` → prepend set → primary btn, and
    `[r primary-btn-enabled]` → prepend active → primary btn."""
    label_recv = next(
        (b for b in boxes if b.get("text") == "r primary-btn-label"), None
    )
    enabled_recv = next(
        (b for b in boxes if b.get("text") == "r primary-btn-enabled"), None
    )
    assert label_recv is not None, "missing [r primary-btn-label]"
    assert enabled_recv is not None, "missing [r primary-btn-enabled]"
    # Both must route through a prepend → primary btn.
    assert ("obj-sf-primary-label-recv", "obj-sf-primary-label-prepend") in line_pairs
    assert ("obj-sf-primary-label-prepend", "obj-sf-primary-btn") in line_pairs
    assert ("obj-sf-primary-enabled-recv", "obj-sf-primary-enabled-prepend") in line_pairs
    assert ("obj-sf-primary-enabled-prepend", "obj-sf-primary-btn") in line_pairs


def test_primary_click_wired_to_loader(boxes, line_pairs):
    """Primary button click → [message primary] → js sf_lom_loader. The
    loader's `primary()` function dispatches by sniffer type."""
    msg = next(
        (
            b
            for b in boxes
            if b.get("maxclass") == "message" and b.get("text") == "primary"
        ),
        None,
    )
    assert msg is not None, "missing [message primary] box"
    assert ("obj-sf-primary-btn", msg["id"]) in line_pairs
    assert (msg["id"], "obj-sf-lom-loader") in line_pairs


def test_status_picker_text_receives_sf_status(boxes, line_pairs):
    """The picker's status live.text reads from [r sf-status]; the bus is
    driven by a [s sf-status] send fed from the loader's outlet 0 (which
    is where status() emits `set <text>` messages — live.text consumes
    those natively, no `prepend set` needed)."""
    txt = next(
        (b for b in boxes if b.get("varname") == "sf_status_picker_text"), None
    )
    assert txt is not None, "missing sf_status_picker_text"
    assert txt["maxclass"] == "live.text"
    assert txt.get("mode") == 0, "status text must be display-only (mode 0)"

    recv = next((b for b in boxes if b.get("text") == "r sf-status"), None)
    assert recv is not None, "missing [r sf-status]"
    # recv → txt
    assert ("obj-sf-status-recv", "obj-sf-status-picker-text") in line_pairs
    # And a [s sf-status] must be fed by the loader's status outlet (outlet 0).
    send = next((b for b in boxes if b.get("text") == "s sf-status"), None)
    assert send is not None, "missing [s sf-status]"
    assert ("obj-sf-lom-loader", send["id"]) in line_pairs


def test_picker_dialog_wired_from_messnamed_receiver(boxes, line_pairs):
    """pickSource() in the loader fires messnamed("sf-open-source-dialog","bang").

    The patcher must wire `[r sf-open-source-dialog]` → [opendialog] →
    [prepend applyPickedSource] → js sf_lom_loader. The previous design
    routed through a [regexp] box that stripped Macintosh-HFS prefixes;
    we removed it after the first UAT round because [regexp] with
    multi-pattern @substitute arguments has a load-time outlet-count
    quirk that triggered `patchcord outlet out of range`. The HFS→POSIX
    conversion now happens in applyPickedSource() in JS.
    """
    recv = next(
        (b for b in boxes if b.get("text") == "r sf-open-source-dialog"), None
    )
    assert recv is not None, "missing [r sf-open-source-dialog]"
    assert (recv["id"], "obj-sf-picker-dialog") in line_pairs
    # opendialog wires directly to [prepend applyPickedSource] — no regex.
    assert ("obj-sf-picker-dialog", "obj-sf-picker-dialog-prepend") in line_pairs
    prep = next(
        (b for b in boxes if b.get("id") == "obj-sf-picker-dialog-prepend"), None
    )
    assert prep is not None
    assert prep.get("text") == "prepend applyPickedSource"
    assert ("obj-sf-picker-dialog-prepend", "obj-sf-lom-loader") in line_pairs
    # And there must be NO [regexp] in the patcher (regression guard for
    # the outlet-count-race fix).
    assert not any("regexp" in (b.get("text") or "") for b in boxes), (
        "regexp box must not reappear in the picker chain — it caused a "
        "load-time `patchcord outlet out of range` race. Strip HFS in JS."
    )


# ── Verb buttons (COMMIT / BOUNCE / EXPORT) — spec §3.1 right column ─────────


def test_commit_button_present_and_wired(boxes, line_pairs):
    """COMMIT live.text → [message commit] → js sf_lom_loader. The loader's
    `commit()` reads activeCuration and emits messnamed("sf-commit-send"…)."""
    btn = next((b for b in boxes if b.get("varname") == "sf_commit_btn"), None)
    assert btn is not None, "missing sf_commit_btn"
    assert btn["maxclass"] == "live.text"
    assert btn.get("mode") == 1
    assert btn.get("presentation") == 1
    assert btn.get("text") == "COMMIT"

    msg = next(
        (
            b
            for b in boxes
            if b.get("maxclass") == "message" and b.get("text") == "commit"
        ),
        None,
    )
    assert msg is not None, "missing [message commit] box"
    assert ("obj-sf-commit-btn", msg["id"]) in line_pairs
    assert (msg["id"], "obj-sf-lom-loader") in line_pairs


def test_bounce_button_present_and_wired(boxes, line_pairs):
    """BOUNCE live.text → [message bounceCuration] → js sf_lom_loader. The
    loader's `bounceCuration()` falls back to activeCuration when no args."""
    btn = next((b for b in boxes if b.get("varname") == "sf_bounce_btn"), None)
    assert btn is not None, "missing sf_bounce_btn"
    assert btn["maxclass"] == "live.text"
    assert btn.get("mode") == 1
    assert btn.get("presentation") == 1
    assert btn.get("text") == "BOUNCE"

    msg = next(
        (
            b
            for b in boxes
            if b.get("maxclass") == "message" and b.get("text") == "bounceCuration"
        ),
        None,
    )
    assert msg is not None, "missing [message bounceCuration] box"
    assert ("obj-sf-bounce-btn", msg["id"]) in line_pairs
    assert (msg["id"], "obj-sf-lom-loader") in line_pairs


def test_export_button_present_and_wired(boxes, line_pairs):
    """EXPORT live.text → [message exportArrangementSnapshot ~/Desktop/snapshot.json]
    → js sf_lom_loader. The loader's `exportArrangementSnapshot()` writes the
    snapshot to disk."""
    btn = next((b for b in boxes if b.get("varname") == "sf_export_btn"), None)
    assert btn is not None, "missing sf_export_btn"
    assert btn["maxclass"] == "live.text"
    assert btn.get("mode") == 1
    assert btn.get("presentation") == 1
    assert btn.get("text") == "EXPORT"

    msg = next(
        (
            b
            for b in boxes
            if b.get("maxclass") == "message"
            and b.get("text", "").startswith("exportArrangementSnapshot")
        ),
        None,
    )
    assert msg is not None, "missing [message exportArrangementSnapshot …] box"
    assert ("obj-sf-export-btn", msg["id"]) in line_pairs
    assert (msg["id"], "obj-sf-lom-loader") in line_pairs


# ── Snapshot / golden test on the picker + verb-row JSON ────────────────────


def test_picker_and_verb_layout_snapshot(boxes):
    """Snapshot the geometry of the 5 user-visible widgets so future
    layout edits are reviewable. If this test breaks because of a
    deliberate move, update the expected dict here."""
    expected = {
        "sf_pick_source_btn": {"x": 8.0, "y": 8.0, "w": 360.0, "h": 32.0, "mode": 1},
        "sf_status_picker_text": {"x": 8.0, "y": 48.0, "w": 700.0, "h": 28.0, "mode": 0},
        "sf_primary_btn": {"x": 720.0, "y": 8.0, "w": 92.0, "h": 44.0, "mode": 1},
        "sf_commit_btn": {"x": 720.0, "y": 58.0, "mode": 1, "text": "COMMIT"},
        "sf_bounce_btn": {"mode": 1, "text": "BOUNCE"},
        "sf_export_btn": {"mode": 1, "text": "EXPORT"},
    }
    found = {}
    for b in boxes:
        v = b.get("varname")
        if v in expected:
            rect = b.get("presentation_rect") or b.get("patching_rect", [])
            row = {
                "x": rect[0] if len(rect) >= 1 else None,
                "y": rect[1] if len(rect) >= 2 else None,
                "w": rect[2] if len(rect) >= 3 else None,
                "h": rect[3] if len(rect) >= 4 else None,
                "mode": b.get("mode"),
                "text": b.get("text"),
            }
            found[v] = row
    for varname, want in expected.items():
        assert varname in found, f"snapshot missing widget {varname}"
        got = found[varname]
        for key, value in want.items():
            assert got.get(key) == value, (
                f"snapshot widget {varname}.{key}: got {got.get(key)!r}, "
                f"expected {value!r}"
            )


# ── P0-5 + P1-7 — Regression: no legacy controls ─────────────────────────────


def test_no_legacy_preset_or_source_umenus(boxes):
    """The legacy `sf_preset_menu` / `sf_source_menu` umenus must be gone —
    they were the user-visible dropdowns that the new picker replaces."""
    for varname in ("sf_preset_menu", "sf_source_menu"):
        match = next((b for b in boxes if b.get("varname") == varname), None)
        assert match is None, (
            f"legacy umenu {varname!r} found — Configurator v1 §3.1 removes it"
        )
    # Belt-and-braces: no umenu objects at all in the patcher (the loaders
    # may still scan, but their outputs are no longer rendered).
    umenus = [b for b in boxes if b.get("maxclass") == "umenu"]
    assert not umenus, f"unexpected umenu box(es) found: {umenus}"


def test_no_legacy_v8ui_event_route(boxes):
    """The `[route preset_click source_click forge_click … commit_click …]`
    table is removed — Configurator v1 wires clicks directly off live.text
    widgets into the loader's [js] inlet."""
    legacy_route = next(
        (b for b in boxes if b.get("text", "").startswith("route preset_click")),
        None,
    )
    assert legacy_route is None, (
        "legacy v8ui-event route table found — must be removed (P0-5)"
    )


def test_no_commit_click_dead_wire(boxes):
    """P1-7 — `commit_click` was the dead-wire alias for `commitOffsets`
    pulled into sf_forge. The new COMMIT button goes directly to the loader."""
    # Scan every text field for the dead string.
    for b in boxes:
        text = b.get("text", "") or ""
        assert "commit_click" not in text, (
            f"dead-wire 'commit_click' found in box {b.get('id')!r} text"
        )
        assert "commitOffsets" not in text, (
            f"dead-wire 'commitOffsets' found in box {b.get('id')!r} text — "
            "the new COMMIT goes direct to js.commit()"
        )


def test_no_legacy_forge_click_or_other_routes(boxes):
    """All the legacy [route ...] outlet branches are gone."""
    legacy_strings = (
        "preset_click",
        "source_click",
        "forge_click",
        "anchor_locator_click",
        "bounce_clips_click",
        "export_song_click",
        "arrangement_load_click",
    )
    for b in boxes:
        text = (b.get("text", "") or "")
        for needle in legacy_strings:
            assert needle not in text, (
                f"legacy token {needle!r} found in box {b.get('id')!r}"
            )


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


def test_every_js_box_declares_numoutlets_in_text(boxes):
    """Every [js] box MUST carry @numoutlets in its text attribute.

    Without this, Max defaults a fresh [js] box to outlets=1 and only honors
    the JS file's `outlets = N` declaration AFTER the script has finished
    evaluating. During that interval Max walks the saved patcher cords and
    deletes any whose source-outlet index >= 1 as
    "patchcord outlet out of range: deleting patchcord". This is the regression
    fix from the 2026-05-14 install-time triage. The box-level numoutlets field
    is NOT enough — Max ignores it for [js] in favor of the text-arg attribute.
    """
    import re

    for box in boxes:
        text = box.get("text", "")
        if not text.startswith("js "):
            continue
        assert "@numoutlets" in text, (
            f"[js] box missing @numoutlets in text: {text!r} — Max will lose "
            "cords during the init race. See _js_box() in builder.py."
        )
        m = re.search(r"@numoutlets\s+(\d+)", text)
        assert m, f"could not parse @numoutlets from {text!r}"
        assert int(m.group(1)) == box["numoutlets"], (
            f"@numoutlets {m.group(1)} disagrees with box numoutlets "
            f"{box['numoutlets']} for {text!r}"
        )


# ── Dicts ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dict_name",
    ["sf_state", "sf_preset", "sf_manifest", "sf_settings"],
)
def test_each_canonical_dict_is_declared(boxes, dict_name):
    texts = _texts(boxes)
    assert any(t == f"dict {dict_name}" for t in texts), f"missing [dict {dict_name}] box"


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


def test_open_editor_button_present(boxes):
    """Phase 4B — footer carries the 'Open Editor' live.text button."""
    btn = next((b for b in boxes if b.get("varname") == "sf_open_editor_btn"), None)
    assert btn is not None, "missing sf_open_editor_btn"
    assert btn["maxclass"] == "live.text"
    # mode 1 = momentary button; label is the click-emitted symbol.
    assert btn.get("mode") == 1
    assert btn.get("text") == "Open Editor"


def test_open_editor_button_wired_to_loader(line_pairs):
    """Phase 4B — button → [t b] → [message openEditor] → [js sf_lom_loader]."""
    assert ("obj-sf-open-editor-btn", "obj-sf-open-editor-tb") in line_pairs
    assert ("obj-sf-open-editor-tb", "obj-sf-open-editor-msg") in line_pairs
    assert ("obj-sf-open-editor-msg", "obj-sf-lom-loader") in line_pairs


def test_open_editor_message_names_handler(boxes):
    """The [message] box's text is the JS handler name resolved by [js]."""
    msg = next((b for b in boxes if b.get("id") == "obj-sf-open-editor-msg"), None)
    assert msg is not None, "missing obj-sf-open-editor-msg"
    assert msg["maxclass"] == "message"
    assert msg.get("text") == "openEditor"


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


def test_preset_loader_still_present(boxes):
    """Configurator v1 removed the preset umenu, but sf_preset_loader.js is
    kept in the patcher (loaded at boot) so a future picker can re-use the
    same scan results without touching the legacy dropdown surface."""
    pre = next((b for b in boxes if "js sf_preset_loader.js" in b.get("text", "")), None)
    assert pre is not None


def test_manifest_loader_still_present(boxes):
    """Same as above for sf_manifest_loader.js — kept for the loadbang scan
    even though its umenu surface is gone."""
    mf = next((b for b in boxes if "js sf_manifest_loader.js" in b.get("text", "")), None)
    assert mf is not None


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


def test_all_live_widgets_opt_out_of_parameter_enrollment(boxes):
    """Every `live.*` widget in the device must either declare
    `parameter_enable: 0` OR carry a full `saved_attribute_attributes.valueof`
    block.

    Background: M4L's host (Live) probes every `live.*` widget at device
    load to build the parameter inventory. Widgets lacking BOTH a
    `parameter_enable: 0` opt-out AND a `saved_attribute_attributes.valueof`
    table emit one `SendMessage error 2: Bad parameter value` to the Max
    console each — the cosmetic boot-noise tracked in
    `docs/issues/max-startup-sendmessage-errors.md`.

    See builder.py inline comments on `obj-sf-status-text` /
    `obj-sf-version-text` for the fix rationale.
    """
    live_widgets = [b for b in boxes if b.get("maxclass", "").startswith("live.")]
    assert live_widgets, "expected at least one live.* widget in the device"
    offenders: list[str] = []
    for b in live_widgets:
        if b.get("parameter_enable") == 0:
            continue
        saa = b.get("saved_attribute_attributes") or {}
        if "valueof" in saa:
            continue
        offenders.append(f"{b.get('id')} ({b.get('maxclass')})")
    assert not offenders, (
        "live.* widgets without parameter_enable:0 or saved_attribute_attributes.valueof "
        f"(each emits one SendMessage error 2 at boot): {offenders}"
    )
