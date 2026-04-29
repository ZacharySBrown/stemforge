# EP-133 Archive Round-Trip: Capture Guide

**Goal:** Capture the SysEx read traffic the TE web tool generates when loading a project. This gives us the read protocol to port to Python, enabling full round-trip project editing (read → patch → write) — including playback modes, sample start/end, envelope, pan, pitch.

**Status:** Archive format is already fully documented (see below). Only missing piece is the read-path SysEx commands.

---

## What we already know

The project lives on the device as a **tar archive** at `/projects/NN`. Inside the tar, each pad is a binary file at `pads/{group}/p{pad_num:02d}` (e.g. `pads/a/p10`). The full byte layout:

| Byte(s) | Field | Values / Notes |
|---------|-------|----------------|
| 0 | unknown | |
| 1–2 | soundId | u16 LE — library slot number |
| 3 | MIDI channel | |
| 4–6 | trimStart | u24 LE — sample start in samples |
| 7 | unknown | |
| 8–10 | trimLength | u24 LE |
| 11 | unknown | |
| 12–15 | timeStretchBpm | f32 LE |
| 16 | volume | 0–255 |
| 17 | pitch | semitones; wraps at 256 for negatives |
| 18 | pan | values ≥240 are negative; divide by 16 to normalize |
| 19 | attack | |
| 20 | release | |
| 21 | timeStretch | 0=off, 1=bpm, 2=bars |
| 22 | chokeGroup | 0=false, 1=true |
| **23** | **playMode** | **0=oneshot, 1=key, 2=legato** |
| 24 | unknown | |
| 25 | timeStretchBars | |
| 26 | pitchDecimal | |

Source: `phones24/ep133-export-to-daw` — `src/lib/parsers.ts`, `src/types/types.ts`.

---

## Step 1 — Set 3 pads to 3 different playmodes

Use pads **"."**, **"0"**, and **"ENTER"** in Group A of **Project 1** (the bottom row of the beware drums). This gives us a known reference: when we parse the archive, byte [23] of each pad file should be 0, 1, and 2 respectively.

**For each pad:**

1. **Hold** the pad (keep it held throughout)
2. **Press SHIFT + SOUND** → display shows `SOUND EDIT`, lands directly on the playmode page (page 1 of 6)
3. Turn **KNOB X** to select the target mode
4. **Release** the pad
5. **Hold SHIFT + SOUND for 2 seconds** to save

| Pad label | pad_num | Target mode | KNOB X position |
|-----------|---------|-------------|-----------------|
| `.` (bottom-left) | 10 | **ONE SHOT** | first position (default — confirm, don't change) |
| `0` (bottom-middle) | 11 | **KEY** | second position |
| `ENTER` (bottom-right) | 12 | **LEGATO** | third position |

> **Note:** "Key" is the gated mode — sample plays only while the pad is held. "Legato" is monophonic hold-and-continue. "One-shot" plays the full sample on trigger regardless of hold.

---

## Step 2 — Capture the read traffic

1. Open **MIDI Monitor** and start a new capture
2. Open the [TE web tool](https://teenage.engineering/apps) in Chrome
3. Connect EP-133 via USB
4. Load **Project 1**
5. Wait for it to fully load (watch for the project name / pads to appear in the UI)
6. Stop MIDI Monitor
7. Copy all captured messages and paste into the section below

You do **not** need to export to Ableton or do anything else — just the load is enough. The read commands are what we're after.

---

## Capture results

### MIDI Monitor output — Project 1 load

```
PASTE MIDI MONITOR OUTPUT HERE
```

---

## Step 3 (optional but useful) — Second capture with a clean project

If you have a spare empty project on the device, load that too with MIDI Monitor running. A shorter read sequence (fewer pads assigned) will be easier to decode.

### MIDI Monitor output — empty project load

```
PASTE MIDI MONITOR OUTPUT HERE
```

---

## What happens next

Once we have the capture:

1. Decode the read command pattern (analogous to how we decoded FILE_PUT from Garrett's captures)
2. Port the read path to Python alongside the existing write path in `stemforge/exporters/ep133/`
3. Implement round-trip: `read_project(N)` → unpack tar → patch pad bytes → repack → `write_project(N)`
4. Add CLI: `stemforge ep133 project set-playmode -P1 -gA -p. --mode oneshot`

Full project generation from YAML (`stemforge ep133 project build <yaml>`) follows naturally from there.
