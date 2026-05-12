# StemForge — Top 3 Use-Case Workflow Plans

**Status:** active. Targets the configurator after Phase 4 ships
(scenes + slicer + splice editor + multi-target export).
**Companions:** [`STEMFORGE_CONFIGURATOR_SPEC_v4.md`](STEMFORGE_CONFIGURATOR_SPEC_v4.md)
(active spec — v3 archived under `archive/`),
[`../HARDENING_VERIFICATION.md`](../HARDENING_VERIFICATION.md).

## Hardware notes (load-bearing)

- **EP-133 K.O. II** — 4 groups × 12 pads × ≤99 scenes. MIDI clock in/out.
  Per-pad time mode (`bpm`/`bar`/`off`).
- **Chompi (TEMPO firmware)** — groovebox mode, MIDI clock sync (slave or
  master), 10-second sample length cap (16-bit 48kHz stereo WAV), two
  parallel sample engines, arpeggiator-meets-step-sequencer Pattern
  Generator with note probability and rest patterns, Slice Engine (16
  even slices across white keys), snapshot A/B for live recall, clock-
  synced FX (dual delay + diffusion reverb + freeze + sidechain ducking).
- **Chompi TAPE firmware does NOT support MIDI sync.** All cross-device
  workflows below use TEMPO. TAPE is mentioned only where relevant for
  sample-prep notes.
- **Chompi role here:** primarily an arpeggiator with tonal samples /
  single-cycle synthesis sources / drone fragments. Not a sample-loop
  player. The 10-second cap and Pattern Generator together make this the
  natural fit.

## Workflow ranking → use-case mapping (recap)

| Rank | Use case | Maps to user mode |
|---|---|---|
| 1 | EP-133 drum-break corpus + Chompi tonal arpeggiator (MIDI-synced) | super-creative |
| 2 | Drum-break corpus standalone (EP-133 only) | creative |
| 3 | Hip-hop × IDM blend set (EP-133 scenes, optional Chompi) | DJ-mode |

Workflows are presented in implementation order (#2 first as fastest win,
#1 next as the headline goal, #3 last as the most configurator-validating).

---

## Workflow #2 — Drum-break corpus (creative mode, EP-133 only)

**Concept:** A coherent kit of 90s sampledelic hip-hop drums, performable
as one set without song structure. Pure Workflow B (per Decision 12 of the
configurator spec).

### Source material

From the corpus, the tracks with strong drum stems suitable for a
sampledelic kit:

- A Tribe Called Quest — Electric Relaxation
- A Tribe Called Quest — Peace, Prosperity and Paper
- Digable Planets — Rebirth of Slick (Cool Like Dat)
- Outkast — Rosa Parks
- Pharoahe Monch — Simon Says
- Mos Def — Quiet Dog Bite Hard
- Jay-Z — 99 Problems

That's 7 tracks. Each has a `drums` stem from demucs.

### Configurator setup

**Project:** `creative_drum_corpus` (single Song, n=1)

**Configuration:** create `drums_corpus` config.
- All 4 EP-133 groups feed from the `drums` stem (same stem, different
  source tracks per group).
- Curation mode: `manual` for all groups (we'll hand-pick chunks; auto
  curation across 7 tracks would homogenize the kit).
- Post-processing: minimal. Maybe HPF on group A (kicks/snares) for
  punch, otherwise leave the 90s grit alone.

**Group → track mapping** (1:1 per Decision 14):
- Group A: chunks pulled from Tribe + Digable (laid-back jazzy breaks)
- Group B: chunks from Outkast + Pharoahe (driving, harder hits)
- Group C: chunks from Mos Def + Jay-Z (modern hip-hop production)
- Group D: chunks from Tribe (Peace, Prosperity) (a single track's
  variations, for cohesion)

This isn't strictly necessary — you could mix all 7 tracks into one group
— but gives you a clear "what am I playing" mental model per group.

**Scene:** one default scene, named `kit`. (Per Decision 12, single-scene
default; the scene strip is collapsed in the UI.)

### Pad layout (12 per group)

Per group, pads cluster from "core hits" at the bottom (low pad numbers)
to "fills/variations" at the top:

```
Group A — Tribe + Digable
─────────────────────────
Pad 7 (top-left)  : Digable break loop (2 bar)
Pad 8             : Tribe break loop A (2 bar)
Pad 9             : Tribe break loop B (2 bar)
Pad 4             : Digable kick + hat fill
Pad 5             : Tribe ghost-note pattern
Pad 6             : Digable percussion roll
Pad 1 (bottom-L)  : kick (one-shot)
Pad 2             : snare (one-shot)
Pad 3             : closed hat (one-shot)
Pad . (bot-corner): open hat
Pad 0             : clap
Pad ENTER         : crash/cymbal (rare hit)
```

Bottom row = single hits (one-shot mode). Middle row = fills (one-shot
mode). Top row = full breaks (loop mode, 2-bar `time_mode: bar`). Same
shape per group, different source tracks.

### Modes

- Bottom + middle row pads: `mode: oneshot`, `time_mode: off`.
- Top row pads: `mode: loop`, `time_mode: bar`, `bars: 2`.

### Performance approach

You're playing this as a drum machine, not a song. Bottom row for
finger-drumming patterns; top-row breaks as bedding when you want to
stop drumming and let the loop carry; middle row for fills between
phrases. Group switching (A/B/C/D) on the fly changes the source-track
character mid-set.

### Configurator features exercised

- Workflow B (single-scene kit) — Decision 12
- Manual curation per group — Decision 9
- Pad canvas as slot table — Decision 14
- Multi-target capability via Koala/Chompi projectors not needed here
  (EP-133 only) — but the validation surface is `validate()`-correct
  capacity (12 pads × 4 groups = 48 slots, well under 999 sample limit)
- Auto-curate skipped — confirms the configurator handles
  `provenance: manual` correctly

### Acceptance / "this works" check

You can perform a 15-minute drum set on the EP-133 alone, switching
groups, mixing one-shots and loops, without touching a laptop. The kit
feels stylistically coherent — someone listening would recognize "90s
hip-hop" as the unifying aesthetic.

### Deferred / v2 nice-to-haves

- Per-pad processing variations (one bank with HPF, one with bitcrush) —
  needs first-class post-processing pipelines (v2).
- Auto-curation pass that picks "12 most diverse drum chunks per source
  track" as a starting palette before manual tweaking. Today's auto-
  curation is per-stem, not per-source-track-grouped; could be useful
  here if extended.

---

## Workflow #1 — EP-133 drums + Chompi tonal arpeggiator (super-creative mode)

**Concept:** EP-133 plays the rhythm section using the Workflow #2 drum
kit (or a derivative). Chompi runs TEMPO firmware as a melodic
arpeggiator, MIDI-clock-synced to the EP-133, playing tonal samples
extracted from the IDM corpus. Two devices, two roles, one tempo.

### Source material

**EP-133 side:** the drum-break corpus from Workflow #2, or a streamlined
version (4 groups × 12 pads).

**Chompi side:** **tonal fragments from the Aphex Twin melodic tracks.**

Specifically:
- `aphex_twin_avril_14th` — single-note piano fragments, root notes
  in C-minor-ish territory
- `aphex_twin_rhubarb` — sustained pad fragments, harmonic tones
- `aphex_twin_xtal` — bell/synth fragments
- `aphex_twin_bucephalus_bouncing_ball` — bouncing tonal hits

Each ~1-2 seconds long, well within TEMPO's 10-second cap. All sourced
from the `other` stem of demucs (tonal/harmonic content).

Optional: drone samples in C from Chompi's official TEMPO sample pack as
a textural underlay if your tonal extracts feel thin.

### Stemforge setup (for Chompi sample export)

This is the workflow that **most needs the Chompi projector** (Decision 2
in the configurator spec — Chompi as v1 target).

**Project:** `super_creative_chompi_aphex` (single Song, n=1)

**Configuration:** `chompi_tonal_arp`
- Single group (Chompi has 12 sample slots per "preset" in TEMPO; we
  use one group = one preset)
- Source stems: `other` (tonal content) from each Aphex track
- Curation mode: `manual` — hand-pick the cleanest tonal fragments
- Post-processing: minimal. Maybe gentle HPF to remove sub rumble; no
  aggressive shaping (preserve Aphex character).

**Pad layout (12 slots):**

The **Slice Engine in TEMPO** is the key feature here. Two strategies:

**Strategy A — one sample per slot, Pattern Generator as arpeggiator:**
- 12 slots = 12 distinct tonal fragments (3 from each of 4 Aphex tracks)
- All in compatible keys (transpose at extraction time if needed; pick
  source phrases that center on C-minor or A-minor for cohesion)
- Chompi's Pattern Generator arpeggiates across them, using the
  white-key mapping
- **You play chord shapes on Chompi keys; the arpeggiator distributes
  hits across the underlying samples in tempo-synced patterns**

**Strategy B — fewer samples, more Slice usage:**
- 3-4 slots, each holding a longer Aphex phrase (~5s)
- Chompi's Slice Engine chops each into 16 even slices across white keys
- Pattern Generator sequences slice-triggers
- **You're sequencing slices of Aphex phrases against EP-133 drums**

**Recommendation: Strategy A for v1.** Slicing requires careful sample
prep (the slice points are even divisions, so the source has to cooperate
rhythmically). Single tonal fragments are forgiving.

### MIDI sync setup

EP-133 = MIDI clock master, Chompi = slave.

```
EP-133 [MIDI OUT] ──→ [MIDI IN] Chompi
```

Chompi TEMPO syncs to EP-133's clock, plays Pattern Generator at the
shared tempo. EP-133 scene-launch tempo changes propagate.

(Could also reverse — Chompi master, EP-133 slave — but EP-133 is the
"foundation" instrument here, so it's natural for it to be master.)

### Performance approach

1. Set EP-133 tempo (90-100 BPM territory for hip-hop). Chompi follows.
2. Launch a Workflow #2 scene on EP-133 (e.g., Group A drum loop on
   Pad 7, kick/snare ones-shots on bottom row).
3. On Chompi, dial up an arp pattern (note order, rest pattern, clock
   division) appropriate to the energy.
4. Hold a chord shape on Chompi keys. Pattern Generator arpeggiates the
   tonal samples against the EP-133 drums.
5. Live-modulate: chord changes on Chompi keys → Pattern Generator
   re-arpeggiates immediately. EP-133 group switches change drum
   character. Both stay in time.
6. Use Chompi's snapshot A/B for "verse vibe" vs "chorus vibe" recall.

### Stemforge → Chompi export pipeline

**This is the load-bearing technical work.**

The Chompi projector needs to:
- Take the abstract `ProjectSpec` for this project
- Validate against TEMPO's capabilities: 12 slots/preset, max 10s per
  sample, 16-bit 48kHz stereo WAV format
- Project the abstract pads onto Chompi's preset structure
- Write to a directory layout matching Chompi's TEMPO firmware SD card
  expectations (different from TAPE per the firmware docs)
- Handle the per-engine asymmetry: Chompi has two parallel sample
  engines; we likely use just one for v1 simplicity

**This work hasn't started.** Today's `KoalaExporter` exists; today's
Chompi exporter exists in some form (mentioned in the bundle), but it
was written for TAPE firmware. **The TEMPO projector needs to be built
from scratch as part of Phase 3** of the configurator plan, or Workflow
#1 doesn't exist.

### Configurator features exercised

- **Multi-target export** (Decision 2) — same `ProjectSpec` projects to
  EP-133 and Chompi simultaneously, or to one at a time
- **Chompi TEMPO projector** — first non-EP-133 first-class target;
  forces the abstraction to be real (not nominal)
- **Per-target validation** (`validate()` per projector) — Chompi's
  10-second sample cap is the test case for "validation lights up red
  in popup before export"
- **Workflow B kit** on Chompi side
- **Workflow A or B** on EP-133 side (B for kit-style; A if you want
  to map this to song scenes)

### Acceptance / "this works" check

You can perform a 20-minute set with EP-133 drums and Chompi arpeggiator,
both clock-synced, both fed by stemforge-produced sample banks. Drum
character (Group A vs B vs C vs D on EP-133) and harmonic character
(chord shape on Chompi) change live. Tempo changes on EP-133 propagate
correctly to Chompi. No laptop required during performance.

### Deferred / v2

- Multi-snapshot export (Chompi A/B snapshots populated by stemforge,
  not just one preset)
- Slice-Engine projector mode (export longer Aphex phrases for Strategy
  B above)
- Chompi-as-master mode (less likely needed but possible)
- Auto-tonal-curation (algorithmic "find harmonically compatible
  fragments across multiple sources") — orthogonal feature, not
  configurator-blocking

---

## Workflow #3 — Hip-hop × IDM blend DJ set (DJ-mode)

**Concept:** A continuous performance where scenes alternate between
recognizable 90s hip-hop and chaotic Aphex/Squarepusher IDM. The
juxtaposition is the artistic statement. Workflow A (per Decision 12) —
scenes are time-anchored, launched in song order.

### Source material

**Hip-hop side:**
- A Tribe Called Quest — Electric Relaxation
- Digable Planets — Rebirth of Slick
- Outkast — Rosa Parks
- Mos Def — Quiet Dog Bite Hard
- Jay-Z — 99 Problems

**IDM side:**
- Aphex Twin — vordhosbn
- Aphex Twin — 54 cymru beats
- Aphex Twin — cock_ver10
- Squarepusher — Beep Street
- Squarepusher — Vic Acid
- Squarepusher — Ill Descent

10 source tracks → ~12-16 scenes (some tracks contribute multiple
scenes for verse/chorus structure; some IDM tracks are too short for
multi-scene treatment).

### Configurator setup

**Project:** `dj_blend_hiphop_idm` (single Song, n=1 — but uses cross-
song splicing per Decision 7)

**Configuration:** `dj_blend`
- 4 groups: A=drums, B=bass, C=vocals, D=other
- Curation: `manual` per scene (use the slicer)
- Post-processing: differs by scene type (hip-hop scenes = subtle EQ;
  IDM scenes = bitcrusher / saturation as character)

### Scenes (the meat of this workflow)

This workflow uses **Live's Consolidate Time to New Scene** primitive
(per Decision 9) heavily. Process per scene:

1. Load source song into arrangement view via stemforge `forge`
2. Identify the section you want (e.g., Tribe verse 1, bars 17-32)
3. Select that time range in arrangement view
4. Run Create → Consolidate Time to New Scene
5. Live creates a new session-view scene with one consolidated clip per
   stem track
6. Configurator detects the new scene; you import it via slicer mini-UI
7. Name it (e.g., `tribe_verse_1`) and configure pad mode/settings
8. Repeat for the next source

Suggested scene order (~16 scenes):

```
1.  intro_drone        (Brian Eno — An Ending) — ambient bed, pad-style
2.  tribe_verse_1      (Electric Relaxation, bars 17-32)
3.  digable_chorus     (Rebirth, bars 1-16)
4.  squarepusher_drop  (Beep Street, the rhythm-violence section)
5.  outkast_chorus     (Rosa Parks, "Hey ya"-ish hook)
6.  aphex_glitch       (54 cymru beats, peak chaos)
7.  mos_def_verse      (Quiet Dog, ~16 bars)
8.  squarepusher_riff  (Vic Acid, melodic fragment)
9.  jay_z_chorus       (99 Problems, "got 99 problems...")
10. aphex_pad          (cock_ver10, slower section)
11. tribe_outro        (Peace Prosperity — outro vibe)
12. squarepusher_break (Ill Descent, breakdown)
13. pharoahe_simon     (Simon Says, the whistle/horn hook)
14. aphex_chaos_2      (vordhosbn, dense rhythmic section)
15. digable_outro      (Rebirth, fade-out)
16. ambient_close      (True Love Waits or Eno return) — soft landing
```

### Per-scene pad layout

Within each scene, pads are pre-filled by the slicer based on what
Consolidate produced (one consolidated clip per stem → ~4 pads).
Post-Phase 2.5, dedup runs as a *seed* (Decision 14); you then drag
pads to make explicit assignments.

For hip-hop scenes:
- Pad 1 (kick/drums consolidated)
- Pad 2 (bass consolidated)
- Pad 3 (vocals consolidated)
- Pad 4 (other / harmonic content)
- Mode: `loop` for the consolidated 4-bar (or 8-bar) sections,
  `time_mode: bar` so they tempo-stretch on scene launch

For IDM scenes (where stem separation is less clean):
- All 4 stems probably go to one or two pads
- Mode: `loop`, `time_mode: bar` if rhythmic; `time_mode: off` for
  textural Aphex like cock_ver10
- May benefit from `time_mode: bpm` if the IDM section locks to a
  specific BPM that differs from the project tempo

### Cross-tempo splicing — the R4 risk realized

This workflow **is** R4 in the configurator spec. Hip-hop sits 90-100 BPM;
Aphex/Squarepusher ranges 120-180 BPM. Some scenes will require
cross-tempo splice handling.

**Per Decision 11 + the hardening canonical fixtures:** test this
workflow against the Definition / Ooh La La / Believer fixtures *before*
trying it with real Aphex content. If a 120 BPM source spliced into a
90 BPM project produces drift, that bug needs fixing in the projector,
not worked around in performance.

### Performance approach

1. Set project tempo to ~92 BPM (hip-hop center of gravity).
2. Pre-load all scenes onto EP-133 via export. Each scene = one
   EP-133 scene.
3. Launch scenes in order via EP-133's scene-launch interface. The
   abrupt swap from hip-hop bars to IDM chaos *is* the artistic
   statement.
4. Within a scene, you can play pads to add/remove stems (mute the
   vocal pad to leave just the instrumental, etc.).
5. Cross-fade between scenes is via EP-133's transition handling
   (which is rougher than a software DJ but works at scene
   boundaries).

### Optional: Chompi underlay

If you have Chompi available + want the v3 ambient-glue feature
(Workflow #14 from the brainstorm):
- Chompi runs TEMPO with drone samples (Eno, Radiohead extracts) on
  one engine
- MIDI-synced to EP-133
- Plays continuously underneath, providing harmonic glue across abrupt
  scene transitions
- Pattern Generator on Chompi's drone engine = arpeggiated drones
  evolving across scenes

This adds the v1 multi-target export validation to the workflow.

### Configurator features exercised

- **Workflow A** (multi-scene song structure) — Decision 12
- **Slicer mini-UI wrapping Consolidate Time to New Scene** — Decision 9
- **Cross-song splicing across many tracks** — Decision 7
- **Cross-tempo handling** — Decision 11 + R4
- **Scene-launch performance** with EP-133 clock-synced
- **Multi-target export** if Chompi underlay added
- **Validation warnings** — 16 scenes with various group counts will
  exercise the projector's validate() output meaningfully

### Acceptance / "this works" check

You can perform a 30-minute DJ set live, launching scenes in order,
playing pads to mute/add stems within scenes, with the hip-hop ↔ IDM
juxtaposition feeling intentional rather than chaotic. Tempo handling
across cross-genre scenes works without audible drift.

### Deferred / v2

- Bidirectional locator sync (write back to arrangement so the set is
  scrubable in Live as well as performable on EP-133)
- Multi-song UI surface (right now, this is "single-song with 10
  splice sources" — could become "10 songs in one project" once v2
  multi-song UI lands)
- Auto-arrange suggestions ("here's a good scene order based on tempo
  proximity") — orthogonal feature
- Live performance recording back into Ableton via Arrangement Record
  (Decision 9 mentions; v2)

---

## Implementation order recommendation

**Build #2 first.** EP-133-only, no Chompi work, no cross-tempo splicing.
Validates: configurator end-to-end (forge → curate → configure → export →
play), Workflow B UX, drum-break corpus aesthetic. Fast win; you're
performing with it while #1 and #3 are in progress.

**Build #1 second.** Adds Chompi TEMPO projector (the load-bearing
unblocked work for non-EP-133 targets), MIDI sync between devices,
multi-target export. Validates Decision 2 (pluggable projectors) and
super-creative mode.

**Build #3 third.** Adds cross-tempo splicing exercise (R4 stress test),
slicer mini-UI maturity (16 scenes is real exercise), scene-launch
performance. Validates Workflow A, Decision 11, and the most ambitious
configurator surface.

The ordering also matches the configurator spec's phasing: Phase 4
(editor proper) ships #2 trivially; Phase 4 + Chompi projector port
ships #1; Phase 4 + heavy slicer use ships #3.

## What NOT to plan for in v1

- **DJ-mode crossfading between scenes** — EP-133 handles scene
  transitions but not crossfades; hardware-limited. Workflow #3 accepts
  this.
- **Chompi-as-master MIDI clock** — possible but not the natural fit;
  EP-133 master is cleaner.
- **Single-song multi-target with different content per target** —
  e.g., "EP-133 gets the drums-only version, Chompi gets the
  tonal-only version." Schema supports it; UI and projector logic for
  it is v2.
- **Live arrangement recording** — Decision 9 mentions Arrangement
  Record as a v2 path; not in any of these workflows.
