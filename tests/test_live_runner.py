"""Self-tests for the Phase 5 Live-in-the-loop smoke runner.

Since the smoke tests themselves require real Ableton Live, this
suite verifies the **infrastructure** instead:

- Fixture status classification (missing / present / corrupt).
- The skip-if-no-fixture decision logic.
- The state-partial-match assertion helper.
- The osascript command-builder (no actual osascript invocation).
- The shell wrapper's --help / --list output.
- The shell wrapper's --skip-fixture-check (meta-test mode).
- Drift between EXECUTION_PLAN_v1.md and the registered smoke functions.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ─── Path bootstrap ────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = REPO_ROOT / "tools" / "test-harness"
RUNNER_SH = HARNESS_DIR / "live-runner.sh"
RUNNER_PY = HARNESS_DIR / "live_runner.py"
PLAN_MD = REPO_ROOT / "docs" / "configurator" / "EXECUTION_PLAN_v1.md"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "als"

# Import live_runner via importlib so the test doesn't depend on a
# package install structure under tools/.
# Make sibling `lib` importable inside live_runner.
sys.path.insert(0, str(HARNESS_DIR))
_spec = importlib.util.spec_from_file_location("live_runner", RUNNER_PY)
assert _spec is not None and _spec.loader is not None
live_runner = importlib.util.module_from_spec(_spec)
# Register in sys.modules BEFORE exec so dataclass()'s introspection
# (which looks the module up by __module__) can find it. Without
# this, exec_module fails with "NoneType has no attribute __dict__".
sys.modules["live_runner"] = live_runner
_spec.loader.exec_module(live_runner)


from lib import assertions, fixtures, osa  # noqa: E402


# ─── Fixture status classification ─────────────────────────────────────────


def test_parse_fixture_status_missing(tmp_path: Path) -> None:
    """A non-existent path is MISSING."""
    assert fixtures.parse_fixture_status(tmp_path / "nope.als") == fixtures.FixtureStatus.MISSING


def test_parse_fixture_status_present(tmp_path: Path) -> None:
    """A gzipped XML is PRESENT."""
    p = tmp_path / "good.als"
    p.write_bytes(gzip.compress(b'<?xml version="1.0"?><Ableton/>'))
    assert fixtures.parse_fixture_status(p) == fixtures.FixtureStatus.PRESENT


def test_parse_fixture_status_corrupt_not_gzipped(tmp_path: Path) -> None:
    """A non-gzip file is CORRUPT (even if it claims to be .als)."""
    p = tmp_path / "bad.als"
    p.write_bytes(b"this is plain text, not gzip")
    assert fixtures.parse_fixture_status(p) == fixtures.FixtureStatus.CORRUPT


def test_parse_fixture_status_corrupt_gzip_no_xml(tmp_path: Path) -> None:
    """A gzip of non-XML is CORRUPT."""
    p = tmp_path / "bad2.als"
    p.write_bytes(gzip.compress(b"not xml at all"))
    assert fixtures.parse_fixture_status(p) == fixtures.FixtureStatus.CORRUPT


def test_shipped_empty_staging_is_present_or_at_least_classified() -> None:
    """The shipped skeleton must be a valid gzipped XML."""
    p = FIXTURES_DIR / "empty-staging.als"
    assert p.exists(), "shipped fixture missing — see tests/fixtures/als/README.md"
    status = fixtures.parse_fixture_status(p)
    assert status == fixtures.FixtureStatus.PRESENT, (
        f"shipped empty-staging.als has bad status {status!r}; "
        "regenerate via lib.fixtures.minimal_skeleton_als_bytes()"
    )


# ─── skip_if_no_fixture decision logic ────────────────────────────────────


def test_skip_if_no_fixture_skips_missing(tmp_path: Path) -> None:
    skip, reason = live_runner.skip_if_no_fixture(tmp_path, "nope.als")
    assert skip is True
    assert "missing" in reason.lower()


def test_skip_if_no_fixture_skips_corrupt(tmp_path: Path) -> None:
    (tmp_path / "bad.als").write_bytes(b"not gzip")
    skip, reason = live_runner.skip_if_no_fixture(tmp_path, "bad.als")
    assert skip is True
    assert "corrupt" in reason.lower()


def test_skip_if_no_fixture_passes_present(tmp_path: Path) -> None:
    (tmp_path / "ok.als").write_bytes(gzip.compress(b"<?xml ?><x/>"))
    skip, reason = live_runner.skip_if_no_fixture(tmp_path, "ok.als")
    assert skip is False
    assert reason == ""


# ─── assert_state partial-match ───────────────────────────────────────────


def test_assert_state_passes_on_partial_match() -> None:
    # Must NOT raise.
    assertions.assert_state(
        {"active_curation": None, "extra": "fine"},
        {"active_curation": None},
    )


def test_assert_state_raises_on_mismatch() -> None:
    with pytest.raises(AssertionError, match="active_curation"):
        assertions.assert_state(
            {"active_curation": "foo"},
            {"active_curation": None},
        )


def test_assert_state_raises_on_missing_key() -> None:
    with pytest.raises(AssertionError, match="missing"):
        assertions.assert_state({}, {"active_curation": None})


def test_assert_state_raises_on_none_actual() -> None:
    with pytest.raises(AssertionError, match="None"):
        assertions.assert_state(None, {"active_curation": None})


def test_assert_state_recursive() -> None:
    assertions.assert_state(
        {"curation": {"name": "x", "groups": 4}, "other": 1},
        {"curation": {"name": "x"}},
    )
    with pytest.raises(AssertionError):
        assertions.assert_state(
            {"curation": {"name": "x"}},
            {"curation": {"name": "y"}},
        )


# ─── osascript command builder ────────────────────────────────────────────


def test_build_open_als_command_shape(tmp_path: Path) -> None:
    app = Path("/Applications/Ableton Live 12 Suite.app")
    als = tmp_path / "x.als"
    als.touch()
    argv = osa.build_open_als_command(app, als)
    assert argv[0] == "osascript"
    assert argv[1] == "-e"
    body = argv[2]
    assert "Ableton Live 12 Suite" in body
    assert str(als) in body
    assert 'tell application "' in body
    assert "open POSIX file" in body


def test_build_quit_command_shape() -> None:
    argv = osa.build_quit_command(Path("/Applications/Ableton Live 12 Suite.app"))
    assert argv[0] == "osascript"
    assert "quit saving no" in argv[2]


def test_open_als_uses_run_wrapper(monkeypatch, tmp_path: Path) -> None:
    """open_als calls subprocess.run via osa._run with the built argv."""
    captured = {}

    def fake_run(argv, *, timeout):
        captured["argv"] = argv
        captured["timeout"] = timeout

        # Mimic a successful osascript run.
        class CP:
            returncode = 0
            stdout = ""
            stderr = ""

        return CP()

    monkeypatch.setattr(osa, "_run", fake_run)
    fixture = tmp_path / "x.als"
    fixture.write_bytes(gzip.compress(b"<?xml ?><x/>"))
    rc = osa.open_als(Path("/Applications/Ableton Live 12 Suite.app"), fixture, timeout=12)
    assert rc is True
    assert captured["argv"][0] == "osascript"
    assert captured["timeout"] == 12
    assert str(fixture) in captured["argv"][2]


def test_app_display_name_strips_dot_app() -> None:
    assert osa.app_display_name(Path("/Applications/Ableton Live 12 Suite.app")) == (
        "Ableton Live 12 Suite"
    )


# ─── Shell wrapper — --help, --list, --skip-fixture-check ─────────────────


def test_live_runner_sh_help_exits_zero() -> None:
    """`live-runner.sh --help` must exit 0 and print usage."""
    cp = subprocess.run(
        [str(RUNNER_SH), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert cp.returncode == 0, f"rc={cp.returncode}\nSTDERR:\n{cp.stderr}"
    out = cp.stdout + cp.stderr
    assert "live-runner.sh" in out
    assert "--all" in out
    assert "--list" in out


def test_live_runner_sh_list_has_ten_smokes() -> None:
    """`live-runner.sh --list` must list exactly 10 smoke tests."""
    cp = subprocess.run(
        [str(RUNNER_SH), "--list"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert cp.returncode == 0, f"rc={cp.returncode}\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}"
    body = cp.stdout
    # The runner prints "smoke_N_..." on its own line; count distinct
    # smoke names.
    smoke_lines = [line for line in body.splitlines() if line.startswith("smoke_") and ":" in line]
    assert len(smoke_lines) == 10, (
        f"expected 10 smoke entries from --list, got {len(smoke_lines)}:\n"
        f"{smoke_lines!r}\n\n--- full stdout ---\n{body}"
    )


def test_live_runner_sh_skip_fixture_check_emits_ten_skips() -> None:
    """`--skip-fixture-check --all` must emit 10 NDJSON skip reports."""
    cp = subprocess.run(
        [str(RUNNER_SH), "--all", "--skip-fixture-check"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert cp.returncode == 0, f"rc={cp.returncode}\nSTDERR:\n{cp.stderr}"
    # Each non-empty stdout line should be a JSON object with status=skip.
    lines = [line for line in cp.stdout.splitlines() if line.strip()]
    assert len(lines) == 10, f"expected 10 NDJSON lines, got {len(lines)}: {lines!r}"
    for line in lines:
        obj = json.loads(line)
        assert obj["status"] == "skip"
        assert "test" in obj


# ─── Drift: plan ↔ implementation ─────────────────────────────────────────


def test_plan_smoke_count_matches_implementation() -> None:
    """Each '- **Smoke N**' bullet in EXECUTION_PLAN_v1.md has a smoke fn."""
    assert PLAN_MD.exists(), f"missing plan: {PLAN_MD}"
    plan_text = PLAN_MD.read_text()
    plan_count = live_runner.parse_smoke_count_from_plan(plan_text)
    impl = live_runner.build_test_registry()
    assert plan_count == len(impl), (
        f"plan lists {plan_count} smokes; live_runner registers {len(impl)}. "
        "Either update the plan or add/remove a smoke_N_* function in live_runner.py."
    )
    # Bonus: every smoke fn name follows the smoke_N_ pattern.
    for t in impl:
        assert t.name.startswith("smoke_"), f"bad smoke name: {t.name}"


def test_every_smoke_has_a_known_fixture() -> None:
    """Every smoke test must reference a fixture in the FIXTURE_INVENTORY."""
    known = {f.filename for f in fixtures.FIXTURE_INVENTORY}
    impl = live_runner.build_test_registry()
    for t in impl:
        assert t.fixture in known, (
            f"smoke {t.name} references unknown fixture {t.fixture!r}; "
            f"add it to lib.fixtures.FIXTURE_INVENTORY and README.md."
        )


def test_runner_emits_ndjson_one_line_per_test(tmp_path: Path) -> None:
    """Smoke a synthetic run: emit_report writes one JSON per test."""
    import io as _io

    buf = _io.StringIO()
    rep = live_runner.TestReport(name="x", status="pass", duration_sec=1.2)
    live_runner.emit_report(rep, stream=buf)
    line = buf.getvalue().strip()
    obj = json.loads(line)
    assert obj == {"test": "x", "status": "pass", "duration_sec": 1.2}
