"""End-to-end CLI tests for ``stemforge deck-from-manifest``.

Library-level coverage lives in ``tests/ep133/test_deck_autogen.py`` (which
uses Click's in-process ``CliRunner``). This file complements it with a
full-subprocess pattern matching ``tests/test_canonical_tempos.py``'s
``_run_split`` helper: ``python -m stemforge.cli deck-from-manifest ...``
runs the CLI exactly as the user invokes it, including module-import side
effects we'd miss with an in-process runner.

The fixture (``tests/ep133/fixtures/session_mode_manifest.json``) mirrors
the dict shape ``_commitSessionTracks`` writes in the COMMIT flow — see
``v0/src/m4l-js/stemforge_loader.v0.js:1526`` for the canonical authoring
side. File paths in the fixture are intentionally fictional because
``deck-from-manifest`` does not read any WAVs (verified by inspecting
``stemforge/exporters/ep133/deck_autogen.py``); if that changes, this
test will need to materialize real WAVs alongside the fixture.

Closes the last "CLI integration gaps" task from
``docs/issues/hardening-test-coverage-gaps.md``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

# Canonical session-mode fixture committed alongside this test. Kept beside
# the test so the input shape is reviewable in the same diff as the
# assertions that consume it.
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "session_mode_manifest.json"


@dataclass
class _CLIResult:
    exit_code: int
    output: str


def _run_deck_from_manifest(manifest: Path, *extra_args: str) -> _CLIResult:
    """Invoke ``python -m stemforge.cli deck-from-manifest`` as a subprocess.

    Mirrors ``tests/test_canonical_tempos.py::_run_split``'s pattern. The
    deck-from-manifest CLI is dirt-cheap (pure dict transform) so subprocess
    overhead is fine; the value is exercising the real entry point including
    Click registration and the per-command imports done inside the function
    body (``deck_from_manifest_cmd`` lazy-imports ``deck_autogen``).
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "stemforge.cli",
            "deck-from-manifest",
            str(manifest),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return _CLIResult(exit_code=proc.returncode, output=proc.stdout + proc.stderr)


def _staged_manifest(tmp_path: Path) -> Path:
    """Copy the canonical fixture into a per-test tmp dir.

    deck-from-manifest writes ``deck.yaml`` next to the manifest by default,
    so staging into tmp_path keeps the test hermetic and lets ``--project``
    name derivation (which reads ``manifest_path.parent.name``) produce
    something stable across runs.
    """
    assert FIXTURE_PATH.is_file(), f"missing fixture: {FIXTURE_PATH}"
    staged_dir = tmp_path / "curated"
    staged_dir.mkdir(parents=True)
    dest = staged_dir / "manifest.json"
    shutil.copyfile(FIXTURE_PATH, dest)
    return dest


def test_deck_from_manifest_session_mode_smoke(tmp_path: Path) -> None:
    """Fixture → CLI → ``deck.yaml`` exists + valid + row counts match input.

    The fixture's session_tracks block has 3/2/2/1 entries on A/B/C/D
    respectively. After deck-from-manifest the deck.yaml's groups should
    have the same per-group pad counts (no spillover; all under the 12-pad
    cap).
    """
    manifest = _staged_manifest(tmp_path)
    result = _run_deck_from_manifest(manifest, "--project", "smoke_test")
    assert result.exit_code == 0, result.output

    deck_path = manifest.parent / "deck.yaml"
    assert deck_path.is_file(), result.output

    parsed = yaml.safe_load(deck_path.read_text())
    # Top-level keys we always emit.
    assert parsed["project"] == "smoke_test"
    assert parsed["project_slot"] == 8  # default --project-slot
    assert parsed["project_bpm"] == 92.0  # echoed from manifest's bpm field
    assert parsed["time_sig"] == [4, 4]

    # Per-group pad counts mirror the fixture's session_tracks counts.
    expected_counts = {"A": 3, "B": 2, "C": 2, "D": 1}
    for group, expected in expected_counts.items():
        assert group in parsed["groups"], f"group {group} missing from deck"
        assert len(parsed["groups"][group]["pads"]) == expected, (
            f"group {group}: expected {expected} pads, got {len(parsed['groups'][group]['pads'])}"
        )

    # Default format-profile layout is preserved (no --profile/--all-drum).
    assert parsed["groups"]["A"]["format_profile"] == "vocal"
    assert parsed["groups"]["B"]["format_profile"] == "vocal"
    assert parsed["groups"]["C"]["format_profile"] == "drum"
    assert parsed["groups"]["D"]["format_profile"] == "texture"


def test_deck_from_manifest_profile_drum_overrides_format_profile(
    tmp_path: Path,
) -> None:
    """``--profile drum`` rewrites every populated group's format_profile.

    Encodes the breaks-n-beats workflow where every group is a drum kit
    and the prior "patch with sed" step is replaced by the CLI flag.
    """
    manifest = _staged_manifest(tmp_path)
    result = _run_deck_from_manifest(manifest, "--profile", "drum", "--project", "drum_test")
    assert result.exit_code == 0, result.output

    parsed = yaml.safe_load((manifest.parent / "deck.yaml").read_text())
    for group in ("A", "B", "C", "D"):
        assert parsed["groups"][group]["format_profile"] == "drum", (
            f"group {group}: expected drum, got {parsed['groups'][group]['format_profile']}"
        )
        # Each pad inherits drum's default play_mode = "key" (see
        # DEFAULT_PLAY_MODE in deck_autogen.py + feedback_drum_profile_defaults.md).
        for pad in parsed["groups"][group]["pads"]:
            assert pad["play_mode"] == "key", (
                f"pad {pad}: expected play_mode=key (drum default), got {pad.get('play_mode')!r}"
            )


def _strip_source_paths(plan: dict) -> dict:
    """Remove ``source:`` keys from every pad row.

    Each pad's ``source`` field is the absolute path of the manifest the
    deck was generated from. When comparing two runs that staged the
    fixture in different tmp dirs, this field will legitimately differ
    even if every other behavior-bearing field matches. Strip it so the
    comparison focuses on layout/format/play_mode semantics.
    """
    out = json.loads(json.dumps(plan))  # cheap deep-copy
    for gblock in out.get("groups", {}).values():
        for pad in gblock.get("pads", []):
            pad.pop("source", None)
    return out


def test_deck_from_manifest_all_drum_alias(tmp_path: Path) -> None:
    """``--all-drum`` is a documented shortcut for ``--profile drum``.

    Runs the CLI twice against staged copies of the same fixture and
    asserts the resulting deck plans are equivalent (modulo each pad's
    ``source:`` field, which is the absolute manifest path and therefore
    differs by tmp dir). If the two flags ever diverge in any
    behavior-bearing field, the "shortcut" framing in the CLI help is a lie.
    """
    # First run: --profile drum.
    manifest_a = _staged_manifest(tmp_path / "a")
    result_a = _run_deck_from_manifest(manifest_a, "--profile", "drum", "--project", "shared_name")
    assert result_a.exit_code == 0, result_a.output
    deck_a = yaml.safe_load((manifest_a.parent / "deck.yaml").read_text())

    # Second run: --all-drum.
    manifest_b = _staged_manifest(tmp_path / "b")
    result_b = _run_deck_from_manifest(manifest_b, "--all-drum", "--project", "shared_name")
    assert result_b.exit_code == 0, result_b.output
    deck_b = yaml.safe_load((manifest_b.parent / "deck.yaml").read_text())

    assert _strip_source_paths(deck_a) == _strip_source_paths(deck_b), (
        "deck.yaml differs between --profile drum and --all-drum "
        "(after stripping per-tmp-dir source paths)"
    )


def test_deck_from_manifest_play_mode_propagates(tmp_path: Path) -> None:
    """``--play-mode oneshot`` overrides the per-profile default on every row.

    Without the flag, group C (drum) would default to play_mode=key. With
    the flag, every pad — including drum-group pads — must end up oneshot.
    """
    manifest = _staged_manifest(tmp_path)
    result = _run_deck_from_manifest(
        manifest, "--play-mode", "oneshot", "--project", "play_mode_test"
    )
    assert result.exit_code == 0, result.output

    parsed = yaml.safe_load((manifest.parent / "deck.yaml").read_text())
    seen_any = False
    for group in ("A", "B", "C", "D"):
        for pad in parsed["groups"][group]["pads"]:
            assert pad["play_mode"] == "oneshot", (
                f"group {group} pad {pad.get('pad')}: expected play_mode=oneshot, "
                f"got {pad.get('play_mode')!r}"
            )
            seen_any = True
    assert seen_any, "no pads to assert against — fixture/CLI regression"


def test_deck_from_manifest_per_clip_bpm_preserved(tmp_path: Path) -> None:
    """Per-clip ``source_bpm`` from the manifest threads into the deck row.

    The COMMIT flow captures each clip's warp_bpm (via warp_markers slope)
    pre-crop and writes it into ``session_tracks[L][i].source_bpm``. The
    deck row must carry that value forward as ``source_bpm`` so kit
    synthesis can skip duration-based inference. Per-clip BPM should NOT
    be overwritten by the project-level BPM — they're independent fields.
    """
    manifest = _staged_manifest(tmp_path)
    result = _run_deck_from_manifest(manifest, "--project", "bpm_test")
    assert result.exit_code == 0, result.output

    parsed = yaml.safe_load((manifest.parent / "deck.yaml").read_text())
    project_bpm = parsed["project_bpm"]
    assert project_bpm == 92.0

    # The fixture has heterogeneous per-clip source_bpm values
    # (88.5 / 141.27 / 184.0 etc.) — all are deliberately != project_bpm so
    # a "copy project_bpm everywhere" bug would be visible.
    fixture = json.loads(FIXTURE_PATH.read_text())
    expected_bpms_by_slot = {}
    for group, entries in fixture["session_tracks"].items():
        expected_bpms_by_slot[group] = {e["slot"]: e["source_bpm"] for e in entries}

    # Walk every produced pad and assert source_bpm matches the fixture's
    # entry for the pad's (group, slot:N) coordinates.
    saw_non_project_bpm = False
    for group, gblock in parsed["groups"].items():
        for pad in gblock["pads"]:
            origin = pad["group"]
            slot = int(pad["clip"].removeprefix("slot:"))
            expected = expected_bpms_by_slot[origin][slot]
            assert "source_bpm" in pad, (
                f"group {group} pad {pad.get('pad')}: missing source_bpm "
                f"(fixture had {expected} for origin {origin} slot {slot})"
            )
            assert pad["source_bpm"] == pytest.approx(expected), (
                f"group {group} pad {pad.get('pad')}: source_bpm={pad['source_bpm']} "
                f"!= fixture {expected} (origin {origin} slot {slot})"
            )
            if pad["source_bpm"] != project_bpm:
                saw_non_project_bpm = True
    assert saw_non_project_bpm, (
        "every per-clip source_bpm equaled project_bpm — fixture or pipeline "
        "lost the per-clip BPM signal we're trying to assert here"
    )
