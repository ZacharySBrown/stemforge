# StemForge Testability Bundle

Companion to `EXPORT_CONFIGURATOR_BUNDLE.md`. Prepared 2026-05-05 for a claude.ai design conversation about hardening + a Phase 0.5 test harness before the Export Configurator implementation begins.

This bundle is organized around what's testable, what isn't, and where the seams are. Read-only pass — no refactors, no new tests, no speculation about UX paths that aren't written down.

---

## 0. Two top-of-bundle answers

### Q1 — "How much of stemforge can be tested without Live running?"

**Honest band: ~70-75% today, ~85% if the LiveAPI mock is hardened, ~10-15% will always need Live.**

Reasoning, by code area:

| Area | LOC est. | Live-free testable today? | With harness work? |
|------|----------|---------------------------|--------------------|
| `stemforge/` Python (curator, prechop, manifest, segmenter, beat_*, tempo_reconciler) | ~7000 | **Yes** — synthetic audio fixtures, no Live, no Demucs. CI already covers this. | Same. Already mature. |
| `stemforge/exporters/ep133/` byte writers + resolver + synthesizer | ~3000 | **Yes** — pure-Python round-trip via in-Python parser. EP-133 firmware not required. | Add cross-validation via phones24 TS parser as subprocess (already mentioned in spec, not implemented). |
| `stemforge/exporters/{base,koala,chompi}.py` | ~900 | **Yes** | Same. |
| `stemforge/cli.py` (~1000 lines) | 1000 | **Mostly** — CLI commands run headless except `create-templates` (OSC into open Live). Click's `CliRunner` not currently used. | Wire `CliRunner` for command-level tests — easy. |
| `tools/m4l_*.py` (m4l_export_clips, m4l_locator_anchor) | ~500 | **Yes** — they take a spec.json on disk. Live writes the spec from the JS side; tests can write it directly. The Python side never imports Live. | Same. |
| `v0/src/m4l-js/` JS modules — pure logic | ~30% of JS | **Yes** today via `tests/js_mocks/max_api.js` — already proves the pattern works (Node sandbox, mocked `Dict`/`File`/`Folder`/`outlet`). | Hardening the LiveAPI mock with a backing `liveTree` dict and setter persistence unlocks another ~40%. |
| `v0/src/m4l-js/` JS modules — LOM-driven (sf_arrangement_reader, sf_arrangement_loader, stemforge_loader.v0.js's `_commitSessionTracks`) | ~70% of JS | **No today** — the mock LiveAPI is no-op stubs. Reads return empty; writes are discarded. | With a hardened mock + LOM tree fixture: ~80% testable headless. The other 20% (LOM read-after-write semantics, deferred-call race conditions, version-specific quirks) needs Live. |
| `v0/build/StemForge.amxd` container — does it open in Live? Does Max parse the patcher? Do JS modules load without errors? | — | **No** — needs Max + Live to load. | Live integration only. |
| End-to-end UX (drop locator → click EXPORT → .ppak appears → upload to device → device plays it) | — | **No** — top half needs Live, bottom half needs hardware. | Tier-split: Live integration tests for top half (manual or Mac runner with Live preinstalled); manual hardware test for bottom. |

The pure-DSP, byte-format, and orchestration logic (where most regressions historically land — see §G) is testable in CI without Live. The thin LOM-glue layer and the visible-surface tests (UI rendering, button reachability across Live versions, JSLiveAPI quirks) need Live.

**Implication for the harness:** Build the Python/Node tier first. It pays for itself fast and runs in seconds. Treat Live integration as an opt-in tier that runs on a developer Mac before merge, not in CI. This matches what `docs/test-plan.md` already proposed (Phases 2–3 in CI; Phase 4 opt-in).

### Q2 — "Is there a path to driving Live programmatically from CI, or is this fundamentally developer-laptop-only?"

**Developer-laptop-only for the foreseeable future.** Live cannot run headless. There is no Live CLI, no Docker image, no `--no-gui`. Some of what you might want is feasible, but only on a Mac with Live installed:

- **AppleScript can launch Live and open a project.** Fragile but works.
- **AbletonOSC** (third-party Remote Script) gives external control of Live over OSC — `stemforge create-templates` (cli.py) already optionally targets it on port 11000. Not a CI fit; needs Live running.
- **GitHub Actions macOS runners** can technically have Live preinstalled on a self-hosted runner. Cost: Mac hardware + Live license per runner + maintenance. Sustainable for a personal project: not really. Sustainable as a self-hosted runner zak occasionally babysits: yes.
- **`docs/test-plan.md` Phase 4** weighs three Live-driver strategies (AppleScript, OSC, "filesystem side-channel"). The recommendation it lands on: filesystem side-channel as primary, OSC as fallback, AppleScript as last resort. None implemented.

**Practical answer for the harness:**
- CI tier (GitHub Actions Linux + macOS): Python tests + Node JS-mock tests + .amxd build determinism check + .pkg installer Tier 1. ~70% of stemforge.
- Developer-Mac tier (manual or self-hosted runner): tests marked `@pytest.mark.live`, run pre-merge. AppleScript launches Live, opens fixture .als, triggers device action, asserts on filesystem side-channels (logs + manifests).
- Hardware tier (manual): EP-133 over USB-MIDI, Launchpad. Never automated. Document the manual checklist instead.

---

## 0.5 Two preflight findings worth flagging

### F1 — `feat/harness-patterns` is misleading. It is **not** a test harness branch.

`git merge-base feat/harness-patterns main` resolves to the branch tip itself; main is **128 commits ahead** of it. The branch contains exactly one commit (`0dc3b4a "Add multi-agent Claude Code harness patterns"`, 2026-04-14) which added agent-role markdown files (`.claude/CLAUDE.md`, `.claude/agents/{architect,engineer,operator,reviewer}.md`, `.claude/skills/{design,plan,review,simplify}.md`). It's the **multi-agent role + slash-command harness**, not a test harness. The name is a coincidence.

The "harness" referenced in the user's memory entry `project_m4l_harness_v1` is a **separate project** at `~/raindog/harness/quickstarts/max-plugin/` — outside this repo. Per the memory, it has triad personas, an audit emitter, 11 verifiers, a DSL, and is "wired via .claude symlinks" into m4l-devices. Worth reading before building Phase 0.5 from scratch — there may be reusable patterns there. **I have not read that external repo as part of this bundle.**

### F2 — `EXPORT_CONFIGURATOR_PLAN_v3.md` does not exist in this repo

I searched the whole tree (`find . -name "*PLAN*v3*" -not -path './.venv/*' -not -path './.claude/worktrees/*"`). Nothing. Either the chat-Claude has it as a draft outside the repo, or it hasn't been pulled in yet. This bundle assumes the chat-Claude is operating from its own copy.

---

## A. Existing test surface

### A.1 — Runner + CI config (load-bearing)

- **pyproject.toml** [tool.pytest.ini_options]: `testpaths = ["tests"]`. Note: `v0/tests/` is NOT in default testpaths — it's run explicitly via `uv run pytest v0/tests/ -v`.
- **`.pre-commit-config.yaml`**: ruff check + ruff format on `^(stemforge|tests)/` (auto-fix, blocking). Trailing whitespace + EOL + YAML/JSON/TOML format checks (blocking). Mypy and pytest are deferred — explicitly NOT blocking commits per the file's own header comment.
- **`.github/workflows/ci.yml`**: three jobs.
  1. `lint` (ubuntu, 5min): ruff check + format on stemforge + tests.
  2. `test` (ubuntu, 8min): `pytest -q --maxfail=5` with `[dev]` extra only — **never installs `[native]` or `[analyzer]`**. Asserts `torch` not imported by `stemforge.cli` import. This is Track B's "core import is light" gate.
  3. `smoke-build-als` (macos-14, 8min): builds .als with `continue-on-error: true` (Track D blocker — currently expected to fail).
  4. (also `smoke-build-amxd` etc — see file)
- **`.github/workflows/release.yml`**: tag-triggered. Builds native binary (universal2), .amxd, .als, signs+notarizes, packages. Out of scope for the harness conversation.
- **No Makefile, justfile, Taskfile.** Everything is `uv run pytest` / `pre-commit run` / direct CLI.
- **Pytest markers in active use:** None custom. I confirmed by grep — no `@pytest.mark.live`, no `@pytest.mark.slow`, no `@pytest.mark.integration`. Skip-conditions use `pytest.mark.skipif(shutil.which("node") is None, ...)` on the JS bridge test, and `pytest.skip(allow_module_level=True)` patterns in `v0/tests/` for missing artifacts.

**Annotation: load-bearing.** This is the foundation. Phase 0.5 should add a custom marker (`@pytest.mark.live` per the test-plan recommendation) before the harness adds Live-dependent tests so CI knows what to skip.

### A.2 — `tests/` (top-level test modules)

16 files. Verified by `ls tests/test_*.py`:

| File | Coverage (one line) | Annotation |
|------|---------------------|------------|
| `test_beat_align.py` | Beat-align warping + tempo inference; synthetic clicks | L |
| `test_beat_detect.py` | Onset detection, BPM extraction; mocked beat-this fallback | L |
| `test_exporters.py` | base.py + EP-133 + Chompi exporter facades | L |
| `test_forge.py` | End-to-end slice + curate; synthetic audio | L |
| `test_js_bridge.py` | Spawns Node test runner for JS mock tests; skipped if `node` missing | L — the seam |
| `test_koala_exporter.py` | Koala .zip layout | L |
| `test_m4l_export_clips.py` | M4L bounce-to-clip pipeline (round-trip) — 11 round-trip tests per memory | L — most-relevant precedent |
| `test_manifest_schema.py` | SampleMeta + BatchManifest schema, hashing, sidecar/batch I/O | L |
| `test_midi_extractor.py` | MIDI note extraction from onsets | C |
| `test_oneshot.py` | Drum classifier oneshot detection | C |
| `test_packaging.py` | "torch not imported by core" import-time check | L — gates Track B's tier split |
| `test_palette.py` | Ableton palette JSON (26 colors) | C |
| `test_pipelines.py` | YAML pipeline parsing + prechop integration | L |
| `test_prechop.py` | Padded chunk extraction, silence-pad fix, off-by-one indices | L — regression-test rich |
| `test_segmenter.py` | Song structure detection | C |
| `test_tempo_reconciler.py` | Tempo source priority chain + fallback | L — has real-audio fixtures |

All test data is **synthetic generated in-test or small in-repo WAVs**. None require Live, Demucs, or GPU. No `tests/fixtures/audio/` directory exists at the top level — I verified.

### A.3 — `tests/ep133/` (EP-133 hardware export pipeline)

12 files. Verified by `ls tests/ep133/test_*.py`:

| File | Cluster | Annotation |
|------|---------|------------|
| `test_packing.py` | Bit-packing helpers | L |
| `test_pad_record.py` | 26/27-byte pad record format | L |
| `test_song_format.py` | Pattern + scene + settings byte builders | L — round-trip with in-Python parser |
| `test_song_resolver.py` | Locator → snapshot resolver | L |
| `test_song_synthesizer.py` | Snapshot → PpakSpec | L |
| `test_song_integration.py` | snapshot.json + manifest → .ppak → re-parse | L — closest thing to E2E for arrangement export |
| `test_ppak_writer.py` | TAR + ZIP container | L |
| `test_payloads.py` | SysEx command payloads | L |
| `test_assign_pad.py` | Pad-rotation policy | L |
| `test_sample_params.py` | Sample-parameter SysEx structs | L |
| `test_capture_reference.py` | Capture .ppak from device via SysEx — uses `reference.ppak` if present | L (gated) |
| `test_ep133_stem_export.py` | Stem-mode export end-to-end | L |

### A.4 — `tests/ep133/conftest.py` and `tests/ep133/fixtures/`

Verified contents of `tests/ep133/fixtures/`:
- `kick_00_init.syx` + `kick_01.syx` … `kick_30.syx`: **31 real device SysEx captures from a kick-sample upload session.** This is the most fixture-rich corpus in the repo. Used by `garrett_kick_messages` session-scoped fixture in `conftest.py:31-44`.
- `001_kick_combined.syx`: combined version
- `reference.ppak`: **does exist** (verified `ls`). Real device-captured project. Used by `test_capture_reference.py` and `test_song_integration.py`. Tests skip cleanly if missing.
- `sample_arrangement.json`, `sample_manifest.json`: small JSON stubs
- `pad/`: subdirectory (binary pad-record samples — didn't enumerate)

**Annotation: load-bearing fixture corpus.** Real-device captures are the right precedent for the EP-133 byte-format work. The `_split_messages` helper (conftest.py:11-19) splits multi-message `.syx` files at `0xF7` — reusable for any SysEx replay. **Strong candidate for Phase 0.5 to extend** with reference captures for other devices (Chompi `.wav` layouts, Koala .zip, etc.).

### A.5 — `tests/js_mocks/` (Node-side JS sandbox)

Verified files:
- `max_api.js` — mock for Max's globals (Dict, File, Folder, post(), outlet()). Per the agent who read it: "implements HFS path normalization, virtual filesystem (seeded from real FS), outlet capture." Scope is partial — what `sf_preset_loader.js`, `sf_state.js`, `sf_forge.js`, and the priority-chain code need.
- `sandbox.js` — VM-based module loader for running Max JS in Node context.
- `priority_chain_fixture.js` — fixture data for preset chain tests.
- `test_preset_resolution.test.js`, `test_arrangement_loader.test.js`, `test_arrangement_reader.test.js`.

**LiveAPI mock specifically: no-op stubs.** Constructor is a recorder; `get`/`set`/`call`/`getcount` return empty values. **Cannot simulate LOM tree changes today.** This is the harness's biggest leverage point: hardening `LiveAPI` with a backing `liveTree` Dict and setter persistence unlocks the JS modules that read-after-write the LOM (which is most of them). `docs/test-plan.md` Phase 1 is exactly this work — it's spec'd, not built.

**Annotation: load-bearing seam, partially built.** Extend it.

### A.6 — `v0/tests/` (shippable artifact integration tests, "Track G")

Verified: `conftest.py`, `fixtures/`, `README.md`, `test_als.py`, `test_amxd.py`, `test_arrangement_reader.py`, `test_binary.py`, `test_pkg_install.py`, `validate-ndjson.py`.

- **Scope (per `v0/tests/README.md`):** "End-to-end tests that verify the shippable v0 artifacts work without requiring Ableton Live to be open."
- **Per-file tests:**
  - `test_binary.py`: validates `v0/build/stemforge-native` runs, emits NDJSON conforming to `v0/interfaces/ndjson.schema.json`, writes manifest. Skipped if binary absent.
  - `test_amxd.py`: structural check on `.amxd` (Max patcher ZIP magic, JSON validity).
  - `test_als.py`: ALS validation — currently all-skip (Track D blocker on `v0/assets/skeleton.als`).
  - `test_pkg_install.py`: **two-tier installer test.** Tier 1 (default, <2s): pkgutil expand, assert layout. Tier 2 (opt-in via `STEMFORGE_INSTALL_E2E=1`, 30-60s): actual `sudo installer -pkg`, verify binary executes.
  - `test_arrangement_reader.py`: tests the Python side of arrangement reading.
  - `validate-ndjson.py`: not a test — a CLI utility.
- **Fixtures:** `expected_stems.json`, `generate_loop.py`, `short_loop.wav`. Modest but real.
- **Skip semantics:** `pytest.skip(allow_module_level=True)` for missing artifacts; per-test skips for missing optional deps (`jsonschema`).

**Annotation: load-bearing pattern, well-designed.** The "tolerant fixture resolution" + "tier-1 fast / tier-2 opt-in" model is the template the harness should copy for Live integration: tier-1 = mocked/byte-level (always runs), tier-2 = full-Live (gated on env var).

### A.7 — Coverage map: what's tested vs gaps

For each major module:

| Module | Tested? |
|--------|---------|
| `stemforge/curator.py` | Indirectly via `test_forge.py` (no dedicated test) |
| `stemforge/prechop.py` | Yes — `test_prechop.py`, regression-rich |
| `stemforge/manifest_schema.py` | Yes — `test_manifest_schema.py` |
| `stemforge/manifest.py` | Indirect (via exporters) |
| `stemforge/cli.py` | Only the import-time tier-split check (`test_packaging.py`); no `CliRunner`-based subcommand tests |
| `stemforge/exporters/ep133/song_*.py` | Yes — dedicated tests per file |
| `stemforge/exporters/ep133/ppak_writer.py` | Yes |
| `stemforge/exporters/koala.py` | Yes |
| `stemforge/exporters/chompi.py` | Indirect via `test_exporters.py` |
| `stemforge/curation_schema.py` | **No tests** — gap |
| `stemforge/segmenter.py` | Yes |
| `stemforge/beat_align.py`, `beat_detect.py`, `tempo_reconciler.py` | Yes |
| `v0/src/m4l-js/sf_*.js` (sf_state, sf_preset_loader, sf_arrangement_reader/loader) | Partial via `tests/js_mocks/` — gap on LOM-write-dependent modules |
| `v0/src/m4l-js/stemforge_loader.v0.js` (2004 LOC, the COMMIT button) | **No tests** — gap |
| `v0/src/m4l-js/sf_ui.js` (1082 LOC, the v8ui paint code) | **No tests** — gap |
| `tools/m4l_export_clips.py` | Tested via `test_m4l_export_clips.py` (the strongest precedent) |
| `tools/m4l_locator_anchor.py` | **No tests** — gap |
| `tools/ep133_*.py` (load_project, load_hybrid_session, etc.) | **No tests** — gap |
| `v0/src/maxpat-builder/build_amxd.py` + `amxd_pack.py` | Has dedicated tests in `v0/src/maxpat-builder/tests/` (separate from main suite) |

**Biggest test-coverage gaps that will hurt the configurator:**
1. `stemforge_loader.v0.js` (the COMMIT button + LOM track builder) — 2004 LOC, no tests.
2. `sf_ui.js` (paint + hit-test) — 1082 LOC, no tests. The configurator's popup will share this pattern.
3. `tools/m4l_locator_anchor.py` — the bidirectional-locator-sync work the configurator wants will route through this code path.
4. `stemforge/cli.py` subcommand-level tests — currently only "import doesn't drag torch" is asserted.

---

## B. The `feat/harness-patterns` branch

See §F1. **Stale. Not a test harness.** Contents:
```
.claude/CLAUDE.md             (155 lines)
.claude/agents/architect.md   (43 lines)
.claude/agents/engineer.md    (44 lines)
.claude/agents/operator.md    (38 lines)
.claude/agents/reviewer.md    (55 lines)
.claude/settings.json         (11 lines)
.claude/skills/design.md      (70 lines)
.claude/skills/plan.md        (87 lines)
.claude/skills/review.md      (86 lines)
.claude/skills/simplify.md    (55 lines)
```

These are the agent-role files that became `.claude/CLAUDE.md` and the four agents currently on `main`. They're the multi-agent **collaboration** harness, not the test harness.

If the chat-Claude was hoping the branch had Phase 0.5 already partially built — it doesn't. **Building Phase 0.5 is greenfield.** The reusable starting points are:
1. `tests/js_mocks/max_api.js` (Node-sandbox mock — extend it)
2. `tests/ep133/conftest.py` (fixture pattern — copy it)
3. `v0/tests/conftest.py` (tolerant fixture resolution + tier-split skip pattern — copy it)
4. The user's external "harness v1" at `~/raindog/harness/quickstarts/max-plugin/` (per memory — read it before designing)

---

## C. Programmatic Live control

Every place the codebase talks to Live, by file:

### C.1 — JS modules (LiveAPI usage)

Confirmed by `grep -l "LiveAPI" v0/src/m4l-js/*.js`:

| Module | Reads | Writes | Live state required | Side-channel? |
|--------|-------|--------|---------------------|---------------|
| `sf_arrangement_reader.js` | `live_set.{tempo, signature_numerator/denominator}`, `tracks[].name`, `cue_points[].{time, name}`, `arrangement_clips[].{file_path, start_time, length, warping}` | None | Tracks named A/B/C/D; ≥1 cue_point | **Yes** — writes `snapshot.json` to disk + appends to `~/stemforge/logs/sf_debug.log` |
| `sf_clip_export.js` | `live_set.tracks[].name`, `clip_slots[].clip.{file_path, start_marker, end_marker, loop_*, warping}`, `tempo`, `signature_numerator` | None directly | Selected tracks; clips referencing source WAVs | **Yes** — JS writes spec.json, shells `tools/m4l_export_clips.py` which writes WAV slices + sidecars + batch manifest, emits NDJSON to stdout |
| `sf_arrangement_loader.js` | None (pure load) | `live_set.tempo`, `tracks.{name, color}`, `clips[].{name, start/end_marker, loop_*, warp_mode}`, warp_marker writes | Project must be open; tracks created/duplicated | Indirect (asserting requires re-reading) |
| `stemforge_loader.v0.js` | `live_set.tracks`, `clips[]`, LOM hierarchy for template matching | `track.{name, color}`, `clip.{file_path, start/end_marker, loop_*, warp_mode}`, `warp_markers[]` | Templates like `SF \| Drums Raw` must exist; manifest readable from disk | Indirect; `_commitSessionTracks` (line 1707) writes its result back into `manifest.session_tracks` (in memory dict, then rewritten to disk) |
| `stemforge_param_scraper.js` | All Live device parameters (audio + MIDI effects) | Creates/deletes devices transiently for enumeration | Dedicated tracks `SF_Scraper_Audio` / `SF_Scraper_MIDI` pre-staged | **Yes** — writes `~/Documents/StemForge/live_devices.json` |
| `sf_forge.js` | None (orchestrator) | None directly | — | **Yes** — Outlets logged; child processes write logs |

**Pattern to lean on:** `sf_arrangement_reader.js` and `sf_clip_export.js` already use the side-channel filesystem assertion approach. The whole device leans toward writing-to-disk + tail-the-file rather than poking back into Live to verify. The harness inherits this: assert on the files, not on LOM state.

### C.2 — Other Live transports

I grepped the JS for `OSC`, `osc`, `applescript`, `osascript`, `python-osc`, `mido`, `sysex` (within `v0/`). Findings:

- **No OSC** in any of the M4L JS modules. Live is reached only via LiveAPI.
- **AbletonOSC** is referenced in `stemforge/cli.py` (`create-templates` command, port 11000). External — not in the device.
- **AppleScript** is mentioned in `docs/test-plan.md` as a Phase 4 strategy for launching Live programmatically. Not implemented anywhere.
- **MIDI/SysEx** is for the EP-133 (separate hardware), not Live.

**Annotation:** The Live↔stemforge link is LiveAPI-only. The harness can either (a) drive the M4L device directly via LiveAPI (requires Live), or (b) drive the Python helpers headless (the `tools/m4l_*.py` scripts), bypassing the device entirely. Option (b) is what `test_m4l_export_clips.py` already does — and it's the right pattern for the next ~75% of harness work.

### C.3 — Python helpers in `tools/m4l_*.py`

| File | Invoked from | Consumes | Emits | Idempotent? | Live required? |
|------|---|---|---|---|---|
| `tools/m4l_export_clips.py` | `sf_clip_export.js` via `[shell]` | spec.json (LOM-derived clip metadata) + source WAVs | WAV slices, .manifest_<hash>.json sidecars, .manifest.json batch, NDJSON to stdout | Yes — re-run on same spec overwrites | **No** — operates on disk only |
| `tools/m4l_locator_anchor.py` | `sf_locator_anchor.js` (the JS half is in-repo per memory; whether the device wires it is a separate question) via `[shell]` | track-dir path + bpm + first_downbeat | NDJSON: `anchor_started`, `anchor_complete`, `anchor_error` | Yes | **No** — delegates to `stemforge re-anchor`, which never opens Live |

**This is the seam.** Both Python helpers are headless. Their inputs are JSON files; their outputs are JSON, WAV, and NDJSON. The harness can drive them directly without ever opening Live. Anything that runs through this pattern is testable in CI — the configurator should follow it.

### C.4 — `.amxd` build pipeline determinism

Files: `v0/src/maxpat-builder/build_amxd.py`, `builder.py`, `amxd_pack.py`, `receiver_builder.py`, `router_builder.py`. Has its own test dir at `v0/src/maxpat-builder/tests/`.

**From spec/code reading** (confirmed):
- Pure Python — no Max needed. `pip install pyyaml` is enough.
- Input: `v0/interfaces/device.yaml` (declarative spec) + JS module list.
- Output: a `.amxd` file. ~50-100 KB.
- The packer comment notes: "the pretty-printing of our packer is not byte-identical to Max's." Round-trip is reliable; bit-identical-rebuild is not guaranteed.

**Implication for harness:**
- ✅ "Rebuild .amxd in CI as test setup" — yes, fast.
- ✅ "Round-trip test: pack → unpack → assert struct equality" — already done in maxpat-builder/tests/.
- ⚠️ "Hash the .amxd in CI and assert it matches a committed reference" — fragile across Python versions. Don't.

### C.5 — External control surface (the `[fswatcher]` question)

I grepped the JS for `fswatcher`, `udpreceive`, `udpsend`, `[shell]` (verb), and any external-input pattern. Findings:

- The device has `[shell]` for spawning subprocesses (output → patcher).
- **No `[fswatcher]`** — the cheap external-control path the user's memory mentions remains unimplemented.
- **No port listeners.** No `[udpreceive]`, no `[oscin]`.
- **No `[node.script]`** that's working — per `docs/m4l-device-status.md`, the bridge is currently broken on macOS 15.6+ hardened runtime.

**Conclusion:** The device is **strictly pull-based**. Max spawns Python; Python writes stdout and files; the patcher tails them. Push-back from outside Live is not wired today. The configurator's "trigger from a skill or harness" need would either be the first such surface, or come via re-driving the M4L device through LiveAPI (which is what `stemforge create-templates` does for AbletonOSC).

---

## D. State that can be asserted on

### D.1 — JSON schemas the system reads or writes

| Schema | Where written | Schema location | Validation |
|--------|---------------|-----------------|------------|
| `stems.json` (StemManifest) | `stemforge/cli.py` (split, forge); written via `stemforge/manifest.py:write_manifest` | dataclass at `stemforge/manifest.py:47-58` | Plain JSON; no formal schema file |
| `prechop_manifest.json` | `stemforge/prechop.py:_write_manifest` | dataclass `ChunkMeta` at `stemforge/prechop.py:98-117` | Plain JSON; no formal schema file |
| `snapshot.json` | `v0/src/m4l-js/sf_arrangement_reader.js:runArrangementExport` | inline JS in the reader's header comment (lines 17-34); Python side of resolver assumes shape | No formal schema file |
| Curation `manifest.json` | `stemforge/curator.py:curate` (writes `beat_dir/manifest.json`) | inline dict at `stemforge/curator.py:720-748` | No formal schema |
| `.manifest_<hash>.json` (sidecar) + `.manifest.json` (batch) | `stemforge/manifest_schema.py:write_sidecar` and `write_batch` | Pydantic `SampleMeta` + `BatchManifest` at `stemforge/manifest_schema.py:62-94` | **Pydantic-validated** |
| `index.json` (track index for M4L discovery) | `stemforge/manifest.py:update_index` | implicit `list[str]` of track names | Plain JSON |
| `device.yaml` (M4L device spec) | hand-edited; consumed by builder | `v0/interfaces/device.yaml` | Implicit |
| **NDJSON event protocol** | native binary stdout + `tools/m4l_export_clips.py` + `tools/m4l_locator_anchor.py` | **`v0/interfaces/ndjson.schema.json`** — formal JSON Schema draft-07 | jsonschema-validated where used |
| `tracks.yaml` (M4L track templates) | hand-edited | `v0/interfaces/tracks.yaml` | Implicit |
| `live_devices.json` | `stemforge_param_scraper.js` writes; consumed by curation v2 | `stemforge/data/live_devices.json` | Implicit |

**Assertion-ready surfaces:** Pydantic schemas and the NDJSON spec are runtime-validatable. The rest are just JSON — easy to assert structurally with `dict.get` checks.

**Gap that hurts the configurator:** Three of the most important contracts (`stems.json`, `prechop_manifest.json`, `snapshot.json`) have no formal JSON Schema files. They're documented as Python dataclasses or JS comments. Phase 0.5 should consider extracting them to `v0/interfaces/*.schema.json` for cross-language validation — this also gives the harness machine-readable state to diff.

### D.2 — Binary outputs that could be hashed

| Output | Stable across runs? | Recommended assertion |
|--------|---------------------|------------------------|
| `.ppak` | Probably (per the spec, byte format is fully deterministic given inputs and reference template), but `meta.json` has a `generated_at` ISO timestamp — that drifts. | Hash with timestamp scrubbed; or assert byte-level on TAR-internal files only. The byte-level test in `test_song_format.py` already does the latter. |
| `.amxd` | Round-trip stable; not bit-identical-rebuild-stable across Python versions. | Round-trip unpack-repack in tests (already done in `v0/src/maxpat-builder/tests/`); don't hash. |
| `.als` | Unstable (Live writes timestamps, GUIDs). | Asserting structural via lxml; already attempted in `v0/tests/test_als.py` (currently all-skip). |
| Bounced `.wav` chunks (from `tools/m4l_export_clips.py`) | **Stable** if source WAV is stable and soundfile is deterministic. The clip-export tests (`test_m4l_export_clips.py`) round-trip WAV bytes. | Hash assertion is reasonable here. |
| Curated bar `.wav` files | Stable given source + slicing config. | Hash + length assertion. |
| Sidecar `.manifest_<hash>.json` | Stable JSON serialization | Schema + content assertion |

### D.3 — Logs and event streams

- **`~/stemforge/logs/sf_debug.log`** — appended by every M4L JS module via `_sfFileLog()` / `_arrFileLog()` helpers. Plain text, ISO-8601 timestamps, `[Module] message` format. **Greppable.** No formal schema. Per `docs/test-plan.md`, this is the proposed primary M4L-in-Live test channel.
- **NDJSON to stdout** — `tools/m4l_*.py` and `stemforge-native` emit one JSON object per line. Schema in `v0/interfaces/ndjson.schema.json`. The Phase-1 native-binary protocol (events: `started`, `progress`, `stem`, `bpm`, `slice_dir`, `complete`, `error`) is the most rigorous schema in the repo.
- **Max console** — `post()` calls. Not scriptable from outside Max. Useful only when running tests with Max IDE open.

**The harness's filesystem-side-channel approach works because all three of these go to disk.** A Live-integration test can: (1) write a fixture .als + manifest, (2) launch Live (AppleScript), (3) trigger the device action, (4) wait for the expected log line OR snapshot.json to appear, (5) assert on its content, (6) close Live. None of those steps require LOM read-after-write.

---

## E. CLI surface

### E.1 — `stemforge <subcommand>` (verified by reading `stemforge/cli.py` decorators)

| Subcommand | What it does | Live? | Demucs/torch? | Network/GPU? |
|---|---|---|---|---|
| `split` | Demucs separate → BPM/downbeat detect → bar-level slice → write stems.json | N | **Y** | Y (faster on GPU) |
| `re-anchor` | Re-cut prechop chunks at user-supplied BPM/downbeat (skip Demucs) | N | N | N |
| `forge` | split + slice-bars + curate; emits NDJSON | N | **Y** | Y |
| `export` | Format curated stems for hardware (EP-133, Chompi, Koala, both) | N | N | N |
| `export-song` | snapshot.json + stems.json + reference template → .ppak | N | N | N |
| `export-koala` | Bulk Koala bank-zip exporter | N | N | N |
| `analyze` | Genre/instrument/BPM detection (recommends settings) | N | **Y** (CLAP/transformers) | Y (model download) |
| `clean-beats` | Remove silent slices below RMS threshold | N | N | N |
| `generate-pipeline-json` | Compile YAML pipelines → JSON for M4L | N | N | N |
| `list` | Show available Demucs models | N | N | N |
| `create-templates` | Build 7 StemForge template tracks in Live (via OSC if AbletonOSC running) | **Y** (only if user wants OSC mode; otherwise prints instructions) | N | N |

**Annotation: load-bearing surface.** Most of these are CLI-testable with `click.testing.CliRunner` against synthetic inputs. The harness should add a tier of subcommand tests — `tests/test_cli.py` is missing today (no `CliRunner` use anywhere in tests).

### E.2 — `tools/` scripts runnable as CLIs

Verified `ls tools/`. Annotated by Live-dependence:

| Script | Purpose | Live? |
|---|---|---|
| `audit_resampling.py` | Compare manifest claims vs actual WAV files; flag silent resamples | N |
| `beat_curator.py` | Legacy compat shim — moved to `stemforge.curator` | N (D — dead) |
| `beat_dashboard.py` | Generate HTML dashboard of beat-alignment metrics | N |
| `diag_definition_tempo.py` | Tempo diagnostic for one track | N |
| `ep133_bpm_matrix.py` | EP-133 BPM-byte test matrix | N |
| `ep133_capture_reference.py` | Capture .ppak from device via SysEx | **Y** (USB-MIDI; not Live) |
| `ep133_load_hybrid_session.py` | Upload hybrid session to EP-133 | **Y** (USB-MIDI) |
| `ep133_load_project.py` | Bulk-load curated stems to EP-133 | **Y** (USB-MIDI) |
| `export_koala_all.py` | Bulk Koala export (precursor to `stemforge export-koala`) | N |
| `extract_loop_test.py` | Cut a 4-bar loop for verification (drag into Ableton manually) | N |
| `find_first_drum_cut.py` | Onset detection diagnostic | N |
| `find_main_beat_drop.py` | Drop detection diagnostic | N |
| `m4l_export_clips.py` | Bounce clips → manifests (called from device) | N (Python-side) |
| `m4l_locator_anchor.py` | Re-anchor from locator (called from device) | N (Python-side) |
| `probe_loop.py` | Iterate BPM/downbeat manually | N |
| `reanchor_all_processed.py` | Bulk re-anchor every track in `~/stemforge/processed/` | N |
| `reslice_and_curate.py` | Re-curate a track at new strategy/n_bars | N |
| `run_js_tests.sh` | Run Node-based JS tests | N |
| `run_plans.py` | Ad-hoc curation strategy demo | N (D) |
| `sf_deploy.py` | Sync M4L JS + presets to package + library | N (filesystem only) |
| `sf_remote.py` | Remote ops helper | N |
| `validate_audio.py` | Score curated WAVs via Gemini multimodal | N (network) |
| `verify_tempo.py` | Full tempo diagnostic matrix | N |

---

## F. Known UX paths (only what's documented)

### F.1 — Documented walkthroughs (load-bearing)

| Flow | Implementation status | Source |
|------|----------------------|--------|
| **Split** | Shipped | `README.md`, `docs/system-design.md`, `docs/user-guide.md` |
| **Re-anchor** | Shipped | `cli.py:re_anchor` docstring; `docs/system-design.md` |
| **Forge (full pipeline)** | Shipped | `cli.py:forge` docstring; `specs/m4l-integrated-forge-device.md` |
| **M4L device load (template auto-creates tracks)** | Shipped | `docs/clip-export-button-wiring.md`, `docs/m4l-device-status.md` |
| **EP-133 song export (arrangement → .ppak)** | Shipped | `docs/ep133-song-export-workflow.md`, `specs/ep133-arrangement-song-export.md` |
| **Bounce clips (sidecars + batch manifest)** | Python+JS shipped; Max button wiring partial | `docs/feature-backlog.md`, `docs/clip-export-button-wiring.md` |
| **EP-133 hybrid-session upload** | Shipped (CLI) | `tools/ep133_load_hybrid_session.py` docstring |

### F.2 — Skills (slash commands)

Verified `ls .claude/skills/`. Per the system-prompt skills list visible in this session: `forge-launch`, `forge-run`, `forge-all`, `ep133-load`, plus generic ones (`init`, `review`, `security-review`, `daily-reading`, `loop`, `schedule`, `claude-api`).

| Skill | Wraps | Live? |
|-------|-------|-------|
| `forge-launch` | Launch Ableton + (optionally) open StemForge.als | Y |
| `forge-run` | Run `stemforge forge`, stream NDJSON | N |
| `forge-all` | Compose forge-launch + forge-run | Y |
| `ep133-load` | Load a single audio sample to a specific EP-133 pad | Y (USB-MIDI) |

**Aspirational (per memory + feature-backlog):** `forge-pick`, `forge-commit` — both blocked on absence of a device external-control surface. This is the same gap as F2 in §C.5.

### F.3 — Documented but not implemented (don't speculate beyond this list)

Per `docs/feature-backlog.md`:
1. **Bounce-to-Clip + Recent-Clip Collector** — partially shipped, Max button wiring incomplete.
2. **Forge Skills (full set)** — partially shipped; pick + commit blocked.
3. **Commit-With-Bounce** — spec only.
4. **VST Extraction (strip third-party plugins from templates)** — backlog only.

The user mentioned "aspirational paths only in your head" — those need to come from him, not me. I haven't fabricated any flows beyond what's written down.

---

## G. Known testing gaps and pain (regression signal)

### G.1 — Patterns from git log + commit messages

I scanned recent commit messages (~last 100). Clusters where bugs have actually shipped:

**Tempo detection / downbeat** — most regression-rich area in the repo:
- "venv drift hides beat-this; reconciler silently degrades to librosa-only" — caught 2026-05-03 after a uv-sync drift; symptom (Definition's BPM coming back doubled at 120 instead of 90) was indistinguishable from a real DSP bug. Now there's an explicit loud-warning in `cli.py` (visible in the in-progress `git diff` on cli.py at lines 325-348).
- Multi-source reconciler bugs (`fix(tempo):`)
- prechop silence-pad off-by-one and pre-source negative-target handling (the in-progress `git diff` on prechop.py is exactly this fix in flight)

**EP-133 byte format** — many small commits to land the right layout:
- `fix(ep133-song):` chain — full byte-level rewrite over multiple commits to get scenes working (`0865298` is the big one). Verified hardware behavior diverged from spec (e.g., scene-bar inheritance from min-pattern-bars, not max).
- Pad-record format — phones24's parser had wrong byte offsets; corrected by diffing real backups (memory entry confirms 2026-04-25 verification).
- SysEx integer-vs-string encoding asymmetry — device emits ints in responses but rejects int writes.

**M4L device + LiveAPI quirks**:
- `fix(m4l):` BOUNCE button + sf_forge spawn (5 bugs caught in UAT)
- Drop write to read-only `Clip.length` — the LOM accepts the write silently, but produces jsliveapi noise.
- UI button-stack pixel-shift regressions (Live version drift)
- Pill colors + Ableton palette migration for legacy presets
- Arrangement-view loader honoring padded chunks + correct LOM units (`1ef7d5a`)

**Clip export math**:
- Loop-region modulo wrap-around (loop_end > source length needs modulo)
- BPM-derived `seconds_per_beat` vs `source_duration / length_beats` (the in-memory `feedback_clip_slice_timing_math.md` records this lesson)

**Curation algorithm**:
- Outlier filter regression (`fix(curation):` chain)
- `section_stratified_select` returning paths that pointed at deleted temp dirs

### G.2 — Memory-file pain signals (from `MEMORY.md` entries)

Patterns that ship as silent failures unless the harness catches them:

| Memory entry | Failure mode | What a harness should check |
|---|---|---|
| `feedback_beat_this_optional_extra` | venv missing `[beat]` extra → silent librosa-only fallback | Pre-flight extra check; fail loud |
| `feedback_ep133_probing_safety` | Speculative SysEx fileId opens wedge the device | Whitelist file IDs; never speculate in tests |
| `project_ep133_pad_record_correct` | phones24 parser had wrong byte offsets; only caught by byte-diff of real backups | Round-trip: real .ppak → parse → re-pack → byte-diff |
| `feedback_continuous_loop_playback` | `loop_*` is TRIM not LOOP on EP-133 | Document mental-model in spec; semantic test |
| `feedback_clip_slice_timing_math` | Use `60/warp_bpm`, not `source_duration/length_beats` | Unit test on clip export at non-4/4 |
| `feedback_arrangement_clip_lom` | warp_bpm read-only, end_time not writable, marker units flip with warping | Mock the read-only-ness in the LiveAPI mock (writes silently dropped) |
| `feedback_audit_trail_for_harness_evolution` | Audit emission pays for itself across debugging AND verifier-hit-rate | NDJSON-emit every transform |
| `feedback_lom_param_ranges` | Native device params 0-1, macros 0-127, OutputTrim inverted | Schema-validate ranges in tests |
| `feedback_test_deploy_discipline` | Debug in standalone Max first, deploy via installer | Add a test that the installer Tier-1 layout matches expected |
| `feedback_rebuild_amxd_before_pr` | PR shipped stale .amxd because rebuild was forgotten | Pre-merge check: grep .amxd for expected JS module names |

### G.3 — Tests that exist BECAUSE of a past regression (the most valuable ones)

Looking at recent commits, regression-driven tests cluster on:
- **`test_prechop.py`** — silence-pad off-by-one, pre-source negative-target, chunk-index 0-vs-1. Test file modified alongside `fix(prechop):` commits.
- **`test_m4l_export_clips.py`** — 11 round-trip tests added per memory. Each one bound to a bounce-flow regression (loop wrap, BPM math, warp markers).
- **`tests/ep133/test_song_format.py`** + **`test_song_synthesizer.py`** — added during the multi-commit byte-format chain. Round-trip via in-Python parser.
- **`test_tempo_reconciler.py`** — added after the multi-source reconciler work.

**The pattern is healthy.** Almost every shipped fix on `main` lands with a test. The gap is M4L-side: regressions in `stemforge_loader.v0.js` and `sf_ui.js` don't have tests alongside their fixes because there's no test-harness for those files yet. The configurator will share that gap unless Phase 0.5 closes it.

---

## Appendix — Things I verified vs. things I sourced from agent reports

I verified directly:
- `tests/` test file list (`ls tests/test_*.py`)
- `tests/ep133/` test file list and fixture dir contents
- Existence of `tests/ep133/fixtures/reference.ppak` and the 30 `kick_*.syx` captures
- `v0/tests/` file list, `conftest.py`, `README.md`
- `pyproject.toml` pytest + mypy config
- `.pre-commit-config.yaml` content
- `.github/workflows/ci.yml` jobs (lint, test, smoke-build-als/amxd)
- `feat/harness-patterns` is 128 commits behind main and contains only the agent-role files
- `EXPORT_CONFIGURATOR_PLAN_v3.md` does not exist in the repo
- `v0/interfaces/ndjson.schema.json` — formal JSON Schema draft-07, defines 7 event types
- `v0/interfaces/device.yaml` and `v0/interfaces/tracks.yaml` exist
- `v0/src/maxpat-builder/` files (build_amxd, builder, amxd_pack, etc.)
- LiveAPI users in `v0/src/m4l-js/` (grep)

I sourced from agent reports (cross-checked against memory + spec docs but not every line of the underlying file):
- LOC counts of individual JS modules (these are approximate)
- The exact LOM properties each JS module reads/writes
- The internal contents of `tests/js_mocks/max_api.js`'s mock implementations
- Details of `stemforge/cli.py` subcommand internals (verified against in-progress diff and the `--help` flags I saw)

I did **not** verify:
- Specific commit hashes that the agents named in their reports — I removed those from this bundle and described patterns instead
- The exact contents of memory files beyond the index in `MEMORY.md`
- The external "M4L harness v1" at `~/raindog/harness/quickstarts/max-plugin/`
- Whether `v0/src/maxpat-builder/tests/` has the byte-identical-rebuild caveat I described (the agent reported it; I didn't open the test file myself)

If the chat-Claude needs ground truth on any of those, ping back with the specific question.
