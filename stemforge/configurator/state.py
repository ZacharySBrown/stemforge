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
        """
        from .curation_io import list_curations  # local: avoid import cycle

        try:
            current_state = load_state(self.state_path)
            active_curations = current_state.active_curations
        except (FileNotFoundError, json.JSONDecodeError):
            active_curations = {}
        names = [p.stem for p in list_curations(self.curations_dir)]
        await self.broadcast(
            SseEvent(
                event="state",
                data={
                    "kind": "curations",
                    "curations": names,
                    "active_curations": active_curations,
                    "ts": time.time(),
                },
            )
        )

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
    "get_active_curation",
    "load_state",
    "save_state",
    "set_active_curation",
]
