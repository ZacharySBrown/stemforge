"""Tests for stock device fragment loading + param application."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from builder import (  # noqa: E402
    STOCK_DEVICE_FILES,
    build_stock_device,
    load_device_fragment,
)


@pytest.mark.parametrize("name", list(STOCK_DEVICE_FILES.keys()))
def test_each_stock_fragment_loads(name):
    elem = load_device_fragment(name)
    assert elem is not None
    assert elem.tag  # non-empty root tag


def test_compressor_params_applied():
    elem = build_stock_device(
        "Compressor",
        {
            "threshold_db": -15,
            "ratio": 6,
            "attack_ms": 10,
            "release_ms": 100,
        },
    )
    assert elem.find("./Threshold/Manual").get("Value") == "-15"
    assert elem.find("./Ratio/Manual").get("Value") == "6"
    assert elem.find("./Attack/Manual").get("Value") == "10"
    assert elem.find("./Release/Manual").get("Value") == "100"


def test_reverb_decay_converted_to_ms():
    elem = build_stock_device(
        "Reverb", {"decay_sec": 6.0, "diffusion": 0.95}
    )
    # 6.0 s → 6000 ms, but it's an integer-ish float → "6000"
    assert elem.find("./DecayTime/Manual").get("Value") == "6000"
    assert elem.find("./Diffusion/Manual").get("Value") == "0.95"


def test_utility_gain():
    elem = build_stock_device("Utility", {"gain_db": -3})
    assert elem.find("./Gain/Manual").get("Value") == "-3"


def test_simpler_slice_mode():
    elem = build_stock_device(
        "Simpler", {"mode": "slice", "warp": "off"}
    )
    assert elem.find("./Playback/PlayMode/Manual").get("Value") == "2"
    assert elem.find("./Player/Warping/Manual").get("Value") == "false"


def test_eq_eight_no_params_is_noop():
    # EQ Eight has no param appliers in v0; should return a valid element.
    elem = build_stock_device("EQ Eight", {})
    assert elem.tag == "Eq8"
