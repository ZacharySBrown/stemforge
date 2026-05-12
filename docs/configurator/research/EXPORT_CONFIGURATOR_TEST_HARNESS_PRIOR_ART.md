# Test Harness Prior Art — m4l-devices / harness

Companion to `EXPORT_CONFIGURATOR_TESTABILITY_BUNDLE.md`. Prepared 2026-05-05 from the `m4l-devices` repo, with verification reads into `~/raindog/harness/quickstarts/max-plugin/`.

The testability bundle was generated read-only inside `stemforge/` and explicitly disclaimed (§F1, §B.4 of the bundle): *"the user's external 'harness v1' at `~/raindog/harness/quickstarts/max-plugin/` — I have not read that external repo."* This brief closes that gap. **A meaningful slice of what the bundle calls "Phase 0.5 greenfield work" already exists in the harness or in `m4l-devices`.** Reuse instead of rebuild where it fits.

This is meant to be handed to a chat-Claude / agent designing the stemforge test harness, so that "what's already built" is on the table before Phase 0.5 designs are sketched.

---

## TL;DR — bundle gaps mapped to existing components

| Bundle gap (where stated) | Existing component | Location | Reuse posture |
|---|---|---|---|
| "No headless Max load-verify" / pitfall #24 (bundle §C.5, §D.3) — *the device is strictly pull-based; no port listeners; smoke check on `.amxd` is structural-only* | `forge_device.load_verifier` — launches Max, captures Max.log delta, categorizes errors (`patchcord_*_oor`, `inlet_outlet_missing`, `expr_syntax`, `js_no_function`, `missing_object`, `missing_file`, …), never trampols user-owned Max sessions | `~/raindog/harness/quickstarts/max-plugin/tools/forge_device/load_verifier.py` (409 LOC) | **Direct reuse** for the `.amxd` build artifact. Skips cleanly when Max not present, ~10–15s wall clock. CLI: `python -m forge_device verify-load <patch.amxd>`. |
| "Push-back from outside Live is not wired today … `[fswatcher]` unimplemented, no `[udpreceive]`" (bundle §C.5) | `sf_remote.py` — UDP bus on 7420 (fire) + 7421 (dumpDict) + log-tail driver. Already runs the harness's StemForge dev device headlessly: `dump`, `fire`, `setstate`, `status`, `log --follow` | `~/raindog/harness/quickstarts/max-plugin/tools/stemforge_bridge/sf_remote.py` (471 LOC) — paired with a JS-side `sf_logger`/`sf_state` UDP listener referenced at `_stemforge_builder_reference.py` | **Pattern to copy + JS-side wiring decision.** This is exactly the "Layer 1 telemetry" the bundle's §C.5 says is missing. The harness ships a working blueprint; stemforge needs to add a `[udpreceive]` to its M4L device to receive it. |
| "Structural correctness check on `.amxd`" / `v0/tests/test_amxd.py` is "JSON validity only" (bundle §A.6) | 14 deterministic verifiers: `verify_project_field` (#6), `verify_project_searchpath` (#25), `verify_inlet_outlet_indices` (#26), `verify_plugin_pair_canonical_shape` (#27), `verify_plugin_pair_for_audio` (#7), `verify_no_node_script` (#1), `verify_no_static_comment_for_dynamic` (#3), `verify_live_dial_param_attrs` (#18), `verify_umenu_items_format` (#5), `verify_amxd_magic` (#14, sentinel `aaaa`/`mmmm`/`iiii`), `verify_amxd_round_trip`, plus 3 spec verifiers | `~/raindog/harness/quickstarts/max-plugin/tools/forge_device/verifiers.py` (394 LOC) | **Drop-in reuse** for `v0/build/StemForge.amxd`. Each verifier is pure (`patcher_dict → Result`), keyed to a numbered pitfall in the dev guide, with a `fix_hint` string the LLM can act on. Run as `python -m forge_device verify-amxd <path>`. |
| "Add `@pytest.mark.live` marker before Live-dependent tests land" (bundle §A.1) + "no formal NDJSON event protocol for fix audit" (bundle §G.2) | `forge_device.audit.Audit` — append-only NDJSON emitter, sha256 every artifact, schema-versioned (`_schema=1.0.0`), `step()` context manager auto-emits `<name>.{start,complete,error}` with `duration_ms`, `replay()` + `summarize()` for aggregation | `~/raindog/harness/quickstarts/max-plugin/tools/forge_device/audit.py` (232 LOC) | **Pattern + lightly-genericized library reuse.** Already proven on tape-loss: `docs/exec-plans/active/tape-loss-audit.ndjson` has 100+ events spanning analyze/design/build/verify phases. The schema (`event`, `phase`, `module`, `verifier`, `pass`, `pitfall`, `fix_hint`, `sha256`, `bytes`) maps cleanly onto stemforge's NDJSON-from-native-binary pattern. |
| "Most tests have no formal JSON Schema files; `stems.json`, `prechop_manifest.json`, `snapshot.json` documented only as Python dataclasses" (bundle §D.1) | `verify_spec_required_fields` + `verify_signal_chain_modules_exist` + `verify_param_refs_resolve` — pattern for cheap structural validators against YAML/JSON specs without standing up a full Pydantic model | same file as above | **Pattern.** The "spec verifier" tier is the right shape for the bundle's gap: 3-line pure functions, registered in a `SPEC_VERIFIERS` list, each returning a `Result(passed, pitfall, detail, fix_hint)`. Same plumbing as the patcher-level checks. |
| "Code-as-harness frame" / what tier of test catches what (implicit across bundle) | `docs/architecture/code-as-harness.md` — explicit 4-layer model (Telemetry / Builders / Verifiers / Creative LLM loop) framed against Murphy et al. arXiv:2603.03329 | `~/raindog/harness/quickstarts/max-plugin/docs/architecture/code-as-harness.md` | **Adopt the architectural language directly.** The "harness-as-action-verifier" / "harness-as-action-filter" / "harness-as-policy" trichotomy is a clean way to talk about the bundle's tier-split (CI / Mac dev / hardware). |
| "tests-that-exist-because-of-a-past-regression are the most valuable; M4L-side gap" (bundle §G.3) | The 20-pitfall guide (`m4l-device-development-guide.md`) is the canonical regression catalog. Each pitfall has a documented failure mode and is converted to a verifier *before* the next fix ships — that's the harness-evolution discipline. | `~/raindog/harness/quickstarts/max-plugin/specs/m4l-device-development-guide.md` (also `~/zacharysbrown/stemforge/memory/m4l_device_development_guide.md`) | **Pattern.** The discipline ("new pitfall → new verifier before fix lands") is what closes the M4L-side regression gap the bundle flags. Three new pitfalls (#25, #26, #27) were added to this catalog *during* tape-loss Phase 2 — see the auto-memory entries `project_pitfall_25_*`, `_26_*`, `_27_*`. |
| "Fixture A/B viewer" referenced in the bundle's auto-memory pointer (`project_fixture_ab_renderer.md`) but not built in stemforge | `m4l-devices/docs/fixtures-viewer/index.html` — single-file HTML, side-by-side dry/wet WAV `<audio>` players with LLM blurb cards. Built for tape-loss DSP-fixture review. | `/Users/zak/zacharysbrown/m4l-devices/docs/fixtures-viewer/index.html` | **Drop-in pattern.** Pure HTML/CSS — render synthetic dry, render wet through the device under test, paste LLM caption per pair, browse. Useful as the listening-tier above schema-validation tier. |
| "Standalone Max IDE testing before Live deploy" feedback-memory (bundle §G.2 cites `feedback_test_deploy_discipline`) | The `<device>-debug.maxpat` convention — every device ships a sibling debug patch with bypass/test-input wiring. Used by tape-loss for Max-IDE-only iteration, *before* any `.amxd` packing or Live load. | `m4l-devices/device/tape-loss/tape-loss-debug.maxpat` (and audit-trail confirms the workflow) | **Convention to adopt.** Cheaper than the load-verifier; runs in seconds inside an open Max IDE; shrinks the iteration loop *before* the heavy verifier kicks in. |

---

## The four highest-leverage reusables (deeper read)

### 1. `forge_device.load_verifier` — headless Max load-error verifier (pitfall #24)

`v0/tests/test_amxd.py` only checks ZIP magic + JSON validity. That misses the entire class of bug where the patcher *parses* but the Max engine emits ~120 console errors when it actually instantiates the audio graph: `patchcord inlet/outlet out of range`, `inlet~/outlet~: No such object`, `js: no function`, codebox `syntax error`, gen~ DSL bugs, audio-graph cycles.

The harness verifier:

- Probes `pgrep -f Max.app/Contents/MacOS/Max` *before* launch and **refuses to run if Max is already running** (won't trample a developer's open IDE).
- Clears Max's `Crash Recovery/maxworkspace-*.txt` so the next launch doesn't restore the previous session and mask the patch.
- Launches Max with the patch via `open -a`, watches `~/Library/Application Support/Cycling '74/Max 9/Logs/Max.log` until size goes idle (default 3s idle / 25s timeout), reads only the new bytes.
- Categorizes error lines via 7 regex groups, returns up to 3 sample messages per category in `Result.extra`.
- SIGTERMs only the PIDs it spawned.
- Skips cleanly when: `MAX_LOAD_VERIFIER=0`, non-Darwin, no Max binary in 4 candidate paths, or Max log doesn't exist yet.

CLI:
```bash
python -m forge_device verify-load v0/build/StemForge.amxd
# or with audit:
python -m forge_device verify-load v0/build/StemForge.amxd --audit /tmp/sf-audit.ndjson
```

Empirical result on tape-loss: caught 47 errors that *every* JSON-shape verifier passed cleanly. Three of those errors became new pitfalls (#25, #26, #27 — searchpath, inlet/outlet indices, plugin~ canonical shape) and three new structural verifiers in `verifiers.py`. **This is exactly the harness-evolution loop.**

Wire-in for stemforge: add a tier between `test_amxd.py` (ZIP/JSON shape) and "open in Live" (manual). Run on every PR that touches `v0/src/maxpat-builder/` or any JS module.

### 2. `sf_remote` — UDP push-back surface for a running M4L device

The bundle calls out at §C.5: *"the device is strictly pull-based. Max spawns Python; Python writes stdout and files; the patcher tails them. Push-back from outside Live is not wired today. The configurator's 'trigger from a skill or harness' need would either be the first such surface, or come via re-driving the M4L device through LiveAPI."*

**The harness solved this for its own M4L device, and ships the driver as a working CLI.** Two UDP ports:

- `7420` (bus) — `fire <module> <args>`. Targets: `state`, `forge`, `preset-loader`, `manifest-loader`, `settings`, `ui`, `logger`. Each maps to a JS module inside the M4L device subscribed to that port.
- `7421` (dump) — `dumpDict <name>`. Logs the full contents of a named `Dict` to the debug log; the CLI then tails the log until a `DUMP END` marker appears and returns the slice.

A canonical interaction:
```bash
uv run sf-remote setstate forging      # push canned UI state JSON
uv run sf-remote fire forge startForge  # trigger orchestrator
uv run sf-remote dump sf_state          # round-trip the resulting state dict
uv run sf-remote log --follow           # tail debug log
```

The bundle's "Phase 4 — filesystem side-channel as primary, OSC as fallback, AppleScript as last resort" recommendation gets a strict upgrade: a *direct UDP* channel into the device, with no `node.script` (which the bundle confirms is broken on macOS 26+), no AbletonOSC dependency (which needs Live + a Remote Script), and no AppleScript fragility.

The harness's JS-side listener is referenced in `tools/stemforge_bridge/_stemforge_builder_reference.py` and `sf_logger_reference.js`. **The receiver shape is the only thing stemforge needs to add to its v0 device** — the driver, canned states, log-tail logic, and dump protocol are already written.

Wire-in for stemforge: add `[udpreceive 7420]` and `[udpreceive 7421]` to `StemForge.amxd`, route to a router-JS that fans out by target. Then drive UAT scenarios from `pytest` via `socket.sendto` + log-tail-with-marker. This is what unblocks `forge-pick` and `forge-commit` in the bundle's §F.3 backlog.

### 3. `forge_device.verifiers` — the 14-verifier registry (pitfalls #1, #3, #5, #6, #7, #14, #18, #25, #26, #27)

Each is a pure `target → Result` function. The `Result` dataclass:

```python
@dataclass
class Result:
    verifier: str        # "plugin_pair_canonical_shape"
    passed: bool
    pitfall: str | None  # "#27" — links to dev guide
    detail: str          # "id-3: numinlets=1, must be 2"
    fix_hint: str        # "use plugin_in()/plugin_out() helpers"
    extra: dict[str, Any]
```

Fix-hints are **LLM-actionable strings**. The build pipeline is the harness-as-action-verifier loop from Murphy et al.: agent proposes patcher, verifier emits structured fail with hint, agent retries.

For stemforge, **all 14 are immediately applicable to `v0/build/StemForge.amxd` and to anything `v0/src/maxpat-builder/build_amxd.py` produces.** The bundle confirms `build_amxd.py` runs without Max — verifiers do too. Each verifier is <50 LOC and has a clearly numbered pitfall in `m4l-device-development-guide.md` for the LLM to read on failure.

The 3 spec verifiers (`spec_required_fields`, `signal_chain_modules_exist`, `param_refs_resolve`) are the **template** for what the bundle calls "extract `stems.json`, `prechop_manifest.json`, `snapshot.json` to `v0/interfaces/*.schema.json`" (§D.1) — but using a `Result`-returning Python function pattern instead of full JSON Schema, which is faster to author and produces better LLM error messages.

### 4. `forge_device.audit` — NDJSON event protocol with sha256 provenance

Append-only NDJSON, one event per line:

```json
{"ts":"2026-04-26T14:39:23.050Z","_schema":"1.0.0","run_id":"...","host":"...","harness_sha":"b50cd41","event":"verifier.spec_required_fields","phase":"verify","verifier":"spec_required_fields","pitfall":null,"detail":"","pass":true}
{"ts":"...","event":"artifact.hashed","phase":"build","kind":"design_doc","module":null,"path":"...","sha256":"8ee125a22fffcec1ea008abd2698168f3731fd38374109cbb12195327cddb011","bytes":6688}
{"ts":"...","event":"manual_step_required","phase":"analyze","human_step":"Drop tape-loss.amxd onto an audio track","estimate_seconds":10,"blocks_phase":"build","why_manual":"LiveAPI cannot programmatically add an M4L device","automate_when":null}
```

Three things stemforge would inherit directly:

1. **Schema-versioned events.** The `_schema` field on every event lets the harness evolve without breaking past audits. The bundle's `v0/interfaces/ndjson.schema.json` already does the equivalent for the native-binary protocol — `audit.py`'s schema can sit alongside it as the build-pipeline protocol.
2. **`Audit.step()` context manager.** Wraps any block, emits `<name>.start`/`<name>.complete` (with `duration_ms`)/`<name>.error` (with `error_type` + traceback). Trivial way to instrument the test suite without re-plumbing logging.
3. **`replay(path)` + `summarize(path)`.** `summarize()` aggregates verifier pass/fail counts, manual-step list, artifact list with hashes, and total `duration_ms`. Useful as a CI artifact uploaded with every PR — instant "what changed in the build pipeline" diff.

Wire-in for stemforge: drop `audit.py` (with module name swap) into `tests/_helpers/`, instrument the existing `tools/m4l_*.py` calls and the `forge` CLI subcommands. Every regression-fix commit henceforth gets one new line in the audit demonstrating the verifier that catches it.

---

## What does NOT carry over

The harness was built for **pre-Live structural correctness** (does the .amxd load cleanly into Max, do the JS modules wire correctly, does the spec validate). It deliberately doesn't touch:

- **Live LOM mocking.** Stemforge's `tests/js_mocks/max_api.js` (with the no-op `LiveAPI` constructor that bundle §A.5 flags as the biggest leverage point) has no analog in the harness — the harness's M4L device doesn't read/write LOM, so no mock was needed. Hardening `LiveAPI` with a backing `liveTree` Dict + setter persistence remains stemforge-side work per the testability bundle §A.5 and `docs/test-plan.md` Phase 1.
- **Click `CliRunner` wiring.** Bundle §A.1 flags this as a gap. Harness CLIs use raw `argparse` and the harness's tests live at `~/raindog/harness/tests/{unit,structural,integration}/` but cover the agent-role / config / manifest schemas — not subcommand behavior. Stemforge needs to add `tests/test_cli.py` itself.
- **Pydantic schema definitions for stemforge domain artifacts** (`stems.json`, `prechop_manifest.json`, `snapshot.json`). `manifest_schema.py` already has `SampleMeta`/`BatchManifest`. Extending that pattern to the other three is stemforge-side work.
- **JS-mock infrastructure for Max globals** (`Dict`/`File`/`Folder`/`outlet`/`post`). Lives only in stemforge. Worth keeping there.
- **The `ep133/` SysEx fixture corpus** (31 real device captures). Stemforge-specific; harness's M4L work has no parallel hardware.
- **Demucs / GPU-tier orchestration.** Stemforge-only.

---

## Recommended Phase 0.5 ordering (given prior art)

1. **Hour-1 wins, no design needed:**
   - `pip install -e ~/raindog/harness/quickstarts/max-plugin/tools` (or `PYTHONPATH=$HARNESS_TOOLS`) — exposes `forge_device` and `stemforge_bridge`.
   - Run `python -m forge_device verify-amxd v0/build/StemForge.amxd` — get the 11 patcher-shape + .amxd-magic verifier results. Add as a CI step, gated behind the `.amxd` rebuild (already non-blocking per `.github/workflows/ci.yml`).
   - Run `python -m forge_device verify-load v0/build/StemForge.amxd` on a developer Mac — the 12th verifier (the heavy one). Will skip cleanly in Linux CI.

2. **Day-1 work, low risk:**
   - Copy `audit.py` into `stemforge/tests/_helpers/audit.py` (or as a vendored dep). Wire `audit.step()` around the existing `forge` and `re-anchor` CLI entry points. Now every CLI run produces a hashable, replay-able audit.
   - Add `@pytest.mark.live` marker (bundle §A.1) and a `live_skip` fixture so the harness's structural verifiers don't accidentally get gated as "live."

3. **Week-1 work, design needed:**
   - Add `[udpreceive 7420]` + `[udpreceive 7421]` + a router JS to `StemForge.amxd`'s build pipeline (`v0/src/maxpat-builder/`). Copy the harness's `_stemforge_builder_reference.py` and `sf_logger_reference.js` patterns. Now `sf_remote.py` works against the stemforge device.
   - Build the LiveAPI-with-liveTree mock in `tests/js_mocks/` (bundle §A.5 — this is stemforge-side; harness has nothing to contribute here).
   - Add 3 stemforge-specific spec verifiers in `forge_device.verifiers`-style for `stems.json`, `prechop_manifest.json`, `snapshot.json`. Same `Result(passed, pitfall, detail, fix_hint)` shape. These extend the harness's registry rather than living parallel to it.

4. **Pre-merge developer-Mac tier (always opt-in):**
   - Tier-2 of `test_pkg_install.py` is the existing model — opt-in via `STEMFORGE_INSTALL_E2E=1`.
   - Add a `STEMFORGE_LIVE_TIER=1` env-gated tier that: (a) ensures Live is **not** running, (b) launches Live via AppleScript with a fixture `.als`, (c) drives the device via `sf_remote fire <target>`, (d) asserts on log markers / `snapshot.json`.

---

## File pointers (verified read)

Harness:
- `~/raindog/harness/quickstarts/max-plugin/tools/forge_device/verifiers.py` — 14 verifiers, registries, `run_all(target, kind=...)`
- `~/raindog/harness/quickstarts/max-plugin/tools/forge_device/load_verifier.py` — pitfall #24 headless Max launcher
- `~/raindog/harness/quickstarts/max-plugin/tools/forge_device/audit.py` — NDJSON emitter + replay/summarize
- `~/raindog/harness/quickstarts/max-plugin/tools/forge_device/cli.py` — `analyze` / `summary` / `verify-amxd` / `verify-spec` / `verify-load` / `minimal-build`
- `~/raindog/harness/quickstarts/max-plugin/tools/stemforge_bridge/sf_remote.py` — UDP driver with canned states
- `~/raindog/harness/quickstarts/max-plugin/tools/stemforge_bridge/patcher.py` — code-as-policy patcher primitives (865 LOC)
- `~/raindog/harness/quickstarts/max-plugin/tools/stemforge_bridge/amxd_pack.py` — pack/unpack
- `~/raindog/harness/quickstarts/max-plugin/docs/architecture/code-as-harness.md` — architectural frame (Murphy et al.)
- `~/raindog/harness/quickstarts/max-plugin/specs/m4l-device-development-guide.md` — the 20+ pitfall catalog (canonical)

m4l-devices:
- `m4l-devices/.claude/CLAUDE.md` — the spec-first authoring contract for this whole workflow
- `m4l-devices/docs/fixtures-viewer/index.html` — A/B HTML listening viewer (drop-in for stemforge if useful)
- `m4l-devices/docs/exec-plans/active/tape-loss-audit.ndjson` — 100+ event audit-trail demonstrating the schema in real use
- `m4l-devices/device/tape-loss/tape-loss-debug.maxpat` — example of the standalone-Max-IDE-debug-patch convention

Stemforge:
- `stemforge/EXPORT_CONFIGURATOR_TESTABILITY_BUNDLE.md` — the gap inventory this brief is responding to
- `stemforge/memory/m4l_device_development_guide.md` — original pitfall guide (the harness has the more recent fork)

---

## One sentence to hand to chat-Claude

> "Before designing Phase 0.5, read `EXPORT_CONFIGURATOR_TEST_HARNESS_PRIOR_ART.md` — the harness already ships the headless Max load-verifier (pitfall #24), the UDP push-back driver (`sf_remote`), 14 structural verifiers wired to a numbered pitfall guide, and an NDJSON audit emitter. The work that genuinely is greenfield is the LOM-mock hardening, the `CliRunner` tier, and 3 stemforge-specific schema verifiers for `stems.json`/`prechop_manifest.json`/`snapshot.json` — design those, reuse the rest."
