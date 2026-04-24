# StemForge Device UI — Build Contract (v1)

Source of truth for parallel implementation. Derived from
`specs/stemforge_device_ui_spec_LATEST.md`. Read that first for full design.

**Status:** authoritative for the implementation session starting 2026-04-22.

---

## 1. Canvas / geometry

- Device canvas: **820 × 169 px** (width × height).
- v8ui area: `0,0` to `820, 149` (top 149 px). Status bar uses native objects
  in the bottom 20 px.
- Three vertical columns inside v8ui:
  - Left column: `x ∈ [0, 212)` — preset + source selectors.
  - Middle column: `x ∈ [212, 716)` — pill matrix / progress / empty state / error.
  - Right column: `x ∈ [716, 820)` — action button (FORGE / CANCEL / DONE / RETRY).
- 4-px grid everywhere. Integer pixel coordinates.

## 2. Max dict contract (shared)

Dict names are frozen. All JS modules must use these names verbatim.

| Dict name | Written by | Read by | Persistence |
|-----------|-----------|---------|-------------|
| `sf_state` | `sf_state.js` | `sf_ui.js`, `sf_forge.js` | Resets on reload (not backed to disk). |
| `sf_preset` | `sf_preset_loader.js`, `sf_state.js` | `sf_forge.js`, `sf_ui.js` | Backed by `live.text` @stored → survives reload. |
| `sf_manifest` | `sf_manifest_loader.js`, Max `[dict]` read of user file | `sf_forge.js`, `sf_ui.js` | Backed by `live.text` @stored → survives reload. |
| `sf_settings` | `sf_settings.js` | all | Persisted to `~/Documents/Max 9/Packages/StemForge/settings.json`. |

**Dict root key:** everything hangs off the top-level key named `root`. So
reading the current device phase is `Dict('sf_state').get('root.kind')`.

Writing with `dict.replace("root", jsonString)` is the pattern used across
existing StemForge code (see `stemforge_loader.v0.js`).

## 3. Runtime state schema (`sf_state`)

Exactly the shape from `specs/stemforge_device_ui_spec_LATEST.md §2`:

```jsonc
// kind = "empty"
{ "kind": "empty" }

// kind = "idle"
{
  "kind": "idle",
  "preset": { /* PresetRef */ },
  "source": { /* SourceRef */ }
}

// kind = "forging"
{
  "kind": "forging",
  "source": {…},
  "preset": {…},
  "phase1": { "active": true, "progress": 0.0, "etaSec": 0, "stems": {…}, "engineLabel": "...", "currentOp": "..." },
  "phase2": { "active": false, "targetsTotal": 11, "targetsDone": 0, "targets": {…}, "currentOp": "" }
}

// kind = "done"
{
  "kind": "done",
  "source": {…}, "preset": {…},
  "tracksCreated": 11,
  "trackRange": [4, 14],
  "elapsedSec": 38.2
}

// kind = "error"
{
  "kind": "error",
  "source": {…}, "preset": {…},
  "error": { "phase": 1|2, "stem": "drums", "target": "crushed", "kind": "split_failed", "message": "...", "fix": "..." }
}
```

### `PresetRef`
```jsonc
{
  "filename": "idm_production.json",
  "name": "idm_production",
  "displayName": "IDM Production",
  "version": "1.0.0",
  "paletteName": "warm_idm",
  "palettePreview": ["#FF3A34", "#F06E24", "#5480E4", "#009D7A"],
  "targetCount": 11
}
```

### `SourceRef`
```jsonc
// manifest
{ "filename": "sketch_04", "type": "manifest", "bpm": 112.4, "bars": 32, "stemCount": 4, "path": "/abs/path/to/stems.json" }
// audio
{ "filename": "recording_20260420.wav", "type": "audio", "path": "/abs/path.wav", "durationSec": 144.2, "sampleRate": 44100 }
```

### `Phase1State.stems`

```jsonc
{
  "drums":  "pending" | "splitting" | "done",
  "bass":   "pending" | "splitting" | "done",
  "vocals": "pending" | "splitting" | "done",
  "other":  "pending" | "splitting" | "done"
}
```

### `Phase2State.targets`

```jsonc
{
  "drums":  { "loops": "pending" | "creating" | "done", "rack": "…", … },
  "bass":   { "loops": "pending", … },
  …
}
```

## 4. Event protocol (v8ui → patcher)

`sf_ui.js` emits events out outlet 0 as lists `<event_name> <args…>`:

| Event | Args | Meaning |
|-------|------|---------|
| `preset_click` | — | User clicked preset selector area. Patcher opens preset `[umenu]`. |
| `source_click` | — | User clicked source selector area. Patcher opens source `[umenu]`. |
| `forge_click` | — | User clicked action button in idle/empty state. |
| `cancel_click` | — | User clicked action button during forge. |
| `retry_click` | — | User clicked action button in error state. |
| `done_click` | — | User clicked action button in done state. |
| `settings_click` | — | User clicked gear icon (settings overlay). |
| `pill_click` | `<stemName> <targetName>` | (v2, not wired in v1.) |

## 5. State-mgr messages (`sf_state.js` inlet)

| Message | Args | Effect |
|---------|------|--------|
| `setPreset` | JSON string OR just the filename | Load preset into `sf_preset` + transition empty→idle (if source also present). |
| `setSource` | JSON string | Load source ref into `sf_manifest` + transition empty→idle (if preset also present). |
| `startForge` | — | Transition idle→forging. Initializes phase1/phase2 from current preset. |
| `markPhase1Start` | — | Zero out progress. |
| `markPhase1Progress` | `<overallPct 0-1> <currentOp>` | Update progress. |
| `markStemStart` | `<stemName>` | Flip stem state to splitting. |
| `markStemDone` | `<stemName>` | Flip stem state to done. |
| `markPhase1Done` | — | Flip phase1.active=false, phase2.active=true. |
| `markTargetStart` | `<stemName> <targetName>` | Flip target to creating, update currentOp. |
| `markTargetDone` | `<stemName> <targetName>` | Flip target to done; increment targetsDone. |
| `markDone` | `<tracksCreated> <trackStart> <trackEnd> <elapsedSec>` | Transition forging→done. |
| `markError` | `<phase> <kind> <message> <fix>` (stem/target via separate msg) | Transition *→error. |
| `reset` | — | Back to empty. Clears phase1/phase2 but keeps preset+source. |
| `getStateJson` | — | Emits current sf_state.root JSON via outlet as `state <jsonstring>`. |

The state manager is the only module that writes to `sf_state`. Other modules
(forge, loaders) call into the state manager.

After every mutation, emit a bang out outlet 0 to trigger v8ui redraw.

## 6. Preset JSON schema (updated for palette)

`stemforge generate-pipeline-json` emits this shape (the v1 baseline is the
existing `pipelines/production_idm.json`). Additions for this spec:

- Top-level: `displayName` (string), `palette` (string, optional), `description` (string).
- Per-target `color` field is an **object** `{ "name": str, "index": int, "hex": str }` rather than a bare hex string.
  - `index` is the Ableton color-index 0–25.
  - `hex` is the resolved RGB for v8ui rendering.
  - `name` is the palette slot name (e.g. "red", "burnt_orange").

Builder resolution (Python side) expands YAML `color: red` → the object form
above by looking up `stemforge/data/ableton_colors.json`.

For backwards compat: if a target has `color: "#RRGGBB"`, the compiler emits
`{ "name": null, "index": 14 (nearest Ableton), "hex": "#RRGGBB" }` and warns.

### Example (snippet)

```jsonc
{
  "name": "idm_production",
  "displayName": "IDM Production",
  "version": "1.0.0",
  "description": "Beat Repeat, Echo, Grain Delay, Decapitator",
  "palette": "warm_idm",
  "stems": {
    "drums": {
      "targets": [
        { "name": "loops", "type": "clips",
          "color": { "name": "red", "index": 14, "hex": "#FF3A34" },
          "chain": [] },
        { "name": "rack", "type": "rack",
          "color": { "name": "crimson", "index": 25, "hex": "#AF2E58" },
          "chain": [{ "insert": "Compressor", "params": { … } }] }
      ]
    }
  }
}
```

## 7. Module file layout

All JS files live in **both** locations (see
`memory/feedback_js_source_of_truth.md`):

- `v0/src/m4l-js/<file>.js` — referenced by `builder.py`.
- `v0/src/m4l-package/StemForge/javascript/<file>.js` — bundled by the pkg installer.

The two must stay in sync. `v0/src/maxpat-builder/build_amxd.py` does NOT
auto-sync yet — after editing, run a copy step (will be automated in a
separate task).

### New JS files

- `sf_state.js` — owns `sf_state` dict, validates transitions, emits redraw bangs.
- `sf_ui.js` — v8ui script that paints the device and handles clicks.
- `sf_preset_loader.js` — scans preset dir, populates `[umenu]`, writes `sf_preset` dict on select.
- `sf_manifest_loader.js` — scans curated manifest dir, opens file dialogs for audio, writes `sf_manifest` dict.
- `sf_settings.js` — reads/writes `settings.json`, mirrors contents into `sf_settings` dict.
- `sf_forge.js` — orchestrator. Calls into existing `stemforge_loader.v0.js:loadSong` for phase 2.

### Preserved / reused

- `stemforge_loader.v0.js` — KEEP. `sf_forge.js` delegates the
  LiveAPI track-creation to it (specifically `loadSong()` or
  `_loadSongFromManifest(mf, preset)`). Don't rewrite the track creation
  logic; reuse.
- `stemforge_ndjson_parser.v0.js` — KEEP. Parses mangled NDJSON from `[shell]`.
- `stemforge_bridge.v0.js` — KEEP as a no-op reference (unused on macOS 26).

## 8. Outlets / wiring summary

Patcher wiring (built by `builder.py`):

```
[v8ui sf_ui.js]
   outlet 0 → route preset_click source_click forge_click cancel_click retry_click done_click settings_click
       preset_click   → [umenu sf_preset_menu] (positioned offscreen; popup menu)
       source_click   → [umenu sf_source_menu] (same)
       forge_click    → [sf_forge_mgr] startForge
       cancel_click   → [sf_forge_mgr] cancelForge
       retry_click    → [sf_forge_mgr] retry
       done_click     → [sf_state_mgr]  reset
       settings_click → [sf_settings_mgr] openOverlay
   outlet 0 → [sf_state_mgr] redraw_hook

[sf_state_mgr]
   outlet 0 → bang → [sf_ui refresh]  (forces redraw from dict)

[sf_preset_loader]
   outlet 0 → [umenu sf_preset_menu] (populate)
   outlet 1 → [sf_state_mgr] setPreset <json>

[sf_manifest_loader]
   outlet 0 → [umenu sf_source_menu] (populate)
   outlet 1 → [sf_state_mgr] setSource <json>

[sf_forge_mgr]
   outlet 0 → [sf_state_mgr]  state mutation messages
   outlet 1 → [shell]          split command (phase 1)
   outlet 2 → [stemforge_loader] loadSongFromDict (phase 2)

[shell stdout] → [js ndjson_parser] → route → [sf_forge_mgr] onSplitEvent
```

## 9. Native (non-v8ui) objects

Still required:

- `[plugin~ 2] → [plugout~ 2]` — audio passthrough (required for audio effect).
- `[live.comment]` scripting_name=`sf_status_text` — bottom-left status line.
- `[live.text]` scripting_name=`sf_status_dot` — bottom-left status dot (12×12 circle).
- `[live.comment]` scripting_name=`sf_version_text` — bottom-right version.
- `[umenu]` scripting_name=`sf_preset_menu` — hidden from presentation, used as popup for preset selection.
- `[umenu]` scripting_name=`sf_source_menu` — hidden from presentation, used as popup for source selection.
- `[live.text]` scripting_name=`sf_gear_btn` — gear icon, top-right of device body (click → settings overlay).
- `[loadbang]` → populate presets & manifests.

## 10. Ableton color palette

File: `stemforge/data/ableton_colors.json`. Schema:

```jsonc
[
  { "index": 0, "name": "pink",  "hex": "#FF94A6" },
  { "index": 1, "name": "orange", "hex": "#FFA529" },
  …
  { "index": 25, "name": "crimson", "hex": "#AF2E58" }
]
```

Exactly 26 entries. Names are lowercase snake_case. Used by:
- Python preset compiler to resolve `color: red` → `{name, index, hex}`.
- JS `sf_forge.js` / `stemforge_loader.v0.js` when calling `track.set('color_index', idx)`.
- JS `sf_ui.js` for rendering pills with the exact matching hex.

## 11. Out of scope for v1

- Chain-editor overlay (click pill → edit chain) — future.
- Pill hover tooltips — future.
- Settings overlay GUI — v1 ships with `settings.json` editing only; gear icon opens a file.
- Multi-source batch forge — future.
- Palette-first YAML refactor — continue to accept legacy hex; emit warning.

## 12. Status-bar color codes

Dot colors (for `sf_status_dot` `bgcolor`):

| State | Dot color | Hex |
|-------|-----------|-----|
| empty / waiting | grey | #555555 |
| idle / done | green | #4ADE80 |
| forging | amber pulsing | #FBBF24 |
| error | red | #F87171 |
| settings/dropdown open | violet | #C084FC |

Status text patterns are as in spec §9.
