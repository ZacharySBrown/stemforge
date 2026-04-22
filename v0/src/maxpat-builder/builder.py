"""
builder — generate a Max for Live patcher (.maxpat JSON) from v0/interfaces/device.yaml.

The output is a dict matching Max's patcher schema. Feed it to
``amxd_pack.pack_amxd`` to produce a shippable .amxd.

Design
------
- One `node.script` object loads ``stemforge_bridge.v0.js`` at patcher open
  time. It owns the child-process spawn of ``stemforge-native`` and parses
  NDJSON into Max outlets (see v0/interfaces/ndjson.schema.json).
- One classic `js` object loads ``stemforge_loader.v0.js``, which uses the
  Live Object Model (LOM) to duplicate template tracks, set tempo, and load
  stem WAVs. node.script cannot reach LiveAPI, so the split is required.
- UI elements (file_drop, dropdowns, toggle, progress, status, button) are
  read from ``device.yaml`` and wired to the bridge via Max messages:
      split_button     → [split $file_path $pipeline $backend $slice] → node.script
      node.script      → [progress pct phase]     → progress_bar, status_text
      node.script      → [stem name path]         → js loader
      node.script      → [complete manifest]      → js loader (triggers LOM)
      node.script      → [error phase message]    → status_text

Coordinates from device.yaml are grid units (8px each) and are translated
directly into ``patching_rect`` / ``presentation_rect``. The M4L device
opens in presentation mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# ── Color palette (from v3 UI spec, Max 0-1 RGBA) ────────────────────────────
COLORS = {
    "bg":        [0.055, 0.055, 0.055, 1.0],   # #0e0e0e
    "surface":   [0.094, 0.094, 0.094, 1.0],   # #181818
    "card":      [0.118, 0.118, 0.118, 1.0],   # #1e1e1e
    "border":    [0.165, 0.165, 0.165, 1.0],   # #2a2a2a
    "accent":    [0.753, 0.518, 0.988, 1.0],   # #c084fc violet
    "accent2":   [0.506, 0.549, 0.973, 1.0],   # #818cf8 indigo
    "accent_deep": [0.306, 0.145, 0.714, 1.0], # #4e25b6 deep violet
    "text":      [0.878, 0.878, 0.878, 1.0],   # #e0e0e0
    "dim":       [0.533, 0.533, 0.533, 1.0],   # #888888
    "green":     [0.290, 0.871, 0.502, 1.0],   # #4ade80
    "yellow":    [0.984, 0.749, 0.141, 1.0],   # #fbbf24
    "red":       [0.973, 0.443, 0.443, 1.0],   # #f87171
}

# ── Object IDs ────────────────────────────────────────────────────────────────
# Stable IDs keep diffs small between regenerations and make patchlines easy.
OBJ_TITLE = "obj-title"
OBJ_FILE_DROP = "obj-audio-in"
OBJ_FILE_PATH_MSG = "obj-file-path-msg"
OBJ_BACKEND_MENU = "obj-backend"
OBJ_PRESET_MENU = "obj-preset"
OBJ_PRESET_DICT = "obj-preset-dict"
OBJ_PRESET_PREPEND = "obj-preset-prepend"
OBJ_SCAN_PRESETS_MSG = "obj-scan-presets-msg"
OBJ_SCAN_DEFERLOW = "obj-scan-deferlow"
OBJ_SLICE_TOGGLE = "obj-slice"
OBJ_PROGRESS_BAR = "obj-progress-bar"
OBJ_STATUS_TEXT = "obj-status-text"
OBJ_FORGE_BUTTON = "obj-forge-button"
OBJ_BRIDGE = "obj-bridge"
OBJ_LOADER = "obj-loader"
OBJ_ROUTE_EVENTS = "obj-route-events"
OBJ_PROGRESS_ROUTE = "obj-progress-route"
OBJ_ERROR_FMT = "obj-error-fmt"
OBJ_CONSOLE_PRINT = "obj-console-print"
OBJ_PACK_SPLIT = "obj-pack-split"
OBJ_PLUGIN_IN = "obj-plugin-in"
OBJ_PLUGOUT = "obj-plugout"
OBJ_LOAD_BTN = "obj-load-btn"
OBJ_LOAD_TRIGGER = "obj-load-trigger"
OBJ_LOAD_DICT = "obj-load-dict"
OBJ_LOAD_READ_MSG = "obj-load-read-msg"
OBJ_LOAD_DICT_MSG = "obj-load-dict-msg"
OBJ_COMPLETE_UNPACK = "obj-complete-unpack"
OBJ_STEMS_DIR_EXTRACT = "obj-stems-dir-extract"
OBJ_CURATE_CMD = "obj-curate-cmd"
OBJ_CURATED_PREPEND = "obj-curated-prepend"

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


# ── Core builder ──────────────────────────────────────────────────────────────


def build_patcher(device_yaml_path: str | Path) -> dict[str, Any]:
    """Load device.yaml and return a Max patcher dict."""
    with open(device_yaml_path) as f:
        spec = yaml.safe_load(f)

    ui = spec["ui"]
    size = ui["size"]
    device_name = spec["device"]["name"]

    elements_by_id: dict[str, dict[str, Any]] = {el["id"]: el for el in ui["elements"]}

    boxes: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []

    device_version = spec["device"].get("version", "0.0.2")

    # ── Visual panels ─────────────────────────────────────────────────────
    # NOTE: Panels are added to a separate list and appended AFTER all
    # interactive elements. In Max presentation mode, EARLIER items in
    # the boxes array render BEHIND later items. We add panels last but
    # they won't appear on top because we DON'T use panels for now —
    # we'll add them incrementally once the base layout is confirmed.
    #
    # TODO: Re-enable background panels after confirming element layout.
    # For now, the Ableton device view provides its own dark background.

    # ── Title bar elements ────────────────────────────────────────────────

    # No internal title — Ableton's device header shows it.
    # Version label — bottom-right, part of status row
    boxes.append(
        _box("version-label", "comment",
             (size["width"] - 48, 78, 44.0, 14.0),
             presentation=True, numinlets=1, numoutlets=0,
             extras={
                 "text": f"v{device_version}",
                 "fontsize": 9.0,
                 "textcolor": COLORS["dim"],
             })
    )

    # ── File dialog (hidden from presentation — used by Forge button) ─────

    OBJ_BROWSE_BTN = "obj-browse-btn"
    OBJ_OPENDIALOG = "obj-opendialog"
    OBJ_PATH_CONVERT = "obj-path-convert"

    # Browse button — NOT in presentation, just wiring target
    boxes.append(
        _box(OBJ_BROWSE_BTN, "textbutton",
             (600, 20, 80, 24),  # offscreen in patcher, not in presentation
             numinlets=1, numoutlets=3, outlettype=["", "", "int"],
             extras={"text": "Browse..."})
    )
    boxes.append(
        _box(OBJ_OPENDIALOG, "newobj", (600, 50, 150, 22),
             numinlets=1, numoutlets=2, outlettype=["", "bang"],
             extras={"text": "opendialog sound"})
    )
    lines.append(_line(OBJ_BROWSE_BTN, 0, OBJ_OPENDIALOG, 0))
    boxes.append(
        _box(OBJ_PATH_CONVERT, "newobj", (600, 80, 220, 22),
             numinlets=1, numoutlets=5, outlettype=["", "", "", "", ""],
             extras={"text": "regexp (.+):(/.*) @substitute %2"})
    )
    lines.append(_line(OBJ_OPENDIALOG, 0, OBJ_PATH_CONVERT, 0))
    boxes.append(
        _box(OBJ_FILE_PATH_MSG, "message", (600, 110, 200, 20),
             numinlets=2, numoutlets=1, outlettype=[""],
             extras={"text": ""})
    )
    lines.append(_line(OBJ_PATH_CONVERT, 0, OBJ_FILE_PATH_MSG, 0))

    # --- Load Session button ─────────────────────────────────────────────
    lb = elements_by_id["load_button"]
    boxes.append(
        _box(
            OBJ_LOAD_BTN,
            "textbutton",
            (lb["pos"]["x"], lb["pos"]["y"], lb["size"]["width"], lb["size"]["height"]),
            presentation=True,
            numinlets=1,
            numoutlets=3,
            outlettype=["", "", "int"],
            extras={
                "text": lb.get("label", "Load"),
                "fontsize": 10.0,
                "bgcolor": COLORS["accent_deep"],
                "bgoncolor": COLORS["accent"],
                "textcolor": COLORS["text"],
                "textoncolor": [1.0, 1.0, 1.0, 1.0],
                "rounded": 2.0,
            },
        )
    )
    # textbutton sends label text, not bang — use [t b] to extract bang
    boxes.append(
        _box(
            OBJ_LOAD_TRIGGER,
            "newobj",
            (lb["pos"]["x"] + lb["size"]["width"] + 8, lb["pos"]["y"] + 4, 30.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["bang"],
            extras={"text": "t b"},
        )
    )
    lines.append(_line(OBJ_LOAD_BTN, 0, OBJ_LOAD_TRIGGER, 0))
    # [dict] read (no args) opens a native file browser that shows .json files.
    # dict doesn't fire any outlet after read — we use [trigger b b] to sequence:
    # right outlet sends "read" (modal dialog blocks), left outlet fires JS after.
    OBJ_LOAD_SEQ = "obj-load-seq"
    boxes.append(
        _box(
            OBJ_LOAD_SEQ,
            "newobj",
            (lb["pos"]["x"], lb["pos"]["y"] + lb["size"]["height"] + 4, 40.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["bang", "bang"],
            extras={"text": "t b b"},
        )
    )
    lines.append(_line(OBJ_LOAD_TRIGGER, 0, OBJ_LOAD_SEQ, 0))
    # Right outlet (fires first) → "read" → dict opens file dialog
    boxes.append(
        _box(
            OBJ_LOAD_READ_MSG,
            "message",
            (lb["pos"]["x"] + 80, lb["pos"]["y"] + lb["size"]["height"] + 4, 60.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "read"},
        )
    )
    lines.append(_line(OBJ_LOAD_SEQ, 1, OBJ_LOAD_READ_MSG, 0))
    boxes.append(
        _box(
            OBJ_LOAD_DICT,
            "newobj",
            (lb["pos"]["x"] + 80, lb["pos"]["y"] + lb["size"]["height"] + 30, 140.0, 22.0),
            numinlets=2,
            numoutlets=4,
            outlettype=["dictionary", "", "", ""],
            extras={"text": "dict sf_manifest"},
        )
    )
    lines.append(_line(OBJ_LOAD_READ_MSG, 0, OBJ_LOAD_DICT, 0))
    # Left outlet (fires second, after dialog closes) → trigger JS loader
    boxes.append(
        _box(
            OBJ_LOAD_DICT_MSG,
            "message",
            (lb["pos"]["x"], lb["pos"]["y"] + lb["size"]["height"] + 30, 180.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "loadFromDict sf_manifest"},
        )
    )
    lines.append(_line(OBJ_LOAD_SEQ, 0, OBJ_LOAD_DICT_MSG, 0))
    lines.append(_line(OBJ_LOAD_DICT_MSG, 0, OBJ_LOADER, 0))

    # --- Backend dropdown — secondary ───────────────────────────────────
    be = elements_by_id["backend"]
    boxes.append(
        _box(
            OBJ_BACKEND_MENU,
            "umenu",
            (be["pos"]["x"], be["pos"]["y"], 180.0, 20.0),
            presentation=True,
            numinlets=1,
            numoutlets=3,
            outlettype=["int", "", ""],
            extras={
                "items": " ".join(be["options"]),
                "arrow": 1,
                "autopopulate": 1,
                "prefix": "Backend: ",
                "bgcolor": COLORS["surface"],
                "textcolor": COLORS["dim"],
                "fontsize": 10.0,
            },
        )
    )

    # --- Preset dropdown — primary selector, takes most of row 1 ────────
    pr = elements_by_id["preset"]
    boxes.append(
        _box(
            OBJ_PRESET_MENU,
            "umenu",
            (pr["pos"]["x"], pr["pos"]["y"], 220.0, 20.0),
            presentation=True,
            numinlets=1,
            numoutlets=3,
            outlettype=["int", "", ""],
            extras={
                "items": "",
                "arrow": 1,
                "prefix": "Preset: ",
                "bgcolor": COLORS["surface"],
                "textcolor": COLORS["accent2"],
                "fontsize": 11.0,
            },
        )
    )
    # [dict sf_preset] — holds the currently selected preset JSON
    boxes.append(
        _box(
            OBJ_PRESET_DICT,
            "newobj",
            (pr["pos"]["x"], pr["pos"]["y"] + 30, 140.0, 22.0),
            numinlets=2,
            numoutlets=4,
            outlettype=["dictionary", "", "", ""],
            extras={"text": "dict sf_preset"},
        )
    )
    # umenu outlet 1 (symbol) → prepend loadPreset → JS loader
    boxes.append(
        _box(
            OBJ_PRESET_PREPEND,
            "newobj",
            (pr["pos"]["x"] + 140, pr["pos"]["y"], 140.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend loadPreset"},
        )
    )
    lines.append(_line(OBJ_PRESET_MENU, 1, OBJ_PRESET_PREPEND, 0))
    lines.append(_line(OBJ_PRESET_PREPEND, 0, OBJ_LOADER, 0))
    # loadbang → deferlow → scanPresets → JS loader (populate umenu on device open)
    boxes.append(
        _box(
            OBJ_SCAN_DEFERLOW,
            "newobj",
            (pr["pos"]["x"] + 140, pr["pos"]["y"] + 30, 60.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "deferlow"},
        )
    )
    boxes.append(
        _box(
            OBJ_SCAN_PRESETS_MSG,
            "message",
            (pr["pos"]["x"] + 140, pr["pos"]["y"] + 56, 100.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "scanPresets"},
        )
    )
    lines.append(_line("obj-loadbang", 0, OBJ_SCAN_DEFERLOW, 0))
    lines.append(_line(OBJ_SCAN_DEFERLOW, 0, OBJ_SCAN_PRESETS_MSG, 0))
    lines.append(_line(OBJ_SCAN_PRESETS_MSG, 0, OBJ_LOADER, 0))

    # Slice toggle removed from UI — always on in production mode.

    # --- Progress bar (thin, no label) ──────────────────────────────────
    pb = elements_by_id["progress_bar"]
    boxes.append(
        _box(
            OBJ_PROGRESS_BAR,
            "live.slider",
            (pb["pos"]["x"], pb["pos"]["y"], pb["size"]["width"], pb["size"]["height"]),
            presentation=True,
            numinlets=1,
            numoutlets=2,
            outlettype=["", "float"],
            extras={
                "saved_attribute_attributes": {
                    "valueof": {
                        "parameter_longname": "StemForge Progress",
                        "parameter_shortname": " ",
                        "parameter_type": 0,
                        "parameter_mmin": 0.0,
                        "parameter_mmax": 100.0,
                        "parameter_initial_enable": 1,
                        "parameter_initial": [0],
                    }
                },
                "orientation": 0,
                "parameter_enable": 1,
                "showname": 0,
                "shownumber": 0,
            },
        )
    )

    # --- Status text — bottom row, muted ────────────────────────────────
    st = elements_by_id["status_text"]
    boxes.append(
        _box(
            OBJ_STATUS_TEXT,
            "live.comment",
            (st["pos"]["x"], st["pos"]["y"], size["width"] - 56, 14.0),
            presentation=True,
            numinlets=1,
            numoutlets=0,
            extras={
                "text": "ready",
                "fontsize": 9.0,
                "textcolor": COLORS["dim"],
            },
        )
    )

    # --- Forge button ────────────────────────────────────────────────────
    sb = elements_by_id["forge_button"]
    boxes.append(
        _box(
            OBJ_FORGE_BUTTON,
            "textbutton",
            (sb["pos"]["x"], sb["pos"]["y"], sb["size"]["width"], sb["size"]["height"]),
            presentation=True,
            numinlets=1,
            numoutlets=3,
            outlettype=["", "", "int"],
            extras={
                "text": sb.get("label", "FORGE"),
                "fontsize": 10.0,
                "fontface": 1,
                "bgcolor": COLORS["accent_deep"],
                "bgoncolor": COLORS["accent"],
                "textcolor": COLORS["text"],
                "textoncolor": [1.0, 1.0, 1.0, 1.0],
                "rounded": 2.0,
            },
        )
    )

    # --- Command builder: sprintf (no symout!) builds the shell command ---
    # symout wraps output as a single quoted symbol which [shell] can't parse.
    # Without symout, sprintf outputs a list of atoms that [shell] joins correctly.
    OBJ_CMD_FMT = "obj-cmd-fmt"
    boxes.append(
        _box(
            OBJ_CMD_FMT,
            "newobj",
            (size["width"] - 300, sb["pos"]["y"] + 40, 480.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "sprintf /usr/local/bin/stemforge-native split %s --json-events --variant ft-fused"},
        )
    )
    # Drop auto-fires: path → sprintf → shell
    lines.append(_line(OBJ_PATH_CONVERT, 0, OBJ_CMD_FMT, 0))
    # Split button re-fires: button → [t b] → message box (bang outputs stored path) → sprintf
    OBJ_TRIGGER_BANG = "obj-trigger-bang"
    boxes.append(
        _box(
            OBJ_TRIGGER_BANG,
            "newobj",
            (sb["pos"]["x"] + 80, sb["pos"]["y"] + 4, 30.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["bang"],
            extras={"text": "t b"},
        )
    )
    lines.append(_line(OBJ_FORGE_BUTTON, 0, OBJ_TRIGGER_BANG, 0))
    lines.append(_line(OBJ_TRIGGER_BANG, 0, OBJ_FILE_PATH_MSG, 0))
    lines.append(_line(OBJ_FILE_PATH_MSG, 0, OBJ_CMD_FMT, 0))

    # --- [shell] object — spawns stemforge-native ---
    boxes.append(
        _box(
            OBJ_BRIDGE,
            "newobj",
            (16.0, sb["pos"]["y"] + 72, 80.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["", "bang"],
            extras={"text": "shell"},
        )
    )
    lines.append(_line(OBJ_CMD_FMT, 0, OBJ_BRIDGE, 0))

    # --- NDJSON parser (classic [js] — parses Max-mangled JSON from [shell]) ---
    OBJ_NDJSON_PARSER = "obj-ndjson-parser"
    boxes.append(
        _box(
            OBJ_NDJSON_PARSER,
            "newobj",
            (16.0, sb["pos"]["y"] + 102, 240.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={
                "text": "js stemforge_ndjson_parser.v0.js",
                "saved_object_attributes": {
                    "filename": "stemforge_ndjson_parser.v0.js",
                    "parameter_enable": 0,
                },
            },
        )
    )
    # [shell] stdout → parser, [shell] done bang → parser
    lines.append(_line(OBJ_BRIDGE, 0, OBJ_NDJSON_PARSER, 0))
    lines.append(_line(OBJ_BRIDGE, 1, OBJ_NDJSON_PARSER, 0))

    # --- route events from parser by event-type symbol ---
    # Outlets: 0=progress 1=stem 2=bpm 3=slice_dir 4=complete 5=curated 6=error 7=unmatched
    boxes.append(
        _box(
            OBJ_ROUTE_EVENTS,
            "newobj",
            (16.0, sb["pos"]["y"] + 132, 420.0, 22.0),
            numinlets=1,
            numoutlets=8,
            outlettype=["", "", "", "", "", "", "", ""],
            extras={"text": "route progress stem bpm slice_dir complete curated error"},
        )
    )
    lines.append(_line(OBJ_NDJSON_PARSER, 0, OBJ_ROUTE_EVENTS, 0))

    # progress → unpack → progress bar (first outlet = pct)
    boxes.append(
        _box(
            OBJ_PROGRESS_ROUTE,
            "newobj",
            (16.0, sb["pos"]["y"] + 162, 160.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["float", "symbol"],
            extras={"text": "unpack 0. s"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 0, OBJ_PROGRESS_ROUTE, 0))
    lines.append(_line(OBJ_PROGRESS_ROUTE, 0, OBJ_PROGRESS_BAR, 0))
    # Phase symbol → status text (prepend "set ")
    boxes.append(
        _box(
            "obj-phase-prepend",
            "newobj",
            (180.0, sb["pos"]["y"] + 162, 80.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["", "list"],
            extras={"text": "prepend set"},
        )
    )
    lines.append(_line(OBJ_PROGRESS_ROUTE, 1, "obj-phase-prepend", 0))
    lines.append(_line("obj-phase-prepend", 0, OBJ_STATUS_TEXT, 0))

    # error → format for status_text + console print
    boxes.append(
        _box(
            OBJ_ERROR_FMT,
            "newobj",
            (300.0, sb["pos"]["y"] + 162, 160.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "sprintf set ERROR(%s): %s"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 6, OBJ_ERROR_FMT, 0))
    lines.append(_line(OBJ_ERROR_FMT, 0, OBJ_STATUS_TEXT, 0))

    # --- LOM loader (classic js, has LiveAPI access) ---
    # Outlets: 0=status text, 1=bang on completion, 2=umenu control (preset dropdown)
    boxes.append(
        _box(
            OBJ_LOADER,
            "newobj",
            (16.0, sb["pos"]["y"] + 192, 240.0, 22.0),
            numinlets=1,
            numoutlets=3,
            outlettype=["", "", ""],
            extras={
                "text": "js stemforge_loader.v0.js",
                "saved_object_attributes": {
                    "filename": "stemforge_loader.v0.js",
                    "parameter_enable": 0,
                },
            },
        )
    )
    # Loader outlet 2 → preset umenu (for dynamic population via scanPresets)
    lines.append(_line(OBJ_LOADER, 2, OBJ_PRESET_MENU, 0))
    # complete event → extract stems dir → curate command → [shell]
    # complete emits: manifest_path bpm stem_count — unpack to get manifest path
    boxes.append(
        _box(
            OBJ_COMPLETE_UNPACK,
            "newobj",
            (16.0, sb["pos"]["y"] + 222, 100.0, 22.0),
            numinlets=1,
            numoutlets=3,
            outlettype=["", "float", "int"],
            extras={"text": "unpack s 0. 0"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 4, OBJ_COMPLETE_UNPACK, 0))
    # Extract directory from manifest path: /path/to/dir/stems.json → /path/to/dir
    boxes.append(
        _box(
            OBJ_STEMS_DIR_EXTRACT,
            "newobj",
            (16.0, sb["pos"]["y"] + 248, 280.0, 22.0),
            numinlets=1,
            numoutlets=5,
            outlettype=["", "", "", "", ""],
            extras={"text": "regexp (.+)/[^/]+$ @substitute %1"},
        )
    )
    lines.append(_line(OBJ_COMPLETE_UNPACK, 0, OBJ_STEMS_DIR_EXTRACT, 0))
    # Build curate command with resolved paths
    repo_root = Path(__file__).resolve().parents[3]
    uv_path = Path.home() / ".local" / "bin" / "uv"
    curate_script = repo_root / "v0" / "src" / "stemforge_curate_bars.py"
    curate_fmt = (
        f"sprintf {uv_path} run --project {repo_root}"
        f" python {curate_script}"
        " --stems-dir %s --n-bars 16 --json-events"
    )
    boxes.append(
        _box(
            OBJ_CURATE_CMD,
            "newobj",
            (16.0, sb["pos"]["y"] + 274, 700.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": curate_fmt},
        )
    )
    lines.append(_line(OBJ_STEMS_DIR_EXTRACT, 0, OBJ_CURATE_CMD, 0))
    lines.append(_line(OBJ_CURATE_CMD, 0, OBJ_BRIDGE, 0))  # feed back into [shell]
    # curated event → unpack to extract manifest path → loadCuratedBars → loader
    # curated outlet emits: <manifest_path> <bars_per_stem> <bpm>
    OBJ_CURATED_UNPACK = "obj-curated-unpack"
    boxes.append(
        _box(
            OBJ_CURATED_UNPACK,
            "newobj",
            (16.0, sb["pos"]["y"] + 304, 100.0, 22.0),
            numinlets=1,
            numoutlets=3,
            outlettype=["", "int", "float"],
            extras={"text": "unpack s 0 0."},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 5, OBJ_CURATED_UNPACK, 0))
    boxes.append(
        _box(
            OBJ_CURATED_PREPEND,
            "newobj",
            (16.0, sb["pos"]["y"] + 330, 160.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend loadCuratedBars"},
        )
    )
    lines.append(_line(OBJ_CURATED_UNPACK, 0, OBJ_CURATED_PREPEND, 0))
    lines.append(_line(OBJ_CURATED_PREPEND, 0, OBJ_LOADER, 0))
    # bpm event → loader (setBPM)
    boxes.append(
        _box(
            "obj-bpm-prepend",
            "newobj",
            (180.0, sb["pos"]["y"] + 222, 120.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend setBpm"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 2, "obj-bpm-prepend", 0))
    lines.append(_line("obj-bpm-prepend", 0, OBJ_LOADER, 0))

    # --- Console print (for debug) ---
    boxes.append(
        _box(
            OBJ_CONSOLE_PRINT,
            "newobj",
            (320.0, sb["pos"]["y"] + 192, 120.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "print StemForge"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 1, OBJ_CONSOLE_PRINT, 0))
    lines.append(_line(OBJ_ROUTE_EVENTS, 3, OBJ_CONSOLE_PRINT, 0))

    # --- Debug prints at key points in FORGE chain ---
    boxes.append(
        _box(
            "obj-print-complete",
            "newobj",
            (120.0, sb["pos"]["y"] + 222, 140.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "print COMPLETE-EVENT"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 4, "obj-print-complete", 0))
    boxes.append(
        _box(
            "obj-print-curated",
            "newobj",
            (180.0, sb["pos"]["y"] + 304, 140.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "print CURATED-EVENT"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 5, "obj-print-curated", 0))
    boxes.append(
        _box(
            "obj-print-curate-cmd",
            "newobj",
            (16.0, sb["pos"]["y"] + 300, 140.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "print CURATE-CMD"},
        )
    )
    lines.append(_line(OBJ_CURATE_CMD, 0, "obj-print-curate-cmd", 0))

    # --- Test message boxes: simulate NDJSON events for debug ---
    # Simulate a "complete" event (as if stemforge-native just finished splitting)
    stems_dir = str(Path.home() / "stemforge" / "processed" / "the_champ_original_version")
    boxes.append(
        _box(
            "obj-test-complete",
            "message",
            (500.0, sb["pos"]["y"] + 132, 300.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": f"complete {stems_dir}/stems.json 112.35 4"},
        )
    )
    lines.append(_line("obj-test-complete", 0, OBJ_ROUTE_EVENTS, 0))
    # Simulate a "curated" event (as if the curate script just finished)
    curated_manifest = stems_dir + "/curated/manifest.json"
    boxes.append(
        _box(
            "obj-test-curated",
            "message",
            (500.0, sb["pos"]["y"] + 160, 300.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": f"curated {curated_manifest} 16 112.35"},
        )
    )
    lines.append(_line("obj-test-curated", 0, OBJ_ROUTE_EVENTS, 0))

    # --- Diagnostic: loadbang → print to verify patcher loads ---
    boxes.append(
        _box(
            "obj-loadbang",
            "newobj",
            (500.0, 20.0, 60.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["bang"],
            extras={"text": "loadbang"},
        )
    )
    boxes.append(
        _box(
            "obj-diag-print",
            "newobj",
            (500.0, 50.0, 180.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "print [StemForge-v0-loaded]"},
        )
    )
    lines.append(_line("obj-loadbang", 0, "obj-diag-print", 0))

    # --- Audio passthrough (required for M4L audio effects) ---
    boxes.append(
        _box(
            OBJ_PLUGIN_IN,
            "newobj",
            (20.0, 20.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=1,
            extras={"text": "plugin~ 2", "outlettype": ["signal"]},
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

    # --- Top-level patcher wrapper ---
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
            "rect": [40.0, 80.0, 40.0 + size["width"] + 40, 80.0 + size["height"] + 120],
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
            "description": f"{device_name} — ONNX-native stem split + beat slice",
            "digest": "",
            "tags": "",
            "style": "",
            "boxes": boxes,
            "lines": lines,
            "dependency_cache": [
                {
                    "name": "stemforge_ndjson_parser.v0.js",
                    "bootpath": "~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect",
                    "type": "TEXT",
                    "implicit": 1,
                },
                {
                    "name": "stemforge_loader.v0.js",
                    "bootpath": "~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect",
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

    parser = argparse.ArgumentParser()
    parser.add_argument("device_yaml")
    parser.add_argument("--out", default=None, help="Write JSON patcher to this path")
    args = parser.parse_args()

    patch = build_patcher(args.device_yaml)
    out = json.dumps(patch, indent="\t")
    if args.out:
        Path(args.out).write_text(out)
    else:
        print(out)
