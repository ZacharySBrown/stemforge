# StemForge — Song Loader M4L Device

Max for Live device that creates song-specific tracks from templates, then reloads templates on demand.

## Session layout

Flat, no groups. Track 0 is `SF | Source` (hosts this device, never touched).

**Phase 1 — templates present:**
```
0: SF | Source
1: SF | Drums Rack       (MIDI, has Drum Rack with 16 Simplers)
2: SF | Bass Rack        (MIDI, has Instrument Rack)
3: SF | Vocals Rack      (MIDI, has Instrument Rack)
4: SF | Other Rack       (MIDI, has Instrument Rack)
```

**Phase 2 — song loaded:**
```
0: SF | Source
1: Drums Rack | <song>
2: Drums Loops | <song>  (audio)
3: Bass Loops | <song>   (audio)
4: Vocals Loops | <song> (audio)
5: Other Loops | <song>  (audio)
```

## Device UI

Hosts on `SF | Source`. Three controls:
- **Manifest file picker**
- **Load Song** button (enabled in Phase 1)
- **Reload Templates** button (enabled in Phase 2)
- **Status text**

Phase detection: check if all four `SF | *Rack` track names exist. Run on init and after every action.

## Load Song (Phase 1 → Phase 2)

1. Read manifest (YAML: song name, color hue, drum pad samples, audio track clip samples)
2. Duplicate `SF | Drums Rack` → rename to `Drums Rack | <song>`, set color
3. For each pad in manifest: navigate to the Simpler at `live_set tracks N devices 0 drum_pads <note> chains 0 devices 0` and call `replace_sample(path)`
4. Create 4 audio tracks at end of session, named `Drums Loops | <song>` etc., colored
5. Audio clip loading: create empty clips in clip slots with filenames as placeholders (**v2: load audio via browser**)
6. Delete the 4 `SF | *Rack` tracks (iterate names, lookup index by name each time, delete)
7. Update status

## Reload Templates (Phase 2 → Phase 1)

For each of the 4 template names, if missing from session:
1. Create bare MIDI track at end of session
2. Select it (`live_set view selected_track`)
3. Navigate `live_app view browser user_library` → walk children matching path components to find `StemForge/Templates/SF_<type>Rack.adg`
4. Call `browser.call("load_item", foundItem.id)`
5. Rename track to `SF | <type> Rack`

Idempotent: skip any template track that already exists.

## Template files

User creates these once in Ableton and saves to User Library:
- `StemForge/Templates/SF_DrumsRack.adg` (Drum Rack, 16 Simplers on C1-D#2)
- `StemForge/Templates/SF_BassRack.adg` (Instrument Rack)
- `StemForge/Templates/SF_VocalsRack.adg` (Instrument Rack)
- `StemForge/Templates/SF_OtherRack.adg` (Instrument Rack)

## Manifest schema

```yaml
song:
  name: "Squarepusher - My Red Hot Car"
  color_hue: 0.62
drums_rack:
  pads:
    - { pad: 0, sample: "/path/to/kick.wav" }
audio_tracks:
  drums_loops:
    clips:
      - { slot: 0, sample: "/path/to/loop.wav" }
  bass_loops: { clips: [] }
  vocals_loops: { clips: [] }
  other_loops: { clips: [] }
```

Missing sections = leave empty. Validate all paths exist before touching session.

## Implementation notes

- Use Node for Max for YAML parsing (`js-yaml`)
- Target Live 12 only; use `replace_sample` on Simpler
- Never touch track 0 / track named `SF | Source`
- Log every LOM call with `[print]` during dev — silent failures are common
- Session must have ≥16 scenes for clip slots to exist; create scenes if needed
- All operations should be undoable via Cmd+Z (don't work around Live's undo)

## v2 deferred

- Audio clip loading into clip slots (use browser for this too, same pattern as `.adg` load but targeting `clip_slot` instead of selected track)
- Song unload / switch

## Acceptance

Full round trip works: load song A → reload templates → load song B → reload → load song C. No stale tracks, no duplicates, correct samples loaded, templates correctly reconstructed each time. `SF | Source` untouched throughout.
