"""
builder — generate a Max for Live patcher (.maxpat JSON) from v0/interfaces/device.yaml.

v0.1.0 matrix architecture (see specs/stemforge_device_ui_spec_LATEST.md
and specs/stemforge_device_ui_contract.md):

    ┌──────────────────────────────────────────────────────────────┐
    │  Device canvas 820 × 169 (fixed M4L height)                  │
    │                                                              │
    │  ┌──────────────────────────────────────────────────────┐    │
    │  │  [v8ui sf_ui.js] @ 0,0  size 820×149                 │    │
    │  │  Paints every phase (empty/idle/forging/done/error)  │    │
    │  │  based on the sf_state dict.  Emits click events     │    │
    │  │  out outlet 0: preset_click / source_click /         │    │
    │  │  forge_click / cancel_click / done_click /           │    │
    │  │  retry_click / settings_click                        │    │
    │  └──────────────────────────────────────────────────────┘    │
    │                                                              │
    │  Footer 820×20 — native live.text / live.comment objects.    │
    │     [sf_status_dot] [sf_status_text]       [sf_version_text] │
    └──────────────────────────────────────────────────────────────┘

Logic layer objects (classic [js], not in presentation):
    [js sf_state.js       @scripting_name sf_state_mgr]
    [js sf_forge.js       @scripting_name sf_forge_mgr]
    [js sf_preset_loader.js]
    [js sf_manifest_loader.js]
    [js sf_settings.js    @scripting_name sf_settings_mgr]
    [js sf_logger.js      @scripting_name sf_logger]

Preserved (unchanged) objects, reused by sf_forge:
    [js stemforge_ndjson_parser.v0.js]
    [js stemforge_loader.v0.js        @scripting_name sf_lom_loader]

Wiring summary (contract §8):
    v8ui outlet 0 → [route preset_click source_click forge_click cancel_click
                     done_click retry_click settings_click]
        preset_click   → sf_preset_loader (open popup)
        source_click   → sf_manifest_loader (open popup)
        forge_click    → sf_forge_mgr startForge
        cancel_click   → sf_forge_mgr cancelForge
        retry_click    → sf_forge_mgr retry
        done_click     → sf_state_mgr    reset
        settings_click → sf_settings_mgr openFile

    sf_state_mgr outlet 0 → [v8ui sf_ui] refresh (redraw on every mutation)
    sf_preset_loader outlet 0 → [umenu sf_preset_menu]
    sf_preset_loader outlet 1 → sf_state_mgr (setPreset <json>)
    sf_manifest_loader outlet 0 → [umenu sf_source_menu]
    sf_manifest_loader outlet 1 → sf_state_mgr (setSource <json>) or browseAudio
    sf_forge_mgr outlet 0 → sf_state_mgr (phase transitions)
    sf_forge_mgr outlet 1 → [shell]        (Phase 1 native binary)
    sf_forge_mgr outlet 2 → sf_lom_loader  (Phase 2 LiveAPI track creation)

    [shell] → [js stemforge_ndjson_parser] → [route progress stem bpm slice_dir
              complete curated error] → sf_forge_mgr on* handlers

Dicts (created by a leading [dict] object per contract §2):
    sf_state / sf_preset / sf_manifest / sf_settings

The .amxd is packed by amxd_pack.py and installed via tools/sf_deploy.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# ── Palette (kept small — v8ui owns most color; we only need footer text
# and status dot defaults here) ──────────────────────────────────────────────
COLORS = {
    "bg":        [0.055, 0.055, 0.055, 1.0],
    "text":      [0.878, 0.878, 0.878, 1.0],
    "dim":       [0.533, 0.533, 0.533, 1.0],
    "status_bg": [0.118, 0.118, 0.137, 1.0],   # #1E1E23 matches v8ui panel
    "dot_grey":  [0.333, 0.333, 0.333, 1.0],   # #555555 — empty/waiting default
}


# ── Stable object IDs ─────────────────────────────────────────────────────────
# Keep these stable so patchlines are readable and diffs small.

OBJ_V8UI                = "obj-sf-ui"

OBJ_SF_STATE            = "obj-sf-state"
OBJ_SF_FORGE            = "obj-sf-forge"
OBJ_SF_PRESET_LOADER    = "obj-sf-preset-loader"
OBJ_SF_MANIFEST_LOADER  = "obj-sf-manifest-loader"
OBJ_SF_SETTINGS         = "obj-sf-settings"
OBJ_SF_LOGGER           = "obj-sf-logger"
OBJ_SF_NDJSON_PARSER    = "obj-sf-ndjson-parser"
OBJ_SF_LOM_LOADER       = "obj-sf-lom-loader"

OBJ_DICT_STATE          = "obj-dict-sf-state"
OBJ_DICT_PRESET         = "obj-dict-sf-preset"
OBJ_DICT_MANIFEST       = "obj-dict-sf-manifest"
OBJ_DICT_SETTINGS       = "obj-dict-sf-settings"

OBJ_UMENU_PRESET        = "obj-umenu-preset"
OBJ_UMENU_SOURCE        = "obj-umenu-source"

OBJ_ROUTE_UI_EVENTS     = "obj-route-ui-events"
OBJ_ROUTE_NDJSON        = "obj-route-ndjson"

OBJ_SHELL               = "obj-shell"
OBJ_OPENDIALOG          = "obj-opendialog"
OBJ_AUDIOPATH_REGEX     = "obj-audiopath-regex"
OBJ_AUDIOPATH_PREPEND   = "obj-audiopath-prepend"

OBJ_STATUS_DOT          = "obj-sf-status-dot"
OBJ_STATUS_TEXT         = "obj-sf-status-text"
OBJ_VERSION_TEXT        = "obj-sf-version-text"

OBJ_LOADBANG            = "obj-loadbang"
OBJ_LOAD_DEFERLOW       = "obj-load-deferlow"
OBJ_LOAD_SEQ            = "obj-load-seq"
OBJ_LOAD_SCAN_PRESETS   = "obj-load-scan-presets"
OBJ_LOAD_SCAN_MANIFESTS = "obj-load-scan-manifests"
OBJ_LOAD_SETTINGS       = "obj-load-settings"

OBJ_PRESET_SELECT_PREP  = "obj-preset-select-prepend"
OBJ_SOURCE_SELECT_PREP  = "obj-source-select-prepend"
OBJ_FORGE_ACTION_ROUTE  = "obj-forge-action-route"

OBJ_PROGRESS_UNPACK     = "obj-progress-unpack"
OBJ_ONPROG_PREPEND      = "obj-onprog-prepend"
OBJ_ONSTEM_PREPEND      = "obj-onstem-prepend"
OBJ_ONBPM_PREPEND       = "obj-onbpm-prepend"
OBJ_ONCOMPLETE_PREPEND  = "obj-oncomplete-prepend"
OBJ_ONCURATED_PREPEND   = "obj-oncurated-prepend"
OBJ_ONERROR_PREPEND     = "obj-onerror-prepend"

OBJ_PLUGIN_IN           = "obj-plugin-in"
OBJ_PLUGOUT             = "obj-plugout"

OBJ_FILELOG_PREPEND     = "obj-filelog-prepend"


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


def _line(
    src_id: str, src_outlet: int, dst_id: str, dst_inlet: int
) -> dict[str, Any]:
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
    """Classic [js] object (SpiderMonkey engine). NOT in presentation."""
    text = f"js {filename}"
    if scripting_name:
        text += f" @scripting_name {scripting_name}"
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

    v8ui_cfg    = ui["v8ui"]
    status_bar  = ui["status_bar"]

    boxes: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []

    # ── Presentation: v8ui canvas (draws the whole main body) ────────────────

    v8ui_rect = (
        v8ui_cfg["pos"]["x"],
        v8ui_cfg["pos"]["y"],
        v8ui_cfg["size"]["width"],
        v8ui_cfg["size"]["height"],
    )
    # Presentation-mode rect: full 820×149 so the middle matrix AND right
    # FORGE button are both visible. Native preset/source umenus sit on TOP
    # of the v8ui's left-column cards (z-order: umenus added after v8ui).
    v8ui_presentation_rect = (
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
            presentation=True,
            presentation_rect=v8ui_presentation_rect,
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
                "mode": 0,          # display-only button
                "text": "",
                "activebgcolor":   COLORS["dot_grey"],
                "bgcolor":         COLORS["dot_grey"],
                "activebgoncolor": COLORS["dot_grey"],
                "bgoncolor":       COLORS["dot_grey"],
                "bordercolor":     COLORS["dot_grey"],
                "activebordercolor":    COLORS["dot_grey"],
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
                "text": "waiting — pick a preset and source",
                "fontsize": 9.0,
                "textcolor": COLORS["dim"],
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
            },
        )
    )

    # ── Dict objects (one per canonical dict name) ──────────────────────────
    # These just ensure the dicts exist on patcher load so JS Dict() refs work.

    dict_row_y = 200.0   # out of presentation mode; patcher-area only
    dict_width = 150.0
    for i, (box_id, dict_name) in enumerate(
        [
            (OBJ_DICT_STATE,    "sf_state"),
            (OBJ_DICT_PRESET,   "sf_preset"),
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
            numoutlets=3,
            outlettype=["", "", ""],
        )
    )

    # ── Visible native umenus (left column, presentation mode) ──────────────
    #
    # Pragmatic fix (2026-04-23): the previous transparent-overlay approach on
    # top of v8ui-drawn preset/source cards was unreliable — clicks on the
    # cards did not consistently open the dropdown in Ableton. We now put two
    # VISIBLE umenus with native Max/Ableton chrome in the left column and
    # narrow the v8ui presentation_rect so it doesn't cover that area.
    #
    # User-visible contract:
    #   - Top-left dropdown  (8, 8,  196, 40)  → sf_preset_menu
    #   - Below it           (8, 54, 196, 40)  → sf_source_menu
    #   - v8ui owns only x=212..820 (middle+right columns)
    #
    # arrow:1 gives the native triangle so it's obviously clickable. No color
    # overrides — Max renders default chrome, which matches other M4L devices.
    # autopopulate:0 keeps the umenu empty until the loader scans and sends
    # `append <name>` via patchline.
    boxes.append(
        _box(
            OBJ_UMENU_PRESET,
            "umenu",
            (16.0, js_row_y + 80, 196.0, 40.0),
            presentation=True,
            presentation_rect=(8.0, 8.0, 196.0, 40.0),
            numinlets=1,
            numoutlets=3,
            outlettype=["int", "", ""],
            extras={
                "varname": "sf_preset_menu",
                "items": "Pick preset...",
                "autopopulate": 0,
                "arrow": 1,
                "fontsize": 11.0,
                "fontname": "Ableton Sans Medium",
                "parameter_enable": 0,
            },
        )
    )
    boxes.append(
        _box(
            OBJ_UMENU_SOURCE,
            "umenu",
            (16.0 + 220.0, js_row_y + 80, 196.0, 40.0),
            presentation=True,
            presentation_rect=(8.0, 54.0, 196.0, 40.0),
            numinlets=1,
            numoutlets=3,
            outlettype=["int", "", ""],
            extras={
                "varname": "sf_source_menu",
                "items": "Pick source...",
                "autopopulate": 0,
                "arrow": 1,
                "fontsize": 11.0,
                "fontname": "Ableton Sans Medium",
                "parameter_enable": 0,
            },
        )
    )

    # umenu outlet 0 (int index) → `select <idx>` into the respective loader.
    boxes.append(
        _box(
            OBJ_PRESET_SELECT_PREP,
            "newobj",
            (16.0, js_row_y + 110, 120.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend select"},
        )
    )
    lines.append(_line(OBJ_UMENU_PRESET, 0, OBJ_PRESET_SELECT_PREP, 0))
    lines.append(_line(OBJ_PRESET_SELECT_PREP, 0, OBJ_SF_PRESET_LOADER, 0))

    boxes.append(
        _box(
            OBJ_SOURCE_SELECT_PREP,
            "newobj",
            (16.0 + 220.0, js_row_y + 110, 120.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend select"},
        )
    )
    lines.append(_line(OBJ_UMENU_SOURCE, 0, OBJ_SOURCE_SELECT_PREP, 0))
    lines.append(_line(OBJ_SOURCE_SELECT_PREP, 0, OBJ_SF_MANIFEST_LOADER, 0))

    # Preset-loader outlet 0 populates the umenu.
    lines.append(_line(OBJ_SF_PRESET_LOADER, 0, OBJ_UMENU_PRESET, 0))
    # Preset-loader outlet 1 sends setPreset <json> → state mgr.
    lines.append(_line(OBJ_SF_PRESET_LOADER, 1, OBJ_SF_STATE, 0))

    # Manifest-loader outlet 0 populates the umenu.
    lines.append(_line(OBJ_SF_MANIFEST_LOADER, 0, OBJ_UMENU_SOURCE, 0))
    # Manifest-loader outlet 1 sends setSource <json> OR browseAudio → we
    # route through [route] to separate the two.
    boxes.append(
        _box(
            "obj-route-source",
            "newobj",
            (16.0 + 220.0, js_row_y + 140, 220.0, 22.0),
            numinlets=1,
            numoutlets=3,
            outlettype=["", "", ""],
            extras={"text": "route setSource browseAudio"},
        )
    )
    lines.append(_line(OBJ_SF_MANIFEST_LOADER, 1, "obj-route-source", 0))
    # setSource → state mgr (re-prepend because [route] strips the selector)
    boxes.append(
        _box(
            "obj-source-set-prepend",
            "newobj",
            (16.0 + 220.0, js_row_y + 166, 160.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend setSource"},
        )
    )
    lines.append(_line("obj-route-source", 0, "obj-source-set-prepend", 0))
    lines.append(_line("obj-source-set-prepend", 0, OBJ_SF_STATE, 0))

    # browseAudio → [opendialog sound] → regexp POSIX path → audioPath …
    boxes.append(
        _box(
            OBJ_OPENDIALOG,
            "newobj",
            (16.0 + 460.0, js_row_y + 166, 150.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["", "bang"],
            extras={"text": "opendialog sound"},
        )
    )
    lines.append(_line("obj-route-source", 1, OBJ_OPENDIALOG, 0))
    boxes.append(
        _box(
            OBJ_AUDIOPATH_REGEX,
            "newobj",
            (16.0 + 460.0, js_row_y + 192, 230.0, 22.0),
            numinlets=1,
            numoutlets=5,
            outlettype=["", "", "", "", ""],
            extras={"text": "regexp (.+):(/.*) @substitute %2"},
        )
    )
    lines.append(_line(OBJ_OPENDIALOG, 0, OBJ_AUDIOPATH_REGEX, 0))
    boxes.append(
        _box(
            OBJ_AUDIOPATH_PREPEND,
            "newobj",
            (16.0 + 460.0, js_row_y + 218, 160.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend audioPath"},
        )
    )
    lines.append(_line(OBJ_AUDIOPATH_REGEX, 0, OBJ_AUDIOPATH_PREPEND, 0))
    lines.append(_line(OBJ_AUDIOPATH_PREPEND, 0, OBJ_SF_MANIFEST_LOADER, 0))

    # ── v8ui event routing (outlet 0 is a selector-prefixed list) ───────────

    boxes.append(
        _box(
            OBJ_ROUTE_UI_EVENTS,
            "newobj",
            (16.0, js_row_y - 40,
             # width
             680.0, 22.0),
            numinlets=1,
            numoutlets=8,  # 7 events + unmatched
            outlettype=["", "", "", "", "", "", "", ""],
            extras={
                "text": (
                    "route preset_click source_click forge_click "
                    "cancel_click retry_click done_click settings_click"
                )
            },
        )
    )
    lines.append(_line(OBJ_V8UI, 0, OBJ_ROUTE_UI_EVENTS, 0))

    # Outlet 0 — preset_click: open the preset umenu as popup.
    # Simpler: every open click also triggers a `scan` into the loader so the
    # menu is always fresh.
    boxes.append(
        _box(
            "obj-preset-scan-msg",
            "message",
            (16.0, js_row_y - 10, 80.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "scan"},
        )
    )
    lines.append(_line(OBJ_ROUTE_UI_EVENTS, 0, "obj-preset-scan-msg", 0))
    lines.append(_line("obj-preset-scan-msg", 0, OBJ_SF_PRESET_LOADER, 0))
    # and also "popup" the umenu
    boxes.append(
        _box(
            "obj-preset-popup-msg",
            "message",
            (110.0, js_row_y - 10, 80.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "popup"},
        )
    )
    lines.append(_line(OBJ_ROUTE_UI_EVENTS, 0, "obj-preset-popup-msg", 0))
    lines.append(_line("obj-preset-popup-msg", 0, OBJ_UMENU_PRESET, 0))

    # Outlet 1 — source_click
    boxes.append(
        _box(
            "obj-source-scan-msg",
            "message",
            (200.0, js_row_y - 10, 110.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "scanManifests"},
        )
    )
    lines.append(_line(OBJ_ROUTE_UI_EVENTS, 1, "obj-source-scan-msg", 0))
    lines.append(_line("obj-source-scan-msg", 0, OBJ_SF_MANIFEST_LOADER, 0))
    boxes.append(
        _box(
            "obj-source-popup-msg",
            "message",
            (320.0, js_row_y - 10, 80.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "popup"},
        )
    )
    lines.append(_line(OBJ_ROUTE_UI_EVENTS, 1, "obj-source-popup-msg", 0))
    lines.append(_line("obj-source-popup-msg", 0, OBJ_UMENU_SOURCE, 0))

    # Outlet 2 — forge_click → sf_forge startForge
    # Outlet 3 — cancel_click → sf_forge cancelForge
    # Outlet 4 — retry_click → sf_forge retry
    # Outlet 5 — done_click → sf_state reset
    # Outlet 6 — settings_click → sf_settings openFile
    # Build a tiny [route] for the forge-targeted buttons so we can re-prepend
    # the correct message name.
    for out_idx, sym in [
        (2, "startForge"),
        (3, "cancelForge"),
        (4, "retry"),
    ]:
        pid = f"obj-forge-prep-{sym}"
        boxes.append(
            _box(
                pid,
                "message",
                (410.0 + (out_idx - 2) * 110, js_row_y - 10, 100.0, 22.0),
                numinlets=2,
                numoutlets=1,
                outlettype=[""],
                extras={"text": sym},
            )
        )
        lines.append(_line(OBJ_ROUTE_UI_EVENTS, out_idx, pid, 0))
        lines.append(_line(pid, 0, OBJ_SF_FORGE, 0))

    boxes.append(
        _box(
            "obj-done-reset-msg",
            "message",
            (410.0 + 3 * 110, js_row_y - 10, 60.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "reset"},
        )
    )
    lines.append(_line(OBJ_ROUTE_UI_EVENTS, 5, "obj-done-reset-msg", 0))
    lines.append(_line("obj-done-reset-msg", 0, OBJ_SF_STATE, 0))

    boxes.append(
        _box(
            "obj-settings-open-msg",
            "message",
            (410.0 + 4 * 110, js_row_y - 10, 80.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "openFile"},
        )
    )
    lines.append(_line(OBJ_ROUTE_UI_EVENTS, 6, "obj-settings-open-msg", 0))
    lines.append(_line("obj-settings-open-msg", 0, OBJ_SF_SETTINGS, 0))

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
    # 2 → stemforge_loader (LOM) — passthrough list
    lines.append(_line(OBJ_SF_FORGE, 2, OBJ_SF_LOM_LOADER, 0))

    # ── [shell] → NDJSON parser → [route ...] → sf_forge on* handlers ───────
    lines.append(_line(OBJ_SHELL, 0, OBJ_SF_NDJSON_PARSER, 0))
    lines.append(_line(OBJ_SHELL, 1, OBJ_SF_NDJSON_PARSER, 0))

    boxes.append(
        _box(
            OBJ_ROUTE_NDJSON,
            "newobj",
            (16.0 + 2 * (js_w + js_gap), js_row_y + 68, 460.0, 22.0),
            numinlets=1,
            numoutlets=8,
            outlettype=["", "", "", "", "", "", "", ""],
            extras={
                "text": "route progress stem bpm slice_dir complete curated error"
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
            (500.0, 20.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["bang"],
            extras={"text": "loadbang"},
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
    lines.append(_line(OBJ_LOADBANG, 0, OBJ_LOAD_DEFERLOW, 0))
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
