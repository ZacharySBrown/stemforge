# `idm_squarepusher` — Vertical IDM (Squarepusher / early Aphex)

Vertical evolution: same harmonic bed, drum chaos escalates. The bass and
chords stay relatively constant; what changes is rhythmic complexity.

## Tempo & length

- **BPM:** 140–170 (recommended start: 160)
- **Total bars:** 80 (≈ 2 min at 160 BPM — tight, dense)

## Locators

| Bar | Name | Drum complexity |
|---:|---|---|
|   1 | `INTRO`     | bass + pad only, no drums |
|   9 | `A`         | basic drum pattern, 1/16 hats |
|  25 | `A'`        | drum pattern doubles in density: ratchets, fills, time-stretched hits |
|  41 | `BREAK`     | drums fully out — bass/pad solo, cliff-edge tension |
|  49 | `CLIMAX`    | drum pattern at MAXIMUM — granular drums, glitch repeats, parallel stacks |
|  73 | `OUT`       | drums cut, bass+pad ring, hard cut at 80 |

## Tracks

1. **Drums Loop** — sliced break on Simpler (slice mode, transient)
2. **Drums Granular** — Granulator II on the same break, modulated grain size
3. **Drums Repeat** — clone with Beat Repeat (chance 0.6, grid 1/32)
4. **Drums Time-Stretch** — Simpler (texture mode), pitched chops
5. **Sub Bass** — Operator FM (Algo 4, mod=carrier ratio 1:1, fast envelopes)
6. **Pad / Chord Bed** — Wavetable, slow attack, 4–8 bar hold notes
7. **Glitch FX Send** — Spectral Time + Frequency Shifter
8. **Compressor Bus (drums)** — parallel compression, fast attack

## Starter chains

- **Drums Loop:** Compressor (4:1, fast) → Saturator → EQ Eight (slight bump 2 kHz)
- **Drums Granular:** Granulator II → Auto Filter with envelope follower → Reverb (small bright)
- **Drums Repeat:** Beat Repeat (Chance 0.6, Grid 7=1/32, Variation 5) → Compressor
- **Drums Time-Stretch:** Simpler texture mode → Erosion → Stereo Imager
- **Sub Bass:** Operator → EQ Eight (low-pass 200 Hz, sub focus) → Compressor (heavy 8:1)
- **Pad:** Wavetable → Hybrid Reverb (large) → Auto Filter slow LFO
- **Master:** Glue Comp (3:1, fast) → tape saturator → limiter

## Sample-set inputs

- `Samples/Breaks/Sliced/<song>_break*.wav` or `Loops/Drums/` — main break
- `Samples/Oneshots/{Kicks,Snares,Hats,Percussion}/<song>_*.wav` — for granular/repeat tracks
- `Samples/Loops/Bass/<song>_bassloop_*.wav` — sub-bass alternative
- `Samples/Loops/Melodic/<song>_melodyloop_*.wav` — pad bed

## Sketching cue

Lock the bass and pad EARLY (bars 1–8) — they will not change for the whole
track. Spend the rest of the session ONLY on drum variation. The drum
complexity arc (A → A' → CLIMAX) is the song's only real engine. If you
find yourself reaching for a chord change, you're writing a different form.

## Building this template in Live (~30 min)

1. **New Set** → tempo **160 BPM**, time signature **4/4**.
2. **Arrangement view**.
3. **Locators**:
   - bar 1 → `INTRO`
   - bar 9 → `A`
   - bar 25 → `A'`
   - bar 41 → `BREAK`
   - bar 49 → `CLIMAX`
   - bar 73 → `OUT`
4. **Arrangement loop end** at bar 80.
5. **Tracks**:
   - `Drums Loop` (red) — Simpler slot, slice mode
   - `Drums Granular` (red) — Granulator II
   - `Drums Repeat` (crimson) — Beat Repeat host
   - `Drums Stretch` (crimson) — Simpler, texture mode
   - `Sub Bass` (blue) — Operator FM
   - `Pad / Chord Bed` (mint) — Wavetable
6. **Returns**: Glitch FX (Spectral Time + Frequency Shifter), Drum Bus
   parallel comp (Compressor 8:1 fast attack), Reverb.
7. **Master**: Glue Comp 3:1 fast → tape saturator → limiter pushed.
8. **Set up an automation lane** on the drum bus volume — you'll want it
   later for the BREAK silence and CLIMAX ducks.
9. **Save** to `~/mus/Templates/idm_squarepusher Project/idm_squarepusher.als`.
