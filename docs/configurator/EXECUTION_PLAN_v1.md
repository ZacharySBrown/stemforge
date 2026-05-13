# Execution Plan — Configurator v1.0

> Companion to `specs/CONSOLIDATED_DESIGN.md`. The spec describes the
> destination; this document describes the path. Optimized for **maximum
> parallelism**, **maximum autonomous execution**, and **maximum headless
> testing** including Live-in-the-loop where unavoidable.

---

## Top-level shape

```
Phase 0:  Foundation  (sequential, ALL OTHER PHASES BLOCKED)
  └── Pydantic schemas, TS-gen, max-stub.js, lom_snapshots fixtures, CI

Phase 1:  Parallel migrations  (4 worktree agents simultaneously)
  ├── Lane 1A: CLI file-shape migration
  ├── Lane 1B: Server curation CRUD endpoints
  ├── Lane 1C: Device picker + sniffer + LOAD-curation
  └── Lane 1D: Popup UI restructure

Phase 2:  COMMIT keystone  (sequential — depends on 1B + 1C)
  └── End-to-end COMMIT + integration test (no Live needed)

Phase 3:  Features  (3 worktree agents simultaneously)
  ├── Lane 3A: Templates (.adg per-group)
  ├── Lane 3B: BOUNCE refactor
  └── Lane 3C: EXPORT via server

Phase 4:  Polish  (2 worktree agents simultaneously)
  ├── Lane 4A: Active-curation persistence
  └── Lane 4B: Stale detection + strip deletion

Phase 5:  Live-in-the-loop smoke suite  (sequential)
  └── AppleScript harness + fixture .als + recorded LOM snapshots
```

**Estimated agent-runs**: 15. **Estimated PRs**: 22 (one per agent + the bookkeeping PRs in between).

## The four testing layers

Per spec §7. Every PR must contribute to one or more of these:

| Layer | Surface | Speed | What it catches |
|---|---|---|---|
| **L1 unit** | pytest + vitest with no I/O | <1s per test | logic bugs |
| **L2 integration (filesystem-only)** | pytest with pyfakefs, msw, fixture trees | <5s per test | wiring bugs, schema bugs |
| **L3 device-JS via `max-stub.js` + `lom_snapshots`** | Node + stubbed Max globals + JSON-replayed LOM | <2s per test | LOM-walking + LOAD/COMMIT logic — **the historical pain killer** |
| **L4 Live-in-the-loop smoke** | AppleScript-driven real Live + sf-remote assertions | 10-60s per test | wiring against real Max + LOM quirks |

L1–L3 run on every PR. L4 runs gated on release / manually.

## Phase 0 — Foundation

**Goal**: lock down the contracts and build the test harness BEFORE any feature work. Every subsequent phase depends on this.

This phase ships as **one PR** because the artifacts are tightly coupled.

### Deliverables

1. **Pydantic schemas** at `stemforge/configurator/schemas/`:
   - `Curation` (curation file)
   - `Pad`, `Group`, `Target`, `PadSource`, `ClipSettings`, `LastBounce`, `LastExport`
   - `ForgeManifest` (auto-curation shape from spec §2.2)
   - `ArrangementManifest` (arrangement-chunks shape from spec §2.2)
   - `StemforgeState` (`.stemforge_state.json` from spec §2.4)
   - All with `schema_version`/`curation_version` + frozen `model_config`
2. **TS type generator** — `scripts/gen_typescript_types.py` that uses `datamodel-code-generator` (or hand-rolled JSON schema → TS) to write `web/configurator/src/lib/api-types.generated.ts`. Plus a CI step that diffs the regenerated output and fails if drifted.
3. **`max-stub.js`** at `tools/test-harness/max-stub.js`:
   - Stubs `Dict`, `LiveAPI`, `outlet`, `messnamed`, `post`, `arrayfromargs`, `Folder`, `File` (the minimum API surface the device JS touches today).
   - Programmable: tests configure return values per LOM path.
   - Records outlet emissions for assertion.
   - Pre-seeds `lom_snapshot` JSON files (replay mode).
4. **`lom_snapshots/`** library at `tests/fixtures/lom_snapshots/`:
   - 5 starter snapshots: `empty-set.json`, `forge-loaded.json`, `staging-empty.json`, `staging-4-pads-stg-a.json`, `staging-full-46-pads.json`.
   - Each is a JSON dump of LOM state at a specific moment (track list, clip slots, clip properties).
   - Documented capture procedure (one-time, from real Live, via `sf-remote dump` plus a small capture script).
5. **Fixture forges + curations** at `tests/fixtures/forges/` + `tests/fixtures/curations/`:
   - 2 forge dirs with synthetic 1-second WAVs + valid manifests (auto-curation + arrangement).
   - 4 curations: empty, partial, bounced, stale-reference.
6. **CI workflows** at `.github/workflows/`:
   - `ci-server.yml` — Python pytest + mypy + ruff
   - `ci-popup.yml` — vitest + tsc + eslint
   - `ci-cli.yml` — CliRunner tests
   - `ci-device-js.yml` — Node vitest on device JS with max-stub
   - `ci-types.yml` — Pydantic → TS regen + diff
   - `ci-integration.yml` — pytest covering server ↔ CLI ↔ filesystem
   - (`ci-smoke-live.yml` stub for Phase 5, not active yet)
7. **Self-test of foundation**: 10+ tests proving every layer of harness actually works (mock LiveAPI returns the seeded path, stubbed Dict round-trips, schema parsing rejects malformed input, TS regen produces stable output).

### Acceptance gates

- All 7 CI workflows pass green.
- `tests/fixtures/lom_snapshots/empty-set.json` loaded through `max-stub.js`, then `new LiveAPI("live_set").getcount("tracks")` returns the seeded value.
- TS regeneration produces no diff against the committed file.
- `Curation(**fixture).model_dump()` round-trips.

---

## Phase 1 — Parallel migrations (4 lanes)

After Phase 0 lands, spawn 4 worktree-isolated agents in parallel. Each operates in disjoint file scope.

### Lane 1A — CLI file-shape migration

**Scope**: `stemforge/cli.py`, `stemforge/curator/*`, `stemforge/forge/*` — the Python source-pipeline side.

**Inputs**: Phase 0 schemas.

**Deliverables**:
- `stemforge migrate-forge <slug>` command: takes an existing `~/stemforge/processed/<slug>/curated/manifest.json`, rewrites it as `auto_curation_manifest.json` with `schema_version: 1` and `manifest_hash`; extracts arrangement data into separate `arrangement_manifest.json`.
- Both forge-writing code paths (`stemforge forge`, `stemforge curate-bars`, `stemforge re-anchor`, etc.) emit the new file shape.
- `stemforge re-curate <slug>` new subcommand: re-runs auto-curation only (without re-running stem separation).
- Compatibility shim in CLI to read both old and new shapes for one release.
- Pydantic-validated reads of forge manifests.

**Self-verification**: pytest CliRunner tests cover round-trip + migration of fixture forges.

**PR scope**: ~600 lines. Title: `migrate(cli): forge file shape — split auto_curation + arrangement manifests`.

### Lane 1B — Server curation CRUD

**Scope**: `stemforge/configurator/{server,intents,state}.py` — replace the old ProjectSpec model with the new Curation model. Add the new endpoints from spec §4.3.

**Inputs**: Phase 0 schemas + fixture curations.

**Deliverables**:
- `GET /curations` — scan `~/stemforge/curations/` directory.
- `POST /curations` — create empty curation with target/groups.
- `GET /curations/{name}` — return single curation.
- `POST /curations/{name}/open` — set active (server-state mutation only at this phase; UDP-to-device wiring comes Phase 2).
- `POST /curations/{name}/save-as` — file copy + active-switch.
- `DELETE /curations/{name}`.
- `PATCH /curations/{name}/template` — write template assignment.
- `PATCH /curations/{name}/target`.
- `POST /curations/{name}/commit` — accepts a device snapshot, validates, writes file atomically. **Server-side write path used by Phase 2's device walker.**
- Atomic write helper: write `.tmp` + `rename`.
- File-system lock for concurrent writers (simple flock).
- SSE `state` event on every mutation.
- Server-side `.stemforge_state.json` reader/writer (full impl deferred to Phase 4, but the file's existence is wired here so Phase 1A/C don't have to add their own state file).

**Self-verification**:
- Round-trip tests for every endpoint via FastAPI TestClient + pyfakefs.
- Concurrent-write test (two simultaneous commits to same curation).
- SSE broadcast test (subscribe, mutate, assert event arrives).

**PR scope**: ~1500 lines. Title: `feat(server): curation CRUD endpoints + atomic write path`.

### Lane 1C — Device picker + sniffer + LOAD-curation

**Scope**: `v0/src/m4l-js/stemforge_loader.v0.js` + builder.

**Inputs**: Phase 0 max-stub.js + lom_snapshots + schemas (TS types).

**Deliverables**:
- New `pickSource()` JS function — opens `[opendialog]`, sniffs the picked file's type (audio / forge_manifest / arrangement_manifest / curation), stores result in JS state.
- Primary-button label switcher: `FORGE` / `LOAD FORGE` / `LOAD CURATION` based on picker state.
- `loadCuration(yamlText)` JS function — parses curation YAML, creates `STG-A`..`STG-N` tracks per target (delete any pre-existing `STG-*` first), populates each pad slot via `loadClip()`, applies `clip_settings` (warp BPM, loop region).
- Device patcher: replace the PRESET dropdown, SOURCE dropdown, and the LOAD/ANCH split-row with the new single `[Pick source…]` element and rearranged primary button.
- Status text emits structured stages for L3 testability: `"sniffer: detected curation v1"`, `"staging: created STG-A through STG-D"`, `"staging: populated A·01 (vocal-bar4-8)"`, etc.

**Self-verification**:
- L3 device-JS tests via max-stub + lom_snapshots:
  - Sniffer: given each fixture file type, returns correct routed type.
  - loadCuration: given a fixture curation YAML and `empty-set` lom_snapshot, produces the expected sequence of LiveAPI calls.
  - Track-rename / deletion idempotence: loading curation twice produces same final state.

**PR scope**: ~1200 lines. Title: `feat(device): unified picker + LOAD-curation via staging tracks`.

### Lane 1D — Popup UI restructure

**Scope**: `web/configurator/src/` — replace the current LeftRail-centric layout with the three-panel layout from spec §3.2.

**Inputs**: Phase 0 TS types + msw mocked server.

**Deliverables**:
- New panels: `ForgeList` (left rail), `ActiveCuration` (center), `CurationList` (right rail).
- Top bar: active curation name + target chip + Save / Save-as / Close + connection.
- Forge list panel: scan-driven, per-entry actions (Load/Unload/Re-anchor/Re-curate/Show in Finder).
- Active curation panel: read-only grid view of pads, per-group template selector, label edit field, bounce/export status.
- Curation list panel: per-entry Open / Duplicate / Rename / Delete.
- All actions wire to the new server endpoints from Lane 1B.
- Remove the old `LeftRail.tsx`'s drag-and-drop curation UI (kept only for the curation panel skeleton — content is replaced).
- Stale-reference badge component (renders when curation's `referenced_forges.manifest_hash` ≠ current forge's hash).
- "Pop out" button in TopBar that calls `window.open(location.href, "stemforge", "popup,width=1200,height=800")` for the macOS+Chrome new-window-resistant workaround (spec §6.8).

**Self-verification**:
- vitest + React Testing Library for each panel against msw-mocked server.
- Snapshot tests for each panel's empty / populated / stale states.

**PR scope**: ~2000 lines. Title: `feat(popup): three-panel restructure — forges / curation / curations`.

### Phase 1 merge order

1. Lane 1A first (CLI file shapes — everyone else's fixtures may depend).
2. Lane 1B + 1C + 1D in any order (independent file scopes).

---

## Phase 2 — COMMIT keystone (sequential)

**Goal**: per spec §11, this is "the keystone fix. Once this works, the architecture's promise holds." Built sequentially because it integrates Phase 1B + 1C end-to-end.

This phase ships as **one PR**, possibly with helper PRs along the way.

### Deliverables

1. Device JS `commit()` function rewritten:
   - Walks `STG-*` tracks (count from active curation's `target.groups`).
   - For each clip slot, snapshots clip state into the Pad shape from spec §2.3.
   - Sends UDP `commit <serialized-snapshot>` to server.
2. Server `POST /curations/{name}/commit` handler:
   - Receives device snapshot.
   - Resolves `(forge_slug, clip_id)` for each pad's audio path (reverse-lookup against forge manifests).
   - Writes curation file atomically.
   - Broadcasts SSE.
3. UDP receiver added to device's `[udpreceive 7420]` route table.
4. End-to-end L3 integration test:
   - Fixture: `lom_snapshots/staging-4-pads-stg-a.json`.
   - Stub device → fixture filesystem → assert curation file content matches expected.
   - **This test is the architecture's correctness check. Block merge on it.**
5. The legacy `commitOffsets()` Dict-only path is removed.

### Self-verification

- L3 tests for the walker against multiple LOM-snapshot fixtures (empty, partial, full).
- L2 tests for the server handler against fixture snapshots.
- Integration test that runs the walker + handler end-to-end and verifies file contents.

### PR scope

~800 lines. Title: `feat: COMMIT end-to-end — device walker → server write path`.

---

## Phase 3 — Features (3 lanes parallel)

After Phase 2 lands, spawn 3 worktree agents.

### Lane 3A — Templates (.adg per-group)

**Scope**: server, device JS, popup (template selector wiring).

**Deliverables**:
- Server endpoint: `GET /templates` scans `~/stemforge/templates/*.adg`.
- Server endpoint: `PATCH /curations/{name}/template` writes assignment + fires UDP to device.
- Device JS handles `template-changed <group> <template-name>` UDP message:
  - Loads `<template-name>.adg` onto the `STG-<group>` track via `LiveAPI("live_set tracks N device 0").call("apply_param")` or whatever the LOM verb is for loading a rack onto a track.
- Popup template selector dropdown wired to the PATCH endpoint.
- L3 tests for the device JS template-load handler.
- L2 tests for the server endpoint.

**PR scope**: ~600 lines.

### Lane 3B — BOUNCE refactor

**Scope**: device JS bounce, server-side bounce-spec construction, integration tests.

**Deliverables**:
- Device JS `bounce()` reads from active curation's `curated_layout` (not from walking A/B/C/D directly).
- For each pad with `source`: solo group track, trigger clip, freeze-and-crop via existing helpers, write WAV to `~/stemforge/bounced/<curation-name>/<pad-id>.wav`.
- Update curation's `last_bounce` block via server.
- Server endpoint: `POST /curations/{name}/trigger-bounce` fires UDP at device.
- L3 tests for the bounce-spec construction (which slots, in which order, with which templates baked).
- The actual WAV rendering still requires Live (deferred to Phase 5 smoke); but the CONTROL of the bounce is testable.

**PR scope**: ~700 lines.

### Lane 3C — EXPORT via server

**Scope**: server endpoint, CLI wiring.

**Deliverables**:
- Server endpoint `POST /curations/{name}/export` body `{out_path, target_format}`.
- Server runs `stemforge export <curation-name> --target ep133 --out <path>` subprocess.
- Server updates `last_export` block.
- Popup "Export to .ppak…" button uses osascript save-dialog (existing pattern from PR #99 era) to pick the out_path, then fires the endpoint.
- L2 tests for the server-side wiring (mocked subprocess).

**PR scope**: ~400 lines.

---

## Phase 4 — Polish (2 lanes parallel)

### Lane 4A — Active-curation persistence

**Scope**: server `.stemforge_state.json` read/write, device sends current `.als` path on boot.

**Deliverables**:
- Server reads `.stemforge_state.json` at startup; writes on every active-curation change.
- Device JS sends `als-opened <path>` UDP on `loadbang`.
- Server responds with `set-active-curation <name>` if it knows one for that `.als`.
- L2 tests for the state file round-trip.
- L3 tests for the device-side bootstrap message.

**PR scope**: ~350 lines.

### Lane 4B — Stale detection + strip deletion

**Scope**: server stale-check, popup stale badge, delete strip device.

**Deliverables**:
- Server computes `referenced_forges[i].manifest_hash` vs current forge's `manifest_hash` at every state broadcast.
- Marks pads as stale in the broadcast.
- Popup renders stale badge.
- Popup `Refresh from forge` button → server endpoint that re-derives pad refs.
- **Delete** `v0/src/m4l-devices/configurator-strip/` and `v0/build/ConfiguratorStrip.amxd`.
- Move "Open Editor" button into `StemForge.amxd`'s footer (the spec's §3.1 layout).
- Close PR #99 with a comment pointing at this PR.

**PR scope**: ~600 lines.

---

## Phase 5 — Live-in-the-loop smoke suite (sequential)

**Goal**: build the L4 layer so we can verify Phase 1–4 actually works on real Live without manual clicking.

### Deliverables

1. `tools/test-harness/live-runner.sh`:
   - Uses AppleScript to open Live + load a fixture `.als`.
   - Waits for the device's `[udpreceive]` to come up (heartbeat).
   - Runs a series of `sf-remote fire ...` commands against the live device.
   - Captures `sf-remote dump` state at each checkpoint.
   - Asserts captured state matches expected.
   - Reports pass/fail.
2. Fixture `.als` files at `tests/fixtures/als/`:
   - `empty-staging.als` — fresh template, just the strip + device.
   - `loaded-forge-stg-empty.als` — a forge loaded, no staging populated.
   - `curation-active-stg-populated.als` — active curation, staging populated.
3. **5–10 smoke tests** scripted via the runner:
   - Smoke 1: open empty .als → device boots → `sf-remote dump` shows no active curation.
   - Smoke 2: load fixture forge → assert FORGE/* tracks created with correct clip count.
   - Smoke 3: create curation → assert staging tracks created with correct count for target.
   - Smoke 4: COMMIT → assert curation file written with correct content.
   - Smoke 5: load curation from disk → assert staging populated correctly.
   - Smoke 6: switch active curation → assert staging repopulated.
   - Smoke 7: re-anchor → assert forge manifests updated + tracks reloaded.
   - Smoke 8: bounce → assert bounce dir populated with correct # of WAVs.
   - Smoke 9: export → assert `.ppak` produced.
   - Smoke 10: stale detection → mutate forge, assert popup state shows stale.
4. `.github/workflows/ci-smoke-live.yml`:
   - Triggered manually (`workflow_dispatch`).
   - Runs on a self-hosted runner with Live + StemForge installed.
   - Executes `live-runner.sh`.
   - Reports per-test pass/fail.
5. README at `tests/fixtures/als/README.md`:
   - How to record new `.als` fixtures.
   - How to capture LOM snapshots for L3 tests.

**PR scope**: ~1500 lines (mostly the runner script + smoke test definitions; fixtures are binary).

---

## Per-phase parallelism plan (for agent dispatch)

| Phase | Sequential / Parallel | # Agents | Wait gate |
|---|---|---|---|
| 0 | sequential | 1 | — |
| 1 | parallel (4 lanes) | 4 | after Phase 0 lands |
| 2 | sequential | 1 | after Phase 1A + 1B + 1C land |
| 3 | parallel (3 lanes) | 3 | after Phase 2 lands |
| 4 | parallel (2 lanes) | 2 | after Phase 3 lands |
| 5 | sequential | 1 | after Phase 4 lands |

Total **12 parallel-or-sequential agent runs** across the whole plan (plus phase-prep coordination by the main orchestrator).

---

## Self-verification at every step

**Every agent's deliverable must include**:

1. ✅ Tests at the highest applicable layer (L1/L2/L3) — block PR merge on green.
2. ✅ Self-consistency: schemas → TS regen → no drift. CI enforces.
3. ✅ Acceptance summary in the PR description listing which tests cover which behaviors.
4. ✅ A small `INTEGRATION.md` note in the PR if the agent expects another phase to touch related code.

**No agent merges without**:
- All L1/L2/L3 CI workflows green.
- At least 5 new tests per lane (Phase 1) or 3 per lane (Phases 3-4).
- Coverage of at least one negative-control case per major code path.

**Phase-level merge gate**:
- All PRs in the phase merged.
- A 5-minute integration smoke runs end-to-end via the harness against the new code (without Live for Phases 0–4; with Live for Phase 5).

---

## What the orchestrator (main session) does

- Spawns each phase's agents with self-contained briefs.
- Verifies CI green on each PR before approving for merge.
- Maintains the cross-phase invariants:
  - Schemas are the source of truth — anyone editing them coordinates with the TS regen.
  - lom_snapshot fixtures are versioned; agents extend, never break, the existing snapshots.
  - The `Curation` Pydantic shape never silently drifts.
- Between phases: drives the merge of in-flight PRs (re-targeting, rebase conflicts).

---

## Risk register

| Risk | Mitigation |
|---|---|
| Pydantic ↔ TS drift in real time | `ci-types.yml` regenerates and diffs on every PR. |
| Phase 1 agents stepping on each other's tests | Disjoint test directories; CI enforces no cross-import. |
| Phase 2 COMMIT path needs Live to verify | L3 max-stub + lom_snapshots replays Live state; Phase 5 final verification. |
| lom_snapshots get stale as Live versions change | Versioned by Live major; capture script in Phase 0 deliverable. |
| AppleScript Live driver unreliable on different macOS | Live-runner has graceful fallback; smoke tests degrade to "skipped" rather than "failed" on environment issues. |
| Strip deletion breaks something nobody noticed | Phase 4B keeps the `Open Editor` button moved to the main device; smoke test 1 catches regression. |

---

## File-by-file ownership across phases

To prevent agent collisions, here's who owns what:

| Path | Phase / Lane owner |
|---|---|
| `stemforge/configurator/schemas/` | Phase 0 (created), Phase 1B + 3A (extend) |
| `stemforge/configurator/server.py` | Phase 1B, Phase 2, Phase 3A/B/C, Phase 4A/B |
| `stemforge/configurator/intents.py` | same |
| `stemforge/cli.py` | Phase 1A, Phase 3C |
| `v0/src/m4l-js/stemforge_loader.v0.js` | Phase 1C, Phase 2, Phase 3A/B, Phase 4A/B |
| `v0/src/m4l-js/stemforge_loader.v0.js` (deploy copy) | always mirrored |
| `web/configurator/src/lib/api-types.generated.ts` | Phase 0 (generated), regenerated on schema changes |
| `web/configurator/src/components/` | Phase 1D, Phase 3A/B/C, Phase 4B |
| `tools/test-harness/max-stub.js` | Phase 0 (created), all subsequent (extended) |
| `tests/fixtures/lom_snapshots/` | Phase 0 (seeded), all subsequent (extended) |
| `tests/fixtures/als/` | Phase 5 |
| `.github/workflows/ci-*.yml` | Phase 0 (created); Phase 5 (activates smoke) |
| `v0/src/m4l-devices/configurator-strip/` | Phase 4B (deleted) |

Phases with same-file ownership are SEQUENTIAL; phases with disjoint ownership run in PARALLEL.

---

## Phase 0 starts now

Spawning the Phase 0 worktree agent immediately after this plan commits. Phases 1+ launch on Phase 0 merge.
