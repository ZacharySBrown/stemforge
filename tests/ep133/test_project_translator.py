"""Tests for the EP-133 project_translator (Project ↔ Snapshot bridge).

The byte-identity acceptance gate (`tests/ep133/test_projector_spec_parity.py`)
is wired in commit 3 — these tests cover the structural / shape contracts for
the translator alone, against the canonical fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stemforge.exporters.ep133.project_translator import (
    project_from_arrangement_and_manifest,
    project_to_snapshots,
)
from stemforge.exporters.ep133.song_resolver import resolve_scenes
from stemforge.scene_model import Project, SceneSpec

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ARRANGEMENT = FIXTURES / "sample_arrangement.json"
SAMPLE_MANIFEST = FIXTURES / "sample_manifest.json"


@pytest.fixture
def fixtures() -> tuple[dict, dict]:
    if not SAMPLE_ARRANGEMENT.exists() or not SAMPLE_MANIFEST.exists():
        pytest.skip("canonical sample_arrangement / sample_manifest missing")
    arrangement = json.loads(SAMPLE_ARRANGEMENT.read_text())
    manifest = json.loads(SAMPLE_MANIFEST.read_text())
    return arrangement, manifest


def test_project_from_arrangement_returns_project(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    assert isinstance(p, Project)
    assert len(p.songs) == 1


def test_project_scenes_match_locator_count(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    # sample_arrangement.json has 3 locators.
    assert len(p.songs[0].scenes) == 3


def test_project_scene_names_match_locators(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    names = [s.name for s in p.songs[0].scenes]
    assert names == ["Verse", "Chorus", "Outro"]


def test_project_scenes_in_locator_time_order(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    times = [s.locator_time_sec for s in p.songs[0].scenes]
    assert times == sorted(times)


def test_project_pad_by_group_resolves_active_clips(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    scenes = p.songs[0].scenes
    # Verse @ t=0: A=loop_a1 (slot 0 → pad "1"), B=bass_b1 (slot 0 → pad "1"),
    # C silent, D silent.
    assert scenes[0].pad_by_group == {"A": "1", "B": "1", "C": None, "D": None}
    # Chorus @ t=8: A=loop_a2 (slot 1 → pad "2"), B=bass_b1 (still active until t=16),
    # C=vox_c1 (slot 0 → pad "1"), D silent.
    assert scenes[1].pad_by_group == {"A": "2", "B": "1", "C": "1", "D": None}
    # Outro @ t=16: A=loop_a3 (slot 2 → pad "3"), B=bass_b2 (slot 1 → pad "2"),
    # C silent, D silent.
    assert scenes[2].pad_by_group == {"A": "3", "B": "2", "C": None, "D": None}


def test_project_round_trip_to_snapshots_matches_resolver(
    fixtures: tuple[dict, dict],
) -> None:
    """The acceptance contract for commit 2:
    project_to_snapshots(project_from_arrangement_and_manifest(arr, mf), mf)
    must reproduce resolve_scenes(arr, mf) at the field level the synthesizer reads.
    """
    arrangement, manifest = fixtures
    direct = resolve_scenes(arrangement, manifest)
    project = project_from_arrangement_and_manifest(arrangement, manifest)
    rebuilt = project_to_snapshots(project, manifest)

    assert len(rebuilt) == len(direct)
    for d, r in zip(direct, rebuilt):
        assert r.locator_time_sec == d.locator_time_sec
        assert r.locator_name == d.locator_name
        for group in ("A", "B", "C", "D"):
            d_clip = d.clip_for(group)
            r_clip = r.clip_for(group)
            if d_clip is None:
                assert r_clip is None
            else:
                assert r_clip is not None
                # synthesize() reads only file_path + length_sec from
                # ArrangementClip; start_time_sec / warping aren't consumed.
                assert r_clip.file_path == d_clip.file_path
                # length_sec on r is reconstructed from manifest's
                # clip_length_sec (canonical fixture has it on every entry).
                assert r_clip.length_sec == float(_entry_length(manifest, group, d_clip.file_path))


def _entry_length(manifest: dict, group: str, file_path: str) -> float:
    entries = manifest["session_tracks"][group]
    for e in entries:
        if (e.get("file_path") or e.get("file")) == file_path:
            return float(e["clip_length_sec"])
    raise AssertionError(f"file {file_path} not in manifest[{group}]")


def test_project_to_snapshots_rejects_multi_song(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    p.songs.append(p.songs[0].model_copy(update={"song_id": "song_002"}))
    with pytest.raises(ValueError, match="exactly 1 song"):
        project_to_snapshots(p, manifest)


def test_project_to_snapshots_raises_on_unmapped_pad(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    # Forge a scene that points at a non-existent pad.
    p.songs[0].scenes[0] = SceneSpec(
        scene_id="scn_bogus",
        bars=1,
        locator_time_sec=0.0,
        pad_by_group={"A": "99", "B": None, "C": None, "D": None},
    )
    with pytest.raises(KeyError, match="no slot"):
        project_to_snapshots(p, manifest)


def test_project_carries_arrangement_bpm_and_time_sig(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    song = p.songs[0]
    assert song.bpm == 120.0
    assert song.time_sig == (4, 4)
    assert song.arrangement_length_sec == 24.0


def test_project_groups_populated_from_manifest_not_arrangement(
    fixtures: tuple[dict, dict],
) -> None:
    # Group D is empty in the arrangement but the manifest still includes it
    # (with no entries) — Project should still have a GroupSpec for D.
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    group_d = next(g for g in p.songs[0].groups if g.group_id == "D")
    assert group_d.pads == []


def test_scene_bars_match_resolver_lengths(fixtures: tuple[dict, dict]) -> None:
    # 3 locators at 0/8/16, arrangement_length=24, BPM=120 → 4-bar scenes (8s = 4 bars at 120bpm 4/4).
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    bars = [s.bars for s in p.songs[0].scenes]
    assert bars == [4, 4, 4]


def test_scene_provenance_imported(fixtures: tuple[dict, dict]) -> None:
    arrangement, manifest = fixtures
    p = project_from_arrangement_and_manifest(arrangement, manifest)
    # Forward path is "imported from arrangement view"; this is the v2 spec
    # Decision 9 baseline. Manual / splice / auto come later.
    assert all(s.provenance == "imported" for s in p.songs[0].scenes)
