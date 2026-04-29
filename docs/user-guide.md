# StemForge User Guide

> **Turn any song into a playable instrument.**
>
> Split stems. Curate the best bars. Play them on your Launchpad, Push, EP-133, or Chompi.

---

## Quick Start

### Install

Download and run `StemForge-0.0.3-alpha.pkg`. The installer sets up everything:

- `stemforge` CLI in your terminal
- StemForge Max for Live device in Ableton
- Session template with pre-configured tracks
- Neural Engine model cache (first install takes 2-3 min)

### Your First Split

```bash
stemforge split ~/Music/my_track.wav
```

This separates your track into **drums**, **bass**, **vocals**, and **other** stems, then slices each stem at beat boundaries. Output lands in `~/stemforge/processed/my_track/`.

### Play in Ableton

1. Open Ableton → **File → New from Template → StemForge**
2. On the `SF | Source` track, click the StemForge device
3. Click **Load** → navigate to `~/stemforge/processed/my_track/curated/manifest.json`
4. Four Drum Rack tracks appear with your curated bars loaded on pads
5. Switch your Launchpad/Push to Note mode → press pads → hear stems

---

## How It Works

```
Your song
   ↓
Split into 4 stems (drums, bass, vocals, other)
   ↓
Slice at bar boundaries (BPM auto-detected)
   ↓
Curate the most diverse/interesting bars
   ↓
Extract one-shot hits (kicks, snares, vocal stabs)
   ↓
Map to a 4×4 pad grid per stem = 64 total pads
   ↓
Play on Launchpad / Push / EP-133 / Chompi
```

---

## The CLI

### `stemforge split` — Separate a track into stems

```bash
# Auto-select backend (local Demucs if no API keys set)
stemforge split track.wav

# Use cloud GPU for faster processing
stemforge split track.wav --backend modal

# Just stems, no beat slicing
stemforge split track.wav --no-slice

# 6-stem separation (adds guitar + piano)
stemforge split track.wav --model 6stem

# Convert formats automatically
stemforge split track.mp3
stemforge split track.flac
```

**Backends:**

| Backend | Speed | Setup |
|---------|-------|-------|
| `demucs` (default) | ~8s per min of audio | None — works offline |
| `modal` | ~1s per min of audio | `pip install modal` then `modal setup` |
| `lalal` | ~5s per min | Set `LALAL_LICENSE_KEY` env var |
| `musicai` | ~10s per min | Set `MUSIC_AI_API_KEY` env var |

### `stemforge forge` — Split + Curate in one step

```bash
# Full pipeline: split → slice → curate → manifest
stemforge forge track.wav

# Custom curation
stemforge forge track.wav --n-bars 16 --strategy rhythm-taxonomy
```

### `stemforge export` — Format for hardware samplers

```bash
# Single track → EP-133 composition kit
stemforge export ~/stemforge/processed/my_track/ --target ep133

# Multiple tracks → Chompi performance set
stemforge export ~/stemforge/processed/ --target chompi --workflow perform

# Both devices at once
stemforge export ~/stemforge/processed/my_track/ --target both

# EP-133 budget mode (22kHz, doubles memory capacity)
stemforge export ~/stemforge/processed/my_track/ --target ep133 --budget

# Preview without writing files
stemforge export ~/stemforge/processed/ --target ep133 --dry-run
```

### `stemforge analyze` — Profile a track

```bash
stemforge analyze track.wav
```

Shows BPM, genre detection, instrument detection, and recommended split settings.

### `stemforge list` — See available options

```bash
stemforge list
```

Shows all backends, presets, models, and stem types.

---

## Ableton Live Integration

### The StemForge Device

The StemForge device is a Max for Live audio effect. It lives on the `SF | Source` track in the session template.

**Two modes:**

| Mode | What it does | When to use |
|------|-------------|-------------|
| **FORGE** | Browse audio → split → curate → load | Processing a new track |
| **LOAD** | Browse a manifest.json → load directly | Loading a previously-processed track |

### FORGE Mode

1. Click **Browse** → select a WAV/MP3/AIFF
2. The device runs `stemforge-native` (fast, CoreML-accelerated)
3. Progress shows in the status bar: splitting → slicing → curating
4. When done, 4 Drum Rack tracks appear with curated bars on pads

### LOAD Mode

1. Click **Load** → navigate to any `curated/manifest.json`
2. Bars load directly from the curated output — no re-processing
3. Multiple loads create multiple sets of tracks (one per song)

### Session Template

The StemForge session template includes:

```
▶ SF | Templates (collapsed)
    SF | Source          ← audio track with StemForge device
    SF | Drums Rack     ← MIDI track with empty Drum Rack
    SF | Bass Rack      ← MIDI track with empty Drum Rack
    SF | Vocals Rack    ← MIDI track with empty Drum Rack
    SF | Other Rack     ← MIDI track with empty Drum Rack
```

When you FORGE or LOAD, the template Drum Racks are duplicated and filled with samples. The templates stay in place for the next song.

---

## The Pad Grid

### Quadrant Layout (8×8 Launchpad)

Each stem owns a 4×4 quadrant. Top rows = loops, bottom rows = one-shots or chromatic pads.

```
┌────────────────────────┬────────────────────────┐
│     DRUMS (4×4)        │      BASS (4×4)        │
│                        │                        │
│  8 curated bar loops   │  4 phrase loops         │
│  (top 2 rows)          │  (top row)             │
│                        │                        │
│  8 classified hits     │  12 chromatic pads     │
│  kick/snare/hat layout │  (bottom 3 rows)       │
│  (bottom 2 rows)       │  play bass live!       │
├────────────────────────┼────────────────────────┤
│     VOCALS (4×4)       │      OTHER (4×4)       │
│                        │                        │
│  8 phrase loops        │  8 phrase loops         │
│  (4-bar vocal phrases) │  (2-bar textures)      │
│                        │                        │
│  4 vocal stabs         │  6 texture one-shots   │
│  (bottom row)          │  (bottom rows)         │
└────────────────────────┴────────────────────────┘
```

### Drum One-Shot Layout

The drum one-shots follow the standard drum machine convention:

```
Top row:     [Snare] [HH-C ] [HH-O ] [Perc ]
Bottom row:  [Kick ] [Kick2] [Perc ] [Perc ]
```

Kick is bottom-left, snare is above it, hi-hats are to the right of snare. Same layout as Push, MPC, and most drum machines.

### Bass Chromatic Modes

The bass quadrant supports three bottom-half modes:

| Mode | What you get | Best for |
|------|-------------|----------|
| **Melodic** (default) | 12 chromatic pads + 4 loops | Playing bass lines live — full octave |
| **Scale** | 8 in-key pads + 8 loops | Safe performance — every pad is in key |
| **Reconstruct** | 4 chromatic + 4 MIDI clips + 8 loops | DAW editing — replay + modify original bass line |

---

## Curation

### What Gets Selected

StemForge analyzes every bar in your track and selects the most **diverse** subset. Diversity is measured across three dimensions:

- **Rhythm** (50%) — onset patterns, beat density
- **Spectral** (25%) — brightness, frequency spread, tonal vs noisy
- **Energy** (25%) — temporal envelope shape, loudness contour

These weights are configurable per stem in `pipelines/curation.yaml`.

### Curation Strategies

| Strategy | How it selects | Best for |
|----------|---------------|----------|
| **max-diversity** | Maximizes distance between selected bars | General use |
| **rhythm-taxonomy** | Groups by rhythm pattern, picks variants from each group | Drums — ensures different groove types |
| **sectional** | Prefers bars near song structure boundaries | Capturing transitions |
| **transition** | Only selects bars at verse/chorus/bridge boundaries | Remix transitions |

### Phrase Lengths

Each stem can use a different phrase length:

| Setting | Duration | Good for |
|---------|----------|----------|
| `phrase_bars: 1` | ~2s at 120 BPM | Chops, glitch, retriggers |
| `phrase_bars: 2` | ~4s | Bass grooves, short riffs |
| `phrase_bars: 4` | ~8s | Vocal phrases, melodies |
| `phrase_bars: 8` | ~16s | Full verse/chorus sections |

### Song Structure Detection

StemForge detects song structure (verse, chorus, bridge) using harmonic and timbral analysis. This powers the **sectional** and **transition** strategies, and ensures the selected loops represent different parts of the song.

The detected form is shown as a letter sequence: `ABACDDA` means section A (verse), then B (chorus), back to A, then C (bridge), etc.

---

## Hardware Export

### EP-133 KO II

```bash
stemforge export ~/stemforge/processed/my_track/ --target ep133
```

**What you get:**

| Group | Pads | Content | Playback |
|-------|------|---------|----------|
| A | 12 | Drum hits (kicks, snares, hats) | One-shot |
| B | 12 | Bass notes | KEYS (chromatic) |
| C | 12 | Vocal/melodic snippets | KEYS (chromatic) |
| D | 12 | Short loops (1-2 bars) | One-shot |

**Memory:** ~2.5 MB per track at native rate, ~1.2 MB with `--budget` flag.
Load the output folder into EP Sample Tool and drag to your project.

### Chompi (TEMPO firmware)

```bash
stemforge export ~/stemforge/processed/my_track/ --target chompi
```

**What you get:**

| Engine | Slots | Content | Use |
|--------|-------|---------|-----|
| Slice | 14 | Full stems (bar-aligned, ≤10s) | Pattern Generator sequencing |
| Chroma | 14 | Melodic phrases | Chromatic playback, arpeggiation |

Copy the output folder contents to your Chompi's SD card root. No subfolders — Chompi requires a flat directory.

### Performance Workflow

Process a whole folder of tracks, then export the best material across all of them:

```bash
# Process your library
for f in ~/Music/set-list/*.wav; do
  stemforge split "$f" --no-slice
done

# Export curated kit for tonight's gig
stemforge export ~/stemforge/processed/ --target ep133 --workflow perform
```

One folder = one gig-ready kit. The curator selects the most diverse hits and loops across your entire library.

---

## Configuration

### Curation Config (`pipelines/curation.yaml`)

This file controls what gets selected and how the pads are laid out. Edit it to customize per-stem behavior:

```yaml
stems:
  drums:
    phrase_bars: 1          # single-bar chops
    loop_count: 8           # 8 loop pads
    oneshot_count: 8        # 8 one-shot pads
    strategy: max-diversity
    oneshot_mode: classify  # kick/snare/hat layout
    distance_weights:
      rhythm: 0.6           # emphasize rhythmic diversity for drums
      spectral: 0.2
      energy: 0.2

  bass:
    phrase_bars: 2          # 2-bar phrases
    bottom_mode: melodic    # 12 chromatic pads + 4 loops
    midi_extract: true      # detect pitches for chromatic playback
    chromatic_root: auto    # auto-detect root note

  vocals:
    phrase_bars: 4          # 4-bar melodic phrases
    strategy: sectional     # prefer bars from different song sections
```

### Pipeline Effects (`pipelines/default.yaml`)

Four built-in effect presets that process stems after separation:

| Pipeline | Character | Effects |
|----------|-----------|---------|
| **default** | Clean | Compressor, EQ |
| **idm_crushed** | Destroyed | LO-FI-AF, Decapitator, Compressor |
| **glitch** | Mangled | Crystallizer, large reverb |
| **ambient** | Ethereal | PhaseMistress, EchoBoy, plate reverb |

---

## File Structure

After processing, your stems live at:

```
~/stemforge/processed/
  my_track/
    drums.wav                    ← full drum stem
    bass.wav                     ← full bass stem
    vocals.wav                   ← full vocal stem
    other.wav                    ← full other stem
    stems.json                   ← manifest (BPM, paths)
    drums_bars/                  ← individual bar slices
      drums_bar_001.wav
      drums_bar_002.wav
      ...
    curated/                     ← diversity-selected output
      manifest.json              ← what the device reads
      drums/
        bar_001.wav ... bar_008.wav
        oneshots/
          os_001.wav ... os_008.wav
      bass/
        bar_001.wav ... bar_004.wav
        midi/
          bass_root.wav          ← chromatic sample
          section_A.json         ← MIDI notes for verse
          midi_manifest.json
      vocals/
        bar_001.wav ... bar_009.wav
      other/
        bar_001.wav ... bar_010.wav
```

---

## Troubleshooting

### Splitting

| Issue | Fix |
|-------|-----|
| "No stems found" | Check that the input is a valid audio file (WAV, MP3, FLAC, AIFF, M4A) |
| Very slow splitting | Use `--backend modal` for cloud GPU (12x faster) |
| MP3/M4A not working | Auto-conversion requires `ffmpeg`. Install: `brew install ffmpeg` |
| Bad stem quality | Try `--model fine` (Demucs fine-tuned, 4x slower but better) |

### Ableton

| Issue | Fix |
|-------|-----|
| No Load button | Re-install the package. Check Max console (Cmd+M) for errors |
| .json files grayed out | The Load button uses `[dict read]` — make sure you're browsing for a `.json` file, not `.wav` |
| "no Simpler found" | Template Drum Racks need 16 Simpler pads pre-populated. Re-setup templates |
| Tracks appear but no sound | Check track monitoring is "Auto". Check clip warping is enabled |
| Wrong tempo | StemForge auto-sets session tempo from the manifest |

### Launchpad / Push

| Issue | Fix |
|-------|-----|
| Pads don't light up | Switch to **Note mode** (not Session mode) for Drum Rack playback |
| Only 4×4 visible | Push shows one Drum Rack at a time. Select different tracks to see each stem's pads |
| Velocity not working | Push 2 sends velocity by default. Make sure Simpler's velocity sensitivity is > 0 |

### Hardware Export

| Issue | Fix |
|-------|-----|
| Chompi rejects files | Chompi requires **stereo** WAV. The exporter handles this automatically |
| EP-133 out of memory | Use `--budget` flag to render at 22kHz (halves file size) |
| Weird naming | Chompi requires flat directory + strict naming (`slice_a1.wav`). Don't rename files |

---

## Requirements

- **macOS 12+** (Apple Silicon recommended for CoreML acceleration)
- **Python 3.11+** (managed via `uv`)
- **Ableton Live 12** with Max for Live (for device integration)
- Optional: **Novation Launchpad Pro** or **Ableton Push 2** for pad playback
- Optional: **Modal account** for cloud GPU processing

---

## Getting Help

- **Issues:** [github.com/ZacharySBrown/stemforge/issues](https://github.com/ZacharySBrown/stemforge/issues)
- **CLI help:** `stemforge --help` or `stemforge <command> --help`
