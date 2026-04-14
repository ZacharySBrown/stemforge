## Integrated Forge Device (StemForgeDevice.maxpat)

One-button split → slice → curate → play pipeline, driven from an Ableton
audio clip. See `build_guide_device.html` for step-by-step setup.

Files:
- `StemForgeDevice.maxpat` — Max for Live Audio Effect patch (open in Max, save-as `.amxd`)
- `stemforge_bridge.js` — Node-for-Max script; spawns `stemforge forge`, streams JSON progress
- `stemforge_lom.js` — classic Max JS; reads clip warp markers/time sig via LOM, writes temp JSON
- `package.json` — declares `stemforge_bridge.js` as the node.script entry
- `build_guide_device.html` — user-facing build/install guide

Python path discovery: the bridge reads `~/.stemforge/python_path` (written by
`install.sh`). It spawns `<python> -m stemforge.cli forge <audio> --analysis
<tmp.json> --n-bars N --strategy S` and parses newline-delimited JSON events
(`started`, `progress`, `complete`) off stdout. On `complete`, it walks
`<output_dir>/curated/<focus_stem>/` and emits one `load <wav> <idx>` message
per curated bar into `polybuffer~ sf_bars`.

The LOM read is split into a classic `[js]` object because `node.script`
cannot access the Live Object Model directly.

---

## Max Patch Structure for StemForgeLoader.amxd

The patch contains:

[midiin] → discard (device needs to be instrument type to sit on MIDI track)

[loadbang] → [js stemforge_loader.js] (main logic)
           → [message setPipelinesDir /path/to/pipelines] (set on load)
           → [message loadPipeline default]

UI Objects:
  [umenu] "Pipeline" — lists available pipelines from PIPELINES_DIR
          → [js stemforge_loader.js] via message "loadPipeline $1"

  [toggle] "Watch" — starts/stops folder watching
           → [js stemforge_loader.js] via message "startWatch"/"stopWatch"

  [button] "Load Latest" — manual trigger
           → [bang] → [js stemforge_loader.js]

  [textedit] status — receives output from outlet 0 of js object
           displays last status message

  [number] BPM display — receives bpm from manifest after load

Connections:
  [js stemforge_loader.js] outlet 0 → [textedit] status display
  [js stemforge_loader.js] outlet 1 → [print] "Load complete"

Save as: m4l/StemForgeLoader.amxd

### How to Build

1. Open Max for Live (inside Ableton: create a new MIDI track → drag "Max Instrument" from the browser)
2. Click the wrench icon to open the Max editor
3. Delete any default objects
4. Build the patch as described above:
   - Add a `[js]` object, double-click it, set the filename to `stemforge_loader.js`
   - Copy `stemforge_loader.js` into the same folder as the `.amxd` file, or set the search path
   - Add UI objects (button, toggle, umenu, textedit) and connect them
   - Add a `[loadbang]` → `[message setPipelinesDir ...]` chain
5. Save the device as `StemForgeLoader.amxd` in the `m4l/` folder
6. Freeze the device (File → Freeze Device) to bundle the JS file inside

### Installation

1. Drag `StemForgeLoader.amxd` onto a MIDI track in your StemForge Templates set
2. Name that track "SF Loader"
3. The device will auto-watch `~/stemforge/processed/` for new stems
4. Click "Load Latest" to manually trigger loading

---

## Automated Template Builder (stemforge_template_builder.js)

Creates all 7 StemForge template tracks automatically — tracks, Ableton devices,
parameters, colors — instead of building them by hand from setup.md.

### Quick Start

1. Open your StemForge Templates set (or any Live set)
2. Create a MIDI track, drag "Max Instrument" onto it
3. Click wrench to open the Max editor
4. Add a `[js]` object, set filename to `stemforge_template_builder.js`
5. Add a `[button]` and connect it to the `[js]` inlet
6. Add a `[textedit]` and connect `[js]` outlet 0 to it (status log)
7. Click the button — watch the status log as tracks are built

### What It Does

- Creates 7 tracks (6 audio + 1 MIDI) with correct names and colors
- Loads Ableton native devices (Compressor, EQ Eight, Reverb, Utility) via Browser API
- Loads VST3 plugins (Decapitator, LO-FI-AF, EchoBoy, etc.) via Browser search
- Sets Ableton device parameters (ratio, attack, frequencies, etc.)
- Logs any devices or parameters it can't find

### After Running

1. VST3 plugin parameters are left at defaults — dial them in per setup.md
2. Group all 7 tracks: select them, Cmd+G, name "StemForge Templates", color grey
3. Remove or bypass the builder device — it's a one-time setup tool

### Troubleshooting

- **"NOT FOUND: PluginName"** — the plugin isn't installed, or its Browser name
  differs from what the script searches for. Edit the `search` field in the
  TEMPLATES array in `stemforge_template_builder.js` to match your Browser.
- **Param not found** — Ableton device parameter names can vary between versions.
  Use the M4L Inspect workflow (select device, read param names in Max console)
  to find the correct names, then update the `params` object in the script.

---

### Known Limitations

1. **Track positioning**: `Song.duplicate_track` inserts at source+1, so duplicated template tracks don't end up in a tidy group. Manually group them after loading.

2. **Simpler sample loading**: `load_device` may not work for all Ableton versions. Fallback: drag from browser.

3. **VST parameter indices**: The pipeline YAML uses descriptive param names for readability, but the M4L device sets params by sequential index. Verify your indices using the M4L "Inspect" workflow in setup.md.

4. **LO-FI-AF section reordering**: Cannot be done via API. Set up section order in template tracks manually.
