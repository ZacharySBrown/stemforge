# EP-133 Loading & Beat-Matching — Final Summary

Status: **WORKING.** 2026-05-11.

This doc replaces the in-progress debrief that preceded it. Five distinct
bugs in the bounce→`.ppak` pipeline made the breaks-n-beats deck fail in
weird, overlapping ways. All five are now fixed in code and committed
along this path:

```
Live (M4L bounce)
  → manifest.json (with per-clip start/end at session tempo)
  → deck-from-manifest → deck.yaml
  → build-deck → kit_synthesizer → ppak_writer → .ppak
  → Sample Tool import → EP-133 device
```

## The five bugs (in the order they cascaded)

### 1. `clip.call("crop")` renders at warp_bpm, NOT session BPM

The single biggest false assumption. The M4L loader's load-bearing comment
said *"post-crop, warp_bpm == project_bpm"*. **It doesn't.** Empirically:
each clip's cropped AIFF is rendered at the clip's *own* `warp_bpm`. In a
session with clips from 4 different songs warped at 89.89 / 85.00 / 104.96
/ 98.19 BPM, the bounced audio comes out at those four rates — not at the
session tempo of 94.15.

**Fix:** in `kit_synthesizer.py`, infer each clip's source BPM from the
source file's *actual* duration by snapping to integer-bar candidates and
picking the one whose resulting BPM is closest to `project_bpm`. Use that
as `sound.bpm` in both the WAV's TNGE metadata AND the pad-record's
binary BPM at bytes 12–15.

**File:** `stemforge/exporters/ep133/kit_synthesizer.py`:`_infer_source_bpm`
+ rewired call site in the per-pad loop.

### 2. AIFF→WAV converter truncating long sources

The pipeline was emitting `slot_slices = (start_offset_sec, end_offset_sec)`
based on the manifest's per-clip slice. Those values are computed in
`_sessionTrackEntryFromClip` (M4L) at the session tempo — but the cropped
audio is at warp_bpm. So a 1-bar oll clip (2.82s at 85 BPM source) got
truncated to 2.44s (which is 1 bar at the session 98.19 BPM Live thought
it had).

**Fix:** stop emitting `slot_slices` in `kit_synthesizer.py` for the kit
workflow. The bounced WAVs already represent the loop region the user
intended; further slicing is incorrect. (If a future flow needs explicit
slicing, gate it behind a deck.yaml flag rather than blanket-trusting the
manifest.)

**File:** same — comment block at the spot where `slot_slices[sample_slot]`
used to be set.

### 3. `pak_type` default was `"user"`

`META_DEFAULTS["pak_type"]` in `ppak_writer.py` was `"user"` — the type
for full-device-backup paks. Sample Tool's project-import path refuses
to load `pak_type: "user"` (you'd need to use the "Restore" workflow).
The bug was masked when a real reference template was supplied (because
those carry `"project"` and override the default), but synthesizing without
a template left the wrong value in place.

**Fix:** changed default to `"project"`.

**File:** `stemforge/exporters/ep133/ppak_writer.py:META_DEFAULTS`.

### 4. `patterns/d05` duplicate tar entry

The writer unconditionally adds an empty 4-byte "song-mode marker" at
`patterns/d05` whenever `spec.song_positions` is set. For decks with 5+
D-group pads, the kit synthesizer emits a real 12-byte pattern at d05 too
— same filename, two TAR entries. Sample Tool's import bails partway
through when it hits the duplicate ("loaded N of M then aborted").

**Fix:** skip the marker emission if a real `d05` pattern is already
present.

**File:** `stemforge/exporters/ep133/ppak_writer.py:478` block.

### 5. Per-sample 20s cap (Sample Tool / device limit)

Verified empirically: a 21.36s sample broke the import (loaded ~10 of 21
pads then aborted); an 11.30s sample loaded clean. The device's
documented per-sample ceiling is ~20s.

**Fix:** in the kit synthesizer's per-pad loop, check
`_read_source_duration_sec(resolved.path)`; if > 20.0s, emit a UserWarning
and `continue` (skip the pad — don't truncate, which would silently drop
the tail). User can shorten the loop region in Live or split into shorter
clips.

**File:** `stemforge/exporters/ep133/kit_synthesizer.py:_MAX_SAMPLE_SEC` +
the duration gate at the top of the per-pad loop.

## Bonus: bar-inference tuning

The duration→BPM inference uses candidate bar counts. Settled on
`(0.25, 0.5, 1, 2, 3, 4, 8)`:

- **Include 3:** real musical phrases (3-bar turnarounds, intro tags,
  textures) — er textures in this deck are 3 bars at 98.19 BPM and need it.
- **Exclude 5/6/7:** vanishingly rare and they steal scoring wins from
  the right 4-bar interpretation. An 11.29s 4-bar oll texture at 85 BPM
  was getting misclassified as 5-bar at 106 BPM when 5 was a candidate.

The scoring picks the candidate whose resulting BPM is closest to
`project_bpm`, which gives clips from the same session a sensible tempo
prior.

## Validated paks built today

| File | Size | Purpose | Loaded? | Beat-matched? |
|------|------|---------|---------|---------------|
| `/tmp/breaks_n_beats_6DRUMS_BARMODE.ppak` | 1.3 MB | first known-good 6-drum minimal pak | ✓ | (early) ✗ |
| `~/Desktop/breaks_n_beats_DRUMS_v2.ppak` | 2.5 MB | 12 drums, manually corrected BPMs | ✓ | ✓ |
| `~/Desktop/TEMPO_TEST.ppak` | 257 KB | 6 synthetic clicks at known BPMs | ✓ | ✓ |
| `~/Desktop/breaks_n_beats_KIT.ppak` | 8.0 MB | **pipeline-built, 12 drums + 9 textures** | ✓ | ✓ |

## Hand-off commands (for future you)

```bash
# 1. Live: open the project, save it (Cmd+S).
# 2. Fire bounce via M4L:
uv run sf-remote fire forge bounceTracks

# 3. After "Bounce complete" in ~/stemforge/logs/sf_debug.log:
uv run stemforge deck-from-manifest \
    /Users/zak/stemforge/decks/breaks_n_beats_ep133/curated/manifest.json \
    --out /Users/zak/stemforge/decks/breaks_n_beats_ep133/curated/deck.yaml

# 4. Build the .ppak:
uv run stemforge build-deck \
    /Users/zak/stemforge/decks/breaks_n_beats_ep133/curated/deck.yaml \
    --out ~/Desktop/<name>.ppak

# 5. Load in TE Sample Tool (Chrome) on the EP-133.
```

## What's NOT fixed yet

- **Pytest suite hasn't been re-run** since the kit_synthesizer +
  deck_plan + ppak_writer changes. Should run before next deploy.
- **`read_project_file` off-by-one bug** in `project_reader.py` is still
  there (`frame[9:-1]` should be `frame[10:-1]`). Doesn't affect this
  workflow because we never read project tars back, but if someone tries
  to debug pad-binary state via SysEx GET, fix that first.
- **M4L manifest still writes wrong `end_offset_sec`** values (computed
  at session tempo). The pipeline ignores them now, but they're misleading
  if anyone tries to read them as truth. If we ever need explicit slicing
  again, fix at the source (M4L) — capture `warp_bpm` pre-crop and convert
  beats↔seconds using each clip's actual rate.
- **Group A/B vocal-verse workflow** hasn't been tested end-to-end through
  the new pipeline. They were excluded from this kit. Long verse vocals
  exceed the 20s cap → will get skipped with the warning. If you want
  them as pads, split into ≤20s chunks or accept the skip.

## Memory notes added

- `feedback_clip_crop_renders_at_warp_bpm.md` — the core lesson.
- `feedback_ep133_per_sample_cap_20s.md` (new, below).
- `feedback_ppak_writer_pak_type_default.md` (new, below).
- `feedback_ppak_writer_d05_marker_collision.md` (new, below).
- `feedback_bar_inference_candidates.md` (new, below).
