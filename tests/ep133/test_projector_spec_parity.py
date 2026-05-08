"""Phase 2 byte-identity acceptance gate.

Locks the contract that the new ``Project``-driven path produces the SAME
bytes as the existing arrangement+manifest path against the canonical
fixture. If this drifts, the abstraction broke — investigate before
regenerating any baseline.

Three assertions:

1. ``Ep133Projector().project(arr, manifest, ...)`` (direct path) and
   ``Ep133Projector().project_from_spec(project_from_arrangement_and_manifest(arr, manifest), manifest, ...)``
   (spec path) produce byte-equal payloads.
2. The spec-path bytes match ``EXPECTED_OVERALL_SHA256`` from
   ``test_song_export_parity`` — catches synthesizer drift even if the
   two paths happen to drift in lockstep.
3. The spec-path payload's overall length matches ``EXPECTED_OVERALL_LEN``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE_PPAK = FIXTURES / "reference.ppak"
SAMPLE_ARRANGEMENT = FIXTURES / "sample_arrangement.json"
SAMPLE_MANIFEST = FIXTURES / "sample_manifest.json"

if not REFERENCE_PPAK.exists():
    pytest.skip(
        "reference.ppak required (same gating as test_song_export_parity.py)",
        allow_module_level=True,
    )

if not SAMPLE_ARRANGEMENT.exists() or not SAMPLE_MANIFEST.exists():
    pytest.skip(
        "sample_arrangement.json / sample_manifest.json missing",
        allow_module_level=True,
    )

from stemforge.exporters.ep133.project_translator import (  # noqa: E402
    project_from_arrangement_and_manifest,
)
from stemforge.exporters.ep133.projector import Ep133Projector  # noqa: E402

# Constants mirror tests/ep133/test_song_export_parity.py so this gate is
# anchored to the same byte-baseline. If those constants ever change
# (deliberate baseline regen), update both files in lockstep.
EXPECTED_OVERALL_LEN = 1758
EXPECTED_OVERALL_SHA256 = "53bdc105369919ca15556c07798180a697d3242dfd3883675c874829f0a7c1ba"
FIXED_GENERATED_AT = "2026-05-08T20:00:00.000Z"


def _materialize(tmp_path: Path) -> tuple[dict, dict]:
    """Mirror sample manifest paths under tmp_path (same as test_song_export_parity)."""
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


@pytest.fixture(scope="module")
def materialized(tmp_path_factory) -> tuple[dict, dict]:
    base = tmp_path_factory.mktemp("projector_spec_parity")
    return _materialize(base)


@pytest.fixture(scope="module")
def direct_bytes(materialized: tuple[dict, dict]) -> bytes:
    arrangement, manifest = materialized
    projector = Ep133Projector()
    with patch(
        "stemforge.exporters.ep133.ppak_writer._utc_iso8601",
        return_value=FIXED_GENERATED_AT,
    ):
        return projector.project(
            arrangement,
            manifest,
            project_bpm=arrangement["tempo"],
            time_sig=tuple(arrangement["time_sig"]),
            project_slot=1,
            arrangement_length_sec=arrangement.get("arrangement_length_sec"),
            reference_template=REFERENCE_PPAK,
        )


@pytest.fixture(scope="module")
def spec_bytes(materialized: tuple[dict, dict]) -> bytes:
    arrangement, manifest = materialized
    project = project_from_arrangement_and_manifest(arrangement, manifest)
    projector = Ep133Projector()
    with patch(
        "stemforge.exporters.ep133.ppak_writer._utc_iso8601",
        return_value=FIXED_GENERATED_AT,
    ):
        return projector.project_from_spec(
            project,
            manifest,
            project_slot=1,
            reference_template=REFERENCE_PPAK,
        )


def test_spec_path_byte_identical_to_direct_path(direct_bytes: bytes, spec_bytes: bytes) -> None:
    """The acceptance gate. If this breaks, the abstraction is wrong."""
    assert len(spec_bytes) == len(direct_bytes), (
        f"length drift: spec={len(spec_bytes)} vs direct={len(direct_bytes)}"
    )
    assert spec_bytes == direct_bytes, (
        "spec-path bytes diverged from direct-path bytes — the Project ↔ "
        "Snapshot translator is dropping or reshaping data the synthesizer "
        "consumes. Compare snapshots from project_to_snapshots vs "
        "resolve_scenes to localize."
    )


def test_spec_path_matches_overall_baseline_sha(spec_bytes: bytes) -> None:
    """Catches a coordinated drift: both paths could move together if synthesize
    or the writer changed. Pin to the same baseline as the pre-existing parity test."""
    actual = hashlib.sha256(spec_bytes).hexdigest()
    assert actual == EXPECTED_OVERALL_SHA256, (
        f"spec-path SHA256 drifted from baseline: {actual} vs "
        f"{EXPECTED_OVERALL_SHA256}. If both this and test_song_export_parity "
        "fail together, the synthesizer / writer changed; if only this fails, "
        "the spec path is bypassing some byte-shaping logic."
    )


def test_spec_path_matches_overall_baseline_length(spec_bytes: bytes) -> None:
    assert len(spec_bytes) == EXPECTED_OVERALL_LEN


def test_validate_spec_returns_no_warnings_for_canonical_project(
    materialized: tuple[dict, dict],
) -> None:
    arrangement, manifest = materialized
    project = project_from_arrangement_and_manifest(arrangement, manifest)
    warnings = Ep133Projector().validate_spec(project)
    assert warnings == [], f"unexpected validation warnings: {warnings}"


def test_validate_spec_flags_multi_song(
    materialized: tuple[dict, dict],
) -> None:
    arrangement, manifest = materialized
    project = project_from_arrangement_and_manifest(arrangement, manifest)
    project.songs.append(project.songs[0].model_copy(update={"song_id": "song_002"}))
    warnings = Ep133Projector().validate_spec(project)
    assert any("1 song" in w for w in warnings)


def test_validate_spec_flags_zero_scenes(materialized: tuple[dict, dict]) -> None:
    arrangement, manifest = materialized
    project = project_from_arrangement_and_manifest(arrangement, manifest)
    project.songs[0].scenes.clear()
    warnings = Ep133Projector().validate_spec(project)
    assert any("zero scenes" in w for w in warnings)
