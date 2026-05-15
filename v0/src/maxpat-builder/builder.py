"""
builder — generate a Max for Live patcher (.maxpat JSON) from v0/interfaces/device.yaml.

Configurator v1 layout (spec §3.1 — see specs/CONSOLIDATED_DESIGN.md).
v0.0.3 lifts the device patcher's visible surface off the legacy
PRESET/SOURCE umenu + LOAD/ANCH split-row + forge_click/commit_click
route table; what ships now is a single picker + primary button row +
verb-button row, all natively-rendered live.text widgets that talk to
stemforge_loader.v0.js by direct message-name.

    ┌──────────────────────────────────────────────────────────────────┐
    │  Device canvas 820 × 169 (fixed M4L height)                      │
    │                                                                  │
    │  ┌──────────────────────────────────┐  ┌──────────────────────┐  │
    │  │  [ Pick source… ]                │  │  FORGE / LOAD FORGE  │  │
    │  │  status: <sniffer text>          │  │  / LOAD CURATION     │  │
    │  │   (live.text → js.pickSource)    │  │   (label driven by   │  │
    │  │   (live.text ← r sf-status)      │  │    primary-btn-label)│  │
    │  └──────────────────────────────────┘  ├──────────────────────┤  │
    │   [ v8ui sf_ui.js — background paint ] │  COMMIT  BOUNCE EXPRT│  │
    │                                        │   (3 small buttons)  │  │
    │                                        └──────────────────────┘  │
    │  [ Open Editor ]   ● status dot · status text · v0.1.0           │
    └──────────────────────────────────────────────────────────────────┘

The v8ui canvas is still present (sf_state still drives its `refresh`
hook so legacy debug-painting works) but it is no longer the source of
truth for clicks — it is painted in the background only, behind the
new presentation-mode widgets.

Logic layer objects (classic [js], not in presentation):
    [js sf_state.js       @scripting_name sf_state_mgr]
    [js sf_forge.js       @scripting_name sf_forge_mgr]
    [js sf_preset_loader.js]       (preserved — populated by loadbang scan)
    [js sf_manifest_loader.js]     (preserved — populated by loadbang scan)
    [js sf_settings.js    @scripting_name sf_settings_mgr]
    [js sf_logger.js      @scripting_name sf_logger]

Preserved (unchanged) objects, reused by sf_forge:
    [js stemforge_ndjson_parser.v0.js]
    [js stemforge_loader.v0.js        @scripting_name sf_lom_loader]

Wiring summary (Configurator v1 §3.1 picker contract):
    sf_pick_source_btn (live.text mode 1) → [message pickSource]
        → [js sf_lom_loader]  (calls pickSource(), which fires
        messnamed("sf-open-source-dialog","bang"))

    [r sf-open-source-dialog] → [opendialog] → regex (HFS→POSIX)
        → [prepend applyPickedSource] → [js sf_lom_loader]

    sf_primary_btn (live.text mode 1) → [message primary]
        → [js sf_lom_loader]  (dispatches by pickedSource.type)
    [r primary-btn-label]   → set text of sf_primary_btn
    [r primary-btn-enabled] → set active of sf_primary_btn

    sf_commit_btn   → [message commit]         → [js sf_lom_loader]
    sf_bounce_btn   → [message bounceCuration] → [js sf_lom_loader]
    sf_export_btn   → [message exportArrangementSnapshot ~/Desktop/snapshot.json]
                                                 → [js sf_lom_loader]

    sf_open_editor_btn (footer) → [t b] → [message openEditor]
                                                 → [js sf_lom_loader]

    sf_state_mgr outlet 0 → [v8ui sf_ui] refresh (redraw on every mutation
                              — still wired so sf_state's UI debug surface
                              keeps working).
    sf_forge_mgr outlet 0 → sf_state_mgr (phase transitions)
    sf_forge_mgr outlet 1 → [shell]        (Phase 1 native binary)
    sf_forge_mgr outlet 2 → sf_lom_loader  (Phase 2 LiveAPI track creation)

    [shell] → [js stemforge_ndjson_parser] → [route progress stem bpm slice_dir
              complete curated error] → sf_forge_mgr on* handlers

UDP receivers (HW-4 sf_remote bus, §6 docs/remote_debug.md): unchanged.
    [udpreceive 7420] → [route /state /forge /preset-loader …] → modules
    [udpreceive 7421] → sf_state_mgr (dumpDict)

Dicts (created by a leading [dict] object per contract §2):
    sf_state / sf_preset / sf_manifest / sf_settings

Removed in Configurator v1 (P0-5 + P1-7):
    - sf_preset_menu umenu, sf_source_menu umenu (replaced by Pick source… btn)
    - the OBJ_ROUTE_UI_EVENTS [route preset_click source_click forge_click
      cancel_click retry_click done_click settings_click commit_click
      bounce_clips_click export_song_click arrangement_load_click
      anchor_locator_click] table and every legacy [message] / [opendialog]
      branch hanging off it (preset_click, source_click, forge_click,
      cancel_click, retry_click, done_click, settings_click, commit_click,
      bounce_clips_click, export_song_click, arrangement_load_click,
      anchor_locator_click).
    - Net effect: the v8ui's outlet-0 events are no longer consumed (the
      v8ui's onclick still fires, harmlessly).

The .amxd is packed by amxd_pack.py and installed via tools/sf_deploy.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# ── Palette (kept small — v8ui owns most color; we only need footer text
# and status dot defaults here) ──────────────────────────────────────────────
COLORS = {
    "bg": [0.055, 0.055, 0.055, 1.0],
    "text": [0.878, 0.878, 0.878, 1.0],
    "dim": [0.533, 0.533, 0.533, 1.0],
    "status_bg": [0.118, 0.118, 0.137, 1.0],  # #1E1E23 matches v8ui panel
    "dot_grey": [0.333, 0.333, 0.333, 1.0],  # #555555 — empty/waiting default
}


# ── Stable object IDs ─────────────────────────────────────────────────────────
# Keep these stable so patchlines are readable and diffs small.

OBJ_V8UI = "obj-sf-ui"

OBJ_SF_STATE = "obj-sf-state"
OBJ_SF_FORGE = "obj-sf-forge"
OBJ_SF_PRESET_LOADER = "obj-sf-preset-loader"
OBJ_SF_MANIFEST_LOADER = "obj-sf-manifest-loader"
OBJ_SF_SETTINGS = "obj-sf-settings"
OBJ_SF_LOGGER = "obj-sf-logger"
OBJ_SF_NDJSON_PARSER = "obj-sf-ndjson-parser"
OBJ_SF_LOM_LOADER = "obj-sf-lom-loader"
OBJ_SF_CLIP_EXPORT = "obj-sf-clip-export"
OBJ_SF_LOCATOR_ANCHOR = "obj-sf-locator-anchor"

OBJ_DICT_STATE = "obj-dict-sf-state"
OBJ_DICT_PRESET = "obj-dict-sf-preset"
OBJ_DICT_MANIFEST = "obj-dict-sf-manifest"
OBJ_DICT_SETTINGS = "obj-dict-sf-settings"

# Configurator v1 §3.1 picker UI — new live.text widgets that replace the
# legacy umenus + v8ui-click route table. The v8ui still draws background
# pixels but is no longer the source of truth for user clicks; that role
# moves to these native widgets in presentation mode.
OBJ_PICK_SOURCE_BTN = "obj-sf-pick-source-btn"
OBJ_PICK_SOURCE_MSG = "obj-sf-pick-source-msg"
OBJ_STATUS_RECV = "obj-sf-status-recv"

OBJ_PRIMARY_BTN = "obj-sf-primary-btn"
OBJ_PRIMARY_MSG = "obj-sf-primary-msg"
OBJ_PRIMARY_LABEL_RECV = "obj-sf-primary-label-recv"
OBJ_PRIMARY_LABEL_PREPEND = "obj-sf-primary-label-prepend"
OBJ_PRIMARY_ENABLED_RECV = "obj-sf-primary-enabled-recv"
OBJ_PRIMARY_ENABLED_PREPEND = "obj-sf-primary-enabled-prepend"

OBJ_COMMIT_BTN = "obj-sf-commit-btn"
OBJ_COMMIT_MSG = "obj-sf-commit-msg"
OBJ_BOUNCE_BTN = "obj-sf-bounce-btn"
OBJ_BOUNCE_MSG = "obj-sf-bounce-msg"
OBJ_EXPORT_BTN = "obj-sf-export-btn"
OBJ_EXPORT_MSG = "obj-sf-export-msg"
OBJ_ANCHOR_BTN = "obj-sf-anchor-btn"
OBJ_ANCHOR_MSG = "obj-sf-anchor-msg"
# Anchor wire — JS reAnchor() fires messnamed("sf-anchor-go", forgeDir);
# the patcher routes that into [js sf_locator_anchor].anchor(forgeDir).
OBJ_ANCHOR_GO_RECV = "obj-sf-anchor-go-recv"
OBJ_ANCHOR_GO_PREPEND = "obj-sf-anchor-go-prepend"

# Picker dialog (driven by sf-open-source-dialog messnamed from js.pickSource).
OBJ_PICKER_DIALOG_RECV = "obj-sf-picker-dialog-recv"
OBJ_PICKER_DIALOG = "obj-sf-picker-dialog"
OBJ_PICKER_DIALOG_REGEX = "obj-sf-picker-dialog-regex"
OBJ_PICKER_DIALOG_PREPEND = "obj-sf-picker-dialog-prepend"

OBJ_ROUTE_NDJSON = "obj-route-ndjson"

# HW-4 (sf_remote): UDP receivers + dispatcher route. 7420 = general bus,
# 7421 = direct dump-dict bus into sf_state_mgr. See docs/remote_debug.md.
OBJ_UDP_GENERAL = "obj-udp-general"
OBJ_UDP_DUMP = "obj-udp-dump"
OBJ_ROUTE_UDP = "obj-route-udp"

OBJ_SHELL = "obj-shell"

OBJ_STATUS_DOT = "obj-sf-status-dot"
OBJ_STATUS_TEXT = "obj-sf-status-text"
OBJ_VERSION_TEXT = "obj-sf-version-text"

# Phase 4B — footer-left "Open Editor" button (replaces ConfiguratorStrip.amxd).
# textbutton → [t b] → [message openEditor] → [js sf_lom_loader].
OBJ_OPEN_EDITOR_BTN = "obj-sf-open-editor-btn"
OBJ_OPEN_EDITOR_TB = "obj-sf-open-editor-tb"
OBJ_OPEN_EDITOR_MSG = "obj-sf-open-editor-msg"

OBJ_LOADBANG = "obj-loadbang"
OBJ_LOAD_DEFERLOW = "obj-load-deferlow"
OBJ_LOAD_SEQ = "obj-load-seq"
OBJ_LOAD_SCAN_PRESETS = "obj-load-scan-presets"
OBJ_LOAD_SCAN_MANIFESTS = "obj-load-scan-manifests"
OBJ_LOAD_SETTINGS = "obj-load-settings"

OBJ_PROGRESS_UNPACK = "obj-progress-unpack"
OBJ_ONPROG_PREPEND = "obj-onprog-prepend"
OBJ_ONSTEM_PREPEND = "obj-onstem-prepend"
OBJ_ONBPM_PREPEND = "obj-onbpm-prepend"
OBJ_ONCOMPLETE_PREPEND = "obj-oncomplete-prepend"
OBJ_ONCURATED_PREPEND = "obj-oncurated-prepend"
OBJ_ONERROR_PREPEND = "obj-onerror-prepend"

# Clip-export NDJSON event prepends (sf_clip_export message names).
OBJ_CX_STARTED_PREP = "obj-cx-started-prepend"
OBJ_CX_PROGRESS_PREP = "obj-cx-progress-prepend"
OBJ_CX_CLIP_DONE_PREP = "obj-cx-clip-done-prepend"
OBJ_CX_CLIP_ERROR_PREP = "obj-cx-clip-error-prepend"
OBJ_CX_COMPLETE_PREP = "obj-cx-complete-prepend"
OBJ_CX_ERROR_PREP = "obj-cx-error-prepend"

# Locator-anchor NDJSON event prepends (kept for [shell] → ndjson path even
# though the legacy ANCH button is gone; the JS module remains for UDP-driven
# re-anchor flows and future Lane wiring).
OBJ_LA_STARTED_PREP = "obj-la-started-prepend"
OBJ_LA_COMPLETE_PREP = "obj-la-complete-prepend"
OBJ_LA_ERROR_PREP = "obj-la-error-prepend"

OBJ_PLUGIN_IN = "obj-plugin-in"
OBJ_PLUGOUT = "obj-plugout"

OBJ_FILELOG_PREPEND = "obj-filelog-prepend"

# Phase 3B C2 — Device → Server HTTP wire ([maxurl] dictionary form).
# JS populates per-verb request Dicts (`sf_http_req_<verb_underscored>`) then
# fires `messnamed(verb, url, jsonText)`. The receivers below ignore the
# inlet atoms and re-fire the already-populated dict by name into a shared
# [maxurl 4]. The response side routes [maxurl]'s `dictionary <name>` output
# back into [js] via `[prepend onHttpResponse]`.
OBJ_HTTP_MAXURL = "obj-sf-http-maxurl"
OBJ_HTTP_COMMIT_RECV = "obj-sf-http-commit-recv"
OBJ_HTTP_COMMIT_MSG = "obj-sf-http-commit-msg"
OBJ_HTTP_BOUNCE_PROG_RECV = "obj-sf-http-bounce-progress-recv"
OBJ_HTTP_BOUNCE_PROG_MSG = "obj-sf-http-bounce-progress-msg"
OBJ_HTTP_BOUNCE_COMP_RECV = "obj-sf-http-bounce-complete-recv"
OBJ_HTTP_BOUNCE_COMP_MSG = "obj-sf-http-bounce-complete-msg"
OBJ_HTTP_RESP_ROUTE = "obj-sf-http-resp-route"
OBJ_HTTP_RESP_PREPEND = "obj-sf-http-resp-prepend"

# Dict-name conventions — MUST match `_httpRequestDictNameFor()` in
# stemforge_loader.v0.js. Hyphens in verb names become underscores.
HTTP_REQ_DICT_COMMIT = "sf_http_req_sf_commit_send"
HTTP_REQ_DICT_BOUNCE_PROG = "sf_http_req_sf_bounce_progress"
HTTP_REQ_DICT_BOUNCE_COMP = "sf_http_req_sf_bounce_complete"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _box(
    obj_id: str,
    maxclass: str,
    patching_rect: tuple[float, float, float, float],
    *,
    presentation: bool = False,
    presentation_rect: tuple[float, float, float, float] | None = None,
    numinlets: int = 1,
    numoutlets: int = 0,
    outlettype: list[str] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": obj_id,
        "maxclass": maxclass,
        "numinlets": numinlets,
        "numoutlets": numoutlets,
        "patching_rect": list(patching_rect),
    }
    if outlettype is not None:
        body["outlettype"] = outlettype
    if presentation:
        body["presentation"] = 1
        body["presentation_rect"] = list(presentation_rect or patching_rect)
    if extras:
        body.update(extras)
    return {"box": body}


def _line(src_id: str, src_outlet: int, dst_id: str, dst_inlet: int) -> dict[str, Any]:
    return {
        "patchline": {
            "source": [src_id, src_outlet],
            "destination": [dst_id, dst_inlet],
        }
    }


def _js_box(
    obj_id: str,
    filename: str,
    patching_rect: tuple[float, float, float, float],
    *,
    scripting_name: str | None = None,
    numinlets: int = 1,
    numoutlets: int = 1,
    outlettype: list[str] | None = None,
) -> dict[str, Any]:
    """Classic [js] object (SpiderMonkey engine). NOT in presentation.

    @numoutlets MUST appear in the text. Max defaults a fresh [js] box to
    outlets=1 and only honors the JS file's `outlets = N` declaration AFTER
    the script has finished evaluating. During that interval Max walks the
    saved patcher cords and deletes any whose source-outlet index >= 1 as
    "patchcord outlet out of range". The box-level numoutlets field is NOT
    enough for [js] — Max ignores it in favor of the text-arg attribute.
    Setting @numoutlets in the text guarantees the box has the right shape
    before cord-restoration runs.
    """
    text = f"js {filename}"
    if scripting_name:
        text += f" @scripting_name {scripting_name}"
    text += f" @numinlets {numinlets} @numoutlets {numoutlets}"
    if outlettype is None:
        outlettype = [""] * numoutlets
    return _box(
        obj_id,
        "newobj",
        patching_rect,
        numinlets=numinlets,
        numoutlets=numoutlets,
        outlettype=outlettype,
        extras={
            "text": text,
            "saved_object_attributes": {
                "filename": filename,
                "parameter_enable": 0,
            },
        },
    )


# ── Core builder ──────────────────────────────────────────────────────────────


def build_patcher(device_yaml_path: str | Path) -> dict[str, Any]:
    """Load device.yaml and return a Max patcher dict."""
    with open(device_yaml_path) as f:
        spec = yaml.safe_load(f)

    ui = spec["ui"]
    size = ui["size"]
    device_name = spec["device"]["name"]
    device_version = spec["device"].get("version", "0.1.0")

    v8ui_cfg = ui["v8ui"]
    status_bar = ui["status_bar"]

    boxes: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []

    # ── v8ui canvas (background-only in Configurator v1) ─────────────────────
    # The v8ui still receives `refresh` from sf_state so its in-script draw
    # hooks keep firing (legacy debug surface), but it is OUT of presentation
    # mode in v0.0.3: the spec §3.1 picker + verb buttons are the only
    # presentation-mode widgets the user sees. The v8ui's outlet-0 click
    # events are no longer routed anywhere — clicks happen on the native
    # widgets that sit (in presentation) where the canvas used to be.
    #
    # We keep the v8ui object in patching mode so:
    #   - sf_state's `refresh` wire still has a destination,
    #   - in-Max debug sessions can still poke the canvas via the patching
    #     view if needed for inspection.

    v8ui_rect = (
        v8ui_cfg["pos"]["x"],
        v8ui_cfg["pos"]["y"],
        v8ui_cfg["size"]["width"],
        v8ui_cfg["size"]["height"],
    )
    boxes.append(
        _box(
            OBJ_V8UI,
            "v8ui",
            v8ui_rect,
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={
                "filename": v8ui_cfg["filename"],
                "varname": v8ui_cfg["id"],
                "saved_object_attributes": {
                    "filename": v8ui_cfg["filename"],
                    "parameter_enable": 0,
                },
            },
        )
    )

    # ── Presentation: bottom status bar (native widgets) ────────────────────

    dot_cfg = status_bar["status_dot"]
    dot_rect = (
        dot_cfg["pos"]["x"],
        dot_cfg["pos"]["y"],
        dot_cfg["size"]["width"],
        dot_cfg["size"]["height"],
    )
    boxes.append(
        _box(
            OBJ_STATUS_DOT,
            "live.text",
            dot_rect,
            presentation=True,
            presentation_rect=dot_rect,
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
            extras={
                "varname": dot_cfg["id"],
                "mode": 0,  # display-only button
                "text": "",
                "activebgcolor": COLORS["dot_grey"],
                "bgcolor": COLORS["dot_grey"],
                "activebgoncolor": COLORS["dot_grey"],
                "bgoncolor": COLORS["dot_grey"],
                "bordercolor": COLORS["dot_grey"],
                "activebordercolor": COLORS["dot_grey"],
                "activebordercoloroff": COLORS["dot_grey"],
                "rounded": 24.0,
                "fontsize": 1.0,
                "parameter_enable": 0,
            },
        )
    )

    txt_cfg = status_bar["status_text"]
    txt_rect = (
        txt_cfg["pos"]["x"],
        txt_cfg["pos"]["y"],
        txt_cfg["size"]["width"],
        txt_cfg["size"]["height"],
    )
    boxes.append(
        _box(
            OBJ_STATUS_TEXT,
            "live.comment",
            txt_rect,
            presentation=True,
            presentation_rect=txt_rect,
            numinlets=1,
            numoutlets=0,
            extras={
                "varname": txt_cfg["id"],
                "text": "waiting — pick a source",
                "fontsize": 9.0,
                "textcolor": COLORS["dim"],
                # Display-only — opt out of M4L parameter enrollment so Live's
                # host doesn't probe a missing saved_attribute_attributes table
                # at device load (each unprobed live.* widget emits one
                # `SendMessage error 2: Bad parameter value` at startup).
                "parameter_enable": 0,
            },
        )
    )

    ver_cfg = status_bar["version_text"]
    ver_rect = (
        ver_cfg["pos"]["x"],
        ver_cfg["pos"]["y"],
        ver_cfg["size"]["width"],
        ver_cfg["size"]["height"],
    )
    boxes.append(
        _box(
            OBJ_VERSION_TEXT,
            "live.comment",
            ver_rect,
            presentation=True,
            presentation_rect=ver_rect,
            numinlets=1,
            numoutlets=0,
            extras={
                "varname": ver_cfg["id"],
                "text": f"v{device_version}",
                "fontsize": 9.0,
                "textcolor": COLORS["dim"],
                # Display-only — opt out of M4L parameter enrollment. See
                # status_text comment above for the SendMessage-at-boot rationale.
                "parameter_enable": 0,
            },
        )
    )

    # ── Phase 4B — "Open Editor" footer button ─────────────────────────────
    # Single live.text button (mode 1 = momentary) at the right edge of the
    # footer, just inside the version stamp. On click → [t b] →
    # [message openEditor] → [js sf_lom_loader].openEditor(), which asks
    # Max to `launchbrowser` the popup URL.
    #
    # Position: in the footer gap between status_text (ends ~x=314) and
    # version_text (starts at x=422 per the slimmed device.yaml).
    btn_x = 322.0
    btn_y = status_bar["status_dot"]["pos"]["y"]
    btn_w = 92.0
    btn_h = status_bar["status_dot"]["size"]["height"]
    open_editor_rect = (btn_x, btn_y, btn_w, btn_h)
    boxes.append(
        _box(
            OBJ_OPEN_EDITOR_BTN,
            "live.text",
            open_editor_rect,
            presentation=True,
            presentation_rect=open_editor_rect,
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
            extras={
                "varname": "sf_open_editor_btn",
                # mode 1 = momentary button (emits its `text` label on click).
                # The downstream [t b] converts the label-symbol into a bang,
                # then the [message openEditor] names the JS handler (pitfall
                # #17 in memory/m4l_device_development_guide.md).
                "mode": 1,
                "text": "Open Editor",
                "fontname": "Ableton Sans Medium",
                "fontsize": 9.0,
                "textcolor": COLORS["text"],
                "activebgcolor": COLORS["dim"],
                "bgcolor": COLORS["status_bg"],
                "activebgoncolor": COLORS["dim"],
                "bgoncolor": COLORS["status_bg"],
                "bordercolor": COLORS["dim"],
                "activebordercolor": COLORS["text"],
                "activebordercoloroff": COLORS["dim"],
                "rounded": 4.0,
                "parameter_enable": 0,
            },
        )
    )
    # [t b] — converts the button's label-symbol output into a bang.
    boxes.append(
        _box(
            OBJ_OPEN_EDITOR_TB,
            "newobj",
            (btn_x, btn_y + 18.0, 40.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["bang"],
            extras={"text": "t b"},
        )
    )
    # Message box names the JS handler — bang fires it, then [js sf_lom_loader]
    # resolves the message-name to `openEditor()`.
    boxes.append(
        _box(
            OBJ_OPEN_EDITOR_MSG,
            "message",
            (btn_x, btn_y + 42.0, 96.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "openEditor"},
        )
    )

    # ── Dict objects (one per canonical dict name) ──────────────────────────
    # These just ensure the dicts exist on patcher load so JS Dict() refs work.

    dict_row_y = 200.0  # out of presentation mode; patcher-area only
    dict_width = 150.0
    for i, (box_id, dict_name) in enumerate(
        [
            (OBJ_DICT_STATE, "sf_state"),
            (OBJ_DICT_PRESET, "sf_preset"),
            (OBJ_DICT_MANIFEST, "sf_manifest"),
            (OBJ_DICT_SETTINGS, "sf_settings"),
        ]
    ):
        boxes.append(
            _box(
                box_id,
                "newobj",
                (16.0 + i * (dict_width + 8), dict_row_y, dict_width, 22.0),
                numinlets=2,
                numoutlets=4,
                outlettype=["dictionary", "", "", ""],
                extras={"text": f"dict {dict_name}"},
            )
        )

    # ── Logic-layer JS objects (classic [js], out of presentation) ──────────
    # Placed on a grid below the dicts so a human opening patching-mode can
    # see them.  The coordinates don't matter for runtime.

    js_row_y = 250.0
    js_w = 210.0
    js_gap = 12.0

    # sf_state (state manager)
    boxes.append(
        _js_box(
            OBJ_SF_STATE,
            "sf_state.js",
            (16.0, js_row_y, js_w, 22.0),
            scripting_name="sf_state_mgr",
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
        )
    )

    # sf_forge (orchestrator)
    boxes.append(
        _js_box(
            OBJ_SF_FORGE,
            "sf_forge.js",
            (16.0 + (js_w + js_gap), js_row_y, js_w, 22.0),
            scripting_name="sf_forge_mgr",
            numinlets=1,
            numoutlets=3,
            outlettype=["", "", ""],
        )
    )

    # sf_preset_loader
    boxes.append(
        _js_box(
            OBJ_SF_PRESET_LOADER,
            "sf_preset_loader.js",
            (16.0 + 2 * (js_w + js_gap), js_row_y, js_w, 22.0),
            scripting_name="sf_preset_loader",
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
        )
    )

    # sf_manifest_loader
    boxes.append(
        _js_box(
            OBJ_SF_MANIFEST_LOADER,
            "sf_manifest_loader.js",
            (16.0 + 3 * (js_w + js_gap), js_row_y, js_w, 22.0),
            scripting_name="sf_manifest_loader",
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
        )
    )

    # sf_settings
    boxes.append(
        _js_box(
            OBJ_SF_SETTINGS,
            "sf_settings.js",
            (16.0, js_row_y + 34, js_w, 22.0),
            scripting_name="sf_settings_mgr",
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
        )
    )

    # sf_logger (sink — no outlets)
    boxes.append(
        _js_box(
            OBJ_SF_LOGGER,
            "sf_logger.js",
            (16.0 + (js_w + js_gap), js_row_y + 34, js_w, 22.0),
            scripting_name="sf_logger",
            numinlets=1,
            numoutlets=0,
            outlettype=[],
        )
    )

    # stemforge_ndjson_parser (kept for phase-1 NDJSON from [shell])
    boxes.append(
        _js_box(
            OBJ_SF_NDJSON_PARSER,
            "stemforge_ndjson_parser.v0.js",
            (16.0 + 2 * (js_w + js_gap), js_row_y + 34, js_w, 22.0),
            scripting_name="sf_ndjson_parser",
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
        )
    )

    # stemforge_loader (kept for LOM Phase 2)
    boxes.append(
        _js_box(
            OBJ_SF_LOM_LOADER,
            "stemforge_loader.v0.js",
            (16.0 + 3 * (js_w + js_gap), js_row_y + 34, js_w, 22.0),
            scripting_name="sf_lom_loader",
            numinlets=1,
            numoutlets=4,
            outlettype=["", "", "", ""],
        )
    )

    # sf_clip_export — bounce A/B/C/D clip slots → sidecars (driven by the
    # BOUNCE button in sf_ui's right column). Outlet 0 = status, outlet 1 =
    # [shell] spawn commands for tools/m4l_export_clips.py.
    boxes.append(
        _js_box(
            OBJ_SF_CLIP_EXPORT,
            "sf_clip_export.js",
            (16.0, js_row_y + 68, js_w, 22.0),
            scripting_name="sf_clip_export",
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
        )
    )

    # sf_locator_anchor — re-anchor a forged track to a user-placed Ableton
    # locator. Driven by the ANCH button in sf_ui's right column.
    #   outlet 0 = status
    #   outlet 1 = [shell] spawn commands for tools/m4l_locator_anchor.py
    #   outlet 2 = manifest path → loadArrangementFromManifest in sf_lom_loader
    #              (re-paints clips on the arrangement view after re-anchor)
    boxes.append(
        _js_box(
            OBJ_SF_LOCATOR_ANCHOR,
            "sf_locator_anchor.js",
            (16.0 + (js_w + js_gap), js_row_y + 102, js_w, 22.0),
            scripting_name="sf_locator_anchor",
            numinlets=1,
            numoutlets=3,
            outlettype=["", "", ""],
        )
    )

    # ── HW-4: sf_remote UDP bus ────────────────────────────────────────────
    # Two [udpreceive] boxes wire `tools/sf_remote.py` to the device for
    # headless debug. See `docs/remote_debug.md` for the protocol.
    #
    #   [udpreceive 7420] → [route state forge preset-loader manifest-loader
    #                        settings ui logger] → each module's inlet 0
    #     Generic message bus: `<target> <msg...>` where target is one of
    #     the route's tags; the rest of the atoms become the module's
    #     incoming Max message.
    #
    #   [udpreceive 7421] → sf_state_mgr inlet 0
    #     Direct dump-dict bus. Sender writes `dumpDict <name>` and
    #     sf_state.dumpDict() prints the dict's contents to the log file
    #     so a remote operator can inspect Max state without Max GUI.
    #
    # Both boxes sit far below the visible UI rectangle (y > 600) so they
    # don't clutter the patcher view in edit mode. They have no
    # presentation rect — invisible in the device's run-mode UI.
    udp_y = js_row_y + 360
    boxes.append(
        _box(
            OBJ_UDP_GENERAL,
            "newobj",
            (16.0, udp_y, 100.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "udpreceive 7420"},
        )
    )
    # The route order MUST stay in sync with sf_remote's `fire <target>`
    # documentation in tools/sf_remote.py and docs/remote_debug.md.
    #
    # Phase 3A added `/template-changed` for server→device hot-apply (the
    # configurator HTTP server's PATCH /curations/{name}/template fires this
    # datagram). Args: `<letter> <template-or-dash>`; routed into
    # sf_lom_loader's `templateChanged(letter, name)` via a [prepend].
    boxes.append(
        _box(
            OBJ_ROUTE_UDP,
            "newobj",
            (16.0, udp_y + 26, 600.0, 22.0),
            numinlets=1,
            numoutlets=9,  # 8 routed targets + 1 unmatched fallthrough
            outlettype=["", "", "", "", "", "", "", "", ""],
            extras={
                "text": (
                    # Match slash-prefixed OSC addresses. Verified empirically
                    # 2026-05-09 via /tmp/udp_probe: Max's `udpreceive` in OSC
                    # mode emits the address as a single symbol with leading
                    # slash preserved (NOT tokenized on `/`). So we match
                    # `/forge` not `forge`. sf_remote.py encodes accordingly.
                    "route /state /forge /preset-loader /manifest-loader "
                    "/settings /ui /logger /template-changed"
                ),
            },
        )
    )
    boxes.append(
        _box(
            OBJ_UDP_DUMP,
            "newobj",
            (550.0, udp_y, 100.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "udpreceive 7421"},
        )
    )

    # 7420 → route input
    lines.append(_line(OBJ_UDP_GENERAL, 0, OBJ_ROUTE_UDP, 0))
    # route outlets → modules. Outlet order matches the route's tag order.
    lines.append(_line(OBJ_ROUTE_UDP, 0, OBJ_SF_STATE, 0))  # state
    lines.append(_line(OBJ_ROUTE_UDP, 1, OBJ_SF_FORGE, 0))  # forge
    lines.append(_line(OBJ_ROUTE_UDP, 2, OBJ_SF_PRESET_LOADER, 0))  # preset-loader
    lines.append(_line(OBJ_ROUTE_UDP, 3, OBJ_SF_MANIFEST_LOADER, 0))  # manifest-loader
    lines.append(_line(OBJ_ROUTE_UDP, 4, OBJ_SF_SETTINGS, 0))  # settings
    lines.append(_line(OBJ_ROUTE_UDP, 5, OBJ_V8UI, 0))  # ui
    lines.append(_line(OBJ_ROUTE_UDP, 6, OBJ_SF_LOGGER, 0))  # logger
    # Phase 3A: outlet 7 = `/template-changed <letter> <name>`. Prepend the
    # message name `templateChanged` so the classic [js] loader dispatches
    # to its top-level `templateChanged(letter, name)` function (which then
    # calls `applyGroupTemplate` to hit the LOM `load_browser_item` verb).
    boxes.append(
        _box(
            "obj-prepend-template-changed",
            "newobj",
            (16.0, udp_y + 54, 200.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend templateChanged"},
        )
    )
    lines.append(_line(OBJ_ROUTE_UDP, 7, "obj-prepend-template-changed", 0))
    lines.append(_line("obj-prepend-template-changed", 0, OBJ_SF_LOM_LOADER, 0))
    # Outlet 8 is the unmatched fallthrough — intentionally unwired.

    # 7421 → sf_state_mgr (direct, dumpDict only)
    lines.append(_line(OBJ_UDP_DUMP, 0, OBJ_SF_STATE, 0))

    # ── Configurator v1 §3.1 picker + verb buttons (live.text widgets) ───────
    #
    # Layout in presentation mode (single 820×149 canvas, status bar excluded):
    #
    #     LEFT column (x=8..718)            RIGHT column (x=720..812)
    #     ┌─────────────────────────────┐   ┌──────────────────────┐
    #     │ y=8..40   [Pick source…]    │   │ y=8..52   PRIMARY     │
    #     │ y=48..76  status text       │   │ y=58..82  COMMIT      │
    #     │            (status text)    │   │ y=86..110 BOUNCE      │
    #     │ y=84..112  (reserved area)  │   │ y=114..138 EXPORT     │
    #     └─────────────────────────────┘   └──────────────────────┘
    #
    # All widgets are live.text @parameter_enable 0 so M4L's host doesn't
    # probe them. Click-buttons use mode 1 (momentary); the click emits
    # the widget's `text` symbol, which the downstream [t b] converts to
    # a bang, and a [message <verb>] box names the JS handler that
    # stemforge_loader.v0.js resolves on its [js] inlet.

    # Picker geometry — slim layout for the 480px canvas (was 820 with a
    # 700-wide status box covering most of the body). Two rows:
    #
    #   row 1 (y=8-44):  [ Pick source (256w) ][gap][ Primary (200w) ]
    #   row 2 (y=52-80): [ COMMIT | BOUNCE | EXPORT | ANCH ] each ~113w
    #
    # Status feedback now lives entirely in the footer's `sf_status_text`
    # live.comment (driven by [r sf-status]), so the body's old big status
    # surface is gone.
    LEFT_X = 8.0
    LEFT_W = 256.0  # Pick source button width.
    RIGHT_X = 272.0  # Primary button x (after Pick source + 8px gap).
    RIGHT_W = 200.0
    VERB_W = 113.0  # Each of the 4 verb buttons. 4*113 + 3*3 = 461 < 480.
    VERB_GAP = 3.0
    VERB_Y = 52.0
    VERB_H = 28.0

    # ── Pick source button ──────────────────────────────────────────────
    pick_src_rect = (LEFT_X, 8.0, LEFT_W, 36.0)
    boxes.append(
        _box(
            OBJ_PICK_SOURCE_BTN,
            "live.text",
            pick_src_rect,
            presentation=True,
            presentation_rect=pick_src_rect,
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
            extras={
                "varname": "sf_pick_source_btn",
                # mode 1 = momentary button (emits the `text` label on click).
                "mode": 1,
                "text": "Pick source…",
                "fontname": "Ableton Sans Medium",
                "fontsize": 11.0,
                "textcolor": COLORS["text"],
                "activebgcolor": COLORS["dim"],
                "bgcolor": COLORS["status_bg"],
                "activebgoncolor": COLORS["dim"],
                "bgoncolor": COLORS["status_bg"],
                "bordercolor": COLORS["dim"],
                "activebordercolor": COLORS["text"],
                "activebordercoloroff": COLORS["dim"],
                "rounded": 4.0,
                "parameter_enable": 0,
            },
        )
    )
    # Click → [message pickSource] → js sf_lom_loader (calls pickSource()).
    boxes.append(
        _box(
            OBJ_PICK_SOURCE_MSG,
            "message",
            (LEFT_X, 44.0, 90.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "pickSource"},
        )
    )
    lines.append(_line(OBJ_PICK_SOURCE_BTN, 0, OBJ_PICK_SOURCE_MSG, 0))
    lines.append(_line(OBJ_PICK_SOURCE_MSG, 0, OBJ_SF_LOM_LOADER, 0))

    # ── Status receiver — feeds the footer's sf_status_text live.comment ──
    # The earlier 700px in-body status box was redundant with the slim
    # footer status: both displayed the same `set <text>` stream and the
    # body version covered most of the device. This wires [r sf-status]
    # straight to the footer widget (live.comment accepts `set <text>`
    # natively, so no prepend needed).
    boxes.append(
        _box(
            OBJ_STATUS_RECV,
            "newobj",
            (LEFT_X, 86.0, 100.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "r sf-status"},
        )
    )
    lines.append(_line(OBJ_STATUS_RECV, 0, OBJ_STATUS_TEXT, 0))

    # ── Primary button (right of Pick source, same row) ─────────────────
    # Label is driven by [r primary-btn-label] from the loader; active
    # state by [r primary-btn-enabled]. On click, [message primary] →
    # js sf_lom_loader (calls primary(), which dispatches by sniffer type).
    primary_rect = (RIGHT_X, 8.0, RIGHT_W, 36.0)
    boxes.append(
        _box(
            OBJ_PRIMARY_BTN,
            "live.text",
            primary_rect,
            presentation=True,
            presentation_rect=primary_rect,
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
            extras={
                "varname": "sf_primary_btn",
                "mode": 1,
                "text": "Pick a source…",
                "fontname": "Ableton Sans Medium",
                "fontsize": 10.0,
                "textcolor": COLORS["text"],
                "activebgcolor": COLORS["text"],
                "bgcolor": COLORS["status_bg"],
                "activebgoncolor": COLORS["text"],
                "bgoncolor": COLORS["status_bg"],
                "bordercolor": COLORS["dim"],
                "activebordercolor": COLORS["text"],
                "activebordercoloroff": COLORS["dim"],
                "rounded": 4.0,
                "parameter_enable": 0,
            },
        )
    )
    boxes.append(
        _box(
            OBJ_PRIMARY_MSG,
            "message",
            (RIGHT_X, 56.0, 90.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "primary"},
        )
    )
    lines.append(_line(OBJ_PRIMARY_BTN, 0, OBJ_PRIMARY_MSG, 0))
    lines.append(_line(OBJ_PRIMARY_MSG, 0, OBJ_SF_LOM_LOADER, 0))

    # [r primary-btn-label] → prepend set → primary button text setter.
    # The loader emits via messnamed("primary-btn-label", "<text>") whenever
    # the sniffer's primary-label-by-type dispatch changes; see
    # _emitPrimaryButtonState() in stemforge_loader.v0.js.
    boxes.append(
        _box(
            OBJ_PRIMARY_LABEL_RECV,
            "newobj",
            (RIGHT_X, 80.0, 140.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "r primary-btn-label"},
        )
    )
    boxes.append(
        _box(
            OBJ_PRIMARY_LABEL_PREPEND,
            "newobj",
            (RIGHT_X, 104.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            # `set <text>` is REJECTED by live.text in mode 1 (toggle button)
            # — Max emits "bad arguments for message set". The supported
            # way to update the displayed label on a live.text widget is
            # the `text <symbol>` message, which writes to the @text
            # attribute. Caught during second UAT round.
            extras={"text": "prepend text"},
        )
    )
    lines.append(_line(OBJ_PRIMARY_LABEL_RECV, 0, OBJ_PRIMARY_LABEL_PREPEND, 0))
    lines.append(_line(OBJ_PRIMARY_LABEL_PREPEND, 0, OBJ_PRIMARY_BTN, 0))

    # [r primary-btn-enabled] → prepend active → primary button.
    # live.text accepts `active 0|1` (mode 1 buttons) to enable/disable.
    boxes.append(
        _box(
            OBJ_PRIMARY_ENABLED_RECV,
            "newobj",
            (RIGHT_X + 150.0, 80.0, 160.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "r primary-btn-enabled"},
        )
    )
    boxes.append(
        _box(
            OBJ_PRIMARY_ENABLED_PREPEND,
            "newobj",
            (RIGHT_X + 150.0, 104.0, 100.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend active"},
        )
    )
    lines.append(_line(OBJ_PRIMARY_ENABLED_RECV, 0, OBJ_PRIMARY_ENABLED_PREPEND, 0))
    lines.append(_line(OBJ_PRIMARY_ENABLED_PREPEND, 0, OBJ_PRIMARY_BTN, 0))

    # ── Verb buttons row — COMMIT / BOUNCE / EXPORT / ANCH ───────────────
    # Each is a live.text mode 1 → [message <verb>] → [js sf_lom_loader].
    # The loader's `commit()`, `bounceCuration()`, `exportArrangementSnapshot()`,
    # `reAnchor()` functions are the targets; the message-name matching that
    # Max performs on classic [js] objects resolves them by top-level
    # function lookup. Row spans the device width below the Pick source +
    # Primary row.
    verb_y = VERB_Y
    _VERB_BTNS = [
        # (button_obj_id, message_obj_id, varname, label, message_text, x_offset_idx)
        (OBJ_COMMIT_BTN, OBJ_COMMIT_MSG, "sf_commit_btn", "COMMIT", "commit", 0),
        (
            OBJ_BOUNCE_BTN,
            OBJ_BOUNCE_MSG,
            "sf_bounce_btn",
            "BOUNCE",
            "bounceCuration",
            1,
        ),
        (
            OBJ_EXPORT_BTN,
            OBJ_EXPORT_MSG,
            "sf_export_btn",
            "EXPORT",
            "exportArrangementSnapshot ~/Desktop/snapshot.json",
            2,
        ),
        # ANCH — re-anchor the bar grid of the currently-picked forge. The
        # button fires `reAnchor` on the loader, which resolves the forge
        # dir from the last-picked source and emits messnamed("sf-anchor-go",
        # <dir>) for the patcher to route into sf_locator_anchor.anchor(dir).
        # The previous v8ui-canvas ANCH button got dropped by 999ee1d's
        # right-column refactor; this restores the in-presentation entry
        # point without bringing back the canvas surface.
        (OBJ_ANCHOR_BTN, OBJ_ANCHOR_MSG, "sf_anchor_btn", "ANCH", "reAnchor", 3),
    ]
    for btn_id, msg_id, varname, label, msg_text, idx in _VERB_BTNS:
        btn_x = LEFT_X + idx * (VERB_W + VERB_GAP)
        btn_rect = (btn_x, verb_y, VERB_W, VERB_H)
        boxes.append(
            _box(
                btn_id,
                "live.text",
                btn_rect,
                presentation=True,
                presentation_rect=btn_rect,
                numinlets=1,
                numoutlets=2,
                outlettype=["", ""],
                extras={
                    "varname": varname,
                    "mode": 1,
                    "text": label,
                    "fontname": "Ableton Sans Medium",
                    "fontsize": 10.0,
                    "textcolor": COLORS["text"],
                    "activebgcolor": COLORS["dim"],
                    "bgcolor": COLORS["status_bg"],
                    "activebgoncolor": COLORS["dim"],
                    "bgoncolor": COLORS["status_bg"],
                    "bordercolor": COLORS["dim"],
                    "activebordercolor": COLORS["text"],
                    "activebordercoloroff": COLORS["dim"],
                    "rounded": 4.0,
                    "parameter_enable": 0,
                },
            )
        )
        boxes.append(
            _box(
                msg_id,
                "message",
                (btn_x, verb_y + 26.0, max(VERB_W, 60.0) + 200.0, 22.0),
                numinlets=2,
                numoutlets=1,
                outlettype=[""],
                extras={"text": msg_text},
            )
        )
        lines.append(_line(btn_id, 0, msg_id, 0))
        lines.append(_line(msg_id, 0, OBJ_SF_LOM_LOADER, 0))

    # ── Picker dialog (driven by sf-open-source-dialog from js.pickSource) ───
    # The loader's pickSource() fires messnamed("sf-open-source-dialog","bang"),
    # which this [r] receives. We then bang the [opendialog], regex-strip the
    # HFS prefix, prepend `applyPickedSource`, and feed it back into the JS
    # so the sniffer can run and the primary button's label/enabled state
    # gets updated via [r primary-btn-label] / [r primary-btn-enabled].
    boxes.append(
        _box(
            OBJ_PICKER_DIALOG_RECV,
            "newobj",
            (LEFT_X, 110.0, 200.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "r sf-open-source-dialog"},
        )
    )
    boxes.append(
        _box(
            OBJ_PICKER_DIALOG,
            "newobj",
            (LEFT_X + 210.0, 110.0, 120.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["", "bang"],
            # opendialog with no args accepts every file type — picker UX
            # owns the user-side filtering (audio + .json + .yaml).
            extras={"text": "opendialog"},
        )
    )
    lines.append(_line(OBJ_PICKER_DIALOG_RECV, 0, OBJ_PICKER_DIALOG, 0))
    # opendialog → [prepend applyPickedSource] → js sf_lom_loader.
    #
    # Note: the previous design routed opendialog through a [regexp] that
    # stripped a Macintosh-HFS volume prefix (e.g. "Macintosh HD:/Users/...")
    # before prepending. That regex never matched on POSIX-emitting Live
    # builds and was a load-time race surface — Max instantiated [regexp]
    # with 5 outlets declared in JSON vs. the dynamic outlet count [regexp]
    # actually exposes given a single pattern, and on some Live versions the
    # mismatch fired "patchcord outlet out of range" during cord
    # restoration. The fix is to skip the regex entirely; the loader's
    # applyPickedSource() handles HFS→POSIX conversion in JS where it can be
    # unit-tested and isn't subject to Max-engine quirks.
    boxes.append(
        _box(
            OBJ_PICKER_DIALOG_PREPEND,
            "newobj",
            (LEFT_X + 590.0, 110.0, 200.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend applyPickedSource"},
        )
    )
    # opendialog → prepend → loader (regex box removed — see comment above).
    lines.append(_line(OBJ_PICKER_DIALOG, 0, OBJ_PICKER_DIALOG_PREPEND, 0))
    lines.append(_line(OBJ_PICKER_DIALOG_PREPEND, 0, OBJ_SF_LOM_LOADER, 0))

    # sf_lom_loader outlet 0 = status (loader's status() emits via
    # outlet(0, "set", "<text>")). Bridge it to [s sf-status] so the
    # picker's status-text live.text — driven off [r sf-status] —
    # receives the loader's status emissions.
    OBJ_STATUS_SEND = "obj-sf-status-send"
    boxes.append(
        _box(
            OBJ_STATUS_SEND,
            "newobj",
            (LEFT_X + 110.0, 78.0, 100.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "s sf-status"},
        )
    )
    lines.append(_line(OBJ_SF_LOM_LOADER, 0, OBJ_STATUS_SEND, 0))

    # sf_clip_export outlet 0 = status (currently logged inside the JS only;
    # could be wired to status text later). Outlet 1 = [shell] spawn commands
    # for the Python helper. Goes to the SAME shell sf_forge feeds.
    lines.append(_line(OBJ_SF_CLIP_EXPORT, 1, OBJ_SHELL, 0))
    # sf_locator_anchor outlet 1 also feeds [shell] (PYTHON_BIN + helper.py
    # + arg pairs). Outlet 0 is status, currently logged inside the JS only.
    lines.append(_line(OBJ_SF_LOCATOR_ANCHOR, 1, OBJ_SHELL, 0))
    # sf_locator_anchor outlet 2 → prepend loadArrangementFromManifest →
    # sf_lom_loader. Triggers a clip-grid refresh after a successful re-anchor.
    OBJ_LA_RELOAD_PREP = "obj-la-reload-prepend"
    boxes.append(
        _box(
            OBJ_LA_RELOAD_PREP,
            "newobj",
            (410.0 + 9 * 110, js_row_y + 16, 230.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend loadArrangementFromManifest"},
        )
    )
    lines.append(_line(OBJ_SF_LOCATOR_ANCHOR, 2, OBJ_LA_RELOAD_PREP, 0))
    lines.append(_line(OBJ_LA_RELOAD_PREP, 0, OBJ_SF_LOM_LOADER, 0))

    # ── ANCH button receive-side: route the loader's resolved forge dir into
    # sf_locator_anchor.anchor(dir). The button itself fires `reAnchor` on
    # the loader (declared in _VERB_BTNS); the loader then emits
    # `messnamed("sf-anchor-go", forgeDir)`. Here we receive that, prepend
    # the message-name `anchor`, and feed [js sf_locator_anchor] so classic
    # Max [js] dispatches to `anchor(forgeDir)`.
    boxes.append(
        _box(
            OBJ_ANCHOR_GO_RECV,
            "newobj",
            (LEFT_X, 140.0, 180.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "r sf-anchor-go"},
        )
    )
    boxes.append(
        _box(
            OBJ_ANCHOR_GO_PREPEND,
            "newobj",
            (LEFT_X + 200.0, 140.0, 120.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend anchor"},
        )
    )
    lines.append(_line(OBJ_ANCHOR_GO_RECV, 0, OBJ_ANCHOR_GO_PREPEND, 0))
    lines.append(_line(OBJ_ANCHOR_GO_PREPEND, 0, OBJ_SF_LOCATOR_ANCHOR, 0))

    # ── Phase 4B — Open Editor button wiring ─────────────────────────────
    # [live.text Open Editor] (mode 1) → [t b] → [message openEditor]
    #     → [js sf_lom_loader] (resolves the message-name to openEditor()).
    lines.append(_line(OBJ_OPEN_EDITOR_BTN, 0, OBJ_OPEN_EDITOR_TB, 0))
    lines.append(_line(OBJ_OPEN_EDITOR_TB, 0, OBJ_OPEN_EDITOR_MSG, 0))
    lines.append(_line(OBJ_OPEN_EDITOR_MSG, 0, OBJ_SF_LOM_LOADER, 0))

    # ── Phase 3B C2 — Device → Server HTTP wire ─────────────────────────────
    # Three `[r sf-…]` receivers feed a shared `[maxurl 4]` via the
    # dictionary input form. The JS loader populates the per-verb request
    # dict before firing the messnamed verb (see `_sendHttpPost` in
    # stemforge_loader.v0.js), so each receiver just re-fires the matching
    # dict name into maxurl. Response side: maxurl outlet 0 emits
    # `dictionary <response_name>`, routed back into [js] via
    # `[prepend onHttpResponse]` — JS reads status_code and calls
    # commitAck() on a 2xx for the commit response dict.
    http_x = LEFT_X
    http_y = 240.0
    http_row_h = 26.0

    # Receivers (3) — left column.
    boxes.append(
        _box(
            OBJ_HTTP_COMMIT_RECV,
            "newobj",
            (http_x, http_y, 160.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "r sf-commit-send"},
        )
    )
    boxes.append(
        _box(
            OBJ_HTTP_BOUNCE_PROG_RECV,
            "newobj",
            (http_x, http_y + http_row_h, 180.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "r sf-bounce-progress"},
        )
    )
    boxes.append(
        _box(
            OBJ_HTTP_BOUNCE_COMP_RECV,
            "newobj",
            (http_x, http_y + 2 * http_row_h, 180.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "r sf-bounce-complete"},
        )
    )

    # Dict-name message boxes (3) — middle column. Each emits the literal
    # `dictionary <req_dict_name>` message that [maxurl] interprets as
    # "execute the request described by this dict". The bang from each
    # [r] re-fires the message so already-populated dict contents go out.
    msg_x = http_x + 200.0
    boxes.append(
        _box(
            OBJ_HTTP_COMMIT_MSG,
            "message",
            (msg_x, http_y, 280.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": f"dictionary {HTTP_REQ_DICT_COMMIT}"},
        )
    )
    boxes.append(
        _box(
            OBJ_HTTP_BOUNCE_PROG_MSG,
            "message",
            (msg_x, http_y + http_row_h, 280.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": f"dictionary {HTTP_REQ_DICT_BOUNCE_PROG}"},
        )
    )
    boxes.append(
        _box(
            OBJ_HTTP_BOUNCE_COMP_MSG,
            "message",
            (msg_x, http_y + 2 * http_row_h, 280.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": f"dictionary {HTTP_REQ_DICT_BOUNCE_COMP}"},
        )
    )

    # [maxurl 4] — shared object, thread-count=4 so bounce-progress beacons
    # don't stack behind a slow commit. verbosity 0 = silent on Max Console.
    maxurl_x = msg_x + 300.0
    boxes.append(
        _box(
            OBJ_HTTP_MAXURL,
            "newobj",
            (maxurl_x, http_y, 140.0, 22.0),
            numinlets=2,
            numoutlets=2,
            outlettype=["", "list"],
            extras={"text": "maxurl 4 @verbosity 0"},
        )
    )

    # Request side: r → msg → maxurl.
    lines.append(_line(OBJ_HTTP_COMMIT_RECV, 0, OBJ_HTTP_COMMIT_MSG, 0))
    lines.append(_line(OBJ_HTTP_BOUNCE_PROG_RECV, 0, OBJ_HTTP_BOUNCE_PROG_MSG, 0))
    lines.append(_line(OBJ_HTTP_BOUNCE_COMP_RECV, 0, OBJ_HTTP_BOUNCE_COMP_MSG, 0))
    lines.append(_line(OBJ_HTTP_COMMIT_MSG, 0, OBJ_HTTP_MAXURL, 0))
    lines.append(_line(OBJ_HTTP_BOUNCE_PROG_MSG, 0, OBJ_HTTP_MAXURL, 0))
    lines.append(_line(OBJ_HTTP_BOUNCE_COMP_MSG, 0, OBJ_HTTP_MAXURL, 0))

    # Response side: maxurl outlet 0 emits `dictionary <response_dict_name>`.
    # [route dictionary] strips the leading "dictionary" symbol; its outlet
    # 0 carries the response dict name. We prepend "onHttpResponse" so
    # classic [js] dispatches to the loader's response handler.
    boxes.append(
        _box(
            OBJ_HTTP_RESP_ROUTE,
            "newobj",
            (maxurl_x, http_y + http_row_h, 140.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
            extras={"text": "route dictionary"},
        )
    )
    boxes.append(
        _box(
            OBJ_HTTP_RESP_PREPEND,
            "newobj",
            (maxurl_x, http_y + 2 * http_row_h, 200.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend onHttpResponse"},
        )
    )
    lines.append(_line(OBJ_HTTP_MAXURL, 0, OBJ_HTTP_RESP_ROUTE, 0))
    lines.append(_line(OBJ_HTTP_RESP_ROUTE, 0, OBJ_HTTP_RESP_PREPEND, 0))
    lines.append(_line(OBJ_HTTP_RESP_PREPEND, 0, OBJ_SF_LOM_LOADER, 0))

    # ── sf_state outlet 0 → v8ui refresh ────────────────────────────────────
    # The state mgr emits `bang` on mutation. We prepend `refresh` so the
    # v8ui re-reads the dict.  (A bare bang also works — sf_ui.js treats
    # bang as refresh — but being explicit is self-documenting.)
    boxes.append(
        _box(
            "obj-refresh-prepend",
            "newobj",
            (16.0 + (js_w + js_gap) * 0, js_row_y + 68, 100.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend refresh"},
        )
    )
    lines.append(_line(OBJ_SF_STATE, 0, "obj-refresh-prepend", 0))
    lines.append(_line("obj-refresh-prepend", 0, OBJ_V8UI, 0))

    # sf_state outlet 1 (btnState) — unused in v1 but we print it so debug
    # sessions can see the transitions.
    boxes.append(
        _box(
            "obj-print-btnstate",
            "newobj",
            (260.0, js_row_y + 68, 160.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "print [sf_state.btnState]"},
        )
    )
    lines.append(_line(OBJ_SF_STATE, 1, "obj-print-btnstate", 0))

    # ── sf_forge outlets ────────────────────────────────────────────────────
    # 0 → state mgr (state mutation messages — passthrough list)
    lines.append(_line(OBJ_SF_FORGE, 0, OBJ_SF_STATE, 0))
    # 1 → [shell]
    boxes.append(
        _box(
            OBJ_SHELL,
            "newobj",
            (16.0 + (js_w + js_gap), js_row_y + 68, 80.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["", "bang"],
            extras={"text": "shell"},
        )
    )
    lines.append(_line(OBJ_SF_FORGE, 1, OBJ_SHELL, 0))
    # sf_lom_loader outlet 3 → [shell] for mkdir-p in the bounce flow
    # (deck manifest stubs need their parent dirs to exist).
    lines.append(_line(OBJ_SF_LOM_LOADER, 3, OBJ_SHELL, 0))
    # 2 → stemforge_loader (LOM) — passthrough list
    lines.append(_line(OBJ_SF_FORGE, 2, OBJ_SF_LOM_LOADER, 0))

    # ── [shell] → NDJSON parser → [route ...] → sf_forge on* handlers ───────
    lines.append(_line(OBJ_SHELL, 0, OBJ_SF_NDJSON_PARSER, 0))
    lines.append(_line(OBJ_SHELL, 1, OBJ_SF_NDJSON_PARSER, 0))

    boxes.append(
        _box(
            OBJ_ROUTE_NDJSON,
            "newobj",
            (16.0 + 2 * (js_w + js_gap), js_row_y + 68, 920.0, 22.0),
            numinlets=1,
            numoutlets=17,
            outlettype=[""] * 17,
            extras={
                "text": (
                    "route progress stem bpm slice_dir complete curated error "
                    "export_started export_progress export_clip_done "
                    "export_clip_error export_complete export_error "
                    "anchor_started anchor_complete anchor_error"
                )
            },
        )
    )
    lines.append(_line(OBJ_SF_NDJSON_PARSER, 0, OBJ_ROUTE_NDJSON, 0))

    # progress → onProgress <pct …> into sf_forge
    boxes.append(
        _box(
            OBJ_ONPROG_PREPEND,
            "newobj",
            (16.0, js_row_y + 200, 140.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend onProgress"},
        )
    )
    lines.append(_line(OBJ_ROUTE_NDJSON, 0, OBJ_ONPROG_PREPEND, 0))
    lines.append(_line(OBJ_ONPROG_PREPEND, 0, OBJ_SF_FORGE, 0))

    boxes.append(
        _box(
            OBJ_ONSTEM_PREPEND,
            "newobj",
            (170.0, js_row_y + 200, 120.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend onStem"},
        )
    )
    lines.append(_line(OBJ_ROUTE_NDJSON, 1, OBJ_ONSTEM_PREPEND, 0))
    lines.append(_line(OBJ_ONSTEM_PREPEND, 0, OBJ_SF_FORGE, 0))

    boxes.append(
        _box(
            OBJ_ONBPM_PREPEND,
            "newobj",
            (300.0, js_row_y + 200, 120.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend onBpm"},
        )
    )
    lines.append(_line(OBJ_ROUTE_NDJSON, 2, OBJ_ONBPM_PREPEND, 0))
    lines.append(_line(OBJ_ONBPM_PREPEND, 0, OBJ_SF_FORGE, 0))

    boxes.append(
        _box(
            OBJ_ONCOMPLETE_PREPEND,
            "newobj",
            (430.0, js_row_y + 200, 140.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend onComplete"},
        )
    )
    lines.append(_line(OBJ_ROUTE_NDJSON, 4, OBJ_ONCOMPLETE_PREPEND, 0))
    lines.append(_line(OBJ_ONCOMPLETE_PREPEND, 0, OBJ_SF_FORGE, 0))

    boxes.append(
        _box(
            OBJ_ONCURATED_PREPEND,
            "newobj",
            (580.0, js_row_y + 200, 140.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend onCurated"},
        )
    )
    lines.append(_line(OBJ_ROUTE_NDJSON, 5, OBJ_ONCURATED_PREPEND, 0))
    lines.append(_line(OBJ_ONCURATED_PREPEND, 0, OBJ_SF_FORGE, 0))

    boxes.append(
        _box(
            OBJ_ONERROR_PREPEND,
            "newobj",
            (730.0, js_row_y + 200, 120.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend onError"},
        )
    )
    lines.append(_line(OBJ_ROUTE_NDJSON, 6, OBJ_ONERROR_PREPEND, 0))
    lines.append(_line(OBJ_ONERROR_PREPEND, 0, OBJ_SF_FORGE, 0))

    # ── Clip-export NDJSON routes (sf_clip_export ← [shell] ← Python helper) ─
    # Each event from tools/m4l_export_clips.py becomes a prepend → message
    # call into the sf_clip_export [js] box. Names mirror the JS handlers in
    # sf_clip_export.js (onClipExportStarted / Progress / ClipDone / ClipError
    # / Complete / Error).
    _CX_PREPENDS = [
        # (route_outlet_idx, prepend_obj_id, message_name, x_offset_idx)
        (7, OBJ_CX_STARTED_PREP, "onClipExportStarted", 0),
        (8, OBJ_CX_PROGRESS_PREP, "onClipExportProgress", 1),
        (9, OBJ_CX_CLIP_DONE_PREP, "onClipExportClipDone", 2),
        (10, OBJ_CX_CLIP_ERROR_PREP, "onClipExportClipError", 3),
        (11, OBJ_CX_COMPLETE_PREP, "onClipExportComplete", 4),
        (12, OBJ_CX_ERROR_PREP, "onClipExportError", 5),
    ]
    for route_idx, obj_id, msg_name, x_idx in _CX_PREPENDS:
        boxes.append(
            _box(
                obj_id,
                "newobj",
                (16.0 + x_idx * 170.0, js_row_y + 250, 160.0, 22.0),
                numinlets=1,
                numoutlets=1,
                outlettype=[""],
                extras={"text": "prepend " + msg_name},
            )
        )
        lines.append(_line(OBJ_ROUTE_NDJSON, route_idx, obj_id, 0))
        lines.append(_line(obj_id, 0, OBJ_SF_CLIP_EXPORT, 0))

    # ── Locator-anchor NDJSON routes (sf_locator_anchor ← [shell] ← Python) ─
    # Each event from tools/m4l_locator_anchor.py becomes a prepend → message
    # call into the sf_locator_anchor [js] box. Names mirror the JS handlers.
    _LA_PREPENDS = [
        # (route_outlet_idx, prepend_obj_id, message_name, x_offset_idx)
        (13, OBJ_LA_STARTED_PREP, "onAnchorStarted", 6),
        (14, OBJ_LA_COMPLETE_PREP, "onAnchorComplete", 7),
        (15, OBJ_LA_ERROR_PREP, "onAnchorError", 8),
    ]
    for route_idx, obj_id, msg_name, x_idx in _LA_PREPENDS:
        boxes.append(
            _box(
                obj_id,
                "newobj",
                (16.0 + x_idx * 170.0, js_row_y + 250, 160.0, 22.0),
                numinlets=1,
                numoutlets=1,
                outlettype=[""],
                extras={"text": "prepend " + msg_name},
            )
        )
        lines.append(_line(OBJ_ROUTE_NDJSON, route_idx, obj_id, 0))
        lines.append(_line(obj_id, 0, OBJ_SF_LOCATOR_ANCHOR, 0))

    # ── Status bar updates — sf_state.getStateJson emits `state <json>` but
    # for the status bar we key off a lightweight prefix.  v1: just wire the
    # sf_forge outlet-0 list into [route markPhase1Progress …] to drive text
    # + dot color.  For simplicity, we do the minimal wire: sf_forge will
    # also send human-readable "status …" messages in a future pass.
    # For now the v8ui shows all state; the status text just shows "ready"
    # until the mgr explicitly drives it.
    # (Left intentionally thin — the v8ui is the primary surface.)

    # ── loadbang → scan presets + manifests + load settings ─────────────────
    boxes.append(
        _box(
            OBJ_LOADBANG,
            "newobj",
            (500.0, 20.0, 120.0, 22.0),
            numinlets=1,
            # [live.thisdevice] in Max 9 has 3 outlets:
            #   outlet 0 = loadbang   (fired at patcher load; LOM NOT ready)
            #   outlet 1 = initialized (fired when Live API IS ready) ← use this
            #   outlet 2 = patcher attribute dumpout
            # We wire EVERYTHING that needs LiveAPI through outlet 1.
            numoutlets=3,
            outlettype=["bang", "bang", ""],
            extras={"text": "live.thisdevice"},
        )
    )
    boxes.append(
        _box(
            OBJ_LOAD_DEFERLOW,
            "newobj",
            (500.0, 50.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["bang"],
            extras={"text": "deferlow"},
        )
    )
    # live.thisdevice outlet 1 is the "Live API ready" bang.
    lines.append(_line(OBJ_LOADBANG, 1, OBJ_LOAD_DEFERLOW, 0))
    # ALSO fire `[message liveApiReady]` → loader when Live's API is ready.
    # The loader's liveApiReady() reads the .als path via LiveAPI (which
    # would have warned-and-returned-empty if called from the JS-box-level
    # `loadbang` at script-init time — see Phase 4A's bootstrap design).
    OBJ_LIVE_API_READY_MSG = "obj-live-api-ready-msg"
    boxes.append(
        _box(
            OBJ_LIVE_API_READY_MSG,
            "message",
            (640.0, 50.0, 110.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "liveApiReady"},
        )
    )
    lines.append(_line(OBJ_LOADBANG, 1, OBJ_LIVE_API_READY_MSG, 0))
    lines.append(_line(OBJ_LIVE_API_READY_MSG, 0, OBJ_SF_LOM_LOADER, 0))
    boxes.append(
        _box(
            OBJ_LOAD_SEQ,
            "newobj",
            (500.0, 80.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=3,
            outlettype=["bang", "bang", "bang"],
            extras={"text": "t b b b"},
        )
    )
    lines.append(_line(OBJ_LOAD_DEFERLOW, 0, OBJ_LOAD_SEQ, 0))

    boxes.append(
        _box(
            OBJ_LOAD_SCAN_PRESETS,
            "message",
            (500.0, 110.0, 80.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "scan"},
        )
    )
    lines.append(_line(OBJ_LOAD_SEQ, 0, OBJ_LOAD_SCAN_PRESETS, 0))
    lines.append(_line(OBJ_LOAD_SCAN_PRESETS, 0, OBJ_SF_PRESET_LOADER, 0))

    boxes.append(
        _box(
            OBJ_LOAD_SCAN_MANIFESTS,
            "message",
            (585.0, 110.0, 110.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "scanManifests"},
        )
    )
    lines.append(_line(OBJ_LOAD_SEQ, 1, OBJ_LOAD_SCAN_MANIFESTS, 0))
    lines.append(_line(OBJ_LOAD_SCAN_MANIFESTS, 0, OBJ_SF_MANIFEST_LOADER, 0))

    boxes.append(
        _box(
            OBJ_LOAD_SETTINGS,
            "message",
            (700.0, 110.0, 60.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "load"},
        )
    )
    lines.append(_line(OBJ_LOAD_SEQ, 2, OBJ_LOAD_SETTINGS, 0))
    lines.append(_line(OBJ_LOAD_SETTINGS, 0, OBJ_SF_SETTINGS, 0))

    # Kick the v8ui into refreshing once everything's loaded.
    boxes.append(
        _box(
            "obj-load-refresh-msg",
            "message",
            (770.0, 110.0, 80.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "refresh"},
        )
    )
    lines.append(_line(OBJ_LOAD_SEQ, 2, "obj-load-refresh-msg", 0))
    lines.append(_line("obj-load-refresh-msg", 0, OBJ_V8UI, 0))

    # ── Diagnostic print on load ────────────────────────────────────────────
    boxes.append(
        _box(
            "obj-diag-print",
            "newobj",
            (600.0, 20.0, 200.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": f"print [{device_name}-v{device_version}-loaded]"},
        )
    )
    lines.append(_line(OBJ_LOADBANG, 0, "obj-diag-print", 0))

    # ── Audio passthrough (required for M4L audio effects) ──────────────────
    boxes.append(
        _box(
            OBJ_PLUGIN_IN,
            "newobj",
            (20.0, 20.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["signal"],
            extras={"text": "plugin~ 2"},
        )
    )
    boxes.append(
        _box(
            OBJ_PLUGOUT,
            "newobj",
            (20.0, 60.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "plugout~ 2"},
        )
    )
    lines.append(_line(OBJ_PLUGIN_IN, 0, OBJ_PLUGOUT, 0))

    # ── Top-level patcher wrapper ───────────────────────────────────────────
    patcher = {
        "patcher": {
            "fileversion": 1,
            "appversion": {
                "major": 9,
                "minor": 0,
                "revision": 8,
                "architecture": "x64",
                "modernui": 1,
            },
            "classnamespace": "box",
            "rect": [40.0, 80.0, 40.0 + size["width"] + 40, 80.0 + size["height"] + 360],
            "openinpresentation": 1,
            "default_fontsize": 11.0,
            "default_fontface": 0,
            "default_fontname": "Ableton Sans Medium",
            "gridonopen": 1,
            "gridsize": [8.0, 8.0],
            "gridsnaponopen": 1,
            "objectsnaponopen": 1,
            "statusbarvisible": 2,
            "toolbarvisible": 1,
            "devicewidth": float(size["width"]),
            "description": f"{device_name} — matrix UI, v8ui-driven",
            "digest": "",
            "tags": "",
            "style": "",
            "boxes": boxes,
            "lines": lines,
            "dependency_cache": [
                {
                    "name": "sf_ui.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "sf_state.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "sf_forge.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "sf_preset_loader.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "sf_manifest_loader.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "sf_settings.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "sf_logger.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "stemforge_ndjson_parser.v0.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "stemforge_loader.v0.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
            ],
            "autosave": 0,
            "project": {
                "version": 1,
                "creationdate": 3590052493,
                "modificationdate": 3590052493,
                "viewrect": [0.0, 0.0, 300.0, 500.0],
                "autoorganize": 1,
                "hideprojectwindow": 1,
                "showdependencies": 1,
                "autolocalize": 0,
                "contents": {"patchers": {}, "code": {}},
                "layout": {},
                "searchpath": {},
                "detailsvisible": 0,
                "amxdtype": 1633771873,
                "readonly": 0,
                "devpathtype": 0,
                "devpath": ".",
                "sortmode": 0,
                "viewmode": 0,
                "includepackages": 0,
            },
            "parameters": {
                "parameterbanks": {
                    "0": {
                        "index": 0,
                        "name": "",
                        "parameters": ["-", "-", "-", "-", "-", "-", "-", "-"],
                    }
                },
                "inherited_shortname": 1,
            },
        }
    }
    return patcher


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("device_yaml")
    ap.add_argument("--out", default=None, help="Write JSON patcher to this path")
    args = ap.parse_args()

    patch = build_patcher(args.device_yaml)
    out = json.dumps(patch, indent="\t")
    if args.out:
        Path(args.out).write_text(out)
    else:
        print(out)
