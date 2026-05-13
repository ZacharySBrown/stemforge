"""Round-trip + reject tests for the Curation schema.

Asserts the on-disk YAML files under ``tests/fixtures/curations/`` parse,
that ``extra="forbid"`` catches typo'd keys, and that the schema rejects
malformed input loudly.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from stemforge.configurator.schemas import Curation, Pad, PadSource, Target

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "curations"


def _minimal_kwargs() -> dict:
    now = dt.datetime(2026, 5, 13, tzinfo=dt.UTC)
    return {
        "name": "test",
        "created_at": now,
        "modified_at": now,
        "target": Target(),
    }


def test_minimal_curation_constructs() -> None:
    c = Curation(**_minimal_kwargs())
    assert c.curation_version == 1
    assert c.type == "deck"
    assert c.target.device == "ep133"
    assert c.target.groups == 4
    assert c.target.pads_per_group == 12


def test_extra_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Curation(**_minimal_kwargs(), bogus_field="nope")


def test_pad_with_source_round_trips() -> None:
    pad = Pad(
        pad_id="A01",
        source=PadSource(
            forge="sample-forge",
            clip_id="vocal-bar0-4",
            audio_path="curated_audio/vocal-bar0-4.wav",
        ),
    )
    restored = Pad(**pad.model_dump())
    assert restored == pad


def test_empty_pad_omits_source() -> None:
    pad = Pad(pad_id="A02")
    dumped = pad.model_dump()
    assert dumped["source"] is None
    assert Pad(**dumped) == pad


@pytest.mark.parametrize(
    "fixture_name",
    sorted(p.name for p in FIXTURE_DIR.glob("*.yaml")),
)
def test_fixture_curation_round_trips(fixture_name: str) -> None:
    """Every fixture YAML loads, dumps, and re-loads identically."""
    path = FIXTURE_DIR / fixture_name
    data = yaml.safe_load(path.read_text())
    c = Curation(**data)
    dumped = c.model_dump(mode="json")
    re_c = Curation(**dumped)
    assert re_c == c


def test_invalid_type_rejected() -> None:
    with pytest.raises(ValidationError):
        Curation(**_minimal_kwargs(), type="bogus")


def test_referenced_forges_default_empty() -> None:
    c = Curation(**_minimal_kwargs())
    assert c.referenced_forges == []


def test_target_groups_bounds() -> None:
    with pytest.raises(ValidationError):
        Target(groups=0)
    with pytest.raises(ValidationError):
        Target(groups=99)
