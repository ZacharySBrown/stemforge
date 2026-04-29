# StemForge M4L Device — Implementation Spec

Target: Max for Live 8+ in Ableton Live 12.3+.
Device type: Audio Effect (so it can live on any track but primarily used on a utility track).
Canvas: 820 × 169 px, fixed width.

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  StemForge.amxd                                             │
│                                                             │
│  ┌───────────────────────┐   ┌─────────────────────────┐    │
│  │  Presentation layer   │   │  Logic layer            │    │
│  │                       │   │                         │    │
│  │  [v8ui sf_ui]────────┼──→│  [js sf_state.js]       │    │
│  │    ↑   draws UI       │   │    holds device state,  │    │
│  │    │                  │   │    exposes messages     │    │
│  │    │  state updates   │   │                         │    │
│  │  from state machine   │←──┤  [js sf_preset_loader]  │    │
│  │                       │   │    reads presets/*.json │    │
│  │                       │   │                         │    │
│  │                       │   │  [js sf_manifest_loader]│    │
│  │                       │   │    reads curated/*.json │    │
│  │                       │   │                         │    │
│  │                       │   │  [js sf_forge.js]       │    │
│  │                       │   │    orchestrates split + │    │
│  │                       │   │    import, calls        │    │
│  │                       │   │    LiveAPI              │    │
│  │                       │   │                         │    │
│  │                       │   │  [js sf_splitter.js]    │    │
│  │                       │   │    shells out to        │    │
│  │                       │   │    demucs/lalal backend │    │
│  └───────────────────────┘   └─────────────────────────┘    │
│                                                             │
│  Dicts:  sf_preset    (current preset JSON)                 │
│          sf_manifest  (current source manifest JSON)        │
│          sf_settings  (global splitting config)             │
│          sf_state     (runtime state: phase, progress, etc.)│
└─────────────────────────────────────────────────────────────┘
```

### Key design principle

Everything downstream of state is pure. `sf_state.js` is the single source of
truth. `v8ui` reads it and re-renders. Forge operations mutate it. There is no
two-way binding, no distributed state, no "eight things out of sync."

---

## 2. Runtime state schema

`sf_state` is a single JSON object, held in a `[dict]` so JS and patcher logic
can both read it.

```typescript
type DevicePhase =
  | { kind: 'empty' }
  | { kind: 'idle', preset: PresetRef, source: SourceRef }
  | { kind: 'forging', source: SourceRef, preset: PresetRef, phase1: Phase1State, phase2: Phase2State }
  | { kind: 'done', source: SourceRef, preset: PresetRef, tracksCreated: number, trackRange: [number, number], elapsedSec: number }
  | { kind: 'error', source: SourceRef, preset: PresetRef, error: ForgeError }

type PresetRef = {
  filename: string        // "idm_production.json"
  name: string            // "idm_production"
  displayName: string     // "IDM Production"
  version: string         // "1.0.0"
  paletteName: string     // "warm_idm"
  palettePreview: string[] // ["#E24B4A", "#A83332", "#378ADD", ...] max 6
  targetCount: number     // 11
}

type SourceRef = {
  filename: string        // "untitled_sketch_04"
  type: 'manifest' | 'audio'
  // manifest fields:
  bpm?: number
  bars?: number
  stemCount?: number
  // audio fields:
  durationSec?: number
  sampleRate?: number
}

type Phase1State = {
  active: boolean
  progress: number        // 0-1
  etaSec: number
  stems: {
    drums: 'pending' | 'splitting' | 'done'
    bass: 'pending' | 'splitting' | 'done'
    vocals: 'pending' | 'splitting' | 'done'
    other: 'pending' | 'splitting' | 'done'
  }
  engineLabel: string     // "demucs · htdemucs_ft · gpu"
  currentOp: string       // "separating vocals"
}

type Phase2State = {
  active: boolean
  targetsTotal: number
  targetsDone: number
  targets: {
    [stemName: string]: {
      [targetName: string]: 'pending' | 'creating' | 'done'
    }
  }
  currentOp: string       // "inserting beat repeat on drums/repeat"
}

type ForgeError = {
  phase: 1 | 2
  stem?: string
  target?: string
  kind: 'missing_template' | 'device_not_found' | 'split_failed' | 'api_error'
  message: string
  fix: string             // user-readable suggestion
}
```

---

## 3. Component inventory (Max objects)

### Presentation layer

| Object | Role |
|--------|------|
| `v8ui sf_ui.js @scripting_name sf_ui` | Draws all three columns: left controls, middle matrix, right button. Reads from `sf_state` dict. One outlet emits events: `preset_click`, `source_click`, `forge_click`, `cancel_click`, `settings_click`, `retry_click`. |
| `live.text @scripting_name sf_status_dot` | Bottom-left status dot (color set by message). |
| `live.comment @scripting_name sf_status_text` | Bottom-left status text. |
| `live.comment @scripting_name sf_version_text` | Bottom-right version string. |

### Logic layer

| Object | Role |
|--------|------|
| `js sf_state.js @scripting_name sf_state_mgr` | Owns state transitions. Exposes `setPreset`, `setSource`, `startForge`, `cancel`, `markPhase1Progress`, `markTargetStarted`, `markTargetDone`, `markDone`, `markError`. |
| `js sf_preset_loader.js` | Scans `~/Documents/Max 9/Packages/StemForge/presets/*.json`, parses, returns list for dropdown. |
| `js sf_manifest_loader.js` | Scans curated manifest dir (from settings). Also detects if a path is audio vs manifest. |
| `js sf_forge.js` | The engine. Drives phase 1 (calls splitter) then phase 2 (LiveAPI track creation). Emits progress events to `sf_state_mgr`. |
| `js sf_splitter.js` | Subprocess management for demucs/lalal. Uses `shell` external or `[mxj]` to spawn. |
| `js sf_settings.js` | Reads/writes global config JSON to `~/Documents/Max 9/Packages/StemForge/settings.json`. |

### Dicts

| Name | Lifetime | Purpose |
|------|----------|---------|
| `sf_preset` | Survives device reload | Currently selected preset JSON |
| `sf_manifest` | Survives device reload | Currently selected source manifest JSON |
| `sf_settings` | Persists to disk | Global config (split engine, device, dirs) |
| `sf_state` | Resets on reload | Runtime state (phase, progress) |

Preset, manifest, and settings dicts are saved via `live.text` in `Stored Only`
mode so Live remembers selections across session reloads.

---

## 4. v8ui rendering

Single `v8ui` object, 820×149 (excluding bottom status bar which uses native
Max objects). Draws entire main body based on `sf_state`.

### Render modes (one function per phase)

```javascript
// sf_ui.js — rough skeleton

var state = { kind: 'empty' };

function dict(name, key) {
  var d = new Dict(name);
  return d.get(key);
}

function refresh() {
  state = JSON.parse(dict('sf_state', 'root') || '{"kind":"empty"}');
  mgraphics.redraw();
}

function paint() {
  // clear to bg
  mgraphics.set_source_rgb(0.176, 0.176, 0.200);
  mgraphics.rectangle(0, 0, this.box.rect[2], this.box.rect[3]);
  mgraphics.fill();

  drawLeftColumn();   // preset + source selectors (always visible)

  switch (state.kind) {
    case 'empty':   drawMiddleEmpty();   break;
    case 'idle':    drawMiddleMatrix();  break;
    case 'forging':
      if (state.phase1.active) drawMiddlePhase1();
      else                     drawMiddlePhase2();
      break;
    case 'done':    drawMiddleMatrix();  break;  // same matrix, no status dots
    case 'error':   drawMiddleError();   break;
  }

  drawRightButton();  // forge/cancel/done/retry
}

function drawMiddleMatrix() {
  // iterate state.preset.stems, draw rows of colored pills
  // each pill: fill color from preset, optional status dot, chain icon
  // left column: stem name in muted text
}
```

### Mouse handling

```javascript
function onclick(x, y) {
  // hit-test columns:
  if (x < 212) {          // left column
    if (y > 8 && y < 56) outlet(0, 'preset_click');
    if (y > 78 && y < 126) outlet(0, 'source_click');
  } else if (x > 716) {   // right column (button)
    outlet(0, 'forge_click');   // or cancel/retry depending on state
  } else {                // middle column
    // pill hover → show chain tooltip (v2)
  }
}
```

Dropdowns open as native Max popup menus, NOT in v8ui. When user clicks the
preset selector area, v8ui sends `preset_click` outlet, which routes to a
`[umenu]` that opens at that location.

### Why v8ui and not live.* widgets

- The matrix needs arbitrary colored pills sized to content. `live.text` can't do that.
- Pulsing status rings during forge require frame-based animation.
- A single canvas is easier to reason about than 40+ `live.text` objects in sync.
- v8ui uses mgraphics (HiDPI-aware, crisp at all zooms).

---

## 5. The forge operation

Handled by `sf_forge.js`. Two phases.

### Phase 1: splitting (only if source is audio)

```javascript
function startForge() {
  var state = getState();
  if (state.source.type === 'audio') {
    runSplit(state.source.path, onSplitProgress, onSplitComplete);
  } else {
    startImport(state.source.manifestPath);
  }
}

function runSplit(audioPath, onProgress, onComplete) {
  var settings = loadSettings();
  var cmd = buildSplitCommand(settings.engine, settings.model, settings.device, audioPath);

  // Shell out via [shell] or [mxj] — depends on your infra.
  // Parse stdout for progress lines (demucs emits "Separated tracks: X.X%").
  // For each stem as it completes, update sf_state.phase1.stems[stem] = 'done'.

  var proc = spawn(cmd);
  proc.stdout.on('line', function(line) {
    var progress = parseProgress(line);
    if (progress) {
      dict('sf_state', 'root.phase1.progress', progress.overall);
      dict('sf_state', 'root.phase1.currentOp', progress.stem ? 'separating ' + progress.stem : '...');
      notifyUI();
    }
  });
  proc.on('close', function(code) {
    if (code !== 0) return markError({ phase: 1, kind: 'split_failed', message: 'Demucs exited with code ' + code });
    var manifestPath = buildManifestFromSplit(audioPath, settings);
    startImport(manifestPath);
  });
}
```

### Phase 2: importing

Uses LiveAPI. This is the existing `loadSong()` logic from your codebase, with
state updates wrapped around it.

```javascript
function startImport(manifestPath) {
  var manifest = JSON.parse(File.read(manifestPath));
  var preset = JSON.parse(dict('sf_preset', 'root'));

  setPhase2Active();

  var trackOffset = getCurrentTrackCount();
  var trackIndex = trackOffset;

  for (var stemName in preset.stems) {
    for (var target of preset.stems[stemName].targets) {
      markTargetStarted(stemName, target.name);
      try {
        createTrackFor(stemName, target, manifest, trackIndex);
        loadClipsIntoTrack(trackIndex, manifest.stems[stemName].clips);
        insertDevicesOnTrack(trackIndex, target.chain);
        markTargetDone(stemName, target.name);
        trackIndex++;
      } catch (e) {
        rollback(trackOffset, trackIndex);
        return markError(mapToForgeError(e, stemName, target.name));
      }
    }
  }

  markDone(trackOffset, trackIndex - 1);
}

function createTrackFor(stemName, target, manifest, idx) {
  var live = new LiveAPI('live_set');
  live.call('create_audio_track', idx);
  var track = new LiveAPI('live_set tracks ' + idx);
  track.set('name', formatTrackName(manifest.sourceName, stemName, target.name));
  track.set('color', hexToAbletonColor(target.color));
}

function formatTrackName(source, stem, target) {
  // Short form: "{source} {target}" — stem is implicit from track color
  // e.g. "sketch_04 loops", "sketch_04 crushed", "sketch_04 phrases"
  var template = loadSettings().trackPrefix; // "{source} {target}"
  return template
    .replace('{source}', source)
    .replace('{target}', target);
}
```

### Rollback on error

Critical: if forge fails mid-operation, we delete any tracks created during
this forge. User should see "session unchanged" — not a partial mess.

```javascript
function rollback(offsetStart, offsetEnd) {
  var live = new LiveAPI('live_set');
  for (var i = offsetEnd - 1; i >= offsetStart; i--) {
    live.call('delete_track', i);
  }
}
```

---

## 6. The preset file format (JSON, post-compile)

The YAML → JSON compile step (`stemforge generate-pipeline-json`) produces:

```json
{
  "name": "idm_production",
  "displayName": "IDM Production",
  "version": "1.0.0",
  "description": "Beat Repeat, Echo, Grain Delay, Decapitator",
  "palette": "warm_idm",
  "stems": {
    "drums": {
      "targets": [
        {
          "name": "loops",
          "type": "clips",
          "color": "#E24B4A",
          "chain": []
        },
        {
          "name": "rack",
          "type": "rack",
          "color": "#C53F3E",
          "chain": [
            { "insert": "Compressor", "params": { "Threshold": 0.55, "Ratio": 0.75 } }
          ]
        }
        ...
      ]
    },
    ...
  }
}
```

### Palette resolution (future refactor)

When you move to palette-first YAML:

```yaml
preset:
  palette: warm_idm

stems:
  drums:
    family: red
    targets:
      - name: loops
      - name: rack
      - name: crushed
      ...
```

The builder reads `palettes/warm_idm.yaml`:

```yaml
families:
  red:   ["#E24B4A", "#C53F3E", "#A83332", "#8B2827", "#6E1F1E", "#501615"]
  blue:  ["#378ADD", "#2C6FB0", "#215485", ...]
  amber: ["#EF9F27", "#BA7517", "#854F0B", ...]
  teal:  ["#1D9E75", "#167559", "#0F553F", ...]
```

And assigns shades 0..N-1 to targets 0..N-1. If a stem has more targets than
the family has shades, interpolate or error. Ship 3–4 palettes:
`warm_idm`, `cool_ambient`, `monochrome_grid`, maybe `high_contrast_live`.

The preset JSON still emits resolved hex values — v8ui doesn't need to know
about palettes.

---

## 7. Global settings

`~/Documents/Max 9/Packages/StemForge/settings.json`:

```json
{
  "splitting": {
    "engine": "demucs",
    "model": "htdemucs_ft",
    "device": "gpu",
    "outputSampleRate": 46875,
    "outputBitDepth": 16,
    "cacheSplits": true
  },
  "workflow": {
    "trackPrefix": "{source} {target}",
    "manifestDir": "~/stemforge/curated",
    "presetDir": "~/Documents/Max 9/Packages/StemForge/presets"
  }
}
```

The settings overlay (state 9) reads and writes this file. Changes apply
globally — not stored per-preset, not per-source. Next forge uses the new
values.

The overlay is accessible via the device's title bar icons (gear icon in
top right of the Ableton device header) OR via a keyboard shortcut defined
in the Max patch. For v1, the gear icon approach is simplest.

---

## 8. Dropdown UX

### Preset dropdown

- Opens as a native Max `[umenu]` positioned below the preset selector.
- Populated by `sf_preset_loader.js` which reads all `*.json` in the preset dir.
- Each entry: palette strip + display name + one-liner.
- Bottom entry: "⟲ Reload presets" which re-scans the directory.
- On selection: loads preset JSON into `sf_preset` dict, transitions to idle (if source also loaded).

### Source dropdown

- Three sections:
  1. **Manifests** — parsed from `curated/manifest.json` index
  2. **Browse for audio...** — opens Max file dialog (`[opendialog]`)
  3. Bottom: settings gear icon inline
- On manifest selection: loads manifest JSON, sets source type to 'manifest'.
- On audio file selection: stores path, sets source type to 'audio'. Does NOT split yet — split happens on FORGE.

---

## 9. Status bar text patterns

```
Empty:        "waiting — pick a preset and source"
Idle (man):   "ready · manifest loaded · stems cached"
Idle (audio): "ready · audio source · will split then import"
Phase 1:      "splitting · {engine} · {stem} {pct}%"
Phase 2:      "forging · {stem}/{target} — {current op}"
Done:         "forge complete · {elapsed} · tracks {start}–{end} · ⌘Z to undo"
Error:        "error · {short reason} — session unchanged"
```

Status dot colors:
- Grey: empty/waiting
- Green: ready/done
- Amber (pulsing): active (forging)
- Red: error
- Purple: informational (dropdowns open, settings open)

---

## 10. Build & ship checklist

1. **Presentation**
   - [ ] v8ui renders all 9 states from sf_state dict
   - [ ] Pill layout correctly truncates when preset has too many targets to fit
   - [ ] Click regions hit the right outlets
   - [ ] Status bar native objects wired up
   - [ ] Device width locked at 820, height 169 (non-negotiable — 169 is the M4L fixed height)
   - [ ] All x/y coordinates integers, snapped to 4px grid where possible
   - [ ] Open in Presentation mode by default

2. **State management**
   - [ ] sf_state.js validates all transitions (can't go from 'empty' to 'forging')
   - [ ] Dicts are live.text-backed so they persist across reload
   - [ ] State changes trigger v8ui redraw via outlet

3. **Forge engine**
   - [ ] Splitter subprocess integration works for demucs on GPU
   - [ ] LiveAPI track creation with correct track colors (Ableton uses a 26-color palette — need hex→index mapping)
   - [ ] Rollback on error deletes only this forge's tracks
   - [ ] Progress events emitted at least every 500ms

4. **Preset & manifest loading**
   - [ ] Directory scan with [folder] object watches for new files
   - [ ] Reload presets action re-scans without device restart
   - [ ] Malformed preset JSON shows error, doesn't crash

5. **Settings**
   - [ ] Settings JSON persisted on disk, survives device reload
   - [ ] Gear icon opens overlay
   - [ ] Overlay blocks interaction with main UI until closed

6. **Quality**
   - [ ] Freeze device before distribution (Collect All equivalent in Max)
   - [ ] Parameters have short/long names, no auto-appended [1] suffixes
   - [ ] Test at 100%, 125%, 150%, 200% HiDPI scaling
   - [ ] Test with preset containing 20+ targets (overflow handling)

---

## 11. Build order (Monday morning to first ship)

Day 1 — scaffolding
- v8ui renders the empty state and idle state with a hardcoded preset JSON
- Preset and source dropdowns wire up (read from disk, populate umenus)
- Clicking FORGE from idle fires an outlet — no actual forge yet

Day 2 — phase 2 (the important one)
- sf_forge.js does the LiveAPI track creation end-to-end for a manifest source
- Progress events update sf_state, v8ui re-renders
- Rollback works on injected failure

Day 3 — phase 1
- Subprocess management for demucs (GPU assumed since you're on M1/M2 or similar)
- Progress parsing from demucs stdout
- Manifest generation from split output

Day 4 — polish
- Done state, error state, settings overlay
- Palette strips in dropdown
- Status bar text patterns

Day 5 — build
- Freeze device
- Test on a clean Ableton session
- Ship

After ship
- Build the palette-based YAML refactor separately; doesn't affect the device.
- Future editability (clickable pills → chain editor overlay): design lands naturally.
- Hover tooltips on pills showing the full chain.

---

## 12. Ableton-native color palette

**Decision:** preset target colors are restricted to Ableton's native 26-color
track palette. No arbitrary hex. This guarantees 1:1 fidelity between the
device's matrix pills and Live's session view track colors.

### The 26 Ableton colors (Live 12)

Indexed 0–25 in Live's color picker. Stored in `stemforge/data/ableton_colors.json`:

```json
[
  { "index": 0,  "hex": "#FF94A6", "name": "pink"         },
  { "index": 1,  "hex": "#FFA529", "name": "orange"       },
  { "index": 2,  "hex": "#CC9D34", "name": "brown"        },
  { "index": 3,  "hex": "#F7F47C", "name": "yellow"       },
  { "index": 4,  "hex": "#BFFB00", "name": "lime"         },
  { "index": 5,  "hex": "#1AFF2F", "name": "green"        },
  { "index": 6,  "hex": "#25FFA8", "name": "mint"         },
  { "index": 7,  "hex": "#5CFFE8", "name": "cyan"         },
  { "index": 8,  "hex": "#8BC5FF", "name": "sky"          },
  { "index": 9,  "hex": "#5480E4", "name": "blue"         },
  { "index": 10, "hex": "#92A7FF", "name": "periwinkle"   },
  { "index": 11, "hex": "#D86CE4", "name": "magenta"      },
  { "index": 12, "hex": "#E553A0", "name": "hot_pink"     },
  { "index": 13, "hex": "#FFFFFF", "name": "white"        },
  { "index": 14, "hex": "#FF3A34", "name": "red"          },
  { "index": 15, "hex": "#F06E24", "name": "burnt_orange" },
  { "index": 16, "hex": "#A13C00", "name": "dark_brown"   },
  { "index": 17, "hex": "#C7C42D", "name": "olive"        },
  { "index": 18, "hex": "#429130", "name": "forest"       },
  { "index": 19, "hex": "#00A649", "name": "kelly"        },
  { "index": 20, "hex": "#009D7A", "name": "teal"         },
  { "index": 21, "hex": "#009DB7", "name": "slate_blue"   },
  { "index": 22, "hex": "#3C55C7", "name": "indigo"       },
  { "index": 23, "hex": "#3C21A0", "name": "dark_indigo"  },
  { "index": 24, "hex": "#AB3CBF", "name": "purple"       },
  { "index": 25, "hex": "#AF2E58", "name": "crimson"      }
]
```

(Verify these hex values against Live 12's actual palette before shipping —
Ableton has shifted them slightly between major versions. Pull them from a
current Live session by inspecting `Track.color` on tracks you've color-picked.)

### Updated preset YAML schema

Target `color` must reference a palette entry by index OR name, not hex:

```yaml
stems:
  drums:
    targets:
      - name: "loops"
        color: red             # or: 14
        chain: []
      - name: "crushed"
        color: crimson         # or: 25
        chain: [...]
```

The builder emits the resolved hex into the JSON (for v8ui rendering) plus the
Ableton color index (for the LiveAPI call). No approximation, no rounding.

### Updated preset JSON (post-compile)

```json
{
  "targets": [
    {
      "name": "loops",
      "color": { "name": "red", "index": 14, "hex": "#FF3A34" },
      "chain": []
    }
  ]
}
```

### Updated track creation

```javascript
function createTrackFor(stemName, target, manifest, idx) {
  var live = new LiveAPI('live_set');
  live.call('create_audio_track', idx);
  var track = new LiveAPI('live_set tracks ' + idx);
  track.set('name', formatTrackName(manifest.sourceName, target.name));
  track.set('color_index', target.color.index);   // exact match, no rounding
}
```

### Palette design guidance

When authoring presets, pick a coherent subset of the 26 Ableton colors per
stem family. Example `warm_idm` palette, built entirely from native colors:

```yaml
# palettes/warm_idm.yaml
families:
  drums:  [red, burnt_orange, crimson, dark_brown, hot_pink, pink]
  bass:   [blue, indigo, dark_indigo]
  vocals: [orange, yellow, olive]
  other:  [teal, kelly, forest, mint]
```

When a stem has more targets than its family has colors, the builder errors at
compile time — forces the preset author to either reduce targets or pick a
family with more variety. Better to catch this at build than surprise the user
with a duplicate color at runtime.

### Trade-offs accepted

- Can't use arbitrary brand colors. Fine — your Ableton session view dictates
  the aesthetic anyway.
- Ableton's 26 colors skew toward saturated/bright. Darker/muted palettes
  require creative use of the limited darker options (`dark_brown`,
  `dark_indigo`, `forest`, `dark_indigo`).
- Future Live versions could shift the palette. Pin the version in
  `ableton_colors.json` and document that updating Live may require updating
  this file.

---

## 13. Known trade-offs

- **One canvas for the matrix means the whole thing redraws per frame during animations.** Fine for a 820×149 canvas on modern hardware. If perf ever becomes an issue, split into two v8uis (static background + animated overlay).
- **Forge is synchronous from the user's POV.** They can't do other things during a split. Max can technically background work via `[mxj]` threads, but we don't need to — the cancel button is sufficient.
- **Preset JSON is re-read on every dropdown open.** That's fine; they're small. If you ever have 100+ presets, add a cache.
- **Ableton-native palette constrains preset authoring.** Intentional (see section 12) — trades creative freedom for zero approximation.

---

## 14. Future evolution (not v1)

- Click pill → chain editor overlay (param tweaking without YAML edit)
- Save overrides back to preset (write-back to YAML)
- Multi-source batch forge (queue of sources, forge all)
- Per-stem preview audio player
- AB compare presets (forge with preset A, then with preset B, see which you like)
- Device chain library (save a chain as reusable, reference by name across presets)
