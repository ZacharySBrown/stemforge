"""Filesystem scan + delegation helpers for the Phase 1.5 forge endpoints.

These helpers wrap the on-disk shape of ``~/stemforge/processed/<slug>/``
so the server's HTTP routes stay thin. Two responsibilities live here:

1. **Discovery** — :func:`list_forges` walks the processed root and emits
   one :class:`ForgeIndexEntry` per subdir that has either the new-shape
   ``auto_curation_manifest.json`` or the legacy ``curated/manifest.json``.
   Both are recognized via :mod:`stemforge.forge.manifest_io`.
2. **Slug resolution** — :func:`resolve_forge_dir` validates a slug and
   returns its dir, or raises a 404-shaped :class:`HTTPException`.

The endpoints themselves (``POST /forges/{slug}/load``, etc.) live in
:mod:`stemforge.configurator.server`; this module is pure I/O so it stays
test-friendly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

# Filename constants duplicated here to avoid a circular import chain via
# `stemforge.forge.manifest_io ← stemforge.configurator.schemas ←
# stemforge.configurator.__init__ ← stemforge.configurator.intents ←
# stemforge.configurator.commit_handler ← stemforge.configurator.forge_io`.
# manifest_io.py is the source of truth; tests pin them to stay in sync.
ARRANGEMENT_FILENAME = "arrangement_manifest.json"
AUTO_CURATION_FILENAME = "auto_curation_manifest.json"
LEGACY_FILENAME = "manifest.json"
LEGACY_PARENT = "curated"


def _manifest_io():
    """Lazy import shim for the rest of manifest_io's surface — keeps the
    module-level cycle broken while still letting handlers reach the
    loaders / errors at call time."""
    from stemforge.forge import manifest_io  # noqa: PLC0415 — intentional lazy import

    return manifest_io


def __getattr__(name: str) -> Any:  # noqa: D401
    """Resolve the previously-eager imports lazily.

    Anything that used to be a module-level import from
    ``stemforge.forge.manifest_io`` (``ForgeManifestError``,
    ``load_forge``, ``load_arrangement``) is re-exported here without
    triggering the cycle.
    """
    if name in ("ForgeManifestError", "load_forge", "load_arrangement"):
        return getattr(_manifest_io(), name)
    raise AttributeError(name)


# Reuse the curation-name validator's character class for slug safety —
# the processed dir's child names mirror the same constraint set.
_SLUG_FORBIDDEN = ("/", "\\", "..", "\x00")


@dataclass
class ForgeIndexEntry:
    """One row in ``GET /forges`` — projection over a single forge dir.

    Field set is the union of what the popup's ``ForgeIndexEntry`` and
    the task brief reference. Optional fields are emitted only when the
    underlying manifest had them (rather than stamping zeros).
    """

    slug: str
    name: str
    manifest_hash: str
    modified_at: str
    has_arrangement: bool
    sample_count: int
    bar_count: int
    target_format: str
    bpm: float | None = None
    source_audio: str | None = None
    chunk_count: int | None = None
    clip_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Emit the dict shape ``GET /forges`` returns over the wire.

        Optional fields are dropped when ``None`` so the popup doesn't have
        to special-case nulls. Order is alphabetical to keep diffs stable.
        """
        payload: dict[str, object] = {
            "bar_count": self.bar_count,
            "has_arrangement": self.has_arrangement,
            "manifest_hash": self.manifest_hash,
            "modified_at": self.modified_at,
            "name": self.name,
            "sample_count": self.sample_count,
            "slug": self.slug,
            "target_format": self.target_format,
        }
        if self.bpm is not None:
            payload["bpm"] = self.bpm
        if self.source_audio is not None:
            payload["source_audio"] = self.source_audio
        if self.chunk_count is not None:
            payload["chunk_count"] = self.chunk_count
        if self.clip_count is not None:
            payload["clip_count"] = self.clip_count
        return payload


def default_processed_dir() -> Path:
    """Return the canonical processed dir (``~/stemforge/processed``)."""
    return Path.home() / "stemforge" / "processed"


def _is_valid_slug(slug: str) -> bool:
    """Reject the obvious path-traversal patterns; everything else is fine.

    Forge slugs are user-chosen track names that have already been sanitized
    by ``stemforge forge``. The endpoint surface only needs to refuse
    actively dangerous values; legitimate slug pickyness lives in the
    forge writer.
    """
    if not isinstance(slug, str) or not slug:
        return False
    if any(token in slug for token in _SLUG_FORBIDDEN):
        return False
    return True


def resolve_forge_dir(
    processed_dir: Path,
    slug: str,
) -> Path:
    """Return the forge dir for ``slug`` or raise 404.

    Validates the slug shape first (400) before stating the dir (404), so
    callers get the right error for the right failure mode. Caller is
    expected to be inside an HTTP handler — the raised exceptions are
    FastAPI :class:`HTTPException` instances.
    """
    if not _is_valid_slug(slug):
        raise HTTPException(status_code=400, detail=f"invalid forge slug: {slug!r}")
    forge_dir = processed_dir / slug
    if not forge_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"forge not found: {slug}")
    return forge_dir


def has_any_manifest(forge_dir: Path) -> bool:
    """True if ``forge_dir`` carries either new-shape or legacy manifest.

    Used as the entry-gate in :func:`list_forges` — directories that lack
    both shapes are not visible to the popup at all (so leftover/work-in-
    progress dirs don't pollute the rail).
    """
    return (forge_dir / AUTO_CURATION_FILENAME).is_file() or (
        forge_dir / LEGACY_PARENT / LEGACY_FILENAME
    ).is_file()


def _modified_at_iso(path: Path) -> str:
    """ISO-8601 mtime for ``path`` (UTC). Falls back to "" if path missing."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return ""
    return datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat()


def _best_mtime_path(forge_dir: Path) -> Path:
    """Return the manifest file whose mtime should drive ``modified_at``.

    Prefer the new-shape auto-curation manifest when present (it's the
    canonical document); fall back to the legacy manifest, then the dir
    itself. Keeps the index sortable by "recently touched" even on
    pre-migration forges.
    """
    new = forge_dir / AUTO_CURATION_FILENAME
    if new.is_file():
        return new
    legacy = forge_dir / LEGACY_PARENT / LEGACY_FILENAME
    if legacy.is_file():
        return legacy
    return forge_dir


def index_entry_for(forge_dir: Path, slug: str) -> ForgeIndexEntry:
    """Build one :class:`ForgeIndexEntry` for an already-validated forge dir.

    Resilient to malformed manifests: a parse failure on ``forge_dir``'s
    auto-curation file produces a minimal entry (no bpm/sample count, an
    empty hash) rather than blowing up the whole index. The popup can
    surface a "broken forge" badge from the empty hash.
    """
    # Bind manifest_io locally: module-level `__getattr__` only fires on
    # `forge_io.load_forge` style lookups, not on bare names inside this
    # module's own functions (PEP 562). Going through the helper preserves
    # the cycle-breaking intent.
    manifest_io = _manifest_io()

    arrangement_path = forge_dir / ARRANGEMENT_FILENAME
    legacy_path = forge_dir / LEGACY_PARENT / LEGACY_FILENAME
    has_arrangement = arrangement_path.is_file()

    bpm: float | None = None
    manifest_hash = ""
    sample_count = 0
    bar_count = 0
    chunk_count: int | None = None
    source_audio: str | None = None

    try:
        manifest = manifest_io.load_forge(slug, forge_dir=forge_dir)
        bpm = float(manifest.bpm)
        manifest_hash = manifest.manifest_hash
        sample_count = len(manifest.clips)
        bar_count = sum(int(c.duration_bars) for c in manifest.clips)
        source_audio = manifest.source_audio or None
    except manifest_io.ForgeManifestError:
        # Surface the forge anyway with a zero-ish entry; the empty hash
        # is the signal to UIs that something is off.
        pass

    if has_arrangement:
        try:
            arrangement = manifest_io.load_arrangement(slug, forge_dir=forge_dir)
            if arrangement is not None:
                chunk_count = len(arrangement.chunks)
        except manifest_io.ForgeManifestError:
            chunk_count = None

    is_legacy_only = not (forge_dir / AUTO_CURATION_FILENAME).is_file() and legacy_path.is_file()
    target_format = "legacy" if is_legacy_only else "auto_curation_v1"

    return ForgeIndexEntry(
        slug=slug,
        name=slug,
        manifest_hash=manifest_hash,
        modified_at=_modified_at_iso(_best_mtime_path(forge_dir)),
        has_arrangement=has_arrangement,
        sample_count=sample_count,
        bar_count=bar_count,
        target_format=target_format,
        bpm=bpm,
        source_audio=source_audio,
        chunk_count=chunk_count,
        clip_count=sample_count if sample_count else None,
    )


def list_forges(processed_dir: Path) -> list[ForgeIndexEntry]:
    """Scan ``processed_dir`` and return one entry per recognized forge.

    Returns ``[]`` when ``processed_dir`` doesn't exist yet. Entries are
    sorted by ``slug`` for stable output (the popup keeps the order; CI
    snapshot tests rely on it).
    """
    if not processed_dir.is_dir():
        return []
    entries: list[ForgeIndexEntry] = []
    for child in sorted(processed_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if not has_any_manifest(child):
            continue
        entries.append(index_entry_for(child, child.name))
    return entries


__all__ = [
    "ForgeIndexEntry",
    "default_processed_dir",
    "has_any_manifest",
    "index_entry_for",
    "list_forges",
    "resolve_forge_dir",
]
