"""EP-133 .ppak byte builder.

TODO: this is a placeholder authored by Track C while Track A is in flight.
Track A owns this file per ``docs/exec-plans/ep133-song-export.md`` — once it
lands, delete this stub and use the canonical implementation. The signature
must remain ``build_ppak(spec, reference_template) -> bytes``.

The stub returns a deterministic byte blob that includes a JSON dump of the
spec so a CLI smoke test can verify end-to-end wiring. It is NOT a valid
``.ppak`` and will not boot on the device.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .song_format import PpakSpec


_STUB_MAGIC = b"STEMFORGE_PPAK_STUB_V0\n"


def build_ppak(spec: PpakSpec, reference_template: Path | bytes | None = None) -> bytes:
    """Placeholder writer. Returns a marker-prefixed JSON dump of the spec.

    Real implementation (Track A) returns ZIP bytes containing
    ``/meta.json`` + ``/projects/PXX.tar``.
    """
    payload = {
        "project_slot": spec.project_slot,
        "bpm": spec.bpm,
        "time_sig": list(spec.time_sig),
        "pattern_count": len(spec.patterns),
        "scene_count": len(spec.scenes),
        "pad_count": len(spec.pads),
        "sound_slots": sorted(spec.sounds.keys()),
        "patterns": [
            {
                "group": p.group,
                "index": p.index,
                "bars": p.bars,
                "events": [asdict(e) for e in p.events],
            }
            for p in spec.patterns
        ],
        "scenes": [asdict(s) for s in spec.scenes],
        "pads": [asdict(p) for p in spec.pads],
    }
    return _STUB_MAGIC + json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
