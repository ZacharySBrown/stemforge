"""Phase 3B: BOUNCE refactor — curation-driven render spec + completion merge.

The device's ``bounceCuration`` JS walks the active curation's pads,
solos each STG-X track, triggers the clip, freezes+crops via Live's LOM,
and writes a WAV per pad. The server is the only piece of the system
that owns the curation's identity + persistent state — so the server
constructs the **bounce spec** (which pads to render + where the WAVs
land) and, when the device reports completion, mutates the curation's
``last_bounce`` block.

Two pure helpers live here so the FastAPI/asyncio/SSE plumbing can stay
in :mod:`stemforge.configurator.intents` while this module stays
unit-testable in isolation (mirrors the Phase 2 split for
:mod:`stemforge.configurator.commit_handler`):

* :func:`build_bounce_spec` — derive a :class:`BounceSpec` from a
  :class:`Curation` + optional ``pad_ids`` filter. Pure function, no
  I/O. Used both to validate the trigger-bounce request and to ship
  the spec to the device.
* :func:`merge_bounce_completion` — apply the device's completion
  report onto a :class:`Curation`, returning the new Curation with
  ``last_bounce`` populated. Pure function; callers handle the atomic
  write.

Spec references:

- ``specs/CONSOLIDATED_DESIGN.md`` §3.3 (BOUNCE verb definition)
- ``specs/CONSOLIDATED_DESIGN.md`` §4.3 (``/curations/{name}/trigger-bounce``)
- ``specs/CONSOLIDATED_DESIGN.md`` §5.5 (bounce flow)
- ``specs/CONSOLIDATED_DESIGN.md`` §6.6 (bounce as part of the verb table)

Wire shape the device emits on completion (POST
``/curations/{name}/bounce-complete``):

.. code-block:: json

    {
      "pad_audio_hashes": {
        "A01": "<sha256-hex>",
        "B01": "<sha256-hex>"
      },
      "manifest_path": "bounced/verse_swap_v1/bounce_manifest.json"
    }

The manifest_path is relative to ``~/stemforge/`` per spec §2.3.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from .schemas import Curation, LastBounce, Pad


# ── Pad-id helpers ───────────────────────────────────────────────────────────


def _is_populated(pad: Pad) -> bool:
    """A pad is *populated* iff it has a ``source`` block.

    Empty pads (the ``{pad_id: X}`` slot placeholders) are skipped by
    BOUNCE — the device has nothing to render for them.
    """
    return pad.source is not None


def _normalize_pad_id(raw: str) -> str:
    """Canonicalize the popup's display-form pad ids to wire form.

    The popup may surface pad ids with the interpunct separator
    (``A·01``) for human readability; the curation's authoritative
    representation is ``A01`` (no separator). Accept both on input so
    the trigger-bounce endpoint can take whatever the popup hands it.
    """
    return raw.replace("·", "").replace("-", "").strip()


# ── BounceSpec — what the device renders ─────────────────────────────────────


class BounceSpecPad(BaseModel):
    """One pad's worth of render directive in a :class:`BounceSpec`.

    The device receives this and knows: which staging track to solo
    (derived from ``pad_id``'s leading letter), which clip slot to
    trigger (the trailing slot number), where to write the rendered
    WAV (``output_path``), and which template chain is baked in
    (advisory — the actual chain lives on STG-X's track devices).
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    pad_id: str = Field(..., description="Canonical pad id, e.g. ``A01``")
    group: str = Field(..., description="Leading letter (``A``..``P``)")
    slot: int = Field(..., ge=1, description="1-indexed clip slot within the group")
    template: str | None = Field(
        default=None,
        description=(
            "Template name baked into this pad's render (group's template "
            "as recorded in the curation). ``None`` = dry passthrough."
        ),
    )
    output_path: str = Field(
        ...,
        description=(
            "Relative path under ``~/stemforge/`` for the rendered WAV "
            "(e.g. ``bounced/<curation>/A01.wav``). Spec §2.3."
        ),
    )


class BounceSpec(BaseModel):
    """Full render directive — what the server hands the device.

    The device's ``bounceCuration`` JS consumes this verbatim. The
    ``pads`` list is the iteration order; the device solos each pad's
    group track in turn, triggers the slot, freezes+crops, writes the
    WAV.

    Empty pads are intentionally absent — BOUNCE renders only what's
    actually populated. Pad-id ordering preserves the curation's
    group-major / slot-ascending convention so a partial bounce stays
    deterministic relative to a full one.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    curation_name: str = Field(..., description="The curation being bounced")
    bounce_dir: str = Field(
        ...,
        description=(
            "Relative output directory under ``~/stemforge/`` for this "
            "bounce (``bounced/<curation>/``). Used by the device as the "
            "prefix for every pad's WAV."
        ),
    )
    manifest_path: str = Field(
        ...,
        description=(
            "Relative path of the per-bounce manifest file the device "
            "will write summarizing this run (``bounced/<curation>/"
            "bounce_manifest.json``)."
        ),
    )
    pads: list[BounceSpecPad] = Field(
        default_factory=list,
        description="Pads to render, in iteration order.",
    )


# ── Spec construction ────────────────────────────────────────────────────────


def _parse_pad_id(pad_id: str) -> tuple[str, int] | None:
    """Split a canonical pad id into ``(group_letter, slot_int)``.

    Returns ``None`` for malformed ids. ``A01`` → ``("A", 1)``,
    ``B12`` → ``("B", 12)``. Two-digit slots are required (matches
    the device's ``_commitWalkGroup`` zero-pad convention).
    """
    canon = _normalize_pad_id(pad_id)
    if len(canon) < 2:
        return None
    letter = canon[0].upper()
    if not letter.isalpha():
        return None
    try:
        slot = int(canon[1:])
    except ValueError:
        return None
    if slot < 1:
        return None
    return letter, slot


def build_bounce_spec(
    curation: Curation,
    pad_ids: Iterable[str] | None = None,
) -> BounceSpec:
    """Construct the per-pad render directive for a curation.

    Pure function. No I/O — the caller handles disk + transport.

    Iteration order:
    - Groups in sorted-letter order (``A``, ``B``, …) matching the
      device's commit walker and the popup's grid render.
    - Within a group, pads in their stored list order (i.e. by slot).

    Args:
        curation: The :class:`Curation` to bounce.
        pad_ids: Optional explicit allow-list (canonical or
            interpunct form). When ``None``, every populated pad is
            bounced. Unknown pad ids are silently skipped — the
            FastAPI route layer can choose to reject them as 422 if
            stricter validation is wanted.

    Returns:
        A :class:`BounceSpec`. ``pads`` may be empty when the
        curation has nothing populated (or the filter matches
        nothing) — callers should reject that with 400 at the route
        layer.
    """
    bounce_dir = f"bounced/{curation.name}"
    manifest_path = f"{bounce_dir}/bounce_manifest.json"

    allowed: set[str] | None = None
    if pad_ids is not None:
        allowed = {_normalize_pad_id(p) for p in pad_ids if p}

    out: list[BounceSpecPad] = []
    for letter in sorted(curation.groups.keys()):
        group = curation.groups[letter]
        template = group.template
        for pad in group.pads:
            if not _is_populated(pad):
                continue
            canon = _normalize_pad_id(pad.pad_id)
            if allowed is not None and canon not in allowed:
                continue
            parsed = _parse_pad_id(canon)
            if parsed is None:
                # Malformed pad id in the curation — shouldn't happen
                # post Pydantic validation, but skip rather than 500
                # so a single bad slot doesn't void the whole bounce.
                continue
            group_letter, slot = parsed
            out.append(
                BounceSpecPad(
                    pad_id=canon,
                    group=group_letter,
                    slot=slot,
                    template=template,
                    output_path=f"{bounce_dir}/{canon}.wav",
                )
            )
    return BounceSpec(
        curation_name=curation.name,
        bounce_dir=bounce_dir,
        manifest_path=manifest_path,
        pads=out,
    )


# ── Completion merge ─────────────────────────────────────────────────────────


class BounceCompletion(BaseModel):
    """``POST /curations/{name}/bounce-complete`` request body.

    The device walks every pad in :class:`BounceSpec`, captures the
    SHA-256 of each rendered WAV, and POSTs this payload when done.
    The server then mutates ``Curation.last_bounce`` accordingly.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    manifest_path: str = Field(
        ...,
        description=(
            "Relative path under ``~/stemforge/`` of the bounce manifest "
            "the device just wrote. Echoed back from :class:`BounceSpec`."
        ),
    )
    pad_audio_hashes: dict[str, str] = Field(
        default_factory=dict,
        description="pad_id (canonical) → SHA-256 hex of the rendered WAV.",
    )
    bounced_at: datetime | None = Field(
        default=None,
        description=(
            "Optional device-supplied timestamp. When omitted, the "
            "server stamps ``datetime.now(UTC)``."
        ),
    )


class BounceProgress(BaseModel):
    """``POST /curations/{name}/bounce-progress`` request body.

    Optional progress beacon — the device may POST one of these per
    pad as it renders. Carries enough state for the popup to surface
    a progress bar via SSE without waiting on completion.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    pad_id: str = Field(..., description="The pad just rendered (canonical)")
    rendered_count: int = Field(..., ge=0)
    total_count: int = Field(..., ge=0)
    output_path: str | None = Field(
        default=None,
        description="Absolute or relative path of the WAV that was written.",
    )


def merge_bounce_completion(
    *,
    existing: Curation,
    completion: BounceCompletion,
) -> Curation:
    """Apply a device completion report onto a curation.

    Mutates ``last_bounce`` to record the new bounced-at timestamp,
    manifest path, and pad-by-pad audio hashes. Bumps
    ``modified_at`` so popup lists re-render with a fresh "bounced N
    minutes ago" string.

    Pure function — the caller writes the result atomically. Matches
    :func:`stemforge.configurator.commit_handler.merge_device_snapshot`
    for symmetry: spec construction + state-mutation helpers live in
    handler modules; routes call them under the asyncio lock.
    """
    bounced_at = completion.bounced_at or datetime.now(UTC)
    merged = existing.model_copy(deep=True)
    merged.last_bounce = LastBounce(
        bounced_at=bounced_at,
        manifest_path=completion.manifest_path,
        pad_audio_hashes={_normalize_pad_id(k): v for k, v in completion.pad_audio_hashes.items()},
    )
    merged.modified_at = bounced_at
    return merged


__all__ = [
    "BounceCompletion",
    "BounceProgress",
    "BounceSpec",
    "BounceSpecPad",
    "build_bounce_spec",
    "merge_bounce_completion",
]
