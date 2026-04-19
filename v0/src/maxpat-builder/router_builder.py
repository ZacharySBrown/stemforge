"""
router_builder — Generate the MIDI Quadrant Router M4L device.

A MIDI Effect that routes an 8×8 controller grid into four 4×4 quadrants
on different MIDI channels, enabling 4 Drum Rack tracks to be played
simultaneously from one Launchpad/Push.

Output: a .maxpat that can be wrapped into a .amxd MIDI Effect.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _box(obj_id, maxclass, rect, *, numinlets=1, numoutlets=0,
         outlettype=None, extras=None):
    body = {
        "id": obj_id,
        "maxclass": maxclass,
        "numinlets": numinlets,
        "numoutlets": numoutlets,
        "patching_rect": list(rect),
    }
    if outlettype:
        body["outlettype"] = outlettype
    if extras:
        body.update(extras)
    return {"box": body}


def _line(src_id, src_outlet, dst_id, dst_inlet):
    return {
        "patchline": {
            "source": [src_id, src_outlet],
            "destination": [dst_id, dst_inlet],
        }
    }


def build_router_patcher() -> dict[str, Any]:
    """Build the MIDI Quadrant Router patcher."""
    boxes = []
    lines = []

    # --- MIDI input → JS router → MIDI output ---
    # Simple chain: midiin sends raw bytes to JS, JS remaps and outputs to midiout
    boxes.append(_box(
        "obj-midiin", "newobj", (20, 20, 80, 22),
        numinlets=1, numoutlets=1, outlettype=["int"],
        extras={"text": "midiin"},
    ))

    boxes.append(_box(
        "obj-router", "newobj", (20, 60, 280, 22),
        numinlets=1, numoutlets=1, outlettype=["int"],
        extras={
            "text": "js stemforge_quadrant_router.js",
            "saved_object_attributes": {
                "filename": "stemforge_quadrant_router.js",
                "parameter_enable": 0,
            },
        },
    ))
    lines.append(_line("obj-midiin", 0, "obj-router", 0))

    boxes.append(_box(
        "obj-midiout", "newobj", (20, 100, 80, 22),
        numinlets=1, numoutlets=0,
        extras={"text": "midiout"},
    ))
    lines.append(_line("obj-router", 0, "obj-midiout", 0))

    # --- Loadbang → colorize pads ---
    boxes.append(_box(
        "obj-loadbang", "newobj", (300, 20, 60, 22),
        numinlets=1, numoutlets=1, outlettype=["bang"],
        extras={"text": "loadbang"},
    ))
    boxes.append(_box(
        "obj-colorize-msg", "message", (300, 50, 60, 22),
        numinlets=2, numoutlets=1, outlettype=[""],
        extras={"text": "colorize"},
    ))
    lines.append(_line("obj-loadbang", 0, "obj-colorize-msg", 0))
    lines.append(_line("obj-colorize-msg", 0, "obj-router", 0))

    # --- Debug: test mapping ---
    boxes.append(_box(
        "obj-test-msg", "message", (300, 80, 40, 22),
        numinlets=2, numoutlets=1, outlettype=[""],
        extras={"text": "test"},
    ))
    lines.append(_line("obj-test-msg", 0, "obj-router", 0))

    # --- Diagnostic ---
    boxes.append(_box(
        "obj-diag", "newobj", (300, 110, 200, 22),
        numinlets=1, numoutlets=0,
        extras={"text": "print [QuadrantRouter-loaded]"},
    ))
    lines.append(_line("obj-loadbang", 0, "obj-diag", 0))

    patcher = {
        "patcher": {
            "fileversion": 1,
            "appversion": {
                "major": 9, "minor": 0, "revision": 8,
                "architecture": "x64", "modernui": 1,
            },
            "classnamespace": "box",
            "rect": [100, 100, 500, 300],
            "openinpresentation": 0,
            "default_fontsize": 11.0,
            "default_fontname": "Ableton Sans Medium",
            "gridsize": [8.0, 8.0],
            "boxes": boxes,
            "lines": lines,
            "dependency_cache": [
                {
                    "name": "stemforge_quadrant_router.js",
                    "bootpath": "~/Documents/Max 9/Packages/StemForge/javascript",
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

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="v0/build/stemforge-quadrant-router.maxpat")
    args = parser.parse_args()

    patch = build_router_patcher()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(patch, indent="\t"))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
