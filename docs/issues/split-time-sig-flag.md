# `stemforge split` missing `--time-sig` flag

**Status:** Open — captured 2026-05-12.

## Symptom

```bash
uv run stemforge split track.wav --pipeline arrangement --time-sig 7/4
# Error: No such option: --time-sig
```

The `--time-sig` flag exists on `stemforge forge` and on `v0/src/stemforge_curate_bars.py --time-sig`, but not on `stemforge split`. This bit us when re-running tombo_in_7_4: I had to drop the `--time-sig 7/4` argument from the split and pass `--time-sig 7` only to curate.

The detected beat grid for tombo was still 4/4-biased even with the curate hint, because `split` runs the beat detector (beat-this:mix) which doesn't honor the hint — and beat-this returns BPM independent of meter anyway.

## What "fix" looks like

1. **Add `--time-sig N/D` to `stemforge split`** — for parity with `forge` and `curate-bars`. Even if it only affects the librosa fallback (per `forge`'s docstring), it stops the surprise.

2. **Document that `--time-sig` only affects librosa fallback**, not beat-this. Currently the docstring buries this.

3. **Plumb the hint through to `curate-bars`** when both are run from `forge` so the user doesn't pass it twice.

4. **For real odd-meter support**: the beat detector picking BPM is fine — but the downstream "this is a 4-bar loop" assumption in `kit_synthesizer._infer_source_bpm` is what breaks. Path forward in [`bar-inference-canopy.md`](bar-inference-canopy.md).

## Done when

`stemforge split --time-sig N/D` is accepted (even if no-op for beat-this) and `tombo_in_7_4`-style content can be processed end-to-end with one flag set.
