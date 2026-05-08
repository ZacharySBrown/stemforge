"""Bidirectional translation between abstract ``Project`` and EP-133 snapshots.

Phase 2 seam: lets the EP-133 projector consume a :class:`Project` while
:func:`synthesize` keeps its existing ``list[Snapshot]`` input contract. This
is what protects byte identity — the byte-shaping function is mechanically
unchanged; this module just shuffles inputs.

Two functions:

- :func:`project_from_arrangement_and_manifest` — forward direction. Calls
  the existing :func:`resolve_scenes` to walk locators × tracks, then
  reshapes into a :class:`Project`.
- :func:`project_to_snapshots` — reverse direction. Walks
  ``project.songs[0].scenes`` and rebuilds ``list[Snapshot]`` byte-equivalent
  to what :func:`resolve_scenes` would have produced.

The reverse path relies on the manifest carrying ``clip_length_sec`` per
session-tracks entry, which the canonical fixture and the forge / arrangement
pipelines both populate. ``ArrangementClip.start_time_sec`` and ``warping``
are reconstructed as placeholders (``0.0`` / ``1``) since
:func:`synthesize` does not consume them.

Removed in Phase 3 once the abstract scene model is the only path.
"""

from __future__ import annotations

from stemforge.scene_model import (
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    SceneSpec,
    Song,
    infer_bars,
    scene_lengths_in_bars,
)

from .song_resolver import (
    GROUPS,
    ArrangementClip,
    Snapshot,
    lookup_pad,
    resolve_scenes,
)


def project_from_arrangement_and_manifest(
    arrangement: dict,
    manifest: dict,
    *,
    project_name: str | None = None,
    song_id: str = "song_001",
) -> Project:
    """Build a fully-populated :class:`Project` from arrangement + manifest.

    Uses :func:`resolve_scenes` for the locator × tracks resolution (so the
    snapshot semantics are word-for-word identical to the direct path), then
    reshapes the resulting snapshots into ``SceneSpec`` entries on a single
    :class:`Song`. The ``Song.groups`` are built from ``manifest.session_tracks``
    so each pad has a stable ``pad_id`` even when the arrangement doesn't
    reference it.
    """
    snapshots = resolve_scenes(arrangement, manifest)

    bpm = float(arrangement.get("tempo", 120.0))
    raw_ts = arrangement.get("time_sig") or [4, 4]
    time_sig = (int(raw_ts[0]), int(raw_ts[1]))
    arrangement_length_sec = arrangement.get("arrangement_length_sec")
    if arrangement_length_sec is not None:
        arrangement_length_sec = float(arrangement_length_sec)

    session = manifest.get("session_tracks") or {}
    groups: list[GroupSpec] = []
    for group_letter in GROUPS:
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
        groups.append(GroupSpec(group_id=group_letter, pads=pads))

    bar_lengths = scene_lengths_in_bars(
        [s.locator_time_sec for s in snapshots],
        bpm,
        arrangement_length_sec,
    )

    scenes: list[SceneSpec] = []
    for i, (snap, bars) in enumerate(zip(snapshots, bar_lengths)):
        pad_by_group: dict[str, str | None] = {}
        for group_letter in GROUPS:
            clip = snap.clip_for(group_letter)
            if clip is None:
                pad_by_group[group_letter] = None
            else:
                pad_num = lookup_pad(manifest, group_letter, clip.file_path)
                pad_by_group[group_letter] = str(pad_num)
        scenes.append(
            SceneSpec(
                scene_id=f"scn_{i + 1:03d}",
                name=snap.locator_name,
                bars=int(bars),
                locator_time_sec=float(snap.locator_time_sec),
                provenance="imported",
                pad_by_group=pad_by_group,
            )
        )

    return Project(
        schema_version=2,
        name=project_name or "",
        songs=[
            Song(
                song_id=song_id,
                bpm=bpm,
                time_sig=time_sig,
                arrangement_length_sec=arrangement_length_sec,
                groups=groups,
                scenes=scenes,
            )
        ],
    )


def project_to_snapshots(project: Project, manifest: dict) -> list[Snapshot]:
    """Rebuild ``list[Snapshot]`` from a :class:`Project` + its source manifest.

    Inverse of :func:`project_from_arrangement_and_manifest` for the EP-133
    consumer. Each ``SceneSpec.pad_by_group`` entry is re-hydrated into an
    :class:`ArrangementClip` whose ``file_path`` and ``length_sec`` come from
    the manifest. ``start_time_sec`` and ``warping`` are placeholder values
    (the synthesizer does not read them).

    Raises ``ValueError`` if the project has zero or more than one song —
    Phase 2 single-song flow only.
    """
    if len(project.songs) != 1:
        raise ValueError(f"project_to_snapshots requires exactly 1 song, got {len(project.songs)}")
    song = project.songs[0]

    session = manifest.get("session_tracks") or {}
    by_group_slot: dict[str, dict[int, dict]] = {}
    for group_letter in GROUPS:
        entries = session.get(group_letter) or session.get(group_letter.lower()) or []
        by_group_slot[group_letter] = {int(e["slot"]): e for e in entries}

    snapshots: list[Snapshot] = []
    for scene in song.scenes:
        clips: dict[str, ArrangementClip | None] = {g: None for g in GROUPS}
        for group_letter in GROUPS:
            pad_id = scene.pad_by_group.get(group_letter)
            if pad_id is None:
                continue
            slot = int(pad_id) - 1
            entry = by_group_slot[group_letter].get(slot)
            if entry is None:
                raise KeyError(
                    f"scene {scene.scene_id!r} references pad {pad_id} on group "
                    f"{group_letter!r} but manifest.session_tracks[{group_letter}] "
                    f"has no slot {slot}"
                )
            file_path = entry.get("file_path") or entry.get("file")
            length_sec = float(entry.get("clip_length_sec") or 0.0)
            clips[group_letter] = ArrangementClip(
                file_path=str(file_path),
                start_time_sec=0.0,
                length_sec=length_sec,
                warping=1,
            )

        snapshots.append(
            Snapshot(
                locator_time_sec=float(scene.locator_time_sec or 0.0),
                locator_name=scene.name,
                a_clip=clips["A"],
                b_clip=clips["B"],
                c_clip=clips["C"],
                d_clip=clips["D"],
            )
        )
    return snapshots


__all__ = ["project_from_arrangement_and_manifest", "project_to_snapshots"]
