# Session Handoff: StemForge Launchpad MVP

**Date:** 2026-04-18
**Branch:** `fix/v0.0.1-beta-release` (PR #24 merged to main; this branch has the v0.0.1 fixes)
**Goal:** One song → 16 curated bars per stem × 4 stems = 64 pads on a Novation Launchpad Pro

---

## What's done

### v0.0.1-beta is shipped and working
- M4L device splits stems inside Ableton via `[shell]` → `stemforge-native`
- NDJSON parser handles Max's JSON mangling (splits on `" 0 "` separator)
- CoreML EP active, 4.54s warm per 10s segment
- `.pkg` installer bundles everything (409 MB)
- Max Package at `~/Documents/Max 9/Packages/StemForge/` with `shell.mxo` + JS files
- Version 0.0.1 everywhere, CoreML cache configured, dylib symlink in postinstall

### Bar curation script created (Step 1 — NEEDS TESTING)
- **File:** `v0/src/stemforge_curate_bars.py`
- Takes stems output from `stemforge-native split` and runs bar slicing + diversity curation
- Reuses `stemforge/slicer.py` (slice_at_bars) + `stemforge/curator.py` (curate)
- Emits NDJSON events on stdout for device integration
- **Bug found + fixed:** `slice_at_bars()` creates `{stem}_bars/` inside `output_dir`, so passing `stems_dir/{stem}_bars` as output_dir caused double-nesting. Fix: pass `stems_dir` directly.
- **Needs retest:** clean up old bar dirs and rerun:

```bash
rm -rf ~/stemforge/processed/the_champ_original_version/*_bars \
       ~/stemforge/processed/the_champ_original_version/curated

uv run python v0/src/stemforge_curate_bars.py \
  --stems-dir ~/stemforge/processed/the_champ_original_version \
  --n-bars 16 --json-events
```

Expected: NDJSON events showing slicing (72 drum bars, etc.) → curating (16 selected) → curated manifest written.

---

## What's left (Steps 2-5)

### Step 2: Update device builder — two modes (~45 min)
**File:** `v0/src/maxpat-builder/builder.py`

Add two modes to the device:

**Mode A — FORGE (extend existing):**
1. Browse → `stemforge-native split` (already works)
2. On split `complete` event → auto-trigger second `[shell]`: `uv run python v0/src/stemforge_curate_bars.py --stems-dir <output_dir> --n-bars 16 --json-events`
3. On curate `curated` event → trigger loader with manifest path

**Mode B — LOAD SESSION (new):**
1. New "Load" `[textbutton]` in device UI
2. `[opendialog]` → browse to a `stems.json` or `manifest.json`
3. Pass manifest path directly to loader (no split, no curate)

Key wiring: the `complete` event from split includes `output_dir` — extract it and pass to the curate command's `--stems-dir`.

### Step 3: Extend loader for Launchpad mapping (~60 min)
**File:** `v0/src/m4l-js/stemforge_loader.v0.js`

New function: `loadCuratedBars(manifestPath)`

For each of the 4 stems, create an **audio track** with **16 clip slots**, one curated bar per slot:
- Track: `[SF] Drums Bars` (red), `[SF] Bass Bars` (blue), `[SF] Vocals Bars` (orange), `[SF] Other Bars` (green)
- Each clip slot: `create_audio_clip(bar_wav_path)`, set looping=1, warp_mode per stem type
- Clip slots map to Launchpad rows:
  - Drums: rows 7-8 (16 pads)
  - Bass: rows 5-6 (16 pads)
  - Vocals: rows 3-4 (16 pads)
  - Other: rows 1-2 (16 pads)

The curated manifest format (from `stemforge_curate_bars.py`):
```json
{
  "track": "the_champ_original_version",
  "bpm": 112.35,
  "stems": {
    "drums": [{"position": 1, "source_bar_index": 5, "file": "/abs/path/bar_001.wav"}, ...],
    "bass": [...],
    "vocals": [...],
    "other": [...]
  }
}
```

### Step 4: Launchpad template setup (~20 min)
For tonight: manual setup in Ableton (not programmatic):
1. Preferences → MIDI → Launchpad Pro as Control Surface
2. 4 audio tracks pre-named for stem mapping
3. Session view clip launch mapped to Launchpad grid
4. Save as template

### Step 5: Test end-to-end (~30 min)
1. Verify bar curation script produces 16 bars × 4 stems
2. Test in standalone Max debug harness (fast iteration)
3. Test in Ableton: FORGE → split → curate → tracks appear → Launchpad plays
4. Test Load Session: browse manifest → tracks appear without re-splitting

---

## Parallelism opportunity

Steps 2, 3, and 4 are independent — they touch different files:
- Step 2: `builder.py` (patcher generation)
- Step 3: `stemforge_loader.v0.js` (LOM track creation)
- Step 4: documentation only

Can be run as 3 parallel agents once Step 1 is validated.

---

## Key files

| File | Status | Purpose |
|------|--------|---------|
| `v0/src/stemforge_curate_bars.py` | Created, needs retest | Bar slice + curate bridge |
| `v0/src/maxpat-builder/builder.py` | Needs modification | Add Load Session + two-phase forge |
| `v0/src/m4l-js/stemforge_loader.v0.js` | Needs modification | Add loadCuratedBars() |
| `v0/src/m4l-js/stemforge_ndjson_parser.v0.js` | May need modification | Handle `curated` event type |
| `v0/interfaces/device.yaml` | Needs modification | Add Load button |
| `v0/build/stemforge-debug.maxpat` | Needs modification | Add curate + load test paths |
| `stemforge/slicer.py` | Existing, reused | slice_at_bars() |
| `stemforge/curator.py` | Existing, reused | curate() |

## Specs to read

| File | What it covers |
|------|---------------|
| `specs/StemForge_Suite_Spec.docx` | Full product vision — 4-device suite, Launchpad 8×8 layout, DJ Mode |
| `specs/stemforge_ui_spec.html` | Detailed UI spec — v0→v3 progression, state machine, session choreography |
| `batch/StemForge_Batch_Pipeline_Spec.docx` | Modal batch processing — same output format as device |
| `docs/m4l-device-status.md` | Container format, node.script findings |
| `docs/device_packaging_research.md` | Max Package pattern, @embed analysis |

## Approved implementation plan

Full plan at `~/.claude/plans/snappy-plotting-kite.md` — covers tonight's MVP (Phase 1) and the full product vision roadmap (Phases 2-5: v1 waveform, v2 mixer, v3 pad grid, v4 full Launchpad, v5 DJ Mode).

## Permissions

Settings at `.claude/settings.json` include:
- `Bash(rm -rf ~/stemforge/processed/*/curated)` — clean curated output
- `Bash(rm -rf ~/stemforge/processed/*/*_bars)` — clean bar slices
- Full git, gh, build, and file operation permissions already configured

## First thing to do in new session

```bash
# 1. Clean up failed bar dirs from previous test
rm -rf ~/stemforge/processed/the_champ_original_version/*_bars \
       ~/stemforge/processed/the_champ_original_version/curated

# 2. Test the curate script
uv run python v0/src/stemforge_curate_bars.py \
  --stems-dir ~/stemforge/processed/the_champ_original_version \
  --n-bars 16 --json-events

# 3. If it works → launch Steps 2-4 in parallel
```
