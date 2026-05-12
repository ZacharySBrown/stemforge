# `lofi_aaba` — Lo-fi Hip Hop AABA

Loop-faithful lo-fi sketch. The artistry is in *almost-identical* repetition
with subtle drops at the BREAK. J Dilla / Nujabes territory.

## Tempo & length

- **BPM:** 80–95 (recommended start: 86)
- **Total bars:** 84 (≈ 4 min at 86 BPM, 4/4)

## Locators

| Bar | Name | Notes |
|---:|---|---|
|   1 | `INTRO`  | drums in slowly, no bass, vinyl crackle present |
|   5 | `A`      | full beat, all elements |
|  21 | `B`      | reharmonization or new sample focus, drums same |
|  37 | `A'`     | back to A material with one subtle variation (filter, swap) |
|  53 | `BREAK`  | drums drop out OR bass drops, vocal/melodic exposed |
|  61 | `A''`    | full return, biggest moment of the track |
|  77 | `OUT`    | filter sweep / tape stop / fade to vinyl crackle |

## Tracks (order top → bottom in arrangement)

1. **Drums Loop** — sliced break or programmed kit; chops on a Simpler
2. **Drums Crushed** — parallel of #1 with heavy saturation/bitcrush
3. **Bass Mono** — sampled upright bass or Operator sub
4. **Keys** — Rhodes/Wurli sampled, slightly detuned
5. **Sample Loop A** — palette slot for dragged-in curation output (vocal chops / instrumental hook)
6. **Sample Loop B** — second palette slot
7. **Texture Send** — vinyl crackle, room tone, tape hiss
8. **Reverb Send** — short plate
9. **Delay Send** — analog-modeled slap

## Starter chains (per track type)

- **Drums:** Tape saturator (Drive ≈ 0.4) → Glue Comp (4:1, fast attack) → low-pass at 8 kHz
- **Drums Crushed:** Redux (8-bit) → Saturator (drive 0.7) → low-pass at 4 kHz
- **Bass Mono:** EQ Eight (high-cut at 2 kHz) → Glue Comp (2:1) → subtle saturator
- **Keys:** Multiband compressor → tape saturator → slap-delay send (1/8d)
- **Master:** Glue Comp (gentle, 1.2:1) → vinyl crackle on a parallel send → low-shelf -1 dB at 60 Hz

## Sample-set inputs (drag from `~/mus/Samples/`)

- `Loops/Drums/<song>_drumloop_4bar_*.wav` — main loop variants
- `Loops/Bass/<song>_bassloop_4bar_*.wav` — bass options for B section
- `Loops/Melodic/<song>_melodyloop_*.wav` — keys/sample chops
- `Loops/Vocal/<song>_vocalloop_*.wav` — optional vocal chops for hooks

## Sketching cue

Lock A into 16 bars, COPY to A' and A'' positions immediately, THEN start
varying. The temptation is to build A and stop — the locators exist to
force you into B and BREAK. Spend 80% of the time on those, not on
perfecting A.

## Building this template in Live (~25 min)

1. **New Set** → set tempo to **86 BPM**, time signature **4/4**.
2. **Switch to Arrangement view** (Tab).
3. **Insert locators** at the bars below. Easiest: type the bar number into
   the position display (top of arrangement), hit Enter to jump there, then
   `Cmd+L` to insert a locator. Right-click the locator to rename it:
   - bar 1 → `INTRO`
   - bar 5 → `A`
   - bar 21 → `B`
   - bar 37 → `A'`
   - bar 53 → `BREAK`
   - bar 61 → `A''`
   - bar 77 → `OUT`
4. **Set arrangement loop end** at bar 84 (so playback stops there).
5. **Create tracks** (Cmd+T audio, Cmd+Shift+T MIDI). Name + color each:
   - `Drums Loop` (red)
   - `Drums Crushed` (dark red)
   - `Bass Mono` (blue)
   - `Keys` (yellow)
   - `Sample Loop A` (orange) — palette slot for dragged-in curation
   - `Sample Loop B` (orange)
   - `Texture` (gray) — vinyl/room tone send target
6. **Add three return tracks** (Cmd+Alt+T): Reverb (short plate), Delay
   (1/8d slap), Texture (vinyl crackle bus).
7. **Insert chains per track** (see [Starter chains](#starter-chains-per-track-type)
   above). For lo-fi, Tape Saturator + Glue Comp + low-pass at 8 kHz on
   the master is the lo-fi-defining move.
8. **File → Save Live Set As…** → save to
   `~/mus/Templates/lofi_aaba Project/lofi_aaba.als`.
9. To use as a template start point, **File → Save Current Set as Default**
   *or* just `Cmd+O` and open this `.als` directly when sketching.
