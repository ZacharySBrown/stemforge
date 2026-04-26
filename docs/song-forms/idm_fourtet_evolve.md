# `idm_fourtet_evolve` — Horizontal IDM (Four Tet / Caribou)

Horizontal evolution: organic accumulation of layers over time. Unlike the
Squarepusher form (which keeps the bed constant and varies drums), this
form lets every element grow and decay across the track.

## Tempo & length

- **BPM:** 110–130 (recommended start: 120)
- **Total bars:** 96 (≈ 3:12 at 120 BPM)

## Locators

| Bar | Name | Layer state |
|---:|---|---|
|   1 | `SEED`       | one looping element only — typically a melodic chop |
|  17 | `BUILD`      | + perc / shaker / texture |
|  33 | `ESTABLISH`  | + drums (kick/snare appear), motif locks |
|  49 | `VARIATION`  | melody mutates: pitch shift, new chop, harmony layer |
|  65 | `BLOOM`      | full arrangement, all elements present, biggest density |
|  81 | `DECAY`      | strip back: melody alone returns, ringing tails |

## Tracks

1. **Drums Loop** — sliced organic break (acoustic, soft transients)
2. **Drums Crushed** — parallel saturator/bitcrush of #1 (low send pre-BLOOM)
3. **Percussion** — shaker / tambourine / found-sound rhythm
4. **Bass** — sub OR upright sample on Simpler
5. **Melodic Chop A** — main motif on Simpler, slice mode
6. **Melodic Chop B** — pitched/chopped variant of A (5th up, octave down, etc.)
7. **Pad / Texture** — long evolving pad, gradual filter sweep
8. **Vocal Chop** — wordless vocal sample, used sparingly
9. **Reverb Send** — medium plate (3–5 s)
10. **Delay Send** — synced 1/8d with feedback ~0.5

## Starter chains

- **Drums Loop:** Compressor (gentle 2:1) → EQ Eight (gentle low-shelf) → Reverb send pre-fader
- **Drums Crushed:** Redux + Saturator + Auto Filter (gradually open over the track)
- **Bass:** EQ low-pass at 200 Hz → Compressor → subtle Saturator (warmth not grit)
- **Melodic Chops:** Simpler (slice) → Auto Pan (slow LFO) → Spectral Resonator (subtle shimmer) → Reverb send
- **Pad:** Wavetable → Hybrid Reverb (massive) → Frequency Shifter (cents range, slow)
- **Master:** Glue Comp gentle → broad warm EQ → soft limiter

## Sample-set inputs

- `Loops/Drums/<song>_drumloop_*.wav` — soft, organic, acoustic-leaning
- `Loops/Bass/<song>_bassloop_*.wav` — preferably acoustic/sub
- `Loops/Melodic/<song>_melodyloop_*.wav` — the SEED chop is critical here
- `Loops/Vocal/<song>_vocalloop_*.wav` — sparse use
- `Samples/Ambient/*.wav` — for the pad layer

## Sketching cue

The SEED chop carries the entire track. Spend 80% of your sketch time picking
it (Loops/Melodic/ is your friend). Once it's chosen, every other element
exists to support, vary, or decay around it. Resist adding drums before
bar 33 — the long lead-in is the genre's signature.
