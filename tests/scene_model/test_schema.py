"""Schema round-trip + invariant tests for the configurator scene model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stemforge.scene_model import (
    MAX_SONGS_V1,
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    ProjectSpec,
    SceneSpec,
    Song,
    project_from_json,
    project_to_json,
)


def _minimal_project() -> Project:
    return Project(
        songs=[
            Song(
                song_id="s1",
                bpm=120.0,
                groups=[
                    GroupSpec(
                        group_id="A",
                        pads=[
                            PadSpec(
                                pad_id="1",
                                clip=ClipRef(audio_hash="abc123def4567890"),
                            )
                        ],
                    )
                ],
                scenes=[
                    SceneSpec(
                        scene_id="scn_001",
                        bars=4,
                        pad_by_group={"A": "1"},
                    )
                ],
            )
        ]
    )


def test_minimal_project_round_trips() -> None:
    p = _minimal_project()
    j = project_to_json(p)
    p2 = project_from_json(j)
    assert p == p2


def test_project_spec_alias_is_project() -> None:
    # Spec text uses both names interchangeably; alias must be the same class.
    assert ProjectSpec is Project


def test_multi_song_constructible_but_v1_warns() -> None:
    p = Project(
        songs=[
            Song(song_id="s1", bpm=120.0),
            Song(song_id="s2", bpm=140.0),
        ]
    )
    warnings = p.validate_v1()
    assert warnings, "v1 advisory check must flag multi-song"
    assert "1 song" in warnings[0]


def test_single_song_v1_is_silent() -> None:
    assert _minimal_project().validate_v1() == []


def test_max_songs_v1_constant() -> None:
    assert MAX_SONGS_V1 == 1


def test_audio_hash_preserved_through_round_trip() -> None:
    cr = ClipRef(audio_hash="abc123def4567890", path="/old/path.wav")
    j = cr.model_dump_json()
    cr2 = ClipRef.model_validate_json(j)
    assert cr2.audio_hash == "abc123def4567890"


def test_clip_path_is_advisory_not_identity() -> None:
    # Two ClipRefs differ only by path; audio_hash matches → identity property.
    a = ClipRef(audio_hash="abc123def4567890", path="/old/path.wav")
    b = a.model_copy(update={"path": "/new/path.wav"})
    assert a.audio_hash == b.audio_hash
    assert a.path != b.path


def test_extra_fields_ignored_for_forward_compat() -> None:
    j = '{"schema_version": 2, "songs": [], "future_field": "ok"}'
    p = project_from_json(j)
    assert p.schema_version == 2
    # Round-trip drops the unknown field — that's the contract of extra=ignore.
    assert "future_field" not in project_to_json(p)


def test_exclude_none_keeps_optional_nulls_out_of_json() -> None:
    p = _minimal_project()
    j = project_to_json(p)
    # ClipRef.path is None by default on this fixture's clip — must not appear.
    assert '"path": null' not in j
    # SceneSpec.locator_time_sec defaults to None — same.
    assert '"locator_time_sec"' not in j


def test_default_factories_dont_share_state() -> None:
    a = Project()
    b = Project()
    a.songs.append(Song(song_id="s1", bpm=120.0))
    assert b.songs == [], "default-factory list must not be shared across instances"


def test_schema_version_default_is_2() -> None:
    assert Project().schema_version == 2


def test_provenance_taxonomy_accepts_all_four() -> None:
    for prov in ("auto", "manual", "splice", "imported"):
        scn = SceneSpec(scene_id="x", bars=1, provenance=prov)
        assert scn.provenance == prov


def test_provenance_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        SceneSpec(scene_id="x", bars=1, provenance="nonsense")  # type: ignore[arg-type]


def test_play_mode_and_stretch_mode_defaults() -> None:
    pad = PadSpec(pad_id="1")
    assert pad.play_mode == "oneshot"
    assert pad.stretch_mode == "bpm"


def test_source_song_id_supports_cross_song_splice() -> None:
    # Decision 7 — schema must permit a clip in song B to point at song A.
    cr = ClipRef(audio_hash="hash_b", source_song_id="song_a")
    assert cr.source_song_id == "song_a"
    j = cr.model_dump_json()
    assert ClipRef.model_validate_json(j).source_song_id == "song_a"


def test_pad_by_group_allows_silent_group() -> None:
    # Missing key OR explicit None both mean "no pad fires for this group".
    scn = SceneSpec(scene_id="x", bars=1, pad_by_group={"A": "1", "B": None})
    assert scn.pad_by_group == {"A": "1", "B": None}


def test_time_sig_round_trip_as_tuple() -> None:
    s = Song(song_id="s1", bpm=120.0, time_sig=(3, 4))
    j = s.model_dump_json()
    s2 = Song.model_validate_json(j)
    assert s2.time_sig == (3, 4)
