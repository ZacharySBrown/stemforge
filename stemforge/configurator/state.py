"""In-memory ProjectSpec + mutation lock + SSE broker + ``.stemforge_state.json`` I/O.

The configurator is **single-writer**: every mutation goes through one of
the ``/intent/*`` or ``/curations/*`` handlers, which acquire
:attr:`AppState.mutation_lock` before touching server state. After a
successful mutation the handler calls :meth:`AppState.broadcast_state`
to push the new state to every SSE subscriber.

The broker is an in-process fan-out — each subscriber owns one
``asyncio.Queue``; the broker holds a list of those queues guarded by the
same mutation lock. On disconnect the subscriber removes itself; nothing
is persisted between server restarts (except the explicit
``~/stemforge/.stemforge_state.json`` file managed by the helpers in this
module).

Persistence layout (per spec §2.4):

- ``~/stemforge/.stemforge_state.json`` — :class:`StemforgeState` JSON.
  Map of ``.als`` absolute path → active curation name. Tiny;
  hand-edit-safe; atomic-write.
- ``~/stemforge/curations/*.yaml`` — see :mod:`curation_io`.

Phase 4A wired the **als-opened bootstrap**: on every Live ``.als`` open,
the device JS posts the project's absolute path to ``POST /als-opened``;
the server consults its in-memory :class:`StemforgeState` cache and
responds with the matching ``active_curation`` (or ``null``) so the
device can auto-load the right curation without user intervention. See
:func:`load_state_with_recovery` and
:attr:`AppState.cached_stemforge_state` for the cache.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from stemforge.scene_model import Project, project_to_json

from .schemas import StemforgeState

EventName = Literal["state", "log", "progress", "error"]


@dataclass
class SseEvent:
    """A single SSE frame to push to subscribers."""

    event: EventName
    data: dict[str, Any]

    def to_wire(self) -> str:
        """Serialize to the ``event: NAME\\ndata: JSON\\n\\n`` form."""
        return f"event: {self.event}\ndata: {json.dumps(self.data, default=str)}\n\n"


@dataclass
class AppState:
    """The mutable world the HTTP app runs against.

    Held as a single attribute on ``app.state.configurator`` — there is
    exactly one per server process. Initialization happens in
    :func:`stemforge.configurator.server.create_app`.
    """

    project: Project = field(default_factory=Project)
    mutation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    subscribers: list[asyncio.Queue[SseEvent]] = field(default_factory=list)
    # The Project's source manifest path (when loaded via load-manifest).
    # Tracked so /intent/commit can re-read from disk without a body.
    last_manifest_path: str | None = None
    # Filesystem roots for curation persistence. Tests override these to
    # point at tmp_path; production callers default to ~/stemforge/...
    curations_dir: Path = field(default_factory=lambda: Path.home() / "stemforge" / "curations")
    state_path: Path = field(
        default_factory=lambda: Path.home() / "stemforge" / ".stemforge_state.json"
    )
    # Phase 4A: in-memory cache of the on-disk :class:`StemforgeState`,
    # primed by :func:`stemforge.configurator.server.create_app`. The
    # ``POST /als-opened`` handler reads from this cache so device
    # bootstrap is one disk-touch at process start, not per-request. The
    # cache is refreshed lazily by readers (``load_state`` always reads
    # disk) and replaced atomically by writers via
    # :meth:`refresh_cached_stemforge_state`.
    cached_stemforge_state: StemforgeState = field(default_factory=StemforgeState)
    # Phase 4B: the broadcaster needs to read forge manifests to compute
    # per-pad stale flags. Mirrors ``app.state.processed_dir`` so the
    # broadcaster can run without reaching into FastAPI state.
    processed_dir: Path = field(default_factory=lambda: Path.home() / "stemforge" / "processed")

    def refresh_cached_stemforge_state(self) -> StemforgeState:
        """Re-read ``.stemforge_state.json`` into the in-memory cache.

        Called by handlers after every write so the cache mirrors disk
        without forcing every reader to round-trip through the filesystem.
        Corruption is handled by :func:`load_state_with_recovery` — a
        malformed file is moved aside and the cache resets to empty so the
        server stays operational.
        """
        self.cached_stemforge_state = load_state_with_recovery(self.state_path)
        return self.cached_stemforge_state

    # ── Subscribers / broker ─────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[SseEvent]:
        """Register a new SSE subscriber. Caller MUST call :meth:`unsubscribe`."""
        q: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=128)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[SseEvent]) -> None:
        """Drop a subscriber's queue. Idempotent."""
        try:
            self.subscribers.remove(q)
        except ValueError:
            pass

    async def broadcast(self, event: SseEvent) -> None:
        """Push ``event`` to every subscriber. Drops on full queue."""
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer — drop this event for them; don't block
                # the broadcaster. Live UIs receive coalesced state via
                # the next event.
                pass

    async def broadcast_state(self) -> None:
        """Convenience: emit a ``state`` event with the current project."""
        await self.broadcast(
            SseEvent(event="state", data=json.loads(project_to_json(self.project)))
        )

    async def broadcast_curations_state(self) -> None:
        """Emit a ``state`` event reflecting the curation index + active map.

        Used by the new curation CRUD endpoints (spec §4.3). The payload
        intentionally mirrors what ``GET /curations`` and the popup's
        SSE-driven curation list want to render.

        Phase 4A: refreshes the in-memory cache before broadcasting so
        all subsequent ``/als-opened`` lookups see the latest map without
        re-reading disk.

        Phase 4B: payload now carries a ``stale_by_curation`` map keyed
        by curation name → ``{pad_id: {stale, current_manifest_hash}}``
        so the popup can render stale badges in ``ForgeList`` (per-forge
        stale count) and ``ActiveCuration`` (per-pad stale indicator)
        without re-resolving every forge in the browser.

        Pre-UAT P0-3: payload-construction factored into
        :func:`current_curations_state` so the cold-start SSE snapshot
        path in ``server.py`` can emit the same shape without a
        full mutation cycle.
        """
        await self.broadcast(SseEvent(event="state", data=current_curations_state(self)))

    async def log(self, message: str, level: str = "info") -> None:
        """Emit a ``log`` SSE event."""
        await self.broadcast(
            SseEvent(
                event="log",
                data={"level": level, "message": message, "ts": time.time()},
            )
        )

    async def progress(self, op: str, progress: float, message: str = "") -> None:
        """Emit a ``progress`` SSE event (0.0 → 1.0)."""
        await self.broadcast(
            SseEvent(
                event="progress",
                data={
                    "op": op,
                    "progress": max(0.0, min(1.0, float(progress))),
                    "message": message,
                    "ts": time.time(),
                },
            )
        )

    async def error(self, code: str, message: str) -> None:
        """Emit an ``error`` SSE event."""
        await self.broadcast(
            SseEvent(
                event="error",
                data={"code": code, "message": message, "ts": time.time()},
            )
        )


# ── Curation-state payload builder (Pre-UAT P0-3) ───────────────────────────


def current_curations_state(state: AppState) -> dict[str, Any]:
    """Build the ``kind: "curations"`` SSE payload for ``state``.

    Pure function — no broadcasting, no SSE wrapping. Mirrors what
    :meth:`AppState.broadcast_curations_state` would push, so the
    cold-start SSE snapshot path in :mod:`server` can emit the same
    shape as every subsequent mutation-driven event.

    Side effect: refreshes the in-memory ``cached_stemforge_state``
    so the result reflects the latest ``.stemforge_state.json`` on
    disk. Matches the legacy behaviour the broadcaster used to
    perform inline.

    Returns:
        Dict ready to drop into ``SseEvent(event="state", data=...)``
        or into the ``GET /state/stream`` initial-snapshot wire.
    """
    from .curation_io import list_curations, read_curation  # local: avoid cycle
    from .stale_check import stale_summary

    # Phase 4A: cache refresh keeps /als-opened lookups disk-free.
    current_state = state.refresh_cached_stemforge_state()
    active_curations = current_state.active_curations
    curation_paths = list_curations(state.curations_dir)
    names = [p.stem for p in curation_paths]

    # Phase 4B: compute per-pad stale flags against current forges.
    forges_by_slug = _load_forges_by_slug(state.processed_dir)
    stale_by_curation: dict[str, dict[str, dict[str, object]]] = {}
    for path in curation_paths:
        try:
            curation = read_curation(path)
        except Exception:  # noqa: BLE001 - mustn't crash on bad files
            continue
        entries = stale_summary(curation, forges_by_slug)
        stale_by_curation[curation.name] = {
            pad_id: entry.to_dict() for pad_id, entry in entries.items()
        }

    return {
        "kind": "curations",
        "curations": names,
        "active_curations": active_curations,
        "stale_by_curation": stale_by_curation,
        "ts": time.time(),
    }


# ── Forge manifest loader (for Phase 4B stale-check) ────────────────────────


def _load_forges_by_slug(processed_dir: Path) -> dict[str, object]:
    """Build ``{slug: ForgeManifest}`` for every loadable forge dir.

    Used by :meth:`AppState.broadcast_curations_state` to feed
    :func:`stemforge.configurator.stale_check.stale_summary`. Forges
    whose manifest fails to parse are skipped (their slugs will
    therefore not appear in the map, causing dependent pads to read as
    stale via the "missing forge" branch). The return type is widened
    to ``dict[str, object]`` to keep the import cycle local — the
    consumer in :mod:`stale_check` is the only place that needs the
    concrete :class:`ForgeManifest` type.
    """
    from stemforge.forge.manifest_io import (
        AUTO_CURATION_FILENAME,
        ForgeManifestError,
        LEGACY_FILENAME,
        LEGACY_PARENT,
        load_forge,
    )

    out: dict[str, object] = {}
    if not processed_dir.is_dir():
        return out
    for child in processed_dir.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        has_new = (child / AUTO_CURATION_FILENAME).is_file()
        has_legacy = (child / LEGACY_PARENT / LEGACY_FILENAME).is_file()
        if not (has_new or has_legacy):
            continue
        try:
            manifest = load_forge(child.name, forge_dir=child)
        except ForgeManifestError:
            continue
        out[child.name] = manifest
    return out


# ── StemforgeState I/O ──────────────────────────────────────────────────────


def load_state(state_path: Path | None = None) -> StemforgeState:
    """Read ``.stemforge_state.json`` and return a :class:`StemforgeState`.

    Returns a default-constructed (empty) state when the file doesn't
    exist yet — first-run behavior. A malformed file raises so the
    caller can decide whether to back it up and reset.
    """
    target = state_path or (Path.home() / "stemforge" / ".stemforge_state.json")
    if not target.is_file():
        return StemforgeState()
    raw = target.read_text()
    if not raw.strip():
        return StemforgeState()
    data = json.loads(raw)
    return StemforgeState.model_validate(data)


def load_state_with_recovery(state_path: Path | None = None) -> StemforgeState:
    """Best-effort variant of :func:`load_state` that survives corruption.

    Phase 4A startup hook. If the state file exists but is malformed
    (truncated mid-write, hand-edited into invalid JSON, schema-version
    drift), this helper moves the bad file aside to
    ``<state_path>.corrupt-<unix-ts>`` and returns a fresh empty
    :class:`StemforgeState` so the server keeps booting. A clean miss
    (file absent / blank) falls through to :func:`load_state`'s default
    empty-state branch — no backup written.

    The backup-on-corruption behaviour means a power-cut between
    ``fsync`` and ``rename`` (`save_state`'s atomic-write pattern) will
    leave the OLD file intact at the real path. Only a half-written final
    file ever triggers the backup; the OS-level atomicity of ``rename``
    on POSIX prevents that on every platform we ship to.
    """
    target = state_path or (Path.home() / "stemforge" / ".stemforge_state.json")
    try:
        return load_state(target)
    except json.JSONDecodeError:
        # Move aside + reset. Preserve the bytes for forensics.
        backup = target.with_name(f"{target.name}.corrupt-{int(time.time())}")
        try:
            os.replace(target, backup)
        except OSError:
            # Couldn't move it — try removing it. Either way we keep
            # serving from an empty in-memory state.
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        return StemforgeState()
    except (ValueError, TypeError):
        # Pydantic ValidationError lands here too (it subclasses
        # ValueError). Same recovery: archive + reset.
        backup = target.with_name(f"{target.name}.corrupt-{int(time.time())}")
        try:
            os.replace(target, backup)
        except OSError:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        return StemforgeState()


def save_state(state: StemforgeState, state_path: Path | None = None) -> None:
    """Atomically persist :class:`StemforgeState` to disk.

    Same write-tmp-then-rename strategy as
    :func:`curation_io.write_curation_atomic` — kept here to avoid a
    cross-module dependency and because the state file is JSON (not
    YAML).
    """
    target = state_path or (Path.home() / "stemforge" / ".stemforge_state.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def get_active_curation(als_path: str, state_path: Path | None = None) -> str | None:
    """Return the active curation name for ``als_path``, or ``None``.

    The lookup key is the path as-given; callers should ``resolve()`` it
    if they want filesystem-level identity. We don't resolve here because
    Phase 4 may want to keep the on-wire path verbatim from Live.
    """
    state = load_state(state_path)
    return state.active_curations.get(als_path)


def set_active_curation(
    als_path: str,
    curation_name: str | None,
    state_path: Path | None = None,
) -> StemforgeState:
    """Set (or clear, when ``curation_name is None``) the active curation.

    Returns the newly-persisted :class:`StemforgeState` so callers can
    feed it into an SSE broadcast without an extra disk read.
    """
    state = load_state(state_path)
    if curation_name is None:
        state.active_curations.pop(als_path, None)
    else:
        state.active_curations[als_path] = curation_name
    state.last_seen_at = datetime.now(UTC)
    save_state(state, state_path)
    return state


__all__ = [
    "AppState",
    "EventName",
    "SseEvent",
    "current_curations_state",
    "get_active_curation",
    "load_state",
    "load_state_with_recovery",
    "save_state",
    "set_active_curation",
]
