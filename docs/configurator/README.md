# StemForge Configurator

Design docs and execution plans for the configurator subsystem — a target-agnostic abstract scene model + 2D editor UI for building hardware-sampler projects.

## Status (as of v0.2.0)

- **Phase 1** ✅ shipped — `stemforge/scene_model/`, `AbstractProjector`, EP-133 projector with byte-identity gate, `re-anchor --then-curate`.
- **Phase 2** ✅ shipped — full `Project → Song → SceneSpec → GroupSpec → PadSpec` schema, `Ep133Projector.project_from_spec`, `export-song --write-spec`, `{schema_version: 2, songs: []}` reader.
- **Phase 2.5** ✅ shipped — COMMIT walks arrangement view too (was session-only); `session_tracks` is a slot table, not a view dump.
- **Phase 3** — not started. M4L device + HTTP server + popup shell.
- **Phase 4** — not started. Editor UI (scene strip, pad canvas, inspector, slicer).
- **Phase 5** — not started. Locator sync + skill bindings.

The breaks-n-beats1 `.ppak` shipped in v0.2.0 hardware-validates the EP-133 pipeline end-to-end via the CLI path (`deck-from-manifest` + `build-deck`). The configurator adds a UI on top of this proven foundation.

## Files in this directory

| File | What it is |
|---|---|
| [`STEMFORGE_CONFIGURATOR_SPEC_v4.md`](STEMFORGE_CONFIGURATOR_SPEC_v4.md) | **Active spec.** Goal, scope, load-bearing decisions (1–16), 5-phase plan, risks. |
| [`STEMFORGE_TOP3_WORKFLOWS.md`](STEMFORGE_TOP3_WORKFLOWS.md) | The three target use cases the configurator enables. **Priority has shifted to Workflow #3a (verse-swap deck)** — see the next file. |
| [`VERSE_SWAP_DECK_PLAN.md`](VERSE_SWAP_DECK_PLAN.md) | Execution plan for the verse-swap workflow — the minimum surface that ships first. Decision 16 (per-group sample rate) is the key new capability. |
| [`PHASE_3_FRESH_SESSION_HANDOFF.md`](PHASE_3_FRESH_SESSION_HANDOFF.md) | Paste-this-at-fresh-session brief. Required reading order, what changed in the last session, the 3 design calls that gate Phase 3 start. |
| [`archive/`](archive/) | Superseded specs: v2, v3. |
| [`research/`](research/) | Background research bundles (export configurator design + testability + prior art + UX inventory). |

## Where to start

If you're picking up configurator work for the first time:

1. Read [`STEMFORGE_CONFIGURATOR_SPEC_v4.md`](STEMFORGE_CONFIGURATOR_SPEC_v4.md) §Goal and §Scope.
2. Read [`STEMFORGE_TOP3_WORKFLOWS.md`](STEMFORGE_TOP3_WORKFLOWS.md) to ground the design in real use cases.
3. Read [`PHASE_3_FRESH_SESSION_HANDOFF.md`](PHASE_3_FRESH_SESSION_HANDOFF.md) for the current entry point — it documents the 3 design calls that gate writing any code.
4. If specifically working the verse-swap deck: also read [`VERSE_SWAP_DECK_PLAN.md`](VERSE_SWAP_DECK_PLAN.md) — it has the realistic memory budget math and the slice-by-slice execution plan.

## Foundation

The configurator builds on the [hardening spec](../STEMFORGE_HARDENING_SPEC.md) which closed 2026-05-08 (verification: [`../HARDENING_VERIFICATION.md`](../HARDENING_VERIFICATION.md)). Phase 1 was unblocked the moment hardening's acceptance gate met. Phases 1–2.5 are in main.
