# Loop-region collapse: second-bounce behavior unverified

**Status:** Mitigated by defensive guard (2026-05-12 — `fix/loop-region-second-bounce-guard`).
`_collapseToLoopRegion` now refuses to write markers when loop bounds already match
the play region (Mode 2 no-op) or fall outside the play region (Mode 3 stale
coordinates); the latter case also emits a `post()` warning. The helper is
safe-by-construction in all three failure modes; pending optional on-device
confirmation of which mode Live actually exhibits, but code correctness no
longer depends on the answer.

## Background

The new `_collapseToLoopRegion` helper writes `loop_start`/`loop_end` onto `start_marker`/`end_marker` before `clip.call("crop")`, so the bounced WAV materializes the loop region. Memory: [`feedback_loop_region_canonical_for_materialize.md`].

This works on FIRST bounce of a clip with its original loop region. We have 6 unit tests covering looping=0, looping=1+divergent bounds, idempotent, and degenerate-bounds safety. All pass.

## What's not tested

**Second-bounce of an already-cropped clip.** When you bounce a clip the first time, Live's `crop` resets the clip's extent. What happens to:

- `looping` flag — preserved or reset?
- `loop_start` / `loop_end` — preserved (now relative to the new clip extent) or reset?
- `start_marker` / `end_marker` — the cropped clip's new natural bounds (0 → new length)

If Live preserves the loop region after crop (now relative to the new extent), a second bounce would re-collapse it idempotently. If Live resets the loop bounds, the helper sees `looping=1` but `loop_start == start_marker` and `loop_end == end_marker`, → no-op write, also safe.

If Live preserves `loop_start`/`loop_end` at OLD coordinates (sample positions that no longer match the cropped audio), we could write garbage to the markers. **This is the failure mode to verify.**

## How to confirm which mode Live exhibits

The guard makes the code safe regardless of Live's actual behavior, but
understanding which mode is in play is still useful context for future LOM
work. To confirm on-device (requires `.pkg` rebuild + reinstall first):

1. In Live, load a clip with a loop region inside the play region (e.g. play 0..8 bars, loop 2..6 bars).
2. Bounce via `sf-remote fire forge bounceTracks <path>`. Verify the bounced WAV is the loop region.
3. **Without reloading the original**, bounce again with the same command.
4. Inspect the Max console:
   - No `[StemForge] _collapseToLoopRegion: loop bounds ... outside play region` warning → Mode 1 or Mode 2 (safe).
   - That warning appears → Mode 3 (helper correctly refused to corrupt; bounce 2 falls through to a plain `crop` of the current play region).
5. Inspect the second-bounce WAV: should match the first-bounce WAV in all modes.

## Done when

Mitigation has landed. Optional follow-up: confirm Mode on-device and record
the answer in `memory/feedback_loop_region_canonical_for_materialize.md`.

The JS mock tests added alongside the guard live in `tests/js_mocks/test_bounce.test.js`:

- `_collapseToLoopRegion: skips when already collapsed (loop bounds == play bounds)`
- `_collapseToLoopRegion: skips + warns when loop_end > end_marker (stale Mode 3)`
- `_collapseToLoopRegion: skips when loop_start < 0 (defensive)`
