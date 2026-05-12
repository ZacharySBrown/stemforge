# StemForge Export Configurator — Context Bundle

Prepared 2026-05-04 for a claude.ai design conversation about the planned third feature area: an **Export Configurator** (abstract grid → projected onto target device topologies).

This bundle is **read-only research**. No refactors were attempted. File:line refs throughout — clone https://github.com/ZacharySBrown/stemforge to inspect.

---

## ⚠️ Risks to read before designing

These are conflicts I see between the proposed plan and current code. Surface them before sinking design effort.

### R1 — "Re-curate after global downbeat" requires re-slicing, not in-place clip mutation
- The curator (`stemforge/curator.py:601`) does not mutate clips. It selects existing WAV files from a `beat_dir/` and writes a manifest of selected indices.
- A "global downbeat" change today re-runs `stemforge re-anchor` (`tools/m4l_locator_anchor.py:43-69`), which **regenerates the prechop chunk WAVs on disk** with the same filenames but new content. That re-slice happens *before* curation in the existing pipeline, but no code re-runs the curator after re-anchor.
- **Implication:** The connection between the modes is not a clip-mutation flow — it's "regenerate WAVs → re-run curator with the same params → reload." If you design the configurator around "tweak a clip's loop bounds without re-slicing the source," you'll fight the existing pipeline. Feasible to add, but not free.

### R2 — `audio_hash` is the identity key, but only for samples that pass through `manifest_schema.write_sidecar`
- Sidecar (`stemforge/manifest_schema.py:62-83`) uses `audio_hash` (sha256 first 16 hex of WAV bytes) — rename-robust.
- But the `stems.json` pipeline manifest (`stemforge/manifest.py:47-58`) and the `prechop_manifest.json` chunk metadata (`stemforge/prechop.py:98-117`) identify chunks by **relative path**. There is no chunk-level audio_hash in those manifests today.
- The arrangement-export resolver (`stemforge/exporters/ep133/song_resolver.py:84-99`) keys on `file_path` (string match into `manifest.session_tracks`).
- **Implication:** If the abstract scene model uses content-hashes as clip refs, you'll need to add hashing at chunk-write time (cheap, but a new write path). If you use file paths, the model breaks the moment a re-anchor moves a file.

### R3 — Locators are one-way (Live → EP-133). No bidirectional sync today.
- `v0/src/m4l-js/sf_arrangement_reader.js` reads `live_set.cue_points`. No code anywhere writes locators back to Ableton or maps them onto session-view scenes.
- The proposed bidirectional sync is genuinely new code, not "lifting existing logic." The hard part is the LOM write path (cue_points are scriptable but with quirks — see R8).

### R4 — `AbstractExporter` exists but only abstracts audio format, not arrangement/scene shape.
- `stemforge/exporters/base.py:150-221` defines audio-side abstraction (sample rate, bit depth, mono/stereo, normalization, memory limit).
- The arrangement/scene/pad model in `stemforge/exporters/ep133/song_format.py` (`PpakSpec`, `Pattern`, `SceneSpec`, `PadSpec`) is **device-specific**: hardcoded EP-133 limits (99 scenes, 12 pads, 4 groups), tick math (TICKS_PER_BAR=384), trigger conventions (note=60, vel=100).
- **Implication:** The "lift the abstract grid above the EP-133 exporter" plan is correct in direction but bigger than swapping a layer. `PpakSpec` will need to be split into `AbstractSceneSpec` (target-agnostic) + `Ep133PpakSpec` (device-mapped).

### R5 — The .amxd container is currently broken on macOS 15.6+
- `node.script` cannot spawn child processes under Live's hardened runtime in Live 12.2.7 / Max 9.0.8 — see `docs/m4l-device-status.md` and `docs/node-script-deep-reseaarch-RESULTS.md`.
- The popup window strategy you're considering ("Node-for-Max + web frontend") is **blocked on this same constraint** today. Live 12.4 / Max 9.1.4 may unblock it, or the workaround is a `[shell]`-launched local HTTP server with `[v8]` + `[maxurl]` talking to it.
- **Don't design around Node-for-Max as if it works** — it doesn't, today.

### R6 — `PpakSpec.scenes[].a/b/c/d` is hardcoded 4-group; new design needs N groups.
- `stemforge/exporters/ep133/song_format.py:`SceneSpec dataclass has named `a, b, c, d` int fields. Not a list. Generalizing to N groups means restructuring this dataclass.

### R7 — JS files are dual-located and must be synced manually
- Per `memory/feedback_js_source_of_truth.md`: every JS module lives at `v0/src/m4l-js/<name>.js` AND `v0/src/m4l-package/StemForge/javascript/<name>.js`. Edits in only one location → stale .amxd when packaged.
- New M4L work in `m4l-devices` repo should NOT replicate this layout. Pick one canonical location and copy on build.

### R8 — `warp_bpm` is read-only; locator/cue_point writes have quirks
- Per `memory/feedback_arrangement_clip_lom.md`: `warp_bpm` read-only via LOM, `end_time` not writable (use `length`), marker units flip with warping.
- Cue-point writes via LOM are scriptable but the tick semantics matter — beats vs. seconds switch when warping. Test the bidirectional path on a warped session early.

---

## What's in this bundle

| § | Content |
|---|---|
| 1 | Clip data model (canonical schemas + actual fields) |
| 2 | Locator → scene flow (with the **tile/repeat function** quoted in full — load-bearing gem) |
| 3 | M4L device architecture + UI patterns (v8ui, build pipeline, what's broken) |
| 4 | Curation module entry/exit |
| 5 | Things the 5-item list missed (you should know about these) |
| 6 | In-flight branches |
| 7 | One opinionated layout suggestion for the new `m4l-devices` repo |

---

## 1. Clip data model

Three layered schemas. They do not fully overlap.

### 1a. `SampleMeta` — load-bearing, the "manifest sidecar" for hardware-loader-friendly metadata
File: [stemforge/manifest_schema.py](stemforge/manifest_schema.py) (canonical, mirrored byte-for-byte by the separate `ep133-ppak` repo)

```python
class SampleMeta(BaseModel):
    file: str | None              # bare filename
    audio_hash: str | None        # sha256 first 16 hex — IDENTITY KEY
    name: str | None              # ≤16 char display name
    bpm: float | None
    time_mode: Literal["off", "bar", "bpm"] | None
    bars: float | None
    playmode: Literal["oneshot", "key", "legato"] | None
    source_track: str | None
    stem: Literal["drums", "bass", "vocals", "other", "full"] | None
    role: str | None              # "loop", "kick", "snare", "one_shot", free-form
    suggested_group: Literal["A","B","C","D"] | None      # ADVISORY, EP-133 only
    suggested_pad: Literal["7","8","9","4","5","6","1","2","3",".","0","ENTER"] | None  # ADVISORY
```

- Wire formats: `.manifest_<hash>.json` next to each WAV; `.manifest.json` in the directory root for batches.
- Resolution order (consumer side): CLI flag → sidecar → batch → defaults. CLI always wins.
- `model_config = {"extra": "ignore"}` — forwards-compatible. Adding fields is safe.
- **Not used by every writer in the repo yet.** Forge curation writes them; prechop only writes them when `write_sidecars=True`. Not all `tools/` scripts emit them.

**Annotation:** Load-bearing. This is the most thoughtful schema in the repo and the only one already designed for cross-target consumption (the EP-133 loader plus a separate `ep133-ppak` repo both consume it).

### 1b. `StemManifest` (`stems.json`) — load-bearing, but track-level not clip-level
File: [stemforge/manifest.py:47-58](stemforge/manifest.py#L47-L58)

```python
@dataclass
class StemManifest:
    track_name: str
    source_file: str
    backend: str                    # "demucs" — only one supported
    bpm: float
    beat_count: int
    stems: list[StemInfo]           # name + wav_path + beats_dir + beat_count
    output_dir: str
    pipeline: str
    processed_at: str
    tempo: TempoProvenance | None   # provenance + confidence + first_downbeat_sec
    input_audio: InputAudio | None  # sha256 of source + sample-accurate fingerprint
```

- This is the **track-level** manifest. It does NOT contain per-clip data — clips/chunks live below it (see 1c).
- `tempo.first_downbeat_sec` is the global downbeat the user is anchoring against. Lives at the track level, not per-clip.
- `session_tracks` is **dynamically grafted** onto this dict by the M4L device's COMMIT button (see §2 below). Not part of the dataclass. The arrangement-export pipeline reads it.

### 1c. `ChunkMeta` (`prechop_manifest.json`) — load-bearing, the "padded chunk" descriptor
File: [stemforge/prechop.py:98-117](stemforge/prechop.py#L98-L117)

```python
@dataclass
class ChunkMeta:
    file: str                  # path relative to manifest dir
    stem: str                  # "drums", "bass", ...
    chunk_index: int           # 1-based
    bars: int                  # target bars (the loop region length)
    pad_bars: int              # configured padding (per side)
    pad_pre_bars: float        # ACTUAL bars of pre-roll padding (clamped at start)
    pad_post_bars: float       # ACTUAL bars of post-roll padding (clamped at end)
    loop_start_sec: float      # offset within padded WAV where bar 1 begins
    loop_end_sec: float        # offset within padded WAV where bar N+1 begins
    total_sec: float           # total padded WAV duration
    chunk_duration_samples: int  # integer frame count — catches silent resamples
    sample_rate: int
    source_offset_sec: float   # where in the source stem this chunk's bar 1 sits
```

This is the descriptor of an arrangement-mode "padded chunk." It encodes:
- **Loop region** (`loop_start_sec`/`loop_end_sec`) — what the M4L loader sets clip start/end markers to.
- **Padding** — pre/post bars audible if the user drag-extends. The phase-3 modifications in the in-progress diff (`stemforge/prechop.py` working-tree changes, see `git status`) add a "leading partial chunk" concept for sub-chunk-period intro material.
- **Source mapping** (`source_offset_sec`) — back-pointer to where this chunk's bar 1 lives in the original stem. **This is what `m4l_locator_anchor.py` needs to do downbeat re-projection** — when the user moves a locator, the JS converts target-time → source-time using this offset.

Top-level `prechop_manifest.json` carries: `bpm`, `bars`, `pad_bars`, `pad_pre_bars`, `pad_post_bars`, `pad_last`, `beats_per_bar`, `first_downbeat_sec`, `pre_bars`, `musical_bar_1_chunk_index`, `leading_partial_emitted`, `stems[stem_name].chunks[]`.

**Annotation:** Load-bearing. The new design needs to either subsume this format or treat it as a stable input. The `loop_start_sec`/`loop_end_sec`/`source_offset_sec` triplet is the contract the arrangement-mode M4L loader depends on.

### 1d. `CurationBlock` schema — separate from above, applies post-curation
File: [stemforge/curation_schema.py](stemforge/curation_schema.py)

Defines `clip` / `warp_markers` / `loop` / `offsets` blocks per WAV, embedded inside the curation manifest. Used by the M4L COMMIT step to capture user-edited clip start/end markers.

**Annotation:** Load-bearing for the existing curation-v1/v2 flow but a separate concept. If the configurator's clip refs need warp markers, they live here.

### 1e. `session_tracks` — runtime-grafted, the actual contract between M4L and the arrangement exporter
Written by [v0/src/m4l-js/stemforge_loader.v0.js:1707-1774](v0/src/m4l-js/stemforge_loader.v0.js#L1707-L1774) (`_commitSessionTracks`). Each entry:

```js
{
  slot: 0..30,                    // Live clip-slot index (NOT EP-133 pad number)
  file: "/abs/path.wav",
  start_offset_sec, end_offset_sec, clip_length_sec,
  mode: "rotate" | "trim",        // hint for the export tool's bake step
  // optional, added by song-export pipeline:
  loop_start_sec, loop_end_sec    // when chunk WAV had pad bars
}
```

- The COMMIT button walks Live's session-view tracks named exactly `A`/`B`/`C`/`D`, captures every loaded clip's file path + start/end markers, and writes the result into the loaded `stems.json`.
- The EP-133 song-export resolver looks files up here (see [stemforge/exporters/ep133/song_resolver.py:84-99](stemforge/exporters/ep133/song_resolver.py#L84-L99)) — **this is the lookup table that maps arrangement clips back to a slot/pad number.**
- `pad = slot + 1` (slots 0-indexed; pads 1-indexed).

**Annotation:** Load-bearing but **structurally a hack**. The four-letter-track convention is hardcoded. Generalizing to "any N tracks → any group taxonomy" means redesigning this contract. That's the lift the configurator wants.

### Mutability summary

Clips are **immutable on disk** in the current code. Sidecar writes use `.model_copy(update=...)` (pydantic immutable pattern). The closest thing to mutation is:

1. `stemforge re-anchor` regenerates chunk WAVs at the same paths (different content).
2. The M4L COMMIT button mutates the loaded-in-memory `stems.json` to add `session_tracks`, then writes back.
3. Curation writes a fresh `manifest.json` in the beat_dir; doesn't touch source WAVs.

If the configurator needs in-place clip-metadata edits (e.g., user drags a clip's loop region in the popup, store the change persistently), there is no existing pattern to copy — design something new.

---

## 2. Locator → scene flow + the tile/repeat function

The crown jewel for your design lift is **`_event_positions_bars`** in [stemforge/exporters/ep133/song_synthesizer.py:121-153](stemforge/exporters/ep133/song_synthesizer.py#L121-L153). Quoted in full:

```python
# Cap on multi-event tiling density so a tiny slice (e.g. a single click
# at 1/64-bar) doesn't produce a pathological pattern. 32 events per
# pattern is a 32nd-note grid at 4/4 — the finest density that's
# musically useful. Beyond that the slice is shorter than typical
# rhythmic resolution and a single trigger sounds the same.
_MAX_EVENTS_PER_PATTERN = 32

# Total trigger counts per pattern that we snap multi-event tiling to.
# These are subdivisions of the WHOLE pattern, not per-bar — chosen so
# spacing always lands on a familiar grid:
#   1 = single fire, 2 = halves, 4 = quarters, 8 = eighths, 16 = sixteenths,
#   32 = thirty-seconds (relative to pattern length).
# A slice that lands between these snaps to the closest. Never produces
# a 6- or 7-tuplet feel that fights the underlying tempo.
_MUSICAL_TRIGGER_COUNTS = (1, 2, 4, 8, 16, 32)


def _event_positions_bars(slice_bars: float, pattern_bars: int) -> list[float]:
    """Compute event positions (in bars) for a multi-event pattern.

    A clip whose slice is shorter than the pattern needs to fire multiple
    times to mimic Ableton's loop-fill behavior. We snap the trigger
    count to the nearest power-of-2 subdivision of the pattern length so
    the result lands on a familiar rhythmic grid instead of an awkward
    6- or 7-tuplet. Slices that are roughly pattern-length or longer
    return a single trigger at position 0 (the device plays the full
    slice in BPM mode).

    Examples:
      pattern_bars=1, slice_bars=1.0     → [0.0]                 (1× whole)
      pattern_bars=1, slice_bars=0.5     → [0.0, 0.5]            (halves)
      pattern_bars=1, slice_bars=0.156   → 8 events (eighth-grid)
      pattern_bars=4, slice_bars=2.0     → [0.0, 2.0]            (every 2 bars)
      pattern_bars=4, slice_bars=1.0     → 4 events (one per bar)
    """
    if slice_bars <= 0 or pattern_bars <= 0:
        return [0.0]
    raw_count = pattern_bars / slice_bars
    if raw_count < 1.5:
        return [0.0]
    candidates = [c for c in _MUSICAL_TRIGGER_COUNTS if c <= _MAX_EVENTS_PER_PATTERN]
    n = min(candidates, key=lambda c: (abs(c - raw_count), c))
    if n == 1:
        return [0.0]
    spacing = pattern_bars / n
    return [i * spacing for i in range(n)]
```

**This is the function you want to lift.** It's already device-agnostic — pure bar math, no EP-133 state. The function returns positions in *bars*; the EP-133-specific code converts to ticks (`TICKS_PER_BAR=384`) and pads them with note=60/vel=100/duration=96, but those are decisions the synthesizer makes ABOVE this function, not inside it.

### Rest of the synthesis pipeline

Three Python files implement Ableton arrangement → EP-133 .ppak today:

| File | Lines | What it does | Annotation |
|------|---|---|---|
| [stemforge/exporters/ep133/song_resolver.py](stemforge/exporters/ep133/song_resolver.py) | 176 | Locator + arrangement clips → list of `Snapshot` (which clip plays on each of A/B/C/D at each locator). Pure query logic. | Load-bearing core. Generalize: replace 4-group `Snapshot` with N-group dict. |
| [stemforge/exporters/ep133/song_synthesizer.py](stemforge/exporters/ep133/song_synthesizer.py) | 495 | Snapshots → `PpakSpec`. Computes scene lengths from locator gaps, infers bars per clip, runs the tile/repeat math, emits empty-pattern markers for silent groups, picks sample slots. | Load-bearing logic but EP-133-specific scaffolding. The math (`_scene_lengths_in_bars`, `infer_bars`, `_event_positions_bars`) is general; the slot allocation (`global_sample_slot` at line 58, `SAMPLE_SLOT_BASE = 700`) is EP-133. |
| [stemforge/exporters/ep133/song_format.py](stemforge/exporters/ep133/song_format.py) | 486 | EP-133 binary writers (patterns, scenes, pads, settings). Dataclasses: `Event`, `Pattern`, `SceneSpec`, `PadSpec`, `PpakSpec`. | EP-133-specific. The dataclass shapes are reasonable starting points for an abstract spec but `SceneSpec.{a,b,c,d}` needs to become a list/dict. |
| [stemforge/exporters/ep133/ppak_writer.py](stemforge/exporters/ep133/ppak_writer.py) | 512 | TAR + ZIP container assembly with reference-template patching. | EP-133-specific, leave alone. |

### Snapshot reading (the M4L side)

[v0/src/m4l-js/sf_arrangement_reader.js](v0/src/m4l-js/sf_arrangement_reader.js) (391 lines) reads `live_set.cue_points` and per-track A/B/C/D arrangement clips, writes `snapshot.json`. Header comment (lines 17-34) documents the wire shape:

```json
{
  "tempo": 120.0,
  "time_sig": [4, 4],
  "arrangement_length_sec": 64.0,
  "locators": [{"time_sec": 0.0, "name": "Verse"}, ...],
  "tracks": {
    "A": [{"file_path": "/abs/path.wav", "start_time_sec": 0.0, "length_sec": 4.0, "warping": 1}],
    "B": [], "C": [...], "D": [...]
  }
}
```

**Annotation:** Load-bearing. The four-track convention is hardcoded; generalizing it to N tracks (or any-named-tracks) means changing this writer. The LOM read primitives (`_getLomNumber`, `_getLomString`, `_stripHfsPrefix`) are intentionally duplicated from `stemforge_loader.v0.js` and reusable.

### Scene-length inference from locator gaps

[stemforge/exporters/ep133/song_synthesizer.py:181-234](stemforge/exporters/ep133/song_synthesizer.py#L181-L234) — `_scene_lengths_in_bars(snapshots, project_bpm, arrangement_length_sec)`. Quantizes each locator to nearest integer bar, computes scene lengths from gaps, falls back to median or 2-bar default for trailing scene. Already handles arbitrary positive integer bar counts (not snapped to powers-of-2). Ready to lift.

### Bars inference

[stemforge/exporters/ep133/song_synthesizer.py:82-101](stemforge/exporters/ep133/song_synthesizer.py#L82-L101) — `infer_bars(clip_length_sec, project_bpm)`. Currently snaps to {1, 2, 4} — this is **EP-133-specific** (its `time.bars` field accepts only those). Other targets won't have this constraint. **Generalize: take `bars_candidates` as a parameter.**

### Locator → session-view bidirectional sync
Status: **does not exist**. Nothing in the repo writes locators back, and nothing reads session-view scenes. The user mentioning this as a goal means designing it from scratch.

---

## 3. M4L device architecture + UI patterns

### 3a. Repo layout
| Path | Role | Annotation |
|---|---|---|
| `v0/build/StemForge.amxd` | Shipped device | Load-bearing — the actual artifact |
| `v0/src/m4l-package/StemForge/` | Max Package source (deployed to `~/Documents/Max 9/Packages/StemForge/`) | Load-bearing |
| `v0/src/m4l-js/` | Dev source — JS files **mirrored** to the Package dir | Load-bearing — but **dual-location footgun** (see R7) |
| `v0/src/maxpat-builder/build_amxd.py` | Programmatic .amxd builder | Load-bearing build pipeline |
| `v0/interfaces/device.yaml` | Declarative device spec consumed by the builder | Load-bearing |
| `m4l/` | Live-12 package mirror (where Live actually loads from) | Load-bearing |
| `tools/sf_deploy.py` | Sync script for the dual-located JS | Load-bearing |
| `docs/m4l-device-status.md` | Current breakage log (macOS 15 hardened-runtime issue) | Read this first |

### 3b. JS module inventory

All in both `v0/src/m4l-js/` and `v0/src/m4l-package/StemForge/javascript/`:

| Module | LOC | Role | Annotation |
|---|---|---|---|
| [sf_ui.js](v0/src/m4l-js/sf_ui.js) | 1082 | v8ui canvas. Imperative paint, hit-test by cached rects, click events out via `outlet(0, "<event_name>")`. | Load-bearing. **Precedent for any new canvas UI.** |
| [sf_state.js](v0/src/m4l-js/sf_state.js) | 650 | Owns the `sf_state` Max dict. Phase-transition validation, redraw bangs. | Load-bearing |
| [sf_forge.js](v0/src/m4l-js/sf_forge.js) | 535 | Orchestrates Phase-1 (audio split via `[shell]`) and Phase-2 (track creation) | Load-bearing |
| [sf_preset_loader.js](v0/src/m4l-js/sf_preset_loader.js) | 316 | Scans presets, populates `[umenu]` | Load-bearing |
| [sf_manifest_loader.js](v0/src/m4l-js/sf_manifest_loader.js) | 501 | Reads `stems.json`, caches stem metadata | Load-bearing |
| [sf_settings.js](v0/src/m4l-js/sf_settings.js) | 373 | settings.json read/write, mirrors to `sf_settings` dict | Load-bearing |
| [sf_clip_export.js](v0/src/m4l-js/sf_clip_export.js) | 403 | "Bounce selected clips → manifest_<hash>.json sidecars" | Load-bearing |
| [sf_arrangement_reader.js](v0/src/m4l-js/sf_arrangement_reader.js) | 391 | LOM → snapshot.json (described in §2) | Load-bearing |
| [sf_arrangement_loader.js](v0/src/m4l-js/sf_arrangement_loader.js) | 514 | Loads prechop_manifest.json → arrangement-view clips with loop markers set | Load-bearing |
| [stemforge_loader.v0.js](v0/src/m4l-js/stemforge_loader.v0.js) | 2004 | LOM track builder for Phase-2; the COMMIT button's `_commitSessionTracks` lives here | Load-bearing but **monstrous file**. Apply the simplifyer agent before refactoring. |
| [stemforge_bridge.v0.js](v0/src/m4l-js/stemforge_bridge.v0.js) | 242 | Node-for-Max bridge — spawns stemforge-native, parses NDJSON | **Currently broken on macOS 15.6+** (R5) |
| [stemforge_ndjson_parser.v0.js](v0/src/m4l-js/stemforge_ndjson_parser.v0.js) | 103 | NDJSON parser; runs in classic [js] | Load-bearing |
| [sf_logger.js](v0/src/m4l-js/sf_logger.js) | 248 | Writes `~/stemforge/logs/sf_debug.log` | Dev-time |
| [stemforge_param_scraper.js](v0/src/m4l-js/stemforge_param_scraper.js) | 562 | Live device parameter dumper (utility) | Throwaway-ish — codifies `live_devices.json` |
| [stemforge_quadrant_router.js](v0/src/m4l-js/stemforge_quadrant_router.js) | 235 | Legacy quadrant-editor click router | **Throwaway** per memory `project_two_templates.md` |

### 3c. v8ui paint pattern (the precedent)

Imperative paint via mgraphics. `paint()` calls `drawRightButton()` etc.; helpers `fillRoundedRect`, `textAt`, `roundedRect`. Hit-testing via cached rects (`commitBtnRect`, `bounceBtnRect`, etc.) and an `onclick(x, y)` handler. Click dispatch as outlet atoms: `outlet(0, "forge_click")`.

Strip device geometry: 820×169 (820×149 canvas + 20px status bar).

**Honest assessment for popup design:**
- v8ui works, is testable in standalone Max, and the `paint`/`hit-test` pattern scales linearly.
- It has zero structure: paint, state, input mixed into one closure. A 2D editor (drag, snap, multi-select, undo) is implementable but each interaction primitive is from-scratch.
- For a popup with a "killer 2D UI," consider: (a) `[shell]`-launched local HTTP server (Python/FastAPI) + `[v8]` HTTP client, with the actual UI in a pinned-frame `[jweb]`. This is more decoupled than Node-for-Max, isn't subject to the macOS 15 issue, and lets you use real frontend tools. The cost is the bridge dance.

### 3d. Test infrastructure
- [tests/test_js_bridge.py](tests/test_js_bridge.py) — pytest harness that spawns Node test suites
- [tests/js_mocks/](tests/js_mocks/) — `max_api.js` mock + per-module `*.test.js`
- [v0/tests/](v0/tests/) — additional M4L tests
- Pure-JS testability is **already a design constraint** (see `docs/test-plan.md` Phase 2-3 strategy). Preserve it in the new design.

### 3e. shell.mxo + Node-for-Max constraints
- Per `memory/feedback_shellmxo_quirks.md`: no `spawn`/`kill` verbs in shell.mxo v8.0.0. Workaround: use `pkill` for cleanup.
- Per `docs/node-script-deep-reseaarch-RESULTS.md`: macOS 15.6+ hardened runtime kills the child node.script process before handshake on Live 12.2.7. Live 12.4 / Max 9.1.4 may unblock.
- Don't design assuming Node-for-Max works. It's the riskiest piece of plumbing in the device today.

---

## 4. Curation module entry/exit

### Entry point
[stemforge/curator.py:601-750](stemforge/curator.py#L601-L750) — `curate(beat_dir, n_bars=14, strategy=...) -> list[Path]`

```python
def curate(
    beat_dir: Path,
    n_bars: int = 14,
    strategy: str = "max-diversity",
    rms_floor: float = 0.005,
    crest_min: float = 4.0,
    content_density_min: float = 0.0,
    distance_weights: dict[str, float] | None = None,
    song_structure: "SongStructure | None" = None,
    alts_per_section: int = 2,
    max_sections: int = 4,
    phrase_bars: int = 1,
) -> list[Path]:
```

- Reads every WAV in `beat_dir/`; analyzes (RMS, crest factor, spectral, rhythm fingerprint).
- Filters by RMS / crest / content-density floors.
- Selects via greedy farthest-point, rhythm-taxonomy clustering, or section-aware strategies.
- Writes `beat_dir/manifest.json` with selection metadata.
- Returns `list[Path]` of selected files in selection order.

**No clip mutation.** It's a selection over the already-sliced WAVs. If you re-curate, you re-select; you don't rewrite source files.

### Strategies (annotation: load-bearing)
- `max-diversity` (default): greedy farthest-point in normalized feature space, seeded on highest crest
- `rhythm-taxonomy`: cluster by rhythm fingerprint (16-bit grid), select diverse variants per cluster
- `sectional` / `transition` / `section-main-alt`: structure-aware (need `song_structure`)

### CLI exits
- `stemforge forge` calls curate as part of the post-slice pipeline (cli.py around line 1014 onward, integrated).
- `stemforge re-anchor` (cli.py:497-720) — re-slices only, **does NOT re-curate**. The "re-curate after global downbeat" feature is still TBD.

### Curation → export handoff
Curator writes `beat_dir/manifest.json`. Downstream consumers:
- M4L device: `sf_manifest_loader.js` reads it, drives Phase-2 track creation
- EP-133 hybrid: `tools/ep133_load_hybrid_session.py` reads `session_tracks` (a derived field added by COMMIT)
- EP-133 song-mode: `stemforge export-song` reads the same `session_tracks`
- Koala: `stemforge/exporters/koala.py` reads the curated dir directly

The handoff is **filesystem-coupled, not API-coupled**. The configurator can sit anywhere in this chain without breaking what's there.

---

## 5. Things the 5-item list missed

### 5a. Multiple legacy EP-133 exporters coexist
The `stemforge/exporters/` directory has FIVE EP-133 files at different generations:

| File | LOC | Status |
|------|-----|--------|
| `ep133.py` | 283 | Older (compose/perform workflows, AbstractExporter-based) |
| `ep133_v2.py` | 568 | Newer attempt |
| `ep133_mapping.py` | 177 | Mapping layer |
| `ep133_stem_export.py` | 565 | Stem-mode export |
| `ep133_upload.py` | 319 | Upload-only |
| `ep133/` (subpackage) | ~3000 LOC across 17 files | **Current canonical** |

**Annotation:** The flat-file `ep133*.py` siblings are **legacy/throwaway** (or at least, their lessons are absorbed into the `ep133/` subpackage). The subpackage is current. If you grep "ep133" you'll see all five — only `ep133/` matters for new design.

There's also `targets/koala.py` and `targets/cli_koala.py` at the repo root, separate from `stemforge/exporters/koala.py`. The repo-root `targets/` directory is also referenced in your message ("we set up the right layout from the start") — it's currently a vendoring sandbox for the Koala exporter (untracked in git per `?? targets/` in `git status`). Not a blueprint.

### 5b. The `bounce-to-clip` flow is the cleanest precedent for "user-facing M4L feature backed by a Python helper"
[v0/src/m4l-js/sf_clip_export.js](v0/src/m4l-js/sf_clip_export.js) (403 lines) + [tools/m4l_export_clips.py](tools/m4l_export_clips.py) + [tests/test_m4l_export_clips.py](tests/test_m4l_export_clips.py) — round-trip tested. The pattern (JS captures Live state → writes intermediate JSON → Python helper does the heavy work → reports back NDJSON) is what the configurator should follow.

### 5c. The `m4l_locator_anchor.py` pattern is the "downbeat anchoring" pipeline
[tools/m4l_locator_anchor.py](tools/m4l_locator_anchor.py) (119 lines) — invoked by JS via `[shell]`. JS captures the locator drag, computes source-time using prechop_manifest, shells the Python tool, NDJSON events route back to outlets. **This is the exact handoff pattern for "user moves something in the popup → Python rewrites manifests."**

### 5d. The phones24 / DannyDesert reference repos are external dependencies
The arrangement-song-export spec references:
- `~/repos/EP133-skill/scripts/create_ppak.py` (DannyDesert — write reference)
- `~/repos/ep133-export-to-daw/src/lib/parsers.ts` + `docs/EP133_FORMATS.md` (phones24 — read reference, canonical)
- `ep133-ppak` repo — the canonical EP-133 sample loader (separate repo, mirrors `manifest_schema.py`)

These are user-local. Not part of stemforge's tree. If the new design abstracts EP-133 mapping, you'll still need these to validate.

### 5e. There is no test for the locator → scene tile/repeat function alone
The EP-133 song-export test suite ([tests/ep133/](tests/ep133/)) tests integration. `_event_positions_bars` is exercised but not directly unit-tested. **Easy win when extracted to a generic module: write the unit tests then.**

### 5f. The shipped device's strip layout currently includes
PRESET selector, SOURCE selector, FORGE/CANCEL/DONE/RETRY primary buttons, COMMIT, BOUNCE, EXPORT-SONG, LOADARR. Plus state-specific middle (matrix during forging, error message on failure, etc.). Confirmed by reading `sf_ui.js` paint helpers and click event names. The "compact summary" the user described is roughly: "left = inputs, middle = state, right = primary action." Mirroring that into the configurator's strip-mode (and putting the actual editor in the popup) is consistent with the existing pattern.

### 5g. Live API quirks worth knowing for any new device
- `warp_bpm` is read-only (must use `live_set tempo`)
- `end_time` not writable (use `length`)
- Marker units flip with warping: beats when `warping=1`, seconds otherwise
- LOM scalar properties come back as 1-element arrays (helpers exist, see `sf_arrangement_reader.js:_getLomNumber`)
- File paths from LOM start with `Macintosh HD:` (helpers strip via `_stripHfsPrefix`)

---

## 6. In-flight branches

`git branch -a` (cleaned to relevant ones):

| Branch | Purpose | Status |
|---|---|---|
| `feat/curation-engine-v2` | Core curation engine (outlier filtering, duration normalization) | Active, partially merged via PRs |
| `feat/curation-library-v2` | Library mode + arrangement integration + song-form templates | Active, more advanced. **Per memory: one-way merge — main → branch, never the reverse without explicit go-ahead.** |
| `feat/ep133-song-export` | What landed as the song-export pipeline (most recent ep133 spec work) | Mostly merged; trailing fixes |
| `feat/arrangement-prechop-mode` | Arrangement-mode prechop with pad bars | Recently merged |
| `feat/m4l-locator-anchor` | Locator → re-anchor flow | Recently merged |
| `feat/harness-patterns` | The audit-driven harness patterns at `~/raindog/harness/quickstarts/max-plugin/` | External work |
| 30+ `worktree-agent-*` and `feat/v0-*` branches | Multi-agent worktree experiments | Mostly stale; ignore |

Specs that describe the planned (not-yet-shipped) work the configurator touches:
- [specs/stemforge-curation-v2-spec.md](specs/stemforge-curation-v2-spec.md) — manifest schema, padding, offsets contract
- [specs/curation-quality-spec.md](specs/curation-quality-spec.md)
- [specs/m4l-integrated-forge-device.md](specs/m4l-integrated-forge-device.md) — "Real-time re-curation" listed as future work but no detailed spec
- [specs/ep133-arrangement-song-export.md](specs/ep133-arrangement-song-export.md) — current arrangement → EP-133 spec (mostly shipped)
- [specs/hardware-export-targets.md](specs/hardware-export-targets.md) — multi-target framing (EP-133 + Chompi); use as starting point for the abstract grid → target projection model
- [specs/manifest-spec.md](specs/manifest-spec.md) — the SampleMeta wire-format spec (canonical)

There is **no spec yet for**:
- Re-curation triggered by global downbeat change
- Bidirectional locator ↔ session-view-scene sync
- The Export Configurator itself

---

## 7. Suggested layout for the `m4l-devices` repo

(Opinionated — feel free to ignore. Based on the patterns I see working in stemforge.)

```
m4l-devices/
├── core/
│   ├── scene_model.py          # AbstractSceneSpec, GroupSpec, PadSpec — N-group, N-pad
│   ├── tile.py                 # _event_positions_bars, lifted verbatim
│   ├── scene_lengths.py        # _scene_lengths_in_bars, lifted
│   ├── snapshot.py             # generic snapshot.json reader (locators + N tracks)
│   └── manifest.py             # session_tracks reader/writer (N-group)
├── targets/
│   ├── _base.py                # AbstractDeviceTarget (project scene_model → device-specific)
│   ├── ep133/
│   │   ├── projector.py        # AbstractSceneSpec → PpakSpec
│   │   ├── byte_format.py      # (lifted from stemforge/exporters/ep133/song_format.py)
│   │   └── writer.py           # (lifted from ppak_writer.py)
│   ├── chompi/
│   │   └── projector.py
│   └── koala/
│       └── projector.py
├── m4l/
│   ├── ConfiguratorStrip.amxd  # compact strip device
│   ├── ConfiguratorPopup/      # Max-side popup wrapper
│   ├── js/                     # ONE canonical location, no dual-location footgun
│   └── package/                # symlink or build-step copy of js/
├── ui/                         # web frontend if you go that route
│   ├── src/
│   └── package.json
├── bridge/                     # local HTTP server (FastAPI?) the device talks to
├── tests/
│   ├── core/                   # pure unit tests for scene_model, tile, etc.
│   ├── targets/                # round-trip per target (lift fixtures from stemforge/tests/ep133)
│   └── js/                     # mock-LiveAPI tests (lift pattern from stemforge/tests/js_mocks)
└── specs/
    └── scene_model.md          # the abstract grid contract
```

Why this shape:
- `core/` is **target-agnostic**. Every Python module here should run with no device imports.
- `targets/_base.py` defines `project(scene_spec) -> device_spec`. Each target subclasses it. This is the "topology projection" the user described.
- `m4l/js/` is **single-location** (fixes R7). Build step copies into the package on package.
- `bridge/` lets you decouple the M4L device from heavy work (the configurator's actual logic). Avoids the macOS 15 Node-for-Max trap (R5).
- `ui/` is optional — start with v8ui in Max, escalate to a `[jweb]` web UI if and only if you need the extra interaction richness.

**Don't** copy stemforge's three-zone Architect/Engineer/Reviewer split into `m4l-devices`. That's a workflow convention specific to multi-agent sessions, not a repo-structure pattern.

---

## Appendix — files I read (verified)

- [stemforge/manifest_schema.py](stemforge/manifest_schema.py) (310 LOC, in full)
- [stemforge/manifest.py](stemforge/manifest.py) (150 LOC, in full)
- [stemforge/prechop.py:95-225](stemforge/prechop.py#L95-L225) (ChunkMeta + prechop_stem signature + phase-3 in-progress diff)
- [stemforge/curator.py:600-750](stemforge/curator.py#L600-L750) (curate function in full)
- [stemforge/exporters/base.py](stemforge/exporters/base.py) (221 LOC, in full)
- [stemforge/exporters/ep133/song_resolver.py](stemforge/exporters/ep133/song_resolver.py) (176 LOC, in full)
- [stemforge/exporters/ep133/song_synthesizer.py](stemforge/exporters/ep133/song_synthesizer.py) (495 LOC; lines 1-250 + 250-496 carefully)
- [stemforge/exporters/ep133/song_format.py:1-130](stemforge/exporters/ep133/song_format.py#L1-L130) (constants + dataclass headers)
- [tools/m4l_locator_anchor.py](tools/m4l_locator_anchor.py) (119 LOC, in full)
- [tools/ep133_load_hybrid_session.py:1-80](tools/ep133_load_hybrid_session.py#L1-L80) (LAYOUT block)
- [v0/src/m4l-js/sf_arrangement_reader.js:1-120](v0/src/m4l-js/sf_arrangement_reader.js#L1-L120) (header + LOM helpers)
- [v0/src/m4l-js/stemforge_loader.v0.js:1700-1790](v0/src/m4l-js/stemforge_loader.v0.js#L1700-L1790) (`_commitSessionTracks`)
- [specs/ep133-arrangement-song-export.md](specs/ep133-arrangement-song-export.md) (full)
- [specs/manifest-spec.md](specs/manifest-spec.md) (full)
- [specs/hardware-export-targets.md](specs/hardware-export-targets.md) (lines 1-150)
- [docs/feature-backlog.md](docs/feature-backlog.md) (lines 1-100)

Files I scanned but didn't read in full (worth a deeper look if your designer wants to dig in):
- `stemforge/exporters/ep133/ppak_writer.py` (512 LOC) — TAR/ZIP byte assembly
- `stemforge/exporters/ep133/song_format.py:130-486` — actual byte builders for patterns/scenes/pads/settings
- `v0/src/m4l-js/sf_ui.js` (1082 LOC) — paint/hit-test pattern
- `v0/src/m4l-js/stemforge_loader.v0.js` (2004 LOC) — Phase-2 LOM track builder, the COMMIT button logic
- `stemforge/curation_schema.py` (311 LOC) — clip/warp_markers/loop/offsets schema
- `stemforge/exporters/chompi.py` (316 LOC) — second example of `AbstractExporter` subclass
- `tests/ep133/` — fixture format examples for round-trip validation
