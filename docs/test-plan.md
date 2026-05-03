# StemForge Programmatic Test Plan

## 1. Executive Summary

- **Test pyramid is JS-sandbox-heavy.** Live cannot run headless; every minute spent fighting that fact returns less coverage than another `module.exports.__test__` shim. ~70 % of M4L logic ships behind those shims already — extend the existing pattern in `tests/js_mocks/` rather than building new infra.
- **One synthesized fixture rules them all.** A `scipy`/`numpy`-generated 8-bar 4/4 stereo loop @ 120 BPM (kick/snare grid + sub-bass + sine-vocal stand-in + percussive "other") is the only credible answer: zero copyright risk, deterministic across machines, fast (~7 s of audio), and Demucs separates it well enough to exercise every downstream code path.
- **Side-channel filesystem assertions are the primary M4L-in-Live strategy.** The JS already writes `~/stemforge/logs/sf_debug.log` and snapshot/manifest files; tests drive M4L by writing into `sf_settings` and assert on log/file outputs. AppleScript is fallback only — it is too brittle to gate CI on.
- **Device targets share one fixture per export flavor.** Refactor exporters around `AbstractExporter` + a `DeviceProfile` dataclass so adding SPD-SX Pro / Koala = one `DeviceProfile` + one golden fixture per flavor, no new test plumbing.
- **Five phases, ~3 weeks of effort.** Phase 1 lays groundwork (fixture + mock LiveAPI hardening). Phases 2–3 are pure-Python and pure-Node and can run in parallel. Phase 4 (Live integration) is opt-in, marked `@pytest.mark.live`, never gates CI. Phase 5 closes the device matrix.

---

## 2. Test Fixture: Recommendation + Rationale

### Options weighed

| Option | Pros | Cons |
|---|---|---|
| **(a) Synthesized at test time (numpy/scipy)** | Zero copyright. Zero binary in repo. Deterministic — any seed → byte-identical WAV. Trivially adjustable (BPM, length, key). Stems are *known*: ground truth exists for every assertion. | Demucs separation quality is lower on synthetic content than real audio; some thresholds need tuning. Initial design effort for the synthesis. |
| (b) CC-0 sample track (e.g. ccmixter, freemusicarchive) | Realistic separation behavior. | Picking one that survives audit churn, satisfies redistribution, AND is short enough is a treadmill. Binary in git is ~2–5 MB. Demucs ground truth is fuzzy → assertions become "approximately." Anyone can swap the file and silently break the suite. |
| (c) Programmatic ProTools-style click+pad+bass loop | Same pros as (a). | Harder to give Demucs something it can split — too pure spectrally and the model collapses. Less useful than (a) for stem-separation tests. |

### Recommendation: **(a) Synthesized fixture.**

The win is not just "no copyright" — it's *ground truth*. Every other layer (bar slicer, curator, prechop, exporter) is testable against known, exact answers because the input was constructed from known, exact pieces.

### Concrete fixture spec

`tests/fixtures/synth_song.py` — pure function `make_synth_song(seed=0, bpm=120, bars=8) -> SynthSongFixture`:

```
SynthSongFixture
├── path: Path                                # written to a session-scope tmpdir
├── bpm, bars, time_sig, sample_rate
├── ground_truth_stems: dict[str, np.ndarray] # what the synthesizer produced
├── ground_truth_beat_times_sec: list[float]  # exact onsets, used as oracle
└── ground_truth_bar_boundaries_sec: list[float]
```

Composition (8 bars, 4/4, 120 BPM = 16.0 s @ 44.1 kHz, stereo):
- **drums**: kick on beats 1 + 3 (60 Hz pulse, 50 ms exp decay), snare on 2 + 4 (white noise band-passed 200 Hz–8 kHz, 80 ms decay), closed hihat on 1/8th notes (high-passed noise).
- **bass**: sawtooth at A1 (55 Hz) playing root-fifth-root pattern, 1 note per beat, soft attack envelope.
- **vocals**: sine-stack (220, 440, 660 Hz) gated to a 4-bar phrase pattern + 4 bars rest, with vibrato so it lands in the "tonal but non-percussive" zone Demucs assigns to vocals.
- **other**: pluck-synth (Karplus-Strong) at C5/E5/G5 on bar downbeats.

**Why this exact composition:** the bar slicer needs varying energy across bars (curator's diversity selection has to *do something*); drums need clear transients (BPM detection); vocals need to be present in only some bars (curation v2 phrase logic); pitched content needs distinct fundamentals (oneshot extraction). All of these are guaranteed by construction.

The fixture is a `@pytest.fixture(scope="session")` writing the WAV once per pytest run to `tmp_path_factory`. Deterministic (`np.random.default_rng(seed)`), so a hash assertion catches accidental drift.

### Single-backend baseline

`DemucsBackend` is now the only stem-separation backend in the repo. Every backend test path runs against `DemucsBackend` only — no API keys, no network, no flakiness.

---

## 3. Test Taxonomy

| Capability | Tier | Files (existing or new) |
|---|---|---|
| **Demucs separation correctness** | Tier 2 (Python, slow but local) | `tests/test_backends_demucs.py` (new), uses synth fixture |
| **BPM + beat detection (low-level)** | Tier 2 | `tests/test_beat_detect.py` (exists; extend with synth fixture oracle) |
| **Tempo reconciliation (multi-source consensus)** | Tier 1 (logic) + Tier 2 (real audio) | `tests/test_tempo_reconciler.py` (exists — mocked-detector unit tests for ratio heuristic, kick tiebreaker, librosa fallback). Phase-2 extension: synth-fixture oracle + curated real-audio regression set covering known-pathological hip-hop tempos. |
| **Bar slicing** | Tier 2 | `tests/test_segmenter.py` (exists), `tests/test_slicer.py` (new) |
| **Curation v1 (max-diversity)** | Tier 2 | `tests/test_palette.py` (exists), `tests/test_curator.py` (new) |
| **Curation v2 (max-diversity, rhythm-taxonomy, sectional)** | Tier 2 | `tests/test_curation_v2.py` (new) — strategy table-driven |
| **Prechop (padded chunks)** | Tier 2 | `tests/test_prechop.py` (exists; extend) |
| **Drum substem extraction (LarsNet/UNet)** | Tier 2 | `tests/test_drum_separator.py` (new) |
| **Oneshot extraction** | Tier 2 | `tests/test_oneshot.py` (exists) |
| **Manifest schema** | Tier 1 (pure Python, fast) | `tests/test_manifest_schema.py` (exists) |
| **Pipeline YAML loading** | Tier 1 | `tests/test_pipelines.py` (exists) |
| **Session loader: `applyCurationV2Clip`** | Tier 3 (Node-vm sandbox) | `tests/js_mocks/test_session_loader.test.js` (new) |
| **Session loader: warp markers + warp_mode per stem** | Tier 3 | same as above |
| **Arrangement loader: tempo, end-to-end placement, loop region** | Tier 3 | `tests/js_mocks/test_arrangement_loader.test.js` (exists; extend) |
| **Arrangement reader (snapshot.json with locators)** | Tier 3 | `tests/js_mocks/test_arrangement_reader.test.js` (exists) |
| **Clip export driver (sf_clip_export.js)** | Tier 3 | `tests/js_mocks/test_clip_export.test.js` (new) |
| **m4l_export_clips.py (the `[shell]` callee)** | Tier 2 | `tests/test_m4l_export_clips.py` (exists) |
| **EP-133 .ppak writer (compose/perform)** | Tier 2 | `tests/test_exporters.py` + `tests/ep133/test_ppak_writer.py` (exist) |
| **EP-133 song-mode (locator-enriched arrangement)** | Tier 2 | `tests/ep133/test_song_*` (exist; extend with synth-fixture e2e) |
| **End-to-end: synth → split → forge → export-song** | Tier 2 (slow) | `tests/test_e2e_pipeline.py` (new), marked `slow` |
| **In-Live integration (optional)** | Tier 4 | `tests/integration/test_live_session.py` (new), marked `live` |

**Tiers defined:**
- Tier 1: pure Python, no audio I/O. <1 s.
- Tier 2: Python + numpy/soundfile/Demucs. Fast Tier 2 < 5 s. Slow Tier 2 = full pipeline, marked `slow`, may hit ~30 s.
- Tier 3: Node-vm with mock LiveAPI. <2 s for the whole suite.
- Tier 4: real Ableton Live. Opt-in via `pytest -m live`. Never in CI.

---

## 4. Phase Plan

### Phase 1 — Foundation (S, ~1 day)

**Lands:**
1. `tests/fixtures/synth_song.py` — the `make_synth_song()` function + session fixture in `tests/conftest.py`.
2. Hardened `tests/js_mocks/max_api.js`. Currently `LiveAPI.get`/`set`/`call` are no-op stubs. Extend to a **scriptable mock** with:
   - A `liveTree` dictionary the test seeds (e.g. `liveTree["live_set tracks 2 clip_slots 0 clip"] = {start_marker: 0, ...}`).
   - `get(prop)` returns `[liveTree[this._path][prop]]` (LOM 1-element-array convention).
   - `set(prop, value)` writes through, recorded in `state.liveApiCalls` for assertions.
   - `call(method, ...args)` matches against a registered handler table. Default: ghost-method behavior (returns truthy, does nothing) — matches Live's actual misbehavior so tests catch the same class of bug the code already mitigates against.
   - `getcount(prop)` returns array length of `liveTree[path][prop]`.
3. Test runner: ensure `tests/test_js_bridge.py` discovers any new `*.test.js` automatically (currently hardcoded — refactor to glob).
4. (Done) Non-Demucs backends were dropped from the repo; no test cleanup needed there.

**Success criteria:**
- `uv run pytest tests/fixtures` (a smoke test that calls the fixture and round-trips the WAV) passes.
- Existing JS bridge tests still pass.
- Synth fixture has a hash-stability test (catches accidental synth changes that would invalidate downstream assertions).

**Deps:** none.

---

### Phase 2 — Core / Python pipeline (M, ~3 days)

**Lands:**
1. `tests/test_backends_demucs.py`: separates the synth fixture, asserts each stem dict key present, asserts spectral correlation between Demucs's `drums` output and `ground_truth_stems["drums"]` exceeds a threshold (~0.6 — Demucs isn't perfect on synth, that's fine).
2. Extend `tests/test_beat_detect.py`: feed synth fixture, assert detected BPM within ±1 of 120, assert beat count = 32 (8 bars × 4 beats).
3. `tests/test_curation_v2.py`: parameterized over `[max-diversity, rhythm-taxonomy, sectional]`. For each strategy, run `forge --curation` against synth fixture, assert `curated/manifest.json` has the expected schema, assert `n_bars` selected matches request, assert each curated bar file exists and is non-silent.
4. `tests/test_prechop.py`: extend to assert `loop_start_sec`/`loop_end_sec` math on the synth fixture for `pad_bars=1` and `pad_last=True/False` cases. Also assert downbeat-anchored slicing: pass `first_downbeat_sec` and verify `source_offset_sec` per chunk lands on the bar grid.
5. Extend `tests/test_tempo_reconciler.py` with real-audio cases:
   - **Synth fixture oracle**: pass synth song through `reconcile_tempo`, assert `bpm` within ±1 of 120, `confidence == "high"`, `first_downbeat_sec` matches the synth's known bar-1 phase.
   - **Real-audio regression set** (`tests/fixtures/tempo_regression/`): a curated set of known-pathological tracks with documented true tempos. Initial set: half-time hip-hop (Black Star "Definition", true 90 BPM — librosa-only path got 120, the bug that motivated this module). Each entry stores expected BPM ± tolerance + the tempo source the reconciler should pick. Marked `slow` (calls beat-this + LarsNet); CI runs the synth oracle, real-audio set runs locally pre-merge.
6. `tests/test_drum_separator.py`: run drum substem extraction on synth fixture (which has known kick/snare/hihat content) and assert each substem's spectral centroid lands in expected band (kick low, snare mid, hihat high).
7. `tests/test_e2e_pipeline.py` (`slow`): synth → `stemforge split` → `stemforge forge --curation pipelines/curation.yaml` → assert all artifacts present (curated/, prechop_manifest.json, drum_substems/, oneshots/). Also assert `stems.json` has `tempo` provenance + `input_audio` fingerprint blocks (sample rate, duration_samples, sha256) — the schema enrichments that arrived with the tempo reconciler.

**Success criteria:**
- All Tier 2 tests pass against synth fixture in <60 s total.
- Coverage report shows >70 % on `stemforge/curator.py`, `stemforge/prechop.py`, `stemforge/oneshot.py`, `stemforge/slicer.py`.

**Deps:** Phase 1.

**Effort:** M. The Demucs separation step is slow (~10 s on M2 for 16 s of audio); use module-scope fixture caching.

---

### Phase 3 — M4L JS sandbox (M, ~2–3 days)

**Lands:**
1. `tests/js_mocks/test_session_loader.test.js`: covers `applyCurationV2Clip`. Build mock clip in `liveTree`, call function with a known v2 loop entry (synthesized — same shape as `curated/manifest.json`'s loop entries), assert:
   - `start_marker` / `end_marker` set to `(rawStart + offset) * secToBeat`
   - `loop_start` / `loop_end` set when `loop.enabled`
   - `warp_mode` matches `BAR_WARP_MODES[stemName]` (drums/bass=0, vocals/other=4)
   - `move_warp_marker` calls match expected count for the seeded existing markers
   - Function returns `false` for legacy entries lacking `padded_start_sec`.
2. Extend `tests/js_mocks/test_arrangement_loader.test.js`: add cases for the 1ef7d5a fix — assert tempo-set call goes out, assert chunks land at `i * bars * 4` beat positions, assert clip span = `(loop_end_sec - loop_start_sec) * secToBeat`, assert markers placed in **seconds** when `warping=false`.
3. `tests/js_mocks/test_clip_export.test.js`: drives `sf_clip_export.js`'s `runExportClips` against a seeded session (3 clips on 4 tracks A/B/C/D), assert the spec.json it would write matches the schema `m4l_export_clips.py` consumes (round-trip contract test).
4. Add a `tests/js_mocks/run_all.js` that imports each `*.test.js` and aggregates pass/fail; the Python bridge becomes one subprocess call.

**Success criteria:**
- All Tier 3 tests run via `uv run pytest tests/test_js_bridge.py` in <5 s.
- Coverage of `applyCurationV2Clip`, `runArrangementLoad`, `runArrangementExport`, and `runExportClips` validated by manually inspecting tests hit each code path (no JS coverage tool — line-of-sight review).

**Deps:** Phase 1.

**Effort:** M. `applyCurationV2Clip` is gnarly — its warp-marker logic alone is 60 lines. Plan ~3 hours of test-writing per top-level function.

**Honest brittleness call-out:** the mock LiveAPI is faithful to the documented LOM; it cannot catch undocumented LOM behavior changes between Live versions (a real risk — see comments in stemforge_loader.v0.js around lines 324–341 where the team has been bitten). Phase 4 covers this.

---

### Phase 4 — Live integration (L, ~3–5 days, optional CI)

This is the part where honesty matters most. Live cannot run headless. Every option has tradeoffs.

**Strategy weighed**

| Strategy | Coverage % of M4L behavior | Brittleness | Effort |
|---|---|---|---|
| Pure Node sandbox (Phase 3) | ~70 % — all our logic, none of the LOM | Low | done in Phase 3 |
| AppleScript UI control | +10 %, but flaky | **High** — UI scripting breaks on Live updates, cursor focus, dialogs. Cannot recommend for CI. | M |
| OSC via tiny Max patch wired into test .als | +20 % — covers actual LOM round-trip | Medium — requires Live + AbletonOSC running, but no UI scripting | M-L |
| **Filesystem side-channel (recommended)** | +15 % — covers the bridge between JS and disk artifacts the rest of the system depends on | Low-Medium — depends on Live being open with the test .als loaded, but no UI clicks | M |

**Recommended primary: filesystem side-channel.** The JS side already writes:
- `~/stemforge/logs/sf_debug.log` — every important code path logs here
- `~/Desktop/snapshot.json` (configurable) — arrangement reader output
- `<exports>/<timestamp>/A01.wav` etc. — clip export bounce output
- `~/stemforge/processed/<track>/curated/manifest.json` — forge output

Tests can drive M4L by writing `sf_settings` (the M4L Dict the device polls) and watching for these files to appear / their contents to match expectations. The existing `sf_settings.js` and `sf_state.js` plumbing is already designed to be poked from outside.

**Lands:**
1. `tests/integration/conftest.py` with a `live_session` fixture: checks Live is running with a known port responding, opens the StemForge test .als if not loaded, waits for device-ready signal (a `~/stemforge/logs/ready.flag` the device writes on init).
2. `tests/integration/test_live_session.py` (`@pytest.mark.live`):
   - **forge round-trip**: write synth fixture path into `sf_settings.audio_in`, trigger `sf_forge` via OSC `/stemforge/forge` (one-line addition to a small Max OSC receiver; not UI scripting), poll for `curated/manifest.json` written, validate against pydantic schema.
   - **session load round-trip**: pre-stage a known `curated/manifest.json`, trigger `loadStemForge`, then have the device dump current LOM state to a sidecar JSON via the existing logger, assert tracks A/B/C/D have N clips at expected slots.
   - **arrangement load round-trip**: similar but for `runArrangementLoad`.
   - **arrangement read round-trip**: the user pre-stages an .als with locators, run `runArrangementExport`, assert the snapshot.json matches a golden (with tolerance on the audio file paths).
3. **NOT recommended**: AppleScript control. Document as fallback in `tests/integration/README.md` with a `tools/applescript/` folder of scripts for manual reproduction, but don't wire into pytest — too brittle to maintain.

**Success criteria:**
- `uv run pytest -m live` passes locally with Live + the StemForge test .als open. Documented as a "developer pre-merge sanity" rather than a CI gate.
- The 4 round-trip tests above all pass.

**Deps:** Phases 1–3.

**Effort:** L. Most of the cost is bootstrap: building the Max OSC receiver subpatch, the device-ready signaling, and the `live_session` pytest fixture's "is Live ready?" probing. Once those exist, adding round-trips is cheap.

**Honest tradeoff:** if you decide Phase 4 is not worth the bootstrap cost, **the plan still has merit without it.** Tier 3 covers most regressions; Tier 4 mainly catches LOM-version drift, which is a low-frequency risk you can accept for now and revisit when Live 12.x lands.

---

### Phase 5 — Export device matrix (M, ~2–3 days)

**Lands:**
1. **Refactor exporter abstraction** to hoist device specs into data:

```
stemforge/exporters/device_profile.py:
  @dataclass class DeviceProfile:
      name: str                  # "ep133", "spdsx", "koala"
      sample_rate: int
      bit_depth: int
      channels: int               # 1 mono, 2 stereo
      max_duration_s: float
      memory_bytes: int | None    # None = unbounded
      naming_strategy: Callable
      writes_project_file: bool   # ep133=True (.ppak), spdsx=False, koala=False
      ...
```

   `EP133Exporter`, `SPDSXExporter`, `KoalaExporter` all subclass `AbstractExporter` and reference a `DeviceProfile`. The .ppak-writing is EP-133-specific; SPD-SX writes `.WFM` + flat folder; Koala writes a flat folder of WAVs + `koala.json`. The exporter abstraction stays generic; device-specific bits live behind `writes_project_file` + a per-device `finalize()` method.

2. **Golden-fixture-driven test pattern**:
   `tests/exporters/conftest.py` provides a `device_profile` parametrize over `[ep133, spdsx_pro_pro, koala]`. Each test case loads a single golden fixture per export flavor:
   - `tests/fixtures/exports/<device>/<flavor>/expected_manifest.json` — pydantic-validated
   - `tests/fixtures/exports/<device>/<flavor>/expected_files.txt` — list of expected output filenames + sizes (with tolerance)
   - `tests/fixtures/exports/<device>/<flavor>/expected_audio_specs.json` — per-file {sample_rate, channels, duration_s, peak_db}

3. **Per-flavor tests** (parametrized by device):
   - `test_export_session_view.py` — flavor (a). Synth fixture → forge → exporter.export from curated/. Assert outputs match golden.
   - `test_export_session_bounce.py` — flavor (b). Build a fake `m4l_export_clips.py` spec.json from synth fixture, run the bouncer, then run the exporter on its output. Assert outputs match golden.
   - `test_export_arrangement_locators.py` — flavor (c). Synth fixture → fake snapshot.json (with 3 locators creating 3 scenes) + stems.json → `export-song`. Assert .ppak (or device equivalent) byte-equality OR (when format is opaque) validate via the parsing path: run `project_reader.py`-equivalent on the output and assert the round-tripped logical content.
   - `test_export_arrangement_bounce.py` — flavor (d). **Scaffolded**: file exists, marked `@pytest.mark.skip(reason="not yet implemented")`, expected fixtures placeholder-stubbed. When implementation lands, removing the skip is the only test change needed.

4. **Adding a new device =**:
   - Subclass `AbstractExporter` with a `DeviceProfile` (~30 lines).
   - Drop 4 fixture directories in `tests/fixtures/exports/<device>/{session,session_bounce,arrangement_locators,arrangement_bounce}/`.
   - The parametrize tables auto-pick it up. No new test functions.

**Success criteria:**
- EP-133 fixtures land with byte-equal expected `.ppak` for the synth-fixture pipeline (or content-equal via reader, if byte-equality is fragile due to timestamps in payload — investigate `ep133/ppak_writer.py` to choose).
- SPD-SX and Koala scaffolding tests pass with placeholder fixtures (assert "exporter wires up, produces *some* output that parses") so the structure is real before fixtures are filled in.
- Flavor (d) test files exist and are skipped, not missing.

**Deps:** Phases 1–2.

**Effort:** M. The big-ticket item is the `DeviceProfile` refactor of `EP133Exporter` — currently the device specifics are inlined. ~half a day of careful refactor + ~half a day per device for SPD-SX / Koala scaffolding.

---

## 5. M4L Automation Tooling

**Primary chosen: filesystem side-channel.** Justification in §4. Specifics:

- **What to build:**
  - A small Max subpatch added to the StemForge test .als: an `[udpreceive 11001]` → `[OSC-route /sf/forge /sf/load_session /sf/load_arrangement /sf/export_clips /sf/snapshot]` → triggers the relevant JS function. ~15 nodes. *Not* AbletonOSC — a dedicated low-surface-area receiver so we don't conflict with whatever the user has running.
  - `tools/integration/live_probe.py` — pytest helper that opens the OSC port, sends commands, polls the filesystem.
  - A device-side `ready.flag` write on init (`sf_state.js`'s init path can drop a single-line file).

- **Fallbacks:**
  - **AppleScript** for cases where OSC isn't enough (e.g. asserting on Live's transport state). Document only, do not wire to pytest.
  - **Manual smoke test checklist** in `tests/integration/MANUAL.md` for visual things tests can't easily assert (clip color, track icons, locator visibility).

- **Brittleness call-outs:**
  - Live version drift will eventually break LOM expectations regardless of test strategy. Mitigation: pin a Live version in `tests/integration/README.md`, document version-tested-against in CI matrix when CI eventually exists.
  - The OSC receiver subpatch is a separate artifact from the device under test. Risk: it gets out of sync with what the device expects. Mitigation: embed version string in patch's `[comment]`, assert it during `live_session` fixture setup.
  - Filesystem polling is timing-sensitive. Use a polling helper with timeout + last-write-time check, not naive `os.path.exists` retry loops.

- **NOT recommending AppleScript for CI**: the user explicitly asked for honesty. AppleScript UI scripting against Live is the kind of thing that runs green for two weeks and then rots after a Live point release. The cost-of-maintenance over its lifetime exceeds the coverage bump it offers. Keep it as a documented manual reproduction technique, not a test gate.

---

## 6. Device Target Matrix

| Device | (a) Session export | (b) Session bounce-export | (c) Arrangement w/ locators | (d) Arrangement bounce-export |
|---|---|---|---|---|
| **EP-133 K.O. II** | Asserts: 4×12 pad layout, .ppak byte/content equal to golden, sidecars present, BPM in pad metadata. **Status: implemented & passing today.** | Asserts: bounce produces A01..D12 WAVs with correct trim, sidecars match `BatchManifest`, .ppak from those WAVs round-trips. **Status: implemented (a812a05/5506a5b) — needs golden fixture.** | Asserts: scenes count = locator count, scene→pad mapping matches `song_resolver`, `arrangement_length_sec` honored, time signature carried. **Status: implemented today, tests partially exist.** | **Status: NOT IMPLEMENTED.** Test file scaffolded, marked `skip`. |
| **Roland SPD-SX Pro** | Asserts: WFM kit file produced, WAVs at 44.1 kHz/24-bit/stereo (verify against actual SPD-SX spec), pad layout matches `DeviceProfile.naming_strategy`. **Status: scaffold only.** | Same as (a) but driven by bounced clips. **Status: scaffold only.** | Locator-derived patterns/kits — depends on SPD-SX's kit/song format support. **Status: research needed; scaffold only.** | **Status: scaffold only, marked `skip`.** |
| **iOS Koala Sampler** | Asserts: flat `.koala`-importable folder, WAVs at 44.1 kHz/16-bit, `koala.json` with bank/pad metadata. **Status: scaffold only.** | Same as (a) but bounced. **Status: scaffold only.** | Koala has no native arrangement/song format — likely flatten-to-banks. **Status: research needed; scaffold only.** | **Status: scaffold only, marked `skip`.** |

**Each cell is one parameterized test case** picking up its device profile + golden fixtures from disk. Adding SPD-SX/Koala = filling in fixtures, not writing new test code.

---

## 7. Open Questions / Risks

1. **EP-133 .ppak byte-equality reliability.** The .ppak writer may include timestamps, hashes, or other byte-varying fields. Need to read `stemforge/exporters/ep133/ppak_writer.py` carefully before promising "byte-equal golden" — content-equal-via-reader is the safer fallback. **Action: confirm before Phase 5 starts.**

2. **Demucs determinism.** Demucs separation results may vary by torch/MPS version on macOS. If this is true on the synth fixture, stem-correlation thresholds need to be loose enough to absorb that. **Action: Phase 2 task 1 includes a determinism probe; if separation outputs drift across torch versions, we cache a "known-good Demucs run" alongside the fixture and feed that into downstream tests.**

3. **Curation v2 strategies' golden output stability.** `max-diversity` includes random-seeded MMR-style selection in some strategies. Need to confirm `_curator.curate(...)` is deterministic given a fixed seed (or take a seed parameter through). **Action: audit `stemforge/curator.py` early in Phase 2; if non-deterministic, either set seed or assert on invariants (count, no-duplicate-bar-indices) instead of identity.**

4. **SPD-SX Pro / Koala format docs.** I don't know these formats well enough to write the golden fixtures yet. **Action: when those devices arrive, dedicate ~1 day per device to format reverse-engineering; fixtures fall out of that work, not before.**

5. **Bouncing-arrangement-export is unimplemented.** Scaffolding test files for unimplemented features is fine, but if the implementation diverges materially from what the test scaffold assumes (e.g. a different snapshot format), the scaffold turns into a chore. **Action: keep scaffold thin — just assert "exporter exists and accepts the documented inputs"; build the asserts after the implementation lands.**

6. **Pure JS sandbox limitations.** The mock LiveAPI cannot reproduce Live's deferred-call semantics or the ghost-method behavior precisely. The current code (e.g. `applyCurationV2Clip`) has been written defensively — that's good — but tests cannot prove that defensiveness works *in Live*. Tier 4 is the only place that does. **Action: be explicit in test docstrings about what Tier 3 does and does not prove.**

7. **Live integration as CI gate or no?** Recommend **no** for now: it requires Live + the test .als + the OSC subpatch, and CI on macOS-with-Live is non-trivial. Run it on developer machines pre-merge only. **Action: confirm with user before Phase 4 lands; design assumes opt-in.**

8. **Synth-fixture-to-Demucs gap.** Real songs and synthetic ones produce different separation residuals. If the user's actual usage shows curator/oneshot bugs that synth tests miss, we need at least one CC-0 real-audio fixture as a sanity track in Phase 4. **Action: revisit after Phase 2 to see if assertions on synth alone are sufficient.**

9. **Tempo regression-set drift.** `tests/test_tempo_reconciler.py`'s real-audio cases bind specific track files (e.g. Black Star "Definition") to expected BPMs. Two failure modes: (a) source files change or move on disk; (b) beat-this / Demucs / LarsNet versions update and produce different BPMs that are still "correct enough" but break exact assertions. **Action: store the audio sha256 alongside the expected BPM in fixture metadata so source drift is detected; assert BPM with a ±2% tolerance rather than equality so model drift doesn't false-fail.**

10. **Half/double-time false positives.** The reconciler's factor-ratio heuristic fires the kick tiebreaker when mix and drums disagree by 0.5×, 0.667×, 0.75×, etc. Genres with genuinely-doubled rhythmic layers (drum-and-bass at 174 BPM with a half-time backbeat that some detectors read as 87) could legitimately exhibit a 2× ratio without being "wrong." **Action: when the regression set grows, add a counter-example for each suspicious ratio so we have explicit cases where the tiebreaker should NOT change the answer.**
