# EP-133 K.O. II Workflow

How to take one or more audio tracks from a raw `.wav` to a hardware-ready
`.ppak` kit on the Teenage Engineering EP-133 K.O. II.

This is the user-facing guide. For the technical depth (LOM quirks,
SysEx protocol findings, byte-level pad records), see the
[session debrief](../sessions/2026-05-12_breaks_n_beats_complete.md)
and the `project_ep133_*` entries in your Claude project memory.

## What you need

- **Ableton Live 12** with the StemForge `.als` template loaded
  ([setup.md](../../setup.md) walks the 7-track build).
- **StemForge M4L device** installed (the installer drops it into the
  StemForge Max Package under `~/Documents/Max 9/Packages/StemForge/`).
- **EP-133 K.O. II** hardware on OS 2.0.5 or later, connected over USB-MIDI.
- **K.O. II Sample Tool** (Teenage Engineering's desktop import app).
- StemForge installed with the `native` extra (`pip install 'stemforge[native]'`)
  so Demucs is available.

## The headline flow

```
            ┌────────────────────────────────────────────────────────┐
   audio →  │ stemforge forge <track> --curation pipelines/curation  │
            │   → stems + curated/ + curated/manifest.json           │
            └─────────────────────────┬──────────────────────────────┘
                                      │
                  (Ableton: drag clips, arrange on tracks A/B/C/D)
                                      │
            ┌─────────────────────────▼──────────────────────────────┐
   COMMIT → │ M4L device → bounce + collapse + commit                │
            │   → curated/manifest.json with session_tracks block    │
            └─────────────────────────┬──────────────────────────────┘
                                      │
            ┌─────────────────────────▼──────────────────────────────┐
   plan →   │ stemforge deck-from-manifest <manifest>                │
            │   → deck.yaml                                          │
            └─────────────────────────┬──────────────────────────────┘
                                      │
            ┌─────────────────────────▼──────────────────────────────┐
   build →  │ stemforge build-deck deck.yaml --out kit.ppak          │
            └─────────────────────────┬──────────────────────────────┘
                                      │
            ┌─────────────────────────▼──────────────────────────────┐
   import → │ K.O. II Sample Tool → import as project → slot 8       │
            └────────────────────────────────────────────────────────┘
```

End-to-end timing for a 46-clip deck: ~12 seconds for the bounce + plan
+ build phases. Sample Tool import takes another 10–20 seconds depending
on payload size.

## Step-by-step

### 1. Forge each source track

```bash
stemforge forge ~/Music/track_01.wav --curation pipelines/curation.yaml
# … repeat per source track
```

Each `forge` run produces `~/stemforge/processed/<slug>/curated/manifest.json`
plus per-stem `bar_NNN.wav` files. Use `pipelines/curation_nopad.yaml` or one
of its `*_perf`, `*_phrase2`, `*_section`, `*_session_drums4` variants —
they're tuned for hardware export (`trim_pad.bars = 0` so the curated WAVs
are exact-bar slices, not padded chunks).

### 2. Arrange in Ableton

Open the StemForge `.als` template. The forge device's manifest dropdown
picks up your new processed tracks automatically (sorted alphabetically).
Drag clips into session view, layout them on tracks **A, B, C, D**
(up to 12 per track — that's the EP-133's group capacity).

### 3. COMMIT

Either hit the COMMIT button in the M4L device, or fire it via:

```bash
uv run sf-remote fire forge bounceTracks \
  ~/stemforge/processed/<slug>/curated/manifest.json
```

The device walks tracks A/B/C/D, bounces each clip with the loop region
baked in (via `_collapseToLoopRegion`), captures `warp_bpm` from
`warp_markers` slope, and writes a `session_tracks` block back into the
manifest.

### 4. Generate the deck plan

```bash
stemforge deck-from-manifest \
  ~/stemforge/processed/<slug>/curated/manifest.json \
  --project my_kit \
  --project-slot 8 \
  --out deck.yaml
```

This emits a `deck.yaml` mapping every committed clip to EP-133 group
A/B/C/D pads 1..12.

#### Format profile use cases

The default layout is `A=vocal, B=vocal, C=drum, D=texture` — appropriate
for a verse-swap deck with one drum row. Override when your kit is more
uniform:

| Flag | Use case |
|------|----------|
| `--profile drum` or `--all-drum` | Single-source breakbeats kit (e.g. just chopped Funky Drummer variants). All pads get drum-profile envelopes (`envelope.release=15`, `key` play-mode). |
| `--profile vocal` | All-vocal kit (acapella stack, ad-libs). One-shot key-trigger. |
| `--profile texture` | Pads, drones, foley. Long release; one-shot. |
| `--profile preserve_source` | Keep whatever was in the manifest's per-clip metadata (useful when you've hand-tagged clips upstream). |
| `--play-mode oneshot\|key\|loop` | Override play mode on every pad row, independent of profile. |

After generation, edit `deck.yaml` directly if you need finer per-pad
control (e.g. swap two pads, override BPM for a single clip).

### 5. Build + import

```bash
stemforge build-deck deck.yaml --out ~/Desktop/my_kit.ppak
```

Output is a `.ppak` plus a sidecar `.projectspec.json` (the abstract
ProjectSpec dump — useful for diffing arrangement → projection during
debugging).

Drag the `.ppak` into K.O. II Sample Tool, choose "import as project",
pick a project slot (1..9), wait for upload. Drag the project from the
device's project list onto your active session and you're done.

## Caveats — things you can hit, and what to do

### Per-sample 20-second cap

The EP-133 Sample Tool breaks partway when a sample exceeds 20s.
`build-deck` skips oversize clips with a warning rather than truncating.
Fix: shorten the loop region in Ableton (the loop region is what gets
materialized — see "loop-region collapse" below) and re-COMMIT.

Memory: `feedback_ep133_per_sample_cap_20s.md`.

### warp_bpm capture

`clip.call("crop")` renders at the clip's warp BPM, **not** the project
BPM. The bounce flow captures `warp_bpm` from `warp_markers` slope
*before* calling crop, then tags it into the bounced WAV (TNGE chunk)
and the per-pad record (bytes 12–15 as float32). If you've ever wondered
why a bounced clip plays at the right tempo on the device even when the
project BPM disagrees with the source BPM — this is why.

If a clip is unwarped, the kit synthesizer falls back to bar-count
inference (snapping duration to `{0.25, 0.5, 1, 2, 3, 4, 8}` bars).
5/6/7-bar candidates are explicitly excluded — they steal scoring
wins from real 4-bar interpretations.

Memory: `feedback_clip_crop_renders_at_warp_bpm.md`,
`feedback_bar_inference_candidates.md`.

### Loop-region collapse semantics

If you set a loop region in Ableton, **that's what gets bounced** — not
the full clip start→end. `_collapseToLoopRegion` writes
`loop_start`/`loop_end` onto `start_marker`/`end_marker` before crop, so
the loop region is materialized into the bounced WAV.

Practical implication: dial in your loop region first, then COMMIT. The
clip's start/end markers can stay wide; loop bounds win.

### Coupled fields on the device

`playmode` and `envelope.release` must be written as a pair. The on-device
UI handles this atomically, but naive SysEx writes drop the coupling and
gate behavior fails silently. `build-deck` always writes pairs — but if
you're writing your own pad records via raw SysEx, beware.

Memory: `feedback_ep133_coupled_fields.md`,
`feedback_ep133_emit_vs_accept.md` (strings vs ints).

### `.ppak` import vs user-paks

Sample Tool's "import as project" only accepts `.ppak` files with
`pak_type = "project"`. `build-deck` sets this correctly. The older
`"user"` pak format will be silently rejected (or fail partway).

Memory: `feedback_ppak_writer_pak_type_default.md`.

### BPM auto-detection on odd-meter / extreme-tempo material

`stemforge forge` uses beat-this:drums (preferred) with a librosa
fallback. It misses on:

- **Doubled BPM** on krautrock-style steady pulses (e.g. detected 282,
  real 141).
- **Halved BPM** on slow ballads (e.g. detected 66, real 132).
- **7/4 or other odd meters** — the 4/4 grid bias confuses both detectors.

Fix: pass `--bpm` directly on `stemforge forge`, or use `stemforge re-anchor`
after the fact. `--time-sig` is `forge`-only today; `stemforge split` is
missing the flag (tracked at [`docs/issues/split-time-sig-flag.md`](../issues/split-time-sig-flag.md)).

## Pointers

- **Session debrief** (technical depth, file-level changes):
  [`docs/sessions/2026-05-12_breaks_n_beats_complete.md`](../sessions/2026-05-12_breaks_n_beats_complete.md)
- **CLI reference** (every `stemforge` and `sf-remote` flag):
  [`docs/guides/cli-reference.md`](cli-reference.md)
- **EP-133 protocol findings** (in Claude project memory):
  - `project_ep133_sysex_upload.md`
  - `project_ep133_protocol_findings.md`
  - `project_ep133_pad_record_correct.md`
  - `project_ep133_binary_pad_record.md`
- **M4L device development**: `memory/m4l_device_development_guide.md`
