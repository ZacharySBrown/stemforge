"""Round-trip tests for the StemforgeState schema."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from stemforge.configurator.schemas import StemforgeState


def test_default_state() -> None:
    s = StemforgeState()
    assert s.schema_version == 1
    assert s.active_curations == {}
    assert s.last_known_port is None


def test_round_trip_with_active_curations() -> None:
    s = StemforgeState(
        active_curations={
            "/Users/zak/Music/Ableton/Verse Swap.als": "verse_swap_v1",
            "/Users/zak/Music/Ableton/Mashup Lab.als": "breaks-n-beats-deck",
        },
        last_known_port=7430,
        last_seen_at=dt.datetime(2026, 5, 13, 9, 14, 0, tzinfo=dt.UTC),
    )
    re_s = StemforgeState(**s.model_dump(mode="json"))
    assert re_s == s


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        StemforgeState(extra_thing=True)


def test_port_must_be_in_range() -> None:
    with pytest.raises(ValidationError):
        StemforgeState(last_known_port=0)
    with pytest.raises(ValidationError):
        StemforgeState(last_known_port=99_999)
