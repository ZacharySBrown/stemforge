"""Unit tests for stemforge.palette — Ableton-native color resolution."""

from __future__ import annotations

import json

import pytest

from stemforge.palette import (
    _load_palette,
    palette_preview,
    resolve_color,
    resolve_preset,
    target_count,
)


def test_palette_file_has_26_entries():
    palette = _load_palette()
    assert len(palette) == 26
    assert {e["index"] for e in palette} == set(range(26))


def test_resolve_color_by_name():
    c = resolve_color("red")
    assert c == {"index": 14, "name": "red", "hex": "#FF3A34"}


def test_resolve_color_by_index():
    c = resolve_color(9)
    assert c["name"] == "blue"
    assert c["hex"] == "#5480E4"


def test_resolve_color_by_hex_snaps_to_nearest():
    c = resolve_color("#FF4444")  # close to red (#FF3A34)
    assert c["index"] == 14
    assert c["hex"] == "#FF4444"  # original preserved
    assert c["name"] is None


def test_resolve_color_dict_passthrough():
    source = {"name": "custom", "index": 9, "hex": "#5480E4"}
    out = resolve_color(source)
    assert out == source
    assert out is not source  # copy


def test_resolve_color_rejects_unknown_name():
    with pytest.raises(ValueError):
        resolve_color("not_a_color")


def test_resolve_color_rejects_bad_index():
    with pytest.raises(ValueError):
        resolve_color(99)


def test_resolve_color_rejects_bad_type():
    with pytest.raises(TypeError):
        resolve_color(1.5)


def test_resolve_preset_walks_all_targets():
    preset = {
        "name": "test",
        "stems": {
            "drums": {
                "targets": [
                    {"name": "loops", "color": "red"},
                    {"name": "crushed", "color": 25},
                ]
            },
            "bass": {"targets": [{"name": "sub", "color": "#5480E4"}]},
        },
    }
    out = resolve_preset(preset)
    assert out["stems"]["drums"]["targets"][0]["color"]["name"] == "red"
    assert out["stems"]["drums"]["targets"][1]["color"]["index"] == 25
    assert out["stems"]["bass"]["targets"][0]["color"]["hex"] == "#5480E4"
    # Source preset unchanged.
    assert preset["stems"]["drums"]["targets"][0]["color"] == "red"


def test_resolve_preset_fills_display_name():
    out = resolve_preset({"name": "idm_production"})
    assert out["displayName"] == "Idm Production"
    assert out["version"] == "1.0.0"


def test_palette_preview_picks_first_target_per_stem():
    preset = resolve_preset(
        {
            "stems": {
                "drums": {"targets": [{"color": "red"}, {"color": "crimson"}]},
                "bass": {"targets": [{"color": "blue"}]},
                "vocals": {"targets": [{"color": "orange"}]},
                "other": {"targets": [{"color": "teal"}]},
            }
        }
    )
    preview = palette_preview(preset)
    assert preview == ["#FF3A34", "#5480E4", "#FFA529", "#009D7A"]


def test_palette_preview_caps_at_limit():
    preset = resolve_preset(
        {"stems": {f"s{i}": {"targets": [{"color": "red"}]} for i in range(10)}}
    )
    assert len(palette_preview(preset, limit=6)) == 6


def test_target_count_sums_across_stems():
    preset = {
        "stems": {
            "drums": {"targets": [{}, {}, {}]},
            "bass": {"targets": [{}]},
            "other": {"targets": []},
        }
    }
    assert target_count(preset) == 4


def test_compiled_production_idm_has_usable_colors(tmp_path, monkeypatch):
    """Compiled pipeline JSON ships colors the M4L loader can parse.

    The loader's parseColor (v0/src/m4l-js/stemforge_loader.v0.js) accepts
    THREE forms: integer, hex string ("#FF4444"), or rich color-descriptor
    object ({hex, index, name}). The yaml→json compile step
    (`stemforge generate-pipeline-json`) currently emits the hex-string
    form straight from the yaml; presets get the dict form when the
    authored preset already has it. Either is acceptable here — the
    contract is that parseColor can consume it.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent
    compiled = json.loads((src / "pipelines" / "production_idm.json").read_text())
    first = compiled["stems"]["drums"]["targets"][0]["color"]
    if isinstance(first, dict):
        assert isinstance(first.get("hex"), str), "dict form must have hex field"
        assert first["hex"].startswith("#")
    elif isinstance(first, str):
        assert first.startswith("#") and len(first) == 7, \
            f"hex-string form must be #RRGGBB; got {first!r}"
    else:
        raise AssertionError(
            f"color must be dict or hex string; got {type(first).__name__}: {first!r}"
        )
