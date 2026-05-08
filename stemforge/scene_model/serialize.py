"""Project disk + JSON serialization (round-trip-safe).

Single owner for ``Project`` ↔ JSON / disk I/O. Wraps pydantic v2's
``model_dump_json`` / ``model_validate_json`` with the project's house
defaults (``indent=2``, ``exclude_none=True``).

Round-trip equality is the contract: ``project_from_json(project_to_json(p)) == p``.
"""

from __future__ import annotations

from pathlib import Path

from .schema import Project


def project_to_json(project: Project) -> str:
    """Serialize a ``Project`` to its canonical JSON form."""
    return project.model_dump_json(indent=2, exclude_none=True)


def project_from_json(text: str) -> Project:
    """Deserialize JSON text into a ``Project``. Raises pydantic ValidationError on bad input."""
    return Project.model_validate_json(text)


def project_to_path(project: Project, path: Path) -> None:
    """Write the canonical JSON form of ``project`` to ``path`` (creates parent dirs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(project_to_json(project))


def project_from_path(path: Path) -> Project:
    """Read a ``Project`` from ``path``."""
    return project_from_json(path.read_text())


__all__ = [
    "project_from_json",
    "project_from_path",
    "project_to_json",
    "project_to_path",
]
