# StemForge → EP-133 Hybrid-Layered Session (v1)

**Target:** `tools/ep133_load_hybrid_session.py` — chops curated stems into
a session layout designed for live performance combining drum loops, drum
hits, key-playable melodic samples, and one-shot FX.

**Scope:** v1 ships ONE song to ONE EP-133 project. Multi-song templating
deferred. Scale-snap (auto-key) deferred to v2.

---

## Conceptual layout

| Group | Role                                | Pad layout                        | Time mode |
|-------|-------------------------------------|-----------------------------------|-----------|
| A     | Drums (hybrid: hits + loops)        | 1-6: one-shot drum hits           | off       |
|       |                                     | 7-12: 2-bar drum loops            | bar (2)   |
| B     | Bass / low-end key chops            | 1-12: short samples for Keys mode | off       |
| C     | Vocals / lead key chops             | 1-12: short samples for Keys mode | off       |
| D     | One-shot FX / accents / extra hits  | 1-12: short one-shots             | off       |

**Why this layout works for the device:**
- Group A's hybrid means you can play the looped backing AND drop one-shot
  fills/breaks from the same group without switching
- Group B/C: each pad is a different chop. In normal mode, finger-drum the
  chops. Press `KEYS` after selecting a pad → play *that* chop chromatically
  across all 12 pads. Switch to a different pad, press KEYS again, play
  the other chop chromatically. Twelve melodic instruments per group.
- Group D for true one-shots — accents, FX, anything that doesn't fit elsewhere

---

## Audio output requirements

All WAVs: mono, 16-bit PCM, 46875 Hz.

### Group A: drum content

**Pads 1-6 (one-shot drum hits):**
- Source: per-song drum-rack samples that StemForge already produces
  (kick, snare, hat closed, hat open, clap, perc/tom)
- Length: native (typically 100ms-1s); no time-stretch
- Filename: `<NNN> A_hit_<role>.wav` (e.g. `100 A_hit_kick.wav`)

**Pads 7-12 (2-bar drum loops):**
- Source: first 6 selected drum loops from the manifest (`stems.drums.keepers`,
  filtered `selected: true`, in order)
- Length: exactly 2 bars at song BPM, sample-accurate
  - frames = `round(2 × 4 × 60.0 / bpm × 46875)`
- Trim: start at curated in-point (`offsets.start_offset_sec`)
- Filename: `<NNN> A_loop_<keeper-id>.wav` (e.g. `106 A_loop_k01.wav`)

### Group B: bass / low-end key chops

- Source: 12 short interesting segments from `stems.bass.keepers`. User
  curates these in Ableton — typically 0.5-2s each, single sustained notes
  or short phrases that sound musical when pitched up/down chromatically
- Length: native; no time-stretch (Keys mode controls pitch)
- Filename: `<NNN> B_key_<keeper-id>.wav`
- Manifest field: `offsets.key_chop_length_sec` (NEW) — tells the exporter
  how much to keep from the start point

### Group C: vocal / lead key chops

- Same as Group B but from `stems.vocals` (or whatever stem has the
  high-end / lead content)
- 12 chops, each short, designed for chromatic playing

### Group D: one-shot FX / accents

- Source: per-song curated FX and accent hits
- 12 one-shots: vocal stab, FX riser, FX impact, sub drop, sweep, reverse
  cymbal, etc. User-defined. Defaults from a `oneshots.fx_kit` block in
  the manifest.

---

## Slot allocation

Contiguous within each group with gaps between groups for human readability:

| Group | Pads 1-6 slots | Pads 7-12 slots | Notes                |
|-------|----------------|-----------------|----------------------|
| A     | 100-105 (hits) | 106-111 (loops) | hit/loop split       |
| B     | 120-131        | (same range)    | all key-playable     |
| C     | 140-151        | (same range)    | all key-playable     |
| D     | 160-171        | (same range)    | all one-shots        |

---

## Per-slot metadata configuration

### Group A pads 1-6 (drum hits)
```python
SlotMeta(
    sound_playmode="oneshot",
    envelope_release=255,
    time_mode="off",        # NO stretch on hits
    sound_amplitude=100,
    sound_pan=<role-dependent>,    # hat slightly L, etc.
    sound_loopstart=-1,
    sound_loopend=-1,
)
```

### Group A pads 7-12 (drum loops)
```python
SlotMeta(
    sound_playmode="oneshot",
    envelope_release=255,
    time_mode="bar",
    time_bars=2,            # 2-bar loops
    sound_bpm=<song_bpm>,
    sound_amplitude=100,
    sound_pan=0,
    sound_loopstart=-1,     # sequencer drives repeat
    sound_loopend=-1,
)
```

### Group B pads 1-12 (bass key chops)
```python
SlotMeta(
    sound_playmode="oneshot",
    envelope_release=255,
    time_mode="off",        # Keys mode pitches, doesn't stretch
    sound_rootnote=60,      # MIDI middle C — Keys mode default
    sound_amplitude=100,
    sound_pan=0,
    sound_loopstart=-1,
    sound_loopend=-1,
)
```

NOTE: `sound.rootnote` (per spec §4) tells the device which MIDI note the
sample's "natural" pitch corresponds to. For Keys mode, when you tap the
center pad of the chromatic layout, it plays at rootnote pitch — taps
above/below pitch up/down semitone-by-semitone. Setting rootnote=60 (C4)
gives a balanced range above and below.

### Group C pads 1-12 (vocal key chops)
Same as Group B.

### Group D pads 1-12 (one-shot FX)
```python
SlotMeta(
    sound_playmode="oneshot",
    envelope_release=255,
    time_mode="off",
    sound_amplitude=100,
    sound_pan=<varies>,
    sound_loopstart=-1,
    sound_loopend=-1,
)
```

---

## Per-pad mute groups

Mute groups make hats/snares cut each other in the natural way. Project-wide
unique IDs (1-9 are safe).

| Group | Pads | Mute group | Reason                                  |
|-------|------|------------|-----------------------------------------|
| A     | 1 (kick)        | none | layers freely with everything           |
| A     | 2,5 (snare,clap)| `1`  | snare and clap cut each other           |
| A     | 3,4 (hat c, o)  | `2`  | open hat cuts closed hat (musical)      |
| A     | 6 (perc)        | none |                                         |
| A     | 7-12 (loops)    | `3`  | only one drum loop variant at a time    |
| B     | 1-12            | `4`  | only one bass note at a time (mono bass)|
| C     | 1-12            | none | vocal phrases can layer (interesting)   |
| D     | 1-12            | none | FX layer freely                         |

Adjust to taste. Group C without mute group means stacked vocals are
possible — drop from spec if you'd rather have monophonic vox.

---

## Manifest schema additions

Extend the existing `curated/manifest.json`:

```json
{
  "song": {
    "bpm": 136.0,
    "name": "smbu",
    "phrase_bars": 2,                  // CHANGED from 4
    "key": "C minor"                   // NEW (v2 will use; v1 just labels)
  },
  "stems": {
    "drums": { "keepers": [...12 items...] },
    "bass":   { "keepers": [...12 items...] },
    "vocals": { "keepers": [...12 items...] }
  },
  "oneshots": {
    "drum_kit": {
      "kick":       "/abs/path/kit/kick.wav",
      "snare":      "/abs/path/kit/snare.wav",
      "hat_closed": "/abs/path/kit/hat_c.wav",
      "hat_open":   "/abs/path/kit/hat_o.wav",
      "clap":       "/abs/path/kit/clap.wav",
      "perc":       "/abs/path/kit/perc.wav"
    },
    "fx_kit": [
      {"role": "vox_stab",   "file": "/abs/path/fx/stab.wav"},
      {"role": "riser",      "file": "/abs/path/fx/riser.wav"},
      {"role": "impact",     "file": "/abs/path/fx/impact.wav"},
      {"role": "sub_drop",   "file": "/abs/path/fx/sub.wav"},
      {"role": "sweep_up",   "file": "/abs/path/fx/sweep_up.wav"},
      {"role": "sweep_down", "file": "/abs/path/fx/sweep_down.wav"},
      {"role": "rev_cymbal", "file": "/abs/path/fx/rev_cymbal.wav"},
      {"role": "noise_burst","file": "/abs/path/fx/noise.wav"},
      {"role": "vinyl_stop", "file": "/abs/path/fx/vinyl_stop.wav"},
      {"role": "tape_stop",  "file": "/abs/path/fx/tape_stop.wav"},
      {"role": "extra_1",    "file": "/abs/path/fx/extra_1.wav"},
      {"role": "extra_2",    "file": "/abs/path/fx/extra_2.wav"}
    ]
  },
  "session_layout": {
    "project_id": 1,
    "version": "hybrid_v1"
  }
}
```

For each keeper in `stems.bass` and `stems.vocals`, ALSO add (NEW):
```json
{
  "file": "...",
  "offsets": {
    "start_offset_sec": 0.123,
    "key_chop_length_sec": 1.5     // NEW: how much audio to keep from the
                                   // start point. Default 1.5s if absent.
  }
}
```

For `stems.drums` keepers, the existing offsets schema is fine — start
offset + 2-bar length computed from BPM.

---

## CLI

```
python3 tools/ep133_load_hybrid_session.py \
    --manifest /path/to/manifest.json \
    --project 1 \
    [--dry-run] \
    [--skip-upload]   # only set metadata, don't re-upload audio
```

---

## Implementation steps

1. **Audio prep stage**
   - For each Group A pad 1-6: copy drum-kit one-shots to
     `processed/<song>/ep133_hybrid/A_hits/<role>.wav`. Resample to 46875
     Hz mono if needed.
   - For each Group A pad 7-12 (drum loops): trim from start_offset for
     2 bars, write to `processed/<song>/ep133_hybrid/A_loops/k<NN>.wav`
   - For each Group B pad 1-12 (bass): trim from start_offset for
     `key_chop_length_sec` (default 1.5s), write to
     `processed/<song>/ep133_hybrid/B_keys/k<NN>.wav`
   - For each Group C pad 1-12 (vocal): same logic as B
   - For each Group D pad 1-12 (FX): copy as-is, resample if needed

2. **Device upload stage**
   - For each slot in declared order: upload WAV via `client.upload_sample`
   - Set slot metadata via `client.set_slot_metadata`
   - Total: 6 + 6 + 12 + 12 + 12 = 48 uploads

3. **Pad assignment stage**
   - Assign each pad: `client.assign_pad(group, pad_num, sym=slot, mute_group=...)`
   - 48 pad assignments total

4. **Reporting**
   ```
   ✓ Project 1 loaded ('smbu', key=C minor, bpm=136).
   Group A: pads 1-6 = drum hits, pads 7-12 = 2-bar loops
   Group B: pads 1-12 = bass key chops (rootnote C4)
   Group C: pads 1-12 = vocal key chops (rootnote C4)
   Group D: pads 1-12 = FX one-shots
   ```

---

## On-device validation

After loading, on the EP-133:
1. Switch to project 1
2. Group A: tap pads 1-6 → drum hits play once. Tap pads 7-12 → 2-bar loops
   play through and stop. Verify no time-stretch on hits.
3. Group B: tap pads 1-12 in normal mode → 12 different bass chops play
   one-shot. Then select pad 1 and press KEYS → pads now play that chop
   chromatically. Press KEYS again to exit. Select pad 2, press KEYS,
   confirm different chop now plays chromatically.
4. Group C: same as B
5. Group D: tap pads 1-12 → 12 different FX one-shots

---

## Estimated effort

Stemforge side (manifest curation in Ableton + chopping):
- ~1 hour: re-curate drums (12 keepers × 2-bar) for SMBU
- ~30 min: pick 12 bass chops with start markers
- ~30 min: pick 12 vocal chops with start markers
- ~30 min: render/extract drum kit one-shots from drum-rack track
- ~30 min: gather/pick 12 FX one-shots
- **Total: ~3 hours**

Code side:
- Building `ep133_load_hybrid_session.py` with the manifest extensions:
  ~2-3 hours

Total realistic estimate: **5-6 hours** for ONE song fully loaded with
this layout. Not achievable in 73 minutes.

---

## v2 deferred features

- **Scale snap (key extraction → device scale setting):** Spec §4 doesn't
  document a project-level scale field. Need to research SysEx for the
  system-setting that controls Keys-mode scale. Likely doable but unverified.
- **Multi-song template:** ship same layout to projects 1-4 with different
  audio. Easy after v1 lands.
- **Hybrid Group A automation:** stemforge auto-detects which drum hits to
  use as kit and which loops to keep, vs requiring manual curation.