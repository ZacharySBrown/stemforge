"""
builder — generate the Configurator Strip (.maxpat) from device.yaml.

Phase 3 strip device: a thin operations strip with seven labelled buttons
that fires HTTP intents at Lane A's local server. The strip is a SEPARATE
device from StemForge.amxd — both live in the user's M4L track stack and
share no patcher state.

See `device.yaml` for the operations table and layout numbers. See
`memory/m4l_device_development_guide.md` for the 20 pitfalls this builder
honors (audio passthrough, project field, classic [js] vs node.script,
[textbutton] needing [t b]→message, presentation rects, etc.).

Output: a Max patcher dict, JSON-serialisable, ready for amxd_pack.

Usage (as a library):

    from builder import build_patcher
    patcher = build_patcher("v0/src/m4l-devices/configurator-strip/device.yaml")

Usage (CLI — writes a .maxpat for visual debugging):

    python builder.py --out v0/build/ConfiguratorStrip.maxpat
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

# ── Stable object IDs ────────────────────────────────────────────────────────
# Keep these stable so test assertions don't shift when the layout changes.

OBJ_PLUGIN_IN = "obj-plugin-in"
OBJ_PLUGOUT = "obj-plugout"

OBJ_JS = "obj-sf-configurator-js"
OBJ_JWEB = "obj-sf-configurator-jweb"
OBJ_SHELL = "obj-sf-configurator-shell"

OBJ_LOADBANG = "obj-loadbang"

OBJ_STATUS_DOT = "obj-status-dot"
OBJ_STATUS_TEXT = "obj-status-text"
OBJ_FOOTER_TEXT = "obj-footer-text"
OBJ_VERSION_TEXT = "obj-version-text"

OBJ_ROUTE_DOT = "obj-route-dot"


# Per-button id template (filled with button id from device.yaml).
def _btn_box_id(btn_id: str) -> str:
    return f"obj-btn-{btn_id}"


def _btn_tb_id(btn_id: str) -> str:
    """[t b] trigger object between textbutton and message box.

    Per m4l_device_development_guide.md pitfall #17: [textbutton] outlet 0
    emits its label text, not a bang — we need [t b] to convert.
    """
    return f"obj-tb-{btn_id}"


def _btn_msg_id(btn_id: str) -> str:
    """Message box that names the verb fed into the JS dispatcher."""
    return f"obj-msg-{btn_id}"


# ── Helpers ──────────────────────────────────────────────────────────────────


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


# ── Verb → JS handler name ──────────────────────────────────────────────────
#
# device.yaml stores hyphenated verbs ("load-manifest"). The JS module
# exports camelCase function names. The mapping is explicit so we never have
# to guess what the Max [js] message router will accept.
VERB_TO_HANDLER = {
    "load-manifest": "loadManifest",
    "slice": "slice",
    "recompute": "recompute",
    "re-anchor": "reAnchor",
    "curate": "curate",
    "export": "exportPpak",
    "open-editor": "openEditor",
    "commit": "commit",
}


# ── Core builder ────────────────────────────────────────────────────────────


def build_patcher(device_yaml_path: str | Path) -> dict[str, Any]:
    """Load device.yaml and return a complete Max patcher dict.

    The patcher includes:
      - plugin~/plugout~ pair (required for audio-effect M4L devices)
      - Seven labelled [textbutton] objects → [t b] → message → [js sf_configurator]
      - [jweb] for the popup (float window)
      - [shell] for HTTP via curl + server-start
      - Status dot + status text + footer + version stamp (live.* widgets)
      - Loadbang → js (port discovery on device boot)
    """
    with open(device_yaml_path) as f:
        spec = yaml.safe_load(f)

    palette = spec["palette"]
    ui = spec["ui"]
    js_cfg = spec["js"]
    server_cfg = spec["server"]
    jweb_cfg = spec["jweb"]
    device_cfg = spec["device"]

    boxes: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []

    # ── plugin~ / plugout~ — required for audio-effect M4L (pitfall #7) ─────
    boxes.append(
        _box(
            OBJ_PLUGIN_IN,
            "newobj",
            (20.0, 360.0, 80.0, 22.0),
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
            (20.0, 400.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=0,
            extras={"text": "plugout~ 2"},
        )
    )
    lines.append(_line(OBJ_PLUGIN_IN, 0, OBJ_PLUGOUT, 0))

    # ── Buttons (presentation mode) ─────────────────────────────────────────
    btn_geom = ui["buttons"]["geometry"]
    btn_w = float(btn_geom["width"])
    btn_h = float(btn_geom["height"])
    btn_y = float(btn_geom["y"])
    btn_gap = float(btn_geom["gap"])
    btn_items = ui["buttons"]["items"]

    x_cursor = 8.0
    for btn in btn_items:
        btn_id = btn["id"]
        label = btn["label"]
        verb = btn["verb"]
        handler = VERB_TO_HANDLER.get(verb)
        if handler is None:
            raise ValueError(f"unknown verb in device.yaml: {verb}")

        rect = (x_cursor, btn_y, btn_w, btn_h)

        boxes.append(
            _box(
                _btn_box_id(btn_id),
                "live.text",
                rect,
                presentation=True,
                presentation_rect=rect,
                numinlets=1,
                numoutlets=2,
                outlettype=["", ""],
                extras={
                    "varname": btn_id,
                    # live.text mode 1 = momentary button. The button emits its
                    # label (a symbol) on click — we trigger-bang downstream.
                    "mode": 1,
                    "text": label,
                    "fontname": "Ableton Sans Medium",
                    "fontsize": 10.0,
                    "textcolor": palette["text"],
                    "activebgcolor": palette["accent"],
                    "bgcolor": palette["panel"],
                    "activebgoncolor": palette["accent"],
                    "bgoncolor": palette["panel"],
                    "bordercolor": palette["panel"],
                    "activebordercolor": palette["accent"],
                    "activebordercoloroff": palette["panel"],
                    "rounded": 6.0,
                    "parameter_enable": 0,
                },
            )
        )

        # [t b] — converts the button's symbol output into a bang (pitfall #17).
        boxes.append(
            _box(
                _btn_tb_id(btn_id),
                "newobj",
                (x_cursor, btn_y + btn_h + 4.0, 40.0, 22.0),
                numinlets=1,
                numoutlets=1,
                outlettype=["bang"],
                extras={"text": "t b"},
            )
        )

        # Message box that names the JS handler — bang fires it, then the
        # [js] runs the corresponding function.
        boxes.append(
            _box(
                _btn_msg_id(btn_id),
                "message",
                (x_cursor, btn_y + btn_h + 30.0, 96.0, 22.0),
                numinlets=2,
                numoutlets=1,
                outlettype=[""],
                extras={"text": handler},
            )
        )

        lines.append(_line(_btn_box_id(btn_id), 0, _btn_tb_id(btn_id), 0))
        lines.append(_line(_btn_tb_id(btn_id), 0, _btn_msg_id(btn_id), 0))

        x_cursor += btn_w + btn_gap

    # ── Status indicator (live.text dot) ────────────────────────────────────
    dot_cfg = ui["status"]["indicator"]
    dot_rect = (
        float(dot_cfg["pos"]["x"]),
        float(dot_cfg["pos"]["y"]),
        float(dot_cfg["size"]["width"]),
        float(dot_cfg["size"]["height"]),
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
                "mode": 0,
                "text": "",
                "bgcolor": palette["dot_warn"],
                "activebgcolor": palette["dot_warn"],
                "bgoncolor": palette["dot_warn"],
                "activebgoncolor": palette["dot_warn"],
                "bordercolor": palette["dot_warn"],
                "activebordercolor": palette["dot_warn"],
                "activebordercoloroff": palette["dot_warn"],
                "rounded": 16.0,
                "fontsize": 1.0,
                "parameter_enable": 0,
            },
        )
    )

    txt_cfg = ui["status"]["text"]
    txt_rect = (
        float(txt_cfg["pos"]["x"]),
        float(txt_cfg["pos"]["y"]),
        float(txt_cfg["size"]["width"]),
        float(txt_cfg["size"]["height"]),
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
                "text": "checking…",
                "fontname": "Ableton Sans Medium",
                "fontsize": 9.0,
                "textcolor": palette["dim"],
                "parameter_enable": 0,
            },
        )
    )

    footer_cfg = ui["status"]["footer"]
    footer_rect = (
        float(footer_cfg["pos"]["x"]),
        float(footer_cfg["pos"]["y"]),
        float(footer_cfg["size"]["width"]),
        float(footer_cfg["size"]["height"]),
    )
    boxes.append(
        _box(
            OBJ_FOOTER_TEXT,
            "live.comment",
            footer_rect,
            presentation=True,
            presentation_rect=footer_rect,
            numinlets=1,
            numoutlets=0,
            extras={
                "varname": footer_cfg["id"],
                "text": "starting…",
                "fontname": "Ableton Sans Medium",
                "fontsize": 9.0,
                "textcolor": palette["dim"],
                "parameter_enable": 0,
            },
        )
    )

    ver_cfg = ui["status"]["version_text"]
    ver_rect = (
        float(ver_cfg["pos"]["x"]),
        float(ver_cfg["pos"]["y"]),
        float(ver_cfg["size"]["width"]),
        float(ver_cfg["size"]["height"]),
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
                "text": f"v{device_cfg.get('version', '0.1.0')}",
                "fontname": "Ableton Sans Medium",
                "fontsize": 9.0,
                "textcolor": palette["dim"],
                "parameter_enable": 0,
            },
        )
    )

    # ── [js sf_configurator.js] — operations dispatcher ─────────────────────
    js_filename = js_cfg["filename"]
    js_scripting = js_cfg["scripting_name"]
    js_numoutlets = int(js_cfg["numoutlets"])
    boxes.append(
        _box(
            OBJ_JS,
            "newobj",
            (16.0, 200.0, 280.0, 22.0),
            numinlets=1,
            numoutlets=js_numoutlets,
            outlettype=[""] * js_numoutlets,
            extras={
                "text": f"js {js_filename} @scripting_name {js_scripting}",
                "saved_object_attributes": {
                    "filename": js_filename,
                    "parameter_enable": 0,
                },
            },
        )
    )

    # Wire each button's message → JS inlet 0.
    for btn in btn_items:
        lines.append(_line(_btn_msg_id(btn["id"]), 0, OBJ_JS, 0))

    # ── Loadbang → JS (boot-time port discovery) ────────────────────────────
    boxes.append(
        _box(
            OBJ_LOADBANG,
            "newobj",
            (16.0, 170.0, 60.0, 22.0),
            numinlets=1,
            numoutlets=1,
            outlettype=["bang"],
            extras={"text": "loadbang"},
        )
    )
    # Loadbang fires the bare bang into the JS — sf_configurator.bang()
    # calls discoverPort().
    lines.append(_line(OBJ_LOADBANG, 0, OBJ_JS, 0))

    # ── JS outlets routed to UI + shell + jweb ──────────────────────────────
    # outlet 0 → status_text   (set <text>)
    # outlet 1 → footer_text
    # outlet 2 → status_dot    (bgcolor r g b a)
    # outlet 3 → jweb          (openurl <url>)
    # outlet 4 → shell         (exec <cmd>)
    #
    # We use [prepend set] for live.comment text targets so a bare string
    # becomes `set <string>`. Status dot accepts `bgcolor r g b a` directly.
    obj_prep_status = "obj-prep-status"
    obj_prep_footer = "obj-prep-footer"
    boxes.append(
        _box(
            obj_prep_status,
            "newobj",
            (16.0, 240.0, 90.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend set"},
        )
    )
    boxes.append(
        _box(
            obj_prep_footer,
            "newobj",
            (120.0, 240.0, 90.0, 22.0),
            numinlets=2,
            numoutlets=1,
            outlettype=[""],
            extras={"text": "prepend set"},
        )
    )
    lines.append(_line(OBJ_JS, 0, obj_prep_status, 0))
    lines.append(_line(obj_prep_status, 0, OBJ_STATUS_TEXT, 0))
    lines.append(_line(OBJ_JS, 1, obj_prep_footer, 0))
    lines.append(_line(obj_prep_footer, 0, OBJ_FOOTER_TEXT, 0))
    lines.append(_line(OBJ_JS, 2, OBJ_STATUS_DOT, 0))

    # ── [jweb] — popup window. Phase 3 = float window (see device.yaml). ────
    jweb_w = float(jweb_cfg["size"]["width"])
    jweb_h = float(jweb_cfg["size"]["height"])
    boxes.append(
        _box(
            OBJ_JWEB,
            "jweb",
            (300.0, 200.0, jweb_w, jweb_h),
            numinlets=1,
            numoutlets=1,
            outlettype=[""],
            extras={
                # Empty url at boot — `openurl` message fills it in when the
                # user clicks Open Editor. The patcher-area rect is large so
                # an opening developer can see the embedded view; in production
                # users will see the float window (Open Editor uses openurl).
                "url": "about:blank",
                "parameter_enable": 0,
            },
        )
    )
    lines.append(_line(OBJ_JS, 3, OBJ_JWEB, 0))

    # ── [shell] — curl + start-server commands ──────────────────────────────
    boxes.append(
        _box(
            OBJ_SHELL,
            "newobj",
            (320.0, 170.0, 80.0, 22.0),
            numinlets=1,
            numoutlets=2,
            outlettype=["", "bang"],
            extras={"text": "shell"},
        )
    )
    lines.append(_line(OBJ_JS, 4, OBJ_SHELL, 0))

    # ── Final patcher dict ──────────────────────────────────────────────────
    device_width = float(ui["size"]["width"])
    device_height = float(ui["size"]["height"])
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
            "rect": [40.0, 96.0, 40.0 + device_width, 96.0 + device_height + 100.0],
            "openinpresentation": 1,
            "default_fontsize": 11.0,
            "default_fontname": "Ableton Sans Medium",
            "gridsize": [8.0, 8.0],
            "devicewidth": device_width,
            "description": (
                f"{device_cfg.get('name', 'ConfiguratorStrip')} — "
                "Phase 3 thin operations strip. Talks to local HTTP server "
                f"via {server_cfg['intent_path_format']}."
            ),
            "boxes": boxes,
            "lines": lines,
            "project": {
                "version": 1,
                "creationdate": 3590052493,
                "modificationdate": 3590052493,
                "viewrect": [0.0, 0.0, device_width, device_height],
                "autoorganize": 1,
                "hideprojectwindow": 1,
                "showdependencies": 1,
                "autolocalize": 0,
                "contents": {"patchers": {}, "code": {}},
                "layout": {},
                "searchpath": {},
                "detailsvisible": 0,
                # 1633771873 = 0x61616161 = b'aaaa' = audio effect.
                # Must match the amxd sentinel at offset 8 — pitfall #14.
                "amxdtype": 1633771873,
                "readonly": 0,
                "devpathtype": 0,
                "devpath": ".",
                "sortmode": 0,
                "viewmode": 0,
                "includepackages": 0,
            },
            "dependency_cache": [
                {
                    "name": js_filename,
                    # The JS ships in StemForge's Max Package javascript/
                    # path (same convention as the big device). When the
                    # strip's installer runs it copies sf_configurator.js
                    # into ~/Documents/Max 9/Packages/StemForge/javascript/.
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
                    "type": "TEXT",
                    "implicit": 1,
                },
            ],
            "autosave": 0,
        }
    }
    return patcher


# ── CLI entrypoint ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    HERE = Path(__file__).resolve().parent
    DEFAULT_YAML = HERE / "device.yaml"
    DEFAULT_OUT = HERE.parents[2] / "build" / "ConfiguratorStrip.maxpat"

    ap = argparse.ArgumentParser(description="Build the Configurator Strip .maxpat")
    ap.add_argument("--device-yaml", default=str(DEFAULT_YAML))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    patch = build_patcher(args.device_yaml)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(patch, indent="\t"))
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
