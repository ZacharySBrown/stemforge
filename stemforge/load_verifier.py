"""Headless Max patch load-verifier (Hardening Stream C.3).

Vendored from the external harness at
``~/raindog/harness/quickstarts/max-plugin/tools/forge_device/load_verifier.py``
(harness commit ``26f4d02``). The fork point is recorded in
``_HARNESS_VERSION``; bumping this constant + diffing against the
upstream file is how stemforge keeps the vendor in step.

This is a *runtime* verifier rather than a JSON-shape verifier: it
launches Max with a target patch, watches Max's per-session log, and
parses any error lines into structured categories. JSON-shape verifiers
(see ``stemforge.verifiers``) catch structural correctness; this one
catches bugs that only manifest when the Max engine actually loads the
patch — missing inlet/outlet operator boxes, wrong codebox JSON field,
gen~ DSL syntax errors, audio-graph cycles, etc.

Pitfall #24 (the reason this exists): JSON-shape verifiers are not load
verifiers. A patch can pass every structural check and still produce
~120 console errors when Max actually loads it.

Operational invariants
----------------------

* **Skip cleanly when prerequisites are missing.** No Max binary, set
  the ``MAX_LOAD_VERIFIER=0`` env var, or run on non-Darwin — all
  return a Result with ``passed=True`` and ``extra["skipped"]=True``.
  CI (Linux) treats those as informational.

* **Never kill Max processes the user owns.** We probe ``pgrep`` for
  pre-existing Max PIDs *before* launch; if any are found we refuse
  to run rather than risk SIGTERM-ing a Max IDE the user has open.
  Sessions we launch ourselves are tracked by PID delta and only
  those PIDs are signalled at teardown.

* **Bootstrap from a clean workspace.** Max treats the previous run's
  forced-quit as a crash and restores its workspace on next launch,
  which would mask the real patch. We delete ``Crash Recovery/
  maxworkspace-*.txt`` before each launch so Max opens with our patch
  and nothing else.

Usage::

    # Direct module CLI
    python -m stemforge.load_verifier v0/build/StemForge.amxd

    # Folded into the verifiers CLI
    python -m stemforge.verifiers verify-load v0/build/StemForge.amxd
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .verifiers import Result

# Vendor reference — harness commit this load-verifier was last synced
# from. Re-vendor with the same procedure documented in stemforge/audit.py.
_HARNESS_VERSION = "26f4d02"


# ── Platform / install-path probing ──────────────────────────────────────────


# Search order: Ableton-bundled Max (most common on dev machines that don't
# also have a standalone Max install) → standalone Max install → beta-channel
# Live. First binary that exists wins. The corresponding `.app` bundle path
# is reconstructed from the binary path when launching via `open -a`.
MAX_BIN_CANDIDATES: list[Path] = [
    Path(
        "/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/Max/"
        "Max.app/Contents/MacOS/Max"
    ),
    Path(
        "/Applications/Ableton Live 12 Beta.app/Contents/App-Resources/Max/"
        "Max.app/Contents/MacOS/Max"
    ),
    Path(
        "/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/Max/"
        "Max.app/Contents/MacOS/Max"
    ),
    Path("/Applications/Max.app/Contents/MacOS/Max"),
]

MAX_LOG = Path.home() / "Library/Application Support/Cycling '74/Max 9/Logs/Max.log"
CRASH_RECOVERY_DIR = Path.home() / "Library/Application Support/Cycling '74/Max 9/Crash Recovery"


def _find_max_bin() -> Path | None:
    """Return the first Max binary that exists on this machine, or None."""
    for cand in MAX_BIN_CANDIDATES:
        if cand.exists():
            return cand
    return None


def _extract_maxpat_from_amxd(amxd_path: Path) -> Path:
    """Convert ``amxd_path`` to a standalone ``.maxpat`` Max can load headless.

    Why: ``.amxd`` is the M4L container format. When Max opens an ``.amxd``
    directly, it bounces to Live (which then instantiates the device on a
    track). With Live not running, the verifier sees only Max's startup
    banner and never parses the device contents — defeating the entire
    purpose of pitfall #24's runtime check.

    Fix: unpack the ``.amxd`` into its inner patcher dict, serialize that
    as a ``.maxpat`` to a temp path, and hand the patcher to Max. Max
    loads ``.maxpat`` headless without needing Live; runtime errors in
    the patcher graph (gen~ syntax, missing inlets, audio cycles, etc.)
    surface in the log just like they would inside a Live host.

    Caveat: LOM-touching JS modules will still throw at load time because
    the ``LiveAPI`` host isn't there. Those errors come back categorised as
    ``js_no_function`` and friends — a known signal that this verifier
    catches patcher-graph errors, not runtime LOM errors. Filter them in
    the caller if needed; the extraction itself is correct.

    Returns the path to the extracted ``.maxpat``. Caller owns cleanup.
    """
    import json
    import sys
    import tempfile

    # Reuse the established v0/src/maxpat-builder import dance from
    # stemforge.verifiers — keeps the v0 path off sys.path long-term.
    repo_root = Path(__file__).resolve().parent.parent
    builder_dir = repo_root / "v0" / "src" / "maxpat-builder"
    if not (builder_dir / "amxd_pack.py").exists():
        raise FileNotFoundError(f"amxd_pack.py not found at {builder_dir}; can't extract .amxd")

    sys.path.insert(0, str(builder_dir))
    try:
        import amxd_pack  # type: ignore[import-not-found]

        unpacked = amxd_pack.unpack_amxd(amxd_path)
    finally:
        if str(builder_dir) in sys.path:
            sys.path.remove(str(builder_dir))

    # unpack_amxd's 'patcher' field is the JSON-decoded ptch chunk, which
    # already includes the standard {"patcher": {...}} envelope (it's the
    # raw .maxpat content, just embedded inside the .amxd container). So
    # we serialize it directly — wrapping again would produce the
    # double-envelope {"patcher": {"patcher": {...}}} that Max can't load.
    maxpat_json = json.dumps(unpacked["patcher"])

    fd, tmp_path = tempfile.mkstemp(prefix=f"sfverify_{amxd_path.stem}_", suffix=".maxpat")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(maxpat_json)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    return Path(tmp_path)


def _max_app_bundle(max_bin: Path) -> Path:
    """Given .../Max.app/Contents/MacOS/Max, return .../Max.app."""
    return max_bin.parents[2]


# ── Log parsing ──────────────────────────────────────────────────────────────


# Max log lines look like:
#   [2026-04-27 13:31:15.777269 error] [4689737] patchcord inlet out of range: ...
# The level token lives inside the timestamp bracket, not as a separate field.
ERROR_TAG = re.compile(r"^\[[^\]]* error\] ")
LINE_AFTER_TAG = re.compile(r"^\[[^\]]* error\] \[\d+\]\s*(.*)")

CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("inlet_outlet_missing", re.compile(r"\b(inlet~|outlet~|inlet|outlet):\s*No such object")),
    ("patchcord_inlet_oor", re.compile(r"patchcord inlet out of range")),
    ("patchcord_outlet_oor", re.compile(r"patchcord outlet out of range")),
    ("expr_syntax", re.compile(r"\bsyntax error\b")),
    ("missing_file", re.compile(r"can't find file")),
    ("js_no_function", re.compile(r"js:\s*no function")),
    ("missing_object", re.compile(r":\s*No such object")),
]


def _categorize(line: str) -> str:
    for name, pat in CATEGORIES:
        if pat.search(line):
            return name
    return "other"


def _extract_message(line: str) -> str:
    m = LINE_AFTER_TAG.search(line)
    return m.group(1) if m else line


# ── Process management ───────────────────────────────────────────────────────


def _list_max_pids() -> set[int]:
    """Return PIDs of any currently running Max processes."""
    r = subprocess.run(
        ["pgrep", "-f", "Max.app/Contents/MacOS/Max"],
        capture_output=True,
        text=True,
        check=False,
    )
    out: set[int] = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            out.add(int(line))
    return out


def _kill_pids(pids: set[int]) -> None:
    """SIGTERM only the specified PIDs — never blanket-kill Max."""
    for pid in pids:
        try:
            subprocess.run(["kill", str(pid)], capture_output=True, check=False)
        except OSError:
            pass


def _clear_crash_recovery() -> None:
    """Delete Max's workspace-recovery file so the next launch starts clean."""
    if not CRASH_RECOVERY_DIR.exists():
        return
    for f in CRASH_RECOVERY_DIR.glob("maxworkspace-*.txt"):
        try:
            f.unlink()
        except OSError:
            pass


def _launch_max(app_bundle: Path, patch: Path) -> None:
    """Launch Max with the patch; returns immediately (Max runs in background)."""
    subprocess.Popen(
        ["open", "-a", str(app_bundle), str(patch)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_idle(*, idle_seconds: float, timeout: float, min_size: int = 200) -> int:
    """Watch Max.log size; return when no growth for ``idle_seconds`` or ``timeout``."""
    deadline = time.time() + timeout
    last_size = -1
    last_change = time.time()
    while time.time() < deadline:
        time.sleep(0.5)
        cur = MAX_LOG.stat().st_size if MAX_LOG.exists() else 0
        if cur != last_size:
            last_size = cur
            last_change = time.time()
        elif cur >= min_size and (time.time() - last_change) >= idle_seconds:
            return cur
    return last_size


# ── Skip-decision helpers ────────────────────────────────────────────────────


def _skip_reason() -> str | None:
    """Return a string describing why the load-verifier should skip, or None."""
    if os.environ.get("MAX_LOAD_VERIFIER") == "0":
        return "MAX_LOAD_VERIFIER=0 (opted out via env)"
    if platform.system() != "Darwin":
        return f"non-Darwin platform ({platform.system()})"
    if _find_max_bin() is None:
        return f"no Max binary found in any of {len(MAX_BIN_CANDIDATES)} candidate paths"
    if not MAX_LOG.exists():
        return f"Max log not found at {MAX_LOG} — launch Max once manually first"
    return None


# ── Public verifier entry-point ──────────────────────────────────────────────


def verify_max_load(
    patch_path: str | Path,
    *,
    idle_seconds: float = 3.0,
    timeout: float = 25.0,
) -> Result:
    """Pitfall #24: launch Max with ``patch_path`` and inspect its log for errors.

    Returns a ``Result``:

    * ``passed=True, extra["skipped"]=True`` — prerequisites missing or
      opted out. CI / non-Mac environments hit this path.
    * ``passed=True`` — Max loaded the patch with zero error lines in
      the log slice produced during this session.
    * ``passed=False`` — Max loaded the patch but emitted ≥1 error line.
      The Result's ``extra`` carries ``error_count``, ``categories``, and
      per-category sample messages so the caller can fix targeted bugs.

    Heavyweight (~10-15 s wall clock) and requires a Max install. The
    JSON-shape verifiers in ``stemforge.verifiers`` are CI-friendly;
    this one is dev-Mac tier.
    """
    patch = Path(patch_path)

    # ── Gate 1: should we run at all? ────────────────────────────────────
    skip = _skip_reason()
    if skip:
        return Result(
            "max_load_clean",
            True,
            "#24",
            detail=f"skipped: {skip}",
            fix_hint="",
            extra={"skipped": True, "skip_reason": skip, "patch": str(patch)},
        )

    if not patch.exists():
        return Result(
            "max_load_clean",
            False,
            "#24",
            detail=f"patch not found: {patch}",
            fix_hint="check the path passed to verify_max_load()",
            extra={"patch": str(patch)},
        )

    # ── Gate 2: don't trample the user's Max session ────────────────────
    pre_pids = _list_max_pids()
    if pre_pids:
        return Result(
            "max_load_clean",
            True,
            "#24",
            detail=(
                f"skipped: Max already running (PIDs: {sorted(pre_pids)}). "
                "Verifier refuses to touch sessions it didn't start."
            ),
            fix_hint="close Max manually before re-running the load verifier",
            extra={
                "skipped": True,
                "skip_reason": "max_already_running",
                "pre_pids": sorted(pre_pids),
                "patch": str(patch),
            },
        )

    max_bin = _find_max_bin()
    assert max_bin is not None  # _skip_reason() would have caught this
    app_bundle = _max_app_bundle(max_bin)

    # ── Gate 3: actually launch and watch ───────────────────────────────
    # If the patch is a .amxd, extract its inner patcher to a temp .maxpat
    # so Max can load it headlessly (without bouncing to Live). See
    # `_extract_maxpat_from_amxd` for the rationale.
    extracted_maxpat: Path | None = None
    launch_path = patch
    if patch.suffix.lower() == ".amxd":
        try:
            extracted_maxpat = _extract_maxpat_from_amxd(patch)
            launch_path = extracted_maxpat
        except Exception as e:
            return Result(
                "max_load_clean",
                False,
                "#24",
                detail=f"failed to extract .maxpat from .amxd: {e}",
                fix_hint=(
                    "verify v0/src/maxpat-builder/amxd_pack.py is present and "
                    "the .amxd is well-formed (run `python -m stemforge.verifiers "
                    "verify-amxd` first)"
                ),
                extra={"patch": str(patch), "extraction_error": str(e)},
            )

    _clear_crash_recovery()
    _launch_max(app_bundle, launch_path)

    # Wait briefly for the new Max to register so we can identify its PID(s).
    time.sleep(1.5)
    our_pids = _list_max_pids() - pre_pids

    try:
        final_size = _wait_for_idle(idle_seconds=idle_seconds, timeout=timeout)
        with open(MAX_LOG, "rb") as fh:
            new_bytes = fh.read(final_size)
    finally:
        # Kill only PIDs we started. Re-probe in case the launcher forked.
        _kill_pids(our_pids or (_list_max_pids() - pre_pids))
        # Clean up extracted .maxpat (if any) — temp dir should auto-clean
        # but be explicit so dev machines don't accumulate sfverify_* files.
        if extracted_maxpat is not None:
            extracted_maxpat.unlink(missing_ok=True)

    text = new_bytes.decode("utf-8", errors="replace")
    error_lines = [ln for ln in text.splitlines() if ERROR_TAG.search(ln)]

    by_cat: dict[str, list[str]] = {}
    for ln in error_lines:
        by_cat.setdefault(_categorize(ln), []).append(_extract_message(ln))

    extra: dict[str, Any] = {
        "patch": str(patch),
        "error_count": len(error_lines),
        "log_bytes_captured": final_size,
        "categories": {k: len(v) for k, v in by_cat.items()},
        "samples": {k: list(dict.fromkeys(v))[:3] for k, v in by_cat.items()},
        "max_bin": str(max_bin),
    }

    if not error_lines:
        return Result(
            "max_load_clean",
            True,
            "#24",
            detail=f"clean load ({final_size} log bytes, 0 errors)",
            extra=extra,
        )

    top_cats = sorted(extra["categories"].items(), key=lambda x: -x[1])[:3]
    cat_summary = ", ".join(f"{n}×{c}" for c, n in top_cats)
    return Result(
        "max_load_clean",
        False,
        "#24",
        detail=f"{len(error_lines)} error lines: {cat_summary}",
        fix_hint=(
            "inspect Result.extra['samples'] for one example per category; "
            "JSON-shape verifiers don't catch these — fix in the patch generator"
        ),
        extra=extra,
    )


# ── Stand-alone CLI ──────────────────────────────────────────────────────────


def _cli(argv: list[str] | None = None) -> int:
    """Direct CLI use: ``python -m stemforge.load_verifier <patch>``.

    Exit codes:
        0 — clean load
        1 — errors found
        2 — skipped / infra (no Max, opted out, etc.)
    """
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Headless Max patch load-verifier.")
    ap.add_argument("patch", type=Path, help="Path to .maxpat or .amxd to load")
    ap.add_argument("--idle-seconds", type=float, default=3.0)
    ap.add_argument("--timeout", type=float, default=25.0)
    ap.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    args = ap.parse_args(argv)

    r = verify_max_load(args.patch, idle_seconds=args.idle_seconds, timeout=args.timeout)

    if args.json:
        print(
            json.dumps(
                {
                    "verifier": r.verifier,
                    "passed": r.passed,
                    "pitfall": r.pitfall,
                    "detail": r.detail,
                    "fix_hint": r.fix_hint,
                    "extra": r.extra,
                },
                indent=2,
            )
        )
    else:
        if r.extra.get("skipped"):
            print(f"== Max load-verifier: SKIPPED — {r.detail}")
            return 2
        verdict = "PASS" if r.passed else "FAIL"
        print(f"== Max load-verifier: {r.extra.get('patch')}")
        print(
            f"   {verdict} — {r.extra.get('error_count', 0)} error lines "
            f"({r.extra.get('log_bytes_captured', 0)} log bytes)"
        )
        for cat, count in sorted((r.extra.get("categories") or {}).items(), key=lambda x: -x[1]):
            print(f"   {count:3d} × {cat}")
            for sample in (r.extra.get("samples") or {}).get(cat, [])[:1]:
                print(f"        e.g. {sample}")

    if r.extra.get("skipped"):
        return 2
    return 0 if r.passed else 1


if __name__ == "__main__":
    sys.exit(_cli())


__all__ = [
    "CATEGORIES",
    "MAX_BIN_CANDIDATES",
    "MAX_LOG",
    "verify_max_load",
]
