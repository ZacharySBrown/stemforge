"""
NDJSON progress + artifact + state-flag writers for Track A0.

Follows the shared-memory protocol in `v0/SHARED.md`:

  v0/state/A0/progress.ndjson   append-only, one JSON object per line
  v0/state/A0/artifacts.json    final artifact summary (overwritten on success)
  v0/state/A0/done.flag         presence = success (body = JSON summary)
  v0/state/A0/blocker.md        presence = blocked (body = human-readable)

Only A0 writes these paths. Other tracks are read-only over them.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def emit(phase: str, pct: int | float, message: str, **fields: Any) -> None:
    """Append one line to progress.ndjson and echo to stderr."""
    config.A0_STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": _utcnow_iso(),
        "phase": phase,
        "pct": float(pct),
        "message": message,
    }
    rec.update(fields)
    line = json.dumps(rec, ensure_ascii=False)
    with open(config.STATE_PROGRESS_NDJSON, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    # Mirror to stderr so the orchestrator / operator can tail live.
    sys.stderr.write(f"[A0 {phase} {pct:>5.1f}%] {message}\n")
    sys.stderr.flush()


def write_artifacts(status: str, artifacts: list[dict[str, Any]],
                    duration_sec: float, **extras: Any) -> None:
    """Write the artifacts.json summary (SHARED.md format)."""
    config.A0_STATE_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "track": "A0",
        "status": status,
        "artifacts": artifacts,
        "duration_sec": round(duration_sec, 2),
    }
    doc.update(extras)
    with open(config.STATE_ARTIFACTS_JSON, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def write_done_flag(branch: str, artifacts: list[str], notes: str = "") -> None:
    """Write done.flag per the A0 track brief subagent handoff spec."""
    config.A0_STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "completed_at": _utcnow_iso(),
        "branch": branch,
        "artifacts": artifacts,
        "notes": notes,
    }
    with open(config.STATE_DONE_FLAG, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def write_blocker(title: str, body_md: str) -> None:
    """Write blocker.md. Caller should NOT also write done.flag."""
    config.A0_STATE_DIR.mkdir(parents=True, exist_ok=True)
    full = f"# A0 blocker — {title}\n\n_{_utcnow_iso()}_\n\n{body_md.rstrip()}\n"
    with open(config.STATE_BLOCKER_MD, "w", encoding="utf-8") as fh:
        fh.write(full)


class Timer:
    """Context manager that records per-stage wall-clock latency into perf.json."""

    def __init__(self, stage: str, perf_path: Path = config.STATE_PERF_JSON,
                 **extras: Any) -> None:
        self.stage = stage
        self.perf_path = perf_path
        self.extras = extras
        self.t0 = 0.0

    def __enter__(self) -> "Timer":
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        dt = time.perf_counter() - self.t0
        self._append({"stage": self.stage, "seconds": round(dt, 4),
                      "failed": exc is not None, **self.extras})

    def _append(self, rec: dict[str, Any]) -> None:
        self.perf_path.parent.mkdir(parents=True, exist_ok=True)
        doc: dict[str, Any]
        if self.perf_path.exists():
            try:
                doc = json.loads(self.perf_path.read_text())
                if "stages" not in doc:
                    doc["stages"] = []
            except Exception:
                doc = {"stages": []}
        else:
            doc = {"stages": []}
        rec["ts"] = _utcnow_iso()
        doc["stages"].append(rec)
        with open(self.perf_path, "w") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
