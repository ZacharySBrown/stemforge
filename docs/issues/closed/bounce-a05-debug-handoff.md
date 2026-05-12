# BOUNCE A05 — start position bug (handoff)

**Captured:** 2026-04-25 ~23:50, mid-debug.
**Branch:** `feat/ep133-song-export`
**Status:** End-to-end pipeline works. Slice math is correct. Wrong LOM property is being read for the bounce-start position. Revert of an over-aggressive seconds_per_beat fix is sitting **uncommitted** in the working tree.

---

## TL;DR

`stemforge` BOUNCE button bounces clips to sidecars on disk. Pipeline is fully wired and producing files. **The bug:** for clip A05 the bounce starts at source-second 7.52s, but the user wants it to start at source-second 3.065s (= clip beat 5.5 = bar 2.2.3 in the clip view). My code reads `clip.start_marker` LOM property (which captured `13.5`), but the user identified this as "the loop start marker, not the content start marker" — meaning I'm reading the wrong LOM field for what the user sees as their playback start.

---

## What's shipped (committed + pushed)

Commits on `feat/ep133-song-export` (newest last):

```
f18ca4f feat(manifest): canonical SampleMeta/BatchManifest schema + forge sidecar emission
c0368ee feat(m4l): BOUNCE button — bounce A/B/C/D clips to sidecars
c082e5c feat(skills): /forge-launch /forge-run /forge-all + feature backlog
0f3921f fix(m4l): BOUNCE button + sf_forge spawn — five bugs caught during UAT
ff9657f fix(clip-export): wrap-around source when loop_end exceeds source length  ← partial fix, see below
3ea35d4 feat(clip-export): wipe stale outputs before re-bouncing into the same dir
4206e19 fix(clip-export): rotate bounce to start_marker, use source-derived seconds  ← linear-warp was WRONG
```

## Uncommitted work in the tree

Reverting the **linear-warp** seconds_per_beat (from commit 4206e19) back to project-tempo math, while keeping the start_marker reading. Tests updated to match. **19 tests passing.**

Files modified, not committed:
- `tools/m4l_export_clips.py` — `slice_and_write_one()` now uses `seconds_per_beat = 60 / src_bpm` again (with `src_bpm = clip_warp_bpm or project_tempo`).
- `tests/test_m4l_export_clips.py` — assertions updated; new `test_start_marker_rotates_loop_within_source`, `test_loop_wraps_around_source_when_loop_extends_past_source`, etc.

**To commit when bug is resolved:** `git diff` will show the revert + test updates. Likely commit message: `fix(clip-export): revert to source-bpm seconds_per_beat (linear-warp was wrong)`.

---

## The active bug

**Symptom:** A05 bounce starts at the wrong section of the source audio. User opened it in QuickTime to verify by ear.

**Spec geometry (captured at click time, latest):**

```json
{
  "track_idx": 3,
  "slot_idx": 5,
  "name": "drums bar 5",
  "file_path": "/Users/zak/stemforge/processed/beep_street/curated/drums/bar_005.wav",
  "warping": true,
  "length_beats": 16,
  "loop_start_beats": 8,
  "loop_end_beats": 24,
  "start_marker_beats": 13.5,        ← what we read
  "signature_numerator": 4,
  "clip_warp_bpm": null,
  "gain": 0.4,
  "suggested_group": "A",
  "suggested_pad": "3"
}
```

**Source:** `/Users/zak/stemforge/processed/beep_street/curated/drums/bar_005.wav` — 17.833s @ 44.1kHz.

**Project tempo:** 107.67 BPM.

**Math (current, working):** `seconds_per_beat = 60 / 107.67 = 0.5572`. So:
- start_marker @ 13.5 beats → source-second **7.52** (42% through source) ← what bounce currently does
- start_marker @ 5.5 beats → source-second **3.065** ← what user wants

**User's screenshot evidence:** Status bar shows `Insert Mark 2.2.3 (Time: 0:03:065)`. Bar 2.2.3 = beat 5.5 in 4/4 ((2-1)*4 + (2-1) + (3-1)*0.25 = 5.5).

**The mismatch:** The LOM `clip.start_marker` returned 13.5 but the user's intended bounce-start is at clip beat 5.5. So either:

- (A) The user moved a marker in the clip view that ISN'T `clip.start_marker` (most likely — Live's terminology is genuinely confusing).
- (B) The LOM property `clip.start_marker` actually represents something other than the play triangle.

User's last message: **"I think that's the loop start marker. Not the content start marker."** — this is the diagnostic clue. The user thinks what I'm reading is the loop-start indicator, not the content-start (play-triangle) marker.

---

## What to do next session

### Step 1 — pin down which LOM property the user is moving

Have the user click BOUNCE again with their current marker setup (the one matching their screenshot — bar 2.2.3 / source 3.065s). Then run:

```bash
jq '.clips[] | select(.suggested_pad == "3")' $(ls -t /tmp/sf_clip_export_*.json | head -1)
```

**Outcomes:**

| `start_marker_beats` value in fresh spec | Diagnosis | Fix |
|---|---|---|
| **5.5** | User had moved start_marker after the previous bounce. Current code is correct — re-test should produce a bounce starting at source 3.065s. | None — just re-bounce. |
| Still **13.5** or some other value | LOM `clip.start_marker` ≠ what the user sees as their playback start. | Read a different LOM property (see Step 2). |
| **5.5** but `loop_start_beats` ALSO changed | User dragged the loop bracket, not the play triangle. | Need to either (a) train the user that loop_start is the rotation pivot, or (b) just always use loop_start as the bounce start (drop start_marker entirely). |

### Step 2 — if start_marker isn't the right property

Possibilities for what to read instead, in order of likelihood:

1. **Just use `clip.loop_start` as the bounce start.** Simpler model: the bounced WAV represents one iteration of the loop region, beginning at loop_start. No "rotation" concept needed — the user just sets the loop boundaries where they want playback to begin. Drop `start_marker_beats` from the spec entirely.

2. **Investigate `clip.position` / `clip.start_time`** — clip position in arrangement, probably not relevant here.

3. **Read all clip LOM properties verbatim and let the user identify the one matching the marker they moved.** Have JS dump every readable property to a debug file:
   ```javascript
   var props = ["start_marker", "end_marker", "loop_start", "loop_end",
                "position", "warp_mode", "length", "warping", "looping"];
   props.forEach(function(p) { log(p + " = " + clip.get(p)); });
   ```
   Then user moves the marker, clicks BOUNCE, and we see which property changed to 5.5.

### Step 3 — once diagnosed, ship the fix

Likely the cleanest fix is **Option 1** (use loop_start, drop start_marker rotation). Removes a confusing UX layer. The user can express any rotation by moving loop_start; no need for a separate "play triangle" concept.

If we go that route:
- Remove `start_marker_beats` from `_readClipSpec()` in `sf_clip_export.js`.
- In helper, set `start_seconds = loop_start_beats * seconds_per_beat`.
- Loop bounce is `source[loop_start_seconds .. loop_end_seconds]` with wrap.
- Update `test_start_marker_rotates_loop_within_source` (rename/repurpose to "loop start defines bounce start").

### Step 4 — verify A05 plays correctly on EP-133

After the fix:
1. User clicks BOUNCE.
2. Open the new `~/stemforge/exports/<ts>/A05.wav` in QuickTime — should sound like Live's playback starting at the user-moved marker.
3. `ppak-load-from-manifest ~/stemforge/exports/<ts>/.manifest.json --groups A=A --start-slot 300` to load.
4. EP-133 plays pad `3` (= slot 305, was A05) — should match what Live plays.

---

## Hard-won facts (don't re-learn these)

These are the gotchas burned in over the past few hours of debug. Worth memory entries.

### shell.mxo (Bill Orcutt / Jeremy Bernstein v8.0.0)

- **No `spawn` verb.** `outlet(N, "spawn", cmd)` makes shell try to exec a binary named `spawn`. Send command via multi-atom: `outlet(N, BIN, ARG1, ARG2, ...)` — selector becomes argv[0], rest become argv[1..n].
- **No `kill` verb either.** Use `pkill`.
- Same bug in `sf_forge.js` (latent for months — only avoided because recent forges used manifest-source mode that skips spawn). Both fixed in commit `0f3921f`.

### Live LOM `clip.start_marker` semantics

- Per Ableton docs: "position of the start marker in beats". Sounds like the play triangle but **the user disputes this** — they identify it as the loop-start marker.
- TBD next session: read multiple clip properties and have the user identify the one that matches their visual mental model.

### Slice timing math

- **Right:** `seconds_per_beat = 60 / clip.warp_marker_bpm` (or `60 / project_tempo` when warp_marker_bpm is null).
- **Wrong (don't go back to this):** `seconds_per_beat = source_duration / length_beats` (linear warp from source duration). Sounds plausible but produces source positions that are way off — the source's natural BPM is the canonical reference, not its duration.

### Bar.beat.sixteenth notation

- 1-indexed. Bar 2.2.3 in 4/4 = (2-1)*4 + (2-1) + (3-1)*0.25 = **5.5 beats**.
- Time at project tempo P: `beats * 60 / P` seconds.

### M4L → Python helper plumbing

- JS writes spec to `/tmp/sf_clip_export_<ts>.json` (NOT into the export dir, which Max's File() can't reliably mkdir).
- Python helper does `mkdir -p` of `export_dir` from inside the spec.
- JS PYTHON_BIN points directly at the repo venv: `/Users/zak/zacharysbrown/stemforge/.venv/bin/python3`. System python lacks `soundfile` and `pydantic`.

### Re-bounce hygiene

- Helper wipes prior outputs in export_dir at start (`.manifest.json`, `.manifest_*.json`, `[ABCD][0-9][0-9].wav`) before writing fresh ones. Conservative glob — leaves user files alone.

---

## Other things in flight (not blocked on A05 fix)

- **Multi-tempo experiment.** User asked to verify per-clip BPM tracking with clips from songs at different tempos. Steps written in conversation. Not yet run — defer until A05 is correct.
- **Issue #33** — V2 BOUNCE with `track.freeze()` for warp + effects baking. Filed on GitHub.
- **`docs/issues/rename-repo.md`** — captured locally, deferred.
- **VST extraction (backlog item #4)** — pending Decapitator native-swap decision. Untouched today.
- **Forge skills** (`/forge-run`, `/forge-launch`, `/forge-all`) — shipped, untested in fresh sessions.

---

## Files for next session to read first

1. **This doc.**
2. `docs/feature-backlog.md` — overall picture.
3. `tools/m4l_export_clips.py` — current slice math (uncommitted).
4. `v0/src/m4l-package/StemForge/javascript/sf_clip_export.js` — JS that reads LOM (search for `_readClipSpec`).
5. `tests/test_m4l_export_clips.py` — 19 passing tests, includes the start_marker rotation cases.

## Quick context-recovery commands

```bash
# Where am I?
git status -s
git log --oneline -10

# What does the latest spec say about A05?
LATEST=$(ls -t /tmp/sf_clip_export_*.json | head -1)
jq '.clips[] | select(.suggested_pad == "3")' $LATEST

# Open the latest A05 bounce + source side-by-side
LATEST_DIR=$(ls -t ~/stemforge/exports/ | head -1)
open ~/stemforge/exports/$LATEST_DIR/A05.wav
open /Users/zak/stemforge/processed/beep_street/curated/drums/bar_005.wav

# Re-run helper against a spec without re-clicking in Live
/Users/zak/zacharysbrown/stemforge/.venv/bin/python3 \
  /Users/zak/zacharysbrown/stemforge/tools/m4l_export_clips.py \
  $LATEST

# Tail the M4L log live
tail -f ~/stemforge/logs/sf_debug.log | grep sf_clip_export
```
