# Session Handoff: Audio Quality Validation via Gemini 2.5 Pro

**Date:** 2026-04-19
**Branch:** `feat/curation-engine-v2`
**Goal:** Validate curated audio output quality using multimodal AI

---

## Context

StemForge's curation engine extracts bar loops and one-shot transients from
separated stems. The output quality of one-shots is currently poor — hits are
too long, classifications are wrong (bass notes labeled as kicks, noise labeled
as hats), and many samples are not musically useful.

A quality spec has been written (`specs/curation-quality-spec.md`) that defines
pass/fail criteria for every output type. A Gemini 2.5 Pro validation script
has been created but needs testing and refinement.

---

## What's Done

### Quality Spec
`specs/curation-quality-spec.md` — comprehensive rubric:
- Bar loop criteria: duration, musical content, RMS, boundaries, loopability
- One-shot criteria: single event, duration per category, classification accuracy
- Per-stem expectations for drums/bass/vocals/other
- Validation prompts for Gemini (per-loop and per-oneshot)
- Scoring: 1-5 scale, minimum average 3.0 to pass

### Validation Script
`tools/validate_audio.py` — sends curated WAVs to Gemini 2.5 Pro:
- Reads curated `manifest.json`
- For each WAV: uploads to Gemini, sends quality prompt, parses JSON response
- Generates per-stem scores and overall report
- Writes `quality_report.json` alongside manifest

### API Setup
- `GEMINI_API_KEY` is in `.env` at repo root
- `google-genai` SDK installed in the venv
- Model: `gemini-2.5-pro-preview-05-06`

### Test Data Available
Two tracks have been curated and are ready for validation:

1. **The Champ** (funk, 112 BPM)
   - `~/stemforge/processed/the_champ_original_version/curated/manifest.json`
   - Known issues: drum one-shots too long, kick classification wrong
   
2. **Can I Kick It** (hip hop, 98 BPM)
   - `~/stemforge/processed/can_i_kick_it/curated/manifest.json`
   - Currently in loops-only mode (no one-shots to validate)
   - Re-run with `stems` mode to get one-shots for validation

---

## What to Do

### 1. Test the Validation Script

```bash
# Dry run first
uv run python tools/validate_audio.py \
  ~/stemforge/processed/the_champ_original_version/curated/manifest.json \
  --dry-run

# Validate drums only (fastest, 4 samples)
uv run python tools/validate_audio.py \
  ~/stemforge/processed/the_champ_original_version/curated/manifest.json \
  --stems drums --max-per-stem 4

# Full validation (all stems, slower)
uv run python tools/validate_audio.py \
  ~/stemforge/processed/the_champ_original_version/curated/manifest.json \
  --max-per-stem 4
```

### 2. Review Gemini Responses

Check if Gemini's assessments match the quality issues we know about:
- Drum one-shots rated 1-2 (too long, wrong classification)
- Bar loops rated 3-5 (these are generally good)
- Silent/near-silent bars flagged

### 3. Tune the Prompts if Needed

The prompts are in `tools/validate_audio.py`. Key areas:
- Gemini may need more specific audio terminology
- JSON response format may need adjustment if Gemini doesn't follow it
- May need to add "think step by step" or chain-of-thought prompting

### 4. Generate Reports for Both Tracks

```bash
# Re-run The Champ in stems mode (with one-shots)
# First, update curation.yaml: change mode from loops-only to stems
# Then:
uv run python v0/src/stemforge_curate_bars.py \
  --stems-dir ~/stemforge/processed/the_champ_original_version \
  --n-bars 16 --json-events \
  --curation pipelines/curation.yaml

# Validate
uv run python tools/validate_audio.py \
  ~/stemforge/processed/the_champ_original_version/curated/manifest.json
```

### 5. Use Reports to Tune Extraction Parameters

Based on Gemini's feedback:
- Tighten one-shot duration windows in `stemforge/oneshot.py` (STEM_PARAMS)
- Raise RMS floors for silent bar rejection
- Add onset-count validation (reject one-shots with >1 transient)
- Improve drum classifier boundaries in `stemforge/drum_classifier.py`

---

## Key Files

| File | Purpose |
|------|---------|
| `specs/curation-quality-spec.md` | Quality rubric — pass/fail criteria |
| `tools/validate_audio.py` | Gemini validation script |
| `stemforge/oneshot.py` | One-shot extraction (tune STEM_PARAMS) |
| `stemforge/drum_classifier.py` | Drum classification (tune thresholds) |
| `stemforge/curator.py` | Diversity selection (tune weights, RMS floors) |
| `pipelines/curation.yaml` | Per-stem config (mode, thresholds, counts) |
| `.env` | GEMINI_API_KEY |

## Known Issues

1. **One-shot durations too long**: max_window_ms in STEM_PARAMS needs tightening.
   Drums should cap at 300ms, not 500ms.
2. **Kick classification wrong**: Bass stem bleed causes bass notes to be classified
   as kicks. `extract_kicks_from_bass()` needs stricter filtering.
3. **Silent bars selected**: RMS floor too low for vocals/other. Bars from
   instrumental sections (no vocal content) pass through.
4. **Gemini response parsing**: The script expects JSON responses — Gemini may
   wrap in markdown or add commentary. Parsing needs to be robust.

## Permissions

The validation script only reads files and calls the Gemini API. No file
modifications, no git operations.
