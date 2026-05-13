"""Forge manifest schemas (``auto_curation_manifest.json`` + ``arrangement_manifest.json``).

Both manifests live under ``~/stemforge/processed/<slug>/``.

The ``manifest_hash`` field is SHA-256 of the canonical JSON of the
``clips`` (or ``chunks``) array. It's the stale-reference detection
mechanism: a curation stores the manifest_hash it was last committed
against; if the forge's current hash differs, the popup surfaces a stale
badge.

**Critical** (per spec §2.2): re-running auto-curation rewrites
``auto_curation_manifest.json`` but **never touches** ``curations/*.yaml``.
Stale-detection at the curation side is what keeps the system safe across
re-curations.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ForgeClip(BaseModel):
    """One auto-curated clip in a forge."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    clip_id: str
    audio_path: str = Field(..., description="Relative path under the forge dir")
    stem: Literal["drum", "bass", "vocal", "other"]
    source_bar_range: tuple[int, int] = Field(..., description="[start_bar, end_bar] in source")
    duration_bars: int = Field(..., ge=0)
    tags: list[str] = Field(default_factory=list)


class ArrangementChunk(BaseModel):
    """One arrangement-view chunk in a forge."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    chunk_id: str
    audio_path: str = Field(..., description="Relative path under the forge dir")
    stem: Literal["drum", "bass", "vocal", "other"]
    source_position_sec: float = Field(..., ge=0.0)
    duration_sec: float = Field(..., gt=0.0)
    bar_position: int = Field(..., ge=0)
    duration_bars: int = Field(..., ge=0)


class ForgeManifest(BaseModel):
    """Auto-curation manifest (``auto_curation_manifest.json``).

    Schema shape from spec §2.2.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    schema_version: Literal[1] = 1
    forge_slug: str
    source_audio: str = Field(..., description="Absolute path to original audio file")
    bpm: float = Field(..., gt=0.0)
    first_downbeat_sec: float = Field(..., ge=0.0)
    manifest_hash: str = Field(..., description="SHA-256 of canonical clips array")
    default_template: str | None = Field(
        None, description="Template name to apply on LOAD-forge (no .adg suffix)"
    )
    clips: list[ForgeClip] = Field(default_factory=list)


class ArrangementManifest(BaseModel):
    """Arrangement manifest (``arrangement_manifest.json``).

    Schema shape from spec §2.2.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    schema_version: Literal[1] = 1
    forge_slug: str
    source_audio: str
    bpm: float = Field(..., gt=0.0)
    first_downbeat_sec: float = Field(..., ge=0.0)
    manifest_hash: str = Field(..., description="SHA-256 of canonical chunks array")
    chunks: list[ArrangementChunk] = Field(default_factory=list)


# ── manifest_hash helpers ────────────────────────────────────────────────────


def _canonical_json(payload: Any) -> str:
    """Canonical JSON for hashing: sorted keys, no whitespace, UTF-8 safe."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_manifest_hash(items: list[dict[str, Any]]) -> str:
    """SHA-256 of the canonical JSON of a clips/chunks array.

    Per spec §2.2 the ``manifest_hash`` field is the hash of the
    ``clips`` array (auto-curation) or ``chunks`` array (arrangement),
    not the whole manifest dict. ``items`` should be the
    ``model_dump(mode="json")`` form of the list — each entry a dict
    with primitive-only values.

    The function is pure: callers compute the hash, then set
    ``manifest_hash`` on the manifest before serializing it.
    """
    canon = _canonical_json(items)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()
