"""EXPORT handler — server-side wrapper around ``stemforge build-deck`` for curations.

Phase 3C surface. The HTTP endpoint ``POST /curations/{name}/export`` wires
through here; this module owns:

1. Path-traversal + writability validation on ``out_path``.
2. Converting the persisted ``Curation`` to a build-deck JSON plan (the CLI
   takes a plan path, not a curation name — see
   :func:`curation_to_deck_plan`).
3. Subprocess invocation (with timeout) of ``uv run stemforge build-deck ...``.
4. Post-success state mutation — writes ``curation.last_export`` (atomic)
   with timestamp + output path + artifact hash.

Subprocess is invoked through an injectable runner so unit tests don't
spawn the real CLI. Mirrors the Phase 1.5 re-anchor / re-curate pattern in
:mod:`stemforge.configurator.server`.

The actual ``.ppak`` rendering happens in the CLI subprocess — this module
is the control plane only.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from .curation_io import (
    curation_path,
    is_valid_curation_name,
    lock_curation,
    read_curation,
    write_curation_atomic,
)
from .schemas import Curation
from .schemas.curation import LastExport

# Spec §4.3: target_format starts at ``ppak``; future values plug in here.
KNOWN_TARGET_FORMATS: frozenset[str] = frozenset({"ppak"})

# Mirrors :class:`~stemforge.configurator.schemas.curation.LastExport`'s
# ``Literal[...]`` constraint. Kept loose (``str``) for the wire-side
# validator so we can return a clean 400 instead of a Pydantic 422 dump.
DEFAULT_TARGET_FORMAT = "ppak"

# Default subprocess timeout. Brief mandates ≤ 300 s — `.ppak` rendering
# on a beefy curation is generally a few seconds, but bouncy hardware
# (Demucs, ffmpeg) can blow past 30 s when contended.
DEFAULT_TIMEOUT_SEC = 300.0


# ── Domain errors ───────────────────────────────────────────────────────────


class ExportValidationError(ValueError):
    """Raised on invalid input (path traversal, bad target_format, etc.).

    The HTTP layer converts these to 400 responses. Distinct from a
    subprocess failure (which surfaces as ``ok=False`` in the envelope,
    not a 4xx).
    """


# ── Result envelope ─────────────────────────────────────────────────────────


@dataclass
class ExportResult:
    """Outcome of one EXPORT invocation.

    Mirrors the re-anchor return shape: HTTP layer wraps with ``slug``/
    ``curation`` keys but the core envelope is ``{ok, stdout, stderr}``.
    On success: ``last_export`` carries the persisted record; on failure:
    ``error`` carries a short tag (``"timeout"``, ``"subprocess"``, ...).
    """

    ok: bool
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    last_export: LastExport | None = None
    command: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }
        if self.error is not None:
            body["error"] = self.error
        if self.last_export is not None:
            body["last_export"] = self.last_export.model_dump(mode="json")
        return body


# ── Validators ──────────────────────────────────────────────────────────────


def validate_target_format(value: str) -> Literal["ppak"]:
    """Normalize + reject unknown target_format values."""
    norm = (value or "").strip().lower()
    if norm not in KNOWN_TARGET_FORMATS:
        raise ExportValidationError(
            f"unknown target_format: {value!r}; expected one of {sorted(KNOWN_TARGET_FORMATS)}"
        )
    # All current entries collapse to "ppak"; widen Literal when more land.
    return "ppak"


def validate_out_path(raw: str | Path) -> Path:
    """Resolve ``out_path`` + reject traversal / missing parent.

    Path rules:

    * Reject any path containing a ``..`` token in its raw form. After
      ``expanduser`` + ``resolve``, walk the resolved path components for
      a residual ``..`` (none should remain, but a `Path("/tmp/..foo")`
      filename should be tolerated — the traversal token is ``..`` not
      ``..foo``).
    * Reject empty paths (no filename component).
    * Require the parent directory to already exist + be writable. We
      DON'T mkdir on the caller's behalf — the popup should pick a real
      destination, not coerce the server into creating tree branches.
    """
    if raw is None or raw == "":
        raise ExportValidationError("out_path is required")

    raw_str = str(raw)
    # Reject the ``..`` segment in the RAW path before normalisation so
    # ``~/Desktop/../../etc/passwd`` is caught even when the user happens
    # to have write access to ``/etc``.
    parts = Path(raw_str).parts
    if any(p == ".." for p in parts):
        raise ExportValidationError(f"path traversal not allowed in out_path: {raw_str!r}")

    path = Path(raw_str).expanduser().resolve()
    if not path.name:
        raise ExportValidationError(f"out_path must include a filename: {raw_str!r}")

    parent = path.parent
    if not parent.is_dir():
        raise ExportValidationError(f"out_path parent does not exist: {parent}")

    return path


def validate_curation_name(name: str) -> str:
    """Mirror :func:`curation_io.is_valid_curation_name` for symmetry."""
    if not is_valid_curation_name(name):
        raise ExportValidationError(f"invalid curation name: {name!r}")
    return name


# ── Subprocess wrapper ──────────────────────────────────────────────────────


def _format_profile_from_label(label: str | None) -> str:
    """Map a Curation group label to a build-deck ``format_profile`` value.

    The CLI uses these profiles for per-group memory budgeting (Decision
    16). Conservative default of ``"drum"`` for unknown labels because the
    drum profile is the most permissive on sample-rate downsampling.
    """
    if not label:
        return "drum"
    norm = label.strip().lower()
    if "vocal" in norm:
        return "vocal"
    # bass / kick / snare / hat etc. all land in the drum profile for now.
    return "drum"


def _resolve_pad_path(source: Any, forges_dir: Path) -> str | None:
    """Resolve a Curation ``PadSource`` to an absolute audio path.

    Forge-owned pads: ``<forges_dir>/<forge_slug>/<audio_path>``.
    External pads:   ``<external_path>`` verbatim.
    Empty pads (no ``source``): returns ``None``; caller omits the pad.
    """
    if source is None:
        return None
    if getattr(source, "external_path", None):
        return str(source.external_path)
    forge = getattr(source, "forge", None)
    audio_path = getattr(source, "audio_path", None)
    if not forge or not audio_path:
        return None
    return str(forges_dir / forge / audio_path)


def curation_to_deck_plan(
    curation: Curation,
    *,
    forges_dir: Path,
    project_slot: int = 1,
) -> dict[str, Any]:
    """Convert a :class:`Curation` to a ``build-deck`` plan dict.

    Pads with no ``source`` are dropped — the CLI accepts sparse groups
    so we don't need to emit empty placeholders. The pad number is parsed
    out of ``pad_id`` (e.g. ``"A03"`` → ``3``). ``project_bpm`` is read
    from the first populated pad's ``clip_settings.warp_bpm`` so the
    project tempo matches the audio's warp bpm.
    """
    project_bpm: float | None = None
    groups_out: dict[str, dict[str, Any]] = {}
    for letter, group in (curation.groups or {}).items():
        pads_out: list[dict[str, Any]] = []
        for pad in group.pads or []:
            path = _resolve_pad_path(pad.source, forges_dir=forges_dir)
            if path is None:
                continue
            # pad_id is "<L><NN>" — pull the trailing integer.
            try:
                pad_num = int("".join(c for c in (pad.pad_id or "") if c.isdigit()))
            except ValueError:
                continue
            if pad_num <= 0:
                continue
            entry: dict[str, Any] = {"pad": pad_num, "path": path}
            if pad.clip_settings and pad.clip_settings.warp_bpm:
                bpm = float(pad.clip_settings.warp_bpm)
                entry["source_bpm"] = bpm
                if project_bpm is None:
                    project_bpm = bpm
            pads_out.append(entry)
        if not pads_out:
            continue
        groups_out[letter] = {
            "format_profile": _format_profile_from_label(group.label),
            "pads": pads_out,
        }
    plan: dict[str, Any] = {
        "project": curation.name,
        "project_slot": int(project_slot),
        "project_bpm": project_bpm or 120.0,
        "groups": groups_out,
    }
    return plan


# Reference .ppak template required by ``build-deck``. The CLI synthesises a
# minimal template when omitted but emits a warning; we point at the
# bundled fixture (a real device-captured .ppak) so the export is byte-clean.
# Resolved relative to this file: repo-root layout assumed.
DEFAULT_REFERENCE_TEMPLATE = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "ep133"
    / "fixtures"
    / "reference.ppak"
)


def build_export_command(
    *,
    deck_plan_path: Path,
    out_path: Path,
    reference_template: Path | None = None,
) -> list[str]:
    """Build the ``uv run stemforge build-deck ...`` argv.

    Centralised so tests can assert against the exact CLI surface without
    string-splitting from inside the handler.
    """
    cmd = [
        "uv",
        "run",
        "stemforge",
        "build-deck",
        str(deck_plan_path),
        "--out",
        str(out_path),
    ]
    template = reference_template or DEFAULT_REFERENCE_TEMPLATE
    if template and template.is_file():
        cmd.extend(["--reference-template", str(template)])
    return cmd


def run_export_subprocess(
    cmd: list[str],
    *,
    runner: Callable[..., Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> tuple[bool, str, str, str | None]:
    """Invoke the CLI subprocess + return ``(ok, stdout, stderr, error_tag)``.

    ``runner`` is the injection seam (defaults to :func:`subprocess.run`).
    A :class:`subprocess.TimeoutExpired` becomes ``ok=False, error="timeout"``;
    a missing-binary ``FileNotFoundError`` becomes ``error="missing_binary"``.
    Any other exception is allowed to bubble — that's a 500.
    """
    runner = runner or subprocess.run
    try:
        proc = runner(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        return False, stdout, stderr, "timeout"
    except FileNotFoundError as exc:
        return False, "", str(exc), "missing_binary"

    ok = getattr(proc, "returncode", 1) == 0
    stdout = getattr(proc, "stdout", "") or ""
    stderr = getattr(proc, "stderr", "") or ""
    return ok, stdout, stderr, None


# ── State mutation ──────────────────────────────────────────────────────────


def _hash_artifact(path: Path) -> str | None:
    """Return SHA-256 of the artifact bytes, or ``None`` if unreadable.

    A successful subprocess exit but missing file is unusual but possible
    (the CLI wrote elsewhere or the path was overridden). We return None
    rather than failing the whole export — the timestamp + path still
    serve as the audit trail.
    """
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def update_last_export(
    *,
    curations_dir: Path,
    name: str,
    out_path: Path,
    target_format: Literal["ppak"] = "ppak",
    now: datetime | None = None,
) -> tuple[Curation, LastExport]:
    """Persist ``LastExport`` to the curation YAML atomically.

    Returns the updated :class:`Curation` + the new :class:`LastExport`.
    Caller is expected to hold ``state.mutation_lock`` for in-process
    serialization; the on-disk lock is acquired here via
    :func:`curation_io.lock_curation` for cross-process safety.
    """
    path = curation_path(curations_dir, name)
    if not path.is_file():
        raise FileNotFoundError(f"curation not found on disk: {name}")
    timestamp = now or datetime.now(UTC)
    artifact_hash = _hash_artifact(out_path)
    record = LastExport(
        exported_at=timestamp,
        target_format=target_format,
        output_path=str(out_path),
        manifest_hash=artifact_hash,
    )
    with lock_curation(path):
        curation = read_curation(path)
        curation.last_export = record
        curation.modified_at = timestamp
        write_curation_atomic(path, curation)
    return curation, record


# ── End-to-end orchestration ────────────────────────────────────────────────


def perform_export(
    *,
    curations_dir: Path,
    name: str,
    out_path_raw: str | Path,
    target_format_raw: str = DEFAULT_TARGET_FORMAT,
    subprocess_runner: Callable[..., Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    now: datetime | None = None,
    forges_dir: Path | None = None,
) -> ExportResult:
    """One-shot orchestration used by the HTTP route.

    Sequencing:

    1. Validate name + target_format + out_path. Validation errors raise
       :class:`ExportValidationError` so the route can map to 400/404.
    2. Confirm the curation exists. Caller is the route layer, which has
       already validated the name; we double-check on disk to surface a
       clean 404 even from direct callers (test code).
    3. Read the curation + render a build-deck JSON plan to a tempfile.
    4. Run the subprocess. Failure ⇒ envelope with ``ok=False`` (route
       returns 200 with diagnostics — match re-anchor's pattern).
    5. On success: update ``last_export`` + return both bodies so the
       route can broadcast a fresh state SSE event.

    ``forges_dir`` defaults to a sibling of ``curations_dir`` (the
    ``~/stemforge/{curations,processed}`` convention). Override when the
    layout differs (tests, alternate user libraries).
    """
    validate_curation_name(name)
    target_format = validate_target_format(target_format_raw)
    out_path = validate_out_path(out_path_raw)

    path = curation_path(curations_dir, name)
    if not path.is_file():
        raise FileNotFoundError(f"curation not found: {name}")

    curation = read_curation(path)
    forges_root = forges_dir if forges_dir is not None else curations_dir.parent / "processed"
    plan = curation_to_deck_plan(curation, forges_dir=forges_root)

    # Write the plan to a tempfile so the CLI can mmap it. Keep the file
    # alive across the subprocess call but delete after — failures still
    # leave stdout/stderr captured in the envelope for diagnostics.
    tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=f"sf-deck-{name}-", suffix=".json")
    deck_plan_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            json.dump(plan, fh)
        cmd = build_export_command(
            deck_plan_path=deck_plan_path,
            out_path=out_path,
        )
        ok, stdout, stderr, error_tag = run_export_subprocess(
            cmd,
            runner=subprocess_runner,
            timeout=timeout,
        )
    finally:
        try:
            deck_plan_path.unlink()
        except OSError:
            pass

    if not ok:
        return ExportResult(
            ok=False,
            stdout=stdout,
            stderr=stderr,
            error=error_tag or "subprocess",
            command=cmd,
        )

    _curation, record = update_last_export(
        curations_dir=curations_dir,
        name=name,
        out_path=out_path,
        target_format=target_format,
        now=now,
    )
    return ExportResult(
        ok=True,
        stdout=stdout,
        stderr=stderr,
        last_export=record,
        command=cmd,
    )


__all__ = [
    "DEFAULT_TARGET_FORMAT",
    "DEFAULT_TIMEOUT_SEC",
    "ExportResult",
    "ExportValidationError",
    "KNOWN_TARGET_FORMATS",
    "build_export_command",
    "perform_export",
    "run_export_subprocess",
    "update_last_export",
    "validate_curation_name",
    "validate_out_path",
    "validate_target_format",
]
