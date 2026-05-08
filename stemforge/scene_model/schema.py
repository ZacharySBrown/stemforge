"""Target-agnostic scene-model schema.

Pydantic v2 models for ``Project / Song / SceneSpec / GroupSpec / PadSpec /
ClipRef``. Multi-song-ready from day one (per configurator spec Decision 10);
v1 UI forces ``len(songs) == 1`` advisorily via :meth:`Project.validate_v1`.

Hash-based clip identity (Decision 3): :attr:`ClipRef.audio_hash` is the
canonical identity. :attr:`ClipRef.path` is advisory and may be invalidated
by re-anchor WAV regeneration.

This module is the wire format. Round-trip via
:mod:`stemforge.scene_model.serialize`. Builders that synthesize a
``Project`` from a manifest + arrangement live in
:mod:`stemforge.scene_model.builders` (Phase 2 commit 2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PlayMode = Literal["oneshot", "key", "legato"]
StretchMode = Literal["none", "bar", "bpm"]
Provenance = Literal["auto", "manual", "splice", "imported"]

MAX_SONGS_V1 = 1


class ClipRef(BaseModel):
    """Reference to an audio clip. Identity = ``audio_hash``; ``path`` advisory."""

    audio_hash: str
    path: str | None = None
    start_offset_sec: float = 0.0
    end_offset_sec: float | None = None
    loop_start_sec: float | None = None
    loop_end_sec: float | None = None
    source_bpm: float | None = None
    source_song_id: str | None = None
    source_track: str | None = None
    name: str | None = None

    model_config = {"extra": "ignore"}


class PadSpec(BaseModel):
    pad_id: str
    clip: ClipRef | None = None
    play_mode: PlayMode = "oneshot"
    stretch_mode: StretchMode = "bpm"
    bars: int | None = None

    model_config = {"extra": "ignore"}


class GroupSpec(BaseModel):
    group_id: str
    pads: list[PadSpec] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class SceneSpec(BaseModel):
    scene_id: str
    name: str = ""
    bars: int
    locator_time_sec: float | None = None
    provenance: Provenance = "imported"
    pad_by_group: dict[str, str | None] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}


class Song(BaseModel):
    song_id: str
    name: str = ""
    bpm: float
    time_sig: tuple[int, int] = (4, 4)
    arrangement_length_sec: float | None = None
    groups: list[GroupSpec] = Field(default_factory=list)
    scenes: list[SceneSpec] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class Project(BaseModel):
    schema_version: int = 2
    project_id: str = ""
    name: str = ""
    songs: list[Song] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    def validate_v1(self) -> list[str]:
        """v1 advisory check: UI surface assumes exactly one song."""
        warnings: list[str] = []
        if len(self.songs) != MAX_SONGS_V1:
            warnings.append(f"v1 supports exactly {MAX_SONGS_V1} song, got {len(self.songs)}")
        return warnings


ProjectSpec = Project


__all__ = [
    "MAX_SONGS_V1",
    "ClipRef",
    "GroupSpec",
    "PadSpec",
    "PlayMode",
    "Project",
    "ProjectSpec",
    "Provenance",
    "SceneSpec",
    "Song",
    "StretchMode",
]
