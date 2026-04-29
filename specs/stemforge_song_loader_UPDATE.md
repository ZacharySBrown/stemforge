# StemForge — Song Loader M4L Device (Live 12.3+)

Max for Live device that builds song-specific tracks from scratch using Live 12.3's native LOM APIs. No templates, no `.adg` files, no browser navigation, no externals, no AppleScript.

**Requires Live 12.3 or later** for `Track.insert_device`, `Chain.insert_device`, and `RackDevice.insert_chain`. If you're on 12.2 or earlier, update Live first.

## Session layout

Flat, no groups. Only one persistent track:

```
0: SF | Source              (audio track, hosts this device)
```

After loading a song:

```
0: SF | Source
1: Drums Rack | <song>      (MIDI, Drum Rack built from scratch)
2: Drums Loops | <song>     (audio, 16 clip slots)
3: Bass Loops | <song>      (audio, 16 clip slots)
4: Vocals Loops | <song>    (audio, 16 clip slots)
5: Other Loops | <song>     (audio, 16 clip slots)
```

Subsequent song loads append more 5-track sets at the end. Previous song tracks stay in place — user deletes them manually when done.

## Device UI

Hosted on `SF | Source`. Controls:
- **Manifest file picker**
- **Load Song** button
- **Status text**

No "reload templates" button — nothing to reload.

## Load Song flow

Read manifest, then execute in order:

**1. Build the Drum Rack track.**

```javascript
// Create MIDI track
liveSet.call("create_midi_track", getTrackCount());
const trackIdx = getTrackCount() - 1;
const track = new LiveAPI(null, `live_set tracks ${trackIdx}`);
track.set("name", `Drums Rack | ${manifest.song.name}`);
setTrackColor(track, manifest.song.color_hue);

// Insert empty Drum Rack
track.call("insert_device", "Drum Rack");
const drumRack = new LiveAPI(null, `live_set tracks ${trackIdx} devices 0`);

// For each pad in manifest: add chain, set trigger note, add Simpler, load sample
for (const padSpec of manifest.drums_rack.pads) {
    drumRack.call("insert_chain");
    const chainIdx = drumRack.getcount("chains") - 1;
    const chain = new LiveAPI(null, `live_set tracks ${trackIdx} devices 0 chains ${chainIdx}`);
    
    // Trigger note: pad index 0-15 maps to MIDI note 36-51 (C1 to D#2)
    chain.set("in_note", 36 + padSpec.pad);
    
    // Name the chain for readability (optional but nice)
    chain.set("name", `Pad ${padSpec.pad}`);
    
    // Add Simpler, load sample
    chain.call("insert_device", "Simpler");
    const simpler = new LiveAPI(null, `live_set tracks ${trackIdx} devices 0 chains ${chainIdx} devices 0`);
    simpler.call("replace_sample", padSpec.sample);
}
```

**2. Create 4 audio tracks for loops.**

```javascript
const audioLabels = ["Drums Loops", "Bass Loops", "Vocals Loops", "Other Loops"];
for (const label of audioLabels) {
    const idx = getTrackCount();
    liveSet.call("create_audio_track", idx);
    const t = new LiveAPI(null, `live_set tracks ${idx}`);
    t.set("name", `${label} | ${manifest.song.name}`);
    setTrackColor(t, manifest.song.color_hue);
}
```

**3. Audio clips: v2.** For now, create named empty clip slots (or skip entirely — user drags samples manually).

**4. Update status text.** "Loaded: <song name>. Track range <start>–<end>."

Session must have ≥16 scenes for clip slots to exist. Create scenes programmatically if needed (`liveSet.call("create_scene", index)` in a loop on device init).

## Manifest schema

```yaml
song:
  name: "Squarepusher - My Red Hot Car"
  color_hue: 0.62           # 0.0-1.0, maps to Live's color palette

drums_rack:
  pads:
    - { pad: 0, sample: "/path/to/kick.wav" }
    - { pad: 1, sample: "/path/to/snare.wav" }
    # ... up to 16

audio_tracks:
  drums_loops:
    clips:
      - { slot: 0, sample: "/path/to/loop.wav" }
  bass_loops: { clips: [] }
  vocals_loops: { clips: [] }
  other_loops: { clips: [] }
```

Missing sections = leave empty. Validate all paths exist before touching the session.

## Key API reference

All functions used are native Live 12.3+ LOM, documented at `docs.cycling74.com/apiref/lom/`:

- `Song.create_midi_track(index)` — create empty MIDI track
- `Song.create_audio_track(index)` — create empty audio track
- `Track.insert_device(name, index?)` — insert native device by UI name ("Drum Rack", "Simpler", etc.)
- `RackDevice.insert_chain(index?)` — add chain to a rack
- `Chain.insert_device(name, index?)` — insert device into a chain
- `Chain.in_note` — MIDI note that triggers this chain (for DrumRack chains)
- `SimplerDevice.replace_sample(path)` — load audio file into Simpler

No browser API used. No externals. No file-based preset loading.

## Implementation notes

- Use Node for Max for YAML parsing (`js-yaml`)
- Never touch track 0 / track named `SF | Source`
- Log every LOM call with `[print]` during dev — silent failures are common
- Verify Live version on device init; show error if < 12.3
- All operations should be undoable via Cmd+Z (don't work around Live's undo)

## v2 deferred

- **Audio clip loading into clip slots.** Requires either `ClipSlot.create_audio_clip(path)` (check if available in 12.3) or browser navigation. For v1, create empty slots with filenames as clip names.
- **Song cleanup.** A "Delete Current Song Tracks" button that removes the most recently loaded song's 5 tracks. Identify by `| <song name>` suffix in track names.

## Acceptance

Run device → pick manifest → click Load Song → 5 new tracks appear with correct names, colors, and the Drum Rack has 16 chains each with a Simpler and its sample loaded. Click pads on a MIDI controller, correct samples play. Load a second song → 5 more tracks appear, first song's tracks untouched. `SF | Source` never modified throughout.
