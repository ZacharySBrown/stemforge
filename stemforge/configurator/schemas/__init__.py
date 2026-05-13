"""Pydantic models for the configurator v1 data model.

These models describe the **on-disk file shapes** that connect StemForge's
three nouns:

- **Forge** (`auto_curation_manifest.json` / `arrangement_manifest.json`)
- **Curation** (`~/stemforge/curations/<name>.yaml`)
- **State** (`~/stemforge/.stemforge_state.json`)

Authoritative spec: `specs/CONSOLIDATED_DESIGN.md` §2.

These models are imported by:

- the server's atomic write path (Phase 1B)
- the device's COMMIT payload validator (Phase 2)
- the TypeScript codegen (`scripts/gen_typescript_types.py`)
- pytest round-trip / fixture-validation suites

Every model is ``extra="forbid"`` so typo'd fields raise at parse time
instead of silently dropping.
"""

from __future__ import annotations

from .curation import (
    ClipSettings,
    Curation,
    Group,
    LastBounce,
    LastExport,
    Pad,
    PadSource,
    ReferencedForge,
    Target,
)
from .forge import ArrangementChunk, ArrangementManifest, ForgeClip, ForgeManifest

# Phase 1B/2 intent-wire schemas (previously stemforge/configurator/schemas.py).
# Re-exported here so existing imports
# `from stemforge.configurator.schemas import AssignPadRequest, ...` keep
# working unchanged; the migration is purely about file layout.
from .intent_wire import (
    AssignPadRequest,
    ClearPadRequest,
    CommitRequest,
    ErrorEvent,
    ExportRequest,
    ExportTarget,
    GroupLetter,
    IntentResponse,
    LoadManifestRequest,
    LogEvent,
    ProgressEvent,
    RecomputeRequest,
    SetGroupFormatRequest,
    StateEvent,
)
from .state import StemforgeState

__all__ = [
    # New configurator v1 (Phase 0) — file shapes.
    "ArrangementChunk",
    "ArrangementManifest",
    "ClipSettings",
    "Curation",
    "ForgeClip",
    "ForgeManifest",
    "Group",
    "LastBounce",
    "LastExport",
    "Pad",
    "PadSource",
    "ReferencedForge",
    "StemforgeState",
    "Target",
    # Legacy intent-wire schemas (preserved for intents.py / server.py).
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
