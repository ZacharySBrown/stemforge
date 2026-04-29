# MIDI Quadrant Router — Spec

> M4L MIDI device that splits an 8×8 controller grid into four 4×4 quadrants,
> each routing to a separate Drum Rack track. Enables all 64 pads visible
> and playable simultaneously on a single Launchpad/controller.

## Problem

Ableton's Drum Rack shows one 4×4 pad grid per track. To play all 4 stems
at once, the user must switch tracks. We want all 64 pads live simultaneously.

## Solution

A Max for Live **MIDI Effect** device placed on a dedicated routing track.
It receives raw MIDI from the controller, maps grid position to quadrant,
remaps note numbers to Drum Rack range (36-51), and routes to the correct
stem track via MIDI channel assignment.

## Grid Mapping

Controller sends notes based on grid position. The router maps:

```
Controller 8×8 grid (Programmer mode note numbers):
┌──────────────────────┬──────────────────────┐
│  TOP-LEFT (Drums)    │  TOP-RIGHT (Bass)    │
│  Notes → Ch 1        │  Notes → Ch 2        │
│  Remap to 36-51      │  Remap to 36-51      │
├──────────────────────┼──────────────────────┤
│  BOT-LEFT (Vocals)   │  BOT-RIGHT (Other)   │
│  Notes → Ch 3        │  Notes → Ch 4        │
│  Remap to 36-51      │  Remap to 36-51      │
└──────────────────────┴──────────────────────┘
```

Each Drum Rack track has MIDI input set to the routing track, filtered to
its specific channel (1/2/3/4).

## Launchpad Pro MK2 in Programmer Mode

Programmer mode note numbers (decimal):
```
Row 8: 81 82 83 84 | 85 86 87 88
Row 7: 71 72 73 74 | 75 76 77 78
Row 6: 61 62 63 64 | 65 66 67 68
Row 5: 51 52 53 54 | 55 56 57 58
─────────────────────┼────────────────
Row 4: 41 42 43 44 | 45 46 47 48
Row 3: 31 32 33 34 | 35 36 37 38
Row 2: 21 22 23 24 | 25 26 27 28
Row 1: 11 12 13 14 | 15 16 17 18
```

Quadrant detection from note number:
- **Column**: `(note % 10)` — cols 1-4 = left, cols 5-8 = right
- **Row**: `(note / 10)` — rows 5-8 = top, rows 1-4 = bottom

```
Top-left:  col 1-4, row 5-8 → Drums (Ch 1)
Top-right: col 5-8, row 5-8 → Bass (Ch 2)
Bot-left:  col 1-4, row 1-4 → Vocals (Ch 3)
Bot-right: col 5-8, row 1-4 → Other (Ch 4)
```

## Note Remapping

Each quadrant's 16 notes must map to Drum Rack notes 36-51 (C1-D#2):

```
Within quadrant (4×4):
  Row 4: pad 12(C#2) 13(D2)  14(D#2) 15(E2)    ← top row
  Row 3: pad  8(G#1)  9(A1)  10(A#1) 11(B1)
  Row 2: pad  4(E1)   5(F1)   6(F#1)  7(G1)
  Row 1: pad  0(C1)   1(C#1)  2(D1)   3(D#1)   ← bottom row
```

Formula: `drum_note = 36 + ((local_row - 1) * 4) + (local_col - 1)`

Where `local_row` and `local_col` are 1-4 within the quadrant.

## M4L Device Architecture

```
[midiin] → [js quadrant_router.js] → [midiout]

quadrant_router.js:
  - Receives note on/off
  - Computes quadrant from note number
  - Remaps to Drum Rack note (36-51)
  - Sets MIDI channel (1-4)
  - Passes through velocity unchanged
```

Alternatively, pure Max objects (no JS needed):
```
[midiin] → [midiparse] → note number
  → [expr] compute quadrant + remap
  → [midiformat] with channel
  → [midiout]
```

## Track Configuration

```
Track: "SF | Pad Router"     ← MIDI track, this device, receives from Launchpad
Track: "Drums | song"        ← MIDI From: "SF | Pad Router", Channel 1
Track: "Bass | song"         ← MIDI From: "SF | Pad Router", Channel 2
Track: "Vocals | song"       ← MIDI From: "SF | Pad Router", Channel 3
Track: "Other | song"        ← MIDI From: "SF | Pad Router", Channel 4
```

Each Drum Rack track's "MIDI From" is set to the router track, filtered
to its channel. The router track's monitoring is set to "In".

## LED Feedback

The router should also handle LED colors back to the Launchpad:
- Receive pad color data from each Drum Rack (via LOM or SysEx)
- Send color SysEx to the Launchpad with per-quadrant stem colors
- Drums = red pads, Bass = blue pads, Vocals = orange, Other = green

Launchpad Pro MK2 LED SysEx format:
```
F0 00 20 29 02 10 0A <pad> <color> F7   (single pad)
F0 00 20 29 02 10 0B <pad> <color> F7   (flashing)
```

## Ableton Move Compatibility

The Ableton Move has a 4×8 pad grid (32 pads). Layout options:
- **2 stems × 16 pads**: Top 4 rows = stem A, bottom 4 = stem B. Page-switch for C/D.
- **4 stems × 8 pads**: Each stem gets 2 rows (8 pads). All 4 visible.
- The Move connects as a standard MIDI controller — same router device works,
  just different note mapping.

## Implementation Priority

1. Build the JS-based MIDI router (works with any controller)
2. Add Launchpad Pro MK2 programmer mode mapping
3. Add LED color feedback
4. Add Move-specific mapping (future, when hardware available)

## Files

- `v0/src/m4l-js/stemforge_quadrant_router.js` — the routing logic
- `v0/src/maxpat-builder/router_builder.py` — generates the .maxpat
- Or: hand-build in Max and save as a preset in the Max Package
