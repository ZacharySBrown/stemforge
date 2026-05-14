"""Stale-reference detection + refresh for curations against forges.

A curation's :class:`ReferencedForge` records the ``manifest_hash`` of
each forge slug it pointed at when the user last committed. If that
slug's *current* manifest_hash differs (forge was re-anchored or
re-curated since), every pad whose ``source.forge`` matches that slug is
stale: the pad's clip id / bar range may no longer resolve in Live.

This module is pure: no I/O, no FastAPI, no async. The functions take a
:class:`Curation` plus a snapshot of the loaded forges and return either
a pad → stale bool map or a brand-new :class:`Curation` instance with
its references rewritten to the current state.

The server's broadcaster wires :func:`compute_stale` into the SSE state
event so the popup can render per-pad and per-forge stale badges. The
new ``POST /curations/{name}/refresh`` endpoint wires
:func:`refresh_pad_refs` to rewrite the on-disk YAML once the user
confirms.

Spec references:

* Spec §2.2 — "Critical: re-running auto-curation rewrites
  auto_curation_manifest.json but never touches curations/\\*.yaml. The
  stale-detection at the curation side is how the system stays safe."
* Spec §6.10 — stale-detection flow.
* Spec §5.6 step 8 — "Refresh from forge" UX.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .schemas import Curation, Group, Pad, PadSource, ReferencedForge

if TYPE_CHECKING:
    from stemforge.forge.manifest_io import ForgeManifest


# ── Public helpers ──────────────────────────────────────────────────────────


def compute_stale(
    curation: Curation,
    forges: dict[str, ForgeManifest | None],
) -> dict[str, bool]:
    """Return ``{pad_id: stale_bool}`` for every pad in ``curation``.

    ``forges`` maps each referenced slug to its currently-loaded
    :class:`ForgeManifest`, or ``None`` when the forge no longer exists.
    A pad is stale when:

    * Its ``source.forge`` is referenced by the curation AT a different
      ``manifest_hash`` than the forge's current manifest_hash, OR
    * Its ``source.forge`` resolves to ``None`` in ``forges`` (forge
      was deleted / unavailable since the last commit).

    Empty pads (no ``source``) and external-path pads (no ``forge``)
    are always non-stale — the stale concept is forge-relative.
    """
    ref_hashes = _curation_ref_hashes(curation)
    out: dict[str, bool] = {}
    for group in curation.groups.values():
        for pad in group.pads:
            out[pad.pad_id] = _pad_is_stale(pad, ref_hashes, forges)
    return out


def stale_summary(
    curation: Curation,
    forges: dict[str, ForgeManifest | None],
) -> dict[str, "PadStaleEntry"]:
    """Per-pad stale summary as ``{pad_id: {stale, current_manifest_hash}}``.

    Used by the SSE broadcaster to enrich every pad with the same fields
    the popup wants to render: ``stale`` (bool) and
    ``current_manifest_hash`` (str | None — null when the forge is gone
    or the pad has no forge ref). Pads with no source are emitted as
    ``{stale: false, current_manifest_hash: null}`` so the popup can
    treat the map as total.
    """
    ref_hashes = _curation_ref_hashes(curation)
    out: dict[str, PadStaleEntry] = {}
    for group in curation.groups.values():
        for pad in group.pads:
            stale = _pad_is_stale(pad, ref_hashes, forges)
            current_hash: str | None = None
            if pad.source is not None and pad.source.forge is not None:
                forge = forges.get(pad.source.forge)
                current_hash = forge.manifest_hash if forge is not None else None
            out[pad.pad_id] = PadStaleEntry(
                stale=stale,
                current_manifest_hash=current_hash,
            )
    return out


def refresh_pad_refs(
    curation: Curation,
    forges: dict[str, ForgeManifest | None],
) -> Curation:
    """Return a copy of ``curation`` with its forge references rewritten.

    For every pad whose source is forge-owned:

    * If the forge still exists, re-resolve the pad's ``audio_path``
      against the current ``auto_curation_manifest`` (clip_id lookup) so
      a re-anchor that moved the clip's WAV onto a different relative
      path still points at the right file.
    * If the clip_id is no longer present in the manifest, leave the
      pad's audio_path untouched (we can't materialize a replacement
      without user intent) — the pad will simply read as ``audio_path``
      and the loader will fail at LOAD time, surfacing the missing clip.
    * If the forge no longer exists at all, leave the pad untouched.

    The returned curation's ``referenced_forges`` list is rewritten to
    the union of slugs still referenced by pads, each carrying that
    forge's CURRENT manifest_hash. Slugs that have disappeared are
    dropped from ``referenced_forges`` (the broadcaster will surface
    them as stale via missing forges instead).

    Idempotent: calling this twice in a row against the same forges map
    yields an equal :class:`Curation`.
    """
    new_groups: dict[str, Group] = {}
    referenced_slugs: set[str] = set()
    for letter, group in curation.groups.items():
        new_pads: list[Pad] = []
        for pad in group.pads:
            new_pad = _refresh_pad(pad, forges)
            if new_pad.source is not None and new_pad.source.forge is not None:
                referenced_slugs.add(new_pad.source.forge)
            new_pads.append(new_pad)
        new_groups[letter] = group.model_copy(update={"pads": new_pads})

    new_refs: list[ReferencedForge] = []
    for slug in sorted(referenced_slugs):
        forge = forges.get(slug)
        if forge is None:
            # Slug still referenced by some pad but the forge is gone;
            # drop the ref so the pad reads as stale-orphan rather than
            # carrying a fictional hash.
            continue
        new_refs.append(ReferencedForge(slug=slug, manifest_hash=forge.manifest_hash))

    return curation.model_copy(update={"groups": new_groups, "referenced_forges": new_refs})


# ── Internals ───────────────────────────────────────────────────────────────


class PadStaleEntry:
    """Lightweight container for the per-pad stale summary.

    Plain class (not a Pydantic model) because the broadcaster turns it
    into a plain dict before pushing to SSE — no validation overhead
    needed inside the hot path.
    """

    __slots__ = ("stale", "current_manifest_hash")

    def __init__(self, *, stale: bool, current_manifest_hash: str | None) -> None:
        self.stale = stale
        self.current_manifest_hash = current_manifest_hash

    def to_dict(self) -> dict[str, object]:
        return {
            "stale": self.stale,
            "current_manifest_hash": self.current_manifest_hash,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PadStaleEntry):
            return NotImplemented
        return (
            self.stale == other.stale and self.current_manifest_hash == other.current_manifest_hash
        )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"PadStaleEntry(stale={self.stale!r}, "
            f"current_manifest_hash={self.current_manifest_hash!r})"
        )


def _curation_ref_hashes(curation: Curation) -> dict[str, str]:
    return {ref.slug: ref.manifest_hash for ref in curation.referenced_forges}


def _pad_is_stale(
    pad: Pad,
    ref_hashes: dict[str, str],
    forges: dict[str, ForgeManifest | None],
) -> bool:
    if pad.source is None or pad.source.forge is None:
        return False
    slug = pad.source.forge
    forge = forges.get(slug)
    if forge is None:
        # Forge missing entirely — every forge-owned pad referencing it
        # is stale (the popup shows a "forge unavailable" tooltip).
        return True
    referenced_hash = ref_hashes.get(slug)
    if referenced_hash is None:
        # Pad points at a forge the curation never listed in
        # ``referenced_forges`` — treat as stale because we have no
        # commit-time anchor to compare against. This matches the
        # broadcaster behaviour of "if in doubt, surface staleness".
        return True
    return referenced_hash != forge.manifest_hash


def _refresh_pad(pad: Pad, forges: dict[str, ForgeManifest | None]) -> Pad:
    """Refresh one pad's source against the forge's current manifest."""
    if pad.source is None or pad.source.forge is None:
        return pad
    forge = forges.get(pad.source.forge)
    if forge is None:
        # Can't resolve; leave pad untouched, broadcaster will surface
        # the dangling reference.
        return pad
    clip_id = pad.source.clip_id
    if clip_id is None:
        # No clip_id to match against — bail.
        return pad
    clip = next((c for c in forge.clips if c.clip_id == clip_id), None)
    if clip is None:
        # clip_id missing in current manifest — leave audio_path untouched
        # so the loader's LOAD path surfaces a "missing clip" rather than
        # us silently rewriting to an unrelated file.
        return pad
    new_source = PadSource.for_forge(
        forge=pad.source.forge,
        clip_id=clip_id,
        audio_path=clip.audio_path,
    )
    return pad.model_copy(update={"source": new_source})


__all__ = [
    "PadStaleEntry",
    "compute_stale",
    "refresh_pad_refs",
    "stale_summary",
]
