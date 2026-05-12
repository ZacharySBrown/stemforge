"""In-memory ProjectSpec + mutation lock + SSE broker.

The configurator is **single-writer**: every mutation goes through one of
the ``/intent/*`` handlers, which acquire :attr:`AppState.mutation_lock`
before touching :attr:`AppState.project`. After a successful mutation the
handler calls :meth:`AppState.broadcast_state` to push the new project to
every SSE subscriber.

The broker is an in-process fan-out — each subscriber owns one
``asyncio.Queue``; the broker holds a list of those queues guarded by the
same mutation lock. On disconnect the subscriber removes itself; nothing
is persisted between server restarts.

There's intentionally **no** persistence layer in this file. Disk
debouncing (spec v4 Decision 15) is a follow-up; Phase 3.1 (this lane)
ships the in-memory contract first.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from stemforge.scene_model import Project, project_to_json

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


__all__ = [
    "AppState",
    "EventName",
    "SseEvent",
]
