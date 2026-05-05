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

## Empirical test data (2026-05-03 from-scratch restem)

To inform the Phase 3 decision, three tracks were restemmed with no
overrides and no pre-existing manifest. Auto-detection landed:

| Track | BPM detected | BPM truth | first_downbeat | Reconciler source |
|---|---|---|---|---|
| Definition | 120.19 | 89.88 | None | `librosa:drums`, low conf |
| Believer | 126.05 | ~125 | None | `librosa:drums`, low conf |
| Ooh La La | 84.72 | ~85.11 | None | `librosa:drums`, low conf |

All three fell back to `librosa:drums` with low confidence — the
multi-source reconciler did not reach consensus on any of them. None
got a `first_downbeat`, so prechop defaulted to cutting from source 0
(`pre_bars=0`, `musical_bar_1_chunk_index=0`).

### What this implies for Phase 3 scope

- **Definition is the only case where BPM is materially wrong** (doubled
  — the half-time hip-hop trap the reconciler was supposed to catch but
  didn't here). Pure-shift ANCH cannot fix this: chunks are physically
  the wrong duration in source-time, so shifting them just relocates
  wrongly-sized clips. This case needs a re-anchor with `--bpm`
  override.
- **Believer and Ooh La La have correct BPM**, just missing
  `first_downbeat`. For these, pure-shift ANCH (the current behavior)
  is sufficient: drop a locator at any audible bar, ANCH shifts
  chunks so that bar lands at the locator. No re-cut needed.

### Possible smaller-scoped Phase 3

Rather than full bar-grid re-anchor, consider:

**Phase 3a — "ANCH adopts Live's tempo as new BPM."**
On every ANCH press, if Live's project tempo differs from the manifest's
BPM by more than a small ε, treat that as a BPM correction signal:
shell `stemforge re-anchor --bpm <Live tempo> --first-downbeat <derived
from locator>`. If Live's tempo matches the manifest, do the current
pure-shift. This way the user's manual workflow becomes:
1. Listen to the chunks; if they're playing the wrong tempo, drag
   Live's tempo until the loop seam is clean (the existing
   `probe_loop.py` workflow but in-Ableton).
2. Drop a locator at bar 1.
3. ANCH — picks up the corrected tempo AND the bar-1 source position
   in one shot.

This handles the Definition case (BPM correction) and the Believer /
Ooh La La case (downbeat correction) without forcing a full re-anchor
on every press. **Cost**: still ~2s per press when BPM differs (Python
shell-out); free (~10ms) when BPM matches (pure shift).

This is probably the right scope. Phase 3 as originally specced (mod
`barSeconds`) is more theoretical and harder to explain; Phase 3a
maps directly to the user's mental model ("I corrected the tempo by
ear, now lock it in").

## 2026-05-03 update — Why Phase 3 is needed even with beat-this in the loop

After installing the `beat` extra (`uv sync --extra beat --extra native`)
and re-stemming all three test tracks, BPM detection became reliable on
all of them — including Definition (90.23 vs truth 89.88, well within
tolerance). But the user still hit a gap on Definition that pure-shift
ANCH cannot close:

**The mismatch:** beat-this returns the *first audible bar boundary* it
detects. For tracks with a clean opening kick (Believer, source 0.300s),
that equals "bar 1 of the song" in the user's musical sense. For tracks
with an intro section before the main drop (Definition, Ooh La La),
beat-this lands on the intro's first bar — which is not what the user
hears as bar 1.

Concretely on Definition:
- beat-this `first_downbeat` = 3.78s (some early intro bar)
- User's "bar 1 of the song" = ~22s (where the main drop hits)
- 22 − 3.78 ≈ 18.2s ≈ 6.8 bars — the user's bar 1 is bar ~7 of beat-this's grid

**Why pure-shift can't fix this.** Pure-shift moves chunk[0] to the
locator's timeline position. But chunk[0]'s *content* is source[3.78s,
3.78 + chunk_period], which is the intro music — not the drop. After
the shift, the drop audio (which was at some later timeline beat in the
loaded clips) is also pushed further right; it never lands at the
locator. The locator placement and the audio identity are decoupled in
the pure-shift model.

What's needed instead is a **source-level re-anchor**: change
`first_downbeat_sec` in the manifest so chunk[0] starts at *the source
time the user heard at the locator*, then reload at the default position.
That's what the original (pre-pivot) Python re-anchor flow did; the
pivot to pure-shift removed it from the JS button.

### What's still wired (dormant) vs. what was disabled

The pure-shift pivot only edited one function — `anchor()` in
`v0/src/m4l-js/sf_locator_anchor.js`. Everything else still exists:

| Component | State |
|---|---|
| Patcher route `anchor_started` / `anchor_complete` / `anchor_error` | wired in `.amxd` |
| `tools/m4l_locator_anchor.py` helper | on disk in main repo |
| NDJSON parser cases for the three anchor events | in `stemforge_ndjson_parser.v0.js` |
| `outlet 1` from `sf_locator_anchor` → `[shell]` | wired in `.amxd` |
| `onAnchorStarted` / `onAnchorComplete` / `onAnchorError` handlers | defined in `sf_locator_anchor.js` |
| `outlet 2` → `loadArrangementFromManifest` (reload after anchor) | wired in `.amxd` |
| `_sourceTimeAtTimelineBeat()` helper for back-computing source time | in `sf_locator_anchor.js` |

What was removed: the *call* to `outlet(1, PYTHON_BIN, HELPER_PATH, ...)`
inside `anchor()`. Restoring it doesn't need a `.amxd` rebuild or any
patcher edits.

### Minimal restoration diff

Replace the body of `anchor()` in
`v0/src/m4l-js/sf_locator_anchor.js` with something close to the
pre-pivot version:

```javascript
function anchor() {
    var argv = arrayfromargs(arguments);
    var dir = argv.length ? String(argv[0]) : TRACK_DIR;
    if (!dir) {
        _status("anchor: no track dir set (call trackDir <path> first)");
        return false;
    }
    dir = _expandTilde(dir);

    var manifestPath = _join(dir, "prechop_manifest.json");
    var manifest = _readJsonFile(manifestPath);
    if (!manifest) {
        _status("anchor: cannot read " + manifestPath);
        return false;
    }

    var locators = _readLocators();
    if (!locators.length) {
        _status("anchor: drop a locator first");
        return false;
    }
    var picked = _pickLocator(locators);

    // Convert the locator's timeline beat → source-time using the
    // CURRENT chunk grid in the loaded manifest.
    var sourceTime = _sourceTimeAtTimelineBeat(manifest, picked.time_beats);
    if (sourceTime == null) {
        _status("anchor: locator at beat " + picked.time_beats +
                " falls outside the chunk grid");
        return false;
    }

    // Live's tempo wins for BPM. Lets the user nudge tempo before ANCH
    // (the Phase 3a workflow) and have it picked up automatically.
    var tempo = 120;
    try { tempo = Number(new LiveAPI("live_set").get("tempo")); } catch (_) {}
    if (!isFinite(tempo) || tempo <= 0) tempo = Number(manifest.bpm) || 120;

    _status("anchor: locator '" + (picked.name || "(unnamed)") +
            "' at beat " + picked.time_beats.toFixed(2) +
            " → source " + sourceTime.toFixed(4) + "s, bpm=" + tempo);

    // Shell to the helper. The patcher's prepend `loadArrangementFromManifest`
    // (wired to outlet 2) handles the reload after `onAnchorComplete` fires.
    try {
        outlet(1, PYTHON_BIN, HELPER_PATH,
               "--track-dir", dir,
               "--bpm", String(tempo),
               "--first-downbeat", sourceTime.toFixed(6),
               "--manifest-out", manifestPath);
    } catch (e) {
        _status("anchor: spawn outlet error: " + e);
        return false;
    }
    return true;
}
```

Then update `onAnchorComplete` to outlet on outlet 2 with the manifest
path (no shift atom — the chunks are now bar-aligned in source so
default load position is correct). The current outlet-2 path emits
`(manifestPath, shift=0)` which the loader handles fine.

### Decision points for the next session

1. **Replace pure-shift, or keep both?** Pure-shift is fast (~10ms)
   and works perfectly for tracks where chunks are already bar-aligned
   in the user's musical sense (e.g., Believer). Re-anchor is slower
   (~2s) but corrects source-level mistakes (Definition, Ooh La La).
   Options:
   - **Replace.** Plain ANCH = re-anchor always. Simpler mental model;
     the ~2s cost is acceptable since users only ANCH a few times per
     track.
   - **Modifier-split.** Plain click = re-anchor (the harder case);
     shift-click or alt-click = pure shift (the visual nudge). Easy to
     wire in `sf_ui.js`'s `onclick(x, y, button, mod1, shift, ctrl, mod2)`.
   - **Two buttons.** ANCH and SHIFT side-by-side. Most discoverable but
     eats more canvas real estate.

2. **What to do about Live's tempo override.** The minimal diff above
   reads Live's tempo and passes it as `--bpm`. That's the Phase 3a
   behavior baked in. For Believer (where BPM is already correct in
   the manifest), Live's tempo will match and re-anchor is a no-op
   on BPM, just corrects `first_downbeat`. For Definition (where the
   user might have manually corrected tempo), it adopts the new BPM.
   Worth keeping as the default; no toggle needed.

3. **Update the test suite.** The Phase 3 implementation removes the
   shift-from-outlet-2 contract from anchor() (replaced with a
   reload-via-onAnchorComplete contract). Three tests in
   `tests/js_mocks/test_locator_anchor.test.js` assert outlet-2 atoms
   directly (`anchor: emits reload atoms (path + shift) on outlet 2`,
   `anchor: shift respects musical_bar_1_chunk_index`, `anchor:
   locator beat outside original grid still shifts`). They'll need
   to be rewritten or replaced to assert outlet-1 (shell) atoms.
