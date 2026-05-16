"""Atomic read/write + file-lock helpers for curation YAML files.

Per spec §2.3 and execution plan Lane 1B: the configurator server is the
sole writer of ``~/stemforge/curations/<name>.yaml``. To survive
mid-write crashes, concurrent COMMITs from multiple devices/popups, and
the inevitable "save while bouncing" race, every write goes through
:func:`write_curation_atomic`. Every read uses :func:`read_curation` for
Pydantic-validated parsing. The :func:`lock_curation` context manager
wraps both with a POSIX advisory lock (``fcntl.flock``) on a sidecar
``.lock`` file so concurrent processes (not just threads) serialize.

The lock target is intentionally a sidecar (``<path>.lock``) rather than
the curation file itself: that way the lock survives the atomic
``rename`` step (which would otherwise unlink-from-underneath an open
lock fd) and tests can sniff for lock contention without parsing YAML.

This module is local-only and macOS-targeted. ``fcntl.flock`` is BSD-ish
and works on Linux + macOS; Windows is out of scope for v1.
"""

from __future__ import annotations

import errno
import fcntl
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import yaml

from .schemas import Curation

# ── Curation name validation ─────────────────────────────────────────────────

# Allow letters, digits, ``_``, ``-``, ``.``. Reject slashes (would break
# the ``curations/<name>.yaml`` invariant) and shell-meta. Length 1-64.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")

# Filenames whose lowercased stems are reserved for control state.
_RESERVED_NAMES = frozenset(
    {
        ".stemforge_state",
        ".configurator_port",
        "stemforge_state",
        "configurator_port",
        # POSIX-y reserved
        ".",
        "..",
    }
)


def is_valid_curation_name(name: str) -> bool:
    """Return True if ``name`` is a syntactically legal curation name.

    Rules:
      - 1–64 characters
      - First character is alphanumeric
      - Subsequent characters are ``[A-Za-z0-9_.-]``
      - Not in :data:`_RESERVED_NAMES`
      - No path separators, no leading dot beyond reserved-list checks
    """
    if not isinstance(name, str):
        return False
    if name.lower() in _RESERVED_NAMES:
        return False
    if "/" in name or "\\" in name:
        return False
    return bool(_NAME_RE.match(name))


# ── Paths ────────────────────────────────────────────────────────────────────


def default_curations_dir() -> Path:
    """Return the canonical curations directory (``~/stemforge/curations``)."""
    return Path.home() / "stemforge" / "curations"


def curation_path(curations_dir: Path, name: str) -> Path:
    """Resolve the on-disk path for a curation by name.

    Caller is responsible for validating ``name`` first via
    :func:`is_valid_curation_name`.
    """
    return curations_dir / f"{name}.yaml"


# ── Read / write ─────────────────────────────────────────────────────────────


def read_curation(path: Path) -> Curation:
    """Parse a curation YAML file into a validated :class:`Curation`.

    Raises:
        FileNotFoundError: if the file is missing.
        pydantic.ValidationError: if the YAML doesn't match the schema.
        yaml.YAMLError: on malformed YAML.
    """
    data = yaml.safe_load(path.read_text())
    if data is None:
        # Empty file → empty mapping. Pydantic will then complain about
        # missing required fields, which is the correct error.
        data = {}
    if not isinstance(data, dict):
        raise yaml.YAMLError(f"curation YAML root must be a mapping, got {type(data).__name__}")
    return Curation.model_validate(data)


def _dump_yaml(curation: Curation) -> str:
    """Serialize a Curation to its on-disk YAML form."""
    # ``model_dump(mode="json")`` collapses datetimes to ISO strings which
    # is what we want on disk. ``yaml.safe_dump`` then renders that
    # plain-Python tree.
    #
    # ``width`` is set huge to DISABLE line-wrapping. PyYAML's default
    # (width=80) folds long plain scalars across multiple indented lines
    # — valid YAML, but the M4L device's hand-rolled line-based parser
    # (``_yamlParseCuration``) can't follow a folded scalar and rejects
    # the file. Long ``external_path`` values (Ableton's deep
    # ``Samples/Processed/Crop/...`` paths) tripped exactly this. One
    # scalar per line keeps the device parser — and humans — happy.
    payload = curation.model_dump(mode="json")
    return yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=1_000_000,
    )


def write_curation_atomic(path: Path, curation: Curation) -> None:
    """Atomically persist ``curation`` to ``path``.

    Strategy: write to ``<path>.tmp.<pid>.<rand>`` in the same directory,
    ``fsync`` it, then ``os.replace`` it onto ``path``. ``os.replace`` is
    atomic on POSIX same-volume renames, so concurrent readers either see
    the old file or the new file, never a partial one.

    Caller is expected to hold :func:`lock_curation` if cross-process
    write-ordering matters.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _dump_yaml(curation)
    # ``delete=False`` so we own the lifecycle: write, fsync, rename.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup; the temp file is named distinctly so this
        # doesn't risk clobbering anyone else's tmp.
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def rename_curation_atomic(src: Path, dst: Path) -> None:
    """Rename ``src`` → ``dst`` atomically on the same filesystem.

    Used by ``POST /curations/{name}/rename``. The caller is expected to
    hold both files' :func:`lock_curation` advisory locks for the
    duration so concurrent writers don't clobber either side. The rename
    itself is :func:`os.replace`, which is atomic on POSIX same-volume
    moves.

    Raises :class:`FileNotFoundError` when ``src`` is missing and
    :class:`FileExistsError` when ``dst`` already exists. The latter is
    deliberate — overwriting an existing curation in a rename would lose
    data; the caller surfaces this as 409.
    """
    if not src.is_file():
        raise FileNotFoundError(f"source curation missing: {src}")
    if dst.exists():
        raise FileExistsError(f"destination curation exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    # Best-effort: rename the lock sidecar too so future ``lock_curation``
    # calls on the new path find the same flock target. Missing sidecar
    # is fine — :func:`lock_curation` creates one on demand.
    src_sidecar = src.with_suffix(src.suffix + ".lock")
    dst_sidecar = dst.with_suffix(dst.suffix + ".lock")
    if src_sidecar.exists() and not dst_sidecar.exists():
        try:
            os.replace(src_sidecar, dst_sidecar)
        except OSError:
            # Lock sidecar move is non-critical; flock() will recreate.
            pass


# ── File lock ────────────────────────────────────────────────────────────────


@contextmanager
def lock_curation(path: Path, *, blocking: bool = True) -> Iterator[None]:
    """Context manager that holds an exclusive POSIX advisory lock.

    Locks a sidecar file at ``<path>.lock`` (created on demand) rather
    than ``path`` itself so the ``os.replace`` in
    :func:`write_curation_atomic` can swing the data file out without
    invalidating the lock.

    When ``blocking=False`` and the lock is already held, raises
    :class:`BlockingIOError`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    # O_CREAT so we don't require the file to exist beforehand.
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise BlockingIOError(f"curation locked: {path}") from exc
            raise
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# ── Discovery ────────────────────────────────────────────────────────────────


def list_curations(curations_dir: Path) -> list[Path]:
    """Return all ``*.yaml`` files under ``curations_dir``, stably sorted.

    Returns an empty list if the directory doesn't exist yet.
    """
    if not curations_dir.is_dir():
        return []
    return sorted(curations_dir.glob("*.yaml"))


__all__ = [
    "curation_path",
    "default_curations_dir",
    "is_valid_curation_name",
    "list_curations",
    "lock_curation",
    "read_curation",
    "rename_curation_atomic",
    "write_curation_atomic",
]
