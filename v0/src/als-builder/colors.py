"""Ableton Live 12 track color palette.

Live uses a fixed 70-color palette indexed 0-69. A track's `ColorIndex/Value`
element stores the integer index; the hex shown in the UI is a lookup.

The table below is the commonly-circulated reverse-engineered palette as
rendered by Live 12.1.x. If a user-observed value differs, prefer the value
Live writes when it saves a set (see `v0/assets/README.md` for provenance).

Entry 0 is the default grey-white Live assigns to new tracks.
"""

from __future__ import annotations

# Hex color per palette index. 70 entries (0-69).
# Source: reverse-engineered from Live 12 default set. See assets/README.md.
PALETTE_HEX: list[str] = [
    "#FF94A6",  # 0  - pink
    "#FFA529",  # 1  - orange
    "#CC9927",  # 2  - dark orange
    "#F7F47C",  # 3  - pale yellow
    "#BFFB00",  # 4  - lime
    "#1AFF2F",  # 5  - green
    "#25FFA8",  # 6  - mint
    "#5CFFE8",  # 7  - cyan
    "#8BC5FF",  # 8  - light blue
    "#5480E4",  # 9  - blue
    "#92A7FF",  # 10 - lavender
    "#D86CE4",  # 11 - magenta
    "#E553A0",  # 12 - hot pink
    "#FFFFFF",  # 13 - white
    "#FF3636",  # 14 - red
    "#F66C03",  # 15 - dark orange
    "#99724B",  # 16 - brown
    "#FFF034",  # 17 - yellow
    "#87FF67",  # 18 - light green
    "#3DC300",  # 19 - darker green
    "#00BFAF",  # 20 - teal
    "#19E9FF",  # 21 - bright cyan
    "#10A4EE",  # 22 - azure
    "#007DC0",  # 23 - deep blue
    "#886CE4",  # 24 - purple
    "#B677C6",  # 25 - pink-purple
    "#FF39D4",  # 26 - fuchsia
    "#D0D0D0",  # 27 - light grey
    "#E2675A",  # 28 - coral
    "#FFA374",  # 29 - peach
    "#D3A465",  # 30 - tan
    "#DCB172",  # 31 - gold
    "#BAB979",  # 32 - olive
    "#A6BE00",  # 33 - yellow green
    "#7DB04D",  # 34 - sage
    "#88C2BA",  # 35 - seafoam
    "#9BC3E0",  # 36 - sky
    "#B6BBD0",  # 37 - periwinkle
    "#A9AABF",  # 38 - lilac
    "#B98FBD",  # 39 - mauve
    "#BE97B3",  # 40 - rose
    "#FFC6AD",  # 41 - peach light
    "#D4BBAC",  # 42 - beige
    "#BBB99E",  # 43 - khaki
    "#EDFFAE",  # 44 - pale lime
    "#D3E89C",  # 45 - pale green
    "#BAD18E",  # 46 - spring green
    "#BAD6C1",  # 47 - pale teal
    "#B0E3E3",  # 48 - pale cyan
    "#B4C0D1",  # 49 - slate
    "#AEB6C8",  # 50 - steel blue
    "#BDB2DE",  # 51 - pale purple
    "#C8B8CA",  # 52 - dusty pink
    "#B682A5",  # 53 - mulberry
    "#C58F8A",  # 54 - dusty red
    "#A0A0A0",  # 55 - mid grey
    "#8E4B41",  # 56 - brick
    "#945F44",  # 57 - dark brown
    "#7F6C38",  # 58 - olive dark
    "#847A5B",  # 59 - army
    "#4E632B",  # 60 - forest
    "#437B5F",  # 61 - deep teal
    "#255778",  # 62 - navy
    "#2F3F7F",  # 63 - indigo
    "#5E58A6",  # 64 - violet
    "#7854C5",  # 65 - deep purple
    "#6B4A67",  # 66 - plum
    "#9B305A",  # 67 - wine
    "#666666",  # 68 - dark grey
    "#333333",  # 69 - near black
]

assert len(PALETTE_HEX) == 70, "Live palette must have exactly 70 entries"


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hex_to_color_index(target_hex: str) -> int:
    """Map an arbitrary hex RGB color to the nearest Live palette index.

    Uses squared Euclidean distance in RGB space. Adequate for v0; a
    perceptual (CIEDE2000) distance would be marginally better but adds
    a dependency for minimal gain in a 70-color palette.
    """
    tr, tg, tb = _hex_to_rgb(target_hex)
    best_idx = 0
    best_dist = float("inf")
    for idx, phex in enumerate(PALETTE_HEX):
        pr, pg, pb = _hex_to_rgb(phex)
        d = (pr - tr) ** 2 + (pg - tg) ** 2 + (pb - tb) ** 2
        if d < best_dist:
            best_dist = d
            best_idx = idx
    return best_idx
