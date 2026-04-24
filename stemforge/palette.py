"""Ableton-native color palette resolution for StemForge preset compilation.

Resolves YAML `color: red` / `color: 14` / `color: "#RRGGBB"` into a rich
object `{name, index, hex}` that both the M4L v8ui renderer (via hex) and
LiveAPI track coloring (via index) can consume.

See specs/stemforge_device_ui_spec_LATEST.md §12 for design rationale.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_PALETTE_FILE = _HERE / "data" / "ableton_colors.json"


@lru_cache(maxsize=1)
def _load_palette() -> list[dict[str, Any]]:
    with _PALETTE_FILE.open() as f:
        palette = json.load(f)
    if len(palette) != 26:
        raise ValueError(
            f"ableton_colors.json must have exactly 26 entries, got {len(palette)}"
        )
    return palette


def _by_name() -> dict[str, dict[str, Any]]:
    return {e["name"]: e for e in _load_palette()}


def _by_index() -> dict[int, dict[str, Any]]:
    return {e["index"]: e for e in _load_palette()}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _nearest_by_hex(hex_str: str) -> dict[str, Any]:
    target = _hex_to_rgb(hex_str)
    best = None
    best_d = 10**9
    for entry in _load_palette():
        r, g, b = _hex_to_rgb(entry["hex"])
        d = (r - target[0]) ** 2 + (g - target[1]) ** 2 + (b - target[2]) ** 2
        if d < best_d:
            best_d = d
            best = entry
    assert best is not None
    return best


def resolve_color(value: str | int | dict[str, Any]) -> dict[str, Any]:
    """Normalize a color spec to `{name, index, hex}`.

    Accepts:
      - ``str`` starting with ``"#"`` — raw hex; snaps to nearest Ableton color
        with a ``name=None`` marker.
      - ``str`` that is a palette name (e.g. ``"red"``) — exact lookup.
      - ``int`` — palette index 0..25.
      - ``dict`` already in normalized form — returned as-is (idempotent).
    """
    if isinstance(value, dict):
        if "index" in value and "hex" in value:
            return dict(value)
        raise ValueError(f"malformed color dict: {value!r}")

    if isinstance(value, int):
        entry = _by_index().get(value)
        if entry is None:
            raise ValueError(f"color index {value} out of range 0..25")
        return dict(entry)

    if isinstance(value, str):
        if value.startswith("#"):
            entry = _nearest_by_hex(value)
            return {"name": None, "index": entry["index"], "hex": value.upper()}
        entry = _by_name().get(value)
        if entry is None:
            valid = ", ".join(sorted(_by_name().keys()))
            raise ValueError(
                f"unknown palette color '{value}' — valid names: {valid}"
            )
        return dict(entry)

    raise TypeError(f"unsupported color type: {type(value).__name__}")


def resolve_preset(preset: dict[str, Any]) -> dict[str, Any]:
    """Walk a preset dict and resolve every `color` to the rich form.

    Non-destructive: returns a new dict. Top-level fields are preserved;
    only per-target `color` values are normalized.
    """
    out = dict(preset)
    stems = out.get("stems") or {}
    new_stems: dict[str, Any] = {}
    for stem_name, stem in stems.items():
        new_stem = dict(stem)
        targets = new_stem.get("targets") or []
        new_targets = []
        for t in targets:
            nt = dict(t)
            if "color" in nt:
                nt["color"] = resolve_color(nt["color"])
            new_targets.append(nt)
        new_stem["targets"] = new_targets
        new_stems[stem_name] = new_stem
    out["stems"] = new_stems

    # Enrich with display metadata used by the M4L device.
    out.setdefault("displayName", out.get("name", "").replace("_", " ").title())
    out.setdefault("version", "1.0.0")
    return out


def palette_preview(preset: dict[str, Any], limit: int = 6) -> list[str]:
    """Pick up to `limit` representative hex colors across a preset's stems.

    Used for the M4L PresetRef.palettePreview strip in the left column.
    Grabs the first target color from each stem in insertion order.
    """
    out: list[str] = []
    for stem in (preset.get("stems") or {}).values():
        targets = stem.get("targets") or []
        if not targets:
            continue
        c = targets[0].get("color")
        if isinstance(c, dict) and c.get("hex"):
            out.append(c["hex"])
        elif isinstance(c, str) and c.startswith("#"):
            out.append(c.upper())
        if len(out) >= limit:
            break
    return out


def target_count(preset: dict[str, Any]) -> int:
    return sum(
        len(stem.get("targets") or [])
        for stem in (preset.get("stems") or {}).values()
    )
