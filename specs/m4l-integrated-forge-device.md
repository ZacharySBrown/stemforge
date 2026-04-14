# StemForge M4L Integrated Device — Implementation Spec

> A single Max for Live device that leverages Ableton's audio analysis engine
> for beat/bar detection, drives Demucs stem separation, runs diversity-based
> beat curation, and loads curated breaks back into the session — all from
> one button press.

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Ableton Live Session                         │
│                                                                 │
│  ┌─ Audio Track ──────────────────────────────────────────────┐ │
│  │  [Audio Clip] ← user drops file here                      │ │
│  │     • Ableton auto-warps: tempo, time sig, warp markers   │ │
│  │     • User can manually correct before forging            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                          │                                      │
│  ┌─ StemForge Device (M4L, on same track) ───────────────────┐ │
│  │                                                            │ │
│  │  ┌─ UI Layer (Max patch) ─────────────────────────────┐   │ │
│  │  │  Waveform display (waveform~)                      │   │ │
│  │  │  Spectral analyzer (spectroscope~ / jit.catch~)    │   │ │
│  │  │  [FORGE] button                                    │   │ │
│  │  │  Status / progress display                         │   │ │
│  │  │  Stem mixer (gain sliders per stem)                │   │ │
│  │  │  Curated bar grid (16 pads)                        │   │ │
│  │  │  Strategy selector (max-diversity / taxonomy / etc)│   │ │
│  │  │  beats_per_slice control (1, 2, 4, 8)              │   │ │
│  │  └────────────────────────────────────────────────────┘   │ │
│  │                          │                                 │ │
│  │  ┌─ JS Bridge (stemforge_bridge.js, Node for Max) ───┐   │ │
│  │  │  1. Reads clip analysis via LOM                    │   │ │
│  │  │  2. Exports analysis JSON to temp file             │   │ │
│  │  │  3. Spawns Python subprocess                       │   │ │
│  │  │  4. Streams progress back to Max via stdout JSON   │   │ │
│  │  │  5. On completion, triggers WAV loading            │   │ │
│  │  └────────────────────────────────────────────────────┘   │ │
│  │                          │                                 │ │
│  │  ┌─ Python Backend (stemforge CLI) ───────────────────┐   │ │
│  │  │  stemforge forge <audio> --analysis <json>         │   │ │
│  │  │    1. Demucs stem separation                       │   │ │
│  │  │    2. Bar slicing using Ableton's grid             │   │ │
│  │  │    3. Beat curation (max-diversity)                │   │ │
│  │  │    4. Writes curated WAVs + manifest               │   │ │
│  │  └────────────────────────────────────────────────────┘   │ │
│  │                          │                                 │ │
│  │  ┌─ Playback Engine (Max patch) ──────────────────────┐   │ │
│  │  │  polybuffer~ loads curated bars                    │   │ │
│  │  │  Pad grid triggers (MIDI-mappable)                 │   │ │
│  │  │  Warp-to-session-tempo (groove~)                   │   │ │
│  │  │  Per-bar spectral display                          │   │ │
│  │  └────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Data Flow — Detailed

### 2.1 Ableton Analysis Extraction (M4L JS → JSON)

The M4L JS bridge reads clip properties via the Live Object Model:

```javascript
// stemforge_bridge.js — LOM extraction
function extract_clip_analysis() {
    // Get the clip on this track's first clip slot (or selected slot)
    var track_path = "live_set this_device canonical_parent";
    var track = new LiveAPI(track_path);

    // Find the clip — iterate clip slots to find first with a clip
    var slot_count = track.getcount("clip_slots");
    var clip = null;
    for (var i = 0; i < slot_count; i++) {
        var slot = new LiveAPI(track_path + " clip_slots " + i);
        if (slot.get("has_clip").toString() === "1") {
            clip = new LiveAPI(track_path + " clip_slots " + i + " clip");
            break;
        }
    }
    if (!clip) { error("No clip found"); return; }

    // Extract analysis data
    var analysis = {
        // Warp markers: pairs of [beat_time, sample_time]
        // beat_time = position in beats, sample_time = position in raw audio samples
        warp_markers: extract_warp_markers(clip),

        // Time signature
        time_signature: {
            numerator: parseInt(clip.get("signature_numerator")),
            denominator: parseInt(clip.get("signature_denominator"))
        },

        // Tempo (session-level)
        tempo: parseFloat(new LiveAPI("live_set").get("tempo")),

        // Audio file path
        file_path: clip.get("file_path").toString(),

        // Clip boundaries
        start_marker: parseFloat(clip.get("start_marker")),
        end_marker: parseFloat(clip.get("end_marker")),
        loop_start: parseFloat(clip.get("loop_start")),
        loop_end: parseFloat(clip.get("loop_end")),

        // Sample rate (from the audio file)
        sample_rate: parseInt(clip.get("sample_rate")),

        // Whether the clip is warped
        is_warped: clip.get("warping").toString() === "1"
    };

    return analysis;
}

function extract_warp_markers(clip) {
    // Warp markers are accessed as a flat array: [beat1, sample1, beat2, sample2, ...]
    var raw = clip.call("get_warp_markers");
    var markers = [];
    for (var i = 0; i < raw.length; i += 2) {
        markers.push({
            beat_time: parseFloat(raw[i]),
            sample_time: parseFloat(raw[i + 1])
        });
    }
    return markers;
}
```

### 2.2 Analysis JSON Schema

The bridge writes this JSON to a temp file that the Python backend reads:

```json
{
    "warp_markers": [
        {"beat_time": 0.0, "sample_time": 0},
        {"beat_time": 1.0, "sample_time": 23523},
        {"beat_time": 2.0, "sample_time": 47080},
        ...
    ],
    "time_signature": {"numerator": 4, "denominator": 4},
    "tempo": 112.35,
    "file_path": "/path/to/audio.wav",
    "start_marker": 0.0,
    "end_marker": 128.0,
    "loop_start": 0.0,
    "loop_end": 128.0,
    "sample_rate": 44100,
    "is_warped": true
}
```

### 2.3 Python Backend — New `forge` Command

```python
# stemforge/cli.py — new command

@cli.command()
@click.argument("audio_file", type=click.Path(exists=True))
@click.option("--analysis", type=click.Path(exists=True),
              help="Ableton analysis JSON (from M4L). If omitted, uses librosa.")
@click.option("--backend", "-b", default="demucs")
@click.option("--model", "-m", default="default")
@click.option("--strategy", "-s", default="max-diversity",
              type=click.Choice(["max-diversity", "rhythm-taxonomy", "sectional"]))
@click.option("--n-bars", "-n", default=14, help="Number of bars to curate")
@click.option("--output", "-o", default=None)
def forge(audio_file, analysis, backend, model, strategy, n_bars, output):
    """Full pipeline: split → slice bars → curate → output."""
    ...
```

### 2.4 Slicer — Ableton Grid Mode

New function in `stemforge/slicer.py`:

```python
def slice_at_bars_from_analysis(
    stem_path: Path,
    analysis: dict,
    output_dir: Path,
    stem_name: str,
    silence_threshold: float = 1e-3,
    normalize: bool = True,
) -> list[Path]:
    """
    Slice using Ableton's warp markers and time signature.

    Instead of running librosa.beat.beat_track(), we use the warp markers
    (which map beat positions to sample positions) and the time signature
    to compute bar boundaries directly.
    """
    numerator = analysis["time_signature"]["numerator"]
    warp_markers = analysis["warp_markers"]

    # Interpolate warp markers to get sample position for every beat
    beat_times = np.array([m["beat_time"] for m in warp_markers])
    sample_times = np.array([m["sample_time"] for m in warp_markers])

    # Generate a beat at every integer beat position
    all_beats = np.arange(beat_times[0], beat_times[-1], 1.0)
    all_samples = np.interp(all_beats, beat_times, sample_times).astype(int)

    # Group by bar (every `numerator` beats)
    bar_samples = all_samples[::numerator]

    # Proceed with standard slicing logic using bar_samples as boundaries
    ...
```

### 2.5 Progress Streaming (Python → Max)

The Python backend prints structured JSON lines to stdout, which Node for Max reads:

```python
# In the forge command
def emit(event: str, **data):
    """Stream progress to M4L via stdout JSON lines."""
    print(json.dumps({"event": event, **data}), flush=True)

emit("started", track=track_name)
emit("progress", phase="splitting", pct=0)
# ... during Demucs ...
emit("progress", phase="splitting", pct=100)
emit("progress", phase="slicing", pct=0, bars=67)
# ... during slicing ...
emit("progress", phase="curating", pct=0)
# ... during curation ...
emit("complete", output_dir=str(output_dir), bars=14, manifest=str(manifest_path))
```

```javascript
// stemforge_bridge.js — reading progress
var proc = child_process.spawn("stemforge", ["forge", ...]);
proc.stdout.on("data", function(data) {
    var msg = JSON.parse(data.toString().trim());
    outlet(0, "progress", msg.phase, msg.pct);  // send to Max UI
    if (msg.event === "complete") {
        outlet(1, "load", msg.output_dir);  // trigger polybuffer~ load
    }
});
```

## 3. M4L Patch Structure

### 3.1 Max Patch Components

```
┌─ stemforge_device.amxd ─────────────────────────────────────┐
│                                                              │
│  ┌─ p ui_panel ──────────────────────────────────────────┐  │
│  │  [waveform~]           — clip waveform display        │  │
│  │  [spectroscope~]       — real-time spectral view      │  │
│  │  [textbutton "FORGE"]  — main action button           │  │
│  │  [live.text]           — status messages               │  │
│  │  [live.menu]           — strategy selector             │  │
│  │  [live.numbox]         — n_bars (12-16)                │  │
│  │  [live.dial] x4        — stem gains (drums/bass/etc)  │  │
│  │  [matrixctrl 4x4]     — 16-pad bar trigger grid       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ p audio_engine ──────────────────────────────────────┐  │
│  │  [polybuffer~ sf_bars] — holds curated bar WAVs       │  │
│  │  [groove~] x16         — playback with tempo sync     │  │
│  │  [selector~ 16]        — route active bar to output   │  │
│  │  [live.gain~]          — output level                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ p bridge ────────────────────────────────────────────┐  │
│  │  [node.script stemforge_bridge.js]                    │  │
│  │    inlet: "forge", "cancel"                           │  │
│  │    outlet 0: progress messages → ui_panel             │  │
│  │    outlet 1: load commands → audio_engine             │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ p spectral_viz (optional, Phase 2) ──────────────────┐  │
│  │  [jit.catch~ 2]       — capture audio to matrix       │  │
│  │  [jit.fft]            — spectral analysis             │  │
│  │  [jit.gl.mesh]        — 3D spectrogram render         │  │
│  │  [jit.window]         — embedded GL display           │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Pad Grid Behavior

Each pad in the 4x4 `matrixctrl` maps to one curated bar:
- **Click/MIDI note** → one-shot playback of that bar
- **Hold** → loop that bar
- **LED color** → derived from spectral centroid (low = warm/red, high = cool/blue)
- **LED brightness** → crest factor (punchier = brighter)
- Pads are MIDI-mappable so they work with Push, Launchpad, etc.

### 3.3 Tempo Sync

Curated bars have a known BPM (from Ableton's analysis). When session tempo differs:
- `groove~` stretches/compresses playback to match session tempo
- This is transparent — bars always play in time regardless of session BPM
- Useful for trying breaks from different tempos together

## 4. Implementation Plan — Phases

### Phase 1: CLI Foundation (Python only, no M4L)
**Goal:** `stemforge forge` command that works end-to-end from the terminal.

1. Add `forge` command to `cli.py`
   - Orchestrates: split → slice (bars) → curate → output
   - Accepts `--analysis` JSON for Ableton grid or falls back to librosa
   - Emits JSON progress lines to stdout

2. Add `slice_at_bars_from_analysis()` to `slicer.py`
   - Reads warp marker + time signature JSON
   - Interpolates to get per-beat sample positions
   - Groups into bars based on time signature numerator

3. Integrate `beat_curator.py` into main package
   - Move from `tools/` to `stemforge/curator.py`
   - Add `curate()` function that takes a strategy name and returns paths

4. Test with Hot Pants:
   ```bash
   # Librosa fallback (no Ableton)
   stemforge forge grooves/"09 - Hot Pants... I'm Coming I'm Coming.mp3" \
       --backend demucs --strategy max-diversity --n-bars 14

   # With mock Ableton analysis JSON
   stemforge forge grooves/"07 - Tombo In 7_4.mp3" \
       --analysis test_analysis_7_4.json \
       --backend demucs --strategy max-diversity
   ```

### Phase 2: M4L Bridge (Node for Max + JS)
**Goal:** M4L device extracts analysis and calls Python.

1. Write `stemforge_bridge.js` (Node for Max)
   - `extract_clip_analysis()` — LOM read
   - `run_forge(analysis)` — spawn Python subprocess
   - Progress streaming back to Max

2. Build basic Max patch
   - [FORGE] button → node.script → Python
   - Status text shows progress
   - On complete, loads WAVs into polybuffer~

3. Test in Ableton:
   - Drop audio on track → press FORGE → bars appear on pads

### Phase 3: Playback + UI Polish
**Goal:** Full interactive device with spectral viz.

1. 4x4 pad grid with matrixctrl + groove~ playback
2. Spectral display per bar (spectroscope~ switches source on pad select)
3. Stem mixer (if stems are kept as separate outputs)
4. Tempo sync via groove~
5. MIDI mapping for pads

### Phase 4: Advanced Features
- Drag-and-drop from Ableton browser directly onto device
- Real-time re-curation (adjust strategy/n_bars, re-curate without re-splitting)
- Multi-stem curated sets (curate drums + bass together, maintaining alignment)
- Export curated set as Ableton Drum Rack preset (.adg)
- 3D spectrogram visualization (jit.gl)

## 5. Gotchas & Known Issues

### 5.1 LOM / Warp Marker Access

**Gotcha: `get_warp_markers` may not exist in all Live versions.**
- The `clip.get_warp_markers` API was added in Live 11. Verify availability.
- Fallback: if warp markers aren't accessible, read `clip.length` and
  `song.tempo` to compute a rigid grid, then warn the user.

**Gotcha: Warp markers are sparse, not dense.**
- Ableton only stores warp markers where the user (or auto-warp) placed them.
- Between markers, timing is interpolated linearly. Our code must do the
  same interpolation (see `np.interp` in Section 2.4).
- An unwwarped clip may have only 2 markers (start and end).

**Gotcha: `file_path` may point to a decoded cache, not the original.**
- For MP3/FLAC clips, Ableton decodes to a WAV cache in the project folder.
- `clip.get("file_path")` returns the cache path, which is fine — it's a WAV.
- But if the project hasn't been saved, the cache path may be temporary.
  Always resolve the path and verify it exists before passing to Python.

### 5.2 Node for Max

**Gotcha: `node.script` has a 4KB stdout buffer limit per message.**
- If the Python process dumps a huge JSON blob, it'll get truncated.
- Solution: use newline-delimited JSON (one small object per line).
  Never dump the full manifest to stdout — write it to a file and send
  the path.

**Gotcha: `child_process.spawn` inherits Max's environment, not the user's shell.**
- The user's Python (with stemforge installed) may not be on Max's PATH.
- Solution: use an absolute path to the Python executable. During install,
  write the path to `~/.stemforge/python_path`. The JS bridge reads this.
  ```javascript
  var pythonPath = fs.readFileSync(
      path.join(os.homedir(), ".stemforge", "python_path"), "utf8"
  ).trim();
  ```

**Gotcha: Max freezes if the JS thread blocks.**
- Never use synchronous I/O in the bridge. All subprocess interaction
  must be async (event-driven via `proc.stdout.on("data", ...)`).

### 5.3 Demucs / PyTorch

**Gotcha: First run downloads ~80MB model to `~/.cache/torch/hub/`.**
- This can time out or fail silently. The bridge should detect this
  (Demucs emits progress to stderr) and show "Downloading model..." in the UI.

**Gotcha: MPS (Apple Silicon) can OOM on long tracks.**
- Demucs `apply_model` handles chunking, but very long tracks (>10 min) at
  high quality (`htdemucs_ft`) can still exceed MPS memory.
- Mitigation: add a `--max-duration` flag that splits the input audio into
  segments, processes each, and concatenates stems before slicing.

**Gotcha: torchaudio ≥2.11 defaults to torchcodec backend.**
- Already fixed in `demucs.py` (force `backend="soundfile"`), but watch for
  regressions on torchaudio updates. Pin torchaudio version in requirements.

### 5.4 Beat/Bar Detection

**Gotcha: librosa.beat.beat_track can hallucinate in sparse sections.**
- Intros, breakdowns, and outros with minimal percussion produce unreliable
  beat positions. Ableton's warp engine handles this much better (it uses
  the full mix, not just one stem).
- When using librosa fallback, consider running beat detection on the full
  mix rather than the drums stem for these sections.

**Gotcha: Odd time signatures need explicit handling.**
- `beats_per_slice` defaults to 4 (assumes 4/4). For 7/4 (Tombo), 6/8,
  5/4, etc., the Ableton analysis JSON provides the correct numerator.
- The librosa fallback has NO time signature detection. If no analysis JSON
  is provided, default to 4/4 but log a warning.
- Consider adding `--time-sig` CLI flag for manual override:
  `stemforge forge track.wav --time-sig 7/4`

**Gotcha: Pickup bars / anacrusis.**
- Many tracks start before beat 1 (pickup notes). Ableton's start_marker
  handles this. In librosa mode, the first detected beat may be beat 2 or 3.
- Solution: if the first warp marker's beat_time > 0, include the audio
  before it as a partial bar (label it `bar_000_pickup.wav`).

### 5.5 Curation

**Gotcha: 16-step rhythm fingerprint is too coarse for dense patterns.**
- A 16-step grid over a bar at 112 BPM = 16th notes. JB's ghost notes
  often fall between 16th-note positions (swing/microtiming).
- For curation accuracy, use 32-step grid internally but display as 16-step.
- Alternatively, use raw onset times (continuous, not quantized) for
  distance calculations and only quantize for display.

**Gotcha: Spectral flux onset detection misses ghost notes.**
- JB's ghost notes are low-velocity snare/hat taps. Spectral flux with a
  fixed threshold misses them.
- Better approach: adaptive threshold (local median + factor) or use
  librosa.onset.onset_detect with `backtrack=True`.
- Even better: when Ableton analysis is available, use Ableton's transient
  markers instead of computing our own.

**Gotcha: "Diversity" can select outlier garbage.**
- The greedy farthest-point algorithm maximizes distance, which can select
  noisy or artifact-laden bars (they're "different" because they're broken).
- Current mitigation: RMS floor filter (skip bars with rms < 0.005).
- Additional: add a minimum crest factor threshold (e.g., crest > 4.0) to
  ensure every selected bar has at least one clean transient.

### 5.6 Max Patch / UI

**Gotcha: `polybuffer~` reloads are not instantaneous.**
- Loading 14 stereo 24-bit WAVs takes a moment. Don't trigger pad playback
  until `polybuffer~` sends its "done" notification.
- Show a brief "Loading bars..." status in the UI.

**Gotcha: `groove~` time-stretch quality depends on mode.**
- For best quality when warping bars to session tempo, use `groove~` in
  "interp 1" mode. For extreme tempo changes (>±30%), consider using
  `elasticx~` (Cycling '74 package) instead.

**Gotcha: The device must work without Python installed.**
- If the user hasn't run `install.sh`, the FORGE button should fail
  gracefully with a clear error: "StemForge Python backend not found.
  Run install.sh first."
- Check for Python on device load, show status indicator (green/red).

### 5.7 File System / Paths

**Gotcha: Spaces and special characters in track names.**
- "Hot Pants... I'm Coming I'm Coming" — apostrophes, ellipsis, spaces.
- All paths must be quoted in shell commands. Python's `subprocess.run()`
  with list args (not `shell=True`) handles this correctly.
- The slug generator in stemforge already sanitizes filenames.

**Gotcha: Output directory conflicts.**
- If the user forges the same track twice, the second run overwrites the
  first. This is intentional (re-curation), but warn if the previous
  curated set was manually modified (check file mtimes vs manifest timestamp).

## 6. Testing Matrix

| Test Case | Librosa Fallback | Ableton Analysis | Notes |
|---|---|---|---|
| 4/4 steady tempo (Hot Pants) | ✓ baseline | ✓ | Compare bar boundaries |
| 4/4 with tempo drift (Fela) | ✓ expect drift | ✓ should be tight | Ableton wins here |
| 7/4 (Tombo) | ✗ will assume 4/4 | ✓ correct bars | Must test Ableton's 7/4 detection |
| 6/8 feel | ✗ ambiguous | ✓ if user sets time sig | May need manual override |
| Intro silence | ✓ skip silent bars | ✓ | Both should handle this |
| Very long track (>10 min, Fela) | ✓ slow but works | ✓ | Watch for MPS OOM |
| MP3 input | ✓ auto-converts | ✓ Ableton decodes | Path handling differs |

## 7. File Layout (Post-Implementation)

```
stemforge/
├── stemforge/
│   ├── cli.py              # + forge command
│   ├── slicer.py           # + slice_at_bars_from_analysis()
│   ├── curator.py          # moved from tools/beat_curator.py
│   ├── backends/
│   │   └── demucs.py
│   └── config.py
├── m4l/
│   ├── StemForgeDevice.amxd        # the integrated device
│   ├── stemforge_bridge.js         # Node for Max bridge
│   └── README_M4L.md              # updated
├── tools/                          # dev/test scripts (not shipped)
│   ├── run_plans.py
│   └── reslice_and_curate.py
├── specs/
│   └── m4l-integrated-forge-device.md  # this file
└── install.sh                      # updated to write python_path
```
