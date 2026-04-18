# StemForge v0 — Full Ship Spec

**Branch:** `feat/harness-patterns`
**Baseline commit:** `11bb1e7` (htdemucs_ft fusion revival + autonomy perms)
**Author:** Architect session `.claude/sessions/architect-170200.json`
**Date:** 2026-04-16

## Why this document

Fusion revival closed issues #4–#9 on `ZacharySBrown/stemforge`. The runtime
is fast (4.54s warm per 10s segment, 11× speedup) and the C++ tests pass
13/13. **But the .pkg is not shippable.** Carry-over notes from the closed
issues flag four unresolved items; a fresh audit of the pkg flow surfaces
one more (models are not bundled). This spec defines done, enumerates the
gap, decomposes the work into parallelisable Engineer workstreams, and
feeds the dispatch round for `Agent(isolation: "worktree")` fleets.

---

## 1. Definition of Done

v0 is shipped when **all** of the following hold on a clean Mac account
(or a simulated clean-account test rig):

1. `sudo installer -pkg v0/build/StemForge-0.0.0.pkg -target /` exits 0
   and emits no errors.
2. Post-install filesystem layout:
   - `/usr/local/bin/stemforge-native` is executable and reports
     `--version` as `0.0.0`.
   - `/usr/local/lib/libonnxruntime.*.dylib` is present and loadable.
   - `~/Library/Application Support/StemForge/models/` contains
     `htdemucs_ft/htdemucs_ft_fused.onnx` and `manifest.json`. sha256 of
     the fused ONNX matches
     `71828190efe191a622f9c9273471de1458fe0e108f277872d43c5c81cbe29ce9`.
   - `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/StemForge.amxd`
     is present (or the equivalent detected Live user library path).
   - `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/stemforge_bridge.v0.js`
     and `stemforge_loader.v0.js` are co-located with the .amxd.
3. Postinstall warmup completed successfully (CoreML MLProgram cache
   populated under `~/Library/Caches/onnxruntime`). First user split
   does not pay the 125s compile cost.
4. Opening Ableton Live 12.1.x and searching the browser's Max Audio
   Effect category shows **StemForge**.
5. Dropping StemForge onto an audio track, then dropping a .wav onto
   the device, produces separated stems loaded into clip slots of new
   tracks within ~30s (10s input → ~5s inference warm + staging IO).
6. `uv run pytest v0/tests` shows ≥ 10 pass and at most 1 skip (the
   `.als` suite stays skipped until `skeleton.als` lands — see W3).
7. Production-path symlinks under `~/Library/Application Support/StemForge/`
   are either **absent** (pure installed state) or point at the
   canonical `v0/build/` tree of the main worktree (dev state).
   **No symlink may point at a `.claude/worktrees/agent-*` path.**

`StemForge.als` (project template) is **not** required for DoD — the
.pkg gracefully skips it when the skeleton asset is absent. Landing
the template is tracked as W3 and is a user-only step.

---

## 2. Gap Analysis

Concrete gaps between the current state (post-baseline-commit `11bb1e7`)
and the DoD.

### G1 — Artifacts scattered across sibling worktrees
`StemForge.amxd` (11 346 bytes) lives in
`.claude/worktrees/agent-a02a5a81/v0/build/StemForge.amxd`, not the main
worktree's `v0/build/`. Same for `stemforge_bridge.v0.js` and
`stemforge_loader.v0.js` in `.claude/worktrees/agent-a02a5a81/v0/src/m4l-js/`.
Python tests `v0/tests/test_amxd.py` skip because of this. `build-pkg.sh`
has sibling-worktree resolution and works anyway, but the test suite
and fresh-clone developer experience do not.

### G2 — Production symlinks point at stale worktrees
`~/Library/Application Support/StemForge/models/*` → `agent-a74b3cc1`
(pre-fusion, no fused .onnx, stale manifest).
`~/Library/Application Support/StemForge/bin/stemforge-native` →
`agent-aeafbfd6` (pre-fusion, would load the old 4-head bag).
Any local install-like test against these symlinks exercises stale code.

### G3 — `.pkg` does not bundle ONNX models  *[highest risk]*
Inspection of `v0/build/build-pkg.sh` confirms the pkg payload includes
only the binary, dylib, .amxd, optional .als, uninstaller. **No models.**
Postinstall creates the empty models directory but never populates it.
On a fresh Mac, `stemforge-native warmup` would fail with model-load
error because `~/Library/Application Support/StemForge/models/` is empty.
Must bundle `htdemucs_ft_fused.onnx` (697 MB) + `manifest.json`
(14 KB) at minimum.

### G4 — `.pkg` does not bundle M4L bridge/loader JS
`v0/src/m4l-js/stemforge_bridge.v0.js` is referenced by the embedded
node.script in `StemForge.amxd` (confirmed by the test
`test_amxd_references_bridge_js`). Node for Max searches the device's
containing folder for the script file. If the JS is not deployed
alongside the .amxd, the device will fail to start its child process.
Neither `build-pkg.sh` nor `postinstall` currently copies these.

### G5 — `.pkg` in sibling worktree is pre-fusion
`.claude/worktrees/agent-a6448eff/v0/build/StemForge-0.0.0.pkg`
(9 667 677 bytes) was built before the fusion revival and before any
model bundling. Not reusable. Must rebuild.

### G6 — Postinstall warmup is untested on a model-less baseline
Issue #8 shipped the warmup hook. Issue #9 confirmed warmup succeeded
on zak's machine. But zak's machine has the stale symlinks from G2 so
`~/.../models/` was not empty. On a pristine account, warmup would
fail. Graceful — postinstall logs and continues — but the user
experience is wrong: they would install, then first split would take
125s, not five.

### G7 — Fresh-install harness does not exist
There is no script or test that simulates a from-zero install and
validates layout + binary + warmup end-to-end. Without one, we cannot
confirm DoD without shipping to the user manually.

### G8 — 11 Python integration tests skip
All skips trace to G1 (.amxd not in main v0/build/) or to the absent
`StemForge.als`. After W1 (canonicalization) lands, the .amxd suite
should move from skip → pass. The .als suite stays skipped until W3
lands the skeleton.

### G9 — `skeleton.als` asset never captured
Requires human interaction with Ableton 12.1.x (File → New Default
Set → Save As…). An agent cannot perform this. Not a DoD blocker per
section 1, but a prerequisite to a future `StemForge.als` ship.

---

## 3. Workstream Decomposition

Five workstreams. Track IDs extend the existing v0 slots by suffix
(e.g. `A-refresh`, `E-refresh`) where the work amends an already-shipped
track, or take a new letter (`H`, `I`) where scope is genuinely new.

### W1 — Artifact canonicalization + symlink refresh   *(Track A-refresh / Engineer)*

**Write scope (per `.claude/CLAUDE.md`):**
- `v0/build/StemForge.amxd` — copy from sibling worktree
- `v0/src/m4l-js/*.js` — copy from sibling worktree
- `v0/state/A/artifacts.json`, `v0/state/A/done.flag` — refresh with
  new paths/shas.
- `v0/state/C/artifacts.json` if present — note canonical .amxd path.
- User-local production symlinks under
  `~/Library/Application Support/StemForge/` (outside repo, but in
  Engineer's allowed shell ops).

**Read-only:** everything else under `v0/`.

**Dependencies:** baseline commit `11bb1e7`. None beyond that.

**DoD for W1:**
1. `v0/build/StemForge.amxd` present, sha256 matches the sibling source.
2. `v0/src/m4l-js/stemforge_bridge.v0.js` + `stemforge_loader.v0.js`
   present in main worktree.
3. `~/Library/Application Support/StemForge/models/*` symlinks repointed
   to canonical `REPO/v0/build/models/*`, OR removed entirely in favor
   of letting `STEMFORGE_MODEL_DIR` point at the repo for dev.
4. `~/Library/Application Support/StemForge/bin/stemforge-native`
   symlink repointed to `REPO/v0/build/stemforge-native`.
5. `uv run pytest v0/tests -q` shows the five `test_amxd_*` tests
   **passing** (not skipping) and the overall suite at ≥ 6 pass / ≤ 6
   skip / 0 fail.
6. `STEMFORGE_MODEL_DIR=v0/build/models v0/build/stemforge-native split
   v0/tests/fixtures/short_loop.wav --out /tmp/sf-w1-smoke
   --variant ft-fused --json-events` produces stems and events without
   error.

**Estimated wall time:** 15–25 min (mostly I/O + test run).

---

### W2 — Installer rebuild with full payload   *(Track E-refresh / Engineer)*

**Write scope:**
- `v0/build/build-pkg.sh`
- `v0/src/installer/scripts/postinstall`
- `v0/src/installer/distribution.xml` (if component topology changes)
- `v0/build/StemForge-0.0.0.pkg` (new artifact)
- `v0/state/E/artifacts.json`, `v0/state/E/done.flag`

**Read-only:** everything under `v0/src/A/`, `v0/src/m4l-js/`, model files.

**Dependencies:** W1 merged (needs `v0/build/StemForge.amxd` + m4l-js in
main worktree).

**Tasks:**
1. Extend `build-pkg.sh`: stage the models user-scope payload. Create
   a third component or extend the user component:
   - `~/Library/Application Support/StemForge/models/manifest.json`
   - `~/Library/Application Support/StemForge/models/htdemucs_ft/htdemucs_ft_fused.onnx`
   (other models — ast, clap, htdemucs unfused, htdemucs_6s — are
   **out of scope for v0 pkg**. Bundle only the default-path model to
   keep pkg size at ~0.9 GB.)
2. Stage `stemforge_bridge.v0.js` + `stemforge_loader.v0.js` into the
   same staging dir as `StemForge.amxd`.
3. Extend `postinstall` to copy the JS files next to the .amxd in the
   detected Ableton User Library. Preserve existing .amxd copy logic.
4. Validate postinstall warmup logic still works against the newly
   populated `~/Library/Application Support/StemForge/models/`.
5. Build the pkg. Record `pkg_size_bytes` and `sha256` in
   `v0/state/E/artifacts.json`.

**DoD for W2:**
1. `v0/build/StemForge-0.0.0.pkg` exists, ~0.9–1.0 GB.
2. `pkgutil --expand-full` on the pkg shows the model payload under
   the user component.
3. Fresh-install simulation passes (W4 is the harness; use a quick
   manual pkgutil + shell probe here as a smoke).

**Estimated wall time:** 30–50 min (pkgbuild + productbuild on 700MB+
payload is IO-heavy).

---

### W3 — skeleton.als user handoff   *(Track D-unblock / Architect)*

**Write scope:**
- `docs/skeleton-als-capture.md` — human-step instructions.
- `v0/state/D/blocker.md` — refreshed pointer to the doc.
- Open a GitHub issue on the repo tagged as human-action-required.

**Read-only:** everything.

**Dependencies:** none. Runs parallel to W1.

**Tasks:**
1. Document the exact Ableton 12.1.x steps: File → New Default Set;
   add any required default tracks (drums bus / Simpler placeholder);
   Save As… to `v0/assets/skeleton.als`. Reference
   `v0/tracks/D-als-template.md` for the expected structure.
2. Note what happens after: Engineer re-runs `v0/src/als-builder/build_als.py`
   to produce `v0/build/StemForge.als`, which then ships in a future
   pkg rebuild (v0.1 or as a fast-follow to v0 ship).
3. Open issue `v0: skeleton.als capture (human-only)`.

**DoD for W3:**
1. `docs/skeleton-als-capture.md` exists and is unambiguous enough
   that a non-expert Ableton user could follow it.
2. Issue is open, referenced from the PR body.

**Estimated wall time:** 10 min.

---

### W4 — Fresh-install validation harness   *(Track H / Engineer)*

**Write scope:**
- `v0/tests/test_pkg_install.py` (or `v0/tests/validate-pkg.sh`, choose
  whichever tests better — pytest is preferred for suite integration).
- `v0/state/H/artifacts.json`, `v0/state/H/done.flag`.

**Read-only:** everything.

**Dependencies:** W2 merged (needs the rebuilt .pkg).

**Tasks:**
1. Write a test that extracts the .pkg into a temp `--target` root
   via `pkgutil --expand-full` (fast, no sudo) and asserts on the
   expected layout. Assertions:
   - `/usr/local/bin/stemforge-native` present, +x.
   - `/usr/local/lib/libonnxruntime.*.dylib` present.
   - Postinstall script exists and is +x.
   - Staging payload contains `StemForge.amxd`, `stemforge_bridge.v0.js`,
     `stemforge_loader.v0.js`.
   - User-component payload contains
     `Library/Application Support/StemForge/models/manifest.json` and
     `.../htdemucs_ft/htdemucs_ft_fused.onnx` of correct sha256.
2. (Bonus, not strictly required) Add a second, more expensive test
   that performs an actual `sudo installer -pkg ... -target $TMPROOT`
   against a hermetic tmp root and runs the resulting binary's
   `--version`. Gate behind `STEMFORGE_INSTALL_E2E=1` to keep default
   `pytest` cheap.
3. Update `v0/tests/README.md` with the new test(s).

**DoD for W4:**
1. `uv run pytest v0/tests/test_pkg_install.py -v` passes against the
   W2-built pkg.
2. Either expand-based assertions cover **all** DoD §2 layout items,
   or a skipped-by-default e2e test does.

**Estimated wall time:** 25–40 min.

---

### W5 — Ableton validation runbook   *(Track I / Architect)*

**Write scope:**
- `docs/v0-ableton-validation.md` — user-facing manual-test runbook.

**Read-only:** everything.

**Dependencies:** W2 merged, W4 agent assignment (can start as W4 does;
no hard code dependency).

**Tasks:**
1. Runbook sections:
   - **Install**: `sudo installer -pkg v0/build/StemForge-0.0.0.pkg -target /`
     (or `open v0/build/StemForge-0.0.0.pkg` for GUI flow).
   - **Ableton setup**: open Live 12.1.x, browse Max Audio Effects,
     drag StemForge onto an audio track.
   - **First-test**: drop a short .wav onto the device, observe the
     progress outlet, watch new tracks populate.
   - **What to check**: stems playable, BPM correct, no Max console
     errors, warmup was already done (first split should be fast).
   - **How to report failure**: screenshots, Max console copy-paste,
     `~/stemforge/logs/` contents.
2. Include a `known issues` section that mentions `StemForge.als`
   absence (W3 followup).

**DoD for W5:** doc committed, linked in the final "ready for Ableton"
summary.

**Estimated wall time:** 15 min.

---

## 4. Parallelisation + Critical Path

```
                              ┌───────────────── W3 ─────────────────┐
                              │  skeleton.als user handoff (async)    │
                              └───────────────────────────────────────┘

baseline (11bb1e7)
     │
     ▼
   ┌────────────┐
   │    W1      │  Artifact canonicalization + symlink refresh
   │ (~20 min)  │
   └────┬───────┘
        │  [user review + merge gate]
        ▼
   ┌────────────┐
   │    W2      │  Installer rebuild with full payload
   │ (~45 min)  │
   └────┬───────┘
        │  [user review + merge gate]
        ▼
   ┌────────────┐      ┌────────────┐
   │    W4      │      │    W5      │   (parallel)
   │ (~35 min)  │      │ (~15 min)  │
   └────┬───────┘      └─────┬──────┘
        │                     │
        └─────────┬───────────┘
                  ▼
          ready-for-Ableton
          summary (Architect)
```

**Waves:**
- **Wave A** (parallel): W1 + W3. Launch together.
- **Wave B**: W2. Gated on W1 PR merging.
- **Wave C** (parallel): W4 + W5. Gated on W2 PR merging.

**User-merge gates** sit between waves because every PR in this spec
touches the production install path (W1: symlinks, W2: installer, W4:
validation harness that runs against the installer) — per the handoff,
these require human review.

**Total wall time (optimistic, with instant user merges):** ~1.5 hours.
**Realistic (with review latency):** 2–4 hours across a day.

---

## 5. Out of scope for v0 ship

- Bundling `ast`, `clap`, `htdemucs` (unfused), `htdemucs_6s` models.
  v0 M4L flow only calls `htdemucs_ft_fused`. Analyzer/Python-CLI
  features that need the other models are post-v0.
- Universal2 binary. Current `stemforge-native` is arm64-only. Apple
  Silicon is the stated ship target; x86_64 rosetta is deferred.
- Notarized / Developer-ID-signed .pkg. Dev-signed (ad-hoc) is the v0
  baseline; notarization is a post-ship quality improvement.
- `StemForge.als` template. W3 surfaces the handoff but the asset
  landing + .als rebuild + .pkg re-ship is explicitly a follow-up
  (v0.1 or fast-follow).
- Any M4L device visual polish. Current .amxd is the Track C Path-1
  programmatic output; the "rich UI with spectral analysis" ambition
  (see `project_m4l_device_design` memory) is v3 work.

---

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Pkg size blows past 1GB, productbuild or installer chokes | Ship blocked | Fall back to shipping a `download-models.sh` postinstall script fetching from a GitHub Release. W2 spec allows this as an alternative. |
| Symlink repointing breaks a zak-local flow | Annoying | W1 backs up pre-existing symlink targets to `v0/state/A-refresh/pre-symlink-state.json` before rewriting. |
| Ableton Live's user-library path detection fails on zak's install | Device doesn't appear | Postinstall already falls back to `~/Music/Ableton/User Library`. Runbook (W5) includes a manual fallback copy command. |
| Node for Max cannot locate bridge JS next to .amxd | Device spawn fails | W4 harness explicitly asserts on JS presence; W5 runbook documents the "no child process" symptom. |
| User merges W2 but not W4 before attempting install | Validation skipped but install may still work | Not a correctness risk; surface in the runbook that W4 harness is optional and the user can proceed straight to Ableton. |

---

## 7. Post-ship follow-ups (not in scope)

- W3 skeleton.als capture → `StemForge.als` rebuild → v0.1 pkg.
- Notarize the .pkg under a Developer ID.
- Universal2 binary.
- Analyzer models (ast, clap) in a future pkg.
- v3 rich M4L device (separate effort, per `project_m4l_device_design`).
