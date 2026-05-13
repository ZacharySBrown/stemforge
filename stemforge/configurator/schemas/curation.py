"""Curation file schema (``~/stemforge/curations/<name>.yaml``).

Mirrors the YAML shape from `specs/CONSOLIDATED_DESIGN.md` §2.3 verbatim.

A **Curation** is the named, persistable artifact representing one curation
pass: which clips go in which pads, which config templates apply per group,
what target device, when it was last bounced/exported. Curations reference
one or more *forges* by slug; they do not embed clip audio.

Schema rules (from spec §2.3):

- Empty pads are present as ``{pad_id: X}`` with no ``source``. Don't omit
  them — pad ordering and identity is preserved.
- ``audio_path`` in the ``source`` block is denormalized for resilience.
- ``clip_settings`` captures Live-side state at COMMIT.
- ``referenced_forges`` is computed at COMMIT from the union of pad sources.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClipSettings(BaseModel):
    """Live-side clip state captured at COMMIT.

    Persisted so the next LOAD restores warp/loop faithfully.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    warp_bpm: float = Field(..., description="Clip's warp BPM in Live at commit time")
    loop_start_bar: float = Field(0.0, description="Loop start in bars (clip-relative)")
    loop_end_bar: float = Field(..., description="Loop end in bars (clip-relative)")
    looping: bool = Field(default=True, description="Whether the clip is looping in Live")


class PadSource(BaseModel):
    """Reference to a forge clip that lives in a pad."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    forge: str = Field(..., description="Forge slug")
    clip_id: str = Field(..., description="Clip ID within the forge's auto_curation_manifest")
    audio_path: str = Field(
        ...,
        description=(
            "Cached resolved relative path under the forge dir. "
            "Always recompute from the forge manifest at LOAD."
        ),
    )


class Pad(BaseModel):
    """A single slot in a curation's curated_layout.

    ``pad_id`` is required and identifies the slot (e.g. ``A01``).
    ``source`` and ``clip_settings`` are omitted on empty pads.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    pad_id: str = Field(..., description="Pad identifier, e.g. A01")
    source: PadSource | None = None
    clip_settings: ClipSettings | None = None


class Group(BaseModel):
    """A row of pads in a curation.

    EP-133 v1 has 4 groups (A/B/C/D), 12 pads each.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    label: str = Field("", description="Human-readable group label")
    template: str | None = Field(
        None,
        description="Template name (no .adg suffix). None = dry passthrough.",
    )
    pads: list[Pad] = Field(default_factory=list)


class Target(BaseModel):
    """Curation's target device + pad geometry."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    device: str = Field("ep133", description="Target device identifier (ep133 only in v1)")
    groups: int = Field(4, ge=1, le=16, description="Number of groups")
    pads_per_group: int = Field(12, ge=1, le=32, description="Pads per group")


class ReferencedForge(BaseModel):
    """One entry in a curation's ``referenced_forges`` list.

    Used for stale-detection: if the forge's current manifest_hash differs
    from the value recorded here, the popup surfaces a stale badge.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    slug: str
    manifest_hash: str = Field(..., description="auto_curation_manifest hash at last commit")


class LastBounce(BaseModel):
    """Record of the most recent BOUNCE for this curation."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    bounced_at: datetime
    manifest_path: str = Field(..., description="Relative path to bounce_manifest.json")
    pad_audio_hashes: dict[str, str] = Field(
        default_factory=dict,
        description="pad_id → SHA-256 of bounced WAV (for diff detection)",
    )


class LastExport(BaseModel):
    """Record of the most recent EXPORT for this curation."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    exported_at: datetime
    target_format: Literal["ppak"] = "ppak"
    output_path: str = Field(..., description="Absolute or relative path to exported artifact")


class Curation(BaseModel):
    """Top-level curation document.

    Persisted as YAML at ``~/stemforge/curations/<name>.yaml``.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    curation_version: Literal[1] = 1
    name: str = Field(..., description="Unique curation name (matches filename without .yaml)")
    type: Literal["deck", "arrangement"] = Field(
        "deck",
        description="Curation type. v1 implements 'deck' only; 'arrangement' reserved for v2.",
    )
    created_at: datetime
    modified_at: datetime
    target: Target
    referenced_forges: list[ReferencedForge] = Field(default_factory=list)
    groups: dict[str, Group] = Field(
        default_factory=dict,
        description="Group letter (A, B, ...) → Group. Determined by target.groups.",
    )
    last_bounce: LastBounce | None = None
    last_export: LastExport | None = None
