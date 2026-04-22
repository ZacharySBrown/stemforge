# StemForge Config-Driven Song Loader

> How presets, processing configs, and the M4L loader work together to create
> per-stem tracks with effect chains in Ableton Live 12.3+.

---

## Architecture

```
                     ┌─────────────────────────┐
                     │   presets/               │
                     │   idm_production.yaml    │  ← YAML preset (human-editable)
                     │   clean.yaml             │
                     └──────────┬──────────────┘
                                │ stemforge generate-pipeline-json
                                ▼
                     ┌─────────────────────────┐
                     │   presets/               │
                     │   idm_production.json    │  ← compiled JSON
                     │   clean.json             │
                     └──────────┬──────────────┘
                                │ deployed to Max Package
                                ▼
┌──────────────┐    ┌─────────────────────────┐    ┌──────────────────────┐
│  M4L Device  │    │  ~/Documents/Max 9/     │    │  curated/            │
│              │◄───│  Packages/StemForge/    │    │  manifest.json       │
│  [Preset ▼]  │    │  presets/*.json          │    │  (WAV paths, stems,  │
│  [Load]      │    └─────────────────────────┘    │   BPM, bar positions)│
│  [FORGE]     │                                    └──────────┬───────────┘
└──────┬───────┘                                               │
       │ loadSong()                                            │
       │ reads preset from sf_preset dict ◄────────────────────┘
       │ reads content from sf_manifest dict
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Ableton Live Session                                               │
│                                                                     │
│  Drums loops    | song   (audio, 16 clips)                          │
│  Drums rack     | song   (MIDI, Drum Rack + Compressor)             │
│  Drums crushed  | song   (audio, 16 clips, Decapitator template)    │
│  Drums repeat   | song   (audio, 16 clips, Beat Repeat + Comp)     │
│  Drums echo     | song   (audio, 16 clips, Echo)                   │
│  Drums grain    | song   (audio, 16 clips, Grain Delay + Reverb)   │
│  Bass loops     | song   (audio, 16 clips, EQ Eight + Compressor)  │
│  Vocals phrases | song   (audio, 16 clips, EQ Eight + Compressor)  │
│  Other loops    | song   (audio, 16 clips)                          │
│  Other grain    | song   (audio, 16 clips, Grain Delay + Reverb)   │
│  Other echo     | song   (audio, 16 clips, Echo)                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Key insight:** The preset defines WHAT tracks to create and WHAT effects to put
on them. The manifest defines WHAT content (WAV files) to load. They're independent —
curate once, swap presets instantly without re-processing.

---

## Preset Schema (illustrated with IDM Production)

```yaml
# presets/idm_production.yaml

preset:
  name: "IDM Production"        # display name in dropdown
  version: "1.0.0"              # for tracking changes
  description: "Beat Repeat, Echo, Grain Delay, Decapitator"

stems:
  drums:
    targets:
      # Target 1: Clean loops — no effects
      - name: "loops"
        type: clips               # audio track with clip slots
        color: "#FF4444"           # Ableton track color
        chain: []                  # no effects

      # Target 2: Drum Rack with one-shots + Compressor
      - name: "rack"
        type: rack                 # MIDI track with Drum Rack
        color: "#FF4444"
        chain:
          - insert: "Compressor"   # native Live device (via insert_device)
            params:
              Threshold: 0.55      # 0-1 normalized (NOT dB)
              Ratio: 0.75          # 0-1 normalized (NOT ratio number)

      # Target 3: Crushed — VST template duplication
      - name: "crushed"
        type: clips
        color: "#882222"
        chain:
          - template: "decapitator_drums"   # duplicates [TEMPLATE] track
            macros:
              Drive: 0.7           # 0-1 normalized → auto-scaled to 0-127
              Punish: 0.5
              Style: 0
              OutputTrim: 0.5

      # Target 4: Beat Repeat stutter
      - name: "repeat"
        type: clips
        color: "#CC3333"
        chain:
          - insert: "Beat Repeat"
            params:
              Chance: 0.7          # probabilistic triggering
              Grid: 7              # 1/16 note repeats
              Variation: 5         # randomize grid
              Variation Type: 4    # Auto
              Pitch Decay: 0.4     # pitch drops on repeats
              Decay: 0.3           # repeats fade out
              Mix Type: 2          # Gate mode
              Gate: 8              # repeat length
          - insert: "Compressor"
            params: { Threshold: 0.5, Ratio: 0.8 }

      # Target 5: Echo with tape character
      - name: "echo"
        type: clips
        color: "#AA4444"
        chain:
          - insert: "Echo"
            params:
              L Synced: -4         # 1/16 note
              R Synced: -3         # 1/8 note
              Feedback: 0.45
              Noise On: 1          # analog noise
              Wobble On: 1         # tape wobble
              Dry Wet: 0.5

      # Target 6: Granular texture
      - name: "grain"
        type: clips
        color: "#993333"
        chain:
          - insert: "Grain Delay"
            params:
              Pitch: -7            # pitched down 7 semitones
              Spray: 0.4           # grain scatter
              Feedback: 0.35
              DryWet: 0.6
          - insert: "Reverb"
            params: { Dry/Wet: 0.3 }

  bass:
    targets:
      - name: "loops"
        type: clips
        color: "#4477FF"
        chain:
          - insert: "EQ Eight"
            params: {}             # inserted flat, ready to shape
          - insert: "Compressor"
            params: { Threshold: 0.6, Ratio: 0.65 }

  vocals:
    targets:
      - name: "phrases"
        type: clips
        color: "#FFAA44"
        chain:
          - insert: "EQ Eight"
            params: {}
          - insert: "Compressor"
            params: { Threshold: 0.65, Ratio: 0.6 }

  other:
    targets:
      - name: "loops"
        type: clips
        color: "#44DD77"
        chain: []

      - name: "grain"
        type: clips
        color: "#338855"
        chain:
          - insert: "Grain Delay"
            params: { Pitch: -5, Spray: 0.5, Feedback: 0.4, DryWet: 0.7 }
          - insert: "Reverb"
            params: { Dry/Wet: 0.4 }

      - name: "echo"
        type: clips
        color: "#2D7744"
        chain:
          - insert: "Echo"
            params: { Feedback: 0.5, Noise On: 1, Wobble On: 1, Dry Wet: 0.55 }
```

---

## Two Chain Types

### Native `insert` chains

Devices inserted via Live 12.3+ `Track.insert_device(name)`. Parameters set by
name matching against `Device.parameters`. All values use Ableton's internal ranges
(typically 0-1, NOT display values like dB or ratios).

```yaml
chain:
  - insert: "Compressor"
    params: { Threshold: 0.55, Ratio: 0.75 }
  - insert: "EQ Eight"
    params: {}                    # inserted with defaults
```

Reference: `stemforge/data/live_devices.json` has all 40 native audio effect
parameter names, ranges, defaults, and enum labels.

### Template chains

For VST3 plugins (can't be inserted via LOM). The user creates a `[TEMPLATE]`
track in their session with the VST wrapped in an Audio Effect Rack. The loader
duplicates the template track and sets macro values.

```yaml
chain:
  - template: "decapitator_drums"     # finds [TEMPLATE] decapitator_drums
    macros:
      Drive: 0.7                       # 0-1 → auto-scaled to param range (0-127)
      Punish: 0.5
```

**v1 constraint:** chains must be homogeneous — all `insert` OR a single `template`.
No mixing native + VST in the same chain.

---

## Priority Chain (what config gets used)

When `loadSong()` runs, it looks for processing config in this order:

1. **`sf_preset` dict** — the preset selected in the device dropdown
2. **`manifest.processing_config`** — config embedded in the manifest (backward compat)
3. **Hardcoded `PROCESSING_CONFIG`** in the JS — last resort fallback

This means:
- New workflow: select preset in dropdown, load manifest → preset wins
- Old manifests with embedded configs still work (priority 2)
- No presets installed → hardcoded IDM production config (priority 3)

---

## Parameter Value Ranges

Native device params use **internal normalized ranges**, NOT display values.

| Parameter | Display | Internal Range | Example Value |
|-----------|---------|---------------|---------------|
| Threshold | -18 dB  | 0.0 - 1.0    | 0.55          |
| Ratio     | 4:1     | 0.0 - 1.0    | 0.75          |
| Output    | 0 dB    | -36.0 - 36.0 | 0             |
| Knee      | 6 dB    | 0.0 - 18.0   | 6             |
| Rack Macros | 89   | 0.0 - 127.0  | 0.7 (→ 89)    |

Macro values in presets use 0-1 and are auto-scaled: `actual = min + val * (max - min)`.

Use the param scraper to discover ranges:
```
# In Max console (from the scraper patcher):
scrapeOne Compressor
scrapeOne "Beat Repeat"
scrapeAll              # writes stemforge/data/live_devices.json
```

---

## File Locations

| Purpose | Path |
|---------|------|
| Preset YAML (source) | `presets/*.yaml` |
| Preset JSON (compiled) | `presets/*.json` |
| Preset JSON (deployed) | `~/Documents/Max 9/Packages/StemForge/presets/` |
| Pipeline YAML (curation config) | `pipelines/curation.yaml` |
| Device param catalog | `stemforge/data/live_devices.json` |
| JS loader | `v0/src/m4l-js/stemforge_loader.v0.js` |
| Param scraper | `v0/src/m4l-js/stemforge_param_scraper.js` |
| Builder | `v0/src/maxpat-builder/builder.py` |
| Device spec | `v0/interfaces/device.yaml` |

---

## Adding a New Preset

1. Create `presets/my_preset.yaml` following the schema above
2. Compile: `uv run stemforge generate-pipeline-json`
3. Deploy: `cp presets/my_preset.json "~/Documents/Max 9/Packages/StemForge/presets/"`
4. Reload device in Ableton — new preset appears in dropdown

## Adding a New Effect to a Target

1. Find the device's parameter names: run `scrapeOne "Device Name"` in Max
2. Add to the target's `chain` in the preset YAML:
   ```yaml
   - insert: "Device Name"
     params:
       ParamName: 0.5    # use internal range from scraper
   ```
3. Recompile + redeploy
