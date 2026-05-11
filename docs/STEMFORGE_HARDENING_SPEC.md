# StemForge Hardening Spec

**Status:** active. Blocks all configurator work.
**Companions:** `EXPORT_CONFIGURATOR_PLAN_v4.md` (archived reasoning),
`EXPORT_CONFIGURATOR_TESTABILITY_BUNDLE.md`,
`EXPORT_CONFIGURATOR_TEST_HARNESS_PRIOR_ART.md`,
`EXPORT_CONFIGURATOR_UX_PATH_INVENTORY.md`.

## Goal

Establish a regression net around current stemforge functionality. The user
*likes* what stemforge does today and intends to use it as-is for some time.
Before any architectural change (configurator, abstract scene model, projector
refactor, etc.), the existing behavior must be testable and tested.

This is non-negotiable: the entire future plan rests on a "byte-identical
output for the same input" criterion that has no meaning without tests for
the inputs.

## Scope

**In scope:**
- Test infrastructure that lets us assert current behavior didn't change.
- Hash-based clip identity (`audio_hash`) — foundation for any future
  configurator code that references clips. Adding this now means the
  hardened baseline already has it; otherwise it gets retrofitted later
  with re-validation pain.
- Closing the highest-impact uncovered paths from the UX inventory.
- Reuse of existing harness assets where they cleanly fit.

**Explicitly out of scope:**
- Any work on the export configurator.
- Any abstract scene model code.
- Any new projectors (Koala, Chompi as projectors — they exist as exporters
  today, leave them alone).
- Any refactor of `song_synthesizer.py` or the EP-133 export chain.
- Any new features. This is purely a coverage and foundation pass.

## Load-bearing decisions

These are the calls that shape the work; if any feels wrong, push back
before code starts.

### Decision 1: filesystem side-channel as primary M4L test mechanism

The M4L device already writes `~/stemforge/logs/sf_debug.log`,
`snapshot.json`, manifests, and bounced WAVs. Tests assert on those
artifacts on disk, not on Live Object Model state via read-after-write.
This is the convention `tests/test_m4l_export_clips.py` already uses; it
becomes universal.

Rationale: LOM read-after-write has known race conditions and version-drift
issues. Disk artifacts are deterministic, hashable, schema-validatable.

### Decision 2: tier-split, not single-tier coverage

| Tier | Runs in | Speed | Examples |
|---|---|---|---|
| 1 — pure logic | CI (Linux) | <1s | manifest schemas, tile/repeat math |
| 2 — Python + audio | CI (Linux) | <60s | curator, prechop, EP-133 byte writers |
| 3 — JS sandbox | CI (Linux) | <5s | LOM-driven JS modules with mocked LiveAPI |
| 4 — Live integration | Developer Mac, opt-in | minutes | filesystem side-channel against running Live |
| 5 — hardware | Manual checklist | — | EP-133 USB-MIDI, Launchpad |

CI runs Tiers 1-3. Tier 4 is `@pytest.mark.live`-gated, runs on developer
Mac pre-merge. Tier 5 is documented manual procedures.

This matches `docs/test-plan.md`'s recommendation and the testability
bundle's verdict (~70-75% testable without Live today, ~85% with mock
hardening).

### Decision 3: harness reuse where it fits, greenfield where it doesn't

The external harness at `~/raindog/harness/quickstarts/max-plugin/` ships
production-quality infrastructure that closes ~half the bundle-flagged gaps:
14 structural verifiers (battle-tested on tape-loss device), an NDJSON
audit emitter, a UDP push-back driver (`sf_remote`), and a headless Max
load-verifier. **Vendor or wire these; don't reinvent.**

The other half — `LiveAPI` mock with backing `liveTree`, Click `CliRunner`
tests, Pydantic schemas for the three undocumented contracts — is
stemforge-side and genuinely greenfield.

Caveat (per prior-art doc's verification footer): the harness's load_verifier
and sf_remote are "engineered, not battle-tested on stemforge." Expect
integration friction. Vendoring is fast; wiring is slower.

### Decision 4: `audio_hash` is foundation, not a configurator-only concern

Today, chunk identity in `prechop_manifest.json` is the file path. `re-anchor`
rewrites WAVs at the same paths, breaking path-based identity for any
downstream consumer.

`audio_hash` (16-hex sha256 prefix of WAV bytes, matching the existing
`SampleMeta` pattern at `stemforge/manifest_schema.py:62-83`) is needed for
the configurator's clip refs *and* for any future "did this chunk actually
change?" check. Adding it as part of hardening means:

- The hardened baseline already includes it.
- Test fixtures get regenerated once, with the field present.
- Downstream consumers (configurator, future projectors) consume hashes
  that have always been there.

Adding it later means re-regenerating fixtures, re-validating every
existing test against the new baseline, and dealing with the half-step
period where some manifests have hashes and some don't. Not worth it.

### Decision 5: highest-impact uncovered paths get tests; everything else gets triaged

The UX inventory found 26 uncovered paths out of 62. Trying to cover
all of them is multi-month work and probably wrong-priority. Strict
prioritization:

**Must-cover before any configurator work:**
- `m4l.button.commit` — the 2004-LOC `_commitSessionTracks` walker. Every
  EP-133 song-export depends on it. **Highest-impact uncovered path in
  the codebase.**
- The §15 must-keep-green path-IDs from v4 (the EP-133 song-export chain
  + arrangement reader + commit + bounce + the four core CLIs).

**Smoke-cover before any configurator work:**
- All 11 `stemforge` CLI subcommands via `CliRunner`. Smoke-level only —
  "command runs against a fixture and produces expected output files."
  Not exhaustive parameter sweeps.

**Investigate before deciding:**
- `m4l.button.settings` — outlet exists in `sf_ui.js` but is undocumented.
  Is it wired? If yes → cover. If no → remove dangling outlet.
- `curation.bulk.reslice-and-curate` — superseded by `re-anchor` + curation
  pair? Confirm with user; drop if dead.

**Defer:**
- The remaining ~20 uncovered paths. Document them; cover them as
  regressions arise or as configurator work touches them.

### Decision 6: synthetic fixture as universal ground truth

A deterministic 8-bar 4/4 stereo loop @ 120 BPM, generated programmatically
(numpy/scipy), with known stem content and known beat times. Every pipeline
test runs against this fixture.

Rationale: the alternative (CC-0 real-audio fixtures) creates "approximate"
assertions and a treadmill of finding redistributable, short, audit-friendly
tracks. Synthetic gives ground truth — every layer of the pipeline is
testable against known answers because the input was constructed from known
pieces.

Per `docs/test-plan.md` §2; design already done.

## Plan

The work splits into four streams that mostly run in parallel, gated on a
formal acceptance check.

### Stream A: foundation data shape

- Add `audio_hash` field to `ChunkMeta`, thread through
  `prechop_manifest.json` writer.
- Regenerate every test fixture containing `prechop_manifest.json`.
- Pydantic schemas for `stems.json`, `prechop_manifest.json`,
  `snapshot.json` (the three undocumented contracts per testability
  bundle §D.1).

### Stream B: stemforge-side test infrastructure

- Synthetic fixture (`tests/fixtures/synth_song.py`) per
  `docs/test-plan.md` §2.
- Hardened `tests/js_mocks/max_api.js` LiveAPI mock with backing
  `liveTree` Dict, get/set/getcount with persistence, handler-table for
  `call`. Encodes known LOM quirks (read-only `warp_bpm`, marker units
  flip with warping).
- `tests/test_cli.py` with `CliRunner` smoke tests for all 11 CLI
  subcommands.
- `@pytest.mark.live` marker registered, default-skip behavior.

### Stream C: harness reuse

- Vendor `forge_device.audit` into `stemforge/tests/_helpers/audit.py`.
  Wire `audit.step()` around `forge`, `re-anchor`, `export-song` CLI
  entry points.
- Vendor `forge_device.verifiers` (14 structural verifiers). Add to CI
  as non-blocking check on `v0/build/StemForge.amxd`.
- Wire harness `verify-load` (pitfall #24, headless Max launcher) as
  developer-Mac-tier check.
- Add `[udpreceive 7420]` + `[udpreceive 7421]` to the device build
  pipeline; adapt harness `sf_remote.py` to talk to it.

### Stream D: highest-impact path coverage

- Tier-3 tests for `m4l.button.commit` against the hardened LiveAPI mock.
  Cover trim/rotate/ambiguous modes, missing clips, warped clips,
  multi-bar clips, the `session_tracks` round-trip into `song_resolver`.
- Coverage for §15 must-keep-green paths (most of which already have
  tests; this stream verifies and fills gaps).

### Stream E: tempo + anchor accuracy (added 2026-05-06)

> **Retroactive scope**: this stream was NOT in the original 14-checkbox
> hardening gate. It was added 2026-05-06 mid-pass after live-audio
> testing on Definition / Believer / Ooh La La surfaced a tempo
> reconciler bias bug (~0.1–0.4% high BPM, ~120ms drift by bar 12) that
> the synthetic fixture had never caught. Gated retroactively as part of
> the acceptance gate per user sign-off in real time. The lesson — that
> synth fixtures are necessary but not sufficient for tempo-sensitive
> work — is documented in `HARDENING_VERIFICATION.md` for future
> tempo-touching streams (cross-song splicing in the configurator
> especially).

This stream was carved off mid-hardening, after the live test revealed that
real-world tempo accuracy was visibly broken on multiple tracks despite the
existing reconciler. Three fixes landed in the same session; this stream
documents the test gaps each one creates.

**Fixes that landed:**

1. **`_bar_period_from_downbeats` median → mean** (`stemforge/tempo_reconciler.py`).
   beat-this's downbeat positions are quantized to its internal frame rate;
   the median of clean IBIs locks onto the most-common quantum, biasing the
   reported BPM by ~0.1–0.4% even when most beats span multiple quanta. Mean
   averages across them and recovers a sub-quantum estimate. Definition went
   from 90.226 → 89.98 (truth ~89.88).

2. **`refine_bpm()` cross-correlation refinement** (`stemforge/tempo_reconciler.py`).
   New function. Holds `first_downbeat` fixed; sweeps BPM ±2% in 0.01 steps;
   for each, sums kick-band onset energy at every implied bar boundary
   across the whole song. Returns the BPM with peak score. Sub-quantum
   resolution because tiny BPM errors accumulate into large drift over 80
   bars, making the score function very steep near the true value.
   Verified: definition 89.98 → 89.89 (matches historic May 2 truth =
   89.88), drift at bar 13 from +128.5ms to +9.9ms.

3. **Always-on wiring** of `refine_bpm` into `stemforge split` (post-reconciler;
   skipped when user passes `--bpm` override) and `stemforge re-anchor`
   (post-prechop-recut, on drums stem with user's locator-anchored fdb).

4. **Locator bar-snap** (`v0/src/m4l-js/sf_locator_anchor.js`). The M4L
   re-anchor button used to compute `shift = locatorBeat - bar1Idx*chunkBeats`
   directly from where the user dropped the locator. If the locator landed
   at a sub-bar position, every prechop chunk tiled at fractional session
   bars, mismatching the curated-clip system (which always fires at integer
   session bars). Now: snap `picked.time_beats` to nearest bar before
   computing shift; visually move the cue_point via LiveAPI to match.

5. **Auto-reslice-curated hook on re-anchor** (Python `stemforge/cli.py`
   re-anchor command). When `curated/manifest.json` exists, re-anchor
   subprocesses `stemforge_curate_bars.py --reslice-only` after rewriting
   `stems.json`. Curated bar WAVs get re-extracted from the source stems
   at the new anchor; loop selections preserved.

6. **Loader cleanup** (`v0/src/m4l-js/stemforge_loader.v0.js`). Deleted
   `_loadCuratedManifest` (v1 flat-bars) and `_loadCuratedV2` (v2 Drum
   Rack-only). Production-mode `loadSong()` is now the single path.
   Manifests without `layout_mode='production'` surface a clear error.

**Test gaps this stream must close:**

| What landed | Test file | What test asserts |
|---|---|---|
| #1 mean-not-median | `tests/test_tempo_reconciler.py` (new test) | Synthesized downbeats with most IBIs at exactly 2.660s + a few at 2.665s → returned period is mean (~2.6605), not median (2.660). Locks the choice in against silent regression. |
| #2 `refine_bpm()` correctness | `tests/test_tempo_reconciler.py` (new test) | Use `tests/fixtures/synth_song.py` rendered at known BPM; call `refine_bpm` with deliberately-wrong candidate; assert refined BPM within 0.05 of truth. Synth fixture is hash-stable so test is deterministic. |
| #3 split → refine_bpm wiring | `tests/test_cli.py` (new test, `@pytest.mark.live` if beat-this gated) | CliRunner runs `split` on synth fixture at e.g. 90.0 BPM; assert `stems.json.bpm` within 0.05 of truth. |
| #4 re-anchor → refine_bpm wiring | `tests/test_cli.py` (new test) | Forge a track, then `re-anchor` with deliberately-wrong `--bpm`; assert final `stems.json.bpm` is closer to truth than input. |
| #5 auto-reslice hook on re-anchor | `tests/test_cli.py` (new test) | Forge → curate → re-anchor; assert `curated/manifest.json.bpm` matches new `stems.json.bpm` AND `bar_001.wav` duration changed accordingly. |
| #6 locator bar-snap (JS) | `tests/js_mocks/test_locator_anchor.test.js` (new test added 2026-05-06) | Cue_point at session beat 18 → `anchor()` snaps `PENDING_LOCATOR_BEAT` to 20; mock's `cp.set("time", ...)` called with snapped value; resulting `shift` is integer-bar multiple. ✓ shipped today. |
| #7 reslice-curated correctness | `tests/test_reslice_curated_from_anchor.py` (8 cases, shipped today) | BPM change rewrites WAV duration; fdb shift moves source-stem read window; one-shots untouched; user-committed `offsets` preserved; error paths for missing inputs. ✓ shipped today. |
| #8 loader rejects non-production manifests | `tests/js_mocks/test_*.test.js` (new test or extend) | `loadFromDict()` with a v1/v2 manifest emits the "not production, re-curate" error and bangs outlet 1 without loading anything. |

### Triage micro-tasks

- Investigate `m4l.button.settings` outlet. Cover or remove.
- Confirm `curation.bulk.reslice-and-curate` status. Cover or drop.

### Canonical tempo regression fixtures

To prevent future reconciler/tempo regressions, three real-world tracks
should be permanent labeled-example tests. They're gated behind a marker
(e.g. `@pytest.mark.live_audio` or `@pytest.mark.has_phase3_inputs`) so
CI without local source files skips them.

Source files: `/private/tmp/phase3_inputs/{believer,definition,ooh_la_la}.wav`.

| Track | Truth BPM | Truth first_downbeat | What it catches |
|---|---|---|---|
| **Definition** | 89.88 | 8.934s | Mix-vs-drums first_downbeat disagreement (mix says 3.78s, drums says 8.94s — drums is right). Sub-quantum BPM bias (median estimator gave 90.226). The killer test for the reconciler. |
| **Ooh La La** | 84.99 | 22.594s | Long intro (>20s before bar 1). Catches first_downbeat regressions where detectors miss extended intros. Also moderate sub-quantum bias (median gave 85.106). |
| **Believer** | 124.99 | 0.283s | Already-correct case. Regression test that detector doesn't *over*-correct on metronomic tracks; locator-anchor snap should be no-op or trivial (≤0.5 beats). |

Recommendation: add `tests/fixtures/known_tempos.py` with these values and
gate via `@pytest.mark.has_phase3_inputs`. Each test runs `split` then
asserts `stems.json.bpm` and `tempo.first_downbeat_sec` match the
documented truth within 0.1 BPM and 50ms respectively.

## Acceptance gate

The hardening pass is done — and only then can configurator work start —
when all of these hold:

**Foundation:**
- [x] `audio_hash` field present in `ChunkMeta`, serialized in
      `prechop_manifest.json`. (`stemforge/prechop.py:110`,
      `stemforge/manifest_schema.py:66`. PR #39.)
- [x] All test fixtures regenerated; full test suite green.
      (679 Python pass + 4 skip + 7 JS test files all green at session end.)
- [x] Pydantic schemas for `stems.json`, `prechop_manifest.json`,
      `snapshot.json` exist; reads/writes validate against them.
      (`stemforge/schemas.py`, PR #43.)

**Test infrastructure:**
- [x] Synthetic fixture deterministic with hash-stability check.
      (`tests/fixtures/synth_song.py` +
      `tests/test_synth_song.py::test_two_renders_same_seed_produce_byte_identical_wavs`.)
- [x] LiveAPI mock has backing `liveTree`; existing JS tests pass through
      the new mock. (`tests/js_mocks/max_api.js:17` + 14 `liveTree`
      references; all 7 JS test files run against this mock.)
- [x] `tests/test_cli.py` exists; all 11 subcommands have at least one
      passing CliRunner smoke test. (21 test functions; sentinel
      `test_acceptance_gate_TI_3_all_eleven_subcommands_have_at_least_one_smoke_test`.)
- [x] `@pytest.mark.live` registered; CI default-skips, opt-in works.
      (`pyproject.toml` markers; `tests/conftest.py:pytest_collection_modifyitems`.)

**Harness wired:**
- [x] `forge_device.verifiers` runs in CI as non-blocking check, passing
      on current `v0/build/StemForge.amxd`. (Vendored as
      `stemforge/verifiers.py`; CI step at `.github/workflows/ci.yml:168`.)
- [x] `forge_device.audit.step()` wraps the load-bearing CLI entry points;
      produces NDJSON trail. (5 `@with_audit` sites in `stemforge/cli.py` —
      forge / re-anchor / reslice-curated / export-song / split. Spec
      originally said "three" — implementation grew during normal
      development as new commands were added; all of them get audit
      coverage.)
- [x] `verify-load` runs on developer Mac against `v0/build/StemForge.amxd`.
      Adaptation gap (`.amxd` requires Live to instantiate; Max can't
      load it headless) closed 2026-05-08: `_extract_maxpat_from_amxd()`
      in `stemforge/load_verifier.py` extracts the inner patcher to a
      temp `.maxpat`. Tests: `test_extract_maxpat_from_amxd_against_real_artifact`
      + 3 sibling cases. 28 pass + 1 skip. The gap was first surfaced
      in PR #49 review and tracked in GH (issue filed 2026-05-08 for
      durable reference) — the spec's "or surfaced issues filed and
      fixed" escape clause now refers to a GH issue, not just a PR
      review thread.
- [x] `sf_remote fire forge` triggers device action with log confirmation.
      Wiring added 2026-05-08: `[udpreceive 7420]` → `[route state forge
      preset-loader manifest-loader settings ui logger]` → module inlets,
      `[udpreceive 7421]` → sf_state_mgr, in
      `v0/src/maxpat-builder/builder.py`. Verified at build time:
      patcher contains 2 udpreceive boxes + 1 dispatcher route + 7
      dispatch lines + 1 dump line.

**High-impact paths:**
- [x] `m4l.button.commit` has ≥10 Tier-3 cases passing.
      (17 cases in `tests/js_mocks/test_commit.test.js`. PR #48.)
- [x] Every must-keep-green path-ID from v4 §15 has at least one passing
      test asserting current behavior. (`tests/test_path_coverage.py`
      with `MUST_KEEP_GREEN_PATHS` parametrize. PR #50.)

**Tempo + anchor accuracy (Stream E, added 2026-05-06):**
- [x] `_bar_period_from_downbeats` uses mean (not median); test in
      `tests/test_tempo_reconciler.py::TestBarPeriodFromDownbeats` locks
      this in (4 cases including the explicit "regressed to median" guard).
- [x] `refine_bpm()` correctness test against `synth_song` fixture at
      known BPM; refined value within 0.05 BPM of truth.
      (`TestRefineBpm` — 4 cases. Note: needed a 24-bar `long_synth_song`
      fixture; default 8-bar synth is too short for refine_bpm's 8-bar
      minimum at ±2% sweeps.)
- [x] `stemforge split` always-on `refine_bpm` wiring covered.
      (Sentinel test `test_split_path_invokes_refine_bpm` rather than
      CliRunner end-to-end — synth's 1/8-note hi-hats trip beat-this
      half-time. SE-2 covers correctness directly.)
- [x] `stemforge re-anchor` always-on `refine_bpm` wiring covered.
      (Same sentinel approach — `test_re_anchor_path_invokes_refine_bpm`.)
- [x] Auto-reslice-curated hook on `re-anchor` covered.
      (Sentinel `test_re_anchor_auto_reslices_curated` asserts the
      `curated/manifest.json` probe + `--reslice-only` invocation +
      `reslice-curated` subcommand registration.)
- [x] Locator bar-snap (M4L) covered in
      `tests/js_mocks/test_locator_anchor.test.js`. (shipped 2026-05-06)
- [x] `reslice_curated_from_anchor()` covered in
      `tests/test_reslice_curated_from_anchor.py` (8 cases). (shipped 2026-05-06)
- [x] `loadFromDict` rejects non-production manifests with clear error
      (legacy v1/v2 paths removed 2026-05-06). Sentinel test in
      `tests/js_mocks/test_loader_dispatch.test.js` (6 cases).
      (shipped 2026-05-07)
- [x] Canonical tempo regression fixtures (Definition / Ooh La La /
      Believer) wired as `@pytest.mark.has_phase3_inputs` tests; truth
      values in `tests/fixtures/known_tempos.py`. (shipped 2026-05-08;
      strict assertion on all three tracks after PR #59 / GH #55
      landed 2026-05-08).

**Outstanding tempo work (filed as GH issues, not blocking gate):**
- ~~GH #55 — reconciler: prefer `beat-this:drums` first_downbeat when BPMs agree~~ — **CLOSED 2026-05-08** (PR #59 merged; phase-equivalence picker plus strict-truth canonical assertions for Definition + Ooh La La).
- GH #56 — `refine_bpm` in split should use drums stem (currently uses mix)

**Triage:**
- [x] `m4l.button.settings` triaged: dangling docstring reference
      removed. (`tests/test_path_coverage.py::test_triage_m4l_button_settings_dangling_docstring_removed`.)
- [x] `curation.bulk.reslice-and-curate` triaged: dropped.
      (`tools/reslice_and_curate.py` deleted; superseded by
      `stemforge reslice-curated` from Stream E.)

If any of these don't hold, the hardening pass is incomplete and
configurator work doesn't start. The discipline is non-negotiable.

## Streams that block configurator work

All four streams plus triage. The acceptance gate is unanimous.

## Streams that don't block configurator work but are good hygiene

None in this spec — by construction. Anything in this spec is a hard gate.
Hygiene work that came up during research but isn't gating goes in a
separate "stemforge-hardening-followups.md" document, not here.

## What this spec deliberately doesn't say

- **Order of operations within streams.** Streams A-D have internal
  dependencies (e.g. fixture regeneration depends on `audio_hash` landing;
  Tier-3 commit tests depend on hardened mock). Determine those when
  picking up each stream.
- **Person-time estimates.** The work is bounded but not predictable; the
  harness reuse has known integration risk per the prior-art doc's
  caveats.
- **Specific test cases.** Each stream's prompt to Claude Code (or
  development session) determines its specific cases.
- **CI configuration changes.** Stream C implies CI updates; specifics
  depend on actual `forge_device.verifiers` integration.

## Risks

**R1 — Harness integration friction.** `verify-load` and `sf_remote` are
engineered but not battle-tested on stemforge per the prior-art footer.
Expect each to surface issues during wiring. Plan for surprises; don't
budget them as commodity work.

**R2 — Fixture regeneration cascade.** Adding `audio_hash` regenerates
every fixture's `prechop_manifest.json`. If any test was implicitly relying
on a specific manifest shape (rather than schema), it breaks. The break
is fixable; just budget for it.

**R3 — `m4l.button.commit` is genuinely complex.** The 2004-LOC
`_commitSessionTracks` walker has trim mode, rotate mode, ambiguous mode,
warp markers, multi-bar clips, audio_hash mismatch detection. Tier-3
coverage of all of those is real work.

**R4 — Triage candidates may surface scope creep.** If `m4l.button.settings`
turns out to be wired to something nontrivial, covering it is a chunk of
work. If it's a dangling outlet, removing it is a one-line fix. We won't
know until we look.

## What success looks like

After hardening lands, the user can:
- Run `pytest -q` and trust that everything passing means everything works.
- Make changes to the codebase with confidence that regressions surface
  in CI.
- Refactor `song_synthesizer.py` (or any other Phase 1 target) knowing
  byte-identical output is verifiable.
- Drive the M4L device headlessly via `sf_remote` for skill-level
  automation.
- Read an NDJSON audit trail of any CLI run to debug after the fact.
- Have a hashed, deterministic synthetic fixture as a stable test target.

The user keeps using stemforge as it works today, with confidence that
nothing will silently break.

When this spec's acceptance gate is met, the configurator spec
(`STEMFORGE_CONFIGURATOR_SPEC.md`) becomes the active plan.
