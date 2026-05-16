"""Atomic readers + writers for the configurator v1 forge file shape.

Spec: `specs/CONSOLIDATED_DESIGN.md` §2.2.

The legacy shape was a single ``curated/manifest.json`` dict embedding both
auto-curation and arrangement data. The new shape lives at the forge root
(`~/stemforge/processed/<slug>/`) as two sibling files:

- ``auto_curation_manifest.json`` — `ForgeManifest` (clips array + bpm +
  `first_downbeat_sec` + `manifest_hash`)
- ``arrangement_manifest.json`` — `ArrangementManifest` (chunks array +
  bpm + `first_downbeat_sec` + `manifest_hash`)

This module provides a compat shim that reads either shape so the rest of
the CLI doesn't have to care. New writers always emit the new shape;
``migrate_legacy`` converts old-only forges in place (leaving the legacy
file in place for one release for safety).

All writes go through a ``.tmp + os.replace`` atomic dance so a crash mid-
write can't leave a partial file behind.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click
from pydantic import ValidationError

from stemforge.configurator.schemas import (
    ArrangementChunk,
    ArrangementManifest,
    ForgeClip,
    ForgeManifest,
    compute_manifest_hash,
)


# ── Filenames (single source of truth) ───────────────────────────────────────

AUTO_CURATION_FILENAME = "auto_curation_manifest.json"
ARRANGEMENT_FILENAME = "arrangement_manifest.json"
LEGACY_FILENAME = "manifest.json"
LEGACY_PARENT = "curated"


class ForgeManifestError(click.ClickException):
    """Raised when a forge directory's manifest can't be read/parsed.

    Subclass of ``ClickException`` so the CLI surfaces a clean one-line
    error instead of a stacktrace.
    """


class LegacyForgeError(ForgeManifestError):
    """Raised when only the legacy ``curated/manifest.json`` exists and the
    caller asked for new-shape semantics without opting into migration.
    """


# ── Path helpers ─────────────────────────────────────────────────────────────


def _auto_curation_path(forge_dir: Path) -> Path:
    return forge_dir / AUTO_CURATION_FILENAME


def _arrangement_path(forge_dir: Path) -> Path:
    return forge_dir / ARRANGEMENT_FILENAME


def _legacy_path(forge_dir: Path) -> Path:
    return forge_dir / LEGACY_PARENT / LEGACY_FILENAME


def new_manifest_exists(forge_dir: Path) -> bool:
    """True when the new-shape ``auto_curation_manifest.json`` is present."""
    return _auto_curation_path(forge_dir).exists()


def legacy_manifest_exists(forge_dir: Path) -> bool:
    """True when only the legacy ``curated/manifest.json`` is present."""
    return _legacy_path(forge_dir).exists()


# ── Atomic write ─────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to ``path`` atomically via ``.tmp`` + ``os.replace``.

    The temp file lives in the same directory so the rename is a true
    in-filesystem atomic move (cross-device renames would degrade to copy).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(tmp, path)


# ── Writers (Pydantic-validated) ─────────────────────────────────────────────


def write_auto_curation(forge_dir: Path, manifest: ForgeManifest) -> Path:
    """Write the auto-curation manifest atomically.

    ``manifest_hash`` is recomputed from the canonical clips array and
    overwrites whatever the caller put on ``manifest.manifest_hash`` —
    this is the load-bearing invariant for stale detection.
    """
    clip_dicts = [c.model_dump(mode="json") for c in manifest.clips]
    manifest = manifest.model_copy(update={"manifest_hash": compute_manifest_hash(clip_dicts)})
    out = _auto_curation_path(forge_dir)
    _atomic_write_json(out, manifest.model_dump(mode="json"))
    return out


def write_arrangement(forge_dir: Path, manifest: ArrangementManifest) -> Path:
    """Write the arrangement manifest atomically (hash recomputed from chunks)."""
    chunk_dicts = [c.model_dump(mode="json") for c in manifest.chunks]
    manifest = manifest.model_copy(update={"manifest_hash": compute_manifest_hash(chunk_dicts)})
    out = _arrangement_path(forge_dir)
    _atomic_write_json(out, manifest.model_dump(mode="json"))
    return out


# ── Readers ──────────────────────────────────────────────────────────────────


def _parse_forge_manifest(slug: str, path: Path) -> ForgeManifest:
    """Parse a new-shape ``auto_curation_manifest.json`` with clean errors."""
    try:
        raw = path.read_text()
    except OSError as e:
        raise ForgeManifestError(f"forge `{slug}` manifest unreadable: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ForgeManifestError(
            f"forge `{slug}` has malformed manifest: invalid JSON ({e.msg} at line {e.lineno})"
        ) from e
    try:
        return ForgeManifest(**data)
    except ValidationError as e:
        # First error is enough — give the user the actionable detail
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "<root>"
        raise ForgeManifestError(
            f"forge `{slug}` has malformed manifest: {loc}: {first.get('msg', 'invalid')}"
        ) from e


def _parse_arrangement_manifest(slug: str, path: Path) -> ArrangementManifest:
    try:
        raw = path.read_text()
    except OSError as e:
        raise ForgeManifestError(f"forge `{slug}` arrangement unreadable: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ForgeManifestError(
            f"forge `{slug}` has malformed arrangement: invalid JSON ({e.msg} at line {e.lineno})"
        ) from e
    try:
        return ArrangementManifest(**data)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "<root>"
        raise ForgeManifestError(
            f"forge `{slug}` has malformed arrangement: {loc}: {first.get('msg', 'invalid')}"
        ) from e


def load_forge(slug: str, forge_dir: Path | None = None) -> ForgeManifest:
    """Read a forge's auto-curation manifest, auto-detecting shape.

    - New shape (`auto_curation_manifest.json` present): parse + return.
    - Legacy-only (`curated/manifest.json` present): convert in-memory and
      return — the caller gets a `ForgeManifest`, the on-disk legacy file
      is left untouched. Run ``stemforge migrate-forge`` to make it
      permanent.

    Both paths return Pydantic-validated models.
    """
    if forge_dir is None:
        from stemforge.config import PROCESSED_DIR

        forge_dir = PROCESSED_DIR / slug
    forge_dir = Path(forge_dir)

    new_path = _auto_curation_path(forge_dir)
    if new_path.exists():
        return _parse_forge_manifest(slug, new_path)

    legacy_path = _legacy_path(forge_dir)
    if legacy_path.exists():
        return _legacy_to_forge_manifest(slug, legacy_path)

    raise ForgeManifestError(
        f"forge `{slug}` has no manifest "
        f"(expected {AUTO_CURATION_FILENAME} or {LEGACY_PARENT}/{LEGACY_FILENAME} "
        f"under {forge_dir})"
    )


def load_arrangement(slug: str, forge_dir: Path | None = None) -> ArrangementManifest | None:
    """Read a forge's arrangement manifest. Returns None when absent.

    Legacy forges did not separate arrangement data; if the new file is
    absent the caller can derive arrangement chunks from prechop output or
    skip the arrangement view entirely. Returning None instead of raising
    keeps the device-side flow tolerant for compat.
    """
    if forge_dir is None:
        from stemforge.config import PROCESSED_DIR

        forge_dir = PROCESSED_DIR / slug
    forge_dir = Path(forge_dir)

    new_path = _arrangement_path(forge_dir)
    if not new_path.exists():
        return None
    return _parse_arrangement_manifest(slug, new_path)


# ── Legacy → new conversion ──────────────────────────────────────────────────


_LEGACY_STEM_ALIAS = {
    "drums": "drum",
    "drum": "drum",
    "bass": "bass",
    "vocals": "vocal",
    "vocal": "vocal",
    "other": "other",
}


def _stem_label(legacy_name: str) -> str:
    """Map legacy stem keys (``drums``, ``vocals``) onto the new Literal
    set the forge schema accepts (``drum``, ``vocal``). Unknown stems are
    bucketed into ``other`` rather than rejected — legacy forges may have
    extra stems (guitar, piano) we don't want to lose silently.
    """
    return _LEGACY_STEM_ALIAS.get(legacy_name, "other")


def _legacy_clip_id(stem_label: str, position: int, n_bars: int) -> str:
    """Build a stable clip_id from legacy `position` + n_bars/position math."""
    start = (position - 1) * n_bars
    end = position * n_bars
    return f"{stem_label}-bar{start}-{end}"


def _read_legacy(legacy_path: Path, slug: str) -> dict[str, Any]:
    try:
        raw = legacy_path.read_text()
    except OSError as e:
        raise ForgeManifestError(f"forge `{slug}` legacy manifest unreadable: {e}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ForgeManifestError(
            f"forge `{slug}` has malformed legacy manifest: invalid JSON "
            f"({e.msg} at line {e.lineno})"
        ) from e


def _legacy_to_forge_manifest(slug: str, legacy_path: Path) -> ForgeManifest:
    """In-memory conversion of legacy → ForgeManifest. Does not write."""
    data = _read_legacy(legacy_path, slug)
    forge_slug, source_audio, bpm, n_bars, clips = _legacy_extract(data, slug)
    return ForgeManifest(
        schema_version=1,
        forge_slug=forge_slug,
        source_audio=source_audio,
        bpm=bpm,
        first_downbeat_sec=float(data.get("first_downbeat_sec", 0.0) or 0.0),
        manifest_hash=compute_manifest_hash([c.model_dump(mode="json") for c in clips]),
        default_template=data.get("default_template"),
        clips=clips,
    )


def _legacy_to_arrangement_manifest(
    slug: str,
    legacy_path: Path,
) -> ArrangementManifest:
    """Extract arrangement chunks from a legacy manifest, or build an empty
    arrangement manifest when the legacy file has no arrangement data.

    Legacy v0/v1 single-file manifests rarely carried arrangement chunks
    inline; arrangement data lived in a sibling ``prechop_manifest.json``.
    For migration we emit an arrangement manifest with the same
    bpm/source_audio metadata so downstream readers don't crash, even if
    chunks is empty. A follow-up `re-anchor` or fresh `forge` run will
    populate chunks from prechop output.
    """
    data = _read_legacy(legacy_path, slug)
    forge_slug, source_audio, bpm, _n_bars, _clips = _legacy_extract(data, slug)
    chunks: list[ArrangementChunk] = []
    # Legacy "arrangement" inline shape (rare): {"arrangement": [{...}, ...]}
    for raw in data.get("arrangement", []) or []:
        try:
            chunks.append(
                ArrangementChunk(
                    chunk_id=str(raw["chunk_id"]),
                    audio_path=str(raw["audio_path"]),
                    stem=_stem_label(str(raw.get("stem", "other"))),  # type: ignore[arg-type]
                    source_position_sec=float(raw.get("source_position_sec", 0.0)),
                    duration_sec=float(raw["duration_sec"]),
                    bar_position=int(raw.get("bar_position", 0)),
                    duration_bars=int(raw.get("duration_bars", 0)),
                )
            )
        except (KeyError, ValueError, TypeError):
            # Skip malformed inline rows rather than killing the whole migration.
            continue
    chunk_dicts = [c.model_dump(mode="json") for c in chunks]
    return ArrangementManifest(
        schema_version=1,
        forge_slug=forge_slug,
        source_audio=source_audio,
        bpm=bpm,
        first_downbeat_sec=float(data.get("first_downbeat_sec", 0.0) or 0.0),
        manifest_hash=compute_manifest_hash(chunk_dicts),
        chunks=chunks,
    )


def _legacy_extract(
    data: dict[str, Any],
    slug: str,
) -> tuple[str, str, float, int, list[ForgeClip]]:
    """Pull the four invariants + clips list out of a legacy manifest dict.

    Returns (forge_slug, source_audio, bpm, n_bars, clips).
    """
    forge_slug = data.get("forge_slug") or data.get("track") or slug
    source_audio = (
        data.get("source_audio") or data.get("source_file") or data.get("source_dir") or ""
    )
    bpm = data.get("bpm")
    if bpm is None or float(bpm) <= 0:
        raise ForgeManifestError(
            f"forge `{slug}` has malformed legacy manifest: missing or non-positive bpm"
        )
    bpm = float(bpm)
    n_bars = int(data.get("n_bars", 1)) or 1

    clips: list[ForgeClip] = []
    stems_dict = data.get("stems")
    if not isinstance(stems_dict, dict):
        raise ForgeManifestError(
            f"forge `{slug}` has malformed legacy manifest: missing or non-object stems"
        )
    for stem_name, entries in stems_dict.items():
        # v2 production shape: stems[stem_name] is a dict with `loops`, `oneshots`, etc.
        if isinstance(entries, dict):
            entries = entries.get("loops") or []
        if not isinstance(entries, list):
            continue
        stem_label = _stem_label(stem_name)
        for entry in entries:
            if not isinstance(entry, dict) or "file" not in entry:
                continue
            position = int(entry.get("position") or entry.get("rank") or (len(clips) + 1))
            # v2 curation entries carry per-loop length as `phrase_bars`;
            # legacy entries use `duration_bars`. Fall back to the manifest's
            # n_bars only when neither is present. (n_bars is the COUNT of
            # curated bars, not each clip's length — using it as the per-clip
            # duration produced bogus 14-bar source_bar_ranges.)
            duration_bars = int(
                entry.get("duration_bars") or entry.get("phrase_bars") or n_bars
            )
            start_bar = (position - 1) * duration_bars
            end_bar = start_bar + duration_bars
            # Keep the legacy `file` value verbatim — it is already relative
            # to the forge root (`curated/<stem>/<file>`) and the real WAVs
            # live there on disk. An earlier rewrite to `curated_audio/<name>`
            # pointed at a directory the pipeline never materializes AND
            # dropped the `<stem>/` subdir via Path(...).name, collapsing all
            # four stems onto the same bar_NN.wav names. Every create_audio_clip
            # in the M4L loader then failed ("Invalid syntax" on a missing
            # file). Caught 2026-05-15 on ooh_la_la.
            audio_path = str(entry["file"])
            clip_id = entry.get("clip_id") or _legacy_clip_id(stem_label, position, duration_bars)
            try:
                clips.append(
                    ForgeClip(
                        clip_id=str(clip_id),
                        audio_path=audio_path,
                        stem=stem_label,  # type: ignore[arg-type]
                        source_bar_range=(start_bar, end_bar),
                        duration_bars=duration_bars,
                        tags=list(entry.get("tags", []) or []),
                    )
                )
            except ValidationError:
                continue
    return forge_slug, source_audio, bpm, n_bars, clips


def build_from_curated_dict(
    slug: str,
    forge_dir: Path,
    curated: dict[str, Any],
    *,
    bpm: float | None = None,
    first_downbeat_sec: float = 0.0,
    default_template: str | None = None,
) -> ForgeManifest:
    """Build a ``ForgeManifest`` from an in-memory legacy ``curated``
    dict (the same dict shape ``stemforge forge`` writes to
    ``curated/manifest.json``).

    Used by writers that want to emit the new-shape file alongside the
    legacy one during the compat window. ``bpm`` overrides the dict's bpm
    field (handy when the bpm landed elsewhere in the pipeline). Other
    invariants — source_audio, n_bars, stems — are pulled from ``curated``.

    Returns an in-memory ``ForgeManifest``; the caller writes it with
    ``write_auto_curation`` to get the atomic on-disk file.
    """
    merged = dict(curated)
    if bpm is not None:
        merged["bpm"] = bpm
    if "bpm" not in merged or merged["bpm"] in (None, 0):
        # Legacy forges sometimes omit bpm at the top of `curated_manifest`
        # because it lives in stems.json. Synthesize a non-zero placeholder
        # only when the caller didn't supply one — the schema rejects 0.
        merged["bpm"] = 120.0
    forge_slug, source_audio, bpm_val, _n_bars, clips = _legacy_extract(merged, slug)
    return ForgeManifest(
        schema_version=1,
        forge_slug=forge_slug,
        source_audio=source_audio,
        bpm=bpm_val,
        first_downbeat_sec=float(first_downbeat_sec or 0.0),
        manifest_hash=compute_manifest_hash([c.model_dump(mode="json") for c in clips]),
        default_template=default_template,
        clips=clips,
    )


def build_empty_arrangement(
    slug: str,
    *,
    source_audio: str,
    bpm: float,
    first_downbeat_sec: float = 0.0,
) -> ArrangementManifest:
    """Build a zero-chunk arrangement manifest with the forge's invariants.

    Used when the writer hasn't computed arrangement chunks yet (forge
    command without prechop, e.g.). The file's existence is what unblocks
    downstream Phase 1B/1C/1D consumers that load both manifests; an empty
    chunks list is a valid, well-formed manifest.
    """
    return ArrangementManifest(
        schema_version=1,
        forge_slug=slug,
        source_audio=source_audio,
        bpm=bpm,
        first_downbeat_sec=float(first_downbeat_sec or 0.0),
        manifest_hash=compute_manifest_hash([]),
        chunks=[],
    )


# Map prechop's plural stem labels to the schema's singular literals.
_PRECHOP_STEM_TO_SCHEMA: dict[str, str] = {
    "drums": "drum",
    "bass": "bass",
    "vocals": "vocal",
    "other": "other",
}


def build_arrangement_from_prechop(
    slug: str,
    *,
    forge_dir: Path,
    source_audio: str,
    bpm: float,
    first_downbeat_sec: float = 0.0,
) -> ArrangementManifest:
    """Build an arrangement manifest from a sibling ``prechop_manifest.json``.

    Reads ``<forge_dir>/prechop_manifest.json`` and flattens its nested
    ``stems.<stem>.chunks[]`` shape into the schema's flat ``chunks[]``
    list (one row per stem-chunk). Falls back to
    :func:`build_empty_arrangement` when the prechop file is absent or
    has no chunk rows.

    The bar grid for each chunk is derived from prechop's
    ``chunk_index`` / ``bars`` fields:
        bar_position       = (chunk_index - 1) * bars
        source_position_sec = first_downbeat_sec + bar_position * bar_period_sec

    Pre-roll chunks (chunk_index < musical_bar_1_chunk_index) get a
    bar_position of 0 and a source_position_sec of 0 so they don't
    project negatives onto the bar grid.
    """
    pre_path = forge_dir / "prechop_manifest.json"
    if not pre_path.is_file():
        return build_empty_arrangement(
            slug,
            source_audio=source_audio,
            bpm=bpm,
            first_downbeat_sec=first_downbeat_sec,
        )

    try:
        data: dict[str, Any] = json.loads(pre_path.read_text())
    except (OSError, json.JSONDecodeError):
        return build_empty_arrangement(
            slug,
            source_audio=source_audio,
            bpm=bpm,
            first_downbeat_sec=first_downbeat_sec,
        )

    beats_per_bar = int(data.get("beats_per_bar") or 4) or 4
    bar_period_sec = (60.0 / float(bpm)) * float(beats_per_bar)
    musical_bar_1 = int(data.get("musical_bar_1_chunk_index") or 1)

    chunks: list[ArrangementChunk] = []
    stems = data.get("stems") or {}
    if not isinstance(stems, dict):
        stems = {}

    for stem_key, stem_block in stems.items():
        schema_stem = _PRECHOP_STEM_TO_SCHEMA.get(str(stem_key))
        if schema_stem is None:
            continue
        if not isinstance(stem_block, dict):
            continue
        for raw in stem_block.get("chunks") or []:
            if not isinstance(raw, dict):
                continue
            try:
                chunk_index = int(raw.get("chunk_index") or 0)
                bars = int(raw.get("bars") or 0)
            except (TypeError, ValueError):
                continue
            if chunk_index <= 0 or bars <= 0:
                continue
            file_rel = str(raw.get("file") or "").strip()
            if not file_rel:
                continue
            offset_from_bar_1 = max(0, chunk_index - musical_bar_1)
            bar_position = offset_from_bar_1 * bars
            source_position_sec = float(first_downbeat_sec or 0.0) + bar_position * bar_period_sec
            duration_sec = float(raw.get("total_sec") or (bars * bar_period_sec))
            chunks.append(
                ArrangementChunk(
                    chunk_id=f"{schema_stem}-chunk-{chunk_index:03d}",
                    audio_path=file_rel,
                    stem=schema_stem,  # type: ignore[arg-type]
                    source_position_sec=source_position_sec,
                    duration_sec=duration_sec,
                    bar_position=bar_position,
                    duration_bars=bars,
                )
            )

    # Sort chunks deterministically (stem, then bar_position) so the
    # manifest_hash stays stable across runs.
    chunks.sort(key=lambda c: (c.stem, c.bar_position, c.chunk_id))

    chunk_dicts = [c.model_dump(mode="json") for c in chunks]
    return ArrangementManifest(
        schema_version=1,
        forge_slug=slug,
        source_audio=source_audio,
        bpm=bpm,
        first_downbeat_sec=float(first_downbeat_sec or 0.0),
        manifest_hash=compute_manifest_hash(chunk_dicts),
        chunks=chunks,
    )


def migrate_legacy(slug: str, forge_dir: Path) -> tuple[Path, Path]:
    """Convert a legacy ``curated/manifest.json`` into the new two-file shape.

    Atomic per file. Leaves the legacy file in place for one release for
    backward compatibility — a follow-up cleanup will delete it.

    Returns (auto_curation_path, arrangement_path).
    """
    legacy_path = _legacy_path(forge_dir)
    if not legacy_path.exists():
        raise ForgeManifestError(
            f"forge `{slug}` has no legacy manifest at {legacy_path}; nothing to migrate"
        )

    forge_manifest = _legacy_to_forge_manifest(slug, legacy_path)
    arrangement_manifest = _legacy_to_arrangement_manifest(slug, legacy_path)

    fm_path = write_auto_curation(forge_dir, forge_manifest)
    am_path = write_arrangement(forge_dir, arrangement_manifest)
    return fm_path, am_path
