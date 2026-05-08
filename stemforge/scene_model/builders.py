"""Project builders that don't need device-specific resolution.

This module owns target-agnostic builders only. The arrangement-driven
builder (which needs the EP-133 resolver to figure out which clip is
active at each locator) lives in
:mod:`stemforge.exporters.ep133.project_translator` until ``resolve_scenes``
graduates to the abstract layer in a later phase.
"""

from __future__ import annotations

from .helpers import infer_bars
from .schema import (
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    Song,
)

GROUPS_DEFAULT: tuple[str, ...] = ("A", "B", "C", "D")


def empty_project_from_manifest(
    manifest: dict,
    *,
    bpm: float = 120.0,
    time_sig: tuple[int, int] = (4, 4),
    project_name: str | None = None,
    song_id: str = "song_001",
    groups: tuple[str, ...] = GROUPS_DEFAULT,
) -> Project:
    """Build a ``Project`` with one empty-scene ``Song`` from a stems manifest.

    Walks ``manifest.session_tracks`` for each group letter, emits one
    :class:`PadSpec` per slot. ``ClipRef.audio_hash`` is left empty when the
    manifest doesn't carry one (Phase 2 decision: hash if available, otherwise
    empty; populating at COMMIT time is a Phase 3 concern). ``ClipRef.path``
    falls back to whichever of ``file_path`` / ``file`` is present, mirroring
    the resolver's hybrid-key tolerance.

    ``scenes`` is empty — this builder is for the "manifest-only, no arrangement
    yet" path (e.g. the configurator popup opening on a forge output before
    locators have been dropped).
    """
    session = manifest.get("session_tracks") or {}
    project_groups: list[GroupSpec] = []
    for group_letter in groups:
        entries = session.get(group_letter) or session.get(group_letter.lower()) or []
        pads: list[PadSpec] = []
        for entry in entries:
            slot = int(entry["slot"])
            file_path = entry.get("file_path") or entry.get("file")
            length = entry.get("clip_length_sec")
            audio_hash = str(entry.get("audio_hash") or "")
            pads.append(
                PadSpec(
                    pad_id=str(slot + 1),
                    clip=ClipRef(
                        audio_hash=audio_hash,
                        path=str(file_path) if file_path is not None else None,
                    ),
                    play_mode="oneshot",
                    stretch_mode="bpm",
                    bars=infer_bars(float(length), bpm) if length is not None else None,
                )
            )
        project_groups.append(GroupSpec(group_id=group_letter, pads=pads))

    return Project(
        schema_version=2,
        name=project_name or "",
        songs=[
            Song(
                song_id=song_id,
                bpm=float(bpm),
                time_sig=time_sig,
                groups=project_groups,
                scenes=[],
            )
        ],
    )


__all__ = ["GROUPS_DEFAULT", "empty_project_from_manifest"]
