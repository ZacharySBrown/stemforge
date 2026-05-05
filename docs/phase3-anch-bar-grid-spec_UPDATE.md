# Phase 3 (Revised v2): ANCH as Bar-Grid Re-Anchor with Promotable Leading Chunk

**Status:** Spec only — supersedes the prior v1 of this spec. Captured
2026-05-03 after a code-grounded review identified four issues (no
forge-time silence trim exists, manifest field name mismatch, prechop
pseudocode bug for `first_downbeat > chunkPeriod`, and an interpretive
gap about chunk geometry) and added the named-locator mechanism to
handle Definition's likely multi-chunk-period error case.

## TL;DR

ANCH becomes a thin trigger over the existing re-anchor flow, with these
properties:

1. **Locator-position-within-chunk math.** The user drops a locator on
   an audible bar boundary anywhere in the song; ANCH derives the
   bar-grid correction from where the locator falls inside its
   containing chunk.
2. **Named-locator parsing.** If the locator is named with a bar number
   (e.g., `4`, `bar 4`), JS subtracts `(N-1) × barSeconds` from the
   locator's source-time before running the offset math. This handles
   the case where the auto-detected bar grid is correct modulo a
   whole-chunk-period shift but wrong about which bar is bar 1.
3. **Live's tempo wins.** If the user nudged Ableton's tempo to fix a
   detected-BPM mistake, ANCH adopts that as the new manifest BPM.
4. **Pre-downbeat audio is promoted to a visible chunk when it can't fit
   the pad-stash.** Existing prechop already preserves sub-bar
   pre-downbeat material in chunk_001's pre-pad (hidden behind
   `loop_start_sec`). The new emit path adds a visible chunk_001 when
   the leading region exceeds pad capacity, with left-silence-pad
   inside the loop region so chunks remain uniform-width and bar-
   aligned in arrangement view.
5. **RMS heuristic gates emit.** Skip the new emit when the leading
   region is dead air below a noise floor.

## Background: how leading audio is handled today

Verified from the worktree: there is **no source-level silence trim**
at forge time. The mechanism that makes leading audio "disappear" in
arrangement view is a pad-stash:

- prechop reads chunk_001 starting at `max(0, downbeat_offset -
  pad_pre_frames)`, capturing pre-downbeat audio in the pre-pad region
  of the chunk WAV.
- The manifest's `loop_start_sec` is set to where the bar grid begins
  inside the chunk WAV (e.g., 0.300s for Believer).
- The M4L loader sets the Live clip's `loop_start` to that value, so
  playback (and visual loop region) only includes audio from
  `loop_start_sec` onward.
- The pre-downbeat audio is physically present in the WAV but latent
  in the pad — accessible only by dragging the clip's left edge
  backward in Ableton.

This works elegantly for **sub-bar pre-downbeat material**: a 0.300s
intro at 125 BPM (~0.16 bars) fits comfortably in a 1-bar pre-pad and
stays out of the way until you want it.

It **breaks down for multi-bar pre-locator material**:

- `pad_pre_frames` defaults to ~1 bar. Any pre-downbeat audio beyond
  that is clipped at source 0 — gone. Only the bar nearest the
  downbeat survives, latent.
- Even within pad capacity, accessing the audio requires manual clip-
  edge drag in Ableton — not a workflow that scales to many tracks.

The new emit case in this spec **promotes** multi-bar pre-locator
audio out of the pad-stash and into a first-class visible chunk_001,
so it appears in arrangement view and is editable via normal clip
operations.

## Algorithm

### JS side (`v0/src/m4l-js/sf_locator_anchor.js`)

```javascript
function anchor() {
    var argv = arrayfromargs(arguments);
    var dir = argv.length ? String(argv[0]) : TRACK_DIR;
    if (!dir) { _status("anchor: no track dir set"); return false; }
    dir = _expandTilde(dir);

    var manifestPath = _join(dir, "prechop_manifest.json");
    var manifest = _readJsonFile(manifestPath);
    if (!manifest) { _status("anchor: cannot read manifest"); return false; }

    var locators = _readLocators();
    if (!locators.length) { _status("anchor: drop a locator first"); return false; }
    var picked = _pickLocator(locators);

    // Convert locator's timeline beat → source-time using current grid.
    var locatorSourceSec = _sourceTimeAtTimelineBeat(manifest, picked.time_beats);
    if (locatorSourceSec == null) {
        _status("anchor: locator outside chunk grid");
        return false;
    }

    // Live's tempo wins.
    var tempo = 120;
    try { tempo = Number(new LiveAPI("live_set").get("tempo")); } catch (_) {}
    if (!isFinite(tempo) || tempo <= 0) tempo = Number(manifest.bpm) || 120;

    // Geometry constants. Note: manifest field is `bars`, not `bars_per_chunk`.
    var beatsPerBar = Number(manifest.beats_per_bar) || 4;
    var barsPerChunk = Number(manifest.bars) || 1;
    var barSeconds = beatsPerBar * 60 / tempo;
    var chunkPeriodSec = barsPerChunk * barSeconds;

    // Named-locator parsing: extract bar number from locator name.
    // "1" → 1, "bar 4" → 4, "4 bar 1" → 4 (first integer wins),
    // "" or "downbeat 1" → 1 (default).
    var locatorBarNumber = _parseBarFromLocatorName(picked.name);

    // Adjust locator source-time: if user said this is bar N, then
    // bar 1 is (N-1) bars earlier in source-time.
    var adjustedSourceSec = locatorSourceSec - (locatorBarNumber - 1) * barSeconds;

    if (adjustedSourceSec < 0) {
        _status("anchor: locator '" + picked.name + "' = bar " + locatorBarNumber +
                " puts bar 1 at source " + adjustedSourceSec.toFixed(3) +
                "s (negative). Check locator name.");
        return false;
    }

    // Offset-within-chunk math (against the bar-1-adjusted source time).
    var oldFirstDownbeat = Number(manifest.first_downbeat_sec) || 0;
    var relSec = adjustedSourceSec - oldFirstDownbeat;
    var offsetWithinChunk = ((relSec % chunkPeriodSec) + chunkPeriodSec) % chunkPeriodSec;

    // Snap to NEAREST chunk boundary, not always forward.
    var signedOffset = offsetWithinChunk;
    if (signedOffset > chunkPeriodSec / 2) {
        signedOffset -= chunkPeriodSec;
    }

    var newFirstDownbeat = oldFirstDownbeat + signedOffset;
    if (newFirstDownbeat < 0) newFirstDownbeat += chunkPeriodSec;

    // Idempotency: skip re-anchor if correction is below threshold.
    var IDEMPOTENCY_THRESHOLD_SEC = 0.005;  // 5ms
    if (Math.abs(signedOffset) < IDEMPOTENCY_THRESHOLD_SEC) {
        _status("anchor: locator '" + picked.name + "' (bar " + locatorBarNumber +
                ") already on bar grid (offset " + (signedOffset * 1000).toFixed(1) +
                "ms < threshold), no-op");
        return false;
    }

    _status("anchor: locator '" + (picked.name || "(unnamed)") +
            "' = bar " + locatorBarNumber +
            " at source " + locatorSourceSec.toFixed(3) +
            "s, adjusted bar 1 → " + adjustedSourceSec.toFixed(3) +
            "s, signedOffset " + signedOffset.toFixed(3) +
            "s, newFirstDownbeat " + newFirstDownbeat.toFixed(4) +
            "s, bpm=" + tempo);

    try {
        outlet(1, PYTHON_BIN, HELPER_PATH,
               "--track-dir", dir,
               "--bpm", String(tempo),
               "--first-downbeat", newFirstDownbeat.toFixed(6),
               "--manifest-out", manifestPath);
    } catch (e) {
        _status("anchor: spawn outlet error: " + e);
        return false;
    }
    return true;
}

// Parse first integer from locator name, default 1.
// Examples: "1" → 1, "bar 4" → 4, "downbeat 1" → 1, "" → 1, "4 bar" → 4
function _parseBarFromLocatorName(name) {
    if (!name) return 1;
    var match = String(name).match(/(\d+)/);
    if (!match) return 1;
    var n = parseInt(match[1], 10);
    return (isFinite(n) && n >= 1) ? n : 1;
}
```

Key properties:

- **Named-locator default of 1.** Backwards-compatible: existing
  workflows that drop a locator named `downbeat 1` or just `1` continue
  to work unchanged. The `(N-1) × barSeconds` term is zero when N=1.
- **Multi-chunk-period error handled.** For Definition, if beat-this's
  grid is bar-aligned but the user's musical bar 1 is several bars
  ahead, the user names their locator `4` (or whatever bar they can
  hear cleanly), and the math derives bar 1 correctly.
- **Idempotent at the bar level.** A locator that already lands on a
  chunk boundary (after bar-number adjustment) within 5ms is a no-op.
- **Smallest correction.** `signedOffset ∈ [-chunkPeriodSec/2,
  +chunkPeriodSec/2)` after the named-locator adjustment.

### Prechop side (`stemforge/prechop.py`)

The new emit case promotes pre-downbeat audio to a visible chunk_001
when (a) there's a meaningful sub-chunk-period remainder of pre-audio
and (b) it has audible content above the noise floor.

```python
# After the existing pre-bars + post-downbeat chunk emit loop,
# add the leading-partial-chunk emit case.

if first_downbeat_sec > 0:
    # Take only the SUB-CHUNK-PERIOD remainder. Whole chunks of
    # pre-downbeat material are already emitted by the existing
    # pre-bars auto path (cli.py:637-641).
    leftover_sec = first_downbeat_sec % chunkPeriodSec
    leftover_frames = int(leftover_sec * sample_rate)

    if leftover_frames > 0:
        # The leftover region in source: [bar_aligned_start, first_downbeat_sec)
        # where bar_aligned_start = first_downbeat_sec - leftover_sec
        bar_aligned_start_frames = int(first_downbeat_sec * sample_rate) - leftover_frames
        leading_region = source_audio[bar_aligned_start_frames :
                                      bar_aligned_start_frames + leftover_frames]

        # RMS gate: skip emit if leading region is dead air.
        leading_rms = np.sqrt(np.mean(leading_region ** 2))
        SILENCE_THRESHOLD_DBFS = -60.0
        silence_floor_amplitude = 10 ** (SILENCE_THRESHOLD_DBFS / 20.0)

        if leading_rms < silence_floor_amplitude:
            # Skip emit — leading region is silence. Behaves like
            # today's pad-stash: pre-audio (if any) lives latent in
            # chunk_002's pre-pad.
            pass
        else:
            # Promote to visible chunk_001:
            # Left-silence-pad the loop region so real content sits
            # at the right edge.
            silence_left_frames = chunk_frames - leftover_frames
            assert silence_left_frames > 0  # leftover_sec < chunkPeriodSec by mod

            loop_region = np.concatenate([
                np.zeros((silence_left_frames, n_channels)),
                leading_region
            ], axis=0)

            # Pads:
            # - Pre-pad extends left of the loop region (i.e., further
            #   into "before bar -1 of the song"). All silence — there's
            #   no source content earlier than 0. Existing pre-pad
            #   silence-pad code at prechop.py:226-231 handles this.
            # - Post-pad reads source [first_downbeat_sec,
            #   first_downbeat_sec + post_pad_frames/sr) — real audio,
            #   the start of what's in chunk_002.

            # Emit with loop_start_sec = pad_pre_sec (start of loop
            # region within the WAV), loop_end_sec = pad_pre_sec +
            # chunk_seconds. Same conventions as any other chunk.
            emit_chunk(
                wav_data=concat([pre_pad_silence, loop_region, post_pad_audio]),
                loop_start_sec=pad_pre_sec,
                loop_end_sec=pad_pre_sec + chunk_seconds,
                chunk_index=0,  # or whatever the indexing convention is
                ...
            )
```

Key notes:

- **Bug fix from v1: `leftover_sec = first_downbeat_sec %
  chunkPeriodSec`.** Composes correctly with arbitrary `pre_bars`.
  Whole-chunk-period content is handled by the existing pre-bars auto
  path; this emit only handles the sub-chunk-period remainder.
- **RMS gate, not source-level trim.** No modification to the source
  WAV. Just a decision about whether the visible chunk_001 should
  exist.
- **Pad geometry inherits.** Pre-pad is silence (existing code). Post-
  pad reads real audio at `[first_downbeat_sec, ...)`. No new pad-
  geometry logic.
- **Loop region: full chunk window.** Same as any other chunk.
  `loop_start_sec` and `loop_end_sec` use the same pad-pre-relative
  conventions. The silence inside the loop region is what makes the
  chunk visually align with the bar grid in arrangement view.

### Helper (`tools/m4l_locator_anchor.py`)

Verified to already accept `--track-dir`, `--bpm`, `--first-downbeat`,
and `--manifest-out`. **No changes needed.**

## Behavior matrix

| Scenario | First-downbeat | Pre-pad capacity | RMS gate | Result |
|---|---|---|---|---|
| Believer initial forge | 0.300s | sufficient (1 bar pre-pad ≈ 1.92s) | content present, but `leftover_sec = 0.300 < pad capacity` — see note | Latent in pad (current behavior) |
| Definition initial forge | 3.78s (1-bar chunks) | 1 bar pre-pad ≈ 0.67s | `leftover_sec = 3.78 mod 0.67 ≈ 0.43s`, content present | Visible chunk_001 with 0.43s of intro audio |
| Leading-silence track initial forge | small (whatever beat-this returns) | sufficient | `leftover_sec` is silence | Skip emit (RMS gated). Bar 1 at timeline 0 |
| User ANCH on Believer | new locator-derived value | n/a | content present | Visible chunk_001 with pre-locator audio |
| User ANCH on already-aligned boom-bap | locator on grid → signedOffset ≈ 0 | n/a | n/a | Idempotency threshold: no-op |

**Note on the Believer "latent vs visible" edge case:** the spec as
written would emit a visible chunk_001 for Believer's 0.300s of
pre-downbeat audio, since RMS is non-zero and `leftover_frames > 0`.
That's a behavior change from today (where it stays latent). Two
options:

- **Option X:** Always emit if RMS-gate passes. Believer gets a visible
  chunk_001 with mostly-silence-on-the-left and 0.300s of audio at
  the right edge.
- **Option Y:** Only emit when `leftover_sec` exceeds some fraction of
  `chunkPeriodSec` (e.g., 25%). For Believer's 0.300s vs ~1.92s chunk
  period, that's 16% — below threshold, stays latent. For Definition's
  1.11s vs 2.67s chunk period (4-bar pipeline), that's 41% — above
  threshold, gets promoted.

I'd lean **Option Y** because it preserves today's clean visual for
the common "tiny intro" case while still promoting multi-bar pre-
locator material. The threshold is tunable. Suggested default: 25%.

If Option Y is chosen, the gate becomes:

```python
MIN_LEFTOVER_FRAC = 0.25  # tunable
if leftover_sec / chunkPeriodSec < MIN_LEFTOVER_FRAC:
    # Below visibility threshold — keep latent in pad.
    pass
elif leading_rms < silence_floor_amplitude:
    # RMS gated — skip emit.
    pass
else:
    # Promote to visible chunk_001.
    emit_chunk(...)
```

## What changes vs current Phase 1+2

| Aspect | Phase 1+2 (today) | Revised Phase 3 v2 |
|---|---|---|
| ANCH behavior | Pure JS shift | Re-cut via Python helper (~2s) |
| Source content | Untouched | Untouched |
| Chunk WAVs | Same as before | Regenerated when ANCH is non-no-op |
| Manifest | Unchanged on ANCH | New `first_downbeat_sec` after ANCH |
| Locator semantics | "Locator IS chunk 0 start" | "Locator is on bar N (default 1); nearest bar grid wins" |
| Pre-downbeat audio | Latent in pad-stash, lost beyond 1 bar | Latent for sub-pad, visible chunk_001 for multi-bar |
| Live tempo override | Not consulted | Adopted as new BPM |
| Multi-chunk-period bar errors | Cannot correct | Named-locator mechanism |

## Sanity check: three reference tracks

### Track 1: Definition (BPM half-time, weak downbeats)

**Forge baseline:** `first_downbeat ≈ 3.78s` (beat-this lands on early
intro bar). With a 4-bar chunk pipeline at ~90 BPM, `chunkPeriodSec ≈
10.67s`. `leftover_sec = 3.78 mod 10.67 = 3.78s`, which is 35% of
chunk period — above the 25% threshold. Visible chunk_001 emits
covering the first 3.78s of intro audio.

(With a 1-bar chunk pipeline, `chunkPeriodSec ≈ 2.67s`, `leftover_sec =
3.78 mod 2.67 = 1.11s` = 42% — also above threshold. The pre-bars
auto path emits 1 whole pre-chunk; the new emit case handles the
1.11s remainder.)

**ANCH workflow:** user finds the actual drop at ~22s, drops a locator
there, names it (e.g., `1` if it's bar 1 of the song proper, or some
higher number if bar 1 is actually before the drop). JS computes
`adjustedSourceSec = 22 - (N-1) × 2.67`. The offset-within-chunk math
runs against `oldFirstDownbeat = 3.78`. If the named-locator mechanism
identifies the right bar, `signedOffset` lands on a real correction
(non-zero) and re-anchor produces a manifest with `newFirstDownbeat`
matching the user's musical bar 1.

**Verification step:** run forge → log `first_downbeat`, then ANCH with
a named locator → log `adjustedSourceSec`, `signedOffset`,
`newFirstDownbeat`. Confirm the resulting bar grid matches what the
user hears. If `signedOffset ≈ 0` despite a named locator, the
`oldFirstDownbeat` is whole-chunk-aligned to the song already and we
need to inspect what `(N-1)` was on the locator.

### Track 2: Boom-bap (steady, clean downbeats)

**Forge baseline:** beat-this hits BPM and downbeat with high
confidence. `first_downbeat` near zero or small, depending on track.
Chunks tile cleanly.

**ANCH idempotency:** user drops a locator (named `1`) on any chunk
boundary. `adjustedSourceSec = locatorSourceSec`, `signedOffset ≈ 0`
(within sample-precision jitter). The 5ms idempotency threshold catches
this and ANCH no-ops with a status-log message. **No re-cut runs.**

**Verification step:** confirm the status line shows
`offset < threshold, no-op` and that the chunks on disk are unchanged.
This is the regression test for the snap-to-nearest math: if it ever
fires when it shouldn't, this track catches it.

### Track 3: Tight song with leading silence

**Forge baseline:** beat-this returns `first_downbeat` somewhere
positive (say, 0.5s if there's a half-second of dead air before the
first kick). The leading region in source `[0, 0.5s)` is silence —
RMS below the -60 dBFS threshold.

**Emit gate:** `leftover_sec = 0.5 mod chunkPeriodSec` is positive,
above 25% of a 1-bar chunk period at most BPMs. RMS gate fires —
content is silence, **skip emit**.

**Result:** chunk_001 starts at the song. Bar 1 of the song is at
timeline beat 0. Identical to today's behavior. The leading silence
stays latent in chunk_001's pre-pad (where today's mechanism puts it).

**Verification step:** confirm bar 1 of the song is at timeline beat
0 and there is no leading partial chunk in arrangement view. This is
the existing-behavior regression test.

## Files that change

- **`v0/src/m4l-js/sf_locator_anchor.js`** — `anchor()` rewritten to
  the algorithm above. Adds `_parseBarFromLocatorName` helper. Field
  name updated to `manifest.bars` (not `bars_per_chunk`).
- **`stemforge/prechop.py`** (or wherever the chunk emit loop lives) —
  adds the leading-partial-chunk emit case after the main loop, with
  RMS gate, leftover-fraction gate, and `% chunkPeriodSec` math to
  compose with `pre_bars`.
- **`tests/js_mocks/test_locator_anchor.test.js`** — three existing
  tests assert the old outlet-2 shift contract; rewrite to assert
  outlet-1 shell-call atoms with the new computed `--first-downbeat`
  value. Add tests for: named locator `4`, idempotency threshold,
  Live-tempo-wins.

## Files that don't change

- **`tools/m4l_locator_anchor.py`** — already accepts the args we need.
  Verified.
- **`v0/src/m4l-js/sf_arrangement_loader.js`** — unchanged. Reads
  `loop_start_sec`/`loop_end_sec` from manifest as today.
- **`.amxd` patcher** — anchor outlets and NDJSON parser cases still
  wired from pre-pivot version.
- **Forge-time silence handling** — there isn't any. Nothing to change.

## Open questions for the implementation session

1. **Option X vs Option Y for the visibility threshold.** Spec
   recommends Option Y (25% of chunk period as visibility floor) to
   preserve today's clean visual for sub-bar intros like Believer.
   If you'd rather always promote, switch to Option X.
2. **`MIN_LEFTOVER_FRAC` tuning.** 25% is a starting point. Worth
   running the three reference tracks and seeing if any feel wrong
   visually.
3. **`SILENCE_THRESHOLD_DBFS` tuning.** -60 dBFS is conservative (well
   below any real musical content). Could go to -70 dBFS or -50 dBFS.
   Likely doesn't matter much — most "leading silence" is digital
   silence (-∞ dBFS).
4. **Definition multi-chunk-period diagnosis.** Even with named-locator
   parsing, we don't know yet whether Definition's grid is sub-bar-
   misaligned or whole-chunk-shifted. Run the verification step
   above before assuming the named-locator mechanism is sufficient.
   If the grid is whole-chunk-shifted but on the right *bar phase*,
   the named-locator parsing handles it. If something stranger is
   happening, we may need a different mechanism.
5. **Locator name conventions.** Should ANCH be tolerant of common
   patterns like `bar 4`, `m4`, `4`, `4.0`? The current parser takes
   the first integer in the name, which handles all of these. Worth
   documenting the convention so users know the magic.

## Why this is shippable

The feature decomposes into three orthogonal concerns:

- **Locator-derived `first_downbeat`** computation in JS, with named-
  locator support. Pure math; no I/O beyond reading the manifest and
  Live's tempo.
- **Existing re-anchor flow** in Python (helper + prechop). Already
  shippable today; just needs the new emit case bolted on.
- **New leading-partial-chunk emit** in prechop, gated by RMS and
  leftover-fraction thresholds. Localized addition; doesn't touch
  existing chunk-emit logic.

Each piece has a clear regression test in the three reference tracks.
The feature interacts with the existing pad-stash mechanism by
**replacing it for multi-bar pre-locator audio** (where pad-stash
breaks down) and **leaving it alone for sub-bar pre-downbeat audio**
(where pad-stash works). The RMS gate ensures dead-air leading regions
don't produce unwanted visible silent clips.

Three pieces, three tests, one integration point. That's the shape of
a feature that should be uneventful to ship.
