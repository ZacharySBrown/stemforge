# StemForge Curation Quality Spec

> Defines what "good" curated output sounds like for each pad type,
> stem type, and layout mode. Used as the evaluation rubric for
> automated audio quality validation via multimodal AI.

---

## 1. Output Types

### 1.1 Bar Loops

A bar loop is a musical phrase extracted from a stem at bar boundaries.

**Duration:** Exact multiple of bar length at detected BPM.
- 1 bar at 120 BPM = 2.0s
- 2 bars at 120 BPM = 4.0s
- 4 bars at 120 BPM = 8.0s
- Duration tolerance: ±50ms (beat detection variance)

**Quality criteria:**

| Criterion | Pass | Fail |
|-----------|------|------|
| Musical content | Contains audible musical material for >80% of duration | Mostly silence with brief fragments |
| RMS energy | >0.02 (audible) | <0.01 (effectively silent) |
| Clean boundaries | Starts and ends near beat boundaries, no abrupt mid-note cuts | Starts mid-phrase, ends with hard clip |
| Loopability | Sounds musically coherent when looped | Jarring discontinuity at loop point |
| Stem isolation | Predominantly the target stem (drums=drums, bass=bass) | Heavy bleed from other stems |

**Per-stem expectations:**

| Stem | What a good loop sounds like | Common failures |
|------|-----------------------------|-----------------|
| Drums | Clear rhythmic pattern — kick, snare, hats audible. Full bar groove. | Silent bars (drum break/fill gaps), bleed from bass |
| Bass | Melodic bass line or riff. Clear pitch content. | Near-silent (bass only present in some sections), kick bleed |
| Vocals | Recognizable vocal phrase — words, melody, or ad-lib | Silent bars (vocals absent in instrumental sections) |
| Other | Texture, guitar, keys, or synth content | Residual noise, very quiet ambient bleed |

### 1.2 One-Shots

A one-shot is an isolated transient hit extracted from a stem.

**Duration targets by category:**

| Category | Ideal duration | Max acceptable | Notes |
|----------|---------------|----------------|-------|
| Kick | 50-200ms | 300ms | Short, punchy, sub-heavy |
| Snare | 80-250ms | 400ms | Transient + body + snare wire tail |
| Hi-hat closed | 30-100ms | 150ms | Very short, bright |
| Hi-hat open | 100-400ms | 600ms | Longer decay, bright |
| Clap | 50-200ms | 300ms | May have double transient (flam) |
| Rim/click | 10-50ms | 80ms | Extremely short, sharp |
| Percussion | 50-500ms | 800ms | Variable (toms, shakers, etc.) |
| Bass pluck | 100-500ms | 1000ms | Single note with decay |
| Vocal stab | 100-500ms | 2000ms | Single syllable or word |
| Texture hit | 50-500ms | 1000ms | Single textural event |

**Quality criteria:**

| Criterion | Pass | Fail |
|-----------|------|------|
| Single event | Contains ONE transient attack | Contains multiple distinct hits (it's a loop, not a one-shot) |
| Clean attack | Transient is preserved, no fade-in cuts the attack | Attack is cut off or masked |
| Clean decay | Natural decay or clean fade-out, no abrupt cut | Hard cut during sustain/decay |
| Isolation | Predominantly one sound | Multiple overlapping sounds |
| Energy | Peak >0.3, RMS >0.01 | Very quiet or near-silent |
| Duration | Within target range for category | Way too long (>1s for a kick) or too short (<10ms for anything) |

**One-shot anti-patterns (common failures):**

1. **"Loop disguised as one-shot"** — Duration >500ms for drums, contains multiple transients. Should be a loop, not a one-shot.
2. **"Noise floor sample"** — Very low RMS, no clear transient. Just background noise between hits.
3. **"Wrong stem bleed"** — Kick one-shot that's actually bass bleed, or vocal one-shot that's actually cymbal bleed.
4. **"Truncated hit"** — Attack is clean but decay is hard-clipped mid-sustain.
5. **"Silence with a blip"** — 500ms of silence with a tiny click somewhere in the middle.

### 1.3 Drum Classification

When one-shots are classified for the drum pad layout:

| Classification | Spectral signature | What it should sound like |
|----------------|-------------------|--------------------------|
| kick | Centroid <300 Hz, mostly sub/low-mid energy | Deep thump, boom, sub-bass punch |
| snare | Centroid 500-5000 Hz, wide bandwidth | Crack, snap, body + snare wire rattle |
| hat_closed | Centroid >5000 Hz, noise-like, short | Tick, tss, metallic click |
| hat_open | Centroid >5000 Hz, noise-like, sustained | Tsshh, sustained shimmer |
| clap | Mid-centroid, double transient | Clap, snap with slight flam |
| rim | Very short, high crest | Click, tick, rim shot |
| perc | Variable | Tom, shaker, conga, cowbell, etc. |

**Classification anti-patterns:**
1. **"Bass note classified as kick"** — Pitched bass pluck from bass stem bleed, not an actual drum hit
2. **"Cymbal wash classified as hat"** — Long reverb tail from cymbal, not a discrete hat hit
3. **"Noise classified as hat"** — Just high-frequency noise floor, not a real hi-hat

---

## 2. Per-Stem Output Expectations

### 2.1 Drums Quadrant (8 loops + 8 one-shots)

**Loops (pads 8-15, top 2 rows):**
- 8 distinct drum grooves, each one bar
- Should sound like different drum patterns from the song
- Diversity: different kick/snare patterns, fills vs straight grooves
- Energy: all should be clearly audible drum patterns (RMS >0.03)

**One-shots (pads 0-7, bottom 2 rows):**
- Layout: kick (pad 0,1), perc (pad 2,3), snare (pad 4), hat_closed (pad 5), hat_open (pad 6), perc (pad 7)
- Each should be a SINGLE isolated drum hit
- Duration: mostly under 300ms (kicks and perc can be longer)
- Should be usable for building new drum patterns by triggering pads

**Validation questions for each drum one-shot:**
1. Is this a single hit, or multiple hits?
2. Does the classification match what you hear?
3. Is the duration appropriate for the type?
4. Would you use this in a drum pattern?

### 2.2 Bass Quadrant (4 loops + chromatic/one-shots)

**Loops (pads 8-11, top row only in melodic mode):**
- 4 distinct bass phrases, each 2 bars
- Should be recognizable bass lines from different song sections
- Clear pitch content, not just sub rumble

**Chromatic pads (pads 0-7 in melodic mode, or pads 0-3 in other modes):**
- Single bass note mapped chromatically
- Each pad should produce a clean pitched tone
- Should be usable for playing bass lines on the pads

**One-shots (when not in melodic mode):**
- Individual bass plucks or notes
- Duration: 100-500ms
- Clear pitch, clean attack

### 2.3 Vocals Quadrant (8-12 loops + 4 one-shots)

**Loops:**
- 4-bar vocal phrases (8-10s at typical tempos)
- Should contain actual vocal content (words, melody)
- Silent/near-silent bars should NOT be selected
- Different phrases from different song sections preferred

**One-shots:**
- Individual vocal stabs: single words, syllables, ad-libs
- Duration: 100-500ms (up to 2s for longer words)
- Should be recognizable vocal fragments

### 2.4 Other Quadrant (8-10 loops + 6 one-shots)

**Loops:**
- 2-bar texture/instrument phrases
- Guitar riffs, synth pads, string stabs, etc.
- Should have audible musical content (not just noise/bleed)

**One-shots:**
- Textural hits: guitar stabs, synth plucks, percussion
- Duration: 50-500ms
- Should be distinct from drum one-shots

---

## 3. Overall Curation Quality

### 3.1 Diversity

Within each stem's selection:
- No two loops should sound identical (different musical content, not just volume differences)
- One-shots should span different timbral characteristics
- For drums: different groove patterns, not the same bar 8 times

### 3.2 Musical Usefulness

Every pad should produce a sound that a musician would want to use:
- No silent or near-silent pads
- No pads that are just noise/artifacts
- Each pad should be recognizable as the target stem type

### 3.3 Minimum Viable Output

For a curated session to be "usable":
- At least 6 of 8 drum loops should be clearly audible drum grooves
- At least 6 of 8 drum one-shots should be recognizable hits
- At least 3 of 4 bass loops should have clear bass content
- At least 8 of 12 vocal loops should have actual vocal content
- Zero pads should be effectively silent (RMS <0.005)

---

## 4. Validation Protocol

### 4.1 Automated Checks (Python)

```python
# For each curated WAV:
1. Duration within expected range for type
2. RMS above minimum threshold
3. Peak above 0.1
4. For one-shots: onset count == 1 (single transient)
5. For one-shots: duration within category bounds
6. For loops: duration matches expected bar length ±50ms
7. For drums: classification matches spectral heuristics
```

### 4.2 Multimodal AI Audit (Gemini 2.5 Pro)

For each curated WAV, ask the model:

**For loops:**
```
Listen to this audio file. It was extracted from the {stem} stem of a song 
at {bpm} BPM. It should be a {phrase_bars}-bar musical loop.

1. What do you hear? Describe the musical content in 1-2 sentences.
2. Does this sound like a {stem} stem? (yes/no/partial)
3. Is it mostly silence? (yes/no, estimate % silent)
4. Would this loop well? (yes/no)
5. Quality score 1-5: (1=garbage/noise, 3=usable, 5=excellent musical content)
```

**For one-shots:**
```
Listen to this audio file. It was extracted as a one-shot from the {stem} stem.
It is classified as: {classification}.

1. What do you hear? Describe the sound in 1 sentence.
2. Is this a single isolated hit, or does it contain multiple events?
3. Does the classification "{classification}" match what you hear? (yes/no, what is it actually?)
4. Is the duration appropriate? (too short / good / too long)
5. Quality score 1-5: (1=noise/artifact, 3=usable hit, 5=clean isolated drum hit)
```

### 4.3 Scoring Thresholds

| Score | Meaning | Action |
|-------|---------|--------|
| 1 | Garbage — noise, silence, artifact | Reject, investigate extraction bug |
| 2 | Poor — wrong content, bad isolation | Flag for parameter tuning |
| 3 | Usable — correct type, acceptable quality | Pass |
| 4 | Good — clean, musical, well-isolated | Pass |
| 5 | Excellent — studio-quality sample | Pass |

**Minimum passing:** Average score ≥3.0 across all pads, no individual score of 1.

---

## 5. Known Issues to Address

### 5.1 One-Shot Duration

Current extraction uses max windows of 500ms (drums), 1000ms (bass/other), 2000ms (vocals). These are too generous — many "one-shots" are actually short loops containing multiple hits.

**Fix:** Tighten windows AND verify single-onset count. If an extracted one-shot has >1 onset, either trim to the first onset's decay or reject it.

### 5.2 Silent Bar Selection

The RMS floor filters are set low enough that nearly-silent bars pass through. Bars from sections where the stem is inactive (e.g., vocal bars during instrumental sections) get selected.

**Fix:** Raise RMS floors per-stem, or add a "content density" metric that measures what fraction of the bar has audible content.

### 5.3 Stem Bleed in One-Shots

htdemucs bleed causes kick hits to appear in the bass stem, and bass notes to appear as drum one-shots.

**Fix:** Cross-stem deduplication — if a one-shot in the drum stem has very similar onset time and spectral content to a one-shot in the bass stem, it's likely bleed. Keep the one in the appropriate stem, discard the other.

### 5.4 Classification Accuracy

The spectral heuristic classifier works on clean, isolated hits but degrades when the one-shot contains bleed, reverb tails, or multiple events.

**Fix:** Post-classification validation — after classifying, verify that the one-shot actually sounds like its label using either spectral checks or multimodal AI audit.
