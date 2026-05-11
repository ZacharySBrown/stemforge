"""Tests for the target-agnostic Project builders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stemforge.scene_model import (
    Project,
    empty_project_from_manifest,
    project_from_json,
    project_to_json,
)

FIXTURES = Path(__file__).resolve().parents[1] / "ep133" / "fixtures"
SAMPLE_MANIFEST = FIXTURES / "sample_manifest.json"


@pytest.fixture
def manifest() -> dict:
    if not SAMPLE_MANIFEST.exists():
        pytest.skip("sample_manifest.json fixture missing")
    return json.loads(SAMPLE_MANIFEST.read_text())


def test_empty_project_has_one_song(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest)
    assert len(p.songs) == 1
    assert p.validate_v1() == []


def test_empty_project_walks_all_four_groups(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest)
    song = p.songs[0]
    assert [g.group_id for g in song.groups] == ["A", "B", "C", "D"]


def test_empty_project_pads_match_session_tracks_count(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest)
    song = p.songs[0]
    counts = {g.group_id: len(g.pads) for g in song.groups}
    assert counts == {"A": 3, "B": 2, "C": 1, "D": 0}


def test_empty_project_pad_ids_are_one_indexed(manifest: dict) -> None:
    # Manifest slots are 0-indexed; EP-133 pads are 1..12. pad_id = slot + 1.
    p = empty_project_from_manifest(manifest)
    pads_a = p.songs[0].groups[0].pads
    assert [pad.pad_id for pad in pads_a] == ["1", "2", "3"]


def test_empty_project_clip_path_carries_through(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest)
    pad_a1 = p.songs[0].groups[0].pads[0]
    assert pad_a1.clip is not None
    assert pad_a1.clip.path == "/songs/test/A/loop_a1.wav"


def test_empty_project_audio_hash_empty_when_manifest_lacks_one(manifest: dict) -> None:
    # Phase 2 decision: hash if available, otherwise empty string.
    p = empty_project_from_manifest(manifest)
    pad_a1 = p.songs[0].groups[0].pads[0]
    assert pad_a1.clip is not None
    assert pad_a1.clip.audio_hash == ""


def test_empty_project_scenes_are_empty(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest)
    assert p.songs[0].scenes == []


def test_empty_project_round_trips_through_json(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest)
    j = project_to_json(p)
    assert project_from_json(j) == p


def test_empty_project_handles_missing_session_tracks() -> None:
    # An empty / minimal manifest is legal — produces a Project with empty groups.
    p = empty_project_from_manifest({})
    assert len(p.songs) == 1
    assert all(len(g.pads) == 0 for g in p.songs[0].groups)


def test_empty_project_propagates_bpm_and_time_sig(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest, bpm=140.0, time_sig=(3, 4))
    song = p.songs[0]
    assert song.bpm == 140.0
    assert song.time_sig == (3, 4)


def test_empty_project_pad_bars_inferred_from_clip_length(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest, bpm=120.0)
    pads_a = p.songs[0].groups[0].pads
    # /songs/test/A/loop_a1.wav has clip_length_sec=8.0 at 120 BPM = 4 bars.
    # /songs/test/A/loop_a2.wav has clip_length_sec=4.0 at 120 BPM = 2 bars.
    assert pads_a[0].bars == 4
    assert pads_a[1].bars == 2


def test_empty_project_returns_project_type(manifest: dict) -> None:
    assert isinstance(empty_project_from_manifest(manifest), Project)


def test_empty_project_name_override(manifest: dict) -> None:
    p = empty_project_from_manifest(manifest, project_name="my_proj")
    assert p.name == "my_proj"
