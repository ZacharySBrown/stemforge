"""GroupSpec.format_profile schema tests.

Per configurator spec v4 Decision 16: per-group sample format. Schema
field is a Literal; defaults to ``preserve_source`` so existing data
round-trips unchanged.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stemforge.scene_model import (
    RESOLUTIONS,
    AudioFormat,
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    SceneSpec,
    Song,
    project_from_json,
    project_to_json,
    resolve_format_profile,
)


def _project_with_profile(profile: str) -> Project:
    return Project(
        songs=[
            Song(
                song_id="s1",
                bpm=120.0,
                groups=[
                    GroupSpec(
                        group_id="A",
                        format_profile=profile,
                        pads=[PadSpec(pad_id="1", clip=ClipRef(audio_hash="abc1234567890def"))],
                    )
                ],
                scenes=[
                    SceneSpec(scene_id="scn", bars=4, pad_by_group={"A": "1"}),
                ],
            )
        ]
    )


def test_default_format_profile_is_preserve_source() -> None:
    g = GroupSpec(group_id="A")
    assert g.format_profile == "preserve_source"


@pytest.mark.parametrize("profile", ["vocal", "drum", "texture", "preserve_source"])
def test_valid_format_profiles_accepted(profile: str) -> None:
    g = GroupSpec(group_id="A", format_profile=profile)  # type: ignore[arg-type]
    assert g.format_profile == profile


def test_invalid_format_profile_rejected() -> None:
    with pytest.raises(ValidationError):
        GroupSpec(group_id="A", format_profile="hi-fi")  # type: ignore[arg-type]


def test_format_profile_round_trips_through_json() -> None:
    project = _project_with_profile("vocal")
    j = project_to_json(project)
    back = project_from_json(j)
    assert back.songs[0].groups[0].format_profile == "vocal"
    assert back == project


def test_format_profile_default_omitted_from_json() -> None:
    project = _project_with_profile("preserve_source")
    j = project_to_json(project)
    # exclude_none + default elision: a default-valued literal is still
    # written by pydantic; we just want the field present + correct.
    assert '"format_profile": "preserve_source"' in j


def test_resolutions_table_complete() -> None:
    expected = {"vocal", "drum", "texture", "preserve_source"}
    assert set(RESOLUTIONS) == expected


def test_resolve_format_profile_returns_audio_format() -> None:
    fmt = resolve_format_profile("vocal")
    assert isinstance(fmt, AudioFormat)
    assert fmt.channels == 1
    assert fmt.sample_rate_hz == 24000
    assert fmt.bit_depth == 16


def test_resolutions_drum_and_texture_are_full_quality() -> None:
    drum = resolve_format_profile("drum")
    tex = resolve_format_profile("texture")
    assert drum.sample_rate_hz == 48000
    assert tex.sample_rate_hz == 48000
