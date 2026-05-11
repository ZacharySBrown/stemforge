"""Tests for :class:`Ep133Projector` — the AbstractProjector implementation.

Covers the three-method surface (``capabilities``, ``validate``, ``project``)
plus the two intermediate helpers (``synthesize_spec``, ``build_bytes_from_spec``)
that the CLI uses for status prints.

Byte-identity is covered by ``test_song_export_parity.py``; here we test the
projector's API shape and validation behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stemforge.exporters.ep133.projector import Ep133Projector
from stemforge.exporters.ep133.song_format import PpakSpec
from stemforge.exporters.projector import AbstractProjector

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE_PPAK = FIXTURES / "reference.ppak"
SAMPLE_ARRANGEMENT = FIXTURES / "sample_arrangement.json"
SAMPLE_MANIFEST = FIXTURES / "sample_manifest.json"


@pytest.fixture
def materialized(tmp_path) -> tuple[dict, dict]:
    """Mirror the integration-test materialization so file_path entries
    resolve to real on-disk stub WAVs (build_ppak reads bytes)."""
    if not SAMPLE_ARRANGEMENT.exists() or not SAMPLE_MANIFEST.exists():
        pytest.skip("Track-C fixture inputs missing")
    arrangement_raw = json.loads(SAMPLE_ARRANGEMENT.read_text())
    manifest_raw = json.loads(SAMPLE_MANIFEST.read_text())
    path_map: dict[str, str] = {}
    for group, entries in (manifest_raw.get("session_tracks") or {}).items():
        gdir = tmp_path / "songs" / group
        gdir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            old = entry.get("file_path") or entry.get("file")
            if old is None:
                continue
            new = gdir / Path(old).name
            new.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
            path_map[old] = str(new)
            entry["file"] = str(new)
    for group_clips in arrangement_raw.get("tracks", {}).values():
        for clip in group_clips:
            old = clip.get("file_path")
            if old in path_map:
                clip["file_path"] = path_map[old]
    return arrangement_raw, manifest_raw


def test_ep133_projector_implements_abstract_interface():
    """Subclass relationship + the three abstract methods are present."""
    assert issubclass(Ep133Projector, AbstractProjector)
    p = Ep133Projector()
    assert callable(p.capabilities)
    assert callable(p.validate)
    assert callable(p.project)


def test_capabilities_reports_ep133_limits():
    caps = Ep133Projector().capabilities()
    assert caps["device"] == "ep133"
    assert caps["max_scenes"] == 99
    assert caps["max_patterns_per_group"] == 99
    assert caps["max_pads_per_group"] == 12
    assert caps["groups"] == ("a", "b", "c", "d")
    assert caps["project_slot_range"] == (1, 9)
    assert caps["supported_bar_counts"] == (1, 2, 4)


def test_validate_accepts_well_formed_inputs(materialized):
    arrangement, manifest = materialized
    warnings = Ep133Projector().validate(arrangement, manifest, project_slot=1)
    assert warnings == []


def test_validate_warns_on_zero_locators(materialized):
    arrangement, manifest = materialized
    arrangement["locators"] = []
    warnings = Ep133Projector().validate(arrangement, manifest, project_slot=1)
    assert any("zero locators" in w for w in warnings)


def test_validate_warns_when_locator_count_exceeds_max(materialized):
    arrangement, manifest = materialized
    arrangement["locators"] = [{"time_sec": float(i), "name": ""} for i in range(120)]
    warnings = Ep133Projector().validate(arrangement, manifest, project_slot=1)
    assert any("> EP-133 limit of 99 scenes" in w for w in warnings)


@pytest.mark.parametrize("bad_slot", [0, 10, -1])
def test_validate_warns_on_out_of_range_project_slot(materialized, bad_slot):
    arrangement, manifest = materialized
    warnings = Ep133Projector().validate(arrangement, manifest, project_slot=bad_slot)
    assert any("out of EP-133 range 1..9" in w for w in warnings)


def test_validate_warns_on_empty_session_tracks(materialized):
    arrangement, manifest = materialized
    manifest["session_tracks"] = {}
    warnings = Ep133Projector().validate(arrangement, manifest, project_slot=1)
    assert any("no session_tracks block" in w for w in warnings)


def test_synthesize_spec_returns_ppakspec(materialized):
    arrangement, manifest = materialized
    spec = Ep133Projector().synthesize_spec(
        arrangement,
        manifest,
        project_bpm=arrangement["tempo"],
        time_sig=tuple(arrangement["time_sig"]),
        project_slot=1,
        arrangement_length_sec=arrangement.get("arrangement_length_sec"),
    )
    assert isinstance(spec, PpakSpec)
    assert len(spec.scenes) == len(arrangement["locators"])


def test_project_returns_bytes_for_well_formed_input(materialized):
    if not REFERENCE_PPAK.exists():
        pytest.skip("reference.ppak required for full project() pipeline")
    arrangement, manifest = materialized
    payload = Ep133Projector().project(
        arrangement,
        manifest,
        project_bpm=arrangement["tempo"],
        time_sig=tuple(arrangement["time_sig"]),
        project_slot=1,
        arrangement_length_sec=arrangement.get("arrangement_length_sec"),
        reference_template=REFERENCE_PPAK,
    )
    assert isinstance(payload, bytes)
    # Sanity: ZIP magic.
    assert payload[:2] == b"PK"


def test_project_works_with_no_reference_template(materialized):
    """When reference_template is None, project() synthesizes a minimal
    template — the bytes are valid even without a captured reference."""
    arrangement, manifest = materialized
    payload = Ep133Projector().project(
        arrangement,
        manifest,
        project_bpm=arrangement["tempo"],
        time_sig=tuple(arrangement["time_sig"]),
        project_slot=1,
        arrangement_length_sec=arrangement.get("arrangement_length_sec"),
        reference_template=None,
    )
    assert isinstance(payload, bytes)
    assert payload[:2] == b"PK"
