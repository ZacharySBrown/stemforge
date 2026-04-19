"""
stemforge.layout — Pad layout engines for Launchpad / Push grid mapping.

Maps curated loops, one-shots, and chromatic samples to pad indices
within a quadrant grid. Computes LED colors from spectral data.

Layout modes:
  - StemsLayout: 4 quadrants (4×4 each), loops top + one-shots bottom
  - DJLayout: base loop + sub-loops + one-shots + combos per quadrant
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import CurationConfig, StemCurationConfig, STEM_COLORS


# ── Quadrant assignments ────────────────────────────────────────────────

QUADRANT_MAP = {
    "drums":  "top_left",
    "bass":   "top_right",
    "vocals": "bottom_left",
    "other":  "bottom_right",
}

# MIDI note base per quadrant (Drum Rack standard: C1=36 for visible 4×4)
QUADRANT_MIDI_BASE = 36  # all quadrants use 36-51, differentiated by MIDI channel

# Drum Rack pad layout within a 4×4 quadrant (index 0-15):
#   Row 3 (top):    pads 12, 13, 14, 15   ← loops 1-4
#   Row 2:          pads  8,  9, 10, 11   ← loops 5-8
#   Row 1:          pads  4,  5,  6,  7   ← one-shots (snare, hat_c, hat_o, perc)
#   Row 0 (bottom): pads  0,  1,  2,  3   ← one-shots (kick, kick2, perc, perc)
#
# Note: Drum Rack pad indexing goes bottom-to-top, left-to-right
# (MIDI note 36=bottom-left, 39=bottom-right, 40=second-row-left, etc.)

LOOP_PAD_INDICES = [12, 13, 14, 15, 8, 9, 10, 11]  # top 2 rows
ONESHOT_PAD_INDICES = [4, 5, 6, 7, 0, 1, 2, 3]      # bottom 2 rows

# Drum-specific pad assignment (kick bottom-left, snare above, hats right of snare)
DRUM_PAD_MAP = {
    # Bottom row: kick left, perc right
    "kick":       [0, 1],
    "perc":       [2, 3],
    # Top row of one-shots: snare left, hats right
    "snare":      [4],
    "clap":       [4],     # clap shares snare slot if no snare
    "hat_closed": [5],
    "hat_open":   [6],
    "rim":        [7],
}


@dataclass
class PadAssignment:
    """One pad in the grid."""
    pad_index: int              # 0-15 within the quadrant
    midi_note: int              # MIDI note for Drum Rack (36-51)
    pad_type: str               # "loop" | "oneshot" | "chromatic" | "midi_clip" | "empty"
    file: str | None = None     # path to WAV file
    label: str = ""             # display label (e.g., "kick", "loop 3", "C2")
    loop: bool = False          # Simpler loop mode
    classification: str = ""    # drum hit type (kick, snare, hat, etc.)
    spectral_centroid: float = 0.0
    led_color: tuple[int, int, int] = (64, 64, 64)  # RGB


@dataclass
class QuadrantLayout:
    """Layout for one stem's 4×4 quadrant."""
    stem_name: str
    quadrant: str               # top_left, top_right, bottom_left, bottom_right
    midi_channel: int           # 1-4
    pads: list[PadAssignment] = field(default_factory=list)
    track_template: str = ""    # template track name in tracks.yaml


@dataclass
class FullGridLayout:
    """Complete 8×8 Launchpad layout."""
    layout_mode: str            # "stems" | "dj"
    quadrants: dict[str, QuadrantLayout] = field(default_factory=dict)
    bpm: float = 120.0
    track_name: str = ""


# ── Color computation ────────────────────────────────────────────────────

def _stem_base_color(stem_name: str) -> tuple[int, int, int]:
    """Get base RGB color for a stem."""
    hex_color = STEM_COLORS.get(stem_name, 0x888888)
    r = (hex_color >> 16) & 0xFF
    g = (hex_color >> 8) & 0xFF
    b = hex_color & 0xFF
    return (r, g, b)


def spectral_to_led_color(
    stem_name: str,
    spectral_centroid: float,
    max_centroid: float = 10000.0,
) -> tuple[int, int, int]:
    """
    Compute LED color from stem base color modulated by spectral brightness.

    Low centroid (warm) → saturated stem color
    High centroid (bright) → whitened stem color
    """
    base_r, base_g, base_b = _stem_base_color(stem_name)
    brightness = min(spectral_centroid / max_centroid, 1.0)

    # Blend toward white as brightness increases
    r = int(base_r + (255 - base_r) * brightness * 0.5)
    g = int(base_g + (255 - base_g) * brightness * 0.5)
    b = int(base_b + (255 - base_b) * brightness * 0.5)

    return (min(r, 255), min(g, 255), min(b, 255))


# ── Stems Layout ─────────────────────────────────────────────────────────

def build_stems_layout(
    curated_manifest: dict,
    config: CurationConfig,
) -> FullGridLayout:
    """
    Build the quadrant layout from a curated manifest.

    Each stem gets a 4×4 quadrant:
      - Top 2 rows (8 pads): loops
      - Bottom 2 rows (8 pads): one-shots
      - Drums: one-shots laid out in drum rack pattern

    Args:
        curated_manifest: The v2 curated manifest dict
        config: Curation config for per-stem settings

    Returns:
        FullGridLayout with 4 quadrants
    """
    grid = FullGridLayout(
        layout_mode="stems",
        bpm=curated_manifest.get("bpm", 120.0),
        track_name=curated_manifest.get("track", ""),
    )

    stem_order = ["drums", "bass", "vocals", "other"]
    midi_channels = {"drums": 1, "bass": 2, "vocals": 3, "other": 4}

    for stem_name in stem_order:
        stem_data = curated_manifest.get("stems", {}).get(stem_name)
        if stem_data is None:
            continue

        sc = config.for_stem(stem_name)
        quadrant_pos = QUADRANT_MAP.get(stem_name, "top_left")
        midi_ch = midi_channels.get(stem_name, 1)

        quadrant = QuadrantLayout(
            stem_name=stem_name,
            quadrant=quadrant_pos,
            midi_channel=midi_ch,
            track_template=f"SF | {stem_name.capitalize()} Rack",
        )

        # Initialize 16 empty pads
        pads: list[PadAssignment] = [
            PadAssignment(
                pad_index=i,
                midi_note=QUADRANT_MIDI_BASE + i,
                pad_type="empty",
            )
            for i in range(16)
        ]

        # Assign loops to top 2 rows
        if isinstance(stem_data, list):
            # v1 manifest format: flat list of bars
            loops = stem_data
            oneshots = []
        elif isinstance(stem_data, dict):
            # v2 manifest format: separate loops/oneshots
            loops = stem_data.get("loops", stem_data.get("bars", []))
            oneshots = stem_data.get("oneshots", [])
        else:
            loops = []
            oneshots = []

        for li, loop in enumerate(loops[:len(LOOP_PAD_INDICES)]):
            pad_idx = LOOP_PAD_INDICES[li]
            file_path = loop.get("file", "")
            centroid = loop.get("spectral", {}).get("centroid_hz", 0) if isinstance(loop.get("spectral"), dict) else 0

            pads[pad_idx] = PadAssignment(
                pad_index=pad_idx,
                midi_note=QUADRANT_MIDI_BASE + pad_idx,
                pad_type="loop",
                file=file_path,
                label=f"loop {li + 1}",
                loop=True,
                spectral_centroid=centroid,
                led_color=spectral_to_led_color(stem_name, centroid),
            )

        # Assign one-shots to bottom 2 rows
        if stem_name == "drums" and sc.oneshot_mode == "classify":
            # Drum-specific layout: kick bottom-left, snare above, hats right
            _assign_drum_oneshots(pads, oneshots, stem_name)
        else:
            # Generic: fill bottom 2 rows in order
            for oi, os in enumerate(oneshots[:len(ONESHOT_PAD_INDICES)]):
                pad_idx = ONESHOT_PAD_INDICES[oi]
                file_path = os.get("file", "")
                centroid = os.get("spectral", {}).get("centroid_hz", 0) if isinstance(os.get("spectral"), dict) else 0
                classification = os.get("classification", "")

                pads[pad_idx] = PadAssignment(
                    pad_index=pad_idx,
                    midi_note=QUADRANT_MIDI_BASE + pad_idx,
                    pad_type="oneshot",
                    file=file_path,
                    label=classification or f"os {oi + 1}",
                    loop=False,
                    classification=classification,
                    spectral_centroid=centroid,
                    led_color=spectral_to_led_color(stem_name, centroid),
                )

        quadrant.pads = pads
        grid.quadrants[stem_name] = quadrant

    return grid


def _assign_drum_oneshots(
    pads: list[PadAssignment],
    oneshots: list[dict],
    stem_name: str,
) -> None:
    """Assign drum one-shots to pads using the standard drum layout."""
    # Group by classification
    by_type: dict[str, list[dict]] = {}
    for os in oneshots:
        cls = os.get("classification", "perc")
        by_type.setdefault(cls, []).append(os)

    # Fill pads according to DRUM_PAD_MAP
    assigned_pads: set[int] = set()

    for cls, pad_indices in DRUM_PAD_MAP.items():
        hits = by_type.get(cls, [])
        for i, pad_idx in enumerate(pad_indices):
            if pad_idx in assigned_pads or i >= len(hits):
                continue
            hit = hits[i]
            file_path = hit.get("file", "")
            centroid = hit.get("spectral", {}).get("centroid_hz", 0) if isinstance(hit.get("spectral"), dict) else 0

            pads[pad_idx] = PadAssignment(
                pad_index=pad_idx,
                midi_note=QUADRANT_MIDI_BASE + pad_idx,
                pad_type="oneshot",
                file=file_path,
                label=cls,
                loop=False,
                classification=cls,
                spectral_centroid=centroid,
                led_color=spectral_to_led_color(stem_name, centroid),
            )
            assigned_pads.add(pad_idx)

    # Fill remaining empty one-shot pads with unassigned hits
    remaining_hits = [
        os for os in oneshots
        if os.get("file", "") not in {pads[i].file for i in assigned_pads if pads[i].file}
    ]
    empty_os_pads = [i for i in ONESHOT_PAD_INDICES if i not in assigned_pads]

    for pad_idx, hit in zip(empty_os_pads, remaining_hits):
        file_path = hit.get("file", "")
        cls = hit.get("classification", "perc")
        pads[pad_idx] = PadAssignment(
            pad_index=pad_idx,
            midi_note=QUADRANT_MIDI_BASE + pad_idx,
            pad_type="oneshot",
            file=file_path,
            label=cls,
            loop=False,
            classification=cls,
            led_color=spectral_to_led_color(stem_name, 0),
        )


# ── Layout serialization ─────────────────────────────────────────────────

def layout_to_manifest(grid: FullGridLayout) -> dict:
    """Convert a FullGridLayout to a manifest-compatible dict for the loader."""
    result = {
        "version": 2,
        "layout_mode": grid.layout_mode,
        "bpm": grid.bpm,
        "track": grid.track_name,
        "quadrants": {},
    }

    for stem_name, quadrant in grid.quadrants.items():
        q = {
            "quadrant": quadrant.quadrant,
            "midi_channel": quadrant.midi_channel,
            "track_template": quadrant.track_template,
            "pads": [],
        }
        for pad in quadrant.pads:
            q["pads"].append({
                "pad_index": pad.pad_index,
                "midi_note": pad.midi_note,
                "type": pad.pad_type,
                "file": pad.file,
                "label": pad.label,
                "loop": pad.loop,
                "classification": pad.classification,
                "led_color": list(pad.led_color),
            })
        result["quadrants"][stem_name] = q

    return result


def print_grid(grid: FullGridLayout) -> str:
    """Pretty-print the 8×8 grid layout for debugging."""
    lines = [f"=== {grid.track_name} ({grid.bpm:.0f} BPM) — {grid.layout_mode} mode ===\n"]

    # Print quadrants side by side: top_left | top_right, then bottom_left | bottom_right
    for row_pair in [("drums", "bass"), ("vocals", "other")]:
        left = grid.quadrants.get(row_pair[0])
        right = grid.quadrants.get(row_pair[1])

        for row in range(3, -1, -1):  # top to bottom
            left_str = ""
            right_str = ""
            for col in range(4):
                pad_idx = row * 4 + col

                if left and pad_idx < len(left.pads):
                    p = left.pads[pad_idx]
                    left_str += f"[{p.label:8s}]"
                else:
                    left_str += "[        ]"

                if right and pad_idx < len(right.pads):
                    p = right.pads[pad_idx]
                    right_str += f"[{p.label:8s}]"
                else:
                    right_str += "[        ]"

            lines.append(f"  {left_str}  |  {right_str}")

        lines.append(f"  {'─' * 44}{'┼'}{'─' * 44}")

    return "\n".join(lines)
