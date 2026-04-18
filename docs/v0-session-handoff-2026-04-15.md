# v0 Orchestration Handoff — 2026-04-15

**Purpose:** full snapshot of the v0 multi-agent build so a future session can pick up cold.

## TL;DR

v0 is **shippable today** on every axis except:
1. `v0/assets/skeleton.als` — one 30-second human step in Ableton (blocks D → E can still ship without the .als template).
2. `htdemucs_ft` default is slow (50s per 10s input); swapping default to `htdemucs_6s` gives 7.3s per 10s input and 6 stems. **Product decision pending.**

All other tracks are green. Branch `feat/harness-patterns` contains 14 integrated commits, not pushed to origin.

## Commits landed this session (in merge order)

| Commit | Track | Summary |
|---|---|---|
| `a5b6875` | F | CI + release workflow skeletons (ONNX-first) |
| `6d52160` | B | Python package split (core / native / analyzer / dev extras) |
| `2ba24a6` | — | Added `[onnx]` optional-dependencies extra |
| `74ec1d6` | A0 partial | ONNX framework, AST + CLAP converted, Demucs blocked |
| `17923d6` | D partial | .als builder + 30/30 tests, awaits `skeleton.als` |
| `4185448` | A0.1 | Demucs ONNX unblocked via vendored HTDemucs (external STFT) |
| `9e0c032` | A code | libstemforge + stemforge-native CLI (runtime BLOCKED for validation) |
| `150358e` | A validator | End-to-end inference green, CoreML inactive |
| `c9683d2` | C | .amxd programmatic generator + bridge/loader JS, 26/26 tests |
| `ac4a71d` | E | .pkg installer + curl\|bash + postinstall, 19/19 tests |
| `0dd0f06` | G | Integration test suite (6 pass / 10 conditional skip) |
| `736e671` | CoreML opt | Static-shape re-export; 4.04× Demucs inference speedup |
| `3b48b21` | Fusion | **ABORTED** — 4-head fusion failed CoreML MLPackage compile |

Pre-session base: `3eeedbe` (Pivot v0 to ONNX-first).

## Current production state

### Per-model performance (10s stereo @ 44.1 kHz, warm cache)

| Model | Stems | CPU | CoreML | Status |
|---|---|---:|---:|---|
| `htdemucs` | 4 | ~24s (est) | **10.9s** | ✅ CoreML active |
| `htdemucs_6s` | 6 | ~20s (est) | **7.3s** | ✅ CoreML active |
| `htdemucs_ft` (current default) | 4 | 22.1s | **50.3s** ⚠️ | Regression — 4× session-load overhead dominates |
| AST (instrument detect) | n/a | — | fp32 CPU | 2.4e-5 logit diff vs torch |
| CLAP (genre) | n/a | — | fp16 CPU | 1.000000 cosine vs torch |

### Pipeline math (current default = `htdemucs_ft`, 50s per 10s)

- 3-minute track: ~15 min
- 4-minute track: ~20 min

### Pipeline math (if default swapped to `htdemucs_6s`, 7.3s per 10s)

- 3-minute track: ~2.2 min (sub-realtime)
- 4-minute track: ~2.9 min

### Build artifacts

| Artifact | Location | Size | State |
|---|---|---|---|
| `stemforge-native` binary | `.claude/worktrees/agent-a133b5f9/v0/build/` | 368KB arm64 | Ad-hoc codesigned, hardened runtime |
| `libonnxruntime.1.24.4.dylib` | same | 35MB | Ad-hoc signed |
| ONNX models | `.claude/worktrees/agent-a74b3cc1/v0/build/models/` | 3.1GB | 5 models + ort_cache |
| `StemForge.amxd` | `.claude/worktrees/agent-a02a5a81/v0/build/` | 11KB | Path-1 programmatic |
| `StemForge-0.0.0.pkg` | `.claude/worktrees/agent-a6448eff/v0/build/` | 9.67MB | xar, unsigned-dev |
| `StemForge.als` | — | — | ❌ blocked on skeleton.als |

Production-path symlinks (for running the binary locally):
- `~/Library/Application Support/StemForge/models/` → A0 worktree
- `~/Library/Application Support/StemForge/bin/stemforge-native` → A worktree

## Pending decisions

### 1. Default model for v0 CLI

| Option | Latency | Quality | Action |
|---|---|---|---|
| **A** Keep `htdemucs_ft` default (status quo) | 50s per 10s | PIVOT-compliant primary | No code change |
| **B** Swap default to `htdemucs_6s` | 7.3s per 10s | 6 stems (drums/bass/vocals/other/guitar/piano); -130 dBFS parity (better than ft's -99) | Edit `DemucsVariant::Default` in `v0/src/A/src/sf_demucs.hpp` + rebuild binary |
| **C** Parallel-load 4 ft sessions in C++ | ~13s projected | Keeps `ft` primary | 1-2h agent, moderate risk |
| **D** Debug CoreML MLPackage compile (see fusion below) | Unknown | Keeps `ft` primary | 4-8h+, uncertain payoff |

**My recommendation:** B. Swap to `htdemucs_6s`. Better feature set (6 stems vs 4), better parity numbers, sub-realtime. ft can stay in the manifest as an option via `--model htdemucs_ft` for users who want it and will wait.

### 2. `skeleton.als` human step

30 seconds in Ableton Live 12.1.x: File → New Default Set → save as `v0/assets/skeleton.als`. Documented in `v0/assets/README.md`.

After it lands:
```bash
uv run python v0/src/als-builder/builder.py   # generates v0/build/StemForge.als
bash v0/build/build-pkg.sh                     # rebuilds .pkg with .als bundled
```

### 3. Production signing (CI-only concern, not blocking)

`v0/build/sign-notarize-pkg.sh` and `.github/workflows/release.yml` expect Developer ID certs via secrets. Track F documents the 8 secret names. Set them in GitHub Secrets when ready to publish a signed release.

### 4. Push to origin

`feat/harness-patterns` has 14 new commits, not pushed. `git push origin feat/harness-patterns` (allowed per settings.json) when ready.

---

## Fusion experiment — full takeaways

**Goal:** eliminate the 40s CoreML session-load overhead on `htdemucs_ft` by fusing the 4 specialist heads into one ONNX graph.

**Result:** ABORTED. Math is perfect; CoreML can't compile the result.

### Timeline

1. **Phase 1 — 2-head smoke test.** Coverage 96.4% (PASS). MLProgram compile returned `SystemError: 20` (ENOTDIR at CoreML framework level), ORT silently fell back to CPU. Brief said Phase 1 PASS = commit to Phase 2, so the fusion agent proceeded.
2. **Phase 2 — 4-head fusion built successfully.** 697MB artifact (25.8MB ONNX + 671.5MB external data). SHA256 `4a6f1d78…`. Passes `onnx.checker.check_model`.
3. **Phase 3 — Parity PASS at bit-exact:** max_abs_err = 0.0, RMS = -240 dBFS (floor). Mathematically equivalent to unfused bag.
4. **Phase 3 — Coverage PASS:** 96.4% (5728/5944 nodes, 32 partitions — same partition count as single-head).
5. **Phase 3 — Compile FAIL:** same `SystemError: 20`. Silent CPU fallback. Latency on CPU only: 7.60s fused vs 10.44s unfused (1.37× CPU-only win).

### Root cause (hypothesized)

`SystemError: 20` = BSD `ENOTDIR`. CoreML EP materializes its compiled MLProgram as an `.mlpackage` directory bundle. At 697MB the package likely trips a path-length, inode, or buffer limit in CoreML's framework code — error surfaces through the OS syscall layer rather than CoreML's structured error output. ORT log redirection doesn't capture NSLog stderr, so the actual NSFileSystemError is invisible from Python.

### Things that DID NOT fix it (per fusion_aborted.md §Phase 3)

- `ModelCacheDirectory` override to clean `/tmp`
- `MLComputeUnits` = `ALL` / `CPUAndNeuralEngine` / `CPUAndGPU` / `CPUOnly`
- `opset_import` dedup (was a prime suspect)
- `disable_ep_fallback` session config (not wired for per-provider compile failure in ORT 1.24.4)

### Key learning: Phase 1 coverage gate is NOT predictive of MLProgram compile success

`CoreMLExecutionProvider::GetCapability` returns partition assignments statically — it doesn't attempt compile. A future smoke test should add a compile-attempt stage (try `session.run(dummy_input)` under the CoreML EP and check for silent fallback via `session.get_providers()`).

### Paths forward (if someone wants to revive fusion)

#### Path F1 — CoreML-side debug (4-8h, uncertain)

Find the NSLog error:
- Run compile inside Xcode Instruments "System Trace" or "CoreML" template
- Dump the `.mlpackage` that CoreML EP is producing, run `coremlcompiler compile` on it manually
- Test `EnableOnSubgraphs=0` (may bypass the per-parallel-subgraph compile path that breaks)

#### Path F2 — Batch-dimension fusion instead of concat-fusion (2-3h, probably works)

Instead of 4 parallel subgraphs sharing an input (concat fusion), export one torch `nn.Module` that batches over `dim=0` so the ONNX graph sees `batch=4` on a single model path. Structurally different — CoreML may prefer this because it's identical operator topology at different batch sizes. Requires torch-side re-export rather than ONNX-side compose.

#### Path F3 — Parallel-load in C++ (1-2h, safest)

Don't fuse at all. Load 4 separate `Ort::Session` objects concurrently via 4 threads at `sf_create`. Inference threads inference them concurrently. If ANE queues multi-client submissions fairly: ~10s load + 0.6s inference = ~13s warm wall. If ANE serializes: ~10s load + 2.2s inference = ~15s warm wall. Either way a major win over 50s, and no graph-level changes.

**This is my recommendation if you want to keep `ft` as default. It's what option C was in the pending decisions above.**

#### Path F4 — Abandon ft as default (0 effort)

Swap to `htdemucs_6s` (option B). 6 stems, 7.3s, done.

### Artifacts from the fusion experiment (committed, reproducible)

- `v0/src/A0/fusion_smoke.py` — 2-head smoke probe
- `v0/src/A0/fuse_ft.py` — full 4-head fuser
- `v0/src/A0/fusion_parity.py` — unfused bag vs fused parity harness
- `v0/state/A/fusion_aborted.md` — **authoritative 354-line report**
- `v0/state/A/fusion_coreml_verbose.log` — 2.3MB ORT verbose capture

Reproduce from a fresh worktree on `feat/harness-patterns`:
```bash
git checkout -B feat/v0-demucs-ft-fused feat/harness-patterns
uv run --active python -m v0.src.A0.reexport_static --models htdemucs_ft --skip-parity --skip-coreml
uv run --active python -m v0.src.A0.fusion_smoke    # ~3s, reproduces compile FAIL
uv run --active python -m v0.src.A0.fuse_ft         # ~3s, builds 697MB artifact
uv run --active python -m v0.src.A0.fusion_parity   # ~20s, bit-exact parity
```

---

## Orchestration patterns learned

Things that worked:

1. **Multi-agent worktree isolation** + explicit scope matrices prevented file collisions across 9 parallel tracks.
2. **done.flag vs blocker.md mutual exclusion** (`v0/SHARED.md` protocol) gave clean pass/fail signal without ambiguity.
3. **Squash-merge per track** kept the integrated history linear and reviewable.
4. **Explicit brief with "MANDATORY READS" + "DO NOT TOUCH"** sections kept agents in their lane.

Things that tripped:

1. **Worktree base commit drift.** Agents were spawned on stale base commits (`13dc893`). Fix: always include "FIRST: rebase worktree" block in briefs.
2. **Gitignored artifacts don't merge.** Large ONNX files + built binaries live in gitignored dirs. When Track A needed A0's models, they weren't on the integrated mainline — had to symlink across worktrees. For future: standardize a "production path" for heavy artifacts (e.g. `~/Library/Application Support/<product>/`) and symlink there, or publish via release assets.
3. **`gh pr create` denied.** All branches land as local commits only; user creates PRs manually. Working as intended per security settings.
4. **HEREDOC commit messages break on apostrophes.** Switched to `git commit -F /tmp/msg.txt` pattern mid-session.
5. **Phase-1 smoke test with coverage gate alone is insufficient.** Coverage passing does NOT predict CoreML MLProgram compile success (see fusion experiment).

---

## How to pick this up next session

1. Read this doc + `v0/state/A/fusion_aborted.md` (if considering fusion revival).
2. Check current branch: `git log --oneline feat/harness-patterns ^0dc3b4a`.
3. Check `v0/state/*/done.flag` and `v0/state/*/blocker.md` for current track states.
4. Decide on the 4 pending items above.
5. For quick wins: option B (swap default to `htdemucs_6s`) is a 1-line change + binary rebuild. Gets v0 to sub-realtime in 30 min.
6. For production release: resolve skeleton.als, wire GitHub Secrets for signing, push tag.

### Quick commands

```bash
# Swap default model (option B)
$EDITOR v0/src/A/src/sf_demucs.hpp   # change DemucsVariant::Default
bash v0/build/build-native.sh --arch $(uname -m)
# re-validate:
~/Library/Application\ Support/StemForge/bin/stemforge-native split v0/tests/fixtures/short_loop.wav --out /tmp/sf_out

# Rebuild .pkg after skeleton.als lands
uv run python v0/src/als-builder/builder.py
bash v0/build/build-pkg.sh

# Push integrated work to origin (allowed by settings)
git push origin feat/harness-patterns
```
