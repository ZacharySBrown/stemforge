"""NDJSON audit-trail emitter (Hardening Stream C.1).

Vendored from the external harness at
``~/raindog/harness/quickstarts/max-plugin/tools/forge_device/audit.py``
(harness commit ``26f4d02``). The fork point is recorded in
``_HARNESS_VERSION``; bumping this constant + diffing against the upstream
file is how stemforge keeps the vendor in step.

Every meaningful step in a CLI run can emit an event to a file at
``~/stemforge/audit/<run_id>.ndjson``. The audit trail is hashable
(each event has stable fields), replayable (re-run a recorded audit and
verify same artifacts), and aggregatable (jq queries reveal verifier
hit-rates, refinement convergence, irreducible manual steps).

Design goals (inherited from the harness):
    1. One event per line — append-safe under concurrent writers
    2. ISO-8601 UTC timestamps — stable across timezones
    3. SHA256 hashes for every artifact — provenance proof
    4. Schema-versioned — `_schema` field on every event
    5. Replayable — `replay()` re-emits events from a prior audit

Usage in stemforge CLI commands::

    @cli.command()
    @with_audit("forge")
    def forge(...):
        ...

The ``with_audit`` decorator opens an ``Audit``, wraps the call in
``audit.step(name)`` (start/complete with duration_ms; .error on
exceptions), and closes the audit log on return.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

# Vendor reference — harness commit this audit module was last synced from.
# See module docstring for the upstream path. To re-vendor:
#   1. cp ~/raindog/harness/quickstarts/max-plugin/tools/forge_device/audit.py
#      stemforge/audit.py
#   2. Re-apply the stemforge-specific additions (this constant,
#      `audit_path_for`, `with_audit`, `STEMFORGE_AUDIT_DIR`).
#   3. Update _HARNESS_VERSION below.
_HARNESS_VERSION = "26f4d02"

AUDIT_SCHEMA_VERSION = "1.0.0"

# Default audit directory. Test runs override via ``STEMFORGE_AUDIT_DIR``
# env var so they don't pollute the user's real audit history.
STEMFORGE_AUDIT_DIR = Path(
    os.environ.get("STEMFORGE_AUDIT_DIR") or "~/stemforge/audit"
).expanduser()


# ── Module-private helpers ───────────────────────────────────────────────────


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _git_sha(repo_root: Path | None = None) -> str | None:
    """Best-effort git sha of the repo containing this file."""
    repo = repo_root or Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Audit emitter ────────────────────────────────────────────────────────────


class Audit:
    """Append-only NDJSON audit emitter.

    Fields automatically attached to every event:
        ts, _schema, run_id, host, harness_sha, harness_vendor_sha
    """

    def __init__(
        self,
        path: str | Path,
        *,
        run_id: str | None = None,
        harness_sha: str | None = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or f"{int(time.time())}-{os.getpid()}"
        self.harness_sha = harness_sha or _git_sha()
        self.harness_vendor_sha = _HARNESS_VERSION
        self.host = socket.gethostname()
        self._fp: Any = None
        self._closed = False

    def __enter__(self) -> Audit:
        self._fp = open(self.path, "a", encoding="utf-8")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._fp and not self._closed:
            self._fp.flush()
            self._fp.close()
            self._closed = True

    def emit(self, event: str, **fields: Any) -> dict[str, Any]:
        """Emit one event. Returns the full event dict (after auto-fields)."""
        if self._closed:
            raise RuntimeError("audit log closed")
        # Map `pass_` → `pass` to avoid Python keyword collision in callers.
        if "pass_" in fields:
            fields["pass"] = fields.pop("pass_")
        record = {
            "ts": _utc_iso(),
            "_schema": AUDIT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "host": self.host,
            "harness_sha": self.harness_sha,
            "harness_vendor_sha": self.harness_vendor_sha,
            "event": event,
            **fields,
        }
        if self._fp is None:
            self._fp = open(self.path, "a", encoding="utf-8")
        self._fp.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._fp.flush()
        return record

    def hash_artifact(
        self, path: str | Path, *, kind: str = "artifact", module: str | None = None
    ) -> str:
        """Hash a file and emit `artifact.hashed`. Returns the sha256."""
        p = Path(path)
        sha = sha256_path(p)
        size = p.stat().st_size
        self.emit(
            "artifact.hashed",
            phase="build",
            kind=kind,
            module=module,
            path=str(p),
            sha256=sha,
            bytes=size,
        )
        return sha

    @contextmanager
    def step(self, name: str, *, phase: str = "build", **extra: Any) -> Iterator[dict[str, Any]]:
        """Context manager: emit ``<name>.start``, time the block, emit
        ``<name>.complete`` with ``duration_ms``. On exception, emit
        ``<name>.error`` and re-raise.
        """
        ctx: dict[str, Any] = dict(extra)
        t0 = time.perf_counter()
        self.emit(f"{name}.start", phase=phase, **ctx)
        try:
            yield ctx
        except Exception as e:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            self.emit(
                f"{name}.error",
                phase=phase,
                duration_ms=duration_ms,
                error=str(e),
                error_type=type(e).__name__,
                **ctx,
            )
            raise
        else:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            self.emit(f"{name}.complete", phase=phase, duration_ms=duration_ms, **ctx)


# ── Replay / inspection helpers ──────────────────────────────────────────────


def replay(path: str | Path) -> Iterator[dict[str, Any]]:
    """Iterate events from an audit file."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate partial writes


def summarize(path: str | Path) -> dict[str, Any]:
    """Aggregate an audit file into a summary dict."""
    summary: dict[str, Any] = {
        "path": str(path),
        "events": 0,
        "phases": {},
        "verifiers": {"pass": 0, "fail": 0, "fails": []},
        "manual_steps": [],
        "artifacts": [],
        "duration_ms_total": 0,
        "errors": [],
    }
    for ev in replay(path):
        summary["events"] += 1
        phase = ev.get("phase", "?")
        summary["phases"][phase] = summary["phases"].get(phase, 0) + 1
        evt = ev.get("event", "")
        if evt.startswith("verifier.") and "pass" in ev:
            if ev["pass"]:
                summary["verifiers"]["pass"] += 1
            else:
                summary["verifiers"]["fail"] += 1
                summary["verifiers"]["fails"].append(
                    {
                        "verifier": ev.get("verifier"),
                        "module": ev.get("module"),
                        "error": ev.get("error"),
                    }
                )
        if evt == "manual_step_required":
            summary["manual_steps"].append(ev.get("human_step"))
        if evt == "artifact.hashed":
            summary["artifacts"].append(
                {
                    "kind": ev.get("kind"),
                    "path": ev.get("path"),
                    "sha256": ev.get("sha256"),
                    "bytes": ev.get("bytes"),
                }
            )
        if evt.endswith(".error"):
            summary["errors"].append(
                {
                    "event": evt,
                    "error": ev.get("error"),
                    "error_type": ev.get("error_type"),
                }
            )
        if evt.endswith(".complete") and "duration_ms" in ev:
            summary["duration_ms_total"] += int(ev["duration_ms"])
    return summary


# ── stemforge-specific helpers ───────────────────────────────────────────────


def audit_path_for(run_kind: str, *, run_id: str | None = None) -> Path:
    """Return the audit-log path for a run of the given kind.

    Uses ``STEMFORGE_AUDIT_DIR`` (env var or default ``~/stemforge/audit``).
    The ``run_id`` defaults to ``<unix_ts>-<pid>`` so concurrent runs don't
    collide.
    """
    rid = run_id or f"{int(time.time())}-{os.getpid()}"
    return STEMFORGE_AUDIT_DIR / f"{run_kind}-{rid}.ndjson"


def with_audit(
    name: str, *, phase: str = "run", **default_fields: Any
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: wrap a CLI callback so the run produces an NDJSON audit.

    Emits ``<name>.start`` + ``<name>.complete`` (or ``.error``) at
    ``~/stemforge/audit/<name>-<run_id>.ndjson``. The wrapped function is
    unchanged; the decorator is purely additive.

    Usage::

        @cli.command()
        @click.option("--audio-file", ...)
        @with_audit("forge")
        def forge(...):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            path = audit_path_for(name)
            with Audit(path) as audit:
                with audit.step(name, phase=phase, **default_fields):
                    return func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "Audit",
    "STEMFORGE_AUDIT_DIR",
    "audit_path_for",
    "replay",
    "sha256_bytes",
    "sha256_path",
    "summarize",
    "with_audit",
]
