"""Forge file-shape I/O (Phase 1A, ``feat/configurator-1a-cli-migration``).

The configurator v1 (spec §2.2) splits a forge's on-disk surface into two
sibling files instead of the single legacy ``curated/manifest.json``:

- ``auto_curation_manifest.json`` — the auto-curated deck (clips array,
  ``schema_version``, ``manifest_hash``).
- ``arrangement_manifest.json`` — arrangement-view chunks (chunks array,
  ``schema_version``, ``manifest_hash``).

``manifest_io.load_forge`` is the single entry point for reading either
shape; it auto-detects and converts legacy → new for one release before
the legacy ``manifest.json`` is dropped in a follow-up cleanup.
"""

from .manifest_io import (
    LegacyForgeError,
    ForgeManifestError,
    load_forge,
    load_arrangement,
    write_auto_curation,
    write_arrangement,
    migrate_legacy,
    legacy_manifest_exists,
    new_manifest_exists,
    build_from_curated_dict,
    build_empty_arrangement,
)

__all__ = [
    "LegacyForgeError",
    "ForgeManifestError",
    "load_forge",
    "load_arrangement",
    "write_auto_curation",
    "write_arrangement",
    "migrate_legacy",
    "legacy_manifest_exists",
    "new_manifest_exists",
    "build_from_curated_dict",
    "build_empty_arrangement",
]
