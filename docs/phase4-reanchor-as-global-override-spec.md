# Phase 4: Re-Anchor as Global System Alignment Override

**Status:** Spec only — captures the post-Phase-3 design discussion on
making re-anchor the single source of truth that all downstream consumers
honor.

**Context:** Phase 3 made ANCH a real source-level re-cut that updates
`prechop_manifest.json` + writes a `tempo.source = "user-override"` marker
into `stems.json`. But the curation pipeline
(`v0/src/stemforge_curate_bars.py`) re-detects BPM and downbeats from
scratch every time it runs — it ignores the user's override. Same gap
exists for any future tool that reads `*_bars/`, `*_phrases/`, or
`curated/`.

## TL;DR

Make re-anchor a global alignment override:

1. The `tempo.source = "user-override"` flag in `stems.json` becomes a
   contract. Any consumer that detects tempo SHOULD instead trust the
   manifest when this flag is present.
2. `stemforge re-anchor` extends to also re-slice `*_bars/` (and
   `*_phrases/` if the pipeline produced them), so anything that reads
   bar slices automatically sees the updated grid.
3. A new `stemforge curate <track_dir>` CLI command runs curation only,
   reusing existing stems + the manifest's tempo. Faster than a full
   `forge` (no Demucs).
4. The M4L device gains a "Load Curated" button that lazily re-runs
   curation when stale (i.e., when `prechop_manifest.json` is newer
   than `curated/`). The user gets seamless workflow: forge → load
   arrangement → ANCH → load curated, never typing in a terminal.

The four steps land independently. Each one is independently shippable
and adds value on its own. Build in order; stop at whichever step the
workflow becomes acceptable.

## User-facing workflow after Phase 4

```
stemforge split track.wav --pipeline arrangement       # 1. forge
                                                        # 2. load arrangement in Live (M4L)
                                                        # 3. press ANCH if grid is off
                                                        #    → re-anchor regenerates prechop + bars
                                                        # 4. press "Load Curated" in M4L
                                                        #    → device sees curated/ is stale
                                                        #    → runs `stemforge curate` (~30s)
                                                        #    → loads fresh clips
```

No terminal needed for the iteration loop. ANCH is the global alignment
override; everything downstream picks it up.

## Today's gap (verified from code)

`stemforge_curate_bars.py:374`:

```python
# Always get librosa beats as baseline (fast, reliable on drums)
bpm, beat_times = detect_bpm_and_beats(bpm_source)

try:
    from stemforge.beat_detect import detect_beats_and_downbeats
    bt_source = source_audio or bpm_source
    bt_bpm, bt_beats, bt_downbeats = detect_beats_and_downbeats(bt_source)
    # ...maybe override with beat-this if its bar CV is better...
```

The curation pipeline runs its own detection, ignoring `stems.json`'s
`tempo.first_downbeat_sec` and `bpm` fields. If you re-anchored to
`first_downbeat = 8.934s`, curation might re-detect `3.78s` and slice
bars at the wrong positions.

`stemforge re-anchor` (`stemforge/cli.py:497+`) only regenerates
`*_prechop/` and updates `stems.json`'s tempo block. `*_bars/` and
`*_phrases/` are untouched. Any tool reading them gets stale grids.

## Step 1: `stemforge_curate_bars.py` honors `user-override`

**Goal:** When `stems.json` indicates the user manually anchored, skip
detection and use the override values directly.

### Behavior

At the top of `_run_pipeline()` in `stemforge_curate_bars.py`, before
the existing detection block at line 374:

```python
# Phase-4: honor user override from stems.json (set by re-anchor).
# Skips re-detection so the bar grid reflects the user's manual anchor.
override_bpm = None
override_first_downbeat = None
if source_manifest.exists():
    sj = json.loads(source_manifest.read_text())
    if sj.get("tempo", {}).get("source") == "user-override":
        override_bpm = float(sj["bpm"])
        override_first_downbeat = float(sj["tempo"]["first_downbeat_sec"])

if override_bpm is not None:
    # Synthesize beat grid at the override tempo, anchored on first_downbeat.
    duration = sf.info(str(bpm_source)).duration
    beat_times = np.arange(override_first_downbeat, duration, 60.0 / override_bpm)
    bpm = override_bpm
    if json_events:
        emit({
            "event": "progress",
            "phase": "alignment",
            "pct": 2,
            "message": (
                f"using user-override tempo: bpm={bpm:.2f} "
                f"first_downbeat={override_first_downbeat:.4f}s"
            ),
        })
else:
    # Existing detection path (librosa baseline + optional beat-this refine).
    bpm, beat_times = detect_bpm_and_beats(bpm_source)
    # ... rest of current detection logic
```

### Edge cases

- `tempo` field missing or `source` is anything other than `"user-override"`
  → fall through to detection (current behavior).
- `bpm` or `first_downbeat_sec` invalid (negative, NaN, missing) → log a
  warning, fall through to detection.
- The `bpm_source` stem doesn't exist on disk → fall through (existing
  code already handles this).

### Tests

Add to `tests/test_curate_bars.py` (create if missing):

- `test_user_override_skips_detection`: build a fake stems.json with
  `tempo.source = "user-override"`, run a tiny `_run_pipeline`,
  confirm the resulting bar slices are at multiples of `barSeconds` from
  the override `first_downbeat`.
- `test_no_override_falls_through_to_detection`: same but with
  `tempo.source = "beat-this:mix"`. Confirm detection runs.
- `test_invalid_override_falls_through`: `bpm = -1.0` → detection runs.

### Files that change

- `v0/src/stemforge_curate_bars.py` — add the override-honoring block
  at the top of `_run_pipeline`.
- `tests/test_curate_bars.py` — new file or extend existing.

### Files that don't change

- `stemforge/curator.py` — works on bar slices it's handed; doesn't care
  where they came from.
- `stems.json` schema — already has `tempo.source` field.
- `stemforge/cli.py` — no CLI surface change yet.

## Step 2: `stemforge curate <track_dir>` CLI wrapper

**Goal:** Let the user run curation only (no Demucs) from a clean CLI
command.

### Command surface

```
stemforge curate <track_dir> [--pipeline PATH] [--strategy NAME] [--n-bars N]
                            [--re-detect-tempo] [--json-events]
```

- `track_dir`: existing processed dir (must contain `stems.json` +
  per-stem WAVs).
- `--pipeline`: curation YAML config. Default: `pipelines/curation_nopad.yaml`.
- `--strategy`, `--n-bars`: passthroughs to `stemforge_curate_bars.py`.
- `--re-detect-tempo`: force tempo re-detection even if `stems.json` has
  `user-override`. Escape hatch.
- `--json-events`: NDJSON progress events on stdout (for M4L integration).

### Behavior

1. Validate `track_dir` exists and contains `stems.json` + at least one
   stem WAV.
2. If `--pipeline` not provided, default to `pipelines/curation_nopad.yaml`
   (same default as the existing `forge --curation` flow uses).
3. Shell out to `python v0/src/stemforge_curate_bars.py --stems-dir
   <track_dir> --pipeline <pipeline> [other flags]`.
4. Forward NDJSON events to stdout (for piping to M4L's NDJSON parser).
5. Return non-zero exit if curation fails.

### Implementation

In `stemforge/cli.py`:

```python
@cli.command("curate")
@click.argument("track_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--pipeline", "pipeline_path", type=click.Path(exists=True, path_type=Path),
              default=None, help="Curation YAML config. "
              "Default: pipelines/curation_nopad.yaml")
@click.option("--strategy", default=None, help="Curation strategy.")
@click.option("--n-bars", type=int, default=None, help="N curated bars per stem.")
@click.option("--re-detect-tempo", is_flag=True,
              help="Force tempo detection even if stems.json has user-override.")
@click.option("--json-events", is_flag=True, help="Emit NDJSON progress events.")
def curate(track_dir, pipeline_path, strategy, n_bars, re_detect_tempo, json_events):
    """
    Run curation against an existing processed track dir, reusing its
    stems and (by default) honoring any user-override tempo from
    re-anchor. Faster than `forge` because no Demucs re-run.
    """
    # ... validation, defaults, subprocess.run() to curate_bars.py
```

### Tests

- `test_curate_command_validates_track_dir`: missing stems.json → error.
- `test_curate_command_default_pipeline`: no `--pipeline` arg → uses
  `curation_nopad.yaml`.
- `test_curate_command_passthrough_to_bars_script`: mock subprocess,
  assert correct args.

### Files that change

- `stemforge/cli.py` — new `curate` command.
- `tests/test_cli_curate.py` — new tests.

### Files that don't change

- `v0/src/stemforge_curate_bars.py` — already invokable with the args
  the wrapper uses (Step 1 makes the override behavior automatic).

## Step 3: Re-anchor extends to `*_bars/` (and `*_phrases/` if present)

**Goal:** When the user re-anchors, ALL downstream bar grids get
regenerated synchronously, so `*_bars/` is never stale relative to
`prechop_manifest.json`.

### Behavior

In `stemforge/cli.py`'s `re_anchor` command, after `run_post_split_steps`
returns:

1. Compute `beat_times = np.arange(first_downbeat, duration, 60/bpm)`
   (same convention used by `stemforge split --bpm X --first-downbeat Y`).
2. For each stem, wipe `<track_dir>/<stem>_bars/` if it exists.
3. Re-slice via `stemforge.slicer.slice_at_bars` with the new
   `beat_times`.
4. If `<track_dir>/<stem>_phrases/` exists, re-group via
   `group_bars_into_phrases` with the new bars.
5. Update mtimes so downstream consumers can detect freshness.

### CLI flag

Add `--no-bars` to `stemforge re-anchor` for users who explicitly don't
want bar regeneration (rare; default is to do it).

### Behavior matrix

| Existing dirs | re-anchor regenerates |
|---|---|
| `*_prechop/` only | `*_prechop/` (current) |
| `*_prechop/` + `*_bars/` | both (new) |
| `*_prechop/` + `*_bars/` + `*_phrases/` | all three (new) |
| `*_prechop/` + `curated/` | `*_prechop/` only; `curated/` left stale |

The `curated/` regeneration is intentionally NOT in this step — that's
expensive and lazy-trigger is the right pattern (Step 4).

### Tests

- `test_re_anchor_regenerates_bars_when_present`: forge a track, run
  re-anchor with new first_downbeat, assert `*_bars/` files have new
  mtimes and slice at the new grid.
- `test_re_anchor_skips_bars_when_absent`: forge with no bar slicing,
  re-anchor, assert no `*_bars/` is created.
- `test_re_anchor_with_no_bars_flag_skips_regeneration`: assert
  `--no-bars` opt-out works.
- `test_re_anchor_marks_curated_stale_when_present`: assert that after
  re-anchor, `curated/` mtime is older than `prechop_manifest.json`
  mtime (= the stale signal Step 4 reads).

### Files that change

- `stemforge/cli.py` — `re_anchor` command body.
- `stemforge/slicer.py` — possibly extract a helper for bar-slicing
  given pre-computed `beat_times`.
- `tests/test_re_anchor.py` — new file or extend existing.

### Files that don't change

- `stems.json` schema — already records the override tempo.
- `prechop.py` — re-anchor's prechop call is unchanged.

## Step 4: M4L "Load Curated" with stale-detect + lazy curate

**Goal:** Press one button in the M4L device; if curated clips are
stale, re-run curation transparently, then load them. No terminal.

### UI surface

A new button in the device next to the existing arrangement-load
button:

- **`LOAD ARR`** (existing): loads `prechop_manifest.json` chunks into
  arrangement view.
- **`LOAD CURATED`** (new): loads curated clips. If curation is stale or
  missing, runs `stemforge curate` first.

### Stale-detect logic

A `curated/` directory is "stale" if any of:

1. It doesn't exist.
2. Its `manifest.json` (or any contained file) is OLDER than
   `prechop_manifest.json`.
3. Its `manifest.json` doesn't exist.

In JS:

```javascript
function _curatedIsStale(trackDir) {
    var curatedManifest = trackDir + "/curated/manifest.json";
    var prechopManifest = trackDir + "/prechop_manifest.json";

    var curatedMtime = _fileMtime(curatedManifest);
    var prechopMtime = _fileMtime(prechopManifest);

    if (curatedMtime == null) return true;
    if (prechopMtime == null) return false;  // no prechop = nothing to be stale against
    return prechopMtime > curatedMtime;
}
```

### Lazy curate flow

When user presses LOAD CURATED:

1. Check stale (~10 ms).
2. If fresh: load curated clips directly (existing arrangement-loader
   pattern). Done.
3. If stale: emit status `"Curated clips are stale; re-running
   curation..."`, shell to `stemforge curate <track_dir>` via `[shell]`.
4. Helper emits NDJSON progress events; device shows progress in
   status display.
5. On `curate_complete` event: load curated clips.
6. On `curate_error`: surface error in status.

### M4L wiring

New JS file: `v0/src/m4l-js/sf_curated_loader.js`. Mirror Phase-3's
`sf_locator_anchor.js` shape:

- `outlet 0`: status messages
- `outlet 1`: shell command atoms (Python, helper script, args)
- `outlet 2`: load-trigger to `sf_lom_loader` (after curation done)

NDJSON event types (helper emits, parser routes):
- `curate_started`
- `curate_progress` (with phase + pct fields)
- `curate_complete <curated_manifest_path>`
- `curate_error <message>`

Helper script: `tools/m4l_curated_loader.py`. Same pattern as
`tools/m4l_locator_anchor.py`:
- Accepts `--track-dir`, `--pipeline`, optional `--n-bars`, `--strategy`.
- Shells to `stemforge curate ... --json-events` and forwards events.

### Curated-clips loading

After curation completes, the device needs to load the curated clips
into arrangement view. The existing curation flow already produces a
manifest at `<track_dir>/curated/manifest.json` that lists which
clips go on which tracks. Reuse that schema; add a loader function
mirroring `sf_arrangement_loader.runArrangementLoad`.

If the curated clip layout doesn't already have a manifest the loader
can consume, this step expands to:

- Define a `curated_layout.json` schema (clip path → track index +
  arrangement position).
- Add a builder in `stemforge_curate_bars.py` to emit it.
- Add a loader in `sf_curated_loader.js`.

### UX

- LOAD CURATED with fresh curated clips: ~1-2s (just clip loading).
- LOAD CURATED with stale curated clips: ~30s (curation + loading).
- Status bar shows live progress during curation.
- If user presses LOAD CURATED again while curation is running, the
  device should ignore (or queue) the second press — needs debouncing.

### Tests

- `test_curated_loader_stale_detect`: synthetic dir with prechop newer
  than curated → stale; reverse → fresh.
- `test_curated_loader_lazy_runs_curate`: stale dir, pressing LOAD
  CURATED shells to `stemforge curate` first.
- `test_curated_loader_skips_curate_when_fresh`: fresh dir, pressing
  LOAD CURATED skips the shell.
- JS sandbox test: `test_curated_loader.test.js` mirroring
  `test_locator_anchor.test.js`.

### Files that change

- `v0/src/m4l-js/sf_curated_loader.js` — new (~100 LOC).
- `v0/src/m4l-package/StemForge/javascript/sf_curated_loader.js` —
  mirror.
- `tools/m4l_curated_loader.py` — new (~80 LOC, mirrors
  `m4l_locator_anchor.py`).
- `v0/src/maxpat-builder/device.yaml` (or wherever JS modules are
  declared) — register `sf_curated_loader.js`.
- The .amxd patcher — add a button + wire to the new JS module.
- `tests/js_mocks/test_curated_loader.test.js` — new.
- `tests/test_m4l_curated_loader.py` — new.

### Files that don't change

- `stemforge/cli.py` — `curate` command from Step 2 is what gets
  invoked.
- `stems.json` schema.
- Existing arrangement-load flow.

## Sequencing rationale

The four steps build incrementally:

| After step | What works |
|---|---|
| 1 | Manual `python v0/src/stemforge_curate_bars.py` honors override |
| 1 + 2 | `stemforge curate <track_dir>` is the scriptable workflow |
| 1 + 2 + 3 | re-anchor regenerates bars too; consistency across artifacts |
| All 4 | Seamless M4L workflow: ANCH → LOAD CURATED, no terminal |

Each step is independently mergeable and reverts cleanly. Stop at the
step where the workflow becomes acceptable for your needs.

## Risks & mitigations

**Risk: curation cost.** Re-running curation after every ANCH is
expensive (~30s). The lazy-trigger pattern (Step 4) confines the cost
to "user actually wants curated clips," not "user pressed ANCH."

**Risk: stale-detect is fragile.** mtime-based detection misses cases
where the user manually edits the manifest with the same mtime. For v1,
mtime is good enough (clock resolution is finer than user-typing
speed); add a content hash later if needed.

**Risk: `*_bars/` re-slicing breaks existing tools.** Some tools may
have cached references to specific bar files. Mitigation: re-slicing
is deterministic — same beat_times produces same files. Tools that
read bars by index (not by file content hash) are fine. Tools that
checksum specific files would need to re-checksum. None known today.

**Risk: user override is wrong.** The user's locator placement might be
slightly off; using it directly (no snap) propagates the error to the
bar grid. Phase-3's idempotency check (5ms threshold) catches obvious
no-ops; for sub-millisecond drift the result is bar grid that's a few
ms off — same as today's auto-detection inaccuracy. Not worse.

**Risk: curated/ schema doesn't exist yet.** Step 4 assumes the
curation pipeline emits a loadable manifest at
`<track_dir>/curated/manifest.json`. Verify this exists before
implementing Step 4; if not, define it as part of that step.

## Open questions

1. **Default curation pipeline.** Today users specify `--curation X` on
   `stemforge forge`. What's the right default for `stemforge curate`?
   `pipelines/curation_nopad.yaml` is the most common; lock it in or
   make the user choose every time?

2. **Step 3's `--no-bars` flag.** Worth having? Or is "always regenerate
   bars" a reasonable default with no opt-out?

3. **Step 4 loader: which Live tracks?** The arrangement loader has a
   convention for stem → track mapping. Curated clips might want a
   different convention (e.g., stratified by section type or strategy).
   Probably reuse arrangement-loader's mapping initially; revisit if
   curation has its own opinion.

4. **Step 4 button placement.** Live UI real estate is constrained.
   Where does LOAD CURATED go on the device?

5. **Curation pipeline staleness criteria.** mtime-based for v1, but is
   there a case where the user runs curation with a different config
   (e.g., switches `--strategy`) and the result should be considered
   fresh under the new config? Probably need to record the curation
   config in `curated/manifest.json` and compare.

## Files that change (full inventory)

| File | Step | Change |
|---|---|---|
| `v0/src/stemforge_curate_bars.py` | 1 | Honor `tempo.source = "user-override"` |
| `tests/test_curate_bars.py` | 1 | New tests (or extend existing) |
| `stemforge/cli.py` | 2 | New `curate` command |
| `tests/test_cli_curate.py` | 2 | New tests |
| `stemforge/cli.py` | 3 | Re-anchor extends to `*_bars/` |
| `stemforge/slicer.py` | 3 | Helper for re-slicing (if needed) |
| `tests/test_re_anchor.py` | 3 | New tests |
| `v0/src/m4l-js/sf_curated_loader.js` | 4 | New JS module |
| `v0/src/m4l-package/.../sf_curated_loader.js` | 4 | Mirror |
| `tools/m4l_curated_loader.py` | 4 | New helper |
| `v0/src/maxpat-builder/device.yaml` | 4 | Register module |
| `.amxd` (patcher) | 4 | Add LOAD CURATED button + wiring |
| `tests/js_mocks/test_curated_loader.test.js` | 4 | New tests |
| `tests/test_m4l_curated_loader.py` | 4 | New tests |

Total: ~12 files touched. Steps 1-3 are Python only; Step 4 spans
Python + JS + .amxd patcher rebuild.

## Why this is shippable

The four steps decompose the problem along clean seams:

- **Step 1** is a single-file change with bounded scope: read a JSON
  field, branch on it, build `beat_times` from manifest values instead
  of detecting. ~30 lines.
- **Step 2** is a CLI wrapper that shells to existing code. ~50 lines
  total.
- **Step 3** extends an existing command. The bar-slicing logic already
  exists in `stemforge.slicer`; just plumb it. ~40 lines.
- **Step 4** is the largest piece (M4L + Python + tests) but follows
  established patterns (mirrors `sf_locator_anchor.js` shape).

Each step has its own test plan. Each step is independently revertable.
The user-facing workflow improves incrementally — even if we ship only
Step 1, the manual `stemforge curate` invocation becomes ergonomic;
adding Step 2 makes it scriptable; Step 3 closes the consistency gap;
Step 4 removes the terminal entirely.
