# `ambient_long_form` — Ambient (Eno / Hecker / Basinski)

Long-form, no hard transitions. The "form" is *which layers are present
when* — locators mark layer entries, not section changes.

## Tempo & length

- **BPM:** 60–80 (recommended start: 70 — slow enough for evolution, fast
  enough that 128 bars is ~7.3 min)
- **Total bars:** 128 (≈ 7 min at 70 BPM)
- **Time signature:** 4/4 (or 6/8 if you want lilt)

## Locators (layer-entry markers, not section breaks)

| Bar | Name | What enters |
|---:|---|---|
|   1 | `BED`     | drone bed only — long pad or field recording |
|  33 | `LAYER1`  | second textural element (granular, choir, broken radio) |
|  65 | `LAYER2`  | melodic motif (sparse, repeating) — first hint of pulse |
|  97 | `DECAY`   | strip back to BED + tail; let reverbs ring out |

## Tracks

1. **Drone Bed** — Wavetable pad on a long sustained note, *or* a sampled
   pad/choir loop with cross-fades to mask repetition
2. **Granular Texture 1** — Granulator II on a found-sound source
3. **Granular Texture 2** — second Granulator II, different source, panned opposite
4. **Field Recording** — looped environmental audio (rain, street, room)
5. **Melodic Motif** — sparse single-note sample on Simpler, triggered slowly
6. **Bass Drone Sub** — optional 60–80 Hz sine, very low level
7. **Convolution Reverb Send** — long IR (10–15 s tail)
8. **Delay/Spectral Send** — Spectral Resonator or long Echo

## Starter chains

- **Pad / Drone:** Hybrid Reverb (large hall, 100% wet on send) → Auto Filter
  with very slow LFO (0.05 Hz, full sweep) → Saturator (subtle warmth)
- **Granular textures:** Spectral Resonator → Erosion (high-pass noise mode)
  → wide stereo Echo (1/8d both sides)
- **Field recording:** EQ Eight (high-pass at 200 Hz, low-pass at 8 kHz to
  fit) → Compressor (gentle) → reverb send
- **Master:** broad EQ smile → very gentle bus compression (1.5:1, slow
  attack) → tape saturator
- **No drums.** If you must have a pulse: a single shaker, mute it 80% of
  the time.

## Sample-set inputs

- `Samples/Ambient/<source>_*.wav` — pads, drones, atmospheres
- `Samples/Loops/Melodic/<song>_melodyloop_*.wav` — sparse motifs
- `Samples/Vocals/<song>_vocalshot_*.wav` — choir-like or breath fragments

## Sketching cue

Resist drums. Resist tempo-locked elements. The form lives in *very long*
crossfades and the way Reverb tails carry energy across locators. If you
catch yourself adding a fourth element before bar 65, mute one.

## Building this template in Live (~25 min)

1. **New Set** → tempo **70 BPM**, time signature **4/4**.
2. **Arrangement view** (Tab).
3. **Locators** (jump to bar, `Cmd+L`, rename):
   - bar 1 → `BED`
   - bar 33 → `LAYER1`
   - bar 65 → `LAYER2`
   - bar 97 → `DECAY`
4. **Arrangement loop end** at bar 128.
5. **Tracks** (audio unless noted):
   - `Drone Bed` (purple) — destination for Wavetable or sampled pad
   - `Granular 1` (light purple) — Granulator II target
   - `Granular 2` (light purple)
   - `Field Rec` (gray)
   - `Melodic Motif` (mint) — Simpler with sparse single-note source
   - `Bass Drone Sub` (dark blue, optional)
6. **Three return tracks**: Convolution Reverb (long IR, 10-15s tail);
   Spectral / Delay (Spectral Resonator OR very long Echo with feedback);
   Texture (subtle saturator + filter sweep send).
7. **Master**: gentle bus comp 1.5:1 slow → broad EQ smile → tape saturator.
   Set Master output ceiling at -6 dBFS — ambient lives in low-RMS territory.
8. **Insert chains per track** (see chains section above). Especially
   important: Auto Filter with very slow LFO (~0.05 Hz) on the Drone Bed.
9. **Save** to `~/mus/Templates/ambient_long_form Project/ambient_long_form.als`.
