# StemForge Configurator Spec

**Status:** active, **v3**. Hardening pass complete as of 2026-05-08
(`HARDENING_VERIFICATION.md`). Phase 2 + Phase 2.5 complete. Configurator
work is unblocked.
**Companions:** `STEMFORGE_HARDENING_SPEC.md` (foundation),
`HARDENING_VERIFICATION.md` (acceptance + lessons),
`EXPORT_CONFIGURATOR_PLAN_v4.md` (archived reasoning),
four input bundles (design, testability, prior-art, UX inventory).

## Changes since v2

- **Decision 9 clarified** — Live's native primitives (Consolidate Time to
  New Scene, Capture and Insert Scene, Tab-drag, Cmd-J) are the canonical
  arrangement↔session bridge; the configurator observes them rather than
  reinventing them.
- **Decision 12 NEW** — Workflow A (time-based scenes) and Workflow B (free
  clip-to-pad kit) are equally first-class. Schema same; UI surfaces both.
- **Decision 13 NEW** — clip identity by content (audio_hash); same audio
  appearing in multiple places is one clip. Different playback semantics
  expressed at pad/slot level, not by duplicating clips.
- **Decision 14 NEW** — pad canvas is the slot table. Explicit user
  assignment, not implicit slot-claim algorithms.
- **Decision 15 NEW** — slot table has a single writer. Configurator HTTP
  server owns the slot-table state on disk; views are inputs (intents),
  not direct writers.
- **Schema simplification** — `SceneSpec.source_song_id` and
  `source_bar_range` become optional metadata, not required fields. Live's
  native scene tracking handles arrangement→session mapping; the
  configurator doesn't need to recompute it.
- **Risks updated** — R6/R7 retained from v2; R8 added for slot-claim
  algorithm now being a load-bearing contract.

## Goal

Replace stemforge's EP-133-specific export pipeline with a **target-agnostic
abstract scene model** that can be projected onto any compatible hardware
sampler. Provide a 2D editor UI for configuring projects against this model.
Connect arrangement view, session view, and curation through a unified
workflow.

## Why

Today, stemforge has three feature areas — arrangement, curation, and EP-133
export — that share concepts but don't share code. The export pipeline is
entangled with EP-133's specific topology (4 groups, 12 pads, 99 scenes).
Adding a new target (Koala, Chompi, MPC, SP-404) means duplicating the
plumbing.

The configurator does three things:

1. **Lifts shared concepts** (scenes, groups, pads, tile/repeat math) out of
   the EP-133 exporter into a target-agnostic layer.
2. **Adds projectors** that map the abstract model onto specific hardware
   topologies. EP-133 becomes one projector among several.
3. **Provides a UI** for building and tweaking projects against the abstract
   model, with multi-target export from one configuration.

The deeper rationale: the user's actual workflow is "I have stems and clips,
I want to perform/sample them on hardware." Today's pipeline is shaped by
the export format. The configurator inverts this — the workflow shapes the
data, and the export format is a projection.

## Scope

### v1 — what this spec covers

**Core configurator:**
- Abstract scene model with `Project → Song → Scene → Group → Pad` schema.
- EP-133 projector with byte-identical parity to current
  `stemforge export-song` output.
- Koala projector (existing exporter ported to projector interface).
- Chompi projector (existing exporter ported to projector interface).
- Multi-target export from popup (select EP-133 / Koala / Chompi).
- Configurator popup UI: scene strip, pad canvas with multi-axis selection,
  inspector with bulk-apply, audio preview, validation warnings.
- Slicer mini-UI: define named scenes by selecting bar ranges from
  arrangement view (creative selection, not locator-driven).
- Splice editor: cross-song scene splicing in the data model and UI.
- Strip device with full operations surface: load, slice, recompute,
  re-anchor, curate, export, open editor.

**Multi-song support:**
- Schema supports multiple songs from day one.
- v1 UI forces n=1; multi-song UI surface deferred to v2.
- Auto-grouping via pre-made template `.als` (default).
- Auto-grouping via AppleScript keystroke (experimental flag, macOS
  developer-only).

**Workflow connections:**
- `re-anchor --then-curate` flag: re-anchoring downbeat auto-triggers
  curation re-run.
- Read-only locator sync: locators in arrangement view drive scene
  definitions in the model. The reverse direction (writing locators back
  to arrangement view from the model) is v2.

**Skills + harness:**
- `skill.forge-pick` and `skill.forge-commit` unblocked by the
  `[udpreceive]` + `sf_remote` infrastructure (which lands as part of
  hardening).

### v2 — explicitly deferred

- Multi-song UI surface (song tabs, per-song scoping in popup).
- Bidirectional locator sync (the *write-back* half — model → arrangement
  view locators).
- Recent-clip enumeration for `skill.bounce-to-clip-and-collect`.
- `commit-with-bounce` skill (blocked on first-class post-processing
  pipelines, which is a separate subsystem).

### Indefinitely deferred

- Programmatic group creation through LOM (`call group_tracks` confirmed
  unavailable; AppleScript stays experimental).
- Mouse-click automation for any operation.
- Auto curation across multiple songs (manual splicing only).

## Load-bearing decisions

The calls that shape this spec. If any feels wrong, push back before the
work starts.

### Decision 1: abstract scene model is target-agnostic

The data model knows nothing about EP-133, MPC, Koala, or any specific
device. It's `Project → Song → Scene → Group → Pad` with arbitrary group
counts, pad counts, and scene counts. Targets enter only at the projection
step.

Concretely: `_event_positions_bars`, `_scene_lengths_in_bars`, and
`infer_bars` (currently in `song_synthesizer.py`) get lifted to
`stemforge/scene_model/`. They're already pure; the lift is mechanical.

### Decision 2: projectors are pluggable; EP-133, Koala, Chompi ship in v1

`AbstractProjector` interface with three methods: `capabilities()`,
`validate()`, `project()`. Adding a new target means subclassing this
interface and supplying device specifics in a `DeviceProfile`-shaped
data structure. No new test plumbing per device.

EP-133 stays the byte-identical reference (Phase 1 acceptance gate).
Koala and Chompi exist as exporters today and adapt cleanly. Three
targets in v1 forces the abstraction to be real, not nominal.

### Decision 3: clip identity is hash-based, not path-based

Per the hardening spec's Decision 4: `audio_hash` (16-hex sha256 prefix
of WAV bytes) is the identity. The configurator's clip refs use
`audio_hash`; the file path is advisory. This survives `re-anchor`
WAV regeneration without invalidating clip references.

This is foundation work and lands as part of hardening — not the
configurator itself. By the time configurator work starts, every chunk
has a hash.

### Decision 4: filesystem side-channel as primary I/O pattern

Same convention as the M4L device today: write artifacts to disk, tail
files, never poke back into Live or another running process for state
reads. The configurator popup talks to a local Python HTTP server; the
M4L device talks to the same server via `[shell]` + `[v8]`; everything
that needs to be observable writes to disk.

Rationale: this makes every layer testable via filesystem assertions
(extending the hardening spec's tier model into the new code). LOM
read-after-write is avoided everywhere.

### Decision 5: M4L device strip is the operations surface, popup is the editor

The M4L device strip (820×169) holds all controls for the workflow:
manifest selection, configuration selection, song scope, group scope,
track source, re-anchor, auto-curate, slice, export, open-editor. The
popup is for fine inspection and bulk editing — the 2D pad grid, scene
list, splice editor.

Both strip and popup talk to the same local Python HTTP server, which
holds the canonical `ProjectSpec` in memory and persists it to disk.

### Decision 6: local Python HTTP server, not Node-for-Max

Node-for-Max is broken on macOS 15.6+ with Live 12.2.7 / Max 9.0.8 (per
testability bundle R5). The viable transport is `[shell]`-launched Python
server + `[jweb]` pointing at `localhost:<port>` for the popup.

This sidesteps the macOS hardened-runtime issue, gives real frontend
tooling for the popup (SolidJS / React / etc.), and matches the bridge
pattern stemforge already uses for `m4l_export_clips.py` and
`m4l_locator_anchor.py`.

### Decision 7: cross-song splicing is supported in v1; multi-song UI is v2

Schema (`Project → Song → Scene`) supports cross-song splicing from day
one. The splice editor UI ships in v1's Phase 4 work — this is the
mashup workflow the user explicitly wants.

Multi-song UI (song tabs, per-song scoped operations in the popup) is
v2. Reason: the schema lift is foundational and cheap to do upfront;
the UI surface for multi-song is genuinely additive and can land later
without schema migration. Per Q5 of the design conversation.

### Decision 8: locator sync is read-only in v1

Locators in arrangement view drive scene boundaries in the abstract
model. The reverse direction — writing locators back to arrangement
view from the model — is v2.

Rationale: LOM `cue_point` writes have known quirks (per testability
bundle R8); building the read path first validates the data flow without
taking on the LOM-write risk. Reverse direction lands once the model is
proven.

### Decision 9: scenes are first-class objects; Live's native primitives are the bridge

Today, locators in arrangement view double as scene boundaries. The user
flagged this as "gross." In the configurator:

- Locators stay for downbeat anchoring (their original technical purpose).
- Scenes are defined by the user via Live's native primitives — the
  configurator observes them rather than reinventing them.
- A scene's `provenance` field records whether it was auto-curated, manual,
  or splice-defined.

**Native Live primitives the configurator leans on (verified in Live 12 docs):**

- **Consolidate Time to New Scene** (Create menu, or right-click on
  arrangement selection) — selects a time range in arrangement view and
  produces a new session scene with one consolidated clip per track.
  This is the *canonical* arrangement→scene primitive. The configurator's
  "slicer mini-UI" wraps this rather than reimplementing it.
- **Capture and Insert Scene** (Create menu) — captures currently-running
  session clips into a new scene. The canonical Workflow B primitive: jam
  with clips, find a combination, capture as scene.
- **Tab-drag** — held-clip + Tab during drag transfers between views.
  Manual but precise. Used by users directly; configurator doesn't need
  to script it.
- **Cmd-J Consolidate** within arrangement — replaces a selection with one
  new clip. Useful for tidying before a Consolidate to New Scene call.
- **Arrangement Record** + scene launching — record session-view
  performance into arrangement timeline. v2 territory but worth flagging.
- **Remove Stop Button** on session-view clip slots — makes clip slots
  transparent to scene launches. Critical for "linear backing track + per-
  track triggering" workflows. Has implications for EP-133 projector's
  pattern-launch semantics.

**What this means for the configurator's slicer:**

The "slicer mini-UI" in the popup is a thin wrapper that:
1. Asks the user for a name and (optionally) instructs them to select
   the relevant arrangement-time range and run Consolidate Time to New Scene.
2. Reads the resulting session scene via the LOM.
3. Builds the abstract `SceneSpec` from the scene's clips.

OR, going the other direction:
1. User triggers Capture and Insert Scene in Live directly.
2. Configurator detects the new session scene.
3. Same observation → SceneSpec build path.

**Schema implication:** `SceneSpec.source_song_id` and
`source_bar_range` become *optional metadata* (recorded if Consolidate
Time to New Scene was the source), not required fields. The configurator
doesn't track scenes by arrangement-time; it tracks them by the session-
view scene Live created.

The slicer is the manual-curation UX. Auto-curation is a separate path
that produces ungrouped clip kits (Workflow B); manual curation produces
named scenes with structure (Workflow A).

### Decision 10: schema multi-song-ready in v1, even though UI is single-song

Adding the `Song` layer between `Project` and `Scene` later is painful —
every projector, fixture, and snapshot.json shape would need migration.
Adding it now is free.

v1 forces `len(songs) == 1` everywhere a song-loop would appear. The UI
hides the song dimension. When v2 turns on multi-song UI, it's purely
additive.

### Decision 11: tempo-sensitive features require canonical real-audio regression fixtures

Synth fixtures are necessary but not sufficient. This is a load-bearing
lesson from the hardening pass (Stream E — see `HARDENING_VERIFICATION.md`
§4.1).

During hardening, live testing on Definition / Ooh La La / Believer
revealed that the tempo reconciler had been silently biased high by
~0.1–0.4% on every track for at least a week. Visible failure mode: clip
drift of +128ms by bar 12 of `drums_chunk_012.wav`. The synth fixture
didn't catch it — the bias only showed up against real audio with real
beat-this output. The fix expanded into Stream E (~9 additional checkboxes)
and produced the canonical fixtures at `tests/fixtures/known_tempos.py`
gated by `@pytest.mark.has_phase3_inputs`.

The lesson generalizes: cross-song splicing (a v1 configurator feature) is
in the same class — tempo-sensitive across multiple sources, with failure
modes that synth fixtures can't reproduce because the bug isn't in the
math, it's in how the math interacts with real beat-detector output.

**Concretely:**
- Cross-song splicing tests use the Definition / Ooh La La / Believer
  fixtures (or extensions thereof) as regression bar.
- Any new tempo-sensitive feature in the configurator adds its own
  canonical real-audio fixtures with `@pytest.mark.has_phase3_inputs`.
- Synth fixtures still cover the unit-level math (per Decision 4 of the
  hardening spec); they're not deprecated, just bounded.
- The CI tier-split holds: real-audio fixtures run on developer Mac, not
  in Linux CI, because the audio inputs aren't redistributable.

**What this is NOT:** a requirement that every test use real audio.
Per-pad mode editing, splice-editor UI, projector validation, etc. don't
need it. The rule is specifically for tempo-sensitive code paths —
anything that touches `refine_bpm`, `_bar_period_from_downbeats`, locator
math, scene-bar inference, or the splice-source-tempo handoff in the
projectors.

### Decision 12: two equally first-class workflows — time-based scenes (A) and free clip-to-pad kits (B)

The configurator supports two top-level user intents as primary, not as
primary + degenerate-case:

**Workflow A — time-based song structure.** User has arrangement-view
content; uses Live primitives (Consolidate Time to New Scene, Capture and
Insert Scene per Decision 9) to produce session scenes; configurator
imports those as scenes; pads on each scene reflect the per-track clips;
export produces a multi-scene preset on the target device. Scenes are
launched in song order for performance.

**Workflow B — free clip-to-pad kit.** User has a pile of clips (curated
session view, dragged in from outside, whatever); assigns them to specific
pads; export produces a single kit/preset. No scene structure; no song
time; just a performance-ready pad bank.

Both are expressible as `Project → Song → [Scene] → Group → Pad`:
- Workflow A: `len(scenes) > 1`, scenes time-anchored
- Workflow B: `len(scenes) == 1`, the single scene is just "the kit"

**UI implications:**
- Fresh project opens with **one default scene** (named "Default" or
  "Kit" — TBD in Phase 4 design). User can ignore the scene entirely
  and just work with the pad canvas (Workflow B) or define more scenes
  (Workflow A, naturally graduates from B).
- **Scene strip** is shown but collapsible/hideable when only one scene
  exists. Doesn't dominate the popup when the user is doing Workflow B.
- **Clip palette/pool sidebar** is essential and ships in v1 (per user
  decision). Drag-from-palette-to-pad is the primary Workflow B
  interaction. Also useful in Workflow A for "I want this clip from
  scene 1 on a pad in scene 2."

The schema cost of supporting both workflows is zero — same data model.
The UX cost is real (clip palette, scene-strip-collapsibility), but worth
it: Workflow B is a real performance use case for the EP-133, not just
"someone using Workflow A wrong."

### Decision 13: clip identity is by content (`audio_hash`), not by trim or processing

The same audio file appearing in multiple places — session view,
arrangement view, multiple pads, multiple scenes — is **one clip with
one identity** keyed by `audio_hash`.

**Different playback semantics are expressed at the pad/slot level, not
by duplicating clips:**
- Same clip on different pads with different trim points → one clip,
  two slot configurations with different `start_marker`/`end_marker`.
- Same clip on different pads with different post-processing → one clip,
  the configuration's per-track post-processing chain handles the
  difference.
- Same clip in different scenes with different modes (one-shot vs. loop)
  → one clip, two pad configs with different `mode`.

This matches Phase 2.5's COMMIT dedup-by-file_path approach and extends
it once Phase 3 wires `audio_hash` population at COMMIT time (today
`audio_hash` is empty string per the Phase 2 loose-end #1).

**The escape hatch when you genuinely need different *audio content*:**
re-export from the configuration with different post-processing applied
upstream, producing a new file with a different hash. That's a content
change, not a duplicate-clip change.

### Decision 14: pad canvas is the slot table; assignment is explicit

Slot N on the target device corresponds to cell (N mod cols, N div cols)
on the popup's pad canvas. **Clip-to-slot assignment is an explicit user
action — drag a clip onto a cell.** No implicit ordering, no
first-come-first-served, no surprises at export time.

**Implicit slot-claim algorithms are seeds, not source-of-truth:**
- Phase 2.5's COMMIT dedup-by-file_path + claim-next-free-slot (0..19)
  produces an *initial* slot assignment when a project is first opened.
- The popup displays this initial assignment in the pad canvas.
- The user drags clips to rearrange — that becomes the new source of truth.
- Re-running COMMIT does not silently overwrite user-arranged slots; the
  user's explicit assignments are preserved unless they ask to reset.

**This is the entire point of the 2D UI.** Today's COMMIT semantics
(implicit dedup, session-first ordering, silent overflow when >20 clips
exist) are correct as a *starting point* but become hostile when the user
has opinions. The pad canvas is where opinions are expressed.

This also clarifies what happens in Workflow 4 from the design discussion
(both views populated): the COMMIT dedup runs as a seed; the user then
explicitly arranges in the pad canvas; export reads the pad canvas, not
the implicit COMMIT output.

### Decision 15: slot table has a single writer (the configurator HTTP server)

Per Phase 2.5's "single-writer-per-fact" architectural insight: the slot
table on disk has **exactly one writer** in the configurator era — the
local Python HTTP server (per Decision 6).

**Today (pre-configurator):** COMMIT writes to two destinations — the
in-memory Max `sf_manifest` dict + `<source_dir>/curated/manifest.json`
on disk. This works because COMMIT is the only writer. Phase 3 introduces
a third potential writer (the popup); without discipline, three writers
to the same JSON would create drift.

**The discipline:**
- Configurator HTTP server holds the canonical `ProjectSpec` in memory.
- Persists to disk on a debounce (e.g. 500ms after last edit).
- All other surfaces — strip device, popup, COMMIT, future slicer —
  send *intents* to the server (POST/PATCH endpoints) rather than
  writing the slot table directly.
- COMMIT becomes one of those intent senders: "here's what I observed
  in session+arrangement view, please reconcile against your current
  state."
- The server reconciles, decides what changes apply, and broadcasts
  via SSE so other surfaces update.

**What this prevents:**
- The popup writing slot N=clip_A while COMMIT simultaneously writes
  slot N=clip_B. Last-write-wins races on shared state.
- The strip device showing stale state because it read the disk before
  the popup's debounced write.
- Reconciliation logic scattered across three writers, each with its
  own dedup and slot-claim quirks.

**Consequence for Phase 3 design:** the HTTP server's API shape is
load-bearing. Designing it as a clean intent-receiver (rather than a
thin file-writing proxy) is what makes this discipline survive contact
with reality.

## Plan

The work breaks into five phases. Order matters (each builds on the
previous), but specific deliverable ordering within a phase is determined
when picking the phase up. Hardening's acceptance gate is met as of
2026-05-08; Phase 1 is unblocked.

### Phase 1 — lift and split

**Outcome:** existing EP-133 export still works, but uses the new
abstraction.

Lift `tile`, `scene_lengths`, `infer_bars` to `stemforge/scene_model/`.
Define `AbstractProjector`. Refactor EP-133 exporter to implement it.
`stemforge export-song` produces byte-identical `.ppak` for hardened
fixtures. Wire `re-anchor --then-curate`.

**Acceptance:** byte-identical `.ppak` for every fixture; all hardening
must-keep-green paths still pass.

### Phase 2 — abstract scene model + multi-song schema

**Outcome:** full data model exists; single-song UI is the only live
surface.

Define `Project`, `Song`, `SceneSpec`, `GroupSpec`, `PadSpec` per the
schema in v4 §2. `Song` layer present from day one (forced n=1 in v1).
Generalize `sf_arrangement_reader.js` to write `Song`-shaped data. CLI
helper to build empty `ProjectSpec` from a manifest + config.

**Acceptance:** `ProjectSpec` round-trips through disk; single-song flow
works end-to-end (forge → curate → ProjectSpec → projector → `.ppak`)
byte-identical to Phase 1.

### Phase 3 — bridge, strip, popup shell, additional projectors

**Outcome:** M4L device exists; popup opens; multi-target abstraction is
real.

Local Python HTTP server (`tools/m4l_configurator_server.py`) with state
endpoints, SSE, projector triggers, audio preview. New `m4l-devices` repo
with strip device. Popup shell (SolidJS or equivalent). Port Koala and
Chompi exporters to projectors.

**Acceptance:** strip controls fire actions; popup loads via `[jweb]`;
each of the three projectors produces a valid bundle for a fixture project.

### Phase 4 — editor

**Outcome:** the configurator UI is real; users build and export
configurations.

Scene strip, pad canvas with multi-axis selection, inspector with
bulk-apply, audio preview, target capacity warnings. Slicer mini-UI for
manual scene definition. Splice editor for cross-song scenes.
Multi-target export.

**Acceptance:** user can build a multi-scene single-song project in the
popup, mix auto + manual curation, export to all three targets.

### Phase 5 — locator sync + skill bindings

**Outcome:** arrangement-view locators drive scene boundaries; skills
drive the device headlessly.

Read-only locator sync: arrangement → ProjectSpec → session view (one-way
write). Wire `skill.forge-pick` and `skill.forge-commit` against the
`[udpreceive]` infrastructure (which lands as part of hardening).

**Acceptance:** drop locators in arrangement, hit Sync, session view
populates with tiled clips; `sf_remote fire <target>` triggers device
actions on developer Mac.

## What this spec deliberately doesn't say

- **Wall-clock estimates per phase.** v4 had them; they were guesses
  anyway. Each phase is bounded by its acceptance criteria, not its
  duration.
- **Specific UI design details.** The mockup in v4 §6 stands as the
  current intent; final design happens in Phase 4. The load-bearing
  interaction decisions (multi-axis selection, bulk-apply contextual
  suggestions, color-encoded modes) are documented; pixel-level details
  aren't.
- **File-by-file refactor instructions.** v4 has them in §7; this spec
  references the v4 phasing rather than repeating it.
- **Frontend stack final choice.** SolidJS is the leading candidate (v4
  §6); React is acceptable. Decided when Phase 3 starts.

## Risks

**R1 — *(retired 2026-05-08)* Hardening's acceptance gate is met.** Phase 1's
"byte-identical" criterion is now verifiable against shipped tests. See
`HARDENING_VERIFICATION.md`.

**R2 — Three projectors in v1 (EP-133, Koala, Chompi) is real work.**
Existing exporter parity is the floor; making them implement
`AbstractProjector` cleanly without leaking device specifics into the
abstract layer is the actual challenge. Plan for genuine refactor cost,
not commodity adaptation.

**R3 — Phase 4's UI surface absorbs time.** Pad canvas with multi-axis
selection, inspector with bulk-apply, splice editor, target validation —
these are individually small but collectively a real frontend project.
Discipline: ship Phase 4 as a minimum viable killer UI (selection, mode,
export, splice) and polish in v1.1.

**R4 — Cross-song splicing has multi-tempo edge cases that synth fixtures
won't catch.** Splicing song1 (120 BPM) into song2 (140 BPM) requires the
projector to handle native tempo per splice source. EP-133's
`time_mode: bpm` per pad supports this; needs validation. **Per Decision 11,
splice tests use the canonical Definition / Ooh La La / Believer fixtures
(or extensions thereof), not synth.** This is the hardening's Stream E
lesson applied; ignoring it has a documented track record of letting
sub-percent tempo bias hide for a week.

**R5 — Multi-song UI deferred to v2 means v1 needs an awkward "single-song
mode" mental model.** The configurator strip's "Song: ●1" tab with no
ability to add a second song is a UX paper-cut. Accept it for v1; v2
removes it.

**R6 — Tempo-pipeline static sentinels (SE-3/4/5) catch call-site changes,
not behavior changes.** The hardening pass shipped `test_split_path_invokes_refine_bpm`,
`test_re_anchor_path_invokes_refine_bpm`, and
`test_re_anchor_auto_reslices_curated` as static greps because the synth
fixture's hi-hat density makes beat-this report half-time on the full
pipeline. Combined with SE-2's direct `refine_bpm` correctness coverage,
this is functionally equivalent — but only if both stay in sync. **If
configurator work modifies `refine_bpm`'s signature or call sites, both
the sentinels and SE-2 need parallel updates.** Per `HARDENING_VERIFICATION.md`
§4.2.

**R7 — `verify-load` doesn't catch LOM-binding errors.** The hardening pass
wired `verify-load` against `v0/build/StemForge.amxd` via the
`_extract_maxpat_from_amxd()` adaptation (GH issue #61, resolved). It
catches patcher-graph errors (the actual target of pitfall #24) but
LOM-touching JS modules throw at load time without the LiveAPI host —
errors come back as `js_no_function`/`missing_object`. **Configurator's
M4L device work is heavy on LOM bindings; don't expect verify-load to
be the only safety net.** Layered coverage required: structural
verifiers + verify-load + Tier-3 mock tests + Tier-4 live integration.
Per `HARDENING_VERIFICATION.md` §4.3.

**R8 — Slot-claim algorithm in COMMIT is now a load-bearing contract.**
Phase 2.5's COMMIT dedup-by-file_path + claim-next-free-slot-in-0..19
became the seed for the slot table (per Decision 14). Existing fixtures
record specific slot assignments produced by this algorithm. **Any future
change to slot-claim logic must be tested against existing fixtures'
assignments to confirm it doesn't reorder slots silently.** Particular
care needed when Phase 3 wires `audio_hash` population at COMMIT time —
switching the dedup key from file_path to audio_hash *should* produce
identical results in normal cases, but edge cases (same path but
different content, or same content but different paths) need explicit
testing. Add at least one fixture that exercises each edge case.

## What success looks like

After v1 ships, the user can:
- Forge a song, open the configurator, slice scenes manually from
  arrangement view, configure pad modes, and export to EP-133, Koala,
  or Chompi from the same project.
- Re-anchor a downbeat in arrangement view and have curation re-run
  automatically.
- Define cross-song splice scenes (mashups) in the data model and UI.
- Drive the device headlessly via `sf_remote fire forge` /
  `sf_remote fire commit` for skill-level automation.
- Drop locators in arrangement view and have them sync into scene
  definitions in the configurator.

After v2 ships, the user can additionally:
- Manage multi-song projects with per-song UI scoping.
- Have the configurator write locators back into arrangement view.
- Use recent-clip enumeration in `skill.bounce-to-clip-and-collect`.
- Use `commit-with-bounce` for post-processing-pipeline-aware bouncing.

## Out of scope, full stop

These won't ship as part of the configurator regardless of timeline:

- Modifying or replacing the existing forge pipeline (it works; leave it).
- Curation algorithm changes (orthogonal subsystem).
- DSP effect chains within the configurator (post-processing is a v2
  concern; v1 configurator just records what mode each pad is in).
- Plugin extraction (`vst-extraction` skill) — orthogonal cleanup.
- Live performance features beyond hardware export (the configurator is
  for *preparing* hardware projects, not for performing live).
