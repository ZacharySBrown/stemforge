# EP-133 K.O. II — Ableton Arrangement → Song Mode Export

**Status:** Spec
**Owner:** Architect
**Branch:** `feat/ep133-song-export` (off `feat/curation-engine-v2`)
**Date:** 2026-04-25

## Goal

Author EP-133 song-mode projects from an Ableton Live arrangement. User arranges curated loops on Tracks A/B/C/D in arrangement view, drops locators at section boundaries, runs one command, and gets a `.ppak` they upload to the EP-133 to perform scenes from the device.

## Non-goals (this spec)

- Automated `.ppak` upload to device via SysEx (project-write is unmapped; user uploads `.ppak` manually via Sample Tool / USB)
- Mid-scene pattern transitions (one snapshot per locator; future work could emit multi-pattern scenes)
- Song-section auto-detection (locator-driven only for v1; future "bars-mode" reserved as `--mode bars`)

## User experience

```
1. Forge a song into StemForge.als (existing flow)
2. Drag Session-view A/B/C/D clips into Arrangement view to build the song
3. Cmd-L to drop locators at section boundaries
4. Click "EXPORT SONG" in the M4L device → writes ~/Desktop/song.ppak
5. Drag .ppak onto your EP-133 via TE Sample Tool (or USB)
6. On device: Project select → Song mode → Play
```

## Constraints

- All clips in arrangement MUST be on tracks named exactly `A`, `B`, `C`, `D`
- All arrangement-clip `file_path` values MUST appear in `manifest.session_tracks[group]` (the Session-view source)
- Up to 99 scenes (EP-133 limit); error if more locators than that
- Up to 12 distinct samples per group (matches Session-view slot constraint and EP-133 pad count)
- v1 assumes 4/4 time signature (other sigs work but are untested)

## Verified data formats

These come from cross-referencing `~/repos/EP133-skill/scripts/create_ppak.py` (write reference) and `~/repos/ep133-export-to-daw/src/lib/parsers.ts` + `docs/EP133_FORMATS.md` (read reference, decoded from real device backups). phones24 is canonical where the two disagree.

### Pattern file: `patterns/{group}/{NN}` (NN = `01..99` zero-padded)

```
4-byte header:
  [0] = 0x00
  [1] = bars (uint8)              ← phones24 confirms; DannyDesert had this as constant 0x01 (incorrect)
  [2] = event_count (uint8, max 255)
  [3] = 0x00

8-byte event (repeats event_count times):
  [0..1]  position (uint16 LE) — ticks within pattern (0 .. bars*384 - 1)
  [2]     pad indicator: pad_num × 8  (so pad 5 → 0x28, pad 12 → 0x58)
  [3]     note (MIDI 0-127). 60 = C4 = natural pitch
  [4]     velocity (0-127)
  [5..6]  duration (uint16 LE) — ticks
  [7]     padding (0x00)
```

For our snapshot mode each pattern is a single trigger event:
- `position = 0`
- `pad = clip_to_pad_lookup(arrangement_clip)`
- `note = 60` (key/legato pads can pitch-shift via the device's keyboard mode)
- `velocity = 127`
- `duration = bars × 384` (sample plays for the whole pattern)

phones24's reader skips chunks where `chunk[2] % 8 !== 0` ("weird chunks"). We don't generate those, so this is a non-issue.

### Scenes file: `scenes`

```
Bytes 0..6:    header (preserve from reference template)
  Bytes 11..12 within absolute file = time-sig numerator/denominator
  (these fall inside chunk 0 and are also part of the per-scene metadata)

Bytes 7+:      6-byte chunks, one per scene (up to 99 scenes)
  [0] pattern index for group A (1-99, or 0 = silent)
  [1] pattern index for group B
  [2] pattern index for group C
  [3] pattern index for group D
  [4..5] reserved (zero-fill is observationally safe)
```

**Auto-loop behavior (verified in phones24's MIDI exporter):** when patterns within a scene have different `bars` values, shorter ones loop within the scene to fill `max(bars[a], bars[b], bars[c], bars[d])`. We exploit this — no need to align clip lengths across tracks.

### Pad file: `pads/{group}/p{NN}` (NN = `01..12` zero-padded), 27 bytes

```
[0]      0x00 (preserve)
[1..2]   instrument num — sample slot (uint16 LE)        ← we set
[3]      midi channel
[4..7]   trim left
[8..11]  trim right
[12..15] time-stretch BPM (float32 LE)                   ← we set (project BPM)
[16]     volume (0-200, default 100)
[17]     pitch (-12..+12; signed: 254/255 = -2/-1, 0, 1-12)
[18]     pan (0 = center; 240-255 = left, 1-16 = right)
[19]     attack (0-255)
[20]     release (0-255; 255 = full release)
[21]     time-stretch mode: 0=off, 1=BPM, 2=bars         ← we set
[22]     choke group (0..N)
[23]     play mode: 0=oneshot, 1=key, 2=legato           ← we set
[24]     pad ID (60 default)
[25]     time-stretch bars: 0=1, 1=2, 3=4, 255=½, 254=¼  ← we set
[26]     pitch decimal
```

### Settings file: 222 bytes

```
[0..3]      reserved
[4..7]      project BPM (float32 LE)                     ← we patch
[8..215]    misc project state (preserve from template)
[216..219]  per-group default volume (a, b, c, d)
[220..221]  reserved
```

We **must** preserve all bytes outside the BPM patch — internal device state we don't fully understand lives in this region.

### Container: `.ppak`

```
{filename}.ppak (ZIP wrapper, ZIP_DEFLATED)
├── /meta.json                        ← teenage engineering pak metadata (see below)
└── /projects/P{0X}.tar (POSIX TAR, no compression — `X` = project slot 1..9)
    ├── pads/{a,b,c,d}/p{01..12}      (27 bytes each, 48 files total)
    ├── patterns/{a,b,c,d}/{NN}       (variable, NN zero-padded 01..99)
    ├── scenes                         (7 + 6×N bytes, variable)
    ├── settings                       (222 bytes)
    └── sounds/{NNN}.wav               (samples bundled — XXX = sample slot)
```

**ZIP gotcha:** archive entries MUST start with `/` (leading slash) or device shows "PAK FILE IS EMPTY".

**meta.json** (preserve structure from reference, patch `generated_at` and `author`):
```json
{
  "info": "teenage engineering - pak file",
  "pak_version": 1,
  "pak_type": "user",
  "pak_release": "1.2.0",
  "device_name": "EP-133",
  "device_sku": "TE032AS001",
  "device_version": "2.0.5",
  "generated_at": "<ISO-8601 UTC>",
  "author": "stemforge",
  "base_sku": "TE032AS001"
}
```

`device_sku` and `base_sku` MUST match the target device. Extract from the user's reference `.ppak`.

## Snapshot resolution algorithm

For each locator (in time order; the last locator's scene runs to arrangement end):

1. For each track A/B/C/D:
   - Find clips where `start_time_sec ≤ locator_time_sec < start_time_sec + length_sec`
   - If multiple match → take the **latest-started** (Ableton's playback rule for overlapping arrangement clips)
   - If none match → group is silent in this scene (`pattern_idx = 0`)
2. For each playing clip:
   - Look up `clip.file_path` in `manifest.session_tracks[group]` → returns the Session-view slot
   - `pad = slot + 1` (slots are 0-indexed in `session_tracks`; pads are 1-indexed)
   - Compute `bars` from clip length on the EP (post-warp, post-bake — see "Bars inference" below)
3. Emit one trigger pattern per unique `(group, pad, bars)` tuple
4. Emit one scene per locator, mapping `{a: pattern_idx, b: pattern_idx, c: pattern_idx, d: pattern_idx}`

### Bars inference

The EP-133's `time.mode = bar` with `time.bars = N` plays the sample over N bars at project tempo. For a snapshotted clip we need to pick N.

Two cases (consistent with the existing hybrid-session loader's `detect_bars_value`):
- If the source baked WAV duration falls within ±400ms of an integer bar at project BPM → snap to that bar count
- Otherwise → use the closest of {1, 2, 4} bars and let the EP's stretch absorb the difference

The bars value is per-(group, pad), determined once when the pattern is generated.

## Component contracts

### `snapshot.json` (Track B output → Track C input)

```json
{
  "tempo": 120.0,
  "time_sig": [4, 4],
  "arrangement_length_sec": 64.0,
  "locators": [
    {"time_sec": 0.0, "name": "Verse"},
    {"time_sec": 16.0, "name": "Chorus"}
  ],
  "tracks": {
    "A": [{"file_path": "/path/to.wav", "start_time_sec": 0.0, "length_sec": 4.0, "warping": 1}],
    "B": [],
    "C": [...],
    "D": [...]
  }
}
```

### `PpakSpec` (Track C output → Track A input)

Pure dataclass, no I/O:

```python
@dataclass
class Event:
    position_ticks: int
    pad: int               # 1..12
    note: int              # MIDI 0..127
    velocity: int          # 0..127
    duration_ticks: int

@dataclass
class Pattern:
    group: str             # 'a' | 'b' | 'c' | 'd'
    index: int             # 1..99 (file is patterns/{group}/{index:02d})
    bars: int
    events: list[Event]

@dataclass
class SceneSpec:
    a: int                 # pattern index 1..99, or 0 = silent
    b: int
    c: int
    d: int

@dataclass
class PadSpec:
    group: str
    pad: int               # 1..12
    sample_slot: int
    play_mode: str         # 'oneshot' | 'key' | 'legato'
    time_stretch_bars: int # 1, 2, or 4 (raw value before encoding)

@dataclass
class PpakSpec:
    project_slot: int      # 1..9
    bpm: float
    time_sig: tuple[int, int]
    patterns: list[Pattern]
    scenes: list[SceneSpec]
    pads: list[PadSpec]
    sounds: dict[int, Path]  # sample_slot → wav file path
```

### `build_ppak(spec, reference_template) → bytes` (Track A)

Loads reference `.ppak`, extracts `settings` + per-pad templates + `meta.json`, patches in our values, re-assembles tar+zip. Pads/patterns/scenes/sounds we author are NEW; everything else preserved.

## Parallel execution plan

**Branch:** `feat/ep133-song-export` off `feat/curation-engine-v2` ✅ created

### Track A — Format library + .ppak writer
- Files: `stemforge/exporters/ep133/song_format.py`, `stemforge/exporters/ep133/ppak_writer.py`
- Tests: `tests/ep133/test_song_format.py`, `tests/ep133/test_ppak_writer.py`
- Public API: see `PpakSpec` + `build_ppak` above
- Tests use round-trip via in-Python parser. Optional: spawn phones24 TS parser via subprocess for cross-validation.

### Track B — Arrangement LOM reader (M4L JS)
- Files: `v0/src/m4l-js/sf_arrangement_reader.js` (new), `v0/src/m4l-js/stemforge_loader.v0.js` (wire button), `v0/src/m4l-package/StemForge/javascript/sf_arrangement_reader.js` (sync per dual-location rule)
- Public message: `exportArrangementSnapshot <output_path>`
- Output: `snapshot.json` (shape above)
- LOM properties: `live_set tempo`, `live_set signature_numerator/denominator`, `live_set cue_points` (each: `name`, `time`), `live_set tracks N arrangement_clips` (each: `file_path`, `start_time`, `length`, `warping`)
- Track filter: only tracks whose `name` ∈ {"A","B","C","D"} (use existing `findTrackByName`)

### Track C — Snapshot resolver + synthesizer + CLI
- Files: `stemforge/exporters/ep133/song_resolver.py`, `stemforge/exporters/ep133/song_synthesizer.py`, `stemforge/cli.py` (add `export-song`)
- Tests: `tests/ep133/test_song_resolver.py`, `tests/ep133/test_song_synthesizer.py`, fixtures in `tests/ep133/fixtures/`
- CLI:
  ```bash
  stemforge export-song \
    --arrangement snapshot.json \
    --manifest stems.json \
    --reference-template tests/ep133/fixtures/reference.ppak \
    --project 1 \
    --out song.ppak
  ```

### Track D — Reference capture + integration test + workflow doc
- Files: `tools/ep133_capture_reference.py`, `tests/ep133/test_song_integration.py`, `docs/ep133-song-export-workflow.md`
- The capture tool wraps existing `project_reader.read_project_file()` (which reads project TAR via SysEx) into a complete `.ppak` (TAR + ZIP + meta.json). Saves to `tests/ep133/fixtures/reference.ppak`.
- Integration test: `arrangement.json + manifest.json → .ppak → re-parse via in-Python parser → assert pattern/scene/pad layout matches expected`. Optionally also runs phones24's TS parser via `node` subprocess.

## Test strategy

| Track | Test type | Validates |
|-------|-----------|-----------|
| A | Round-trip in-Python | byte builders match expected layout |
| A | (optional) Round-trip via phones24 TS | format consumable by external reader |
| B | M4L test harness (`v0/tests/`) | snapshot JSON shape with mock arrangement |
| C | Unit (resolver) | overlapping clips, missing files, locator edge cases |
| C | Unit (synthesizer) | pattern dedup, scene mapping, bars inference |
| D | End-to-end (Python) | arrangement → .ppak → re-parsed → layout assertions |
| Manual | On-device | Champ song actually plays in song mode |

Every new module ships with tests. Per project rules, tests are non-negotiable.

## Risks + mitigations

| Risk | Mitigation |
|------|-----------|
| Settings file has fields we don't know about | Use captured reference template as base; only patch known bytes |
| `.ppak` doesn't boot on device | Track D's integration test catches format errors; manual on-device test catches device-specific issues |
| Pattern format edge case ("weird chunks where pad % 8 != 0") | We generate only well-formed events |
| Multi-bar `position` semantics past 384 ticks | We use position=0 in trigger patterns; non-issue |
| Sample slot conflicts with existing device state | Use slot range 100+ (matches hybrid loader convention); document in workflow |
| Same WAV in arrangement vs Session has different start markers | COMMIT in Session view first, then drag to Arrangement; Track C warns if mismatch detected |
| Locators not placed | Track C errors with clear message; future `--mode bars` provides fallback |

## Out of scope for v1

- Multi-pattern scenes (e.g., A's pattern changes within one scene)
- Per-event chromatic notes (all events use note=60; future: read from MIDI clips on tracks)
- FX settings synthesis (preserved from template; future: read `live_set tracks N devices` for per-stem FX)
- Auto-upload via SysEx (manual `.ppak` drag for now)
- Bars-mode auto-scenes (extension point reserved in CLI: `--mode bars --bars-per-scene N`)

## References

- Write reference: `~/repos/EP133-skill/scripts/create_ppak.py` (DannyDesert)
- Read reference: `~/repos/ep133-export-to-daw/src/lib/parsers.ts` (phones24)
- Format spec: `~/repos/ep133-export-to-daw/docs/EP133_FORMATS.md` (phones24)
- Existing SysEx project reader: `stemforge/exporters/ep133/project_reader.py`
- Existing hybrid session loader: `tools/ep133_load_hybrid_session.py`
- Existing pad-record decoder: `stemforge/exporters/ep133/pad_record.py`
