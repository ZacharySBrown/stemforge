"""
receiver_builder — Generate tiny M4L MIDI Effect receivers for quadrant routing.

Each Drum Rack track gets one of these. It receives MIDI from the
router via a named [receive] object and outputs to the track's MIDI chain.

Generates 4 receivers: sf_q_drums, sf_q_bass, sf_q_vocals, sf_q_other.
"""

from __future__ import annotations

import json
from pathlib import Path


def _box(obj_id, maxclass, rect, *, numinlets=1, numoutlets=0,
         outlettype=None, extras=None):
    body = {
        "id": obj_id, "maxclass": maxclass,
        "numinlets": numinlets, "numoutlets": numoutlets,
        "patching_rect": list(rect),
    }
    if outlettype:
        body["outlettype"] = outlettype
    if extras:
        body.update(extras)
    return {"box": body}


def _line(src_id, src_outlet, dst_id, dst_inlet):
    return {"patchline": {"source": [src_id, src_outlet], "destination": [dst_id, dst_inlet]}}


def build_receiver(stem_name: str) -> dict:
    send_name = f"sf_q_{stem_name}"
    boxes = []
    lines = []

    # Receive note events as "note <pitch> <velocity>" messages
    boxes.append(_box(
        "obj-recv", "newobj", (20, 20, 120, 22),
        numinlets=0, numoutlets=1, outlettype=[""],
        extras={"text": f"receive {send_name}"},
    ))

    # midiformat converts "note pitch velocity" to raw MIDI bytes
    boxes.append(_box(
        "obj-midiformat", "newobj", (20, 50, 100, 22),
        numinlets=6, numoutlets=1, outlettype=["int"],
        extras={"text": "midiformat"},
    ))
    lines.append(_line("obj-recv", 0, "obj-midiformat", 0))

    # midiout sends properly formatted MIDI downstream to the Drum Rack
    boxes.append(_box(
        "obj-midiout", "newobj", (20, 80, 80, 22),
        numinlets=1, numoutlets=0,
        extras={"text": "midiout"},
    ))
    lines.append(_line("obj-midiformat", 0, "obj-midiout", 0))

    return {
        "patcher": {
            "fileversion": 1,
            "appversion": {"major": 9, "minor": 0, "revision": 8, "architecture": "x64", "modernui": 1},
            "classnamespace": "box",
            "rect": [100, 100, 300, 150],
            "openinpresentation": 0,
            "default_fontsize": 11.0,
            "gridsize": [8.0, 8.0],
            "boxes": boxes,
            "lines": lines,
            "project": {
                "version": 1, "creationdate": 3590052493, "modificationdate": 3590052493,
                "viewrect": [0, 0, 300, 500], "autoorganize": 1, "hideprojectwindow": 1,
                "showdependencies": 1, "autolocalize": 0,
                "contents": {"patchers": {}, "code": {}},
                "layout": {}, "searchpath": {}, "detailsvisible": 0,
                "amxdtype": 1835361645, "readonly": 0, "devpathtype": 0, "devpath": ".",
                # 1835361645 = 0x6D6D6D6D = b'mmmm' = MIDI effect
                "sortmode": 0, "viewmode": 0, "includepackages": 0,
            },
            "autosave": 0,
        }
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from amxd_pack import pack_amxd

    out_dir = Path("v0/build")
    out_dir.mkdir(parents=True, exist_ok=True)

    for stem in ["drums", "bass", "vocals", "other"]:
        patcher = build_receiver(stem)
        name = f"StemForgeRecv_{stem.capitalize()}"

        # Save as .maxpat for debugging
        maxpat_path = out_dir / f"{name}.maxpat"
        maxpat_path.write_text(json.dumps(patcher, indent="\t"))

        # Pack as .amxd for Ableton
        amxd_path = out_dir / f"{name}.amxd"
        pack_amxd(patcher, str(amxd_path), device_type=1, device_class="midi")

        # Install to MIDI Effects
        install_dir = Path.home() / "Music/Ableton/User Library/Presets/MIDI Effects/Max MIDI Effect"
        install_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(amxd_path, install_dir / f"{name}.amxd")

        print(f"  {name}: built + installed")
