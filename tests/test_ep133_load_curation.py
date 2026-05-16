"""Tests for tools/ep133_load_curation.py — ProjectSpec → SysEx load plan.

Covers the pure ``plan_from_projectspec`` builder (slot mapping, group
ordering, empty-pad skipping). The device-I/O path (``run_load``) needs a
real EP-133 + the ``ep133`` extra, so it is not exercised here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# tools/ isn't on the package path; load the module from its file.
_HELPER = Path(__file__).resolve().parents[1] / "tools" / "ep133_load_curation.py"
_spec = importlib.util.spec_from_file_location("ep133_load_curation", _HELPER)
ep133_load_curation = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve the module via sys.modules.
sys.modules["ep133_load_curation"] = ep133_load_curation
_spec.loader.exec_module(ep133_load_curation)

plan_from_projectspec = ep133_load_curation.plan_from_projectspec


def _spec(groups: dict[str, list[dict]]) -> dict:
    """Build a minimal ProjectSpec with the given group→pads mapping."""
    return {
        "schema_version": 2,
        "songs": [
            {
                "song_id": "kit",
                "groups": [
                    {"group_id": gid, "pads": pads}
                    for gid, pads in groups.items()
                ],
            }
        ],
    }


def _pad(pad_id: int, path: str, *, bpm: float | None = 120.0) -> dict:
    return {
        "pad_id": str(pad_id),
        "clip": {"path": path, "source_bpm": bpm, "start_offset_sec": 0.0},
        "play_mode": "oneshot",
        "stretch_mode": "bpm",
    }


def test_slot_mapping_matches_ppak_layout() -> None:
    """A→700.., B→720.., C→740.., D→760.. — slot = base + pad_num-1."""
    spec = _spec(
        {
            "A": [_pad(1, "/a1.wav"), _pad(2, "/a2.wav")],
            "B": [_pad(1, "/b1.wav")],
            "D": [_pad(12, "/d12.wav")],
        }
    )
    ops = plan_from_projectspec(spec)
    by_id = {(o.group, o.pad_num): o.slot for o in ops}
    assert by_id[("A", 1)] == 700
    assert by_id[("A", 2)] == 701
    assert by_id[("B", 1)] == 720
    assert by_id[("D", 12)] == 771


def test_empty_pads_are_skipped() -> None:
    """Pads with no clip (or no path) produce no work."""
    spec = _spec(
        {
            "A": [
                _pad(1, "/a1.wav"),
                {"pad_id": "2", "clip": None, "play_mode": "oneshot"},
                {"pad_id": "3", "clip": {"path": ""}, "play_mode": "oneshot"},
            ]
        }
    )
    ops = plan_from_projectspec(spec)
    assert [o.pad_num for o in ops] == [1]


def test_carries_bpm_and_modes() -> None:
    spec = _spec({"C": [_pad(1, "/c1.wav", bpm=138.0)]})
    (op,) = plan_from_projectspec(spec)
    assert op.source_bpm == 138.0
    assert op.playmode == "oneshot"
    assert op.time_mode == "bpm"


def test_missing_bpm_leaves_source_bpm_none() -> None:
    spec = _spec({"A": [_pad(1, "/a1.wav", bpm=None)]})
    (op,) = plan_from_projectspec(spec)
    assert op.source_bpm is None


def test_non_bpm_stretch_mode_maps_to_off() -> None:
    spec = _spec(
        {"A": [{"pad_id": "1", "clip": {"path": "/x.wav"}, "stretch_mode": "none"}]}
    )
    (op,) = plan_from_projectspec(spec)
    assert op.time_mode == "off"


def test_custom_start_slot() -> None:
    spec = _spec({"A": [_pad(1, "/a1.wav")], "B": [_pad(1, "/b1.wav")]})
    ops = plan_from_projectspec(spec, start_slot=100)
    by_id = {o.group: o.slot for o in ops}
    assert by_id["A"] == 100
    assert by_id["B"] == 120  # base + GROUP_SLOT_STRIDE


def test_rejects_unknown_group() -> None:
    spec = _spec({"E": [_pad(1, "/e1.wav")]})
    with pytest.raises(ValueError, match="group_id"):
        plan_from_projectspec(spec)


def test_rejects_out_of_range_pad() -> None:
    spec = _spec({"A": [_pad(13, "/a13.wav")]})
    with pytest.raises(ValueError, match="out of range"):
        plan_from_projectspec(spec)


def test_rejects_spec_with_no_songs() -> None:
    with pytest.raises(ValueError, match="no songs"):
        plan_from_projectspec({"songs": []})


def test_playmode_override_forces_every_pad() -> None:
    spec = _spec({"A": [_pad(1, "/a1.wav"), _pad(2, "/a2.wav")]})
    ops = plan_from_projectspec(spec, playmode_override="key")
    assert {o.playmode for o in ops} == {"key"}


def test_no_playmode_override_keeps_spec_mode() -> None:
    spec = _spec({"A": [_pad(1, "/a1.wav")]})
    (op,) = plan_from_projectspec(spec)
    assert op.playmode == "oneshot"  # the value in _pad()
