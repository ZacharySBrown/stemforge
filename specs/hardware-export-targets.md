# StemForge Hardware Export Targets — Spec

> Export stem/slice output to hardware samplers for composition and live
> performance. Initial targets: Chase Bliss Chompi (TEMPO firmware) and
> Teenage Engineering EP-133 KO II.

## 1. Motivation

StemForge produces stems and beat slices that live on disk as WAV files.
To use them in a hardware performance or composition context, a musician
currently has to manually rename, resample, trim, and organize files for
each device. This is tedious and error-prone — the naming conventions,
sample rates, bit depths, mono/stereo requirements, and memory limits
differ across every piece of hardware.

`stemforge export` automates this: given a processed track (or a
directory of them), it formats, budgets, and packs stems/slices for a
specific device, ready to load.

## 2. Target Devices

### 2.1 Teenage Engineering EP-133 KO II

| Parameter        | Value                                                    |
|------------------|----------------------------------------------------------|
| Sample rate      | 46,875 Hz (non-standard; EP Sample Tool resamples)       |
| Bit depth        | 16-bit storage, 32-bit float internal                    |
| Channels         | Mono preferred (stereo = 2x memory)                      |
| Format           | WAV                                                      |
| Memory           | 128 MB (~24 min mono at native rate)                     |
| Max per sample   | 20 seconds                                               |
| Sample slots     | 999 (global pool, shared across projects)                |
| Groups           | 4 per project (A, B, C, D) x 12 pads each               |
| Chromatic mode   | KEYS: spreads 1 sample across 12 pads (1 octave)        |
| Scale modes      | 12T, MAJ, MIN, DOR, PHR, LYD, MIX, LOC, MA.P, MI.P     |
| Loading          | EP Sample Tool (browser, Chrome, USB-C, drag-and-drop)   |
| Polyphony        | 16 mono / 12 stereo voices (OS 2.0)                     |

**Memory budget trick:** Rendering at 22,050 Hz mono doubles capacity
to ~48 min. Percussion and short vocal stabs survive this well. The EP
Sample Tool preserves sub-46,875 Hz rates — it only resamples *up*, not
down.

### 2.2 Chase Bliss Chompi (TEMPO firmware)

| Parameter        | Value                                                    |
|------------------|----------------------------------------------------------|
| Sample rate      | 48,000 Hz                                                |
| Bit depth        | 16-bit                                                   |
| Channels         | Stereo required (mono files rejected)                    |
| Format           | WAV                                                      |
| Storage          | Micro SD, FAT32, 4 GB usable max                        |
| Max per slot     | 10 seconds                                               |
| Engines          | Slice (auto-chops into 16 segments) + Chroma (chromatic) |
| Slots            | 14 per engine (28 total)                                 |
| Naming           | `slice_a1.wav`–`slice_a14.wav`, `chroma_a1.wav`–`chroma_a14.wav` |
| SD structure     | Flat root directory, no folders                          |
| Sequencer        | Pattern Generator (arp modes, probability, rests)        |
| MIDI             | External clock sync (send/receive)                       |

**TAPE firmware** is also supported (Cubbi = chromatic, Jammi = one-shot,
5 banks x 14 slots x 2 engines = 140 slots), but TEMPO is the primary
target for its sequencer and slice engine.

## 3. Device Mapping

### 3.1 EP-133 Group Layout

```
┌─────────────────────────────────────────────────────┐
│ EP-133 Project                                      │
│                                                     │
│  Group A (drums)     12 pads ← drum beat 1-shots    │
│  Group B (bass)      12 pads ← bass slices (KEYS)   │
│  Group C (melodic)   12 pads ← vocal/guitar (KEYS)  │
│  Group D (loops)     12 pads ← short loops (≤4s)    │
└─────────────────────────────────────────────────────┘
```

| Group | StemForge Source         | Playback Mode | Notes                                |
|-------|--------------------------|---------------|--------------------------------------|
| A     | `drums_beats/*.wav`      | One-shot      | Individual hits, sequenced           |
| B     | `bass_beats/*.wav`       | KEYS (chrom.) | Play bass lines chromatically        |
| C     | `vocals_beats/*.wav` or `other_beats/*.wav` | KEYS (chrom.) | Melodic snippets from source |
| D     | Curated bar-length loops | One-shot      | 1-2 bar percussion/groove loops      |

**Memory per track** (~120 BPM, mono, 46875 Hz):
- 1 beat slice = ~0.5s = ~46 KB
- 12 drum hits + 12 bass + 12 melodic = ~1.7 MB
- 4 loops (2 bars, 4s each) = ~740 KB
- **Total: ~2.5 MB per track**
- At 22050 Hz: ~1.2 MB per track → **~100 tracks in 128 MB**

### 3.2 Chompi TEMPO Layout

```
┌─────────────────────────────────────────────────────┐
│ Chompi SD Card (root)                               │
│                                                     │
│  Slice engine:  slice_a1.wav ... slice_a14.wav      │
│    └─ Full drum/bass stems (≤10s each)              │
│    └─ Chompi auto-chops each into 16 slices         │
│    └─ Sequence with Pattern Generator               │
│                                                     │
│  Chroma engine: chroma_a1.wav ... chroma_a14.wav    │
│    └─ Guitar riffs, vocal phrases (≤10s each)       │
│    └─ Play chromatically, arpeggiate                │
└─────────────────────────────────────────────────────┘
```

| Engine | StemForge Source       | Use Case                              |
|--------|-----------------------|---------------------------------------|
| Slice  | Full drum/bass stems  | Beat-chop performance, pattern sequencing |
| Chroma | Vocal/guitar phrases  | Chromatic melody, arpeggiator         |

**Stem selection for Slice engine:** Prefer stems with clear transients
(drums first, then bass). The auto-slicer divides evenly into 16 — so
stems should be trimmed to musically meaningful boundaries (full bars)
before export.

**Phrase selection for Chroma engine:** Use the curator's diversity
selection to pick the most distinct melodic phrases. Short, pitched
content works best — isolated notes or 1-bar riffs.

## 4. Workflows

### 4.1 Composition Workflow

**Goal:** Maximum raw material from a single track for building new music.

```
stemforge export ~/stemforge/processed/my_track/ \
    --target ep133 \
    --workflow compose \
    --output ~/Desktop/ep133-kit/
```

**EP-133 compose:**
- Load every usable beat slice from the track
- Fill all 4 groups from one source
- Drums → Group A (up to 12 most distinct hits via curator)
- Bass → Group B (all slices, chromatic)
- Vocals/other → Group C (all slices, chromatic)
- Auto-generate 1-2 bar loops from drum stem → Group D
- Output: folder ready for EP Sample Tool drag-and-drop

**Chompi compose:**
- Full stems trimmed to ≤10s (bar-aligned) → all 14 Slice slots
- Interesting phrases from vocals/guitar → all 14 Chroma slots
- Output: flat directory ready to copy to SD card root

### 4.2 Performance Workflow

**Goal:** Curated kit across multiple tracks for live performance.

```
stemforge export ~/stemforge/processed/ \
    --target chompi \
    --workflow perform \
    --output ~/Desktop/chompi-gig/
```

**EP-133 perform:**
- Scan all processed tracks in directory
- Curator selects 12 most diverse drum hits across all tracks → Group A
- 12 most diverse bass notes → Group B
- 12 most diverse melodic snippets → Group C
- 4-8 best short loops → Group D
- Output: one folder = one gig-ready kit

**Chompi perform:**
- 14 best drum/groove stems across tracks → Slice engine
- 14 best melodic phrases across tracks → Chroma engine
- Pattern Generator presets (future: export MIDI patterns?)
- Output: one SD card image = ready to perform

## 5. Format Pipeline

```
StemForge beat slices (44.1 kHz, 32-bit float, stereo)
    │
    ├─→ EP-133 exporter
    │     ├─ Resample to 46875 Hz (or 22050 Hz for budget mode)
    │     ├─ Convert to 16-bit
    │     ├─ Downmix to mono
    │     ├─ Trim/pad to ≤20s
    │     ├─ Normalize (peak)
    │     ├─ Name by slot number
    │     └─ Write memory budget report
    │
    └─→ Chompi exporter
          ├─ Resample to 48000 Hz
          ├─ Convert to 16-bit
          ├─ Ensure stereo (duplicate mono → stereo if needed)
          ├─ Trim to ≤10s (bar-aligned)
          ├─ Normalize (peak)
          ├─ Name per convention (slice_a1.wav, chroma_a1.wav)
          └─ Validate flat directory (no nested folders)
```

## 6. CLI Interface

```bash
# Single track → EP-133 composition kit
stemforge export track_dir/ --target ep133 --workflow compose

# Directory of tracks → Chompi performance kit
stemforge export processed/ --target chompi --workflow perform

# Both devices at once
stemforge export processed/ --target both --workflow perform

# EP-133 memory-saving mode (22050 Hz)
stemforge export track_dir/ --target ep133 --workflow compose --budget

# Dry run — show what would be packed + memory budget
stemforge export processed/ --target ep133 --workflow perform --dry-run

# Custom group mapping
stemforge export track_dir/ --target ep133 --workflow compose \
    --group-c other   # put "other" stem in group C instead of vocals
```

### Options

| Flag           | Default    | Description                                    |
|----------------|------------|------------------------------------------------|
| `--target`     | (required) | `ep133`, `chompi`, `both`                      |
| `--workflow`   | `compose`  | `compose` (single track) or `perform` (multi)  |
| `--output`     | `./export/`| Output directory                               |
| `--budget`     | off        | EP-133: render at 22050 Hz to save memory      |
| `--dry-run`    | off        | Show plan + memory budget without writing files |
| `--group-a/b/c/d` | auto   | EP-133: override which stem maps to which group |
| `--firmware`   | `tempo`    | Chompi: `tempo` or `tape`                      |

## 7. Output Manifest

Each export writes an `export.json` alongside the audio files:

```json
{
  "device": "ep133",
  "workflow": "perform",
  "source_tracks": ["break_01", "funk_loop", "vocal_phrase"],
  "sample_rate": 46875,
  "bit_depth": 16,
  "channels": 1,
  "slots": [
    {
      "slot": 1,
      "group": "A",
      "pad": 1,
      "file": "001_break_01_drums_beat_003.wav",
      "source_track": "break_01",
      "source_stem": "drums",
      "duration_s": 0.48,
      "size_bytes": 44928
    }
  ],
  "memory_used_bytes": 2621440,
  "memory_total_bytes": 134217728,
  "memory_pct": 1.95,
  "exported_at": "2026-04-18T12:00:00Z"
}
```

## 8. Module Structure

```
stemforge/
  exporters/
    __init__.py          # ExportTarget enum, shared utilities
    base.py              # AbstractExporter (resample, bit-depth, normalize)
    ep133.py             # EP133Exporter — group mapping, memory budget
    chompi.py            # ChompiExporter — naming, stereo enforcement
```

Exporters follow the same pattern as backends: abstract base class,
device-specific implementations. The CLI command in `cli.py` dispatches
to the appropriate exporter.

## 9. Dependencies

- `soundfile` — already in use (WAV read/write)
- `librosa` — already in use (resampling)
- `numpy` — already in use

No new dependencies required.

## 10. Future Targets

Other hardware worth considering once the exporter pattern is established:

- **SP-404 MK2** (Roland) — 32 GB SD, 16 pads x 10 banks, WAV/AIFF
- **MPC One / Live** (Akai) — programs + keygroups, WAV
- **Digitakt II** (Elektron) — Transfer app, +Drive
- **PO-33 / PO-133** (TE) — line-in only, no file transfer
- **1010music Blackbox** — SD card, folder-based, very flexible

The `AbstractExporter` pattern should make adding these straightforward.
