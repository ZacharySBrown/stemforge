# Phase 3: ANCH as Bar-Grid Re-Anchor

**Status:** Spec only — not yet implemented. Write up captured at end of the
2026-05-03 session for review in a separate session before any code changes.

## Today's behavior (after Phase 1+2)

ANCH is a **pure JS timeline shift**:

1. Read first cue_point from `live_set.cue_points`.
2. Read manifest's `musical_bar_1_chunk_index` (0-indexed; ≥ 0).
3. Compute `pristineBar1Beat = musical_bar_1_chunk_index × chunkBeats`.
4. Compute `shift = locatorBeat − pristineBar1Beat`.
5. Outlet `(manifestPath, shift)` to the loader; loader places clip[i] at
   `i × chunkBeats + shift`.

No re-cut. No Python. Same chunk WAVs, same loop regions, just placed at
shifted timeline positions. After the Phase 1+2 prechop fixes, intro
chunks appear as full-length blocks before bar 1, which is what the user
wants.

**Limitation today:** the locator is implicitly assumed to mark **bar 1**.
If the user drops it on bar 5 or bar 17 (any other bar), the shift puts
chunk[`musical_bar_1_chunk_index`] at the locator — i.e., it treats the
locator as bar 1. There's no notion of "this is bar N, derive bar 1 from
it."

## Phase 3 — proposed change

Make ANCH **bar-aware**: the locator marks the start of *some* bar, not
necessarily bar 1. From its source-time + the BPM, derive where every bar
boundary in the song lives, then re-cut the chunks so they're cleanly
bar-aligned (same chunk lengths, but `first_downbeat_sec` corrected so the
locator falls exactly on a chunk boundary).

### Algorithm

```
# In sf_locator_anchor.js anchor():
locatorBeat       = picked.time_beats              # from LOM
locatorSourceSec  = _sourceTimeAtTimelineBeat(manifest, locatorBeat)
                                                   # uses CURRENT chunk grid
barSeconds        = beatsPerBar × 60 / bpm         # 1 bar in source-time
newFirstDownbeat  = locatorSourceSec mod barSeconds
                                                   # smallest non-negative
                                                   # bar boundary in source

# Then shell to:
stemforge re-anchor <track_dir> \
  --bpm <Live tempo> \
  --first-downbeat <newFirstDownbeat> \
  --pre-bars <auto>                                # default behavior
```

Once the helper finishes, reload the arrangement at `shift=0` (chunks are
now bar-aligned in source, so they're bar-aligned in the timeline at
`i × chunkBeats`). The locator the user dropped will sit precisely on a
chunk boundary in the new layout.

### Concrete example: Definition

- BPM = 89.88, `barSeconds` = 60×4/89.88 ≈ 2.67 sec
- User drops locator at timeline beat 16 (start of clip[1] in current
  layout, where bar 1 of the song actually plays).
- `_sourceTimeAtTimelineBeat` converts beat 16 → source 8.935 sec
  (this happens to be the current `first_downbeat`).
- `newFirstDownbeat = 8.935 mod 2.67 = 0.93 sec`
- Re-anchor with `first_downbeat=0.93` and auto `--pre-bars`. The new
  manifest has bar 1 of the chunk grid at source 0.93 sec; the user's
  locator (which marked source 8.935) sits exactly at chunk[3]'s start
  — a clean bar boundary in the new grid.

The interpretation: the user's locator marks *bar 4* of the song (since
8.935 = 0.93 + 3 × 2.67), not bar 1. Bar 1 is at source 0.93. The DJ
intro from source 0 to 0.93 is the partial-bar before bar 1; intro
chunks cover bars 1, 2, 3 at source 0.93, 3.6, 6.27 respectively.

## What changes vs today

| Aspect | Today (Phase 1+2) | After Phase 3 |
|---|---|---|
| ANCH behavior | Pure JS shift | Re-cut via Python (~2s) |
| Source content | Untouched | Re-cut at new `first_downbeat` |
| Chunk WAVs | Same as before | Regenerated |
| Manifest | Unchanged | New `first_downbeat_sec`, new chunk count |
| Iteration speed | Instant (~10ms) | ~2 sec roundtrip |
| Locator semantics | "Locator IS bar 1" (implicit) | "Locator IS the start of *a* bar" |

## What this fixes

1. **Songs where auto-detected `first_downbeat` is bar-aligned but on the
   wrong bar.** Today the user has to manually override `first_downbeat`
   via CLI `re-anchor`. Phase 3 lets them just drop a locator on any
   audible bar boundary and hit ANCH — the algorithm finds bar 1 from
   there.
2. **Sub-beat misalignment.** If the auto-detected `first_downbeat` is
   *between* bar boundaries (e.g., 0.5 of a beat early), Phase 3
   corrects it: the new `first_downbeat = locator_source mod
   barSeconds` is by construction on a bar grid, so subsequent chunks
   land on bar boundaries.

## What this might break

- **The pure-shift workflow.** Today the user can ANCH multiple times
  with different locator positions and see different shifts instantly.
  Phase 3 makes each ANCH a re-cut, so iteration is slower and source
  WAVs are rewritten each time. We might want to preserve a "shift only"
  variant (perhaps a modifier on the click — shift-click ANCH for pure
  shift, plain click ANCH for bar-grid).
- **Manifest churn.** Each ANCH press rewrites the manifest. Users
  iterating on locator placement may not want this. (Mitigation: write
  to a `.tmp` manifest and only commit on confirmation? Probably overkill.)
- **Sub-beat snap is opinionated.** `mod barSeconds` always lands the new
  `first_downbeat` in `[0, barSeconds)`. If the song has a long pickup
  or anacrusis the user *wants* preserved as bars 1-N before the kick,
  this would compress them all into the partial bar at the start. The
  current pure-shift workflow handles this naturally — pre-bars chunks
  remain visible before the locator.

## Open questions for the next session

1. **Does the user actually need bar-grid alignment?** In their testing
   so far, the locator HAS been at bar 1 each time. The "locator is any
   bar" generalization is hypothetical — confirm with the user that
   this is a real workflow, not a theoretical one.
2. **Modifier keys.** If we keep pure-shift as the default and put bar-
   grid alignment behind a modifier (or a second button), which is the
   primary?
3. **Preserve intro chunks.** The pure-shift workflow keeps existing
   intro chunks visible. Phase 3's `mod barSeconds` always puts bar 1
   within 1 bar of source 0, eliminating any meaningful intro coverage.
   Is the user OK with that?
4. **Rounding.** Should the algorithm snap `locatorSourceSec` to the
   nearest bar boundary (assuming current grid is approximately right)
   before computing the new `first_downbeat`? That would make ANCH
   resilient to small locator placement errors.

## Files that would change

- `v0/src/m4l-js/sf_locator_anchor.js` — anchor() switches from pure
  shift to shell-out, like the pre-pivot version but using `mod` math.
- `v0/src/m4l-js/sf_arrangement_loader.js` — reload uses `shift=0`,
  same as the original (no changes).
- `tools/m4l_locator_anchor.py` — already exists from the earlier
  Python-helper iteration; unchanged.
- Patcher wiring — the `anchor_started/complete/error` NDJSON routes
  are still in place (we never removed them). Just need to re-enable
  the shell-out path in the JS.

## Why this is a separate session

The user explicitly wants to think about this before any code changes
go in. The Phase 1+2 fixes already handle the immediate issue (full
song coverage with intro chunks). Phase 3 is an enhancement on top.
