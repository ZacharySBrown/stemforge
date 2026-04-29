# EP-133 Song Export — User Workflow

Turn an Ableton arrangement into a EP-133 K.O. II project that plays back
in **song mode** (chained scenes) or **scene mode** (manual scene selection)
on the device — using one button in the M4L device, one CLI command, and
one drag-and-drop into TE Sample Tool.

> **Version:** v1 (locator-driven snapshots, single pattern per scene)
> **Spec:** [`specs/ep133-arrangement-song-export.md`](../specs/ep133-arrangement-song-export.md)

---

## Why this exists

You forge a song with StemForge. You arrange the curated stems into a song
in Ableton's arrangement view. You want to perform that song on the EP-133
without recreating it pad-by-pad on the device.

This workflow takes the arrangement you already built and emits a `.ppak`
file you upload to the EP-133. The result: every section of your song is
a scene on the device, and you can either let song-mode chain them in
order or jump between them manually.

---

## Prerequisites

Before you start, you need:

1. **A forged manifest**. Run `uv run stemforge forge <track.wav>` (or
   `/forge-run` skill) to produce a `stems.json` with stem groupings.
2. **A populated Session view**. The StemForge M4L loader has placed the
   curated bar-loops into A/B/C/D session-view clip slots. Verify the
   manifest's `session_tracks` map matches what you see in Live.
3. **The StemForge M4L device** installed and added to a track. The
   "EXPORT SONG" button is wired in v0.1.x and onward.
4. **TE Sample Tool** (or any USB drag-drop method) for uploading `.ppak`
   files to your EP-133.
5. **A reference template** at `tests/ep133/fixtures/reference.ppak` (see
   [§ Capturing a reference template](#capturing-a-reference-template)).
6. **Tracks named `A`, `B`, `C`, `D`** in the arrangement. Names must
   match exactly (case-sensitive). Other tracks are ignored.

---

## Step-by-step

### 1. Arrange

Drag your Session-view A/B/C/D clips into the arrangement view to build the
song timeline. The exporter reads **arrangement-view clips only** — Session
clips are used solely as the sample bank that backs the pads.

Rules of thumb:

- One clip per A/B/C/D track at any given timeline position. If two clips
  on the same track overlap, the later-started one wins (matches Live's
  own playback behaviour).
- Clip lengths are flexible. The EP-133's auto-loop handles different
  bar lengths within a scene — a 1-bar A clip will loop four times under
  a 4-bar D clip, no manual alignment needed.
- Stick to clips already in your `session_tracks` (i.e. the curated
  bar-loops). Arbitrary clips that aren't in the manifest will fail with
  a clear error.

### 2. Locate

Drop **locators** (Cmd-L on macOS) at every section boundary in the
arrangement. Locators are the source of truth for scene boundaries —
each locator becomes one scene on the EP-133.

```
Arrangement timeline:
  0       16      32      48      64
  |-------|-------|-------|-------|
  ▼       ▼       ▼       ▼
  Verse   Chorus  Verse   Chorus
  └─ Scene 1  └─ Scene 2  └─ Scene 3  └─ Scene 4
```

Notes:
- The first locator should be at time 0. If you forget, the section
  before your first locator won't be exported.
- Up to 99 locators (the EP-133's scene limit). The CLI errors if you
  exceed this.
- Locator names become scene names in the captured `snapshot.json` —
  they don't appear on-device but they help you debug the export.

### 3. Export the snapshot

Click **"EXPORT SONG"** in the M4L device. This walks the arrangement,
reads tracks A/B/C/D + locators + tempo/sig, and writes a snapshot JSON
to disk (default location: alongside your project file).

```
EXPORT SONG → ~/Desktop/snapshot.json
```

The snapshot is plain text — open it to verify the structure looks right
before running the synthesizer.

### 4. Build the .ppak

Run the StemForge CLI:

```bash
uv run stemforge export-song \
    --arrangement ~/Desktop/snapshot.json \
    --manifest /path/to/stems.json \
    --reference-template tests/ep133/fixtures/reference.ppak \
    --project 1 \
    --out ~/Desktop/song.ppak
```

What this does, in order:

1. Loads the snapshot, the manifest, and the reference template.
2. Resolves which clip is playing on each of A/B/C/D at each locator.
3. Synthesizes patterns (one snapshot trigger per (group, pad, bars)
   combination), scenes (one per locator), and pad records.
4. Patches the reference template's `settings` and per-pad bytes.
5. Writes a ZIP-wrapped TAR (`.ppak`) to `--out`.

Slot conflict guard: this writes into project slot **1** by default —
choose any 1..9 that you don't mind overwriting on the device.

### 5. Upload to the EP-133

Drag `~/Desktop/song.ppak` onto **TE Sample Tool**. Sample Tool will push
the project into the slot indicated by the file's container (`P01.tar`
in the example above).

Alternative: copy the `.ppak` onto the EP-133 in disk mode if you have
that workflow set up. Sample Tool is the supported path.

### 6. Play it

On the EP-133:

- **Song mode** — press `[SONG]` then `[PLAY]`. Scenes chain in order;
  the song stops at the last scene. Tempo follows the BPM patched into
  the `.ppak`.
- **Scene mode** — exit song mode. Use the `[SCENE]` button to step
  through scenes manually. You can hit any scene at any time; this is
  the same `.ppak`, just played differently.

---

## Both modes for free

The export is the same `.ppak` whether you use song mode or scene mode.
You don't have to re-export to switch — the device just plays the scenes
back differently:

| Mode | Triggered by | Behaviour |
|------|--------------|-----------|
| **Song** | `[SONG]` + `[PLAY]` | Scenes play back-to-back in order. Stops at last scene. |
| **Scene** | `[SCENE]` + scene number | Manual selection; loops within the chosen scene until you switch. |

Use song mode for hands-off playback (album listening, demos, set
backbones). Use scene mode for live performance — jam between sections,
hold a verse, jump to the chorus on cue.

---

## Capturing a reference template

The export pipeline patches a known-good `.ppak` rather than building one
from scratch. This preserves device-specific bytes we don't fully
understand (parts of `settings`, FX state on pads). You need a reference
template at `tests/ep133/fixtures/reference.ppak`.

There are two ways to produce one.

### Option A — automated capture from your device

The capture tool reads a project from your live EP-133 over USB-MIDI
SysEx and wraps it as a `.ppak`:

```bash
uv run python tools/ep133_capture_reference.py \
    --project 1 \
    --out tests/ep133/fixtures/reference.ppak
```

Pre-flight checklist:
- Connect the EP-133 via USB.
- The project slot you target (`--project 1` here) must be initialised
  on-device. Any minimal project works — a single sample on one pad is
  enough. Empty slots return an "invalid open" error.
- Don't run other SysEx-heavy tools simultaneously (no Sample Tool, no
  parallel batch loaders).

### Option B — Sample Tool backup

If you've already backed up a project via TE Sample Tool, drop that
`.ppak` directly into `tests/ep133/fixtures/reference.ppak`. No
processing needed — Sample Tool's output is byte-compatible.

Either way, **don't commit the captured file**: it's per-device and
contains your serial number. The `.gitignore` excludes it.

---

## Common errors and fixes

### "PAK FILE IS EMPTY" on device

The ZIP entries inside your `.ppak` are missing the leading slash that
the EP-133 firmware requires. The fix is on the writer side, not the
device side — check that the writer is using `ZipInfo("/projects/...")`
not `ZipInfo("projects/...")`. If you've manually edited a `.ppak`, you
may have re-zipped it without the leading slash.

If you see this with a fresh export from `stemforge export-song`, it
likely means your reference template was captured/copied through a tool
that stripped the leading slash. Re-capture via Option A above.

### Patterns don't trigger (silence on play)

The most common cause is that a pattern's pad number references a
sample slot that isn't loaded on the device. Confirm:

1. Open the `.ppak` in TE Sample Tool and look at the `pads/X/pNN`
   assignments — each `sample_slot` in the binary must point at a slot
   you've loaded.
2. The samples bundled in `/sounds/NNN.wav` inside the `.ppak` must
   match those slots. The synthesizer bundles them automatically when
   they're referenced from the manifest.
3. If you swapped reference templates between captures, the
   `device_sku` in `meta.json` must match the device. Mismatch → the
   device may refuse the import silently.

### Tempo doesn't match the arrangement

The settings file's BPM patch (bytes 4..7, float32 LE) wasn't applied,
or the arrangement snapshot has the wrong tempo recorded. Check:

1. Open the snapshot JSON — does `tempo` match Live's tempo at export
   time?
2. Run the integration test (`uv run pytest tests/ep133/test_song_integration.py -v`)
   against your reference. The `test_settings_bpm_matches_arrangement`
   case will catch a missed patch.

### "device rejected open for project N" during capture

The targeted project slot is empty on the device. Initialise it
(any minimal project works), then re-run the capture tool.

### "FILE_INIT(read) timed out" during capture

The device is busy or in an error state. Power-cycle it (long-press
power) and retry. If it persists, check that no other tool is holding
the USB-MIDI port.

### Clips on the arrangement don't appear in the snapshot

Tracks must be named exactly `A`, `B`, `C`, `D`. Other names are
ignored. Rename and re-export.

### "file not found in session_tracks"

A clip in the arrangement points to a WAV that isn't in
`manifest.session_tracks[group]`. Make sure you're arranging from the
session-view clips StemForge populated, not from arbitrary samples
elsewhere on disk.

---

## What's NOT supported in v1

These are explicit non-goals. If you need any of them, file an issue.

- **Multi-pattern scenes** — each scene is one snapshot of which clip
  plays per group. We don't synthesize within-scene pattern changes.
  Workaround: drop another locator at the change point.
- **Chromatic notes** — every event uses MIDI note 60 (C4 = natural
  pitch). Pitching a clip up/down within a scene isn't exported.
- **FX synthesis** — per-stem effects (reverb, delay, etc.) on Ableton
  tracks are not translated to EP-133 device effects. Whatever FX live
  on the reference template's pads will carry over; ours won't be
  added.
- **Auto-upload via SysEx** — the EP-133's project-write SysEx command
  is unmapped, so you must drag the `.ppak` to Sample Tool manually.
  This is a known firmware limitation, not a stemforge bug.
- **Bars-mode auto-scenes** (`--mode bars --bars-per-scene N`) — the
  CLI accepts `--mode locator` only in v1. The bars-mode flag is
  reserved as an extension point for cases where you don't want to
  hand-place locators.
- **Time signatures other than 4/4** — should work, but is untested.
  Report any quirks.

---

## Reference

- Spec: [`specs/ep133-arrangement-song-export.md`](../specs/ep133-arrangement-song-export.md)
- Exec plan: [`docs/exec-plans/ep133-song-export.md`](exec-plans/ep133-song-export.md)
- Capture tool: [`tools/ep133_capture_reference.py`](../tools/ep133_capture_reference.py)
- Format library: `stemforge/exporters/ep133/song_format.py`
- Writer: `stemforge/exporters/ep133/ppak_writer.py`
- Resolver / synthesizer: `stemforge/exporters/ep133/song_resolver.py`,
  `stemforge/exporters/ep133/song_synthesizer.py`
- Integration test: [`tests/ep133/test_song_integration.py`](../tests/ep133/test_song_integration.py)
