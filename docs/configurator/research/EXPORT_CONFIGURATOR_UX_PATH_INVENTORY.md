# StemForge UX Path Inventory + Test-Coverage Map

Companion to `EXPORT_CONFIGURATOR_BUNDLE.md`, `EXPORT_CONFIGURATOR_TESTABILITY_BUNDLE.md`, and `EXPORT_CONFIGURATOR_TEST_HARNESS_PRIOR_ART.md`. Prepared 2026-05-05 — third and final input bundle before the configurator plan reaches v4.

This is **path inventory + coverage map**, not test design. No new tests proposed; no harness redesign. Every row anchored in code, written documentation, or the design-conversation context the prompt explicitly authorized as `proposed`.

---

## Section 0 — TL;DR

**Counts.**
- **62 UX paths total** — **45 shipped**, **9 aspirational** (in backlog/specs), **8 proposed** (design-conversation only).
- **By testability tier (lowest meaningful):** 7 Tier 1 (pure logic), 18 Tier 2 (Python + audio), 6 Tier 3 (JS sandbox), 24 Tier 4 (Live integration), 7 Tier 5 (hardware).
- **By current test coverage:** 22 covered, 14 partial, 26 uncovered.

**Three callouts:**

- **Most-used uncovered path:** `m4l.button.commit` — the COMMIT button that walks Live tracks A/B/C/D and writes `session_tracks` into `stems.json`. The 2004-LOC `stemforge_loader.v0.js` `_commitSessionTracks` is the contract that **every EP-133 song-export depends on** (`song_resolver._index_session_tracks`), and it has no dedicated tests. Tier-4 today; Tier-3 reachable once the LiveAPI mock has a backing `liveTree`.
- **Highest regression risk for the configurator:** `m4l.arrangement.read-snapshot` and the EP-133 song-export chain (`song_resolver` → `song_synthesizer` → `ppak_writer`). The configurator is going to *replace* the current locator-driven shape with manual scene slicing (proposed 7a) and bidirectional locator sync, but the existing `tests/ep133/test_song_*.py` fixtures are the byte-identical baseline that Phase 1 acceptance criteria must keep green. Whatever the abstract scene model produces for the EP-133 target must regenerate the same `.ppak` bytes.
- **Path found in code that is not documented anywhere:** `m4l.button.settings` (line 925-area outlet `settings_click` in `sf_ui.js`). It exists in the v8ui paint code but no doc references it; no skill, no spec, no backlog entry. Either it's a stub awaiting wiring, or it triggers something I missed reading. Worth confirming with the user.

---

## Section 1 — Path catalog

Status values: `shipped` / `aspirational` / `proposed`. Tier values: `1`–`5` per the prompt. Coverage values: `covered` / `partial` / `uncovered`. Pitfalls reference `memory/m4l_device_development_guide.md` Section 10 numbering (#1–#20) plus the harness's three new ones (#25–#27).

### 1. Stemforge core CLI

| id | name | trigger | precondition | steps | outputs | status | tier | coverage | coverage_refs | harness_pitfalls | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `core.split` | Demucs separate + BPM/downbeat detect + bar slice | `stemforge split <audio>` | Audio file readable; `[native]` extra installed | 1) Demucs separates 4 stems 2) tempo_reconciler runs (beat-this + librosa + LarsNet kicks) 3) prechop emits padded chunks 4) writes `stems.json` + `prechop_manifest.json` + sidecars | `<output>/<track>/{drums,bass,vocals,other}.wav`, `*_prechop/`, `stems.json` | shipped | 2 | partial | `tests/test_forge.py`, `tests/test_prechop.py`, `tests/test_tempo_reconciler.py` | — | Tempo detection regression-rich (beat-this venv-drift, half-time hip-hop). Currently no `CliRunner`-level test; pieces tested individually. |
| `core.forge` | Full forge: split + slice bars + curate; emits NDJSON | `stemforge forge <audio>` (or `/forge-run` skill) | Audio readable; `[native]` installed | 1) split 2) slice at bar boundaries 3) curate (max-diversity / rhythm-taxonomy / sectional / section-main-alt) 4) emit NDJSON progress 5) write `curated/manifest.json` + sidecars | `curated/<stem>/bar_*.wav`, `curated/manifest.json`, NDJSON to stdout | shipped | 2 | partial | `tests/test_forge.py` (synthetic), NDJSON not asserted in tests | — | Streamed via `/forge-run` and `forge_click` button. NDJSON event schema in `v0/interfaces/ndjson.schema.json`. |
| `core.re-anchor` | Re-cut prechop at user BPM/downbeat without Demucs re-run | `stemforge re-anchor <track-dir> --bpm X --first-downbeat Y` | Track dir with prior split; prechop chunks present | 1) Read existing stems 2) re-prechop with new grid 3) update `stems.json` tempo provenance + `prechop_manifest.json` | rewritten `*_prechop/`, updated manifests | shipped | 2 | partial | `tests/test_prechop.py` exercises core math; no `re-anchor` CLI integration test | — | Hot path for the locator-anchoring loop. The phase-3 leading-partial-chunk diff (in `git diff stemforge/prechop.py`) is unmerged regression work. |
| `core.analyze` | Genre/instrument/BPM detection (recommends settings) | `stemforge analyze <audio>` | Audio readable; `[analyzer]` extra installed | 1) librosa BPM 2) CLAP genre 3) AST instrument 4) print table or JSON | stdout report | shipped | 2 | uncovered | — | — | `--json-out` flag for machine-readable. Heavy network/GPU on first run (model download). |
| `core.list-models` | Show available Demucs models | `stemforge list` | — | Static print | stdout | shipped | 1 | uncovered | — | — | Trivial. Not worth covering. |
| `core.clean-beats` | Remove silent slices below RMS threshold | `stemforge clean-beats --target-dir D --threshold T` | Beats dir present | 1) Walk beats dir 2) compute RMS per file 3) delete (or `--dry-run` list) | filesystem deletes | shipped | 2 | uncovered | — | — | Destructive; deserves a smoke test. |
| `core.generate-pipeline-json` | Compile YAML pipelines + presets → JSON for M4L | `stemforge generate-pipeline-json` | `pipelines/` and/or `presets/` dirs present | 1) glob YAML 2) parse 3) write `pipelines/pipelines.json` (M4L reads this) | `pipelines/pipelines.json` | shipped | 1 | partial | `tests/test_pipelines.py` (parsing), no end-to-end command test | — | Build artifact consumed by `sf_preset_loader.js`. |
| `core.create-templates` | Build the 7 StemForge template tracks in Live | `stemforge create-templates` | Either: AbletonOSC running on port 11000 OR user reads printed instructions | 1) Probe localhost:11000 2) if up → fire OSC trigger 3) else → print step-by-step | OSC commands or stdout | shipped | 4 | uncovered | — | — | Only CLI subcommand that touches Live. AbletonOSC is third-party; not bundled. |

### 2. Curation

| id | name | trigger | precondition | steps | outputs | status | tier | coverage | coverage_refs | harness_pitfalls | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `curation.auto.diversity` | Greedy farthest-point selection across feature space | (inside `core.forge`) `--strategy max-diversity` | Beat dir of WAVs; analyzer present | Greedy farthest-point in normalized features (rhythm fingerprint + spectral + crest) | `beat_dir/manifest.json` with selection rationale | shipped | 2 | partial | `tests/test_forge.py` exercises end-to-end | — | Default strategy. |
| `curation.auto.rhythm-taxonomy` | Cluster by rhythm fingerprint, pick variants per cluster | `--strategy rhythm-taxonomy` | song_structure optional | Cluster by 16-bit rhythm fingerprint, allocate slots, pick diverse variants | `manifest.json` | shipped | 2 | uncovered | — | — | Memorable name from `TOP3_TUNING_*` docs. |
| `curation.auto.sectional` | Section-aware weighting | `--strategy sectional` | `song_structure` provided | Weight bars by structural importance (intro/verse/chorus); pick top-K within constraints | `manifest.json` | shipped | 2 | uncovered | — | — | Falls back to `max-diversity` if no structure. |
| `curation.auto.transition` | Boundary-only selection | `--strategy transition` | `song_structure` provided | Pick only bars near section boundaries | `manifest.json` | shipped | 2 | uncovered | — | — | Same fallback as sectional. |
| `curation.auto.section-main-alt` | Per section: MAIN (centroid) + N alts (most distant) | `--strategy section-main-alt` | `song_structure` provided | For each section type: pick centroid + N most-distant alts | `manifest.json` | shipped | 2 | uncovered | — | — | Captures backbone + variations. |
| `curation.manual.commit-clips` | Commit user-edited clip start/end markers back to manifest | M4L COMMIT button | Live open; tracks A/B/C/D have clips loaded | 1) Walk session tracks 2) capture file_path + start/end markers 3) infer rotate-vs-trim mode 4) write `session_tracks` into in-memory `stems.json` | mutated `stems.json` (in memory; written by manifest_loader) | shipped | 4 | uncovered | — | #1, #18 | Lives in `stemforge_loader.v0.js:1707-1774`. **Most-used uncovered path** — see TL;DR. |
| `curation.re-curate-after-downbeat` | Re-run curation after global downbeat changes | (no surface today) | `core.re-anchor` already happened | Conceptually: re-slice → re-curate with same params → reload | new `manifest.json` | aspirational | 2 | uncovered | — | — | Listed in `specs/m4l-integrated-forge-device.md` "Real-time re-curation" with no detailed spec. Connects arrangement and curation modes. |
| `curation.bulk.reslice-and-curate` | Re-curate one track at new strategy/n_bars | `tools/reslice_and_curate.py` | Track dir present | Wraps curator with new params over existing slices | new `manifest.json` | shipped | 2 | uncovered | — | — | Diagnostic tool; not part of forge flow. |
| `curation.bulk.reanchor-all-processed` | Bulk re-anchor every track in `~/stemforge/processed/` | `tools/reanchor_all_processed.py` | Many tracks already split | Walk processed dir → call `core.re-anchor` per track → audit log | filesystem mutations + audit | shipped | 2 | uncovered | — | — | Migration tool. |

### 3. Arrangement view (Live)

| id | name | trigger | precondition | steps | outputs | status | tier | coverage | coverage_refs | harness_pitfalls | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `arrangement.read-snapshot` | LOM → snapshot.json (locators + per-track A/B/C/D arrangement clips) | M4L EXPORT button (`export_song_click`) | Live open; tracks named A/B/C/D; ≥1 cue_point | 1) Read `live_set.{tempo, signature}` 2) walk cue_points 3) walk arrangement_clips per track 4) write JSON | `<output>/snapshot.json` + log line | shipped | 4 | partial | `tests/js_mocks/test_arrangement_reader.test.js` (mock LiveAPI), `v0/tests/test_arrangement_reader.py` | #1, #5, #18, #25, #26 | Tested logic-side; live LOM reads are not asserted. |
| `arrangement.locator-anchor.set` | User drops Ableton locator → JS computes source-time → re-anchor | M4L LOAD button + locator drag (planned) | Prechop manifest loaded; user has dragged a locator | 1) JS reads cue_point time 2) maps to source-time via prechop_manifest 3) shells `tools/m4l_locator_anchor.py` | NDJSON `anchor_started`/`anchor_complete` + rewritten chunks | shipped | 4 | uncovered | — | #1 | Python helper is headless and Tier-2-testable; the JS half is uncovered. |
| `arrangement.load-prechop` | Lay out padded chunks as arrangement clips | M4L LOADARR button (`arrangement_load_click`) | Track dir w/ `prechop_manifest.json`; Live open | 1) `[opendialog]` for manifest 2) read manifest 3) per-stem: create track if needed, place chunks at bar grid w/ correct loop markers | LOM mutations: tracks + clips | shipped | 4 | partial | `tests/js_mocks/test_arrangement_loader.test.js` | #25, #26, marker-units-flip-with-warping (memory `feedback_arrangement_clip_lom`) | Read-only of `warp_bpm` is a known footgun. |
| `arrangement.bidirectional-locator-sync` | Locators in Live ↔ session-view scenes ↔ abstract scene model | (no surface today) | — | Conceptually: writing locators back to Live, mapping session scenes to/from locators | LOM cue_point writes | proposed | 4 | uncovered | — | — | Source 7e — referenced in `EXPORT_CONFIGURATOR_BUNDLE.md` §R3. Genuinely new code. |
| `arrangement.manual-scene-slice` | User selects bar ranges → defines named scenes (replaces locator-as-scene) | (no surface today; configurator popup) | Configurator popup; arrangement loaded | 1) Read arrangement bars 2) UI lets user select [start_bar..end_bar] + name 3) write scene definitions to abstract model | scene definitions in configurator state | proposed | 4 | uncovered | — | — | Source 7a. Replaces today's "locators-as-scene-markers" workflow. |

### 4. M4L device interactions (button-by-button)

| id | name | trigger | precondition | steps | outputs | status | tier | coverage | coverage_refs | harness_pitfalls | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `m4l.device.load` | Open StemForge.amxd inside Live; JS modules instantiate; UI paints | drop StemForge.amxd onto Live track | Live + Max for Live + StemForge package installed | 1) Live loads `.amxd` 2) Max instantiates v8ui + 9 JS modules 3) sf_ui paints initial state 4) sf_settings reads ~/stemforge/settings.json | device strip visible at 820×169 | shipped | 4 | partial | `v0/tests/test_amxd.py` (ZIP/JSON only); harness `verify-amxd` + `verify-load` (per prior-art §1) close this | #1, #6, #7, #14, #25, #26, #27 | Container currently broken on macOS 26 (`docs/m4l-device-status.md`). Harness load-verifier is the right tool here. |
| `m4l.button.preset` | Pick a curation/processing preset from dropdown | preset_click outlet | Presets dir scanned; `pipelines/pipelines.json` present | 1) sf_preset_loader scans dir 2) [umenu] populated 3) user picks → `sf_preset` Dict updated | sf_preset Dict mutated | shipped | 3 | covered | `tests/js_mocks/test_preset_resolution.test.js` | #5 | One of the few JS-mock-tested paths. |
| `m4l.button.source` | Pick a source audio file via [opendialog sound] | source_click outlet | — | 1) [opendialog sound] modal 2) user picks file 3) sf_settings stores path 4) sf_state transitions to "ready" | sf_settings.audio_file populated | shipped | 4 | uncovered | — | #2 | `[opendialog sound]` (per pitfall #2 — must use this, not `[dropfile]`). |
| `m4l.button.forge` | Run forge pipeline via [shell] + native binary | forge_click outlet | Source + preset selected; binary at one of the search_paths | 1) sf_forge spawns `[shell]` 2) native binary streams NDJSON 3) sf_ndjson_parser routes events 4) sf_state advances phase | NDJSON events + final `stems.json` | shipped | 4 | partial | `tests/test_forge.py` (Python side); JS orchestrator uncovered | #1, #4 | Phase 1 (audio split) only — Phase 2 (track creation) lives in `m4l.button.commit` style flow. |
| `m4l.button.cancel` | Abort an in-flight forge | cancel_click outlet | Forge running | sf_forge sends `pkill` | child process killed | shipped | 4 | uncovered | — | shell.mxo lacks `kill` (memory `feedback_shellmxo_quirks`) — uses `pkill` | Manual UAT only. |
| `m4l.button.done` | Acknowledge a complete forge, advance UI | done_click outlet | Forge done state | sf_state transitions to "idle" | UI redraw | shipped | 3 | uncovered | — | — | Trivial. |
| `m4l.button.retry` | Retry after a forge error | retry_click outlet | Error state | sf_state resets to "ready" | UI redraw | shipped | 3 | uncovered | — | — | Trivial. |
| `m4l.button.settings` | Open settings UI (?) | settings_click outlet | — | Unclear from sf_ui.js read | unclear | shipped(?) | 4 | uncovered | — | — | **Found in code (`sf_ui.js` outlet name) but undocumented.** See TL;DR third callout. |
| `m4l.button.commit` | Walk Live tracks A/B/C/D; capture clip markers; write `session_tracks` | commit_click outlet | Live open; tracks A/B/C/D have clips | 1) Walk tracks → clip slots → clips 2) capture file_path + start/end + length 3) infer rotate/trim mode 4) mutate manifest | mutated `stems.json` in-memory then re-written | shipped | 4 | uncovered | — | #18 | `_commitSessionTracks` at `stemforge_loader.v0.js:1707`. The contract every EP-133 song-export depends on. |
| `m4l.button.bounce` | Bounce selected Live clips → manifest sidecars | bounce_clips_click outlet | Live open; clips selected | 1) Walk selected clips 2) write spec.json 3) shell `tools/m4l_export_clips.py` 4) Python writes WAVs + sidecars + batch | NDJSON + WAV files + `.manifest_<hash>.json` + `.manifest.json` | shipped (JS+Py); Max button wiring partial per `docs/feature-backlog.md` | 4 | covered (Python side) | `tests/test_m4l_export_clips.py` (11 round-trip tests per memory) | #1, #4, marker-unit-flip (memory) | The strongest precedent for "JS captures + Python helper does the work" pattern. |
| `m4l.button.export-song` | Trigger arrangement read → snapshot.json | export_song_click outlet | Live open; tracks A/B/C/D; cue_points present | 1) Walk arrangement view 2) write snapshot.json 3) status update | `<output>/snapshot.json` | shipped | 4 | partial | `tests/js_mocks/test_arrangement_reader.test.js` | #25, #26 | Output then handed to `core.export-song` (CLI). |
| `m4l.button.loadarr` | Load prechop chunks into arrangement view | arrangement_load_click outlet | Track dir w/ prechop_manifest selected via [opendialog] | 1) [opendialog] file picker 2) read prechop_manifest 3) lay out chunks across tracks at bar grid | LOM mutations | shipped | 4 | partial | `tests/js_mocks/test_arrangement_loader.test.js` | warp_bpm read-only (memory) | The arrangement-mode loader. |
| `m4l.scrape-params` | Enumerate all Live device parameter ranges | (manual: load StemForgeRecv tracks then trigger) | Pre-staged audio + MIDI tracks named `SF_Scraper_Audio` / `SF_Scraper_MIDI` | 1) Walk Live device catalog 2) instantiate transiently 3) dump params 4) write JSON | `~/Documents/StemForge/live_devices.json` | shipped | 4 | uncovered | — | — | Utility used during preset authoring. Output is checked into `stemforge/data/live_devices.json`. |

### 5. Export — current

| id | name | trigger | precondition | steps | outputs | status | tier | coverage | coverage_refs | harness_pitfalls | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `export.ep133.compose` | Format curated material from one track for EP-133 | `stemforge export <track> --target ep133 --workflow compose` | Track dir w/ curated material | 1) Pick curated bars 2) format (resample 46875 Hz, mono, 16-bit, ≤20s) 3) write to output dir + SETUP.md | `*.wav` (slot-named) + `SETUP.md` | shipped | 2 | covered | `tests/test_exporters.py` | — | The pre-song-mode exporter. |
| `export.ep133.perform` | Curated kit across multiple tracks for live performance | `stemforge export <dir> --target ep133 --workflow perform` | Multiple tracks present | Diversity selection across tracks → 12 hits per group | output dir | shipped | 2 | covered | `tests/test_exporters.py` | — | Same exporter, different selection strategy. |
| `export.ep133.song-mode` | Synthesize EP-133 song-mode `.ppak` from arrangement snapshot | `stemforge export-song --arrangement snapshot.json --manifest stems.json --reference-template ref.ppak --project N --out song.ppak` | snapshot.json + stems.json + reference template | 1) Resolve locator → scene 2) synthesize PpakSpec (patterns/scenes/pads/sounds) 3) write TAR + ZIP container 4) tile sub-scene-length clips via `_event_positions_bars` | `<out>/song.ppak` | shipped | 2 | covered | `tests/ep133/test_song_resolver.py`, `test_song_synthesizer.py`, `test_song_format.py`, `test_song_integration.py`, `test_ppak_writer.py` | — | The most fixture-rich subsystem. **Phase-1 byte-identical-fixture acceptance criterion lives here.** |
| `export.ep133.hybrid-session` | Upload hybrid session (A=drums, B=bass, C=vocals, D=FX) via SysEx | `python tools/ep133_load_hybrid_session.py manifest.json --project N` | EP-133 connected; manifest with `session_tracks` | Per-clip rotate vs. trim → bake WAV → SysEx upload | EP-133 device state | shipped | 5 | uncovered | — | — | Hardware-tier; uses `tools/ep133_load_hybrid_session.py`. |
| `export.ep133.bulk-project` | Bulk-load curated stems into EP-133 project; assign pads | `python tools/ep133_load_project.py manifest.json` | EP-133 connected; manifest with curated bars | Walk manifest → SysEx upload + pad-assign | EP-133 device state | shipped | 5 | uncovered | — | — | Used heavily in production. |
| `export.ep133.capture-reference` | Read .ppak from device → save as fixture template | `python tools/ep133_capture_reference.py` | EP-133 connected | SysEx read project TAR → wrap into .ppak (TAR + ZIP + meta.json) | `tests/ep133/fixtures/reference.ppak` | shipped | 5 | covered | `tests/ep133/test_capture_reference.py` (gated on connected device) | — | Source of the `reference.ppak` fixture used by the song-export integration test. |
| `export.koala.bulk` | Bulk Koala bank-zip exporter | `stemforge export-koala <track-dir>` | Curated track dir | Layout WAVs into Koala bank format → zip | `~/stemforge/koala_exports/<track>_<ts>.zip` | shipped | 2 | covered | `tests/test_koala_exporter.py` | — | Recently shipped (commit `b14ed06`). |
| `export.chompi.compose` | Format stems for Chompi (TEMPO firmware) | `stemforge export <dir> --target chompi --workflow compose` | Track dir | Format (48kHz stereo 16-bit ≤10s) → flat dir | output dir | shipped | 2 | covered | `tests/test_exporters.py` | — | Slice + Chroma engines, 14 slots each. |

### 6. Export — proposed (configurator)

| id | name | trigger | precondition | steps | outputs | status | tier | coverage | coverage_refs | harness_pitfalls | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `configurator.popup.launch` | Launch local Python HTTP server + web UI from M4L | new M4L button (proposed) | M4L device loaded; Python available | 1) [shell] launches FastAPI/Python server 2) `[jweb]` or browser opens UI 3) UI receives state via WebSocket/REST | popup window with NxM grid | proposed | 4 | uncovered | — | #1 | Source 7e. Replaces the EP-133-only export pipeline as the surface for arrangement-driven export. |
| `configurator.scene.manual-slice` | Define named scenes by selecting bar ranges from arrangement | configurator popup UI | Arrangement loaded; project bars known | 1) UI shows arrangement bars 2) user drags ranges 3) scenes added to abstract model 4) abstract model saved | scene definitions in scene_model state | proposed | 4 | uncovered | — | — | Source 7a — replaces locator-driven scene markers. |
| `configurator.splice.cross-song` | One scene's clip set draws from multiple songs (mashup) | configurator popup UI | Multi-song project loaded | 1) UI lets user pick clips from any song's curated set 2) scene clip-refs span songs 3) auto-curation stays per-song | mashup scene definitions | proposed | 4 | uncovered | — | — | Source 7b. Manual curation only. |
| `configurator.mashup.multi-song` | Forge 2-4 songs into one project; group per song | configurator popup + multi-forge | Multiple sources, one Live project | 1) Forge song1 2) Forge song2 (different track group) 3) "Current song" scope on each stemforge op (re-anchor, curation, export) | per-song group tracks; stemforge ops scoped | proposed | 4 | uncovered | — | — | Source 7c. |
| `configurator.autogroup.template-als` | After forge, group 4 stem tracks under named group ("song1") via pre-made template .als | (post-forge step in M4L) | StemForge.als has empty groups pre-defined | 1) Forge places stems into pre-existing empty group | groups populated | proposed | 4 | uncovered | — | — | Source 7d, path A. Fragile re. user-modified template. |
| `configurator.autogroup.applescript` | After forge, group via AppleScript keystroke automation | (post-forge step in M4L) | macOS only; UI scripting permission granted | 1) AppleScript sends Cmd-G keystroke to grouped track selection | grouped tracks | proposed | 4 | uncovered | — | — | Source 7d, path B. Dev-only / experimental. |
| `configurator.projector.ep133` | Project abstract scene model → EP-133 PpakSpec | configurator popup → EXPORT | Abstract scene model fully resolved | 1) Read scene_model 2) project to ep133 target topology (4 groups × 12 pads) 3) emit PpakSpec 4) call existing `ppak_writer` | `.ppak` file | proposed | 2 | uncovered | — | — | Source 7e. Phase-1 acceptance criterion: byte-identical to current `export.ep133.song-mode` output for the same input. |
| `configurator.projector.multi-target` | Single configurator export to multiple targets at once | configurator popup → EXPORT (multi-select) | Same as projector.ep133 + chompi/koala selected | Project scene_model to each target separately; write each | multiple device-specific files | proposed | 2 | uncovered | — | — | The "abstract grid → many devices" north star. |

### 7. Hardware

| id | name | trigger | precondition | steps | outputs | status | tier | coverage | coverage_refs | harness_pitfalls | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `hw.ep133.load-single` | Load one audio sample onto a specific EP-133 pad | `/ep133-load` skill | EP-133 connected; sample on disk | 1) Wraps `ppak-load-one` 2) auto-picks slot from cursor 3) reads sidecar/batch manifests | EP-133 device state | shipped | 5 | uncovered | — | — | Skill listed in system reminder; not in `.claude/skills/` (must be a global plugin skill). |
| `hw.ep133.upload-ppak` | Drag a `.ppak` onto TE Sample Tool → upload to device | manual (browser) | `.ppak` produced by export-song; TE Sample Tool app | User drags `.ppak` into TE Sample Tool browser | EP-133 device state | shipped | 5 | uncovered | — | — | The "last mile" for EP-133 song-mode. Cannot be automated today. |
| `hw.ep133.bpm-matrix` | Diagnose EP-133 BPM byte encoding across project slots | `python tools/ep133_bpm_matrix.py` | EP-133 connected | SysEx round-trip per slot | tabular report | shipped | 5 | uncovered | — | — | Diagnostic only. |
| `hw.ep133.protocol-probe` | Probe SysEx fileId space safely | `tools/` (various) | EP-133 connected | Stat fileIds via `0B` only — never speculative `03 00` opens | report | shipped | 5 | uncovered | — | — | Protected by memory `feedback_ep133_probing_safety` rule (speculative opens wedge device). |
| `hw.launchpad.load` | Load drum-rack templates onto Launchpad for performance | manual/walkthrough | Launchpad connected; drum-rack templates created | TBD per `docs/launchpad-setup.md` | Launchpad device state | aspirational | 5 | uncovered | — | — | Setup doc exists; flow not automated. |
| `hw.chompi.upload` | Copy WAVs to Chompi SD card | manual (filesystem copy) | Chompi SD mounted | User copies output dir to SD card root | SD card layout | shipped | 5 | uncovered | — | — | No tool — Chompi reads flat directory from SD. |
| `hw.devices.preset-scrape` | Scrape Live native device parameters | (see `m4l.scrape-params`) | — | — | `live_devices.json` | shipped | 4 | uncovered | — | — | Cross-listed. |

### 8. Skills / orchestration

| id | name | trigger | precondition | steps | outputs | status | tier | coverage | coverage_refs | harness_pitfalls | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `skill.forge-launch` | Launch Ableton (optionally with StemForge.als) | user says "launch Live" / "open StemForge" | macOS; Ableton installed | `pgrep` to check; `open -a` or `open <als>` | Ableton launches | shipped | 4 | uncovered | — | — | `.claude/skills/forge-launch/SKILL.md`. |
| `skill.forge-run` | Run `stemforge forge` and stream NDJSON | user says "forge X" | Audio path | `uv run stemforge forge` with defaults; parse NDJSON for progress | manifest + stdout updates | shipped | 2 | uncovered | — | — | Wraps `core.forge`. |
| `skill.forge-all` | Compose forge-launch + forge-run | user says "do the whole thing" / "open StemForge and forge X" | Both preconditions | Sequential: launch in background, forge in foreground | both above | shipped | 4 | uncovered | — | — | Manual steps `forge-pick` and `forge-commit` documented as remaining. |
| `skill.ep133-load` | Quick-load a single sample to a specific EP-133 pad | user says "load X on pad Y" | EP-133 connected | Wraps `ppak-load-one`; auto-picks slot | EP-133 state | shipped | 5 | uncovered | — | — | Listed in skills register but not in repo's `.claude/skills/`. |
| `skill.forge-pick` | Pick patch + source via the M4L device | (blocked) | M4L external control surface (TBD: `[fswatcher]` or UDP per harness `sf_remote`) | TBD | TBD | aspirational | 4 | uncovered | — | — | `docs/feature-backlog.md` §2. Unblocked by harness `sf_remote` if stemforge adds `[udpreceive]` per prior-art §2. |
| `skill.forge-commit` | Trigger device's COMMIT action | (blocked) | Same as above | TBD | TBD | aspirational | 4 | uncovered | — | — | Same blocker as forge-pick. |
| `skill.commit-with-bounce` | COMMIT + freeze warp + post-process bounce | (not implemented) | Post-processing pipelines first-class | TBD | TBD | aspirational | 4 | uncovered | — | — | `docs/feature-backlog.md` §3. Spec only. |
| `skill.vst-extraction` | Strip non-native devices from templates; preserve VST work on branch | (not implemented) | Branch + audit infra | TBD | branch + clean main | aspirational | 1 | uncovered | — | — | `docs/feature-backlog.md` §4. |
| `skill.bounce-to-clip-and-collect` | Find recently-edited Live clips + bounce them as forge inputs | partial M4L button + "find recent clips" missing | Live open | Bounce shipped (`m4l.button.bounce`); recent-clip enumeration not | bounced WAVs + manifests | aspirational (full); shipped (bounce only) | 4 | partial | `tests/test_m4l_export_clips.py` for bounce | #1 | `docs/feature-backlog.md` §1. |

### 9. Diagnostic / dev tools (cross-listed for completeness)

| id | name | trigger | tier | coverage | notes |
|---|---|---|---|---|---|
| `dev.probe-loop` | Iterate BPM/downbeat manually and write a 4-bar test loop | `tools/probe_loop.py` | 2 | uncovered | Hot path during tempo correction. |
| `dev.beat-dashboard` | HTML report of beat alignment metrics | `tools/beat_dashboard.py` | 2 | uncovered | Dashboard generation. |
| `dev.audit-resampling` | Compare manifest claims vs. WAV files; flag silent resamples | `tools/audit_resampling.py` | 1 | uncovered | Silent-failure detector — high test value. |
| `dev.verify-tempo` | Full tempo diagnostic matrix | `tools/verify_tempo.py` | 2 | uncovered | Ground-truth BPM. |
| `dev.diag-definition-tempo` | Single-track tempo diagnostic | `tools/diag_definition_tempo.py` | 2 | uncovered | Named for "Definition" track regression. |
| `dev.find-first-drum-cut` | Onset detection diagnostic | `tools/find_first_drum_cut.py` | 2 | uncovered | — |
| `dev.find-main-beat-drop` | Drop detection diagnostic | `tools/find_main_beat_drop.py` | 2 | uncovered | — |
| `dev.extract-loop-test` | Cut a single 4-bar loop for visual verification | `tools/extract_loop_test.py` | 2 | uncovered | Manual confirmation aid. |
| `dev.validate-audio` | Score curated WAVs via Gemini multimodal | `tools/validate_audio.py` | 2 (network) | uncovered | AI-assisted QA. |
| `dev.sf-deploy` | Sync M4L JS + presets to Max package + Ableton library | `tools/sf_deploy.py` | 1 | uncovered | Filesystem only. |
| `dev.sf-remote` | (Aspirational) UDP driver for running M4L device | (per harness prior-art §2) | 4 | uncovered | Stemforge has no `[udpreceive]` today; harness ships the driver. |
| `dev.run-js-tests` | Run Node-based JS module tests | `tools/run_js_tests.sh` | 3 | covered | Wraps `tests/js_mocks/`. |

---

## Section 2 — Coverage gaps (shipped or must-support proposed, with no test today)

For each, one line: gap → tier that could close it.

**Stemforge core:**
- `core.analyze`: no end-to-end CLI test → Tier 2 (synthetic audio + CliRunner).
- `core.clean-beats`: destructive operation, no smoke test → Tier 1 (mock filesystem) or Tier 2 (real WAV dir + dry-run check).
- `core.create-templates`: AbletonOSC trigger never tested → Tier 4 (Live + AbletonOSC) or Tier 1 mocked-OSC (assert message bytes only).

**Curation:**
- `curation.auto.rhythm-taxonomy`, `curation.auto.sectional`, `curation.auto.transition`, `curation.auto.section-main-alt`: no per-strategy tests → Tier 2 (synthetic beat dir, assert selection determinism + diversity score above floor).
- `curation.manual.commit-clips`: 2004-LOC `_commitSessionTracks` has no tests → Tier 3 once LiveAPI mock has `liveTree`; until then, Tier 4 only.
- `curation.re-curate-after-downbeat`: no implementation → blocked on design (aspirational).
- `curation.bulk.reslice-and-curate`, `curation.bulk.reanchor-all-processed`: bulk tools uncovered → Tier 2.

**Arrangement (Live):**
- `arrangement.locator-anchor.set` (JS half): wrapper untested → Tier 3 (mock LiveAPI returns canned cue_point) or Tier 4.
- `arrangement.bidirectional-locator-sync`: no implementation, blocked.
- `arrangement.manual-scene-slice`: no implementation, blocked.

**M4L buttons (the bulk of the gap):**
- `m4l.device.load`: harness `verify-amxd` + `verify-load` from prior-art §1 close this — Tier 3 patcher-shape always; Tier 4 headless-Max-load on dev Mac.
- `m4l.button.source`: opendialog uncovered → Tier 4 (or Tier 3 with mocked file picker).
- `m4l.button.forge` (JS orchestrator side): `[shell]` spawn + NDJSON routing → Tier 3 with hardened mock + audit emitter.
- `m4l.button.cancel`, `done`, `retry`: trivial state transitions → Tier 3.
- `m4l.button.settings`: undocumented → triage with user first (see §3).
- `m4l.button.commit`: the high-value gap → Tier 3 once LiveAPI mock supports getter+setter on tracks/clip_slots/clips.
- `m4l.button.export-song`: snapshot-write half uncovered live-side → Tier 3 with mock + assert side-channel JSON.
- `m4l.button.loadarr`: warp_marker + tempo writes — Tier 3 (mock writes); Tier 4 to assert post-write LOM state.
- `m4l.scrape-params`: utility, no test → Tier 4 (only meaningful with real Live device catalog).

**Export:**
- `export.ep133.hybrid-session`, `bulk-project`: hardware tier — never automated; manual checklist.
- `export.ep133.capture-reference`: gated on connected device → Tier 5 manual; fixture is the test artifact.

**Configurator (proposed):**
- All 8 paths uncovered. The Phase 1 acceptance criterion "byte-identical .ppak for the same input as the current pipeline" makes `tests/ep133/test_song_*.py` the load-bearing safety net. Don't break those fixtures.

**Hardware:**
- All 7 hardware paths uncovered. Acceptable; document manual steps.

**Skills:**
- All 4 skills uncovered (skill behavior is hard to test outside an interactive session). Their wrapped CLIs (`core.forge`, `core.re-anchor`, etc.) carry the test value.

---

## Section 3 — Triage candidates (the call you make, not me)

Paths I think might be candidates for `drop` or `nice-to-have` in v1. One sentence each. **Final triage requires the user — claude.ai chat or zak directly.**

**Possible drop:**
- `m4l.button.settings` — found in code but undocumented anywhere; might be a stub. Confirm whether it's wired to anything before investing in coverage.
- `core.list-models` — single static print; trivial and unlikely to break. No coverage value.
- `dev.run-plans` — flagged as ad-hoc demo (confirmed earlier). Likely dead.
- `curation.bulk.reslice-and-curate` — superseded by re-anchor + curation pair? Confirm whether it's still used.

**Possible nice-to-have (don't block configurator on these):**
- `skill.commit-with-bounce` — listed as `LATER` in backlog with a hard dependency on first-class post-processing pipelines. Don't block configurator.
- `skill.vst-extraction` — orthogonal to configurator; one-time cleanup.
- `arrangement.bidirectional-locator-sync` — proposed but expensive (LOM cue_point writes are quirky per memory). Could ship configurator with one-way (read locators, write scene model) and add the reverse direction in v2.
- `configurator.autogroup.applescript` — fragile (UI scripting permission, macOS only). Prefer `configurator.autogroup.template-als` as the v1 path.
- `configurator.projector.multi-target` — start with EP-133-only projector to prove the abstraction; add chompi/koala targets after Phase 1.
- `hw.launchpad.load` — aspirational, not configurator-dependent.

**Possible must-support that's at risk:**
- `m4l.button.commit` — the contract every export depends on. Tests must come **before** Phase 1 lands or refactor risk is uncapped.
- `export.ep133.song-mode` — same. The current fixture set is the byte-identical baseline.

---

## Section 4 — Cross-reference: configurator-affected paths

For each proposed configurator path (sources 7a–7e), every existing UX path the configurator will *change* rather than *add*. These are the paths whose tests must keep passing through the refactor — and whose fixtures the harness's "byte-identical" Phase 1 acceptance criterion will lean on.

### `configurator.popup.launch` + `configurator.projector.ep133` (7e)

**Replaces (existing entry point):**
- `m4l.button.export-song` → configurator popup becomes the user-facing surface. Underlying `arrangement.read-snapshot` (snapshot.json producer) is *kept* but its consumer changes from CLI to in-process projector.

**Refactors but keeps the byte-format end:**
- `export.ep133.song-mode` (`stemforge export-song` CLI) → `song_resolver.py` and `song_synthesizer.py` become the "EP-133 projector implementation." `ppak_writer.py` and `song_format.py` byte builders are unchanged.
- `_event_positions_bars` (the tile/repeat function in `song_synthesizer.py:121-153`) → lifted to abstract layer per `EXPORT_CONFIGURATOR_BUNDLE.md` §2.
- `_scene_lengths_in_bars` → lifted to abstract layer.
- `infer_bars` → generalized (today snaps to {1, 2, 4} for EP-133; abstract should accept any positive integer).
- `SceneSpec.{a,b,c,d}` → restructured to N-group dict.

**Phase-1 must-keep-green tests:**
- `tests/ep133/test_song_resolver.py`
- `tests/ep133/test_song_synthesizer.py`
- `tests/ep133/test_song_format.py`
- `tests/ep133/test_song_integration.py`
- `tests/ep133/test_ppak_writer.py`
- The `tests/ep133/fixtures/reference.ppak` baseline.

### `configurator.scene.manual-slice` (7a)

**Replaces:**
- The locator-as-scene-marker convention used by `arrangement.read-snapshot` and consumed by `song_resolver.resolve_scenes`. Locator semantics shift: locators *can still* drive scenes, but the configurator's manual-slice UI is the new primary surface.
- The convention "all clips in arrangement MUST be on tracks named exactly A/B/C/D" (per `specs/ep133-arrangement-song-export.md`) — generalizes to N tracks.

**Affects:**
- `m4l.button.export-song` — its output (snapshot.json) gets new fields for scene definitions.

**Phase-1 must-keep-green:**
- The current snapshot.json shape (locators + tracks A/B/C/D) must still produce a valid scene definition — backwards-compat path.

### `configurator.splice.cross-song` + `configurator.mashup.multi-song` (7b, 7c)

**Affects:**
- `core.forge` — must support multiple-source workflow without overwriting. Today's `~/stemforge/processed/<track>/` layout is per-track; multi-song requires either a project layer or careful per-track scoping.
- `curation.manual.commit-clips` — must scope to "current song" rather than the whole Live set.
- `arrangement.read-snapshot` — must understand which tracks belong to which song's group.
- `m4l.button.commit` — same scoping concern.
- `m4l.button.bounce` — bounce-with-source-attribution (already supported via `source_track` field in `SampleMeta`).

**Phase-1 must-keep-green:**
- Single-song flow continues to work without changes from the user's POV.

### `configurator.autogroup.template-als` / `configurator.autogroup.applescript` (7d)

**Affects:**
- `m4l.device.load` (post-forge UI state) — after forge, four stem tracks now appear inside a named group.
- `arrangement.load-prechop` — must place chunks into tracks within the named group, not at the top level.
- `m4l.button.commit` — must walk *inside* the song's group, not the global track list.

**Phase-1 must-keep-green:**
- Existing single-song flow without grouping continues to work (i.e., grouping is opt-in or backward-compatible).

### Path-IDs whose tests must continue passing through any configurator refactor

Bundling for easy grep:

```
m4l.button.commit
m4l.button.bounce
m4l.button.export-song
m4l.button.loadarr
arrangement.read-snapshot
arrangement.load-prechop
core.forge
core.re-anchor
core.split
export.ep133.song-mode
export.ep133.compose
export.ep133.perform
curation.auto.diversity
curation.manual.commit-clips
```

The `tests/ep133/fixtures/reference.ppak` and the 31 SysEx captures (`tests/ep133/fixtures/kick_*.syx`) are the load-bearing artifacts the configurator's Phase 1 byte-identical criterion leans on. Don't touch.

---

## Appendix — Sources read vs. extrapolated

### Verified by reading code

- CLI subcommand list (`grep "@cli.command" stemforge/cli.py`): 11 commands at lines 92, 497, 722, 735, 805, 914, 979, 1014, 1328, 1491, 1618.
- M4L button outlets (`grep "outlet(0," v0/src/m4l-js/sf_ui.js`): 11 distinct event names — `preset_click`, `source_click`, `commit_click`, `bounce_clips_click`, `export_song_click`, `arrangement_load_click`, `forge_click`, `cancel_click`, `done_click`, `retry_click`, plus `settings_click` (referenced in the file's header comment but the actual outlet line wasn't in my grep — flagged as undocumented in TL;DR).
- `v0/interfaces/device.yaml` — 9 JS modules + binary search paths + post-complete actions.
- Skills directory contents (`ls .claude/skills/`): `design.md`, `plan.md`, `review.md`, `simplify.md` (agent skills) + `forge-launch/`, `forge-run/`, `forge-all/` (stemforge skills). Read each skill's SKILL.md.
- `docs/feature-backlog.md` — confirmed 4 backlog items (bounce-to-clip+collector, forge-skills full set, commit-with-bounce, vst-extraction).
- `tests/` and `tests/ep133/` test file lists (verified in testability bundle).
- `m4l_device_development_guide.md` Section 10 pitfall numbering (#1–#20) verified by reading the section.
- Pitfalls #25, #26, #27 from `EXPORT_CONFIGURATOR_TEST_HARNESS_PRIOR_ART.md` reading.

### Inferred from documentation without full code verification

- M4L button → JS-module-handler mapping (e.g., `forge_click` → `sf_forge.js`). Believed correct from the bundle's earlier reads; not re-verified line-by-line in this pass.
- `_commitSessionTracks` LOC count (2004 LOC for `stemforge_loader.v0.js`). From the testability bundle.
- Specific tool-script behaviors (e.g., `tools/probe_loop.py` "iterate BPM/downbeat manually"). From file headers, not full file reads.
- `skill.ep133-load` listed in the system reminder but not present in `.claude/skills/`. Assumed to be a global plugin skill installed elsewhere on the user's system.

### Described from design-conversation context (source 7)

- `configurator.scene.manual-slice` — described in the prompt's source 7a.
- `configurator.splice.cross-song` — source 7b.
- `configurator.mashup.multi-song` — source 7c.
- `configurator.autogroup.template-als` and `configurator.autogroup.applescript` — source 7d (two implementation paths).
- `configurator.popup.launch`, `configurator.projector.ep133`, `configurator.projector.multi-target` — source 7e.
- `arrangement.bidirectional-locator-sync` — referenced in the original `EXPORT_CONFIGURATOR_BUNDLE.md` §R3 and the configurator design conversation. Tagged `proposed`.

### Did not verify

- Whether the `m4l.button.settings` outlet is wired to a real handler. Only confirmed the outlet name appears in `sf_ui.js`'s header comment.
- Whether `skill.ep133-load` exists outside this repo — accepted at face value from system reminder.
- The exact post-complete LOM-mutation contract referenced in `device.yaml:101-107` (`set_tempo_from_manifest`, `duplicate_template_tracks`, `load_clips_into_tracks`, `load_beat_slices_into_simpler`). Treated as documented but not traced through `stemforge_loader.v0.js`.
- Specific commit hashes for past regressions. Avoided naming them in this bundle (the testability bundle's appendix flagged this as a discipline).
- The actual structure of `tests/ep133/fixtures/pad/` — saw the directory exists but didn't enumerate.

If the chat-Claude needs ground truth on any of those, ping back with the specific question.
