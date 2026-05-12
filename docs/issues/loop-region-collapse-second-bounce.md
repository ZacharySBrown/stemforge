# Loop-region collapse: second-bounce behavior unverified

**Status:** Open — captured 2026-05-12.

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

## How to test

1. In Live, load a clip with a loop region inside the play region (e.g. play 0..8 bars, loop 2..6 bars).
2. Bounce via `sf-remote fire forge bounceTracks <path>`. Verify the bounced WAV is the loop region.
3. **Without reloading the original**, bounce again with the same command.
4. Inspect the second-bounce output: same audio? Truncated? Errors in Max console?

## Done when

Either:
- We confirm Live resets loop bounds on crop (then the helper is safe on second bounce — no action needed).
- We find a failure mode and add an early-return when post-crop loop bounds match play bounds.

Also: add a JS mock test that exercises this case once we know what to assert.
