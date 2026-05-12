# StemForge Configurator Spec

**Status:** active. Hardening pass complete as of 2026-05-08
(`HARDENING_VERIFICATION.md`). Configurator work is unblocked.
**Companions:** `STEMFORGE_HARDENING_SPEC.md` (foundation),
`HARDENING_VERIFICATION.md` (acceptance + lessons),
`EXPORT_CONFIGURATOR_PLAN_v4.md` (archived reasoning),
four input bundles (design, testability, prior-art, UX inventory).

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

### Decision 9: scenes are first-class objects, not locator markers

Today, locators in arrangement view double as scene boundaries. The user
flagged this as "gross." In the configurator:

- Locators stay for downbeat anchoring (their original technical purpose).
- Scenes are defined by the user via a slicer UI (creative selection
  by bar range, optionally non-contiguous via splicing).
- A scene's `provenance` field records whether it was auto-curated, manual,
  or splice-defined.

The slicer is the manual-curation UX. Auto-curation is a separate path
that produces ungrouped clip kits; manual curation produces named scenes
with structure.

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
