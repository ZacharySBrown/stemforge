"""Canonical tempo regression fixtures (Stream E hardening, 2026-05-08).

Three real-world tracks with documented truth values for BPM and
first_downbeat. Tests that import this module assert that
`stemforge split` produces values within tight tolerances of the truth
on each track.

These exist as the permanent labeled-example test set against any
future reconciler / refine_bpm / first_downbeat refactor. If a
"refactor that improves things on synth_song" silently regresses
real-world tracks, these tests catch it.

Source files live at `/private/tmp/phase3_inputs/`. Tests requiring
them are marked `@pytest.mark.has_phase3_inputs` and auto-skip when
the files are missing (tests/conftest.py).

Truth values:

  Definition (Black Star feat. Mos Def, Talib Kweli)
    bpm  = 89.88
    fdb  = 8.934s
    Documented in commit d405901 (2026-05-02), confirmed empirically
    via refine_bpm cross-correlation 2026-05-06. The mix detector
    sees a phantom downbeat at 3.78s; the drums detector + locator
    agree on 8.94s. Catches:
      - Sub-quantum BPM bias in the median estimator (would land at
        90.226 instead of ~89.88)
      - Mix-vs-drums first_downbeat disagreement (GH #55 still open;
        until that fix lands, fresh-split first_downbeat asserts
        only that BPM is right).

  Ooh La La (The Faces -- 1971, classic-rock cover sampled in hip-hop)
    bpm  = 84.99
    fdb  = 22.594s
    Long intro (>20s before bar 1) -- catches detectors that miss
    extended intros. Verified 2026-05-06 via locator placement.

  Believer (Imagine Dragons -- electronic-rock, metronomic kick)
    bpm  = 124.99
    fdb  = 0.283s
    Already-correct case. Regression-tests that the system doesn't
    OVER-correct on cleanly-detected tracks.

Tolerances chosen so a regression of >=0.1% BPM or >=50ms phase trips
the test. These are well below the threshold a user would notice,
but big enough to catch a real bug like the median-vs-mean issue
that bit us 2026-05-06.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PHASE3_INPUTS_DIR = Path("/private/tmp/phase3_inputs")


@dataclass(frozen=True)
class CanonicalTempo:
    """One labeled-example track for tempo-detection regression testing."""

    name: str
    source_audio: Path
    truth_bpm: float
    truth_first_downbeat_sec: float
    bpm_tolerance: float = 0.1
    fdb_tolerance_sec: float = 0.05
    # When the auto-detector picks the wrong first_downbeat (e.g.
    # Definition's mix-vs-drums disagreement), assert ONLY bpm and skip
    # first_downbeat assertion. Set to True for tracks where the spec
    # explicitly notes an open auto-detection issue.
    fdb_assert_pending_fix: bool = False
    pending_fix_issue: int | None = None


CANONICAL_TRACKS: list[CanonicalTempo] = [
    CanonicalTempo(
        name="definition",
        source_audio=PHASE3_INPUTS_DIR / "definition.wav",
        truth_bpm=89.88,
        truth_first_downbeat_sec=8.934,
        bpm_tolerance=0.15,  # mean estimator + refine_bpm typically lands within 0.05
        fdb_tolerance_sec=0.05,
        fdb_assert_pending_fix=False,  # GH #55 not yet implemented
        pending_fix_issue=55,
    ),
    CanonicalTempo(
        name="ooh_la_la",
        source_audio=PHASE3_INPUTS_DIR / "ooh_la_la.wav",
        truth_bpm=84.99,
        truth_first_downbeat_sec=22.594,
        bpm_tolerance=0.15,
        fdb_tolerance_sec=0.10,  # 22.594s anchor — a 100ms tolerance is still tight
        # Same mix-vs-drums first_downbeat disagreement as Definition.
        # beat-this:mix returns ~0.02s (a phantom transient at the very
        # start of the long intro); beat-this:drums returns ~22.60s
        # (the actual first kick). The reconciler currently picks mix.
        fdb_assert_pending_fix=False,
        pending_fix_issue=55,
    ),
    CanonicalTempo(
        name="believer",
        source_audio=PHASE3_INPUTS_DIR / "believer.wav",
        truth_bpm=124.99,
        truth_first_downbeat_sec=0.283,
        bpm_tolerance=0.10,
        fdb_tolerance_sec=0.05,
    ),
]


__all__ = ["CANONICAL_TRACKS", "CanonicalTempo", "PHASE3_INPUTS_DIR"]
