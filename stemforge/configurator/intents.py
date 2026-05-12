"""Intent handlers — one async function per ``/intent/*`` endpoint.

Each handler:

1. Acquires ``state.mutation_lock`` (single-writer discipline, spec v4
   Decision 15).
2. Mutates ``state.project`` in place — or constructs a fresh
   :class:`Project` for ``load-manifest``.
3. Returns an :class:`IntentResponse` with ``ok=True`` on success.
4. Broadcasts a ``state`` SSE event so subscribers can re-render.
5. On failure, **does not** mutate; returns ``ok=False`` with populated
   ``errors``.

Handlers never raise — every failure surfaces as a structured error in
the response envelope. The FastAPI route is responsible for HTTP-status
mapping (200 with ``ok=False`` is acceptable here because the request
*shape* was valid; pydantic 422 covers shape errors).
"""

from __future__ import annotations

import json
from pathlib import Path

from stemforge.scene_model import (
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    Song,
    empty_project_from_manifest,
)

from .audio_hash import audio_hash
from .schemas import (
    AssignPadRequest,
    ClearPadRequest,
    CommitRequest,
    ExportRequest,
    IntentResponse,
    LoadManifestRequest,
    RecomputeRequest,
    SetGroupFormatRequest,
)
from .state import AppState

DEFAULT_GROUPS = ("A", "B", "C", "D")
PADS_PER_GROUP = 12


def _ensure_song(project: Project) -> Song:
    """Return ``project.songs[0]``, creating an empty one if missing."""
    if not project.songs:
        project.songs.append(
            Song(
                song_id="song_001",
                name="",
                bpm=120.0,
                groups=[GroupSpec(group_id=g) for g in DEFAULT_GROUPS],
                scenes=[],
            )
        )
    return project.songs[0]


def _ensure_group(song: Song, group_id: str) -> GroupSpec:
    for g in song.groups:
        if g.group_id == group_id:
            return g
    new = GroupSpec(group_id=group_id)
    song.groups.append(new)
    return new


def _ensure_pad(group: GroupSpec, pad_idx: int) -> PadSpec:
    """Return the pad whose ``pad_id`` matches ``str(pad_idx)``; create on demand."""
    target = str(pad_idx)
    for pad in group.pads:
        if pad.pad_id == target:
            return pad
    new = PadSpec(pad_id=target)
    group.pads.append(new)
    return new


# ── Handlers ─────────────────────────────────────────────────────────────────


async def handle_load_manifest(state: AppState, req: LoadManifestRequest) -> IntentResponse:
    """Replace state with a fresh project built from a stems manifest.

    Wraps :func:`empty_project_from_manifest`. The manifest's
    ``session_tracks`` block is the source of truth for the seed slot
    table; audio hashes are NOT populated here — that's
    ``/intent/commit``'s job (so the load step stays fast).
    """
    path = Path(req.manifest_path).expanduser()
    if not path.is_file():
        await state.error("manifest_not_found", f"manifest not found: {path}")
        return IntentResponse(
            ok=False,
            errors=[f"manifest not found: {path}"],
        )

    try:
        manifest = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        await state.error("manifest_unreadable", f"could not read manifest: {exc}")
        return IntentResponse(
            ok=False,
            errors=[f"could not read manifest at {path}: {exc}"],
        )

    bpm = float(manifest.get("bpm") or req.bpm)

    async with state.mutation_lock:
        state.project = empty_project_from_manifest(
            manifest,
            bpm=bpm,
            time_sig=req.time_sig,
            project_name=req.project_name or path.stem,
        )
        state.last_manifest_path = str(path.resolve())

    await state.log(f"loaded manifest from {path}", "info")
    await state.broadcast_state()
    return IntentResponse(ok=True, state=state.project, warnings=state.project.validate_v1())


async def handle_commit(state: AppState, req: CommitRequest) -> IntentResponse:
    """Reconcile observed session/arrangement tracks into the slot table.

    Two driving modes (in priority order):

    1. ``req.session_tracks`` populated — apply that block directly. The
       M4L COMMIT path uses this.
    2. ``req.manifest_path`` populated — re-read ``curated/manifest.json``
       from disk.

    Audio hashes are populated when ``populate_audio_hash=True`` (default)
    using the channel-collapse-invariant :func:`audio_hash` helper. Pads
    whose clip file can't be found are recorded with an empty
    ``audio_hash`` and a warning.
    """
    warnings: list[str] = []

    if req.session_tracks is not None:
        session_tracks = req.session_tracks
    elif req.manifest_path is not None:
        path = Path(req.manifest_path).expanduser()
        if not path.is_file():
            return IntentResponse(ok=False, errors=[f"manifest not found: {path}"])
        try:
            manifest = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            return IntentResponse(ok=False, errors=[f"could not read manifest at {path}: {exc}"])
        session_tracks = manifest.get("session_tracks") or {}
    else:
        return IntentResponse(
            ok=False,
            errors=[
                "commit requires either session_tracks or manifest_path; neither was provided."
            ],
        )

    async with state.mutation_lock:
        song = _ensure_song(state.project)
        for group_letter in DEFAULT_GROUPS:
            entries = (
                session_tracks.get(group_letter) or session_tracks.get(group_letter.lower()) or []
            )
            group = _ensure_group(song, group_letter)
            # Reset the group's pads to mirror the observed entries.
            # COMMIT is authoritative for *this* reconciliation; user-driven
            # assign-pad calls after this will layer on top.
            new_pads: list[PadSpec] = []
            for entry in entries:
                slot = int(entry.get("slot", len(new_pads)))
                pad_id = str(slot + 1)
                file_path = entry.get("file_path") or entry.get("file")
                hash_val = str(entry.get("audio_hash") or "")
                if req.populate_audio_hash and not hash_val and file_path:
                    try:
                        hash_val = audio_hash(file_path)
                    except (FileNotFoundError, RuntimeError) as exc:
                        warnings.append(f"could not hash {file_path}: {exc}")
                clip = ClipRef(
                    audio_hash=hash_val,
                    path=str(file_path) if file_path else None,
                    name=entry.get("name"),
                    source_bpm=(float(entry["source_bpm"]) if entry.get("source_bpm") else None),
                    end_offset_sec=(
                        float(entry["clip_length_sec"])
                        if entry.get("clip_length_sec") is not None
                        else None
                    ),
                )
                new_pads.append(
                    PadSpec(
                        pad_id=pad_id,
                        clip=clip,
                        play_mode="oneshot",
                        stretch_mode="bpm",
                    )
                )
            group.pads = new_pads

    await state.log("committed session_tracks", "info")
    await state.broadcast_state()
    return IntentResponse(ok=True, state=state.project, warnings=warnings)


async def handle_assign_pad(state: AppState, req: AssignPadRequest) -> IntentResponse:
    """Set the clip on ``(group, pad)``.

    ``clip_id`` is the ``audio_hash`` of an existing clip in the project,
    OR (when ``clip_path`` is also provided) a fresh hash for a new clip.
    Either way, the pad's ``ClipRef.audio_hash`` becomes the canonical
    identity.
    """
    if req.clip_id is None and req.clip_path is None:
        return IntentResponse(
            ok=False,
            errors=["assign-pad requires clip_id or clip_path"],
        )

    warnings: list[str] = []
    async with state.mutation_lock:
        song = _ensure_song(state.project)
        group = _ensure_group(song, req.group)
        pad = _ensure_pad(group, req.pad)

        hash_val = req.clip_id or ""
        if req.clip_path and not hash_val:
            try:
                hash_val = audio_hash(req.clip_path)
            except (FileNotFoundError, RuntimeError) as exc:
                warnings.append(f"could not hash {req.clip_path}: {exc}")

        pad.clip = ClipRef(
            audio_hash=hash_val,
            path=req.clip_path,
            name=req.name,
        )

    await state.log(f"assigned pad {req.group}{req.pad}", "info")
    await state.broadcast_state()
    return IntentResponse(ok=True, state=state.project, warnings=warnings)


async def handle_clear_pad(state: AppState, req: ClearPadRequest) -> IntentResponse:
    """Drop the clip on ``(group, pad)``. Pad row stays in the model."""
    async with state.mutation_lock:
        song = _ensure_song(state.project)
        group = _ensure_group(song, req.group)
        pad = _ensure_pad(group, req.pad)
        pad.clip = None

    await state.log(f"cleared pad {req.group}{req.pad}", "info")
    await state.broadcast_state()
    return IntentResponse(ok=True, state=state.project)


async def handle_set_group_format(
    state: AppState,
    req: SetGroupFormatRequest,
) -> IntentResponse:
    """Update a group's ``format_profile`` (spec v4 Decision 16)."""
    async with state.mutation_lock:
        song = _ensure_song(state.project)
        group = _ensure_group(song, req.group)
        group.format_profile = req.format

    await state.log(f"set group {req.group} format to {req.format}", "info")
    await state.broadcast_state()
    return IntentResponse(ok=True, state=state.project)


async def handle_recompute(state: AppState, req: RecomputeRequest) -> IntentResponse:
    """Re-broadcast state; future work derives bars + memory budget here."""
    async with state.mutation_lock:
        # No-op for now — derived state is computed on read. The intent
        # exists so Lane B's UI can force a refresh without mutating.
        pass

    await state.log("recompute triggered", "info")
    await state.broadcast_state()
    return IntentResponse(
        ok=True,
        state=state.project,
        warnings=state.project.validate_v1(),
    )


async def handle_export(state: AppState, req: ExportRequest) -> IntentResponse:
    """Export the current project to a hardware target's bundle format.

    Today only ``target="ep133"`` is wired; the projector's
    ``project_from_spec`` or ``project_kit`` path is selected based on
    whether the project has scenes (``project_from_spec``) or is a
    single-scene kit (``project_kit``). Writes the resulting bytes to
    ``out_path`` and emits start/finish progress SSE events.
    """
    # Heavy import deferred so module-load doesn't pull mido / EP-133 deps
    # for routes that never touch them.
    from stemforge.exporters.ep133.clip_index import ClipIndex
    from stemforge.exporters.ep133.projector import Ep133Projector

    warnings: list[str] = []
    out_path = Path(req.out_path).expanduser()

    await state.progress("export", 0.0, f"Exporting to {req.target} → {out_path.name}")

    async with state.mutation_lock:
        snapshot = state.project.model_copy(deep=True)

    projector = Ep133Projector()
    warnings.extend(projector.validate_spec(snapshot))
    if not snapshot.songs:
        await state.progress("export", 1.0, "Aborted: no songs.")
        return IntentResponse(
            ok=False,
            errors=["project has no songs; nothing to export"],
        )

    song = snapshot.songs[0]
    has_scenes = bool(song.scenes)

    try:
        await state.progress("export", 0.25, "Synthesizing bytes...")
        if has_scenes:
            # Song-mode path needs a manifest to resolve scene-aligned
            # snapshots. For now require the manifest was loaded via
            # /intent/load-manifest and is on disk.
            if not state.last_manifest_path:
                return IntentResponse(
                    ok=False,
                    errors=[
                        "scene-mode export requires a loaded manifest; "
                        "call /intent/load-manifest first."
                    ],
                )
            manifest = json.loads(Path(state.last_manifest_path).read_text())
            payload = projector.project_from_spec(
                snapshot,
                manifest,
                project_slot=req.project_slot,
                reference_template=req.reference_template,
            )
        else:
            # Workflow B (single-scene kit). Build a federated clip index
            # rooted at ``last_manifest_path`` when present; otherwise the
            # ClipRef.path fallbacks are used by the kit synthesizer.
            clip_index = ClipIndex()
            if state.last_manifest_path:
                clip_index.add_manifest(Path(state.last_manifest_path))
            payload = projector.project_kit(
                snapshot,
                clip_index,
                project_slot=req.project_slot,
                reference_template=req.reference_template,
            )
    except Exception as exc:  # noqa: BLE001
        await state.error("export_failed", str(exc))
        return IntentResponse(
            ok=False,
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)
    await state.progress("export", 1.0, f"Wrote {len(payload)} bytes to {out_path}")
    await state.log(f"exported {len(payload)} bytes to {out_path}", "info")
    return IntentResponse(ok=True, state=snapshot, warnings=warnings)


__all__ = [
    "handle_assign_pad",
    "handle_clear_pad",
    "handle_commit",
    "handle_export",
    "handle_load_manifest",
    "handle_recompute",
    "handle_set_group_format",
]
