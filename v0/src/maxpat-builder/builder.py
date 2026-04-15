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

# ── Object IDs ────────────────────────────────────────────────────────────────
# Stable IDs keep diffs small between regenerations and make patchlines easy.
OBJ_TITLE = "obj-title"
OBJ_FILE_DROP = "obj-audio-in"
OBJ_FILE_PATH_MSG = "obj-file-path-msg"
OBJ_BACKEND_MENU = "obj-backend"
OBJ_PIPELINE_MENU = "obj-pipeline"
OBJ_SLICE_TOGGLE = "obj-slice"
OBJ_PROGRESS_BAR = "obj-progress-bar"
OBJ_STATUS_TEXT = "obj-status-text"
OBJ_SPLIT_BUTTON = "obj-split-button"
OBJ_BRIDGE = "obj-bridge"
OBJ_LOADER = "obj-loader"
OBJ_ROUTE_EVENTS = "obj-route-events"
OBJ_PROGRESS_ROUTE = "obj-progress-route"
OBJ_ERROR_FMT = "obj-error-fmt"
OBJ_CONSOLE_PRINT = "obj-console-print"
OBJ_PACK_SPLIT = "obj-pack-split"

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

    # --- Title comment ---
    title_el = elements_by_id.get("title", {"pos": {"x": 12, "y": 8}, "text": device_name})
    boxes.append(
        _box(
            OBJ_TITLE,
            "comment",
            (title_el["pos"]["x"], title_el["pos"]["y"], 200.0, 22.0),
            presentation=True,
            numinlets=1,
            numoutlets=0,
            extras={
                "text": title_el.get("text", device_name),
                "fontsize": 16.0,
                "textcolor": [0.753, 0.518, 0.988, 1.0],
            },
        )
    )

    # --- File drop (dropfile) ---
    fd = elements_by_id["audio_in"]
    boxes.append(
        _box(
            OBJ_FILE_DROP,
            "dropfile",
            (fd["pos"]["x"], fd["pos"]["y"], fd["size"]["width"], fd["size"]["height"]),
            presentation=True,
            numinlets=1,
            numoutlets=2,
            outlettype=["", "int"],
            extras={"types": list(fd.get("accepts", [])), "fontsize": 11.0},
        )
    )
    # Message box to store the last-dropped file path (string). Dropfile's
    # outlet 0 emits a symbol; we capture it in a message box so the split
    # button can re-send it without re-dropping.
    boxes.append(
        _box(
            OBJ_FILE_PATH_MSG,
            "message",
            (
                fd["pos"]["x"],
                fd["pos"]["y"] + fd["size"]["height"] + 4,
                fd["size"]["width"],
                20.0,
            ),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": ""},
        )
    )
    lines.append(_line(OBJ_FILE_DROP, 0, OBJ_FILE_PATH_MSG, 0))

    # --- Backend dropdown (umenu) ---
    be = elements_by_id["backend"]
    boxes.append(
        _box(
            OBJ_BACKEND_MENU,
            "umenu",
            (be["pos"]["x"], be["pos"]["y"], 136.0, 22.0),
            presentation=True,
            numinlets=1,
            numoutlets=3,
            outlettype=["int", "", ""],
            extras={
                "items": ", ".join(be["options"]),
                "arrow": 1,
                "autopopulate": 1,
                "prefix": "Backend: ",
            },
        )
    )

    # --- Pipeline dropdown (umenu) ---
    pl = elements_by_id["pipeline"]
    boxes.append(
        _box(
            OBJ_PIPELINE_MENU,
            "umenu",
            (pl["pos"]["x"], pl["pos"]["y"], 136.0, 22.0),
            presentation=True,
            numinlets=1,
            numoutlets=3,
            outlettype=["int", "", ""],
            extras={
                "items": ", ".join(pl["options"]),
                "arrow": 1,
                "autopopulate": 1,
                "prefix": "Pipeline: ",
            },
        )
    )

    # --- Slice toggle ---
    sl = elements_by_id["slice"]
    boxes.append(
        _box(
            OBJ_SLICE_TOGGLE,
            "live.toggle",
            (sl["pos"]["x"], sl["pos"]["y"], 22.0, 22.0),
            presentation=True,
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={
                "parameter_enable": 1,
                "saved_attribute_attributes": {
                    "valueof": {"parameter_initial_enable": 1, "parameter_initial": [1 if sl.get("default", True) else 0]}
                },
            },
        )
    )

    # --- Progress bar (live.gain~ would be audio; use live.slider in bar style) ---
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
                "_parameter_range": [0.0, 100.0],
                "orientation": 2,  # horizontal
                "parameter_enable": 1,
                "parameter_shortname": "progress",
                "parameter_longname": "progress",
            },
        )
    )

    # --- Status text ---
    st = elements_by_id["status_text"]
    boxes.append(
        _box(
            OBJ_STATUS_TEXT,
            "comment",
            (st["pos"]["x"], st["pos"]["y"], size["width"] - 24, 22.0),
            presentation=True,
            numinlets=1,
            numoutlets=0,
            extras={"text": "idle", "fontsize": 11.0},
        )
    )

    # --- Split button ---
    sb = elements_by_id["split_button"]
    boxes.append(
        _box(
            OBJ_SPLIT_BUTTON,
            "textbutton",
            (sb["pos"]["x"], sb["pos"]["y"], 72.0, 28.0),
            presentation=True,
            numinlets=1,
            numoutlets=3,
            outlettype=["", "", "int"],
            extras={
                "text": sb.get("label", "Split"),
                "fontsize": 12.0,
                "bgoncolor": [0.9, 0.35, 0.15, 1.0],
            },
        )
    )

    # --- "pack split" message builder that turns a bang + 4 args into
    #     `split <path> <pipeline> <backend> <slice>` for node.script ---
    boxes.append(
        _box(
            OBJ_PACK_SPLIT,
            "newobj",
            (size["width"] - 300, sb["pos"]["y"] + 40, 240.0, 22.0),
            numinlets=5,
            numoutlets=1,
            outlettype=["list"],
            extras={"text": "pak split symbol symbol symbol int"},
        )
    )
    # The user clicks the button → send captured file path into pak inlet 1
    # (so the pak holds the latest path). Button then sends a bang to pak
    # inlet 0 so it emits the whole list.
    lines.append(_line(OBJ_SPLIT_BUTTON, 0, OBJ_PACK_SPLIT, 0))
    lines.append(_line(OBJ_FILE_PATH_MSG, 0, OBJ_PACK_SPLIT, 1))
    lines.append(_line(OBJ_PIPELINE_MENU, 1, OBJ_PACK_SPLIT, 2))
    lines.append(_line(OBJ_BACKEND_MENU, 1, OBJ_PACK_SPLIT, 3))
    lines.append(_line(OBJ_SLICE_TOGGLE, 0, OBJ_PACK_SPLIT, 4))

    # --- node.script bridge ---
    boxes.append(
        _box(
            OBJ_BRIDGE,
            "newobj",
            (16.0, sb["pos"]["y"] + 72, 260.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "node.script stemforge_bridge.v0.js"},
        )
    )
    lines.append(_line(OBJ_PACK_SPLIT, 0, OBJ_BRIDGE, 0))

    # --- route events from bridge by event-type symbol ---
    boxes.append(
        _box(
            OBJ_ROUTE_EVENTS,
            "newobj",
            (16.0, sb["pos"]["y"] + 102, 360.0, 22.0),
            numinlets=1,
            numoutlets=6,
            outlettype=["", "", "", "", "", ""],
            extras={"text": "route progress stem bpm slice_dir complete error"},
        )
    )
    lines.append(_line(OBJ_BRIDGE, 0, OBJ_ROUTE_EVENTS, 0))

    # progress → unpack → progress bar (first outlet = pct)
    boxes.append(
        _box(
            OBJ_PROGRESS_ROUTE,
            "newobj",
            (16.0, sb["pos"]["y"] + 132, 160.0, 22.0),
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
            (180.0, sb["pos"]["y"] + 132, 80.0, 22.0),
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
            (300.0, sb["pos"]["y"] + 132, 160.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "sprintf set ERROR(%s): %s"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 5, OBJ_ERROR_FMT, 0))
    lines.append(_line(OBJ_ERROR_FMT, 0, OBJ_STATUS_TEXT, 0))

    # --- LOM loader (classic js, has LiveAPI access) ---
    boxes.append(
        _box(
            OBJ_LOADER,
            "newobj",
            (16.0, sb["pos"]["y"] + 162, 240.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["", ""],
            extras={
                "text": "js stemforge_loader.v0.js",
                "saved_object_attributes": {
                    "filename": "stemforge_loader.v0.js",
                    "parameter_enable": 0,
                },
            },
        )
    )
    # complete event → loader
    boxes.append(
        _box(
            "obj-complete-prepend",
            "newobj",
            (16.0, sb["pos"]["y"] + 192, 140.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend loadManifest"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 4, "obj-complete-prepend", 0))
    lines.append(_line("obj-complete-prepend", 0, OBJ_LOADER, 0))
    # bpm event → loader (setBPM)
    boxes.append(
        _box(
            "obj-bpm-prepend",
            "newobj",
            (180.0, sb["pos"]["y"] + 192, 120.0, 22.0),
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
            (320.0, sb["pos"]["y"] + 162, 120.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "print StemForge"},
        )
    )
    lines.append(_line(OBJ_ROUTE_EVENTS, 1, OBJ_CONSOLE_PRINT, 0))
    lines.append(_line(OBJ_ROUTE_EVENTS, 3, OBJ_CONSOLE_PRINT, 0))

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
                    "name": "stemforge_bridge.v0.js",
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
