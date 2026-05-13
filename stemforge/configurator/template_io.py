"""Filesystem scan for Phase 3A config templates (``~/stemforge/templates/``).

A **config template** in v1 is a Live device-group preset (``.adg``) stored at
``~/stemforge/templates/<name>.adg``. The configurator's popup surfaces the
templates as a per-group dropdown; assigning a template to a curation group
fires a server→device notification so the staging track hot-applies the rack.

This module is pure I/O:

* :func:`list_templates` walks the templates dir and returns one
  :class:`TemplateIndexEntry` per ``.adg`` file (alphabetically stable).
* Optional ``<name>.description`` sidecar (plain text, UTF-8) is read into
  the ``description`` field when present.
* :func:`resolve_template_path` validates a template name and returns its
  ``.adg`` path, or raises an HTTPException — used by the PATCH route to
  reject unknown templates with a 404.

The endpoints themselves live in :mod:`stemforge.configurator.server`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException

# A template name is what the user types in the dropdown — the filename minus
# the ``.adg`` suffix. The same forbidden-token set as the curation/forge
# slug validators keeps us out of obvious path-traversal trouble; the user
# generally chooses these names in Live's Save Device Group dialog.
_NAME_FORBIDDEN = ("/", "\\", "..", "\x00")
TEMPLATE_SUFFIX = ".adg"
DESCRIPTION_SUFFIX = ".description"


@dataclass
class TemplateIndexEntry:
    """One row in ``GET /templates`` — projection over a single ``.adg`` file."""

    name: str
    path: str
    modified_at: str
    size_bytes: int
    description: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Wire shape — drops ``description`` when missing for compactness."""
        payload: dict[str, object] = {
            "name": self.name,
            "path": self.path,
            "modified_at": self.modified_at,
            "size_bytes": self.size_bytes,
        }
        if self.description is not None:
            payload["description"] = self.description
        return payload


def default_templates_dir() -> Path:
    """Return the canonical templates dir (``~/stemforge/templates``)."""
    return Path.home() / "stemforge" / "templates"


def _is_valid_template_name(name: str) -> bool:
    """Reject obvious path-traversal patterns; otherwise accept verbatim."""
    if not isinstance(name, str) or not name:
        return False
    if any(token in name for token in _NAME_FORBIDDEN):
        return False
    # The name is the basename without ``.adg`` — guard against callers that
    # accidentally pass the suffix in. ``str.endswith`` keeps the test simple
    # while still letting names contain dots (e.g. ``vocal.classic.v2``).
    if name.endswith(TEMPLATE_SUFFIX):
        return False
    return True


def _modified_at_iso(path: Path) -> str:
    """ISO-8601 mtime for ``path`` (UTC). Empty string on a missing file."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return ""
    return datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat()


def _read_description(adg_path: Path) -> str | None:
    """Read the optional ``<name>.description`` sidecar.

    Returns the file's stripped text content, or ``None`` when no sidecar
    exists. A sidecar that exists but is unreadable also returns ``None``
    (we don't fail the index over a permissions glitch on a doc file).
    """
    sidecar = adg_path.with_suffix(DESCRIPTION_SUFFIX)
    if not sidecar.is_file():
        return None
    try:
        text = sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def list_templates(templates_dir: Path) -> list[TemplateIndexEntry]:
    """Scan ``templates_dir`` and return one entry per ``.adg`` file.

    Returns ``[]`` when the directory doesn't exist yet — first-run-friendly.
    Entries are stable-sorted alphabetically by ``name`` so the popup's
    dropdown order matches between renders and across machines.
    """
    if not templates_dir.is_dir():
        return []
    entries: list[TemplateIndexEntry] = []
    for child in sorted(templates_dir.iterdir()):
        if not child.is_file():
            continue
        if child.suffix != TEMPLATE_SUFFIX:
            continue
        if child.name.startswith("."):
            continue
        name = child.stem
        if not _is_valid_template_name(name):
            # Path-traversal-ish names that snuck onto disk; skip rather
            # than expose them to the popup.
            continue
        try:
            size_bytes = child.stat().st_size
        except OSError:
            size_bytes = 0
        entries.append(
            TemplateIndexEntry(
                name=name,
                path=str(child),
                modified_at=_modified_at_iso(child),
                size_bytes=size_bytes,
                description=_read_description(child),
            )
        )
    return entries


def resolve_template_path(templates_dir: Path, name: str) -> Path:
    """Return the ``.adg`` path for ``name`` or raise 404.

    Raises:
        HTTPException(400): malformed ``name`` (path-traversal-ish).
        HTTPException(404): the file doesn't exist.
    """
    if not _is_valid_template_name(name):
        raise HTTPException(status_code=400, detail=f"invalid template name: {name!r}")
    path = templates_dir / f"{name}{TEMPLATE_SUFFIX}"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"template not found: {name}")
    return path


def template_exists(templates_dir: Path, name: str) -> bool:
    """Return ``True`` iff ``<name>.adg`` is present in ``templates_dir``.

    Used by :func:`stemforge.configurator.intents.handle_patch_template` to
    reject assigning an unknown template name before it lands in the YAML.
    Non-existent ``templates_dir`` returns ``False`` instead of raising —
    matches :func:`list_templates`'s first-run friendliness.
    """
    if not _is_valid_template_name(name):
        return False
    if not templates_dir.is_dir():
        return False
    return (templates_dir / f"{name}{TEMPLATE_SUFFIX}").is_file()


__all__ = [
    "DESCRIPTION_SUFFIX",
    "TEMPLATE_SUFFIX",
    "TemplateIndexEntry",
    "default_templates_dir",
    "list_templates",
    "resolve_template_path",
    "template_exists",
]
