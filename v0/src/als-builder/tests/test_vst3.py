"""Tests for VST3 device emission + missing-plugin placeholder."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from builder import (  # noqa: E402
    build_vst3_device,
    build_vst3_missing_placeholder,
    load_vst3_lookup,
    _normalize_vst3_param_value,
)


def test_lookup_loads():
    lookup = load_vst3_lookup()
    assert "SoundToys.Decapitator" in lookup
    assert "XLN.LO-FI-AF" in lookup


def test_known_plugin_emits_parameters():
    lookup = load_vst3_lookup()
    dev = build_vst3_device(
        "SoundToys.Decapitator",
        {"drive": 0.35, "style": "E"},
        lookup,
    )
    assert dev.tag == "Vst3PluginDevice"
    params = dev.findall("./ParameterList/Parameter")
    # Both drive and style should emit.
    assert len(params) == 2


def test_unknown_plugin_emits_placeholder():
    lookup = load_vst3_lookup()
    dev = build_vst3_device(
        "Acme.NonexistentPlugin",
        {"something": 0.5},
        lookup,
    )
    # Placeholder Uid is all-zero.
    uid = dev.find("./Uid").get("Value")
    assert uid == "00000000000000000000000000000000"


def test_missing_placeholder_carries_params_in_display_name():
    dev = build_vst3_missing_placeholder("Vendor.Thing", {"a": 1})
    assert "Vendor.Thing" in dev.find("./UserDisplayName").get("Value")
    assert "params" in dev.find("./UserDisplayName").get("Value")


def test_normalize_enum_value():
    spec = {"range": [0, 4], "enum": {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}}
    assert _normalize_vst3_param_value("A", spec) == 0.0
    assert _normalize_vst3_param_value("E", spec) == 1.0


def test_normalize_semitones_string():
    spec = {"range": [-24, 24]}
    # "+5 semitones" → 5.0, (5 - (-24)) / (24 - (-24)) = 29/48 ≈ 0.604
    v = _normalize_vst3_param_value("+5 semitones", spec)
    assert 0.6 < v < 0.61


def test_normalize_clamps():
    spec = {"range": [0.0, 1.0]}
    assert _normalize_vst3_param_value(2.0, spec) == 1.0
    assert _normalize_vst3_param_value(-1.0, spec) == 0.0
