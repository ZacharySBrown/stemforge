"""Phase 2 keystone: COMMIT reverse-lookup + curation merge helpers.

The device walks its staging tracks and emits a snapshot keyed on
absolute ``audio_path`` strings (because that's what Live's LOM hands
the device for each clip). The server is the only piece of the system
that knows about the forge index, so the server is the only place that
can resolve ``audio_path`` → ``(forge_slug, clip_id)``.

This module owns that resolution + the merge step that turns a device
snapshot into a fully-typed :class:`Curation`. Kept separate from
:mod:`stemforge.configurator.intents` so it's unit-testable without
spinning up the FastAPI app, the SSE broker, or the asyncio lock.

Spec references:

- §2.3 (Curation file schema, Pad/PadSource shape)
- §6.6 (COMMIT flow)
- §11 (keystone — once this works the architecture's promise holds)

Wire format the device emits (matches :class:`DeviceCommitBody`):

.. code-block:: json

    {
      "als_path": "/Users/zak/Music/proj.als",
      "groups": {
        "A": {
          "label": "Vocals",
          "template": "dry-direct",
          "pads": [
            {
              "pad_id": "A01",
              "audio_path": "/abs/.../curated_audio/vocal-bar4-8.wav",
              "clip_settings": {
                "warp_bpm": 138.0,
                "loop_start_bar": 0,
                "loop_end_bar": 4,
                "looping": true
              }
            }
          ]
        }
      }
    }

The device does NOT send ``source.forge`` / ``source.clip_id`` — those
come from the server-side reverse-lookup, keyed on ``audio_path``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .forge_io import default_processed_dir
from .schemas import (
    ClipSettings,
    Curation,
    ForgeManifest,
    Group,
    Pad,
    PadSource,
    ReferencedForge,
)


# ── Device-snapshot wire shape ────────────────────────────────────────────────


class DevicePadSnapshot(BaseModel):
    """One pad's worth of LOM state from the device walker.

    Only ``pad_id`` is required (empty pads carry just that). When the
    slot held a clip, ``audio_path`` is the absolute path Live reported
    plus ``clip_settings`` captures warp/loop state.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    pad_id: str = Field(..., description="e.g. A01")
    audio_path: str | None = Field(
        default=None,
        description="Absolute audio path Live reported. None for empty pads.",
    )
    clip_settings: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Loose-typed dict (warp_bpm, loop_start_bar, loop_end_bar, "
            "looping). Validated against ClipSettings during merge."
        ),
    )


class DeviceGroupSnapshot(BaseModel):
    """One group's worth of device snapshot — label, template, pads."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    label: str | None = Field(default=None)
    template: str | None = Field(default=None)
    pads: list[DevicePadSnapshot] = Field(default_factory=list)


class DeviceCommitBody(BaseModel):
    """``POST /curations/{name}/commit`` request body — Phase 2 shape.

    The device walks staging tracks and POSTs this. The server does the
    forge reverse-lookup + writes the canonical YAML.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    als_path: str | None = Field(
        default=None,
        description="Optional .als path for active-curation persistence (Phase 4A).",
    )
    groups: dict[str, DeviceGroupSnapshot] = Field(default_factory=dict)


# ── Reverse-lookup ────────────────────────────────────────────────────────────


class _ForgePathIndex:
    """Reverse index: absolute audio path → (forge_slug, clip_id).

    Built once per commit from the scanned forge manifests so the
    per-pad lookup is O(1). The processed-dir scan is the slow part
    (it parses every manifest JSON); we amortize it across all pads
    in the commit.

    Both ``clips`` (auto-curation) and ``chunks`` (arrangement) are
    indexed because the device may stage from either side.
    """

    def __init__(self, processed_dir: Path) -> None:
        self.processed_dir = processed_dir
        # audio_path (absolute) → (forge_slug, clip_id)
        self._by_path: dict[str, tuple[str, str]] = {}
        # forge_slug → manifest_hash at scan time
        self._hashes: dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        if not self.processed_dir.is_dir():
            return
        # Use the same scanner as the /forges endpoint so we honor the
        # same "what counts as a forge" rules.
        for child in sorted(self.processed_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            self._ingest_forge(child)

    def _ingest_forge(self, forge_dir: Path) -> None:
        from stemforge.forge.manifest_io import (
            ARRANGEMENT_FILENAME,
            AUTO_CURATION_FILENAME,
            ForgeManifestError,
            load_arrangement,
            load_forge,
        )

        slug = forge_dir.name
        auto_path = forge_dir / AUTO_CURATION_FILENAME
        if auto_path.is_file():
            try:
                manifest: ForgeManifest = load_forge(slug, forge_dir=forge_dir)
            except ForgeManifestError:
                manifest = None  # type: ignore[assignment]
            if manifest is not None:
                self._hashes[slug] = manifest.manifest_hash
                for clip in manifest.clips:
                    abs_path = str((forge_dir / clip.audio_path).resolve())
                    self._by_path[abs_path] = (slug, clip.clip_id)
                    # Also index the rel-path-from-home and the path-with-
                    # symlinks-unresolved variants so devices that report a
                    # non-canonicalized path still resolve.
                    raw = str(forge_dir / clip.audio_path)
                    if raw != abs_path:
                        self._by_path.setdefault(raw, (slug, clip.clip_id))

        arr_path = forge_dir / ARRANGEMENT_FILENAME
        if arr_path.is_file():
            try:
                arrangement = load_arrangement(slug, forge_dir=forge_dir)
            except ForgeManifestError:
                arrangement = None
            if arrangement is not None:
                # arrangement manifest has its own hash; we don't surface
                # it because referenced_forges keys on auto-curation hash.
                for chunk in arrangement.chunks:
                    abs_path = str((forge_dir / chunk.audio_path).resolve())
                    self._by_path[abs_path] = (slug, chunk.chunk_id)
                    raw = str(forge_dir / chunk.audio_path)
                    if raw != abs_path:
                        self._by_path.setdefault(raw, (slug, chunk.chunk_id))

    def lookup(self, audio_path: str) -> tuple[str, str] | None:
        """Resolve ``audio_path`` → ``(forge_slug, clip_id)`` if known."""
        if not audio_path:
            return None
        candidate = audio_path
        # Try the path as given, then a canonicalized version. The device
        # may emit either (Live's `file_path` is the as-loaded path).
        hit = self._by_path.get(candidate)
        if hit is not None:
            return hit
        try:
            resolved = str(Path(candidate).resolve())
        except OSError:
            resolved = candidate
        return self._by_path.get(resolved)

    def manifest_hash(self, forge_slug: str) -> str:
        """Return the recorded manifest_hash for ``forge_slug`` (or '')."""
        return self._hashes.get(forge_slug, "")


def resolve_audio_to_source(
    audio_path: str,
    index: _ForgePathIndex,
) -> PadSource:
    """Reverse-lookup helper exposed for direct unit testing.

    Returns a forge-owned :class:`PadSource` when ``audio_path`` is in
    a known forge, an external-path :class:`PadSource` otherwise.
    """
    hit = index.lookup(audio_path)
    if hit is None:
        return PadSource.for_external(audio_path)
    forge_slug, clip_id = hit
    # Re-derive the relative path so the curation file stores the path
    # the way it would round-trip cleanly through LOAD (which already
    # resolves relative to the forge dir).
    try:
        rel = str(
            Path(audio_path).resolve().relative_to((index.processed_dir / forge_slug).resolve())
        )
    except (ValueError, OSError):
        # Couldn't compute a clean relative path; fall back to absolute.
        rel = audio_path
    return PadSource.for_forge(forge_slug, clip_id, rel)


# ── Merge: device snapshot → Curation ────────────────────────────────────────


def merge_device_snapshot(
    *,
    existing: Curation,
    body: DeviceCommitBody,
    processed_dir: Path | None = None,
) -> Curation:
    """Merge ``body`` (device snapshot) into ``existing``, return new Curation.

    Behavior:

    * Each group in ``body.groups`` replaces the same letter in
      ``existing.groups`` wholesale (pad list AND label/template when
      the device sent non-None values; otherwise preserve existing).
    * Each pad's ``audio_path`` is reverse-looked-up against the forge
      index. ``source`` is set accordingly.
    * Empty pads (no ``audio_path``) become ``Pad(pad_id=...)`` with no
      ``source`` or ``clip_settings``.
    * ``clip_settings`` is funneled through :class:`ClipSettings` so the
      device's loose-typed dict can't sneak invalid shapes into the file.
    * ``referenced_forges`` is rebuilt from the union of pad sources in
      the merged groups, with hashes from the forge index at commit time.
    * ``modified_at`` is bumped to ``datetime.now(UTC)``.

    The function is pure (no I/O beyond the forge scan); callers do the
    atomic write themselves.

    Raises :class:`pydantic.ValidationError` if any pad fails the schema.
    """
    if processed_dir is None:
        processed_dir = default_processed_dir()
    index = _ForgePathIndex(processed_dir)

    merged = existing.model_copy(deep=True)
    for raw_letter, group_snap in body.groups.items():
        letter = raw_letter.upper()
        new_pads: list[Pad] = []
        for pad_snap in group_snap.pads:
            new_pads.append(_pad_from_snapshot(pad_snap, index))
        existing_group = existing.groups.get(letter)
        label = (
            group_snap.label
            if group_snap.label is not None
            else (existing_group.label if existing_group else "")
        )
        template = (
            group_snap.template
            if group_snap.template is not None
            else (existing_group.template if existing_group else None)
        )
        merged.groups[letter] = Group(label=label, template=template, pads=new_pads)

    # Rebuild referenced_forges from the union of pad sources we just merged.
    referenced: dict[str, str] = {}
    for group in merged.groups.values():
        for pad in group.pads:
            if pad.source is None or pad.source.forge is None:
                continue
            slug = pad.source.forge
            if slug in referenced:
                continue
            # Prefer the just-scanned hash; fall back to whatever the
            # existing curation knew so we don't regress to "" when the
            # forge has been moved/deleted between commits.
            scanned = index.manifest_hash(slug)
            if scanned:
                referenced[slug] = scanned
            else:
                prior = next(
                    (f.manifest_hash for f in existing.referenced_forges if f.slug == slug),
                    "",
                )
                referenced[slug] = prior
    merged.referenced_forges = [
        ReferencedForge(slug=slug, manifest_hash=h) for slug, h in sorted(referenced.items())
    ]

    merged.modified_at = datetime.now(UTC)
    return merged


def _pad_from_snapshot(
    pad_snap: DevicePadSnapshot,
    index: _ForgePathIndex,
) -> Pad:
    """Build one :class:`Pad` from a device snapshot entry.

    Empty pads (no ``audio_path``) come out source-less. Populated pads
    get the reverse-lookup treatment + :class:`ClipSettings` validation.
    """
    pad_dict: dict[str, Any] = {"pad_id": pad_snap.pad_id}
    if pad_snap.audio_path:
        source = resolve_audio_to_source(pad_snap.audio_path, index)
        pad_dict["source"] = source.model_dump(exclude_none=True)
        if pad_snap.clip_settings is not None:
            # Validate the device's loose dict against ClipSettings so a
            # malformed snapshot fails fast (the FastAPI route converts
            # ValidationError → 422).
            settings = ClipSettings.model_validate(_normalize_clip_settings(pad_snap.clip_settings))
            pad_dict["clip_settings"] = settings.model_dump()
    try:
        return Pad.model_validate(pad_dict)
    except ValidationError:
        # Propagate; the route layer turns this into 422.
        raise


# ── Loose → strict clip_settings normaliser ──────────────────────────────────


def _normalize_clip_settings(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce the device's loose-typed clip_settings into ClipSettings shape.

    The device JS captures Live's ``warp_bpm`` (number), ``loop_start`` /
    ``loop_end`` (in beats), and ``looping`` (0/1 → bool). The schema
    uses bar-units; we let the device send ``loop_start_bar`` /
    ``loop_end_bar`` directly when it can (loadCuration handled this
    inversion), and fall back to converting from beats when only the
    raw LOM names are present (4 beats/bar in 4/4).
    """
    out = dict(raw)
    if "warp_bpm" in out:
        out["warp_bpm"] = float(out["warp_bpm"])
    if "loop_start_bar" not in out and "loop_start" in out:
        out["loop_start_bar"] = float(out["loop_start"]) / 4.0
    if "loop_end_bar" not in out and "loop_end" in out:
        out["loop_end_bar"] = float(out["loop_end"]) / 4.0
    if "looping" in out:
        out["looping"] = bool(out["looping"])
    # Drop the raw LOM-units fields so the strict schema doesn't trip
    # on extra-forbid.
    out.pop("loop_start", None)
    out.pop("loop_end", None)
    return out


__all__ = [
    "DeviceCommitBody",
    "DeviceGroupSnapshot",
    "DevicePadSnapshot",
    "merge_device_snapshot",
    "resolve_audio_to_source",
    "_ForgePathIndex",
]
