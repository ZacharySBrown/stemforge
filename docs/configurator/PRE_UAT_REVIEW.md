# Pre-UAT Review — Configurator v1

> Author: Staff SWE review on 2026-05-14, against `main` at commit `3ed9cd3`,
> with the running configurator server on `127.0.0.1:8765`, popup served
> from `stemforge/configurator/static/`, and `~/stemforge/` populated with
> 35 forges, 4 fixture curations, and 2 fixture templates.

## Verdict

**SHIP-WITH-FIXES.** The architecture works end-to-end on disk; CI gates
all green; 186 configurator-Python tests, 43 popup vitest, 82 device-JS
max-stub tests all pass. **But several wires are crossed:** two popup
endpoints will 404 against the real server, the initial SSE snapshot
broadcasts the wrong shape (so the popup boots showing "no curation
active" until the user touches something), and the deployed `.amxd`
still has the pre-rebuild PRESET/SOURCE umenus instead of the spec §3.1
picker. None are unsolvable; all are remediable with disjoint, small
PRs. **Do not start UAT until at least the P0 lane lands.**

## Where the code lives (for the reader)

- Server: `/Users/zak/zacharysbrown/stemforge/stemforge/configurator/`
- Popup: `/Users/zak/zacharysbrown/stemforge/web/configurator/src/`
- Device JS: `/Users/zak/zacharysbrown/stemforge/v0/src/m4l-js/stemforge_loader.v0.js`
- Device patcher builder: `/Users/zak/zacharysbrown/stemforge/v0/src/maxpat-builder/builder.py`
- Deployed `.amxd`: `/Users/zak/zacharysbrown/stemforge/v0/build/StemForge.amxd`
- Phase 5 (open PR #113): `tools/test-harness/live_runner.py` etc. — NOT yet on main.

## P0 — must fix before UAT

### P0-1 — Popup "add forge…" button 404s

**Symptom**: The big call-to-action button in `ForgeList` (the "add
forge…" pill at the bottom of the left rail) fires
`POST /intent/pick-manifest`. The server has no such route. The button
silently fails and emits a 405 toast.

**Root cause**: `web/configurator/src/lib/api.ts:278-283` defines
`pickManifest()` against `/intent/pick-manifest`. `web/configurator/src/hooks/useIntent.ts:275`
wraps it. `web/configurator/src/components/ForgeList.tsx:272-399` calls
it from the button. Server side, `stemforge/configurator/server.py`
exposes `/intent/pick-save-path` (Phase 3C) but never registered the
sibling `/intent/pick-manifest`.

**msw covered this up**: `web/configurator/src/test/handlers.ts:60`
mocks `/intent/pick-manifest` as 200-OK, so the vitest suite passes
green despite the production route being absent.

**Fix** (server-side):
1. Add `POST /intent/pick-manifest` to `server.py` that drives an
   osascript `choose file` dialog (audio + .json + .yaml) and on a
   non-null pick fires the appropriate `/forges/{slug}/load` cascade
   (or returns the picked path for the device to consume).
2. Optionally also add `Pick source...` semantics so the popup can
   sniff the picked file's shape (sniffer mirrors the device-side
   `pickSource()` JS in §2.7 of the spec).

**Estimated**: ~120 lines server + 1 small test. ~30 min.

**Lane**: server.

### P0-2 — `closeActiveCuration` 422s on empty body

**Symptom**: TopBar's "Close" button POSTs `/curations/active/close`
with `body: "{}"`. Server's `CloseActiveCurationBody` declares
`als_path: str` (required). Body 422s. User-visible: close button does
nothing.

**Root cause**: `web/configurator/src/lib/api.ts:270-275` sends `{}`.
`stemforge/configurator/intents.py:480-484` requires `als_path`.

**Fix**: Mirror the openCuration patch — send
`{als_path: "__popup__"}` from the popup. OR make `als_path` optional
server-side with a documented `__popup__` default and propagate the
sentinel to a single helper. Pick the **server-side fix** — same fix
applies to `OpenCurationBody`, `CloseActiveCurationBody`, and any
future als-path-keyed body; do it once.

**Estimated**: ~60 lines + 2 tests. ~30 min.

**Lane**: server + popup (delete the patch once server accepts empty).

### P0-3 — Initial SSE snapshot is the wrong shape

**Symptom**: When the popup boots (or reloads, or auto-reconnects), it
receives the initial SSE state event. Today that event is the **legacy
`Project` shape** — `{schema_version: 2, project_id: "", name: "",
songs: []}` — which has neither `kind: "curations"` nor a `curation`
key. The popup's `handleStateEvent` falls into the legacy branch with
`payload.curation = undefined`, sets `curation: null`, and the popup
shows "no curation active" even if `.stemforge_state.json` has
`__popup__: bounced` set.

After the user triggers any mutation, the server broadcasts the new
`kind: "curations"` shape and the popup recovers — but the cold-boot
state is always wrong.

**Root cause**: `stemforge/configurator/server.py:432-437` (the
`/state/stream` snapshot) emits `state.project.model_dump_json()` (the
old `Project` model) as the initial event. The Phase 4B broadcaster
uses `broadcast_curations_state()` but only on mutation.

**Fix**: At subscriber-attach time in `stream_state`, send a
`kind: "curations"` snapshot via the same code path as
`broadcast_curations_state` (factor out a `current_curations_state()`
helper that returns the payload dict; `/state/stream` and the
broadcaster both consume it). This will make initial-paint instant.

**Estimated**: ~80 lines + 2 tests. ~45 min.

**Lane**: server.

### P0-4 — Demo-time popup patches are uncommitted

**Symptom**: Working tree has uncommitted edits to
`web/configurator/src/lib/api.ts` (openCuration → sentinel body) and
`web/configurator/src/hooks/useProjectState.ts` (handle
`kind: "curations"` SSE shape). The deployed
`stemforge/configurator/static/` bundle already reflects these patches
(built off the uncommitted source).

**Root cause**: Demo session left the patches in-place; not committed.

**Fix**: Commit the `useProjectState` patch (this is the right
client-side handler for the new SSE shape). The api.ts openCuration
patch can be **reverted** once P0-2 lands (server accepts empty body)
so it's a no-op there. Net: 1 commit for `useProjectState`, 1 commit
reverting api.ts.

**Estimated**: trivial. ~15 min.

**Lane**: popup.

### P0-5 — Deployed StemForge.amxd is the OLD patcher

**Symptom**: The on-device user-visible UI still has the
`sf_preset_menu` umenu ("Pick preset...") and `sf_source_menu` umenu
("Pick source..."). Both are pre-rebuild. Spec §3.1 requires ONE
picker button ("Pick source...") that opens `[opendialog]`, NOT a
umenu. No COMMIT/BOUNCE/RE-ANCHOR/FORGE buttons are visible (still
hidden behind legacy verb routes `preset_click`/`source_click`/
`forge_click`/`commit_click`).

The new `pickSource()` + `applyPickedSource()` JS contract shipped in
Phase 1C is unreachable from the deployed patcher.

**Root cause**: Phase 1C explicitly deferred the patcher visual lift
("Deliverables: ...Device patcher: replace the PRESET dropdown, SOURCE
dropdown, and the LOAD/ANCH split-row with the new single
`[Pick source…]` element"). The agent shipped only the JS contract,
not the new patcher. Phase 4B promised to "lift Open Editor button
into footer" and did so, but did not return to the picker lift.

**Fix**: Two paths, pick one:
- (A) **Defer**: confirm on-device UAT focuses on JS-contract paths
  reachable from the existing buttons (COMMIT/BOUNCE behind their
  legacy routes still works because the JS `commit()`/`bounce()`
  functions exist). UAT runs on the OLD patcher; Phase 1C visual lift
  becomes a follow-up.
- (B) **Fix now**: rewrite `v0/src/maxpat-builder/builder.py` per spec
  §3.1, rebuild `StemForge.amxd`, redeploy. ~3 hours.

Recommended: **(A) for this UAT round**. The picker visual lift is
high-risk to ship hot — flag as a documented UAT scope limit ("UI
buttons match pre-rebuild; new JS contract reachable via popup
operations").

**Estimated**: 0 lines (defer) OR ~600 lines (fix now).

**Lane**: device (if doing it).

### P0-6 — Vite dev-proxy is stale

**Symptom**: `web/configurator/vite.config.ts:21` regex is
`^/(state|intent|preview|healthz)` — predates Phase 1B+. Hitting
`/curations`, `/forges`, `/templates`, `/als-opened` in `npm run dev`
goes to vite (404 on its own host) instead of being proxied.

**Production-mode (server serves static) works fine.** This is a
dev-iteration-only break — UAT won't actually hit it if the user only
runs the production-served popup. Reclassify as P1 unless the user
will run `npm run dev`.

**Fix**: Update the regex to
`^/(state|intent|preview|healthz|curations|forges|templates|als-opened)`.

**Estimated**: 1 line + 1 line test. ~5 min.

**Lane**: popup.

### P0-7 — CurationRow tile not clickable

**Symptom**: User flagged during demo. In `CurationList`, the curation
"card" body (the entry name, target chip, modified-at line) has no
click handler. Only the `BookOpen` icon button (4 small icon buttons
across the bottom) fires `open.mutate(entry.name)`. The visible card
itself looks tappable but does nothing.

**Root cause**: `web/configurator/src/components/CurationList.tsx:78-123`
— the `<div className="flex items-start justify-between gap-2">` has
no `onClick`.

**Fix**: Make the row body click → open-as-active. Wrap the row in a
`<button>` (or add `role="button"` + `onClick` + keyboard handling)
that fires `open.mutate(entry.name)` if not already active. The 4 icon
buttons keep their explicit handlers.

**Estimated**: ~20 lines + 1 test. ~20 min.

**Lane**: popup.

### P0-8 — TopBar "Save" button is a noop

**Symptom**: `TopBar.tsx:72-79` declares `handleSave()` with an empty
body and a TODO comment ("Lane 1B may eventually add /intent/save-active...").
User clicks Save, nothing happens. No toast, no feedback.

**Root cause**: Intentional gap; no save semantics at the popup level
(curation files are device-COMMIT-written). But the button is rendered
and clickable.

**Fix**: Either:
- Remove the Save button entirely (the device's COMMIT is the writer);
  or
- Make it a confirm-tooltip that says "saves happen on the device's
  COMMIT button" and disables itself.

Recommend the latter (tooltip + disabled) since users may instinctively
look for a Save in the popup.

**Estimated**: ~15 lines + 1 test. ~15 min.

**Lane**: popup.

## P1 — should fix soon (won't block UAT)

### P1-1 — `pickManifest` test handler hid wire mismatch

The msw handlers under `web/configurator/src/test/handlers.ts` should
mirror real server routes, not over-mock. Adding contract tests that
boot a real FastAPI test client (via FastAPI's `TestClient`) and call
the popup's `api.ts` functions against it would have caught P0-1.

### P1-2 — `_getAlsPath()` LOM verb chain is speculative

`v0/src/m4l-js/stemforge_loader.v0.js:3759-3791`. Three fallback
verbs, none verified against real Live. Phase 5 L4 work. If verbs
silently return empty strings, `als-opened` posts `""` and bootstrap
auto-load fails silently.

### P1-3 — `__popup__` sentinel as als_path is a hack

The active-curation map keys by `.als` path. The popup has no Live
context but still wants an "active curation for the popup" entry. We
fudge with `als_path: "__popup__"`. Cleaner: separate the active-by-als
map from a "global active for headless popup operations" slot.

### P1-4 — mypy baseline at 34 errors (was ~27)

`uv run mypy stemforge/configurator/` reports 34 errors. Several are
fixable today: `default_factory=StemforgeState`, missing
`last_known_port` kwargs in `StemforgeState()` calls, etc.

### P1-5 — `tools/` ruff-format drift

`uv run ruff format --check stemforge tests scripts tools` reports 20
files in `tools/` that would be reformatted. Not configurator-owned
but trivial to auto-fix.

### P1-6 — Stale ConfiguratorStrip build artifacts

`v0/build/ConfiguratorStrip.amxd`, `v0/build/ConfiguratorStrip.maxpat`,
`v0/src/ConfiguratorStrip.amxd`, `v0/src/ConfiguratorStrip.maxpat`
remain on disk (`v0/build/` and `v0/src/` are git-tracked roots).
Phase 4B commit message said "gitignored build artifacts; no git rm
needed" — but `v0/src/ConfiguratorStrip.amxd` is at the root of `v0/src`,
not in `v0/src/m4l-devices/configurator-strip/`. Verify gitignore
status and decide.

### P1-7 — Legacy `commit_click` dead wire in builder.py

`v0/src/maxpat-builder/builder.py:976-1111`. The entire patcher
template still routes `commit_click → commitOffsets`. Phase 3B's
`bounceCuration` replaces `commitOffsets` (per PR #110), but the old
verb still ships in every rebuilt `.amxd`. Tied to P0-5 (defer
patcher rewrite for UAT).

### P1-8 — `triggerBounce` popup → `body: "{}"` works against a body
the server accepts (TriggerBounceBody has all-optional fields), but
the popup never surfaces the returned bounce spec. Operators wouldn't
know if the spec is malformed.

### P1-9 — Initial state-stream contains the legacy `Project`

Even after P0-3 fix, ensure the legacy event-source is not also
fired. Today both shapes can be received on the wire; popup handles
both but receivers in the wild may not.

## P2 — polish / nice-to-have

- ConnectionStatus dot doesn't show a tooltip about port/URL.
- StatusBar progress bar has no test coverage for `progress.fraction = 0`.
- ForgeList renders 35 entries with no virtualization — may stutter on
  large lists.
- `useProjectState` reconnect token uses `useRef.current` in a deps
  array (eslint-disable). Conventional pattern is to bump state.
- `CurationList` tooltip "cannot delete active" is silently confusing
  — the trash icon is just disabled with no visual indicator that
  active-curation is the blocker.
- The popup has no "create new curation" affordance from the
  curations rail (curations are created by device COMMIT only). For
  test setups, a "new empty curation" button would be useful.
- `intent_wire.py` schema is not used by any route in main; dead
  module from a midway agent.

## What's working well

- **Server is rock-solid.** All 186 Python tests pass; the curation
  CRUD, atomic-write, stale-detection, refresh, bounce-spec
  construction, export subprocess wiring are all clean. Pydantic
  schemas are well-organized in `schemas/`.
- **TS-types regen produces zero drift.** The Phase 0 contract is
  holding.
- **L3 max-stub harness works.** 82 device-JS tests run in 250ms
  against the stubbed Max env — historical Live-in-the-loop pain
  killer delivered.
- **Phase 4B stale-detection works end-to-end.** Confirmed via SSE:
  the fixture `stale-reference` curation's pad A01 broadcasts as
  `stale: true` with the current forge hash.
- **Phase 3A template hot-apply has correct UDP wiring.** Server
  emits the OSC-prefixed route message and tests verify the
  `/template-change A drum-rack-classic` envelope.
- **Active curation persistence round-trips.** Hitting the running
  server: `/curations/partial/open` with `als_path: "__popup__"` →
  `.stemforge_state.json` updates → subsequent `GET /curations`
  reflects.
- **Bounce spec construction is well-shaped.** A trigger-bounce
  against `partial` returns 5 pads with proper output_path and
  per-group template baked in.

## Coverage gaps

- **No contract test** between popup `api.ts` and server routes. msw
  mocks hide wire mismatches. Add a `tests/test_popup_contract.py`
  that imports the OpenAPI schema and asserts every popup function
  hits a real route with a real body shape.
- **No initial-snapshot SSE test.** The first event the popup receives
  is the legacy `Project` shape — not tested anywhere.
- **No real Live integration test runs.** Phase 5 ships skeleton
  fixture + 1 of 10 tests has a fixture; 9 fixtures are `.gitkeep`.
- **No popup → server cold-start test.** Boot server, boot popup
  pointed at it, assert the popup renders an active curation
  state from `.stemforge_state.json`.
- **No regression test for the device .amxd's UI surface.** A simple
  Python script parsing the .amxd patcher JSON and asserting
  presence/absence of named varname elements would catch P0-5-like
  drift instantly.

## Verification matrix

| Phase | Gate | Local | Notes |
|---|---|---|---|
| 0 Foundation | pytest schemas | green | 186 tests pass |
| 0 Foundation | TS regen no-diff | green | clean |
| 0 Foundation | max-stub.test.js | green | 29 tests |
| 1A CLI | tests/test_cli_forge_migration | green | 9 tests |
| 1B CRUD | tests/test_configurator_curation_crud | green | 29 tests |
| 1C Picker | v0/src/m4l-js/stemforge_loader.v0.test.js | green | 53 tests |
| 1D Popup | vitest popup | green | 43 tests |
| 1.5 Bridge | tests/test_configurator_forges | green | 21 tests |
| 2 Commit | tests/test_commit_keystone | green | 3 tests |
| 3A Templates | tests/test_configurator_templates | green | 15 tests |
| 3B Bounce | tests/test_configurator_bounce | green | 16 tests |
| 3C Export | tests/test_configurator_export | green | 26 tests |
| 4A Persistence | tests/test_configurator_state_persistence | green | 10 tests |
| 4B Stale/strip | tests/test_configurator_stale | green | 17 tests |
| End-to-end | curl against running server | green | open/close/refresh/bounce/templates all OK |
| End-to-end | popup against running server | **yellow** | initial SSE wrong; add-forge 404; close 422; tile not clickable |
| End-to-end | device against running server | **red** | deployed .amxd has old UI; JS contract unreachable via on-device buttons |
| 5 Smoke | live-runner.sh | n/a | not on main yet (PR #113 open) |

## Follow-up backlog (P1+P2)

Bundle these into a single "Configurator v1 hardening" sprint after UAT.

1. `tools/` ruff-format auto-fix sweep (P1-5).
2. Mypy delta cleanup (P1-4).
3. Strip artifact gitignore audit (P1-6).
4. Patcher visual lift per spec §3.1 (P1-7 / P0-5 deferred).
5. `__popup__` sentinel → dedicated headless-active slot (P1-3).
6. Popup contract tests (P1-1).
7. Real Live L4 fixtures (P1-2).
8. Save-button semantics nail-down (P0-8 polish path).
9. Connection dot tooltip + virtualized lists + status-bar empty-state
   coverage (P2 batch).

---

## Remediation plan

Five parallel agents launched against disjoint scopes. Each writes its
own PR; each is self-contained; each has acceptance criteria in its
brief (CI all green + tests + no regressions on existing).

| Agent | Lane | P0s addressed | File scope | Expected PR title |
|---|---|---|---|---|
| A | server | P0-1, P0-2, P0-3 | `stemforge/configurator/server.py`, `stemforge/configurator/intents.py`, `tests/test_configurator_curation_crud.py`, `tests/test_configurator_state_file.py` | `fix(configurator-server): pick-manifest route + optional als_path + initial SSE snapshot` |
| B | popup-wire | P0-4, P0-6 | `web/configurator/src/lib/api.ts`, `web/configurator/src/hooks/useProjectState.ts`, `web/configurator/vite.config.ts` | `fix(popup): commit demo patches + vite-proxy refresh` |
| C | popup-ux | P0-7, P0-8 | `web/configurator/src/components/CurationList.tsx`, `web/configurator/src/components/TopBar.tsx`, `web/configurator/src/components/CurationList.test.tsx`, `web/configurator/src/components/TopBar.test.tsx` | `fix(popup): clickable curation row + Save-button semantics` |

P0-5 (device .amxd picker) is deferred per recommendation; UAT runs on
the existing on-device buttons. Documented as a scope limit in the UAT
brief. If user disagrees, spin up a fourth agent on
`v0/src/maxpat-builder/builder.py` + amxd rebuild.

All three agents:
- Open their own PR with conventional commit prefixes.
- Co-author trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Cap at 4 commits per PR.
- Acceptance: all 10 CI workflows green; new tests added; no
  regression on existing.

---

*End of review.*
