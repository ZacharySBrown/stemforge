# ISSUE: turn `tempo_ground_truth.json` into pytest regression fixtures

**Opened 2026-07-24.** We collected **16 hand-labelled tracks** (tempo verified by click-drift,
downbeat by visual bar-line — Ableton-grade) in `tests/fixtures/tempo_ground_truth.json`. Turn this
into a proper regression test for `reconcile_tempo` so the tempo/downbeat rule can't silently regress.

## What to build
A parametrized test over `tracks[]` that, for each track, asserts:
1. **Tempo** — the reconciler picks within ~4% of `ground_truth.bpm`, using each track's two stored
   estimates (`beat_this_drums`, `beat_this_mix`) as the reconcile inputs. Expected pass rate **14/15**
   (Beck excluded); the 2 `edge_case_feel` tracks (Beck 54-not-108, Can 203-not-100) are **known
   misses** — assert they're flagged/low-confidence, not that they're correct.
2. **Downbeat** — beat-phase of the chosen downbeat is closer to `ground_truth.downbeat_sec` for the
   **drums** estimate than the mix (the validated `drums-db` default). Tolerant thresholds — the
   labels are approximate and some mark bars far from the song start (tempo error compounds).
3. **Classification** — `agree` / `clean-ratio` / `fuzzy` split matches (10/3/3) so the fuzzy path
   stays exercised.

## Why (provenance)
Full write-up: `chroma-stems/specs/handoffs/reconciler-tempo-downbeat-validation.md`. The fix these
fixtures guard: fuzzy disagreement → take the lower/plausible estimate (was: Python took mix, Swift
kept drums). Mirror the same fixtures into the Swift test target for `TempoReconciler.reconcile`.

## Note
`reconcile_tempo` currently re-runs beat-this on audio paths; either (a) refactor a pure
`_reconcile_from_estimates(drums, mix)` seam to test the decision without re-detecting, or (b) stash
short reference clips. (a) is cheaper and is the right seam anyway.
