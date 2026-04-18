"""Tests for colors.py — palette + hex→index nearest-neighbor mapping."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from colors import PALETTE_HEX, hex_to_color_index  # noqa: E402


def test_palette_is_70_entries():
    assert len(PALETTE_HEX) == 70


def test_exact_match_returns_same_index():
    # Feeding the palette's own hex back in should round-trip.
    for idx, h in enumerate(PALETTE_HEX):
        assert hex_to_color_index(h) == idx, f"idx {idx} ({h}) did not round-trip"


def test_tracks_yaml_colors_all_resolve():
    # The 7 tracks.yaml colors must all map to *some* palette index.
    colors = [
        "#FF4444",
        "#882222",
        "#4477FF",
        "#44DD77",
        "#44CCCC",
        "#FFAA44",
        "#FF4444",
        "#888888",
    ]
    for c in colors:
        idx = hex_to_color_index(c)
        assert 0 <= idx < 70


def test_bright_red_maps_to_a_red_bucket():
    # #FF4444 is a vivid red — it should land on an obviously red palette slot.
    idx = hex_to_color_index("#FF4444")
    hex_hit = PALETTE_HEX[idx]
    r, g, b = (int(hex_hit.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    assert r > g and r > b, f"expected red-dominant, got {hex_hit}"
