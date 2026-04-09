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

### Known Limitations

1. **Track positioning**: `Song.duplicate_track` inserts at source+1, so duplicated template tracks don't end up in a tidy group. Manually group them after loading.

2. **Simpler sample loading**: `load_device` may not work for all Ableton versions. Fallback: drag from browser.

3. **VST parameter indices**: The pipeline YAML uses descriptive param names for readability, but the M4L device sets params by sequential index. Verify your indices using the M4L "Inspect" workflow in setup.md.

4. **LO-FI-AF section reordering**: Cannot be done via API. Set up section order in template tracks manually.
