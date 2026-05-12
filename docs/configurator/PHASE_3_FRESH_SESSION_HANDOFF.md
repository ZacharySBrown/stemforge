# Fresh Session Handoff — Configurator Phase 3

Paste this verbatim at the start of a fresh Claude Code session.

---

````
Picking up StemForge configurator work. Hardening complete; Phase 1 + 2 +
2.5 complete (commits on `feat/hardening-hw3-hw4-finish`, then merged).
Resuming with Phase 3.

## Read first, in order

1. `docs/configurator/STEMFORGE_CONFIGURATOR_SPEC_v4.md` — active spec. **v4 is current**;
   v3 is superseded (archived under `docs/configurator/archive/`). The
   "Changes since v3" block at the top calls out Decision 16 (per-group
   sample format) which is NEW since the last session and is load-bearing
   for the priority workflow.
2. `docs/configurator/STEMFORGE_TOP3_WORKFLOWS.md` — the three target use cases the
   configurator is being built to enable. Read carefully; the priority
   workflow has shifted.
3. `docs/STEMFORGE_HARDENING_SPEC.md` + `docs/HARDENING_VERIFICATION.md` —
   foundation. Read R6 + R7 in the verification's §4 explicitly; both
   apply during Phase 3 work.

## What changed in the previous session

- **Phase 2 complete:** abstract scene model in `stemforge/scene_model/`,
  EP-133 projector refactored, byte-identity gate green, JS arrangement
  reader emits `{schema_version: 2, songs: []}` shape.
- **Phase 2.5 emerged:** COMMIT was walking session view only, so
  arrangement-only edits were invisible. Fixed by walking both views,
  dedup by file_path, slot-claim 0..19. Architectural insight:
  `session_tracks` is a slot table, not a view dump.
- **Spec went v3 → v4:** Decision 16 (per-group sample format) was added
  to support the hip-hop verse-swap workflow. Without it, 24 verses
  won't fit in EP-133's 64 MB memory at uniform stereo 48 kHz.

## Priority shift — read this carefully

The previous session had Workflow #1 (EP-133 + Chompi MIDI-synced)
ranked highest. **The priority is now a fourth workflow not in the doc:**

**Workflow #3a — hip-hop verse-swap deck.** EP-133 only. Single scene,
four groups: A = primary verses (12 vocal pads), B = alt verses + hooks
(12 pads), C = drum corpus (12 pads), D = texture/IDM (12 pads).
Performance gesture: trigger a verse on Group A, swap drum breaks from
Group C underneath the same vocal mid-verse.

**Why this is the new priority:**
- It's the closest "real workflow you can ship" given current hardware.
- It's EP-133 only — skips the Chompi projector dependency.
- It's single-scene Workflow B — skips splice editor and scene
  structure work.
- It's the workflow the user is most excited about.

**What it specifically requires from configurator work** (per
`STEMFORGE_TOP3_WORKFLOWS.md` and the v4 spec):
- All of Phase 3 EXCEPT projectors 3.5–3.6 (Koala, Chompi). EP-133 only.
- Phase 4.1–4.5 (scene strip, pad canvas, inspector, validation, audio
  preview) plus 4.6 (slicer mini-UI).
- SKIP Phase 4.7 (splice editor) and 4.8 (multi-target export).
- **Decision 16 (per-group sample format)** must land — vocal verses at
  mono 24 kHz are what makes the memory math work.

That's roughly 60% of v1's full surface, ordered for fastest time-to-
performance.

## Phase 3 starting point

Per the v4 spec §Plan, Phase 3 is:
1. Local Python HTTP server (`tools/m4l_configurator_server.py`)
2. New `m4l-devices` repo with strip device
3. Popup shell via `[jweb]` pointing at `localhost:<port>`
4. (Skipped for now) port Koala + Chompi exporters

**Three design calls before code starts:**

a. **Frontend stack.** SolidJS leading per spec; React acceptable.
   Decide based on what you can iterate fast in. Not load-bearing for
   the architecture — both work.

b. **HTTP server API shape.** Per Decision 15, server is an
   intent-receiver (not a thin file-writing proxy). Endpoints should be
   intent-shaped (`POST /intent/commit`, `POST /intent/assign-pad`)
   rather than CRUD. Worth ~30 min of design before code.

c. **Where audio_hash population lives.** Per Phase 2 loose-end #1,
   `audio_hash` is empty string at COMMIT time today. Phase 3 should
   wire hash population somewhere — likely the Python server when it
   ingests COMMIT output, but could also be JS-side. Affects
   reconciliation logic (Decision 14 says implicit slot-claim is the
   seed; explicit user assignment overrides). Worth deciding before
   code touches the slot-table reconciliation path.

## Forge work in parallel (does not block configurator)

The user is forging 5 more hip-hop tracks to bring the verse-swap
deck to 12 songs total. **This work is independent of Phase 3 and runs
in parallel.** Configurator doesn't need to know about it; just be
aware that the manifest pool will expand during Phase 3 and the popup
should handle a project that references manifests added after project
creation gracefully.

## Discipline holds from prior phases

- Per-PR scope, not big-bang commits.
- §15 must-keep-green path-IDs from v4 stay green through all Phase 3
  work. The Phase 1 byte-identity gate (`test_song_export_parity`)
  stays green throughout.
- R6 sentinel triple isolation: configurator work shouldn't touch
  `cli.py`'s `refine_bpm` call sites. If it does, run the sentinels
  explicitly per commit.
- R7 verify-load layered coverage: any new LOM-binding JS in the strip
  device needs Tier-3 mock tests; verify-load won't catch its bugs.
- Honesty discipline from prior bundles: surface drift between spec
  and reality rather than rationalizing.

## What I do NOT want

- Don't start Phase 4 work in parallel with Phase 3. Sequence them.
- Don't port Koala or Chompi projectors yet — both are deferred until
  after the verse-swap deck ships.
- Don't add scene structure or splice editor UI to Phase 4 — single-
  scene Workflow B is the priority surface.
- Don't redesign the spec without flagging it. v4 is the active doc.

## Immediate next step

Make the three design calls (a–c above), document them as a short PR
or `docs/phase3-decisions.md` note, then start Phase 3.1 (HTTP server
skeleton). The user is around for design discussion if any of the
three calls need a back-and-forth.
````

---

After Phase 3 lands cleanly, the next prompt covers the Phase 4 minimum
viable surface (pad canvas + inspector + slicer + audio preview +
Decision 16 implementation). Phase 4.7 (splice editor) and 4.8 (multi-
target export) get their own prompts later as separate workflows
require them.
