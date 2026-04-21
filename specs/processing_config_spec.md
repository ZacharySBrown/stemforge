# StemForge — Processing Config (Effect Chains + VST Templates)

**Extends:** `stemforge_song_loader.md`
**Status:** Draft spec
**Live version:** 12.3+

Adds effect-chain processing to song tracks. Two sources of effects: native Live devices inserted by name (clean LOM), and user-curated VST chain templates duplicated from hidden template tracks (LOM-safe workaround for the "can't insert VST via LOM" limitation).

## Design

Per stem, N targets. Each target = one track. Same WAV file can land on multiple targets (loops track + crushed track) — processing differs per target.

```yaml
drums:
  targets:
    - name: "loops"
      type: clips
      chain: []                          # clean
    - name: "rack"
      type: rack
      chain: []                          # Drum Rack on its own track
    - name: "crushed"
      type: clips
      chain:
        - insert: "Saturator"            # native Live device (Step 1)
          params: { Drive: 18.0 }
        - template: "decapitator_drums"  # user VST template track (Step 2)
          macros: { crunch: 0.7 }
```

Two effect entry types:
- `insert`: native Live device name. Uses `Chain.insert_device` via LOM. No setup required.
- `template`: name of a hidden template track in the session. Device chain from that track is copied onto the target track. User curates these once. Supports VST3.

## Session layout

```
0:  SF | Source                 (persistent, hosts device)
1+: Song tracks                 (created on load)
... (blank separation)
N:  ▼ SF | Effect Templates     (folded group, dark grey)
      [TEMPLATE] decapitator_drums      (audio track, Decapitator configured)
      [TEMPLATE] valhalla_vox_verb      (audio track, reverb configured)
      ... user adds more as needed
```

Template tracks are hidden in a folded group at session bottom. User creates once, duplicates from spec on demand.

## Effect templates

**Template track = audio track with a pre-configured device chain.** User creates manually:

1. Create audio track at end of session
2. Name it `[TEMPLATE] <name>` (e.g., `[TEMPLATE] decapitator_drums`)
3. Load devices onto it (VST3s, stock devices, Audio Effect Racks — anything)
4. Configure parameters to taste
5. Optionally wrap in an Audio Effect Rack to expose macros as stable parameter interface
6. Move the track into the `SF | Effect Templates` group, fold the group, color it dark grey

Templates persist across song loads. Built once per project/session.

**Macro wrapping (recommended):** wrap the VST chain in an Audio Effect Rack so macros provide stable parameter names. Spec references macros by name; raw VST3 parameter IDs are unstable across Live versions and plugin updates.

```
[TEMPLATE] decapitator_drums:
  └── Audio Effect Rack (macros: crunch, tone, mix)
        ├── Decapitator (Drive → macro "crunch")
        ├── EQ Eight (Tilt → macro "tone")
        └── Utility (Dry/Wet → macro "mix")
```

## Target types (from base spec)

- `clips`: audio track with clip slots. Samples populated per song manifest.
- `rack`: MIDI track with Drum Rack. Samples populated per song manifest (Pattern A from base spec).
- `midi_slice`: future; MIDI-triggered slicing via Simpler slice mode or similar. Not v1.

Track naming: `<stem> <target_name> | <song>` (e.g., `drums crushed | Squarepusher - MRHC`). Disambiguates when a stem has multiple targets.

## Processing config schema

Full example:

```yaml
song:
  name: "Squarepusher - My Red Hot Car"
  color_hue: 0.62

stems:
  drums:
    targets:
      - name: "loops"
        type: clips
        source_samples:
          - { slot: 0, sample: "/path/to/drums_loop_01.wav" }
        chain: []

      - name: "rack"
        type: rack
        source_samples:
          - { pad: 0, sample: "/path/to/kick.wav" }
          - { pad: 1, sample: "/path/to/snare.wav" }
        chain: []

      - name: "crushed"
        type: clips
        source_samples: "from:loops"       # shorthand: reuse loops samples
        chain:
          - insert: "Saturator"
            params: { Drive: 18.0, Output: -3.0 }
          - template: "decapitator_drums"
            macros: { crunch: 0.7, tone: 0.4, mix: 1.0 }

  bass:
    targets:
      - name: "loops"
        type: clips
        source_samples: [ ... ]
        chain: []

  vocals:
    targets:
      - name: "loops"
        type: clips
        source_samples: [ ... ]
        chain: []

  other:
    targets:
      - name: "loops"
        type: clips
        source_samples: [ ... ]
        chain: []
```

**`source_samples: "from:<target_name>"`** means "copy sample references from sibling target `<target_name>`". Avoids duplication when multiple targets share WAVs. Only valid within the same stem.

## Load Song flow (extended)

For each stem, for each target:

1. Create track (audio or MIDI per `type`)
2. Name it `<stem> <target_name> | <song>`, set color
3. If `type: rack`: build Drum Rack per base spec (Pattern A)
4. If `type: clips`: load sample references into clip slots (v1 stubbed; v2 full)
5. **Process the effect chain in order:**
   ```javascript
   for (const effect of target.chain) {
       if (effect.insert) {
           // Native device
           track.call("insert_device", effect.insert);
           const deviceIdx = track.getcount("devices") - 1;
           applyParams(track, deviceIdx, effect.params);
       } else if (effect.template) {
           // User template — copy devices from template track
           copyDevicesFromTemplate(track, effect.template);
           applyMacros(track, effect.template, effect.macros);
       }
   }
   ```

## `applyParams` — setting native device parameters

```javascript
function applyParams(track, deviceIdx, params) {
    if (!params) return;
    const device = new LiveAPI(null, `${track.path} devices ${deviceIdx}`);
    const paramCount = device.getcount("parameters");
    
    for (const [paramName, value] of Object.entries(params)) {
        // Find parameter by name
        for (let i = 0; i < paramCount; i++) {
            const param = new LiveAPI(null, `${device.path} parameters ${i}`);
            if (param.get("name")[0] === paramName) {
                param.set("value", value);
                break;
            }
        }
    }
}
```

Parameter names match what's shown in Ableton's UI (e.g., Saturator has "Drive", "Output", "DC"). If a name doesn't match, log a warning and skip that param — don't abort the whole load.

## `copyDevicesFromTemplate` — VST template duplication

The hard part. Options in order of preference:

**Option 1 (cleanest, if available in Live 12.3):** Check if `Track.duplicate_devices_to(source_track, target_track)` or similar exists. Not in base LOM; unlikely but worth a 5-minute spike.

**Option 2 (practical):** Use the `copy_pad` pattern's analog for tracks — there isn't one. So: select the template track, select all its devices, Cmd+C, select target track, Cmd+V. Requires keystroke automation (AppleScript on Mac) — **no**, we said no AppleScript.

**Option 3 (the actual answer): `live_set.duplicate_track(templateTrackIdx)`, then move devices.**

Wait — `duplicate_track` duplicates with all devices. But it creates a whole new track. You don't want a second track, you want the devices on your existing target track.

**Option 4 (the real actual answer): just duplicate the template track and rename it.**

Reframe the design: when a target spec says `template: "decapitator_drums"`, the loader **duplicates the template track** and renames the duplicate to the target name. The template's devices come along for the ride. No device-copying needed.

This means a target with both `insert` steps AND a `template` step is more complex — you need the template's devices AND the `insert` devices on the same track. Options:

- **Require template to contain the full chain.** If you want native + VST combined, put both in the template. The config just references the template; no mixing.
- **Allow mixing:** duplicate template track, then programmatically insert native devices before/after the template's devices.

**Recommendation for v1: require `chain` to be homogeneous — either all `insert` or a single `template`.** No mixing. Keeps implementation simple. Mixing becomes a v2 feature.

Revised config constraint:

```yaml
# Valid: all native
chain:
  - insert: "Saturator"
    params: { Drive: 18.0 }
  - insert: "EQ Eight"
    params: { ... }

# Valid: single template
chain:
  - template: "decapitator_drums"
    macros: { crunch: 0.7 }

# Invalid v1: mixing
chain:
  - insert: "Saturator"
  - template: "decapitator_drums"       # error: chain is mixed
```

If you want both, build a template that contains the Saturator too. Keep templates self-contained.

**With this constraint, the template flow becomes:**

```javascript
function applyTemplate(targetTrackName, templateName, macros, songName, colorHue) {
    // Find template track
    const templateIdx = findTrackIndexByName(`[TEMPLATE] ${templateName}`);
    if (templateIdx === -1) throw new Error(`Template not found: ${templateName}`);
    
    // Duplicate it
    liveSet.call("duplicate_track", templateIdx);
    // Duplicate lands at templateIdx + 1 (inside the template group)
    
    // Since LOM can't move tracks between groups, we need the template group
    // to be at the end of the session, and we're OK with the duplicate
    // appearing inside the group. But we want it OUTSIDE.
    //
    // Workaround: don't keep templates in a group. Keep them as flat tracks
    // at the end of the session, just named [TEMPLATE] ... and collapsed/
    // narrow-width for visual de-emphasis.
    
    // Rename the duplicate
    const dup = new LiveAPI(null, `live_set tracks ${templateIdx + 1}`);
    dup.set("name", targetTrackName);
    setTrackColor(dup, colorHue);
    
    // Apply macros
    applyMacros(dup, macros);
    
    return dup;
}
```

**Important architectural consequence: templates can't be inside a group**, because `duplicate_track` creates the duplicate inside the group, and we established we can't move tracks out of groups. So templates are **flat tracks at the bottom of the session, named `[TEMPLATE] <name>`**, collapsed to minimum width for visual tidiness. User can color them all dark grey.

## `applyMacros` — setting rack macro values

If the template's device chain starts with an Audio Effect Rack, its macros are at `track devices 0 parameters N` (macros are DeviceParameters on the rack).

```javascript
function applyMacros(track, macros) {
    if (!macros) return;
    const rackDevice = new LiveAPI(null, `${track.path} devices 0`);
    
    // Check it's a rack
    const className = rackDevice.get("class_name")[0];
    if (!className.includes("Rack") && !className.includes("Group")) {
        console.warn("Template track's first device is not a rack; macros ignored");
        return;
    }
    
    // Iterate parameters, match macro names
    const paramCount = rackDevice.getcount("parameters");
    for (const [macroName, value] of Object.entries(macros)) {
        for (let i = 0; i < paramCount; i++) {
            const param = new LiveAPI(null, `${rackDevice.path} parameters ${i}`);
            if (param.get("name")[0] === macroName) {
                param.set("value", value);
                break;
            }
        }
    }
}
```

Macro values are float 0.0-1.0 (Live normalizes the underlying parameter range into this space).

## v1 scope

**In scope:**
- Native `insert` with params for all target types
- Single-template `template` chains (no mixing)
- Macro parameterization of template racks
- One curated VST template: `[TEMPLATE] decapitator_drums` (manually created by user)

**Out of scope (v2):**
- Mixed chains (native + template in same chain)
- Nested templates (template referencing another template)
- Parameter automation over time (only static values for v1)
- Dynamic template discovery (v1: user hardcodes template names in configs)
- Template validation (v1: assume templates exist; fail gracefully with clear error if not)

## Example: the Decapitator drums template (user setup steps)

1. Create audio track at end of session
2. Rename to `[TEMPLATE] decapitator_drums`
3. Insert Audio Effect Rack
4. Inside the rack, insert Decapitator (SoundToys VST3)
5. Configure Decapitator: Drive taste, Style = Punish, etc.
6. Back on the rack: map Macro 1 to Decapitator's Drive, rename macro to "crunch"
7. Map Macro 2 to Decapitator's Tone, rename macro to "tone"
8. Map Macro 3 to the rack's dry/wet (or a Utility's gain), rename to "mix"
9. Collapse track to narrow width, color dark grey
10. Save the set — the template is now baked in

Config to use this template:

```yaml
- name: "crushed"
  type: clips
  source_samples: "from:loops"
  chain:
    - template: "decapitator_drums"
      macros: { crunch: 0.7, tone: 0.4, mix: 1.0 }
```

## Key API reference additions

- `Song.duplicate_track(index)` — duplicates a track adjacent to source
- `Device.parameters` — list of DeviceParameters
- `DeviceParameter.name` — parameter name as shown in UI
- `DeviceParameter.value` — read/write parameter value
- `Device.class_name` — check device type (useful to detect racks vs raw VSTs)

## Implementation order

1. **Config parsing.** Read extended YAML, validate chain is homogeneous (all insert or single template), validate all templates referenced exist in session.
2. **Native chain (`insert`).** Implement `applyParams`. Test with Saturator, EQ Eight, Compressor on a drums clips track.
3. **Template discovery.** Build the template track index: find all tracks named `[TEMPLATE] *`.
4. **Template application.** Duplicate template track, rename, apply macros.
5. **End-to-end.** Config with both a native-chain target and a template target; verify both produce correct tracks with correct processing.
6. **User onboarding doc.** Short README explaining how to create a template track correctly. Live screenshots probably helpful.

## Acceptance

Given:
- Session with `[TEMPLATE] decapitator_drums` template track (user-created, with Audio Effect Rack wrapping Decapitator, macros mapped and named)
- A song config with a `crushed` target referencing that template with `macros: { crunch: 0.7 }`
- A `crunchy_native` target with `chain: [{ insert: "Saturator", params: { Drive: 12 } }]`

Clicking Load Song should produce:
- A `drums crushed | <song>` track that is a copy of the Decapitator template, with crunch macro set to 0.7
- A `drums crunchy_native | <song>` track with Saturator inserted, Drive set to 12
- Playing clips on either track sounds correct and different from clean loops
