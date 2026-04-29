# Session Postmortem — April 18-19, 2026

## What We Built (The Good)

### Curation Engine v2 — Massive Feature Set
Over two days we built a complete audio curation engine from scratch:

- **One-shot extraction** (`stemforge/oneshot.py`) — multi-band onset detection, kick-from-bass recovery for htdemucs bleed
- **Drum hit classification** (`stemforge/drum_classifier.py`) — spectral heuristics for kick/snare/hat/clap/rim/perc, handles acoustic + electronic
- **Song structure detection** (`stemforge/segmenter.py`) — chroma + MFCC recurrence analysis, tested on 15+ tracks. Detected ABACDDA form on Prodigy, verse/hook separation on Tribe
- **MIDI extraction** (`stemforge/midi_extractor.py`) — pitch detection via pyin, key detection, section-aware MIDI clips, 3 bottom-half modes (melodic/scale/reconstruct)
- **Phrase-length grouping** (`stemforge/slicer.py`) — configurable 1/2/4/8 bar phrases per stem
- **Per-stem curation config** (`pipelines/curation.yaml`) — distance weights, phrase bars, strategy, loop/oneshot counts, processing pipelines
- **Section-stratified selection** — loops chosen to represent different song sections, not just spectral diversity
- **Hardware exporters** (`stemforge/exporters/`) — EP-133 + Chompi TEMPO with full CLI, memory budgeting, format conversion
- **Layout engine** (`stemforge/layout.py`) — quadrant pad mapping with LED colors
- **108 tests** — up from 14 at the start

### Launchpad MVP Improvements
- v2 loader with `SimplerDevice.replace_sample` (Live 12 API)
- Group track duplication per song
- `[dict]` Load Session with v1/v2 auto-detection
- Loops-only mode for reliable playback

### Documentation
- System design doc (500 lines)
- User guide (400 lines)
- Curation quality spec
- Instrument Rack quadrant setup guide
- MIDI quadrant router spec
- Audio validation handoff doc

### Infrastructure
- Build pipeline: JS auto-sync in build-pkg.sh
- Postinstall: CoreML warmup skip when cache exists
- Gemini validation script ready for audio quality auditing

## Where We Got Lost (The Bad)

### The Drum Rack Rabbit Hole
We spent 4+ hours chasing Drum Rack + Launchpad quadrant routing:
1. Built one-shot extraction → loaded into Drum Rack Simplers
2. Sample quality was poor (wrong durations, bad classifications)
3. Pivoted to loops-only Drum Racks
4. Then spent hours on quadrant MIDI routing:
   - Programmer mode port discovery (Standalone Port, not Live or MIDI)
   - Channel-based routing doesn't work for track-to-track in Ableton
   - `[send]`/`[receive]` approach — MIDI byte interleaving problem
   - `[midiout]` semantics confusion
   - .amxd sentinel discovery (`aaaa` vs `mmmm` vs `iiii`)
   - Finally arrived at Instrument Rack with key zones (the right answer)

**The lesson:** We should have validated the Ableton routing architecture BEFORE building the engine features. One hour of research would have saved four hours of trial and error.

### One-Shot Quality
The one-shot extraction produces samples that aren't musically useful:
- Duration windows too generous (500ms-2000ms — too long for one-shots)
- Drum classification brittle (bass notes classified as kicks, noise as hats)
- htdemucs stem bleed makes clean isolation difficult
- Need Gemini-based audio validation to tune parameters empirically

### Feature Creep
We built 5 major systems in rapid succession without validating each one in Ableton before moving on:
1. Config → 2. One-shots → 3. Drum classification → 4. MIDI extraction → 5. Exporters → 6. Layout → 7. Quadrant routing

Should have been: Config → loops working in Ableton → validate → THEN one-shots → validate → THEN the rest.

## What Needs Fixing (The Ugly)

1. **One-shot quality** — needs Gemini validation + parameter tuning before it's usable
2. **Drum Rack sample loading** — works (`replace_sample`) but the content isn't good enough
3. **Quadrant routing** — Instrument Rack approach is designed but not tested
4. **v1 vs v2 manifest confusion** — two loading paths, format detection is fragile
5. **Silent bar selection** — bars from sections where the stem is inactive still get through

---

## Three-Pronged Product Vision (Clarified)

### Prong 1: Production Mode (PRIMARY — IDM Music Making)
**Goal:** Generate high-quality stems and curated bars for DAW-based IDM production.

**Architecture:**
- 4 audio tracks × N clip slots (the v0.0.2 approach that worked great)
- Variable phrase lengths per stem (1-bar drums, 2-bar bass, 4-bar vocals)
- Section-stratified diversity selection
- NO one-shots needed in this mode
- Post-processing variants as additional tracks (crushed drums, verb textures)
- Production template with effect chains per tracks.yaml

**Status:** WORKING. The loops-only curate → clip-slot loader is the proven path. Just needs quality tuning (RMS floors, content density filtering) and the production template saved.

**What to do next:**
- Run Gemini validation on curated loops to tune quality
- Build the production template in Ableton (audio tracks, effect chains)
- Test with 5+ tracks to validate diversity across genres

### Prong 2: Play Mode (FUN — Saturated Launchpad Grid)
**Goal:** Fill every pad on the Launchpad with something playable and interesting from a song.

**Architecture:**
- 64 pads = 16 per stem, ALL loops (loops-only mode)
- Could include post-processing variants (same bar, different effects)
- One-shots on a separate Drum Rack IF quality improves
- Launchpad in Session mode for clip launch (simple, proven)
- OR Instrument Rack approach for Note mode (designed, not tested)

**Status:** PARTIALLY WORKING. Loops-only with 16 clips per stem works. The 64-pad Launchpad Session mode works (v0.0.2 proved this). Need to test with the diversified loops (varying phrase lengths).

**What to do next:**
- Install latest build, load The Champ in Session mode
- Validate the diversified loops sound good
- Design the "saturated grid" — fill empty pads with processing variants
- Test Instrument Rack quadrant approach when time permits

### Prong 3: Performance Mode (VISION — DJ Alternative)
**Goal:** Two songs on two Launchpads, stem-swapping between decks with transition strategies.

**Architecture:**
- Dual-deck: 8 MIDI tracks (4 per deck), each with Drum Racks
- Instrument Rack per deck with 4 chains
- Quadrant router per Launchpad
- Transition automation (stem swap, blend, drop, filter sweep)
- Session tempo locked to Deck A; Deck B stretches via groove~

**Status:** DESIGNED (in plan spec), NOT BUILT. Depends on Prongs 1+2 being solid first.

**What to do next:**
- Get Prong 2 working reliably first
- Build the Instrument Rack quadrant setup
- Test with one Launchpad before attempting dual-deck
- Consider Ableton Move as an alternative controller

---

## Priority Order

1. **Validate loop quality** (Gemini + listening) — this determines if the engine output is good enough
2. **Production template** — audio tracks + clip slots, the bread and butter
3. **Play mode testing** — loops-only on Launchpad Session mode
4. **One-shot quality tuning** — tighter windows, better classification
5. **Instrument Rack quadrant** — for Note mode Launchpad
6. **Performance/DJ mode** — dual-deck, transition strategies

---

## Commits on `feat/curation-engine-v2`

| # | What |
|---|------|
| 1 | Phase 1: config, one-shots, drum classifier, phrase-length, weights |
| 2 | Phase 2: song segmenter, all 3 curator strategies |
| 3 | MFCC-enhanced segment labeling |
| 4 | One-shots wired into pipeline + layout engine |
| 5 | Drum Rack templates + v2 loader |
| 6 | Hardware exporters (EP-133 + Chompi) |
| 7 | Exporter tests (37 tests) |
| 8 | MIDI extraction engine (22 tests) |
| 9 | Section-stratified loop selection |
| 10 | v2 loader with group duplication + replace_sample |
| 11 | System design + user guide docs |
| 12 | Section-stratified path fix |
| 13 | Curation quality spec |
| 14 | Loops-only mode + Gemini validator + handoff |
| 15 | MIDI quadrant router |
| 16+ | Router iterations (port discovery, byte packing, Instrument Rack pivot) |

**Branch:** `feat/curation-engine-v2` — 16+ commits, not yet merged to main.

---

## Key Lessons

1. **Validate in Ableton early and often.** Don't build 5 engine features before testing one in the DAW.
2. **Research Ableton routing constraints before building routing architecture.** The LOM has hard limits (no channel filtering for track-to-track, no programmatic Drum Rack creation, `midiout` semantics differ in M4L vs standalone Max).
3. **The clip-slot approach works.** Don't abandon what works for an unproven architecture.
4. **One-shots are a hard problem.** htdemucs stem bleed + naive onset detection = bad samples. Need multimodal AI validation to iterate on quality.
5. **Two templates, not one.** Production (clips) and Performance (Drum Racks/Launchpad) are different products sharing the same engine.
6. **The Standalone Port.** Launchpad Pro MK2 Programmer mode sends on the Standalone Port, not Live or MIDI. This cost us an hour.
