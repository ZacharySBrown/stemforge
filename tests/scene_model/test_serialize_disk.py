"""Disk round-trip tests for ``Project`` JSON serialization."""

from __future__ import annotations

from stemforge.scene_model import (
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    SceneSpec,
    Song,
    project_from_path,
    project_to_path,
)


def _full_project() -> Project:
    return Project(
        name="round_trip_fixture",
        project_id="proj_001",
        songs=[
            Song(
                song_id="s1",
                name="opener",
                bpm=120.0,
                time_sig=(4, 4),
                arrangement_length_sec=64.0,
                groups=[
                    GroupSpec(
                        group_id="A",
                        pads=[
                            PadSpec(
                                pad_id="1",
                                clip=ClipRef(
                                    audio_hash="abc123def4567890",
                                    path="/tmp/x.wav",
                                    source_song_id="s2",
                                    source_track="A",
                                    name="kick_loop",
                                    source_bpm=120.0,
                                ),
                                play_mode="key",
                                stretch_mode="bar",
                                bars=4,
                            )
                        ],
                    )
                ],
                scenes=[
                    SceneSpec(
                        scene_id="scn_001",
                        name="verse",
                        bars=2,
                        locator_time_sec=4.0,
                        provenance="manual",
                        pad_by_group={"A": "1"},
                    )
                ],
            )
        ],
    )


def test_project_round_trips_to_disk(tmp_path) -> None:
    p = _full_project()
    out = tmp_path / "project.json"
    project_to_path(p, out)
    assert out.exists()
    p2 = project_from_path(out)
    assert p == p2


def test_disk_round_trip_is_idempotent(tmp_path) -> None:
    # Write → read → write must produce byte-identical JSON.
    p = _full_project()
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    project_to_path(p, a)
    project_to_path(project_from_path(a), b)
    assert a.read_text() == b.read_text()


def test_project_to_path_creates_parent_dirs(tmp_path) -> None:
    out = tmp_path / "nested" / "deeper" / "project.json"
    project_to_path(_full_project(), out)
    assert out.exists()


def test_disk_form_is_indent_2(tmp_path) -> None:
    out = tmp_path / "project.json"
    project_to_path(_full_project(), out)
    text = out.read_text()
    assert "\n  " in text, "canonical form is indent=2"
