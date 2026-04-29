# Instrument Rack Quadrant Setup — Launchpad Pro MK2

## Prerequisites
- Launchpad Pro MK2 in Programmer mode (Standalone Port)
- StemForgeQuadrantRouter M4L MIDI Effect installed
- Curated samples loaded

## Architecture
One MIDI track → Router → Instrument Rack with 4 chains.
Each chain receives a 16-note range, transposes to C1-D#2, feeds a Drum Rack.

```
Launchpad (Programmer mode, Standalone Port)
  → SF | Pads track
    → StemForgeQuadrantRouter (JS remaps 11-88 → offset note ranges)
    → Instrument Rack
      ├─ Chain "Drums"  key zone C1-D#2   (36-51)  Pitch: 0   → Drum Rack
      ├─ Chain "Bass"   key zone E2-G3    (52-67)  Pitch: -16 → Drum Rack
      ├─ Chain "Vocals" key zone G#3-B4   (68-83)  Pitch: -32 → Drum Rack
      └─ Chain "Other"  key zone C5-D#6   (84-99)  Pitch: -48 → Drum Rack
```

## Setup Steps

1. Create MIDI track `SF | Pads`
2. MIDI From → `Launchpad Pro (Standalone Port)`, All Channels
3. Drop `StemForgeQuadrantRouter` on the track
4. After the router, add **Instrument Rack** (Instruments → Instrument Rack)
5. Create 4 chains (right-click → Create Chain, ×4)
6. Name them: `Drums`, `Bass`, `Vocals`, `Other`
7. Click **Key** button to show key zones
8. Set key zones:
   - Drums: C1 to D#2 (notes 36-51)
   - Bass: E2 to G3 (notes 52-67)
   - Vocals: G#3 to B4 (notes 68-83)
   - Other: C5 to D#6 (notes 84-99)
9. In each chain, add **Pitch** MIDI effect before the Drum Rack:
   - Drums: Pitch = 0
   - Bass: Pitch = -16
   - Vocals: Pitch = -32
   - Other: Pitch = -48
10. In each chain, add a **Drum Rack** with 16 Simpler pads loaded with samples
11. Monitor → In
12. Put Launchpad in Programmer mode (hold Setup → orange pad)
13. Press pads — each quadrant triggers its Drum Rack

## Per-Chain Audio Routing
Right-click each chain → set Audio To for independent routing:
- Drums chain → return track or external out
- Bass chain → different return track
- etc.

## Saving as Template
Save the Instrument Rack as a preset (.adg): right-click rack title → Save Preset.
Drag onto any track for instant quadrant setup.

## Note Mapping Reference

```
Launchpad physical grid (Programmer mode):
Row 8: 81 82 83 84 | 85 86 87 88    → Drums (36-51) | Bass (52-67)
Row 7: 71 72 73 74 | 75 76 77 78
Row 6: 61 62 63 64 | 65 66 67 68
Row 5: 51 52 53 54 | 55 56 57 58
───────────────────┼───────────────
Row 4: 41 42 43 44 | 45 46 47 48    → Vocals (68-83) | Other (84-99)
Row 3: 31 32 33 34 | 35 36 37 38
Row 2: 21 22 23 24 | 25 26 27 28
Row 1: 11 12 13 14 | 15 16 17 18
```
