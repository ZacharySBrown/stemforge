"""Pydantic request/response schemas for the configurator HTTP API.

These models describe the **wire format** of the ``/intent/*`` endpoints
and the ``IntentResponse`` envelope every mutation handler returns. They
intentionally do **not** redefine the underlying scene model — that lives
in :mod:`stemforge.scene_model` and stays the single source of truth.

Each request model maps 1:1 to a handler in :mod:`.intents`. The
``Literal`` constraints (group letters, pad indices, format profiles)
exist so pydantic returns ``422`` with a structured error before the
handler runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from stemforge.scene_model import FormatProfile, Project

GroupLetter = Literal["A", "B", "C", "D"]
ExportTarget = Literal["ep133"]


# ── Intent requests ──────────────────────────────────────────────────────────


class LoadManifestRequest(BaseModel):
    """Replace current state with a project built from a stems manifest."""

    manifest_path: Path
    project_name: str | None = None
    bpm: float = 120.0
    time_sig: tuple[int, int] = (4, 4)

    model_config = {"extra": "forbid"}


class CommitRequest(BaseModel):
    """Reconcile observed session/arrangement tracks into the slot table.

    The M4L device may POST a fresh ``session_tracks`` block directly
    (Phase 2.5 COMMIT flow), or trigger a re-read from
    ``manifest_path``'s ``curated/manifest.json``. Audio hashes are
    populated as part of this intent (closes Phase 2 loose-end #1).
    """

    session_tracks: dict[str, list[dict[str, Any]]] | None = None
    manifest_path: Path | None = None
    populate_audio_hash: bool = True

    model_config = {"extra": "forbid"}


class AssignPadRequest(BaseModel):
    group: GroupLetter
    pad: int = Field(..., ge=1, le=12)
    clip_id: str | None = None  # ``audio_hash`` of the clip to assign
    clip_path: str | None = None  # advisory; recorded on the ClipRef
    name: str | None = None

    model_config = {"extra": "forbid"}


class ClearPadRequest(BaseModel):
    group: GroupLetter
    pad: int = Field(..., ge=1, le=12)

    model_config = {"extra": "forbid"}


class SetGroupFormatRequest(BaseModel):
    group: GroupLetter
    format: FormatProfile  # mirrors stemforge.scene_model.FormatProfile

    model_config = {"extra": "forbid"}


class RecomputeRequest(BaseModel):
    """No-op-bodied trigger; recomputes derived state (bars, memory budget)."""

    # Intentionally empty: the body's presence is the signal. Reserving
    # for future "scope" flags (e.g. ``bars=True, memory=False``).
    model_config = {"extra": "forbid"}


class ExportRequest(BaseModel):
    target: ExportTarget
    out_path: Path
    project_slot: int = Field(default=1, ge=1, le=9)
    reference_template: Path | None = None

    model_config = {"extra": "forbid"}


# ── Response envelope ────────────────────────────────────────────────────────


class IntentResponse(BaseModel):
    """Uniform response shape for every ``/intent/*`` POST.

    ``ok=True`` ⇒ ``state`` is the new ``Project``; mutations were applied.
    ``ok=False`` ⇒ ``state`` is ``None``; ``errors`` populated; no
    mutation occurred (handlers must roll back on partial failure).
    """

    ok: bool
    state: Project | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ── SSE event payloads (documented; not strictly required by FastAPI) ────────


class StateEvent(BaseModel):
    """``event: state`` payload — the full Project JSON."""

    project: Project

    model_config = {"extra": "forbid"}


class LogEvent(BaseModel):
    """``event: log`` payload — human-readable line for the strip device."""

    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str
    ts: float

    model_config = {"extra": "forbid"}


class ProgressEvent(BaseModel):
    """``event: progress`` payload — long-running operation status."""

    op: str
    progress: float = Field(..., ge=0.0, le=1.0)
    message: str = ""
    ts: float

    model_config = {"extra": "forbid"}


class ErrorEvent(BaseModel):
    """``event: error`` payload — non-fatal error surfaced to subscribers."""

    code: str
    message: str
    ts: float

    model_config = {"extra": "forbid"}


__all__ = [
    "AssignPadRequest",
    "ClearPadRequest",
    "CommitRequest",
    "ErrorEvent",
    "ExportRequest",
    "ExportTarget",
    "GroupLetter",
    "IntentResponse",
    "LoadManifestRequest",
    "LogEvent",
    "ProgressEvent",
    "RecomputeRequest",
    "SetGroupFormatRequest",
    "StateEvent",
]
