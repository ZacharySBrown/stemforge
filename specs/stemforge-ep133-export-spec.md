# stemforge — EP-133 Export
## BPM Sync · Play Modes · Mute Groups · Audio Format

**Version:** 2.0  
**Upstream dependency:** Curation Stage v2 manifest

---

## Version Contract

| | v0 | v1 |
|--|----|----|
| Clip boundaries used | `raw_start_sec` / `raw_end_sec` (offsets = 0) | `padded_start_sec` + committed offsets |
| Boundary formula | Same — `padded_start + start_offset` resolves to raw | Same formula, now meaningful |
| Play modes | Full — oneshot/key/legato + loop + mute groups | Same |
| Time stretch | Full — BPM and BAR modes | Same |
| SETUP.md | Generated | Same |
| Manifest schema | **Same** | Same |

**v0 ships the complete EP-133 export pipeline.** The only thing missing is fine-tuned boundaries — you get the raw separator cuts. v1 upgrades that transparently when `offsets.committed = true` in the manifest, with zero changes to export code.

---

## 1. Purpose

Takes the curated manifest (with committed offsets) and produces:

1. Per-stem WAVs formatted for EP Sample Tool (46,875 Hz / 16-bit)
2. Manifest metadata block with play mode, mute group, time-stretch config
3. A `SETUP.md` with pad assignment map and BPM sync instructions

The EP-133 is a **standalone performance target**. No Ableton. No MIDI back to the host. Ableton was the fine-tuning environment; the EP-133 receives the result.

---

## 2. EP-133 Capabilities — Confirmed

| Feature | Supported | Notes |
|---------|-----------|-------|
| BPM sync via MIDI clock (receive) | ✅ | System Settings → MIDI → Clock → On |
| USB MIDI class-compliant | ✅ | USB-C, no driver |
| TRS MIDI in/out | ✅ | TRS-A 3.5mm, adapter required |
| Analogue sync in/out (Sync24) | ✅ | PO / modular / vintage drum machines |
| Play mode: oneshot | ✅ | Monophonic, plays full sample on trigger |
| Play mode: key (gated) | ✅ | Polyphonic, plays while pad held |
| Play mode: legato | ✅ | Monophonic, continues position on retrigger |
| Loop per pad | ✅ | Loops sample after first trigger |
| Mute groups (choke) | ✅ | Up to 8 groups per project |
| Time stretch — BPM mode | ✅ | Stretch sample to match project BPM given source BPM |
| Time stretch — BAR mode | ✅ | Stretch sample to fit N bars exactly |
| Per-pad MIDI channel | ✅ | Sound Edit → MIDI |
| Trim (start point + length) | ✅ | Sound Edit → Trim (on-device micro-adjustment) |

**Not supported:**
- Latching toggle pad mode (workaround below)
- Cross-group choke (put competing sounds in same mute group)

---

## 3. Play Mode Strategy

Two modes cover all stem use cases:

### Mode 1 — Trigger + Loop (drums, bass)
- `play_mode: oneshot` + `loop: true`
- Fires on first press, loops continuously
- Re-trigger restarts from the top
- Closest to sticky/latching behavior available on-device

### Mode 2 — Gated (vocals, other, most melodic stems)
- `play_mode: key` — plays while pad is held, stops on release
- True "only on when pressed"
- `play_mode: legato` is the mono alternative — use for single-voice stems (e.g. lead vocal) where you never want voice stacking

### Mode Mapping

| Stem | Play Mode | Loop | Mute Group | Rationale |
|------|-----------|------|------------|-----------|
| drums | oneshot | true | 0 | Rhythmic loop, continuous |
| bass | oneshot | true | 1 | Rhythmic loop, chokes with itself |
| vocals | key | false | 2 | Gated, polyphonic OK for harmonies |
| other | legato | false | 0 | Gated, mono for single-voice stems |

Mute groups: pads in the same group choke each other (hi-hat style). Group 0 = no choke.

---

## 4. YAML Config Schema

```yaml
ep133_export:
  enabled: true

  sync:
    mode: midi_clock           # "midi_clock" | "sync24" | "usb_midi"
    master: ableton            # Ableton sends clock; EP-133 receives
    # EP-133 system setting: SHIFT+ERASE → MIDI → Clock → On

  defaults:
    play_mode: key             # "oneshot" | "key" | "legato"
    loop: false
    mute_group: 0              # 0 = no group, 1–8 = choke group
    time_stretch:
      mode: bpm                # "bpm" | "bar" | "none"
      source_bpm: null         # null = read from manifest source_bpm

  stems:
    drums:
      play_mode: oneshot
      loop: true
      mute_group: 0
      time_stretch:
        mode: bar
        bars: 4                # Stretch drums to fit 4 bars exactly

    bass:
      play_mode: oneshot
      loop: true
      mute_group: 1
      time_stretch:
        mode: bpm
        source_bpm: null       # Auto from manifest

    vocals:
      play_mode: key
      loop: false
      mute_group: 2
      time_stretch:
        mode: bpm
        source_bpm: null

    other:
      play_mode: legato
      loop: false
      mute_group: 0
      time_stretch:
        mode: bpm
        source_bpm: null

  pad_map:
    drums:  { group: A, pad: 1 }
    bass:   { group: A, pad: 2 }
    vocals: { group: A, pad: 3 }
    other:  { group: A, pad: 4 }
```

---

## 5. Audio Processing Pipeline

**Boundary resolution (same for v0 and v1):**
```
export_start = manifest.clip.padded_start_sec + manifest.offsets.start_offset_sec
export_end   = manifest.clip.padded_end_sec   + manifest.offsets.end_offset_sec
```
In v0: padded == raw, offsets == 0.0 → resolves to raw separator boundaries. No branching.

```
for each stem:
    1. Compute export_start, export_end (formula above)
    2. Slice audio to [export_start, export_end]  ← tight, no padding
    3. Resample to 46,875 Hz  (librosa.resample or soundfile)
    4. Dither + convert to 16-bit
    5. Normalize if peak > -1.0 dBFS
    6. Write to export/ep133/{stem}_ep133.wav
    7. Write ep133 metadata block to manifest
```

**Why tight trim at export:**
The EP-133's on-device Trim editor (Sound Edit → Trim) gives you start-point and length knobs for micro-adjustment. Sending tight audio there keeps the trim controls precise. Padding lives in Ableton; EP-133 gets the dialed-in result.

**Storage math:**
At 46,875 Hz / 16-bit stereo: ~40s ≈ 7.5 MB. 128 MB device cap → ~17 stems of 40s. For longer stems: use mono (doubles available length) or trim more aggressively during curation.

---

## 6. Manifest Schema — EP-133 Block

Written by the EP-133 export stage, appended to each stem's manifest entry:

```json
{
  "stem": "drums",
  "ep133": {
    "play_mode": "oneshot",
    "loop": true,
    "mute_group": 0,
    "time_stretch": {
      "mode": "bar",
      "bars": 4,
      "source_bpm": 128.0
    },
    "pad": { "group": "A", "pad": 1 },
    "audio": {
      "filename": "drums_ep133.wav",
      "sample_rate": 46875,
      "bit_depth": 16,
      "channels": "stereo",
      "duration_sec": 32.24,
      "export_start_sec": 4.210,
      "export_end_sec": 36.450
    }
  }
}
```

---

## 7. BPM Sync Setup

Recommended connection: **Ableton → USB-C → EP-133**

EP-133 settings (one-time):
```
SHIFT + ERASE → System Settings → MIDI → Clock → On
```

Once set, EP-133 locks to Ableton's tempo. Tempo changes in Ableton propagate immediately. The EP-133 time-stretch (BPM mode) stretches the imported sample to match whatever clock it receives.

Alternative: Sync24 via 3.5mm if running EP-133 without a computer (standalone performance with a pocket operator or modular as clock master).

---

## 8. Time Stretch — BPM vs BAR Mode

| Mode | Use when | EP-133 behavior |
|------|----------|-----------------|
| `bpm` | Stem length is a known musical duration at a known BPM | Stretches proportionally to current project BPM |
| `bar` | Stem is exactly N bars long | Stretches to fit exactly N bars regardless of original BPM |
| `none` | Stem is a one-shot hit or atonal sample | No stretching |

For stems with `offsets.committed = true`, the `source_bpm` in the manifest is the BPM at which the trimmed audio was curated. Use that directly.

---

## 9. Latch Workaround Detail

The EP-133 has no native latching toggle pad mode. Two options:

**Option A — oneshot + loop (automated, default for drums/bass):**
First press starts loop. Re-press restarts from top (does not stop). Sufficient for rhythmic stems where you want continuous playback.

**Option B — Sequencer pattern trigger (manual, full toggle):**
Program the stem as a looping sequencer pattern. The pad then starts/stops the pattern — true on/off toggle. Cannot be automated by stemforge export; requires manual on-device setup. Document in `SETUP.md` as an upgrade path.

---

## 10. Generated SETUP.md

Each export run writes `export/ep133/SETUP.md`:

```markdown
# EP-133 Setup — <song_name>

## BPM Sync
1. Connect EP-133 to Mac Mini via USB-C
2. EP-133: SHIFT+ERASE → MIDI → Clock → On
3. Ableton: set MIDI output to EP-133, enable Clock
Project BPM: 128.0

## Import Samples (EP Sample Tool)
Open EP Sample Tool. Import in this order:

| Pad | Group | File | Play Mode | Loop | Mute Group | Time Stretch |
|-----|-------|------|-----------|------|------------|--------------|
| 1 | A | drums_ep133.wav | oneshot | yes | — | BAR 4 |
| 2 | A | bass_ep133.wav | oneshot | yes | 1 | BPM 128.0 |
| 3 | A | vocals_ep133.wav | key | no | 2 | BPM 128.0 |
| 4 | A | other_ep133.wav | legato | no | — | BPM 128.0 |

## On-Device Sound Edit (per pad)
After import, for each pad:
  SHIFT + SOUND → navigate with +/- to:
  - Sound: set Play Mode (knobX)
  - Time: set BPM or BAR + value (knobX / knobY)
  - Mute Group: set group number (knobX)
  - Trim: fine-adjust start point if needed (knobX = start, knobY = length)

## Sticky Loop Upgrade (Optional — Drums)
To get true on/off toggle for drums:
  Program drums_ep133.wav as a looping sequencer pattern
  Assign a free pad to start/stop that pattern
  This replaces oneshot+loop with a pattern trigger
```

---

## 11. CLI Interface

```bash
# Export EP-133 package from curated manifest
stemforge export ep133 \
  --manifest processed/song_name/stems.json \
  --config pipelines/default.yaml \
  --out export/ep133/song_name/

# Output:
#   export/ep133/song_name/drums_ep133.wav
#   export/ep133/song_name/bass_ep133.wav
#   export/ep133/song_name/vocals_ep133.wav
#   export/ep133/song_name/other_ep133.wav
#   export/ep133/song_name/SETUP.md
#   (manifest updated with ep133 block)
```

---

## 12. Open Questions

1. **EP Sample Tool CLI:** GUI-only as far as documented. If an undocumented CLI or scripted import exists, the SETUP.md step becomes fully automated. Worth investigating.

2. **Mono export option:** For stems exceeding ~35s, halving file size via mono conversion doubles available device storage. Add `channels: mono` as a per-stem YAML option.

3. **Source BPM for trimmed clips:** After offset commit, the exported audio starts at `export_start_sec`. The `source_bpm` value in the manifest was detected on the full file. Confirm this BPM remains valid for the trimmed clip (it should, unless trim crosses a tempo change).

4. **Mute group ceiling:** EP-133 supports 8 mute groups. Add validation in the export stage: error if YAML defines more than 8 distinct non-zero group IDs.
