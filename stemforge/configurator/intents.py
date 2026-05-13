"""Intent handlers — one async function per HTTP endpoint.

Two families of handlers live here:

* **Legacy /intent/\\*** — scene-model intents inherited from the v0.2
  configurator (load-manifest, commit-by-session-tracks, assign-pad,
  clear-pad, set-group-format, recompute, export). These keep working
  unchanged so Lane 1C/1D + the running M4L device aren't disrupted
  mid-migration.
* **Curation CRUD /curations/\\*** — the new Phase 1B surface from spec
  §4.3. Each handler reads/writes a ``Curation`` YAML file under
  ``state.curations_dir`` via :mod:`curation_io` and the
  ``.stemforge_state.json`` active-curation map via :mod:`state`.

Discipline (both families):

1. Acquire ``state.mutation_lock`` (single-writer per process, spec v4
   Decision 15) before any read-modify-write cycle.
2. For curation files: hold a :func:`curation_io.lock_curation`
   advisory lock so cross-process writers serialize too.
3. Mutate filesystem + in-memory state.
4. Broadcast a ``state`` SSE event so subscribers can re-render.
5. On failure, raise :class:`fastapi.HTTPException` with an explicit
   status code (404/409/400). Legacy ``/intent/*`` handlers retain the
   ``IntentResponse`` envelope contract.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from stemforge.scene_model import (
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    Song,
    empty_project_from_manifest,
)

from .audio_hash import audio_hash
from .curation_io import (
    curation_path,
    is_valid_curation_name,
    list_curations,
    lock_curation,
    read_curation,
    write_curation_atomic,
)
from .schemas import (
    AssignPadRequest,
    ClearPadRequest,
    CommitRequest,
    Curation,
    ExportRequest,
    Group,
    IntentResponse,
    LoadManifestRequest,
    Pad,
    PadSource,
    RecomputeRequest,
    SetGroupFormatRequest,
    Target,
)
from .state import (
    AppState,
    load_state,
    set_active_curation,
)

DEFAULT_GROUPS = ("A", "B", "C", "D")
PADS_PER_GROUP = 12

# Group-letter sequence used to seed empty curations. Targeted at v1's
# EP-133 4-group layout but extends to any ``target.groups`` up to 16.
_ALL_GROUP_LETTERS = "ABCDEFGHIJKLMNOP"


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


# ── Curation CRUD (Phase 1B) ─────────────────────────────────────────────────


class CreateCurationBody(BaseModel):
    """Body of ``POST /curations``."""

    name: str
    target: Target = Field(default_factory=Target)

    model_config = {"extra": "forbid"}


class OpenCurationBody(BaseModel):
    """Body of ``POST /curations/{name}/open``.

    ``als_path`` keys the active-curation map (one per Live project). In
    Phase 1B device-to-server wiring is deferred (Phase 4A); meanwhile
    callers must pass it explicitly so the active-curation file stays a
    real shared resource across surfaces.
    """

    als_path: str

    model_config = {"extra": "forbid"}


class SaveAsBody(BaseModel):
    """Body of ``POST /curations/{name}/save-as``."""

    new_name: str
    als_path: str | None = Field(
        default=None,
        description="Optional .als path to update the active-curation map for.",
    )

    model_config = {"extra": "forbid"}


class PatchTemplateBody(BaseModel):
    """Body of ``PATCH /curations/{name}/template``."""

    group_letter: str = Field(..., min_length=1, max_length=1)
    template_name: str | None = Field(
        default=None,
        description="Template name without .adg suffix; ``null`` clears the assignment.",
    )

    model_config = {"extra": "forbid"}


class PatchTargetBody(BaseModel):
    """Body of ``PATCH /curations/{name}/target``.

    Any subset of fields may be supplied — unspecified fields preserve
    their current value. ``label`` is per-group (a stretch field for
    callers that want to relabel a group without sending the full
    target). When provided alongside ``groups``, the label binding picks
    the first letter (``A``) by convention.
    """

    groups: int | None = Field(default=None, ge=1, le=16)
    pads_per_group: int | None = Field(default=None, ge=1, le=32)
    device: str | None = None
    # The spec also mentions ``color_palette`` and ``label`` — neither
    # field exists on the Phase 0 Target/Group schema today. We accept
    # them so the wire shape from spec §4.3 is honored and store
    # ``label`` on the first group when present. ``color_palette`` is
    # accepted-and-ignored at this phase (no schema slot).
    color_palette: list[str] | None = None
    label: str | None = None

    model_config = {"extra": "forbid"}


class CommitPadSnapshot(BaseModel):
    """One pad's worth of device-side snapshot data on COMMIT.

    Loose-typed on purpose: Phase 2's device walker will fill these in
    from the LOM. ``audio_path`` is resolved against the
    ``referenced_forges`` map in :func:`handle_curation_commit`.
    """

    pad_id: str
    source: PadSource | None = None
    clip_settings: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}


class CommitGroupSnapshot(BaseModel):
    """One group's worth of device-side snapshot data."""

    label: str | None = None
    template: str | None = None
    pads: list[CommitPadSnapshot] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class CommitCurationBody(BaseModel):
    """Body of ``POST /curations/{name}/commit``.

    The device walks its staging tracks, builds one
    :class:`CommitGroupSnapshot` per group, and POSTs the bundle. The
    server validates the resulting :class:`Curation`, writes it
    atomically, and broadcasts state. ``referenced_forges`` is collapsed
    from the union of pad sources.

    Phase 1B note: per the execution plan this endpoint is intentionally
    partial; Phase 2 wires the device-side walker. The shape we accept
    here is the shape Phase 2 will emit.
    """

    groups: dict[str, CommitGroupSnapshot] = Field(default_factory=dict)
    forge_manifest_hashes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map of forge slug → manifest_hash recorded at commit time. "
            "Phase 4B uses this for stale-detection."
        ),
    )

    model_config = {"extra": "forbid"}


# ── Helpers ─────────────────────────────────────────────────────────────────


def _curation_summary(c: Curation) -> dict[str, Any]:
    """Return the index-row shape used by ``GET /curations``."""
    populated = 0
    for group in c.groups.values():
        for pad in group.pads:
            if pad.source is not None:
                populated += 1
    return {
        "name": c.name,
        "type": c.type,
        "target": c.target.model_dump(),
        "group_count": len(c.groups),
        "populated_pad_count": populated,
        "modified_at": c.modified_at.isoformat(),
        "created_at": c.created_at.isoformat(),
        "last_bounce_at": (c.last_bounce.bounced_at.isoformat() if c.last_bounce else None),
        "last_export_at": (c.last_export.exported_at.isoformat() if c.last_export else None),
        "referenced_forges": [f.slug for f in c.referenced_forges],
    }


def _empty_curation(name: str, target: Target) -> Curation:
    """Construct a fresh empty :class:`Curation` shaped per ``target``."""
    now = datetime.now(UTC)
    groups: dict[str, Group] = {}
    for idx in range(target.groups):
        letter = _ALL_GROUP_LETTERS[idx]
        pads = [Pad(pad_id=f"{letter}{slot + 1:02d}") for slot in range(target.pads_per_group)]
        groups[letter] = Group(label="", template=None, pads=pads)
    return Curation(
        name=name,
        type="deck",
        created_at=now,
        modified_at=now,
        target=target,
        referenced_forges=[],
        groups=groups,
    )


def _load_curation_or_404(state: AppState, name: str) -> Curation:
    if not is_valid_curation_name(name):
        raise HTTPException(status_code=400, detail=f"invalid curation name: {name!r}")
    path = curation_path(state.curations_dir, name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"curation not found: {name}")
    try:
        return read_curation(path)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"curation file failed schema validation: {exc.errors()}",
        ) from exc


def _als_path_active_matches(state: AppState, name: str) -> bool:
    """True iff the curation is active for *any* known ``.als`` path."""
    try:
        sf_state = load_state(state.state_path)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return name in sf_state.active_curations.values()


# ── Handlers ────────────────────────────────────────────────────────────────


async def handle_list_curations(state: AppState) -> dict[str, Any]:
    """``GET /curations`` — scan curations dir + return summary rows.

    Returns a dict with ``curations`` (stable-sorted by name) and
    ``active_curations`` (the current ``.als → name`` map). Files that
    fail schema validation are surfaced under ``errors`` rather than
    silently dropped.
    """
    summaries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in list_curations(state.curations_dir):
        try:
            c = read_curation(path)
        except (ValidationError, Exception) as exc:  # noqa: BLE001
            errors.append({"name": path.stem, "error": str(exc)})
            continue
        summaries.append(_curation_summary(c))
    summaries.sort(key=lambda row: row["name"])
    try:
        sf_state = load_state(state.state_path)
        active = sf_state.active_curations
    except (FileNotFoundError, json.JSONDecodeError):
        active = {}
    return {
        "curations": summaries,
        "active_curations": active,
        "errors": errors,
    }


async def handle_create_curation(state: AppState, body: CreateCurationBody) -> Curation:
    """``POST /curations`` — create an empty curation file.

    Rejects malformed names (400) and existing names (409). Writes the
    file atomically under the per-process mutation lock + cross-process
    advisory lock.
    """
    if not is_valid_curation_name(body.name):
        raise HTTPException(status_code=400, detail=f"invalid curation name: {body.name!r}")
    path = curation_path(state.curations_dir, body.name)
    async with state.mutation_lock:
        if path.exists():
            raise HTTPException(status_code=409, detail=f"curation already exists: {body.name}")
        curation = _empty_curation(body.name, body.target)
        with lock_curation(path):
            write_curation_atomic(path, curation)
    await state.log(f"created curation {body.name}", "info")
    await state.broadcast_curations_state()
    return curation


async def handle_get_curation(state: AppState, name: str) -> Curation:
    """``GET /curations/{name}`` — return the full Curation."""
    return _load_curation_or_404(state, name)


async def handle_open_curation(
    state: AppState,
    name: str,
    body: OpenCurationBody,
) -> dict[str, Any]:
    """``POST /curations/{name}/open`` — set active in state file.

    Phase 1B accepts an explicit ``als_path`` in the body so this works
    in the absence of device-to-server wiring (Phase 4A). Once the
    device emits its current ``.als`` path on every connection, the
    body can become optional.
    """
    curation = _load_curation_or_404(state, name)
    async with state.mutation_lock:
        sf_state = set_active_curation(body.als_path, curation.name, state.state_path)
    await state.log(f"opened curation {name} for {body.als_path}", "info")
    await state.broadcast_curations_state()
    return {
        "curation": curation.model_dump(mode="json"),
        "active_curations": sf_state.active_curations,
    }


async def handle_save_as(
    state: AppState,
    name: str,
    body: SaveAsBody,
) -> Curation:
    """``POST /curations/{name}/save-as`` — copy + switch active."""
    if not is_valid_curation_name(body.new_name):
        raise HTTPException(status_code=400, detail=f"invalid curation name: {body.new_name!r}")
    src = curation_path(state.curations_dir, name)
    if not src.is_file():
        raise HTTPException(status_code=404, detail=f"curation not found: {name}")
    dst = curation_path(state.curations_dir, body.new_name)
    async with state.mutation_lock:
        if dst.exists():
            raise HTTPException(
                status_code=409, detail=f"destination curation exists: {body.new_name}"
            )
        # Read, rewrite ``name`` field, persist via atomic write so the
        # ``modified_at`` timestamp + name field are consistent. A naive
        # ``shutil.copy2`` would leave the duplicated file claiming the
        # original name internally.
        source_curation = read_curation(src)
        cloned = source_curation.model_copy(deep=True)
        cloned.name = body.new_name
        cloned.modified_at = datetime.now(UTC)
        with lock_curation(dst):
            write_curation_atomic(dst, cloned)
        if body.als_path:
            set_active_curation(body.als_path, body.new_name, state.state_path)
    await state.log(f"saved {name} as {body.new_name}", "info")
    await state.broadcast_curations_state()
    return cloned


async def handle_delete_curation(state: AppState, name: str) -> dict[str, Any]:
    """``DELETE /curations/{name}`` — remove file unless active."""
    if not is_valid_curation_name(name):
        raise HTTPException(status_code=400, detail=f"invalid curation name: {name!r}")
    path = curation_path(state.curations_dir, name)
    async with state.mutation_lock:
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"curation not found: {name}")
        if _als_path_active_matches(state, name):
            raise HTTPException(
                status_code=409,
                detail=f"refusing to delete active curation {name!r}; close it first",
            )
        with lock_curation(path):
            path.unlink()
            # Best-effort: drop the sidecar lock file too.
            lock_sidecar = path.with_suffix(path.suffix + ".lock")
            try:
                lock_sidecar.unlink()
            except FileNotFoundError:
                pass
    await state.log(f"deleted curation {name}", "info")
    await state.broadcast_curations_state()
    return {"deleted": name}


async def handle_patch_template(
    state: AppState,
    name: str,
    body: PatchTemplateBody,
) -> Curation:
    """``PATCH /curations/{name}/template`` — set per-group template."""
    path = curation_path(state.curations_dir, name)
    async with state.mutation_lock:
        curation = _load_curation_or_404(state, name)
        letter = body.group_letter.upper()
        if letter not in curation.groups:
            raise HTTPException(
                status_code=404,
                detail=f"group {letter!r} not present in curation {name}",
            )
        curation.groups[letter].template = body.template_name
        curation.modified_at = datetime.now(UTC)
        with lock_curation(path):
            write_curation_atomic(path, curation)
    await state.log(f"set template {body.template_name!r} on {name}.{letter}", "info")
    await state.broadcast_curations_state()
    return curation


async def handle_patch_target(
    state: AppState,
    name: str,
    body: PatchTargetBody,
) -> Curation:
    """``PATCH /curations/{name}/target`` — partial-update target metadata.

    Reshaping the pad grid (changing ``groups`` or ``pads_per_group``)
    re-seeds any new group letters with empty pads. Removed letters
    simply disappear; their pad data is lost. Per the plan, the device
    side ("recreate staging tracks for new target") is wired in Phase 2.
    """
    path = curation_path(state.curations_dir, name)
    async with state.mutation_lock:
        curation = _load_curation_or_404(state, name)
        new_target = curation.target.model_copy(deep=True)
        if body.device is not None:
            new_target.device = body.device
        if body.groups is not None:
            new_target.groups = body.groups
        if body.pads_per_group is not None:
            new_target.pads_per_group = body.pads_per_group
        curation.target = new_target

        # Re-seed groups if the geometry changed. Preserve existing
        # group data where the letter survives the resize.
        wanted_letters = set(_ALL_GROUP_LETTERS[: new_target.groups])
        for letter in list(curation.groups.keys()):
            if letter not in wanted_letters:
                del curation.groups[letter]
        for idx in range(new_target.groups):
            letter = _ALL_GROUP_LETTERS[idx]
            if letter not in curation.groups:
                pads = [
                    Pad(pad_id=f"{letter}{slot + 1:02d}")
                    for slot in range(new_target.pads_per_group)
                ]
                curation.groups[letter] = Group(label="", template=None, pads=pads)
            else:
                # Resize the existing pad list to match the new
                # pads_per_group. Truncation drops trailing pads.
                pads = curation.groups[letter].pads
                if len(pads) < new_target.pads_per_group:
                    for slot in range(len(pads), new_target.pads_per_group):
                        pads.append(Pad(pad_id=f"{letter}{slot + 1:02d}"))
                elif len(pads) > new_target.pads_per_group:
                    curation.groups[letter].pads = pads[: new_target.pads_per_group]

        if body.label is not None:
            # The Phase 0 schema attaches label to Group, not Target.
            # Apply to the first group as the "primary" group label —
            # callers wanting per-group labels use template/etc.
            first_letter = _ALL_GROUP_LETTERS[0]
            if first_letter in curation.groups:
                curation.groups[first_letter].label = body.label

        curation.modified_at = datetime.now(UTC)
        with lock_curation(path):
            write_curation_atomic(path, curation)

    await state.log(f"patched target on {name}", "info")
    await state.broadcast_curations_state()
    return curation


async def handle_curation_commit(
    state: AppState,
    name: str,
    body: CommitCurationBody,
) -> Curation:
    """``POST /curations/{name}/commit`` — accept a device snapshot.

    Phase 1B: validates the shape, merges the snapshot into the curation,
    collapses ``referenced_forges`` from pad sources, persists atomically.
    Phase 2 will produce the body from the device-side LOM walker.
    """
    path = curation_path(state.curations_dir, name)
    async with state.mutation_lock:
        curation = _load_curation_or_404(state, name)
        # Build replacement groups dict. Snapshot wins for any group it
        # contains; groups absent from the snapshot are left as-is.
        for raw_letter, group_snap in body.groups.items():
            letter = raw_letter.upper()
            new_pads: list[Pad] = []
            for pad_snap in group_snap.pads:
                # Build the Pad through model_validate so the loose-typed
                # ``clip_settings`` dict from the device is funneled through
                # the Phase 0 Pydantic validator instead of trusting blind.
                pad_dict: dict[str, Any] = {"pad_id": pad_snap.pad_id}
                if pad_snap.source is not None:
                    pad_dict["source"] = pad_snap.source.model_dump()
                if pad_snap.clip_settings is not None:
                    pad_dict["clip_settings"] = pad_snap.clip_settings
                try:
                    new_pads.append(Pad.model_validate(pad_dict))
                except ValidationError as exc:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "pad_id": pad_snap.pad_id,
                            "errors": exc.errors(),
                        },
                    ) from exc
            existing = curation.groups.get(letter)
            label = (
                group_snap.label
                if group_snap.label is not None
                else (existing.label if existing else "")
            )
            template = (
                group_snap.template
                if group_snap.template is not None
                else (existing.template if existing else None)
            )
            curation.groups[letter] = Group(label=label, template=template, pads=new_pads)

        # Collapse referenced_forges from union of pad sources.
        referenced: dict[str, str] = {}
        for group in curation.groups.values():
            for pad in group.pads:
                if pad.source is None:
                    continue
                slug = pad.source.forge
                if slug in body.forge_manifest_hashes:
                    referenced[slug] = body.forge_manifest_hashes[slug]
                elif slug not in referenced:
                    # Preserve any previously-recorded hash for this slug.
                    prior = next(
                        (f.manifest_hash for f in curation.referenced_forges if f.slug == slug),
                        "",
                    )
                    referenced[slug] = prior
        from .schemas import ReferencedForge

        curation.referenced_forges = [
            ReferencedForge(slug=slug, manifest_hash=h) for slug, h in sorted(referenced.items())
        ]

        curation.modified_at = datetime.now(UTC)
        with lock_curation(path):
            write_curation_atomic(path, curation)

    await state.log(f"committed curation {name}", "info")
    await state.broadcast_curations_state()
    return curation


__all__ = [
    "CommitCurationBody",
    "CreateCurationBody",
    "OpenCurationBody",
    "PatchTargetBody",
    "PatchTemplateBody",
    "SaveAsBody",
    "handle_assign_pad",
    "handle_clear_pad",
    "handle_commit",
    "handle_create_curation",
    "handle_curation_commit",
    "handle_delete_curation",
    "handle_export",
    "handle_get_curation",
    "handle_list_curations",
    "handle_load_manifest",
    "handle_open_curation",
    "handle_patch_target",
    "handle_patch_template",
    "handle_recompute",
    "handle_save_as",
    "handle_set_group_format",
]
