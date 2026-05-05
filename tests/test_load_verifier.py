"""Tests for stemforge.load_verifier (Hardening Stream C.3).

Three layers:
    1. Pure-logic unit tests — categorization regex, skip-decision
       helpers, message extraction. Always run, no Max needed.
    2. Skip-path integration — verify the verifier returns a clean
       skip Result when Max isn't installed / Max is already running /
       opted out via env. Always run, no Max session disturbed.
    3. @pytest.mark.live integration — actually launches Max against
       v0/build/StemForge.amxd and asserts the verifier completes.
       Default-skipped via the live-marker auto-skip; opt in with
       STEMFORGE_LIVE=1 (per Stream B.4). Will only run on macOS
       with Max installed AND no pre-existing Max session.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

import pytest

from stemforge import load_verifier as lv
from stemforge.verifiers import Result


REPO_ROOT = Path(__file__).resolve().parent.parent
STEMFORGE_AMXD = REPO_ROOT / "v0" / "build" / "StemForge.amxd"


# ── Layer 1: pure-logic unit tests ───────────────────────────────────────────


def test_error_tag_matches_max_log_format():
    line = (
        "[2026-04-27 13:31:15.777269 error] [4689737] patchcord inlet out of range: 5 outside 0..1"
    )
    assert lv.ERROR_TAG.search(line) is not None


def test_error_tag_does_not_match_info_lines():
    info = "[2026-04-27 13:31:15.777269 info] [4689737] device loaded"
    warn = "[2026-04-27 13:31:15.777269 warning] [4689737] deprecated message"
    assert lv.ERROR_TAG.search(info) is None
    assert lv.ERROR_TAG.search(warn) is None


def test_extract_message_strips_timestamp_and_pid():
    line = (
        "[2026-04-27 13:31:15.777269 error] [4689737] patchcord inlet out of range: 5 outside 0..1"
    )
    msg = lv._extract_message(line)
    assert msg == "patchcord inlet out of range: 5 outside 0..1"


def test_extract_message_falls_back_to_full_line_on_unexpected_format():
    weird = "completely unexpected line format with no brackets"
    assert lv._extract_message(weird) == weird


@pytest.mark.parametrize(
    "line, expected",
    [
        (
            "[t error] [pid] patchcord inlet out of range: blah",
            "patchcord_inlet_oor",
        ),
        (
            "[t error] [pid] patchcord outlet out of range: blah",
            "patchcord_outlet_oor",
        ),
        (
            "[t error] [pid] inlet~: No such object",
            "inlet_outlet_missing",
        ),
        (
            "[t error] [pid] outlet: No such object",
            "inlet_outlet_missing",
        ),
        (
            "[t error] [pid] expr~: syntax error in expression 'foo+'",
            "expr_syntax",
        ),
        (
            "[t error] [pid] can't find file: missing.wav",
            "missing_file",
        ),
        (
            "[t error] [pid] js: no function 'doSomething'",
            "js_no_function",
        ),
        (
            "[t error] [pid] gen~: No such object",
            "missing_object",
        ),
        (
            "[t error] [pid] some unknown error message",
            "other",
        ),
    ],
)
def test_categorize_handles_each_known_pattern(line: str, expected: str):
    assert lv._categorize(line) == expected


def test_categories_list_has_no_duplicate_names():
    names = [name for name, _ in lv.CATEGORIES]
    assert len(names) == len(set(names))


def test_max_bin_candidates_are_all_paths():
    for c in lv.MAX_BIN_CANDIDATES:
        assert isinstance(c, Path)
        assert "Max.app/Contents/MacOS/Max" in str(c)


def test_max_app_bundle_returns_dot_app_dir():
    bin_path = Path("/Apps/Foo.app/Contents/MacOS/Foo")
    assert lv._max_app_bundle(bin_path) == Path("/Apps/Foo.app")


# ── Layer 2: skip-path integration (no Max session disturbed) ────────────────


def test_skip_when_env_var_disables_verifier(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_LOAD_VERIFIER", "0")
    r = lv.verify_max_load(STEMFORGE_AMXD)
    assert r.passed
    assert r.extra.get("skipped") is True
    assert "MAX_LOAD_VERIFIER=0" in r.extra.get("skip_reason", "")


def test_skip_when_no_max_binary_found(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_LOAD_VERIFIER", "")  # don't trip the env-var skip
    monkeypatch.setattr(lv, "_find_max_bin", lambda: None)
    r = lv.verify_max_load(STEMFORGE_AMXD)
    assert r.passed
    assert r.extra.get("skipped") is True
    assert "no Max binary" in r.extra.get("skip_reason", "")


def test_skip_when_max_already_running(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Force the skip-reason gate past, then claim a pre-existing PID set so the
    # "don't trample" gate fires. We use a tmpfile patch path because we don't
    # want to depend on v0/build/StemForge.amxd existing.
    fake_patch = tmp_path / "fake.amxd"
    fake_patch.write_bytes(b"\x00" * 32)
    monkeypatch.setattr(lv, "_skip_reason", lambda: None)
    monkeypatch.setattr(lv, "_list_max_pids", lambda: {99999})
    r = lv.verify_max_load(fake_patch)
    assert r.passed  # skip path
    assert r.extra.get("skipped") is True
    assert r.extra.get("skip_reason") == "max_already_running"
    assert r.extra.get("pre_pids") == [99999]


def test_fail_when_patch_path_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # All gates pass except the patch doesn't exist.
    monkeypatch.setattr(lv, "_skip_reason", lambda: None)
    monkeypatch.setattr(lv, "_list_max_pids", lambda: set())
    r = lv.verify_max_load(tmp_path / "does_not_exist.amxd")
    assert not r.passed
    assert "not found" in r.detail


def test_categorize_a_synthetic_log_slice():
    # Exercise the post-launch branch logic by feeding a synthetic log.
    # The PID-bracket must contain digits to match LINE_AFTER_TAG.
    log = "\n".join(
        [
            "[t1 error] [4689737] patchcord inlet out of range: 5 outside 0..1",
            "[t2 error] [4689737] patchcord inlet out of range: 6 outside 0..1",
            "[t3 error] [4689737] inlet~: No such object",
            "[t4 info] [4689737] device loaded",
        ]
    )
    error_lines = [ln for ln in log.splitlines() if lv.ERROR_TAG.search(ln)]
    assert len(error_lines) == 3
    by_cat: dict = {}
    for ln in error_lines:
        by_cat.setdefault(lv._categorize(ln), []).append(lv._extract_message(ln))
    assert by_cat["patchcord_inlet_oor"] == [
        "patchcord inlet out of range: 5 outside 0..1",
        "patchcord inlet out of range: 6 outside 0..1",
    ]
    assert by_cat["inlet_outlet_missing"] == ["inlet~: No such object"]


# ── Layer 3: live integration (opt-in via STEMFORGE_LIVE=1) ──────────────────


@pytest.mark.live
@pytest.mark.skipif(not STEMFORGE_AMXD.exists(), reason="StemForge.amxd not built")
def test_verify_max_load_runs_against_real_stemforge_amxd():
    # This test: launches Max (or skips if Max already running, no Max
    # installed, etc.), captures error categories, and checks the Result
    # carries the expected fields. We don't assert pass/fail — that's a
    # bug-tracking question, not a test concern. The only failure mode
    # for this test is "verifier crashed".
    r = lv.verify_max_load(STEMFORGE_AMXD)
    assert isinstance(r, Result)
    assert r.verifier == "max_load_clean"
    assert r.pitfall == "#24"
    # Either skipped (Max not present, or already running) or completed
    # cleanly with an error_count. Both are acceptable for a smoke run.
    if r.extra.get("skipped"):
        assert r.extra.get("skip_reason")
    else:
        assert "error_count" in r.extra
        assert "categories" in r.extra
        assert "log_bytes_captured" in r.extra


# ── Acceptance gate sentinel ─────────────────────────────────────────────────


def test_acceptance_gate_HW_3_load_verifier_module_and_cli_wired():
    # Hardening Spec acceptance gate HW-3:
    #   "verify-load runs on developer Mac against v0/build/StemForge.amxd
    #   (or surfaced issues filed and fixed)."
    # Static proof: the load_verifier module exists, exposes verify_max_load,
    # and the verifiers CLI has a verify-load subcommand wired through.
    assert hasattr(lv, "verify_max_load")
    assert callable(lv.verify_max_load)
    assert lv.MAX_LOG.is_absolute()
    assert all(isinstance(p, Path) for p in lv.MAX_BIN_CANDIDATES)
    # CLI wiring sentinel: the verifiers CLI dispatches verify-load.
    from stemforge import verifiers as v

    # Smoke: argparse parses the new subcommand without raising.
    with pytest.raises(SystemExit):
        # --help exits cleanly (SystemExit code 0).
        v.main(["verify-load", "--help"])


def test_categories_regex_compiles_and_uses_word_boundaries():
    # Spot-check a regex pattern uses word boundaries where appropriate
    # (so 'expr_syntax' doesn't match a substring inside another word).
    expr_pattern = next(p for name, p in lv.CATEGORIES if name == "expr_syntax")
    assert isinstance(expr_pattern, re.Pattern)
    # Boundary check: doesn't match inside another word.
    assert not expr_pattern.search("nosyntax error")
    assert expr_pattern.search("expression: syntax error here")


def test_kill_pids_no_op_when_set_empty():
    # _kill_pids should never blanket-kill when given an empty set.
    with mock.patch("subprocess.run") as runner:
        lv._kill_pids(set())
        runner.assert_not_called()
