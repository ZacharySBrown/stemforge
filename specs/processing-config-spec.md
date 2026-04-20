# StemForge Processing Config Spec

> Defines per-stem target tracks, track types, and post-processing chains.
> Each stem maps to 1-N target tracks. Each target has a type (clips, rack,
> midi-slice) and an optional effect chain.

---

## Config Format

```yaml
name: "IDM Production"
version: 1

# Global settings
global:
  strategy: max-diversity
  downbeat_correction: true

# Per-stem targets — each stem produces 1-N tracks
stems:
  drums:
    targets:
      - type: clips
        name: "Drums Loops"
        color: "#FF4444"
        params:
          phrase_bars: 1
          loop_count: 16
          strategy: rhythm-taxonomy

      - type: rack
        name: "Drums One-Shots"
        color: "#FF4444"
        params:
          oneshot_count: 16
          oneshot_mode: classify    # classify | diverse | loudest
          use_larsnet: true
        chain:
          - device: "Compressor"
            params: { threshold: -18, ratio: 4, attack: 5, release: 50 }

      - type: clips
        name: "Drums Crushed"
        color: "#882222"
        params:
          phrase_bars: 1
          loop_count: 16
        chain:
          - device: "XLN.LO-FI-AF"        # VST3
            params: { bitcrush: 0.6, drive: 0.4 }
          - device: "SoundToys.Decapitator" # VST3
            params: { drive: 0.35, style: "E" }
          - device: "Compressor"            # stock Ableton
            params: { threshold: -15, ratio: 6 }

  bass:
    targets:
      - type: clips
        name: "Bass Loops"
        color: "#4477FF"
        params:
          phrase_bars: 2
          loop_count: 16
          strategy: max-diversity
        chain:
          - device: "EQ Eight"
            params: {}
          - device: "Compressor"
            params: { threshold: -14, ratio: 3 }

      - type: rack
        name: "Bass One-Shots"
        color: "#4477FF"
        params:
          oneshot_count: 8
          oneshot_mode: diverse

  vocals:
    targets:
      - type: clips
        name: "Vocals Phrases"
        color: "#FFAA44"
        params:
          phrase_bars: 4
          loop_count: 16
          strategy: sectional
        chain:
          - device: "EQ Eight"
            params: {}
          - device: "Compressor"
            params: { threshold: -16, ratio: 4 }

  other:
    targets:
      - type: clips
        name: "Other Loops"
        color: "#44DD77"
        params:
          phrase_bars: 2
          loop_count: 16

      - type: clips
        name: "Other Verb"
        color: "#44CCCC"
        params:
          phrase_bars: 2
          loop_count: 16
        chain:
          - device: "SoundToys.EchoBoy"
            params: { delay: "1/4 dotted", feedback: 0.45 }
          - device: "Reverb"
            params: { decay: 4.2, diffusion: 0.9 }
```

---

## Track Types

### `clips` — Audio track with clip slots
- Creates an audio track with N curated bar/phrase loops
- Each clip slot has one WAV loaded
- **Params:**
  - `phrase_bars`: 1, 2, 4, 8 (bar grouping before curation)
  - `loop_count`: number of clips to curate (max 16)
  - `strategy`: max-diversity | rhythm-taxonomy | sectional | transition
  - `rms_floor`, `crest_min`, `content_density_min`: quality filters
  - `distance_weights`: { rhythm, spectral, energy }

### `rack` — MIDI track with Drum Rack
- Creates a MIDI track, inserts Drum Rack, adds chains with Simplers
- Each pad gets one curated one-shot sample
- Built from scratch via Live 12.3+ `insert_device` / `insert_chain`
- **Params:**
  - `oneshot_count`: number of pads to fill (max 16)
  - `oneshot_mode`: classify (kick/snare/hat layout) | diverse | loudest
  - `use_larsnet`: true/false (drum sub-stem separation for better isolation)

### `midi_slice` (future) — MIDI track with sliced audio
- Takes a bar loop, slices to MIDI via transient detection
- Creates a MIDI clip with the sliced pattern
- Drum Rack or Simpler in slice mode
- **Params:**
  - `source`: which clips target to slice from
  - `slice_mode`: transient | beat | manual
  - `quantize`: none | 1/16 | 1/8

---

## Effect Chain

Each target can have a `chain` node — a list of effects applied in order.
The loader inserts these onto the track after creating it.

### Stock Ableton effects
```yaml
chain:
  - device: "Compressor"
    params: { threshold: -18, ratio: 4 }
  - device: "EQ Eight"
    params: {}
  - device: "Reverb"
    params: { decay: 4.2 }
  - device: "Auto Filter"
    params: { frequency: 2000, resonance: 0.5 }
```

Inserted via `track.call("insert_device", "Compressor", index)`.
Parameters set via `device.set("parameter_name", value)` or by
navigating `device.parameters` and matching by name.

### VST3 / AU plugins
```yaml
chain:
  - device: "SoundToys.Decapitator"    # VST3 plugin name
    params: { drive: 0.35 }
  - device: "XLN.LO-FI-AF"
    params: { bitcrush: 0.6 }
  - device: "SoundToys.EchoBoy"
    params: { delay: "1/4 dotted" }
```

VST3 insertion via `track.call("insert_device", "vst3:SoundToys.Decapitator")`.
If the plugin isn't installed, skip it and log a warning.

Parameter setting for VSTs: navigate `device.parameters`, match by
`parameter.name`, set value. VST parameter names are plugin-specific.

### Chain on a Drum Rack track
Effects are inserted ON THE TRACK (after the Drum Rack), not inside
individual Drum Rack chains. For per-pad effects, that's a future feature.

---

## Loader Behavior

For each stem in the config:
1. Iterate `targets` in order
2. For each target:
   a. Create the appropriate track type (audio or MIDI)
   b. Name it: `{target.name} | {song_name}`
   c. Set color from `target.color`
   d. Load content (clips for `clips` type, one-shots for `rack` type)
   e. Insert effect chain devices in order
   f. Set effect parameters
3. All tracks for one song appear together at the end of the session

Multiple songs = multiple sets of tracks, accumulated.

---

## Presets

Processing configs are saved as YAML files in `pipelines/`:
- `pipelines/production_idm.yaml` — crushed drums, verb textures
- `pipelines/production_clean.yaml` — minimal processing
- `pipelines/production_ambient.yaml` — long reverbs, delays
- `pipelines/performance_launchpad.yaml` — quadrant layout

The device UI has a preset selector (dropdown or chips) to pick
which config to use for the next Load.

---

## Implementation Notes

- `insert_device` with VST names: try `"vst3:Name"` format first,
  fall back to `"vst:Name"` (AU), fall back to skip with warning
- Parameter matching: VST params may have different names than expected.
  Use fuzzy matching on `parameter.name` if exact match fails.
- Chain order matters: effects are inserted left-to-right in the chain
- Color: hex string → Ableton color index mapping needed
- The same curated WAV files can be loaded onto multiple tracks
  (e.g., Drums Loops and Drums Crushed use the same bar WAVs,
  just with different effect chains)
