"""Canonical tempo regression tests (Hardening Stream E, 2026-05-08).

Three real-world tracks with documented truth values. Each test:
  1. Runs `stemforge split` on the source audio (NO --bpm/--first-downbeat
     overrides — this is the auto-detection path)
  2. Reads the resulting `stems.json`
  3. Asserts BPM is within tolerance of documented truth
  4. Asserts first_downbeat is within tolerance — UNLESS the track is
     flagged `fdb_assert_pending_fix` (= a known auto-detection ceiling
     that we have a filed GH issue for).

These are heavy (each runs Demucs end-to-end, ~30-60s on MPS). Gated by
`@pytest.mark.has_phase3_inputs` — auto-skipped when source files are
missing, opt-in for users who have them.

Why this matters: synth-fixture tests catch many regressions but can't
catch real-world failure modes like beat-this's per-frame quantization
bias (which silently shipped 90.226 BPM for Definition for ~a week —
truth is 89.88). These three tracks anchor the suite to ground truth on
material the device actually targets.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from fixtures.known_tempos import CANONICAL_TRACKS, CanonicalTempo


# Subprocess isolation rationale: invoking `stemforge split` in-process via
# Click's CliRunner triggers a torch double-init in full-suite mode
# ("function '_has_torch_function' already has a docstring") because Demucs
# imports torch a second time after earlier tests have already pulled it in.
# Running each split as a fresh subprocess sidesteps the import state entirely.


@dataclass
class _SplitResult:
    exit_code: int
    output: str


def _run_split(source: Path, out: Path) -> _SplitResult:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "stemforge.cli",
            "split",
            str(source),
            "--output",
            str(out),
            "--pipeline",
            "arrangement",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    return _SplitResult(
        exit_code=proc.returncode,
        output=proc.stdout + proc.stderr,
    )


@pytest.mark.has_phase3_inputs
@pytest.mark.parametrize("track", CANONICAL_TRACKS, ids=[t.name for t in CANONICAL_TRACKS])
def test_canonical_track_bpm_matches_truth(tmp_path: Path, track: CanonicalTempo):
    """`stemforge split` produces stems.json BPM within tolerance of truth.

    Catches sub-quantum BPM bias (median estimator) and refine_bpm wiring
    failures. The 0.10–0.15 BPM tolerance is below user-perceptible drift
    over a 3-minute track (= ~1 beat accumulated max) but big enough to
    catch the 0.4% bias that prompted today's refine_bpm work.
    """
    out = tmp_path / "out"
    result = _run_split(track.source_audio, out)
    assert result.exit_code == 0, result.output

    sj_path = out / track.name / "stems.json"
    assert sj_path.exists(), f"stems.json not produced for {track.name}"
    sj = json.loads(sj_path.read_text())

    delta = abs(sj["bpm"] - track.truth_bpm)
    assert delta <= track.bpm_tolerance, (
        f"{track.name}: bpm={sj['bpm']} vs truth={track.truth_bpm} "
        f"(Δ={delta:.4f}, tol={track.bpm_tolerance}). "
        f"all_estimates: {sj.get('tempo', {}).get('all_estimates')}"
    )


@pytest.mark.has_phase3_inputs
@pytest.mark.parametrize(
    "track",
    [t for t in CANONICAL_TRACKS if not t.fdb_assert_pending_fix],
    ids=[t.name for t in CANONICAL_TRACKS if not t.fdb_assert_pending_fix],
)
def test_canonical_track_first_downbeat_matches_truth(tmp_path: Path, track: CanonicalTempo):
    """`stemforge split` produces stems.json first_downbeat within tolerance.

    Tracks flagged `fdb_assert_pending_fix=True` are excluded from this
    parametrize set — for those, see `test_canonical_track_first_downbeat_pending_fix`.
    """
    out = tmp_path / "out"
    result = _run_split(track.source_audio, out)
    assert result.exit_code == 0, result.output

    sj = json.loads((out / track.name / "stems.json").read_text())
    fdb = sj["tempo"]["first_downbeat_sec"]
    delta_sec = abs(fdb - track.truth_first_downbeat_sec)
    assert delta_sec <= track.fdb_tolerance_sec, (
        f"{track.name}: first_downbeat={fdb}s vs truth="
        f"{track.truth_first_downbeat_sec}s (Δ={delta_sec * 1000:.1f}ms, "
        f"tol={track.fdb_tolerance_sec * 1000:.0f}ms). "
        f"all_estimates: {sj.get('tempo', {}).get('all_estimates')}"
    )


@pytest.mark.has_phase3_inputs
@pytest.mark.parametrize(
    "track",
    [t for t in CANONICAL_TRACKS if t.fdb_assert_pending_fix],
    ids=[t.name for t in CANONICAL_TRACKS if t.fdb_assert_pending_fix],
)
def test_canonical_track_first_downbeat_pending_fix(tmp_path: Path, track: CanonicalTempo):
    """Documents tracks where auto-detect produces the wrong first_downbeat
    pending an open GH issue. When the issue is implemented, the relevant
    track should flip `fdb_assert_pending_fix=False` in known_tempos.py
    and this test will start enforcing the truth value.

    Until then: assert the auto-detector at least produced SOME
    first_downbeat (sanity check that the field is populated). Real
    correctness is deferred to the linked issue.
    """
    out = tmp_path / "out"
    result = _run_split(track.source_audio, out)
    assert result.exit_code == 0, result.output

    sj = json.loads((out / track.name / "stems.json").read_text())
    fdb = sj["tempo"]["first_downbeat_sec"]
    # Only sanity-check that the field is populated and finite.
    assert isinstance(fdb, (int, float))
    assert fdb >= 0

    # Soft signal: if the detector happens to land on truth (= the issue
    # has been fixed in code but the fixture flag wasn't flipped),
    # surface it as a warning rather than failing.
    delta_sec = abs(fdb - track.truth_first_downbeat_sec)
    if delta_sec <= track.fdb_tolerance_sec:
        import warnings

        warnings.warn(
            f"{track.name}: first_downbeat now matches truth "
            f"({fdb}s, Δ={delta_sec * 1000:.1f}ms). "
            f"GH #{track.pending_fix_issue} appears to be resolved — "
            f"flip fdb_assert_pending_fix=False in "
            f"tests/fixtures/known_tempos.py to enforce.",
            UserWarning,
            stacklevel=2,
        )
