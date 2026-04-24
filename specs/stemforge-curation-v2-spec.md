# stemforge — Curation Stage v2
## Trim Padding · Warp Markers · Per-Stem Offsets

**Version:** 2.0  
**Role:** Shared upstream stage. All export targets (Ableton, EP-133, future) consume its manifest output.

---

## Version Contract

| | v0 | v1 |
|--|----|----|
| Clip boundaries | Raw separation output (no padding) | Padded + warp markers auto-detected |
| Offsets | Not supported — `offsets.committed` always `false` | Full offset commit via M4L |
| Export reads | `raw_start_sec` / `raw_end_sec` directly | `padded_start_sec` + `start_offset_sec` |
| Warp markers | Written as stubs (start/end only) | Full transient/downbeat detection |
| Wide window | Not supported | Per-stem `bars` override in YAML |
| Manifest schema | **Same** — v1 fields present, zeroed | Fully populated |

**v0 and v1 share an identical manifest schema.** v0 just doesn't populate the offset and warp fields beyond stubs. Any export target (EP-133, Ableton) written against v0 continues to work in v1 without changes — it just gains precision automatically when `offsets.committed = true`.

---

## 1. Purpose

Raw Demucs/LALAL stems are cut at detected boundaries. Before any export target sees a stem, the curation stage:

1. Adds configurable **trim padding** on each end (default: 0.5 bars) — _v1_
2. Detects and writes **warp markers** (start, content_start, content_end, end) into the manifest — _v1_
3. Exposes a **wide-window** option per stem for stems with consistent drift — _v1_
4. Writes **per-stem offset** values into the manifest after Ableton fine-tuning — _v1_
5. Locks those offsets as the source of truth for all downstream exports — _v1_

**v0 target:** curation stage emits the manifest with `raw_start_sec` / `raw_end_sec` from the separator, `offsets.committed = false`, and stub warp markers. All export targets use raw boundaries directly. This is sufficient for a first working pipeline end-to-end.

The Ableton M4L loader is the **adjustment environment** — you drag warp markers, nudge clip boundaries, and commit offsets back to the manifest. The EP-133 export (and any future target) reads those committed offsets and applies them at export time.

---

## 2. YAML Config Schema

```yaml
curation:
  trim_pad:
    default_bars: 0.5          # Added to each end. 0.5 = half bar.
    unit: bars                 # "bars" | "beats" | "seconds"

  warp_markers:
    enabled: true
    mode: auto                 # "auto" | "manual_only"
    auto_snap: transient       # "transient" | "downbeat" | "none"

  loop:
    enabled: true              # Written to manifest; each target interprets
    loop_mode: none            # "none" | "loop" | "ping_pong"

  # Per-stem overrides
  stems:
    drums:
      trim_pad:
        bars: 0.5
      warp_markers:
        auto_snap: downbeat

    bass:
      trim_pad:
        bars: 1.0              # Wide window — bass drifts
      warp_markers:
        auto_snap: downbeat

    vocals:
      trim_pad:
        bars: 0.5
      warp_markers:
        auto_snap: transient

    other:
      trim_pad:
        bars: 0.5
      warp_markers:
        auto_snap: transient
```

**Key design decisions:**
- `default_bars: 0.5` is the global fallback
- Per-stem `bars` overrides the default — this is the wide-window switch
- `unit: bars` requires project BPM to convert to seconds; `seconds` is valid when BPM is unknown
- `mode: manual_only` skips auto detection and writes only start/end anchor markers

---

## 3. Curation Logic

### v0 (ship this first)

```
for each stem in separation_result:
    1. Load detected boundaries: raw_start_sec, raw_end_sec from separator
    2. Write manifest entry:
           clip.raw_start_sec      = raw_start_sec
           clip.raw_end_sec        = raw_end_sec
           clip.padded_start_sec   = raw_start_sec   ← same as raw in v0
           clip.padded_end_sec     = raw_end_sec     ← same as raw in v0
           clip.pad_bars           = 0.0
           clip.wide_window        = false
           warp_markers            = [stub start, stub end]
           offsets.committed       = false
           offsets.start_offset_sec = 0.0
           offsets.end_offset_sec   = 0.0
```

All export targets call `export_start = padded_start_sec + start_offset_sec` — which in v0 resolves to `raw_start_sec + 0.0`. No special-casing needed anywhere.

### v1 (additive, same manifest schema)

```
for each stem in separation_result:
    1. Load detected boundaries: raw_start_sec, raw_end_sec
    2. Resolve pad_bars = stems[stem].trim_pad.bars ?? curation.trim_pad.default_bars
    3. pad_sec = (pad_bars / project_bpm) * 60 * 4
    4. padded_start = max(0, raw_start_sec - pad_sec)
    5. padded_end   = min(total_duration, raw_end_sec + pad_sec)
    6. Run warp marker detection on [padded_start, padded_end] window:
           if mode == "auto":
               if auto_snap == "transient":  librosa.onset.onset_detect()
               if auto_snap == "downbeat":   librosa.beat.beat_track() → downbeats
           Generate [{time_sec, beat_pos, type}] list
    7. Write full manifest entry (see Section 5)
    8. Set offsets.committed = false (awaiting M4L fine-tuning)
```

---

## 4. Warp Marker Types

| Type | Description |
|------|-------------|
| `start` | Padded clip start — the outer boundary. Drag freely. |
| `content_start` | Where actual stem audio begins. Reference anchor. |
| `content_end` | Where actual stem audio ends. Reference anchor. |
| `end` | Padded clip end — outer boundary. Drag freely. |
| `transient` | Auto-detected attack point within content window. |
| `downbeat` | Auto-detected bar downbeat within content window. |

`content_start` and `content_end` are the adjustment targets. You drag them to actual transients in Ableton and commit the resulting offset. The `start`/`end` padding markers survive this movement as trim room.

---

## 5. Manifest Schema — Curation Block

```json
{
  "stem": "bass",
  "file": "bass.wav",
  "source_bpm": 128.0,

  "clip": {
    "raw_start_sec": 4.210,
    "raw_end_sec":   36.450,
    "padded_start_sec": 2.117,
    "padded_end_sec":   38.543,
    "pad_bars": 1.0,
    "wide_window": true
  },

  "warp_markers": [
    { "time_sec": 2.117,  "beat_pos": -4.0, "type": "start" },
    { "time_sec": 4.210,  "beat_pos":  0.0, "type": "content_start" },
    { "time_sec": 4.198,  "beat_pos":  0.0, "type": "transient" },
    { "time_sec": 36.450, "beat_pos": 128.0,"type": "content_end" },
    { "time_sec": 38.543, "beat_pos": 132.0,"type": "end" }
  ],

  "loop": {
    "enabled": true,
    "loop_start_sec": 4.210,
    "loop_end_sec":   36.450,
    "loop_mode": "none"
  },

  "offsets": {
    "committed": false,
    "start_offset_sec": 0.0,
    "end_offset_sec": 0.0,
    "note": ""
  }
}
```

---

## 6. Offset Commit Flow (Ableton → Manifest)

After loading stems into Ableton and adjusting warp markers:

```
M4L "Commit Offsets" button
    │
    ├── Read clip.start_marker from LOM
    ├── Read clip.end_marker from LOM
    ├── Compute start_offset_sec = start_marker - manifest.clip.padded_start_sec
    ├── Compute end_offset_sec   = end_marker   - manifest.clip.padded_end_sec
    ├── Write to manifest:
    │       offsets.start_offset_sec = <computed>
    │       offsets.end_offset_sec   = <computed>
    │       offsets.committed = true
    │       offsets.note = "adjusted to transient @ 4.198s"
    └── All export targets now read committed offsets
```

**Effective boundaries used by export targets:**

```
export_start = padded_start_sec + start_offset_sec
export_end   = padded_end_sec   + end_offset_sec
```

If `offsets.committed == false`, exports use padded boundaries directly.

---

## 7. Wide Window — Practical Use

For a bass stem consistently arriving a half-beat late:

```yaml
stems:
  bass:
    trim_pad:
      bars: 2.0   # 4 total bars of adjustment room
```

Load in Ableton, drag `content_start` to the actual attack, hit Commit. Every export target sees the corrected boundary without re-running curation.

---

## 8. EP-133 Sample Tool — Format Requirements

The EP Sample Tool requires:
- **Sample rate:** 46,875 Hz exactly (not 44.1k, not 48k)
- **Bit depth:** 16-bit
- **Max length:** ~40s stereo, ~80s mono

The curation stage writes the padded/offset boundaries into the manifest. The EP-133 export stage reads `export_start` / `export_end` and trims the audio tight (no padding) before resampling to 46,875 Hz. The EP-133's own Trim editor handles any final on-device micro-adjustment.

---

## 9. Audio Processing at Export Time (All Targets)

**Effective boundary resolution — same formula for v0 and v1:**

```
export_start = padded_start_sec + start_offset_sec
export_end   = padded_end_sec   + start_offset_sec
```

In v0: `padded_*` == `raw_*` and offsets are 0.0, so this resolves to raw boundaries. No branching needed in export code.

```
for each stem:
    1. Compute export_start, export_end (formula above)
    2. Slice audio to [export_start, export_end]
    3. Target-specific processing:
        Ableton:  write full padded file; M4L sets start_marker/end_marker/warp points via LOM
        EP-133:   resample to 46,875 Hz → dither to 16-bit → normalize → write {stem}_ep133.wav
    4. Write target-specific metadata block to manifest
```

---

## 10. M4L Warp Marker Application (Ableton Path)

```python
# Pseudocode — actual implementation in stemforge_loader.js

clip.start_marker = manifest["clip"]["padded_start_sec"]
clip.end_marker   = manifest["clip"]["padded_end_sec"]
clip.loop_start   = manifest["loop"]["loop_start_sec"]
clip.loop_end     = manifest["loop"]["loop_end_sec"]
clip.looping      = manifest["loop"]["enabled"]
clip.warp_mode    = 4  # Complex (default for stems)

for wm in manifest["warp_markers"]:
    clip.create_warp_marker(wm["time_sec"], wm["beat_pos"])
```

Warp mode reference:

| Value | Mode |
|-------|------|
| 0 | Beats |
| 1 | Tones |
| 2 | Texture |
| 3 | Re-Pitch |
| 4 | Complex |
| 5 | Complex Pro |

Default: `4` (Complex) for all stems. Expose as `warp_mode` in YAML per-stem if needed.

---

## 11. CLI Interface

```bash
# Run curation on a separation output
stemforge curate --input processed/song_name/ --config pipelines/default.yaml

# Run with wide window override at runtime
stemforge curate --input processed/song_name/ --wide-window bass --wide-window vocals

# Commit offsets from Ableton back to manifest (triggered by M4L button, or CLI)
stemforge commit-offsets --manifest processed/song_name/stems.json

# Export to EP-133 (reads committed offsets)
stemforge export ep133 --manifest processed/song_name/stems.json --out export/ep133/

# Export Ableton session data (reads committed offsets, triggers M4L reload)
stemforge export ableton --manifest processed/song_name/stems.json
```

---

## 12. Open Questions

1. **Source BPM detection:** Curation needs project BPM to convert `bars` to seconds. Currently assumes BPM is in the manifest from the split stage. Confirm field-miner / split stage always writes `source_bpm`.

2. **Warp mode per stem:** Complex (4) is the right default. Should vocals use Tones (1)? Expose as per-stem YAML option.

3. **Offset precision:** Offsets are in seconds. Should beat_pos also be offset and rewritten in warp markers after commit, or left as original reference?

4. **EP-133 Trim vs. padded export:** Current design sends tight (offset-applied) audio to EP-133. Alternative: send padded audio and encode trim points as EP Sample Tool metadata. Check if EP Sample Tool supports pre-set trim points on import.
