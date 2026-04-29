# StemForge Device UI — Production Mode Spec

> The M4L device panel for IDM production workflow.
> Control panel + results dashboard, not a real-time visualizer.

---

## 1. Layout (400 × 220 px)

Compact horizontal strip, fits in Ableton's device view without scrolling.

```
┌──────────────────────────────────────────────────────────────┐
│  StemForge                                          v0.3.0  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  [Browse...]  [Load]  [Re-curate]     BPM: 112  Key: Cm     │
│                                                              │
│  ┌─ Pipeline ──────────────────────────────────────────────┐ │
│  │  drums: 1-bar × 16 clips  +  8 one-shots  [●●●○○]      │ │
│  │  bass:  2-bar × 16 clips                   [●●○○○]      │ │
│  │  vocals: 4-bar × 9 clips                   [●○○○○]      │ │
│  │  other: 2-bar × 16 clips                   [●●○○○]      │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Processing ────────────────────────────────────────────┐ │
│  │  drums → [default] [idm_crushed] [+]                    │ │
│  │  bass  → [default] [+]                                  │ │
│  │  vocals → [default] [+]                                 │ │
│  │  other → [default] [glitch] [+]                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 100%  idle    │
└──────────────────────────────────────────────────────────────┘
```

## 2. Panel Breakdown

### A. Title Bar
- Device name + version
- Subtle, doesn't take much space

### B. Action Buttons + Song Info
- **Browse**: opens audio file dialog (FORGE mode — split + curate)
- **Load**: opens JSON manifest dialog (load pre-processed)
- **Re-curate**: re-runs curation with current settings (no re-splitting)
- **BPM**: detected tempo (read-only, from manifest)
- **Key**: detected key + mode (read-only, from MIDI extractor)

### C. Pipeline Summary (per-stem readout)
After loading, shows what was created for each stem:
- Stem name
- Phrase length × clip count
- One-shot count (drums only)
- **Diversity indicator** [●●●○○]: 5-dot visual showing how diverse the
  selected clips are (computed from feature vector spread). Full = very
  diverse, empty = similar-sounding clips.

Clicking a stem name could expand to show:
- Song section coverage (which sections the clips came from)
- Content density stats (% of clips with strong content)
- First-transient timing distribution

### D. Processing Pipeline (1-to-many mapping)
Shows which processing pipelines are applied per stem. Each stem can have
multiple output tracks with different effect chains.

- **Chip-style selectors**: each pipeline is a clickable chip
- **[+] button**: add another processing variant from the pipeline library
- Clicking a chip shows its effect chain (from pipelines/default.yaml)
- **This is the 1-to-many config** — adding "idm_crushed" to drums creates
  a second drum track with the crushed effect chain

Currently configured in `pipelines/curation.yaml` under `processing:`.
The device UI would read/write this config.

### E. Progress Bar + Status
- Standard progress bar (existing)
- Status text: current phase + percentage
- Color: violet=ready, yellow=processing, green=complete, red=error

## 3. Configuration (stored in curation.yaml)

The device reads and can modify `pipelines/curation.yaml`. Changes persist
across sessions. The UI maps to these config fields:

| UI Element | Config Field |
|-----------|-------------|
| Phrase bars per stem | `stems.{stem}.phrase_bars` |
| Loop count | `stems.{stem}.loop_count` |
| Strategy dropdown | `stems.{stem}.strategy` |
| Processing chips | `stems.{stem}.processing` |
| Distance weights | `stems.{stem}.distance_weights` |

Advanced settings (accessible via gear icon or right-click):
- RMS floor, crest min, content density min
- Downbeat correction on/off
- LarsNet on/off
- Bottom mode (melodic/scale/reconstruct) for pitched stems

## 4. The 1-to-Many Processing Pipeline

This is the key production feature. For each stem, you can specify
multiple processing pipelines. Each creates an additional track in the
song group:

```yaml
# In curation.yaml
stems:
  drums:
    processing:
      - pipeline: default        # → "Drums Loops | song" (clean)
      - pipeline: idm_crushed    # → "Drums Crushed | song" (destroyed)
      - pipeline: ambient        # → "Drums Ambient | song" (reverb wash)
```

**How it works in Ableton:**
1. Load manifest → 5-track group appears (base tracks)
2. For each stem with multiple pipelines, the loader:
   - Duplicates the base track
   - Renames: "Drums Crushed | song_name"
   - Applies the pipeline's effect chain parameters via LOM
   - Same clips, different processing

**Track group with 1-to-many:**
```
▼ Song Name
    Drums Loops | song        ← default pipeline
    Drums Crushed | song      ← idm_crushed pipeline (same clips, different FX)
    Drums Rack | song         ← one-shots
    Bass Loops | song         ← default pipeline
    Vocals Loops | song       ← default pipeline
    Other Loops | song        ← default pipeline
    Other Glitch | song       ← glitch pipeline (same clips, different FX)
```

**Effect application via LOM:**
The loader reads `pipelines/default.yaml` for each pipeline's effect chain,
then sets device parameters on the duplicated track:
```javascript
// For each effect in the pipeline chain:
var device = new LiveAPI("live_set tracks " + trackIdx + " devices " + deviceIdx);
device.set("parameter_name", value);
```

This requires the template tracks to have the effect devices pre-loaded
(Compressor, EQ, LO-FI-AF, etc.) — the loader just adjusts parameters,
it doesn't add new devices.

## 5. Template Layout Recommendations

### Production Template (StemForgeClips):

```
▶ SF | Templates (collapsed, gray)
    SF | Source            ← audio, StemForge device, gray
    SF | Drums Rack        ← MIDI, Drum Rack × 16 Simplers, red
    SF | Bass Rack         ← MIDI, Drum Rack × 16 Simplers, blue (future use)
    SF | Vocals Rack       ← MIDI, Drum Rack × 16 Simplers, orange (future use)
    SF | Other Rack        ← MIDI, Drum Rack × 16 Simplers, green (future use)
```

When a song loads, the group appears AFTER templates:
```
▶ SF | Templates
▼ My Red Hot Car (Squarepusher)
    Drums Loops | my_red...     ← audio, 16 clips, red
    Drums Crushed | my_red...   ← audio, 16 clips, dark red (if idm_crushed configured)
    Drums Rack | my_red...      ← MIDI, 8 one-shots, red
    Bass Loops | my_red...      ← audio, 16 clips, blue
    Vocals Loops | my_red...    ← audio, 16 clips, orange
    Other Loops | my_red...     ← audio, 16 clips, green
    Other Glitch | my_red...    ← audio, 16 clips, teal (if glitch configured)
```

### Naming Convention
- `{Stem} {Pipeline} | {song_name}`
- Default pipeline omits the pipeline name: `Drums Loops | song`
- Non-default shows it: `Drums Crushed | song`, `Other Glitch | song`

### Color Coding
- Drums: red family (#FF4444 default, #882222 crushed, #FF8888 ambient)
- Bass: blue family
- Vocals: orange family
- Other: green family
- Each pipeline variant gets a shade of the stem's base color

## 6. Implementation Phases

### Phase A: Static Summary Panel (quick win)
- After loading, show BPM/key/clip counts in the status text area
- No new UI elements, just richer status messages
- Existing device, no builder changes

### Phase B: Processing Pipeline Execution
- Read `processing` from curation.yaml
- For each additional pipeline, duplicate the base track
- Apply effect parameters from pipelines/default.yaml via LOM
- This is the 1-to-many feature

### Phase C: Full Config UI
- Add chip selectors, per-stem readout, diversity indicators
- Re-curate button (re-runs curate without re-splitting)
- Device grows to 400×220

### Phase D: Advanced Config Panel
- Gear icon opens advanced settings
- Edit weights, thresholds, strategy per stem
- Writes back to curation.yaml
