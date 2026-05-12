# `big_beat_drop` — Big Beat (Chemical Brothers / Prodigy / Fatboy Slim)

Drum-led, breakbeat-heavy, EXTREME dynamic contrast. The breakdown→drop
move is the genre's defining engine. Drop must land on a 16-bar boundary
or the whole structure deflates.

## Tempo & length

- **BPM:** 120–140 (recommended start: 132)
- **Total bars:** 128 (≈ 3:53 at 132 BPM)

## Locators

| Bar | Name | What's happening |
|---:|---|---|
|   1 | `INTRO`        | filter intro, drums build, no full break yet |
|  17 | `A`            | first full break drops, main groove |
|  33 | `BREAKDOWN`    | drums STRIP — bass+pad only, build with riser/sweep |
|  49 | `DROP`         | full energy: break + bass + stab + vocal sample |
|  81 | `BREAK`        | short stripped passage, 8 bars, drum fill at end |
|  89 | `DROP'`        | second drop, more elements, climax |
| 121 | `OUT`          | filter sweep, drum fill, hard cut at 128 |

## Tracks

1. **Break Loop** — sliced Amen / Apache / Funky Drummer on Simpler (slice mode)
2. **Break Crushed** — parallel of #1 with heavy bus comp + saturator
3. **Bass 303** — TB-303 emulation (Operator or external) with squelchy filter automation
4. **Bass Sub** — sustained sub-bass for the DROP sections
5. **Stab Sample** — short orchestra hit / horn stab on Simpler (one-shot)
6. **Vocal Sample** — chopped vocal phrase, classic big beat ad-lib
7. **Riser / FX** — automation lane lives here, builds at end of each section
8. **Reverb Send** — large bright plate
9. **Compressor Bus (drums+bass)** — heavy bus compression, fast attack

## Starter chains

- **Break Loop:** Glue Comp (4:1 fast attack, ratio 4) → Saturator (drive 0.5) → EQ Eight (low-shelf +2 dB at 80 Hz, slight 2 kHz cut)
- **Break Crushed:** Compressor (8:1, hard) → Redux 4-bit → Filter (low-pass at 6 kHz, automated)
- **Bass 303:** Filter automation lane is everything — start closed at INTRO, full open at DROP
- **Bass Sub:** EQ low-pass 200 Hz → Compressor heavy → Saturator (sub fatness)
- **Stabs:** EQ Eight (slight high-shelf bump) → short Reverb send → Auto Pan (subtle)
- **Master:** Glue Comp 3:1 fast → tape saturator → limiter (push it)

## Automation lanes (CRITICAL)

Big Beat lives in automation. Set up lanes in advance:

- Master low-pass filter — closes during BREAKDOWN, opens at DROP
- Drum bus volume — drops to silence for last beat of every 16-bar block
- Riser FX — increases over each pre-DROP build
- 303 filter cutoff — sweeps continuously

## Sample-set inputs

- `Samples/Breaks/{Classic,Modern}/*.wav` — Amen/Apache/Funky Drummer family
- `Samples/Oneshots/Kicks/<song>_kick_*.wav` — for parallel layered kick
- `Samples/Loops/Bass/*.wav` — sub-bass for DROP sections
- `Samples/Vocals/<song>_vocalshot_*.wav` — chopped ad-libs
- Ableton's stock Operator preset library has TB-303 starters

## Sketching cue

Build BACKWARDS from the DROP. Lock bar 49 first — full energy, every track
on, the moment everything "lands." THEN work backward to the BREAKDOWN
strip-down. Most failed Big Beat sketches put energy too early — the drop
is only powerful BECAUSE the breakdown was empty.

## Building this template in Live (~35 min)

1. **New Set** → tempo **132 BPM**, time signature **4/4**.
2. **Arrangement view**.
3. **Locators**:
   - bar 1 → `INTRO`
   - bar 17 → `A`
   - bar 33 → `BREAKDOWN`
   - bar 49 → `DROP`
   - bar 81 → `BREAK`
   - bar 89 → `DROP'`
   - bar 121 → `OUT`
4. **Arrangement loop end** at bar 128.
5. **Tracks**:
   - `Break Loop` (red) — Simpler slice mode (Amen/Apache/Funky Drummer)
   - `Break Crushed` (dark red)
   - `Bass 303` (blue) — Operator with squelchy filter automation
   - `Bass Sub` (dark blue) — for DROP sections only
   - `Stab Sample` (orange) — Simpler one-shot
   - `Vocal Sample` (yellow) — chopped phrase
   - `Riser / FX` (gray) — automation lives here
6. **Returns**: Reverb (large bright plate), Drum+Bass Bus (heavy parallel
   compression).
7. **Master**: Glue Comp 3:1 fast → tape saturator → limiter (push it).
8. **Set up automation lanes — CRITICAL for this form**:
   - Master low-pass filter (closes at BREAKDOWN, opens at DROP)
   - Drum bus volume (drops to silence end of every 16-bar block)
   - Riser FX (increases over each pre-DROP build)
   - 303 filter cutoff (continuous sweep)
9. **Save** to `~/mus/Templates/big_beat_drop Project/big_beat_drop.als`.
