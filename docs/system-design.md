# StemForge — System Design Document

> **Version:** 0.3.0-alpha · **Date:** 2026-04-19 · **Status:** Active Development

---

## 1. Overview

StemForge is a dual-mode audio production system that separates songs into stems (drums, bass, vocals, other), slices them into musically meaningful segments, curates the most diverse/interesting slices, and loads them into Ableton Live for performance and composition.

**Primary workflows:**
- **Ableton Live integration** via Max for Live device — Browse → Split → Curate → Play on Launchpad/Push
- **CLI pipeline** — Process tracks from the command line for batch workflows
- **Hardware export** — Format curated stems for EP-133, Chompi, and other hardware samplers

**Key metrics:**
- Local stem separation: ~4.5s per 10s audio (CoreML, Apple Silicon)
- Cloud GPU separation: ~0.45s per 10s audio (Modal, A10G)
- 108 automated tests, 24 Python modules

---

## 2. Architecture

### 2.1 Three-Zone Model

```
┌─────────────────────────────────────────────────────────────┐
│                        STEMFORGE                            │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │     CORE     │  │     M4L      │  │    TOOLS     │     │
│  │  stemforge/  │  │    v0/src/   │  │    tools/    │     │
│  │              │  │   m4l-js/    │  │   batch/     │     │
│  │  CLI         │  │   maxpat-    │  │   exporters  │     │
│  │  Backends    │  │   builder/   │  │              │     │
│  │  Slicer      │  │              │  │              │     │
│  │  Curator     │  │  [shell]+[js]│  │              │     │
│  │  Segmenter   │  │  LiveAPI/LOM │  │              │     │
│  │  Analyzer    │  │              │  │              │     │
│  │  Exporters   │  │              │  │              │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│        │                   │                   │            │
│        │    stems.json     │                   │            │
│        └───────────────────┘                   │            │
│                manifest contract               │            │
└─────────────────────────────────────────────────────────────┘
```

**Zone rules:**
- **Core** (`stemforge/`) has zero M4L dependencies — standalone Python package
- **M4L** (`v0/src/`) reads Core's output (manifests) but never imports Core code
- **Tools** (`tools/`, `batch/`) may call Core CLI commands but don't import M4L

### 2.2 Module Map

| Module | Purpose | Dependencies |
|--------|---------|-------------|
| `cli.py` | Click CLI entry point | All core modules |
| `config.py` | Config loading, constants, curation YAML | PyYAML |
| `backends/` | Stem separation (Demucs, LALAL, MusicAI, Modal) | Per-backend |
| `slicer.py` | BPM detection, beat/bar slicing, phrase grouping | librosa |
| `curator.py` | Diversity-based selection (GFP in 20D feature space) | numpy |
| `segmenter.py` | Song structure detection (chroma recurrence + MFCC) | librosa, scipy |
| `oneshot.py` | Transient extraction, multi-band onset detection | librosa |
| `drum_classifier.py` | Spectral heuristic drum hit classification | numpy |
| `midi_extractor.py` | Pitch detection, key detection, MIDI clip generation | librosa |
| `layout.py` | Pad grid mapping for Launchpad/Push quadrants | numpy |
| `analyzer.py` | Genre/instrument classification (CLAP, AST) | transformers (optional) |
| `manifest.py` | stems.json dataclass + I/O | stdlib |
| `exporters/` | Hardware sampler formatters (EP-133, Chompi) | soundfile, librosa |

### 2.3 Data Flow

```
Audio file
  │
  ├─→ Backend.separate()          Demucs / LALAL / MusicAI / Modal
  │     → drums.wav, bass.wav, vocals.wav, other.wav
  │     → stems.json manifest
  │
  ├─→ Slicer                      BPM detection + bar slicing
  │     → {stem}_bars/bar_001.wav ... bar_NNN.wav
  │     → {stem}_phrases/ (when phrase_bars > 1)
  │
  ├─→ Segmenter                   Chroma + MFCC recurrence analysis
  │     → SongStructure (segments, boundaries, form label)
  │
  ├─→ Curator                     Greedy farthest-point selection
  │     → curated/{stem}/bar_001.wav ... (diverse subset)
  │
  ├─→ One-shot Extractor          Multi-band onset detection
  │     → curated/{stem}/oneshots/os_001.wav ...
  │     → Drum classifier → kick/snare/hat/perc labels
  │
  ├─→ MIDI Extractor              pyin pitch detection + key detection
  │     → curated/{stem}/midi/root_sample.wav
  │     → curated/{stem}/midi/section_A.json ...
  │
  ├─→ Layout Engine               Quadrant mapping + LED colors
  │     → curated/manifest.json (v2 with loops + oneshots + pads)
  │
  ├─→ M4L Loader                  LiveAPI track creation + sample loading
  │     → Ableton tracks with Drum Racks / clip slots
  │
  └─→ Exporters                   Hardware-specific formatting
        → EP-133 kit / Chompi SD card
```

---

## 3. Backend Architecture

### 3.1 Abstract Interface

```python
class AbstractBackend(ABC):
    @abstractmethod
    def separate(self, audio_path: Path, output_dir: Path, **kwargs) -> dict[str, Path]:
        """Returns {stem_name: stem_wav_path}"""
    
    @property
    @abstractmethod
    def name(self) -> str: ...
```

### 3.2 Implementations

| Backend | Type | Speed (per 10s) | Requirements |
|---------|------|-----------------|-------------|
| **Demucs** | Local CPU/GPU | ~7.8s (M2 MPS) | `torch`, `demucs` |
| **stemforge-native** | Local CoreML | ~4.5s (Neural Engine) | ONNX model + CoreML EP |
| **Modal** | Cloud GPU (A10G) | ~0.45s | `modal` SDK, deployed app |
| **LALAL.AI** | Cloud API | ~5-10s | API key |
| **Music.AI** | Cloud API | ~5-15s | API key |

### 3.3 Model Pipeline (stemforge-native)

```
Audio → STFT preprocessing (z_cac) → ONNX htdemucs_ft_fused
  → CoreML MLProgram compile (cached) → Neural Engine inference
  → 4 stem outputs → WAV encoding
```

The ONNX model is chunked at 343,980 samples (~7.8s @ 44.1kHz) with STFT input shape `[1, 4, 2048, 336]`.

---

## 4. Curation Engine

### 4.1 Feature Analysis

Each bar/beat slice is profiled with 14 features:

| Feature | Type | What it captures |
|---------|------|-----------------|
| `spectral_centroid` | Hz | Brightness / frequency balance |
| `spectral_bandwidth` | Hz | Frequency spread |
| `spectral_flatness` | 0-1 | Noise vs tonal (0=pure tone, 1=white noise) |
| `crest_factor` | ratio | Punchiness (peak / RMS) |
| `onset_density` | /sec | Rhythmic activity |
| `rhythm_fingerprint` | 16-bin | Quantized onset pattern |
| `energy_curve` | 8-segment | Temporal energy envelope |
| `rms` | amplitude | Overall loudness |
| `peak` | amplitude | Maximum sample value |
| `attack_time` | seconds | Time to peak |
| `onset_times` | list | Raw onset positions |
| `onset_count` | int | Number of transients |
| `duration` | seconds | Slice length |

### 4.2 Selection Strategies

| Strategy | Algorithm | Best for |
|----------|-----------|----------|
| **max-diversity** | Greedy farthest-point in 20D z-normalized feature space | General use — maximizes variety |
| **rhythm-taxonomy** | Cluster by rhythm fingerprint (Hamming), pick diverse variants per cluster | Drums — ensures different groove patterns |
| **sectional** | Weight by structural importance (distance to song boundaries) | Picking bars near verse/chorus transitions |
| **transition** | Filter to boundary-adjacent bars only, then diversity-select | Isolating musical transitions |

### 4.3 Configurable Distance Weights

The 20D feature vector is weighted by category before normalization:

```python
spectral_features *= w_spectral   # centroid, bandwidth
transient_features *= w_energy    # crest, onset_density  
rhythm_features *= w_rhythm       # 16-bin fingerprint
```

Default: `rhythm=0.5, spectral=0.25, energy=0.25`. Per-stem overrides in `curation.yaml`.

### 4.4 Phrase-Length Grouping

Bars can be grouped into multi-bar phrases before curation:

```
phrase_bars=1: individual bars (chops, glitch)
phrase_bars=2: 2-bar grooves (bass lines)
phrase_bars=4: 4-bar phrases (melodies, vocal lines)
phrase_bars=8: 8-bar sections (full verses)
```

Implemented as concatenation of adjacent bar WAVs via `group_bars_into_phrases()`.

---

## 5. Song Structure Detection

### 5.1 Algorithm

1. **Chroma features** (12D) — harmonic content via `librosa.feature.chroma_stft()`
2. **MFCC features** (13D mean + 13D std) — timbral content + variability
3. **Recurrence matrix** — self-similarity via `librosa.segment.recurrence_matrix()`
4. **Novelty curve** — checkerboard kernel convolution on the diagonal
5. **Boundary detection** — peak-picking on novelty, constrained by `min_segment_bars`
6. **Bar snapping** — boundaries snapped to nearest bar from beat grid
7. **Section labeling** — cosine similarity on 38D feature vectors (chroma + MFCC mean + MFCC std)

### 5.2 Output: SongStructure

```python
@dataclass
class SongStructure:
    segments: list[SongSegment]      # labeled sections
    form: str                         # e.g., "ABACDDA"
    boundaries_bars: list[int]        # bar numbers where structure changes
    bar_importance: dict[int, float]  # per-bar structural importance (0-1)
    total_bars: int
```

### 5.3 Tested Results

| Track | Artist | BPM | Form | Sections |
|-------|--------|-----|------|----------|
| Smack My Bitch Up | Prodigy | 136 | ABACDDA | 4 distinct harmonic sections |
| Express Yourself | NWA | 126 | AAAABBA | Bridge detected |
| Go! Spastic | Squarepusher | 99 | AAAAABCD | 4 sections in outro |
| The Big Come Down | NIN | 81 | ABAAACAA | 3 sections (verse/breakdown) |
| Can I Kick It | Tribe | 98 | ABAABBB | Hook vs verse separation |

---

## 6. One-Shot Extraction

### 6.1 Multi-Band Onset Detection

Three frequency bands with per-stem weighting:

| Band | Range | Drums weight | Vocals weight |
|------|-------|-------------|---------------|
| Low | 20-250 Hz | 0.4 | 0.1 |
| Mid | 250-4000 Hz | 0.2 | 0.7 |
| High | 4000-16000 Hz | 0.4 | 0.2 |

### 6.2 Drum Classification

Spectral heuristic classifier (zero ML dependencies):

| Category | Key discriminators |
|----------|-------------------|
| **kick** | centroid < 300 Hz, duration > 50ms |
| **snare** | centroid 500-5000 Hz, crest > 5.0, bandwidth > 1500 Hz |
| **hat_closed** | centroid > 5000 Hz, flatness > 0.35, duration < 120ms |
| **hat_open** | centroid > 5000 Hz, flatness > 0.35, duration > 120ms |
| **clap** | double-onset (flam), mid-centroid |
| **rim** | duration < 30ms, crest > 8.0 |
| **perc** | fallback |

Handles both acoustic and electronic drums (808 kicks, synth snares).

### 6.3 Kick-from-Bass Recovery

htdemucs routes kick drum energy into the bass stem. `extract_kicks_from_bass()` extracts low-frequency transients from the bass stem and classifies them as kicks for the drum pad layout.

---

## 7. MIDI Extraction

### 7.1 Pipeline

```
Stem WAV → librosa.pyin() → f0 contour → note segmentation
  → root sample extraction (cleanest note)
  → key detection (Krumhansl-Kessler chroma correlation)
  → section-aware MIDI clip generation
```

### 7.2 Three Bottom-Half Modes

| Mode | Pads | Use case |
|------|------|----------|
| **melodic** (default) | 12 chromatic + 4 loops | Full octave, play live |
| **scale** | 8 in-key + 8 loops | Safe performance, more loops |
| **reconstruct** | 4 chromatic + 4 MIDI clips + 8 loops | DAW editing |

---

## 8. M4L Device Architecture

### 8.1 Process Spawning

```
[opendialog] → [regexp path] → [sprintf command] → [shell]
  [shell] stdout → [js ndjson_parser.v0.js] → [route events]
  [shell] done   → [js parser] bang handler
```

- **`[shell]`** (Jeremy Bernstein, MIT) spawns `stemforge-native`
- **`[js]`** (classic SpiderMonkey) handles NDJSON parsing + LiveAPI access
- **`[node.script]`** is NOT used — broken on macOS 26+ (Team ID mismatch SIGKILL)

### 8.2 Load Session Flow

```
[Load button] → [t b] → [t b b]
  right → [message "read"] → [dict sf_manifest] (opens JSON file browser)
  left  → [message "loadFromDict sf_manifest"] → [js loader]
    → loader detects v1/v2 format → dispatches to appropriate loading function
```

### 8.3 Two-Phase FORGE Flow

```
Browse audio → [shell] stemforge-native split → NDJSON events
  → complete event → extract stems dir → [sprintf curate command] → [shell]
  → curate NDJSON → curated event → [unpack] → loadCuratedBars → loader
```

### 8.4 Loader Functions

| Function | Mode | Creates |
|----------|------|---------|
| `loadManifest()` | v0 | Audio tracks from template duplication |
| `loadCuratedBars()` | v1 Launchpad MVP | 4 audio tracks × 16 clip slots |
| `loadFromDict()` | v1/v2 auto-detect | Routes to appropriate loader |
| `loadCuratedV2()` | v2 Drum Rack | 4 MIDI tracks with Drum Rack pads |

---

## 9. Quadrant Layout

### 9.1 8×8 Launchpad Grid

```
┌────────────────────────┬────────────────────────┐
│     DRUMS (4×4)        │      BASS (4×4)        │
│  Loops (top 2 rows)    │  Loops (top row)       │
│  One-shots (bottom 2)  │  Chromatic (bottom 3)  │
│  kick BL, snare above  │  or Scale / MIDI clips │
├────────────────────────┼────────────────────────┤
│     VOCALS (4×4)       │      OTHER (4×4)       │
│  Loops (top 2 rows)    │  Loops (top 2 rows)    │
│  One-shots (bottom 2)  │  One-shots (bottom 2)  │
└────────────────────────┴────────────────────────┘
```

### 9.2 Drum Pad Layout

```
Row 2 (top of one-shots):  [Snare] [HH-C ] [HH-O ] [Perc ]
Row 1 (bottom):            [Kick ] [Kick2] [Perc ] [Perc ]
```

Matches Ableton Push / MPC / drum machine convention.

---

## 10. Hardware Exporters

### 10.1 EP-133 KO II

- 46,875 Hz / 16-bit / mono (22,050 Hz budget mode)
- 4 groups × 12 pads: drums→A, bass→B(KEYS), melodic→C(KEYS), loops→D
- Memory budgeting: 128 MB, ~2.5 MB per track

### 10.2 Chompi TEMPO

- 48,000 Hz / 16-bit / stereo required
- Slice engine (14 slots): full stems, bar-aligned for clean auto-chop
- Chroma engine (14 slots): melodic phrases for chromatic playback
- Flat SD card directory, strict naming: `slice_a1.wav`, `chroma_a1.wav`

### 10.3 AbstractExporter Pattern

```python
class AbstractExporter(ABC):
    def export_compose(self, track_dir, output_dir) -> ExportManifest: ...
    def export_perform(self, tracks_dir, output_dir) -> ExportManifest: ...
```

Shared utilities: resample, mono/stereo conversion, bit-depth, peak normalize, bar-aligned trim.

---

## 11. Build & Deploy Pipeline

### 11.1 Development Flow

```
Edit source → Rebuild debug patch → Test in standalone Max
  → Build .amxd (build_amxd.py) → Build .pkg (build-pkg.sh)
  → Install → Test in Ableton
```

### 11.2 Key Build Commands

```bash
# Debug patch (fast iteration)
uv run python v0/src/maxpat-builder/builder.py \
  v0/interfaces/device.yaml --out v0/build/stemforge-debug.maxpat

# .amxd device (no JS embedding — uses Max Package)
uv run python v0/src/maxpat-builder/build_amxd.py

# Installer package (bundles binary + models + device + template)
STEMFORGE_VERSION=0.0.3 ./v0/build/build-pkg.sh

# JS auto-synced to Max Package during build-pkg.sh
```

### 11.3 Artifacts

| Artifact | Size | What |
|----------|------|------|
| `stemforge-native` | 394 KB | ONNX inference binary (CoreML EP) |
| `libonnxruntime.dylib` | 34 MB | ONNX Runtime |
| `htdemucs_ft_fused.onnx` | 665 MB | Stem separation model |
| `StemForge.amxd` | ~23 KB | Max for Live device |
| `StemForge.als` | ~14 KB | Ableton session template |
| Max Package | ~50 KB | JS files + shell.mxo external |

---

## 12. Testing

**108 tests** across 6 test files:

| File | Tests | Coverage |
|------|-------|---------|
| `test_forge.py` | 4 | Bar slicing, curation, strategy fallback |
| `test_modal_backend.py` | 7 | Modal SDK mocking, error handling |
| `test_oneshot.py` | 19 | One-shot extraction, drum classification, config |
| `test_segmenter.py` | 16 | Novelty, labeling, structure detection, dataclass |
| `test_exporters.py` | 37 | Base utils, EP-133, Chompi, CLI, bar-align |
| `test_midi_extractor.py` | 22 | Pitch detection, notes, key, pads, sections |
| `test_packaging.py` | 3 | Import isolation, friendly errors |

---

## 13. Configuration

### 13.1 Pipeline Config (`pipelines/default.yaml`)

Defines per-stem effect chains for 4 presets: `default`, `idm_crushed`, `glitch`, `ambient`.

### 13.2 Curation Config (`pipelines/curation.yaml`)

```yaml
layout:
  mode: stems              # stems | dj | dual-deck | session

stems:
  drums:
    phrase_bars: 1
    loop_count: 8
    oneshot_count: 8
    strategy: max-diversity
    oneshot_mode: classify   # kick/snare/hat layout
    distance_weights: { rhythm: 0.6, spectral: 0.2, energy: 0.2 }

  bass:
    phrase_bars: 2
    loop_count: 4
    midi_extract: true
    bottom_mode: melodic     # 12 chromatic pads + 4 loops
    chromatic_root: auto

song:
  boundary_method: recurrence
  min_segment_bars: 4
  max_segments: 8
```

---

## 14. Roadmap

| Phase | Status | What |
|-------|--------|------|
| v0.0.1 | Shipped | M4L device, stemforge-native, CoreML, .pkg installer |
| v0.0.2 | Shipped | Launchpad MVP (64 pads), Modal backend, Load Session |
| v0.0.3 | In progress | Curation engine v2, quadrant layout, Drum Racks |
| v0.1.0 | Planned | Waveform display, richer status strip, chip selectors |
| v0.2.0 | Planned | Stem mixer, spectroscope |
| v0.3.0 | Planned | In-device pad grid (matrixctrl + groove~) |
| v1.0.0 | Planned | DJ layout, sub-loops, combo pads |
| v2.0.0 | Vision | Dual-deck DJ mode, transition strategies |
