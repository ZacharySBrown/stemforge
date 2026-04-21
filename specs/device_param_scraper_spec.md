# StemForge — Live Device Parameter Scraper

**Status:** Draft spec
**Target:** Standalone Max for Live utility device, run once to produce a JSON reference of all native Live audio + MIDI effect parameters.
**Output:** `stemforge/data/live_devices.json` in the repo, used by the processing config loader for validation and by the human as an authoring reference.
**Live version:** 12.3+

## Purpose

Enumerate every native Live audio effect and MIDI effect's parameters (name, original_name, range, quantization, enum values) and dump to JSON. The JSON becomes the source of truth for:

1. **Config validation.** StemForge processing configs reference devices by name and parameters by name. The loader can validate before touching the session.
2. **Authoring reference.** When writing a new config, the JSON is a searchable catalog: "What parameters does Saturator have? What are Drive's min/max?"
3. **Quantized parameter translation.** Config files use readable strings (`"Soft Sine"`); the loader looks up the index in the JSON and sets the parameter numerically.

Run once per Live version. Output is stable until Live updates.

## Scope

**In scope:**
- All native Live 12 **audio effects** (applied to audio tracks)
- All native Live 12 **MIDI effects** (applied to MIDI tracks before an instrument)

**Out of scope:**
- Instruments (Simpler, Drum Rack, Operator, Wavetable, etc.) — out of scope because StemForge uses only Simpler and Drum Rack, which are handled by base spec and song loader directly.
- VST3 / AU plugins — their parameters are user-configured per-plugin and not catalogable via this approach. StemForge handles those via template tracks (see processing config spec).
- Max for Live devices — can't be inserted via `insert_device`.

## Device list

Build the list statically in the scraper. If Ableton adds a device in a future Live release, update the list and re-run.

### Audio effects (~36 devices in Live 12)

```javascript
const AUDIO_EFFECTS = [
    "Amp",
    "Auto Filter",
    "Auto Pan",
    "Beat Repeat",
    "Cabinet",
    "Channel EQ",
    "Chorus-Ensemble",
    "Compressor",
    "Corpus",
    "Delay",
    "Drum Buss",
    "Dynamic Tube",
    "Echo",
    "EQ Eight",
    "EQ Three",
    "Erosion",
    "External Audio Effect",
    "Filter Delay",
    "Frequency Shifter",
    "Gate",
    "Glue Compressor",
    "Grain Delay",
    "Hybrid Reverb",
    "Limiter",
    "Looper",
    "Multiband Dynamics",
    "Overdrive",
    "Pedal",
    "Phaser-Flanger",
    "Redux",
    "Resonators",
    "Reverb",
    "Roar",
    "Saturator",
    "Shifter",
    "Simple Delay",
    "Spectral Blur",
    "Spectral Resonator",
    "Spectrum",
    "Tuner",
    "Utility",
    "Vinyl Distortion",
    "Vocoder",
];
```

### MIDI effects (~12 devices in Live 12)

```javascript
const MIDI_EFFECTS = [
    "Arpeggiator",
    "Chord",
    "CC Control",
    "Envelope",
    "Envelope Follower",
    "Expression Control",
    "LFO",
    "MIDI Monitor",
    "Note Echo",
    "Note Length",
    "Pitch",
    "Random",
    "Scale",
    "Shaper",
    "Velocity",
];
```

Note: exact names must match Live 12's UI labels. Some names have evolved between versions (e.g., "Chorus" vs "Chorus-Ensemble"). If a device fails to insert, log it and move on; don't abort.

## Output schema

`stemforge/data/live_devices.json`:

```json
{
  "live_version": "12.3.5",
  "scraped_at": "2026-04-20T14:30:00Z",
  "audio_effects": {
    "Saturator": {
      "class_name": "Saturator",
      "category": "audio_effect",
      "parameters": [
        {
          "index": 0,
          "name": "Device On",
          "original_name": "Device On",
          "min": 0.0,
          "max": 1.0,
          "default_value": 1.0,
          "is_quantized": true,
          "value_items": ["Off", "On"]
        },
        {
          "index": 1,
          "name": "Drive",
          "original_name": "Drive",
          "min": 0.0,
          "max": 36.0,
          "default_value": 0.0,
          "is_quantized": false,
          "value_items": null
        },
        {
          "index": 2,
          "name": "Type",
          "original_name": "Type",
          "min": 0.0,
          "max": 5.0,
          "default_value": 0.0,
          "is_quantized": true,
          "value_items": ["Analog Clip", "Soft Sine", "Medium Curve", "Hard Curve", "Sinoid Fold", "Digital Clip"]
        }
        // ... all other params
      ]
    },
    "EQ Eight": { ... },
    "Compressor": { ... }
  },
  "midi_effects": {
    "Arpeggiator": { ... }
  },
  "errors": {
    "SomeDeviceName": "Error message if insertion failed"
  }
}
```

Alphabetically sorted by device name for diff-friendly commits.

## Implementation

### Device: `StemForge_ParamScraper.amxd`

M4L **audio effect** device (because we need both audio and MIDI tracks available in the session; device itself lives on a dedicated "scraper host" track but interacts with other tracks).

### UI

- **Status display:** current device being scraped, progress counter (`Scraping: Saturator [15/51]`)
- **"Scrape All" button**
- **"Scrape Audio Effects" button**
- **"Scrape MIDI Effects" button**
- **Output path field:** where to write the JSON (default: `~/Documents/StemForge/live_devices.json`, configurable)

### Setup requirements (documented in device info area)

Before clicking Scrape:
1. Create a blank Live set (or use a scratch set)
2. Delete all tracks except one audio track and one MIDI track
3. On the MIDI track, insert Simpler (or any instrument) — required because MIDI effects can only be inserted on a MIDI track that already has an instrument
4. Insert `StemForge_ParamScraper.amxd` onto any track (it can be elsewhere — it drives the other two)
5. Name the audio track `SF_Scraper_Audio` and the MIDI track `SF_Scraper_MIDI` (scraper finds tracks by name)
6. Click Scrape

### Core enumeration function

```javascript
// In the M4L device's JS

function scrapeDevice(trackIdx, deviceName) {
    const track = new LiveAPI(null, `live_set tracks ${trackIdx}`);
    
    // Insert device at end of chain
    const deviceCountBefore = track.getcount("devices");
    try {
        track.call("insert_device", deviceName);
    } catch (e) {
        return { error: `insert_device failed: ${e}` };
    }
    
    const deviceCountAfter = track.getcount("devices");
    if (deviceCountAfter === deviceCountBefore) {
        return { error: "insert_device returned but device count unchanged" };
    }
    const deviceIdx = deviceCountAfter - 1;
    
    // Enumerate parameters
    const device = new LiveAPI(null, `live_set tracks ${trackIdx} devices ${deviceIdx}`);
    const className = device.get("class_name")[0];
    const paramCount = device.getcount("parameters");
    
    const params = [];
    for (let i = 0; i < paramCount; i++) {
        const p = new LiveAPI(null, `live_set tracks ${trackIdx} devices ${deviceIdx} parameters ${i}`);
        
        const isQuantized = p.get("is_quantized")[0] === 1;
        
        params.push({
            index: i,
            name: p.get("name")[0],
            original_name: p.get("original_name")[0],
            min: p.get("min")[0],
            max: p.get("max")[0],
            default_value: p.get("default_value")[0],
            is_quantized: isQuantized,
            value_items: isQuantized ? p.get("value_items") : null,
        });
    }
    
    // Clean up: delete the device we just inserted
    track.call("delete_device", deviceIdx);
    
    return {
        class_name: className,
        parameters: params,
    };
}
```

### Orchestration

```javascript
async function scrapeAll() {
    const audioTrackIdx = findTrackIndexByName("SF_Scraper_Audio");
    const midiTrackIdx = findTrackIndexByName("SF_Scraper_MIDI");
    
    if (audioTrackIdx === -1 || midiTrackIdx === -1) {
        updateStatus("ERROR: need tracks named SF_Scraper_Audio and SF_Scraper_MIDI");
        return;
    }
    
    const result = {
        live_version: getLiveVersion(),
        scraped_at: new Date().toISOString(),
        audio_effects: {},
        midi_effects: {},
        errors: {},
    };
    
    // Audio effects
    for (let i = 0; i < AUDIO_EFFECTS.length; i++) {
        const deviceName = AUDIO_EFFECTS[i];
        updateStatus(`Scraping audio: ${deviceName} [${i + 1}/${AUDIO_EFFECTS.length}]`);
        
        const scraped = scrapeDevice(audioTrackIdx, deviceName);
        if (scraped.error) {
            result.errors[deviceName] = scraped.error;
        } else {
            result.audio_effects[deviceName] = {
                ...scraped,
                category: "audio_effect",
            };
        }
        
        // Brief pause to let Live settle (avoid LOM race conditions)
        await sleep(50);
    }
    
    // MIDI effects
    for (let i = 0; i < MIDI_EFFECTS.length; i++) {
        const deviceName = MIDI_EFFECTS[i];
        updateStatus(`Scraping MIDI: ${deviceName} [${i + 1}/${MIDI_EFFECTS.length}]`);
        
        const scraped = scrapeDevice(midiTrackIdx, deviceName);
        if (scraped.error) {
            result.errors[deviceName] = scraped.error;
        } else {
            result.midi_effects[deviceName] = {
                ...scraped,
                category: "midi_effect",
            };
        }
        
        await sleep(50);
    }
    
    // Sort alphabetically for diff-friendliness
    result.audio_effects = sortObjectKeys(result.audio_effects);
    result.midi_effects = sortObjectKeys(result.midi_effects);
    result.errors = sortObjectKeys(result.errors);
    
    // Write to disk
    const outputPath = getOutputPath();
    writeJSON(outputPath, result);
    updateStatus(`Done. Wrote ${Object.keys(result.audio_effects).length} audio + ${Object.keys(result.midi_effects).length} MIDI devices to ${outputPath}`);
}

function sortObjectKeys(obj) {
    const sorted = {};
    Object.keys(obj).sort().forEach(k => { sorted[k] = obj[k]; });
    return sorted;
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
```

### File writing

Use Node for Max (`require('fs')`) for file I/O. Simpler than Max's native `[filein]`/`[text]` approach for JSON.

```javascript
const fs = require('fs');
const path = require('path');

function writeJSON(outputPath, data) {
    // Ensure directory exists
    const dir = path.dirname(outputPath);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
    
    fs.writeFileSync(outputPath, JSON.stringify(data, null, 2), 'utf8');
}
```

### Live version detection

```javascript
function getLiveVersion() {
    const app = new LiveAPI(null, "live_app");
    const major = app.call("get_major_version");
    const minor = app.call("get_minor_version");
    const bugfix = app.call("get_bugfix_version");
    return `${major}.${minor}.${bugfix}`;
}
```

## Timing expectations

Per-device overhead: ~100-500ms (insertion + enumeration + deletion). For the full list (~50 devices), expect **30-90 seconds total runtime**. Show progress in the UI so it doesn't feel frozen.

If any device takes more than ~5 seconds, assume it's stuck and log a timeout error. Shouldn't happen with native devices, but VST-heavy systems occasionally misbehave.

## Handling quirks

**Devices that fail to insert.** Some names might not match Live 12's current UI labels exactly. Catch the error, log it to `errors`, move on. You'll iterate on the device list over time.

**Instrument dependency on MIDI tracks.** MIDI effects can only be inserted when the MIDI track has an instrument. The setup requires Simpler (or any instrument) at index 0. When the scraper inserts a MIDI effect, it'll land at index 1 or later — the scraper uses `getcount("devices") - 1` which naturally handles this.

**Utility, EQ Three etc. work on both audio and MIDI tracks with instruments.** The scraper only inserts them on the audio track — no need to double-catalog.

**Quantized value_items list sometimes empty.** If `is_quantized` is 1 but `value_items` returns empty, store `null` rather than an empty array. Some parameters are quantized (integer-stepped) without having discrete labels.

**Parameter names can contain special characters.** Colons, slashes, parentheses. Keep them as-is in the JSON — don't sanitize. Config validator does exact string match.

**Device version drift across Live updates.** "Chorus" became "Chorus-Ensemble" in Live 11. If you update Live and re-scrape, diff the JSON output — new parameters or renamed devices will show up clearly.

## Optional: diff against previous scrape

Useful but not critical. If previous JSON exists at the output path, read it, compare, and print a summary of differences:

- New devices
- Removed devices
- New parameters on existing devices
- Renamed parameters (match by index + `original_name`)
- Changed ranges

This is a nice-to-have for detecting breaking changes after Live updates. Skip for v1; add if you update Live and want to diff.

## Consuming the JSON in other specs

**Processing config validator** (in `processing_config_spec.md`):

```javascript
function validateChain(chain, deviceCatalog) {
    const errors = [];
    for (const step of chain) {
        if (!step.insert) continue;  // template references handled separately
        
        const device = deviceCatalog.audio_effects[step.insert] 
                    || deviceCatalog.midi_effects[step.insert];
        if (!device) {
            errors.push(`Unknown device: ${step.insert}`);
            continue;
        }
        
        for (const paramName of Object.keys(step.params || {})) {
            const param = device.parameters.find(p => 
                p.name === paramName || p.original_name === paramName);
            if (!param) {
                errors.push(`${step.insert} has no parameter "${paramName}"`);
            }
            // Could also validate value ranges and quantized enum strings here
        }
    }
    return errors;
}
```

**Quantized enum string translation:**

```javascript
function translateParamValue(device, paramName, value) {
    const param = device.parameters.find(p => 
        p.name === paramName || p.original_name === paramName);
    
    if (param.is_quantized && typeof value === "string" && param.value_items) {
        const idx = param.value_items.indexOf(value);
        if (idx === -1) {
            throw new Error(`"${value}" not valid for ${paramName}. Options: ${param.value_items.join(", ")}`);
        }
        return idx;
    }
    return value;
}
```

Config author writes:
```yaml
- insert: "Saturator"
  params:
    Drive: 18.0
    Type: "Soft Sine"     # readable
```

Loader translates "Soft Sine" → 1 via the catalog.

## Acceptance

1. Run the scraper with an audio track + a MIDI track (with Simpler) set up correctly.
2. After 30-90 seconds, it writes `live_devices.json` with ~50 devices enumerated.
3. Open the JSON. Verify: Saturator has "Drive", "Type", "Output" parameters with reasonable ranges; Type shows `value_items: ["Analog Clip", "Soft Sine", ...]`; Arpeggiator has "Rate", "Groove", "Gate" etc.
4. `errors` section is empty, or contains only devices you know are misnamed (fix the list and re-run).
5. Re-running produces identical output (modulo `scraped_at`).
6. Processing config loader can load the JSON and use it for validation.

## v1 out of scope

- **Instruments.** StemForge doesn't use Operator/Wavetable/etc. If needed later, extend device list with instrument names and run on a MIDI track (no pre-existing instrument required — instruments replace whatever's there).
- **Racks.** Audio Effect Rack, Instrument Rack, Drum Rack have dynamic parameter counts (macros). Not catalog-able statically; user-configured.
- **VSTs.** Per-plugin, user-configured. Handled via template track pattern in processing config spec.
- **Cross-version diff.** Nice to have when you update Live. Add later if useful.

## Implementation order

1. Scaffolding: M4L device, UI, status text, Scrape button.
2. Setup track detection (find `SF_Scraper_Audio`, `SF_Scraper_MIDI` by name). Show clear error if missing.
3. Single-device scrape: `scrapeDevice` function, hardcoded to "Saturator", verify output JSON looks right.
4. Loop over all audio effects, accumulate results.
5. Loop over MIDI effects.
6. File writing via Node for Max.
7. Alphabetical sort + final JSON write.
8. Polish: progress UI, error handling, Live version field.

Should be a 2-3 hour build.
