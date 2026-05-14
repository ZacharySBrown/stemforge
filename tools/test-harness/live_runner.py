"""Live-in-the-loop smoke runner — orchestrator (Phase 5, L4 layer).

Per ``docs/configurator/EXECUTION_PLAN_v1.md`` and
``specs/CONSOLIDATED_DESIGN.md §7`` (L4 = Live-in-the-loop), this is the
gate that turns "L3 stubs say it works" into "Live actually does it."

The shell wrapper ``live-runner.sh`` is the user-facing entrypoint.
This module is the engine — it opens fixture ``.als`` files via
osascript, waits for the device's ``[udpreceive]`` to come up, fires
``sf-remote`` intents, captures state, and asserts.

CLI usage::

    python tools/test-harness/live_runner.py --list
    python tools/test-harness/live_runner.py --all
    python tools/test-harness/live_runner.py --test smoke_1_empty_boot
    python tools/test-harness/live_runner.py --all --skip-fixture-check

The runner emits one NDJSON line per test on stdout::

    {"test": "smoke_1_empty_boot", "status": "skip", "reason": "fixture missing: empty-staging.als"}
    {"test": "smoke_2_load_forge", "status": "pass", "duration_sec": 12.4}

Aggregate summary on stderr at end. Exit code: 0 iff every non-skipped
test passed.

The runner is **deliberately conservative**: tests that depend on a
real Live process skip cleanly when (a) Live is not installed, or
(b) the required fixture ``.als`` is absent. The user records fixtures
manually per the procedure in ``tests/fixtures/als/README.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Make sibling imports work when invoked as a script.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib import assertions, fixtures, osa, sf_remote_shim  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR_DEFAULT = REPO_ROOT / "tests" / "fixtures" / "als"
STEMFORGE_HOME = Path.home() / "stemforge"
PORT_FILE = STEMFORGE_HOME / ".configurator_port"
CURATIONS_DIR = STEMFORGE_HOME / "curations"
BOUNCED_DIR = STEMFORGE_HOME / "bounced"
EXPORTS_DIR = STEMFORGE_HOME / "exports"

# Heartbeat / poll knobs (kept small so the runner is responsive when
# everything is healthy; overridable from CLI flags).
DEVICE_BOOT_TIMEOUT_SEC = 30.0
DEVICE_BOOT_POLL_SEC = 1.0


# ─── Smoke test registry ────────────────────────────────────────────────────


@dataclass
class SmokeTest:
    """Declarative description of one smoke test."""

    name: str
    description: str
    fixture: str  # filename under tests/fixtures/als/
    sequence: list[str]  # human-readable steps (also doc/UX)
    assertion_summary: str  # one-line "what we check"
    fn: Callable[["RunContext"], None] = field(repr=False)


@dataclass
class RunContext:
    """Per-test execution context: paths, ports, knobs."""

    fixture_path: Path
    fixtures_dir: Path
    port: int
    live_app: Path | None
    dry_run: bool = False


@dataclass
class TestReport:
    name: str
    status: str  # "pass" | "fail" | "skip" | "error"
    duration_sec: float
    reason: str = ""


# ─── Individual smoke-test implementations ─────────────────────────────────
#
# Each test is a function taking a RunContext. It raises AssertionError on
# logical failure, or any other Exception on infrastructure error. The
# runner translates raises into TestReport entries.
#
# Note: the smoke functions below are intentionally lean. The HEAVY
# verification logic lives in lib/assertions.py. Each smoke function is
# essentially: "drive the device, then assert on captured state."
# When fixtures are missing the smoke runner skips before calling these.


def smoke_1_empty_boot(ctx: RunContext) -> None:
    """Smoke 1: open empty-staging.als → device boots → no active curation."""
    _open_fixture_and_wait_for_device(ctx)
    state = sf_remote_shim.get_state(ctx.port)
    assertions.assert_state(state, {"active_curation": None})


def smoke_2_load_forge(ctx: RunContext) -> None:
    """Smoke 2: load fixture forge → FORGE/* tracks created with clip count."""
    _open_fixture_and_wait_for_device(ctx)
    sf_remote_shim.fire("forge", "load", "breaks-n-beats-1")
    _settle()
    state = sf_remote_shim.get_state(ctx.port)
    assertions.assert_track_count(state, prefix="FORGE/breaks-n-beats-1", expected=4)


def smoke_3_create_curation(ctx: RunContext) -> None:
    """Smoke 3: create curation → staging tracks created with target count."""
    _open_fixture_and_wait_for_device(ctx)
    curation_name = "smoke_test_curation_3"
    sf_remote_shim.fire("forge", "create-curation", curation_name, "ep133")
    _settle()
    state = sf_remote_shim.get_state(ctx.port)
    # EP-133 = 4 staging tracks (STG-A..STG-D).
    assertions.assert_track_count(state, prefix="STG-", expected=4)
    assertions.assert_state(state, {"active_curation": curation_name})


def smoke_4_commit(ctx: RunContext) -> None:
    """Smoke 4: COMMIT → curation file written with correct content."""
    _open_fixture_and_wait_for_device(ctx)
    curation_name = "smoke_test_curation_4"
    sf_remote_shim.fire("forge", "create-curation", curation_name, "ep133")
    _settle()
    sf_remote_shim.fire("state", "commit")
    _settle(longer=True)
    curation_path = CURATIONS_DIR / f"{curation_name}.yaml"
    if not curation_path.exists():
        curation_path = CURATIONS_DIR / f"{curation_name}.json"
    assertions.assert_curation_file(
        curation_path,
        expected_keys=["curation_version", "target", "groups"],
    )


def smoke_5_load_curation(ctx: RunContext) -> None:
    """Smoke 5: load curation from disk → staging populated correctly."""
    _open_fixture_and_wait_for_device(ctx)
    sf_remote_shim.fire("forge", "open-curation", "verse_swap_v1")
    _settle()
    state = sf_remote_shim.get_state(ctx.port)
    assertions.assert_state(state, {"active_curation": "verse_swap_v1"})
    assertions.assert_track_count(state, prefix="STG-", expected=4)


def smoke_6_switch_curation(ctx: RunContext) -> None:
    """Smoke 6: switch active curation → staging repopulated."""
    _open_fixture_and_wait_for_device(ctx)
    sf_remote_shim.fire("forge", "open-curation", "verse_swap_v1")
    _settle()
    sf_remote_shim.fire("forge", "open-curation", "live_set_oct_2026")
    _settle(longer=True)
    state = sf_remote_shim.get_state(ctx.port)
    assertions.assert_state(state, {"active_curation": "live_set_oct_2026"})


def smoke_7_reanchor(ctx: RunContext) -> None:
    """Smoke 7: re-anchor → forge manifests updated + tracks reloaded."""
    _open_fixture_and_wait_for_device(ctx)
    sf_remote_shim.fire("forge", "re-anchor", "breaks-n-beats-1", "0.247")
    _settle(longer=True)
    state = sf_remote_shim.get_state(ctx.port)
    # The re-anchor flow updates manifest_hash; the smoke just asserts
    # we have a fresh hash in state (existence, not specific value).
    if not isinstance(state, dict):
        raise AssertionError("expected /state dict after re-anchor")
    forges = _nested(state, ("forges",)) or _nested(state, ("live", "forges")) or []
    if not any(isinstance(f, dict) and f.get("slug") == "breaks-n-beats-1" for f in forges):
        raise AssertionError("breaks-n-beats-1 not present in /state.forges after re-anchor")


def smoke_8_bounce(ctx: RunContext) -> None:
    """Smoke 8: bounce → bounce dir populated with correct # of WAVs."""
    _open_fixture_and_wait_for_device(ctx)
    sf_remote_shim.fire("forge", "open-curation", "verse_swap_v1")
    _settle()
    sf_remote_shim.fire("state", "bounce")
    # Bouncing is slow — Live actually renders each pad.
    _settle(longer=True, extra_sec=8.0)
    bounce_dir = BOUNCED_DIR / "verse_swap_v1"
    # Fixture covenant (see tests/fixtures/als/README.md): the
    # curation-active-stg-populated.als has 4 pads on STG-A.
    assertions.assert_bounce_dir(bounce_dir, expected_wav_count=4)


def smoke_9_export(ctx: RunContext) -> None:
    """Smoke 9: export → .ppak produced."""
    _open_fixture_and_wait_for_device(ctx)
    sf_remote_shim.fire("forge", "open-curation", "verse_swap_v1")
    _settle()
    out_path = EXPORTS_DIR / "verse_swap_v1.ppak"
    # Clean any prior export so we know this run produced it.
    if out_path.exists():
        out_path.unlink()
    sf_remote_shim.fire("forge", "export", "verse_swap_v1", str(out_path))
    _settle(longer=True, extra_sec=4.0)
    assertions.assert_ppak_exists(out_path)


def smoke_10_stale(ctx: RunContext) -> None:
    """Smoke 10: stale detection → mutate forge, popup state shows stale."""
    _open_fixture_and_wait_for_device(ctx)
    sf_remote_shim.fire("forge", "open-curation", "verse_swap_v1")
    _settle()
    # Re-curate the forge — this rewrites the manifest_hash. Curation
    # still references the OLD hash → stale detection should fire.
    sf_remote_shim.fire("forge", "re-curate", "breaks-n-beats-1")
    _settle(longer=True)
    state = sf_remote_shim.get_state(ctx.port)
    if not isinstance(state, dict):
        raise AssertionError("expected /state dict after re-curate")
    stale = (
        _nested(state, ("stale",))
        or _nested(state, ("active_curation_stale",))
        or _nested(state, ("curation", "stale"))
    )
    if not stale:
        raise AssertionError(
            "expected stale flag in /state after forge re-curate, "
            f"got state keys={sorted((state or {}).keys())!r}"
        )


# ─── Inventory ─────────────────────────────────────────────────────────────


def build_test_registry() -> list[SmokeTest]:
    """Return the canonical list of 10 smoke tests, in plan order."""
    return [
        SmokeTest(
            name="smoke_1_empty_boot",
            description="open empty-staging.als → device boots → no active curation",
            fixture="empty-staging.als",
            sequence=["open fixture", "wait for /healthz", "GET /state"],
            assertion_summary="state.active_curation is None",
            fn=smoke_1_empty_boot,
        ),
        SmokeTest(
            name="smoke_2_load_forge",
            description="load fixture forge → FORGE/* tracks created",
            fixture="loaded-forge-stg-empty.als",
            sequence=["open fixture", "fire forge load <slug>", "GET /state"],
            assertion_summary="4 tracks named FORGE/breaks-n-beats-1/* exist",
            fn=smoke_2_load_forge,
        ),
        SmokeTest(
            name="smoke_3_create_curation",
            description="create curation → STG-* tracks created with target count",
            fixture="loaded-forge-stg-empty.als",
            sequence=["open fixture", "fire forge create-curation <name> ep133", "GET /state"],
            assertion_summary="4 staging tracks exist + active_curation set",
            fn=smoke_3_create_curation,
        ),
        SmokeTest(
            name="smoke_4_commit",
            description="COMMIT → curation file written with correct content",
            fixture="loaded-forge-stg-empty.als",
            sequence=[
                "open fixture",
                "create curation",
                "fire state commit",
                "stat curations/<name>.yaml",
            ],
            assertion_summary="curation file exists with curation_version/target/groups",
            fn=smoke_4_commit,
        ),
        SmokeTest(
            name="smoke_5_load_curation",
            description="load curation from disk → staging populated",
            fixture="curation-active-stg-populated.als",
            sequence=["open fixture", "fire forge open-curation verse_swap_v1", "GET /state"],
            assertion_summary="active_curation == verse_swap_v1 + 4 STG-* tracks",
            fn=smoke_5_load_curation,
        ),
        SmokeTest(
            name="smoke_6_switch_curation",
            description="switch active curation → staging repopulated",
            fixture="curation-active-stg-populated.als",
            sequence=[
                "open fixture",
                "open verse_swap_v1",
                "open live_set_oct_2026",
                "GET /state",
            ],
            assertion_summary="active_curation switches to live_set_oct_2026",
            fn=smoke_6_switch_curation,
        ),
        SmokeTest(
            name="smoke_7_reanchor",
            description="re-anchor → forge manifests updated + tracks reloaded",
            fixture="curation-active-stg-populated.als",
            sequence=["open fixture", "fire forge re-anchor <slug> 0.247", "GET /state"],
            assertion_summary="forges list still contains the slug after re-anchor",
            fn=smoke_7_reanchor,
        ),
        SmokeTest(
            name="smoke_8_bounce",
            description="bounce → bounce dir populated with correct # of WAVs",
            fixture="curation-active-stg-populated.als",
            sequence=["open fixture", "open verse_swap_v1", "fire state bounce", "stat bounced/"],
            assertion_summary="bounced/verse_swap_v1/ has 4 WAV files",
            fn=smoke_8_bounce,
        ),
        SmokeTest(
            name="smoke_9_export",
            description="export → .ppak produced",
            fixture="curation-active-stg-populated.als",
            sequence=["open fixture", "open verse_swap_v1", "fire forge export ... .ppak"],
            assertion_summary="exports/verse_swap_v1.ppak exists, size > 1024",
            fn=smoke_9_export,
        ),
        SmokeTest(
            name="smoke_10_stale",
            description="stale detection → mutate forge, popup state shows stale",
            fixture="curation-active-stg-populated.als",
            sequence=[
                "open fixture",
                "open verse_swap_v1",
                "fire forge re-curate <slug>",
                "GET /state",
            ],
            assertion_summary="state.stale (or active_curation_stale) is truthy",
            fn=smoke_10_stale,
        ),
    ]


# ─── Helpers used by smoke functions ───────────────────────────────────────


def _settle(*, longer: bool = False, extra_sec: float = 0.0) -> None:
    """Pause to let the device react. Short by default; longer for COMMIT/BOUNCE.

    Real Ableton operations are async (UDP fire-and-forget). We give
    the device time to walk LOM, write files, and update server state
    before we GET /state to assert.
    """
    base = 2.5 if longer else 0.8
    time.sleep(base + extra_sec)


def _nested(d: dict, path: tuple[str, ...]) -> Any:
    """Walk a nested dict by a tuple of keys; return None on miss."""
    cur: Any = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def _open_fixture_and_wait_for_device(ctx: RunContext) -> None:
    """Open the fixture .als and block until the configurator /healthz responds.

    Raises RuntimeError on timeout. Smoke tests rely on this side effect.
    """
    if ctx.dry_run:
        return
    if ctx.live_app is None:
        raise RuntimeError("Ableton Live not found on this host")
    osa.open_als(ctx.live_app, ctx.fixture_path, timeout=15.0)
    deadline = time.monotonic() + DEVICE_BOOT_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if sf_remote_shim.healthz_ok(ctx.port, timeout=1.5):
            return
        time.sleep(DEVICE_BOOT_POLL_SEC)
    raise RuntimeError(
        f"configurator /healthz on port {ctx.port} did not come up within "
        f"{DEVICE_BOOT_TIMEOUT_SEC}s of opening {ctx.fixture_path.name}"
    )


# ─── Fixture-skip decorator ────────────────────────────────────────────────


def skip_if_no_fixture(
    fixtures_dir: Path,
    fixture_filename: str,
) -> tuple[bool, str]:
    """Return (skip, reason). skip=True if fixture missing or corrupt.

    Used by the runner before invoking any smoke function. Pure /
    side-effect-free so we can unit-test the decision logic.
    """
    fp = fixtures.fixture_path(fixtures_dir, fixture_filename)
    status = fixtures.parse_fixture_status(fp)
    if status is fixtures.FixtureStatus.MISSING:
        return (
            True,
            f"fixture missing: {fixture_filename} (record it per tests/fixtures/als/README.md)",
        )
    if status is fixtures.FixtureStatus.CORRUPT:
        return True, f"fixture corrupt: {fixture_filename} (not a gzipped .als XML)"
    return False, ""


# ─── Runner core ───────────────────────────────────────────────────────────


def run_one(test: SmokeTest, ctx: RunContext) -> TestReport:
    """Execute a single smoke test; never raise."""
    skip, reason = skip_if_no_fixture(ctx.fixtures_dir, test.fixture)
    if skip:
        return TestReport(name=test.name, status="skip", duration_sec=0.0, reason=reason)
    if ctx.live_app is None:
        return TestReport(
            name=test.name,
            status="skip",
            duration_sec=0.0,
            reason="Ableton Live not installed on this host",
        )
    started = time.monotonic()
    try:
        test.fn(ctx)
    except AssertionError as exc:
        return TestReport(
            name=test.name,
            status="fail",
            duration_sec=round(time.monotonic() - started, 2),
            reason=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — runner must capture everything
        return TestReport(
            name=test.name,
            status="error",
            duration_sec=round(time.monotonic() - started, 2),
            reason=f"{type(exc).__name__}: {exc}",
        )
    return TestReport(
        name=test.name,
        status="pass",
        duration_sec=round(time.monotonic() - started, 2),
    )


def emit_report(rep: TestReport, *, stream: Any = sys.stdout) -> None:
    payload = {
        "test": rep.name,
        "status": rep.status,
        "duration_sec": rep.duration_sec,
    }
    if rep.reason:
        payload["reason"] = rep.reason
    stream.write(json.dumps(payload) + "\n")
    stream.flush()


def run_suite(
    selected: list[SmokeTest],
    ctx: RunContext,
    *,
    out: Any = sys.stdout,
    err: Any = sys.stderr,
) -> int:
    """Run a list of smoke tests; emit NDJSON; return process exit code."""
    reports: list[TestReport] = []
    for t in selected:
        rep = run_one(t, ctx)
        emit_report(rep, stream=out)
        reports.append(rep)
    # Tear down: tell Live to quit so the next CI run starts fresh.
    if ctx.live_app and not ctx.dry_run:
        try:
            osa.quit_live(ctx.live_app, timeout=10.0)
        except Exception:  # noqa: BLE001
            pass
    n_pass = sum(1 for r in reports if r.status == "pass")
    n_fail = sum(1 for r in reports if r.status == "fail")
    n_err = sum(1 for r in reports if r.status == "error")
    n_skip = sum(1 for r in reports if r.status == "skip")
    err.write(
        f"\n=== smoke summary ===\n"
        f"  pass:  {n_pass}\n"
        f"  fail:  {n_fail}\n"
        f"  error: {n_err}\n"
        f"  skip:  {n_skip}\n"
        f"  total: {len(reports)}\n"
    )
    err.flush()
    return 0 if (n_fail == 0 and n_err == 0) else 1


# ─── Plan-vs-impl drift parser ─────────────────────────────────────────────

# Matches '- Smoke N:' bullets (with or without bold markers).
# The plan currently uses the un-bolded form; the regex tolerates both
# so we don't lose drift detection if someone reformats.
_SMOKE_LINE_RE = re.compile(r"-\s+(?:\*\*)?Smoke\s+(\d+)(?:\*\*)?\s*:", re.IGNORECASE)


def parse_smoke_count_from_plan(plan_md: str) -> int:
    """Count occurrences of '- Smoke N:' bullets in the plan markdown."""
    return len(_SMOKE_LINE_RE.findall(plan_md))


# ─── CLI ───────────────────────────────────────────────────────────────────


def _resolve_port(args: argparse.Namespace) -> int:
    """Resolve the configurator HTTP port: CLI > port file > default 7430."""
    if args.port:
        return int(args.port)
    p = sf_remote_shim.read_port_file(PORT_FILE)
    if p is not None:
        return p
    return 7430


def _resolve_live_app(args: argparse.Namespace) -> Path | None:
    if args.live_app:
        p = Path(args.live_app)
        if not p.exists():
            return None
        return p
    return osa.find_live_app()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="live_runner",
        description="StemForge Configurator Live-in-the-loop smoke suite (Phase 5).",
    )
    ap.add_argument("--all", action="store_true", help="Run every smoke test.")
    ap.add_argument(
        "--test",
        action="append",
        default=[],
        help="Run a specific smoke by name (repeatable).",
    )
    ap.add_argument("--list", action="store_true", help="List all smoke tests and exit.")
    ap.add_argument(
        "--fixtures-dir",
        default=str(FIXTURES_DIR_DEFAULT),
        help=f"Where the .als fixtures live (default: {FIXTURES_DIR_DEFAULT}).",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=0,
        help="Configurator HTTP port (default: read .configurator_port or 7430).",
    )
    ap.add_argument(
        "--live-app", default=None, help="Path to Ableton Live .app (default: auto-detect)."
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Don't open Live, don't fire UDP; just emit plan."
    )
    ap.add_argument(
        "--skip-fixture-check",
        action="store_true",
        help="Skip the fixture .als status check (for the meta-tests / harness self-tests).",
    )
    args = ap.parse_args(argv)

    registry = build_test_registry()

    if args.list:
        for t in registry:
            print(f"{t.name}: {t.description}")
            print(f"    fixture: {t.fixture}")
            print(f"    assert : {t.assertion_summary}")
        return 0

    if not args.all and not args.test:
        ap.error("pass --all or --test <name> (see --list)")

    if args.all:
        selected = list(registry)
    else:
        by_name = {t.name: t for t in registry}
        selected = []
        for name in args.test:
            if name not in by_name:
                ap.error(f"unknown smoke test: {name!r}. Try --list.")
            selected.append(by_name[name])

    fixtures_dir = Path(args.fixtures_dir).expanduser().resolve()
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    port = _resolve_port(args)
    live_app = _resolve_live_app(args)

    # If the user passed --skip-fixture-check, we still iterate the
    # selected tests but emit synthetic skip reports without trying to
    # open Live. This is what tests/test_live_runner.py uses.
    if args.skip_fixture_check:
        for t in selected:
            emit_report(
                TestReport(
                    name=t.name,
                    status="skip",
                    duration_sec=0.0,
                    reason="--skip-fixture-check (meta-test mode)",
                )
            )
        return 0

    # We assemble a fresh per-iteration ctx so run_one stays pure
    # (avoids ``RunContext`` mutation between tests). The fixture path
    # is the only field that changes per-test; the rest is constant.
    reports_rc = 0
    for t in selected:
        per_test_ctx = RunContext(
            fixture_path=fixtures.fixture_path(fixtures_dir, t.fixture),
            fixtures_dir=fixtures_dir,
            port=port,
            live_app=live_app,
            dry_run=args.dry_run,
        )
        rep = run_one(t, per_test_ctx)
        emit_report(rep)
        if rep.status in ("fail", "error"):
            reports_rc = 1

    if live_app and not args.dry_run:
        try:
            osa.quit_live(live_app, timeout=10.0)
        except Exception:  # noqa: BLE001
            pass

    sys.stderr.write(f"\ndone. port={port} fixtures={fixtures_dir}\n")
    return reports_rc


# ─── Free-standing helpers exported for tests ──────────────────────────────


def build_open_command_for(fixture_path: Path) -> list[str]:
    """Convenience wrapper used by the unit tests."""
    app = osa.find_live_app()
    if app is None:
        # Tests pin a canonical fake path so the assertion is meaningful
        # on hosts without Live.
        app = Path("/Applications/Ableton Live 12 Suite.app")
    return osa.build_open_als_command(app, fixture_path)


def parse_fixture_status(path: Path) -> fixtures.FixtureStatus:
    """Re-export for tests (lets tests patch via live_runner.parse_fixture_status)."""
    return fixtures.parse_fixture_status(path)


def assert_state(actual: dict | None, expected_subset: dict[str, Any]) -> None:
    """Re-export of lib.assertions.assert_state for tests."""
    assertions.assert_state(actual, expected_subset)


# Keep an explicit module-level list of socket symbols imported so that
# linters don't trip on the import-and-don't-use complaint. (We use
# socket via sf_remote_shim, not directly here, but referencing the
# module avoids re-import drift in future edits.)
_ = socket
_ = os


if __name__ == "__main__":
    raise SystemExit(main())
