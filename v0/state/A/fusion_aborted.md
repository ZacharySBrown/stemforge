# Track A.fusion — htdemucs_ft 4→1 ONNX fusion: ABORTED

**Branch:** `feat/v0-demucs-ft-fused` (from `feat/harness-patterns`)
**Date:** 2026-04-15
**Engineer:** fusion specialist session
**Status:** **Aborted — fused ONNX builds bit-exactly but CoreML MLProgram compile fails with SystemError 20.** Manifest defaults and binary untouched.

## TL;DR

Fusing the 4 specialist htdemucs_ft heads into one ONNX graph works
mathematically (bit-exact parity on CPU) but the resulting graph is rejected
by the CoreML Execution Provider at MLProgram compile time. The static
partition coverage is 96.4 % — identical to the single-head graph — so the
failure is **not** a supported-ops problem; it's a compile-phase defect
that surfaces only on multi-subgraph fused artifacts. The fusion is
therefore not a drop-in replacement for the 4-session bag on CoreML, and
the promised ~40 s wall-clock win on htdemucs_ft cannot be delivered
through this pathway without a CoreML-side fix.

The scaffolding (fusion_smoke, fuse_ft, fusion_parity) is committed as a
reproducible baseline. The 4 static heads and the built fused graph remain
on disk. The manifest still points at the 4 unfused heads. Binary
unchanged. `done.flag` unchanged.

## What was run

Single session on M-series macOS 15.4.0, arm64, ORT 1.24.4. All work in
the worktree `agent-a063d997`, new branch `feat/v0-demucs-ft-fused` off
`feat/harness-patterns@736e671`.

Prerequisites:
- Worktree started empty of v0/ content; `git checkout -B
  feat/v0-demucs-ft-fused feat/harness-patterns` populated it.
- `v0/build/models/htdemucs_ft/` was empty (no ONNX files checked in). The
  4 static heads were re-generated here by running
  `python -m v0.src.A0.reexport_static --models htdemucs_ft --skip-parity
  --skip-coreml` — each head exports in ~4 s, total ~16 s, yielding the 4
  x 174.3 MB files whose sha256 matches the Track A.coreml-opt manifest
  exactly (head0 `be575fc0960f…`, head1 `e815682b8fda…`, head2
  `3a49d5b3c4c6…`, head3 `2320d950ba42…`).
- `~/Library/Application Support/StemForge/` is NOT present on this host —
  the end-to-end symlinked-binary path documented in `done.flag` is not
  materialised. Phase 5 was therefore out of reach regardless of fusion
  outcome.

## Phase 1 — 2-head smoke test (PASS on coverage; compile failed)

`v0/src/A0/fusion_smoke.py` glues heads 0 + 1 with
`onnx.compose.merge_models` using `onnx.compose.add_prefix` to isolate
internal names and Identity fanout nodes on the shared `mix` / `z_cac`
inputs. Opset-imports are deduped post-merge (merge_models leaves two
`('', 17)` entries which CoreML EP rejects downstream).

Result on the 2-head fused graph:

| metric | value | criterion | verdict |
|---|---:|---:|:---:|
| total nodes | 2 978 | — | — |
| CoreML-supported nodes | 2 870 | — | — |
| **Partition coverage** | **96.4 %** | ≥ 90 % | **PASS** |
| CoreML partitions | 32 | — | — |
| MLProgram compile | FAIL | must succeed | **FAIL** |

Exact CoreML EP line from ORT verbose log:

```
[W:onnxruntime:, coreml_execution_provider.cc:113 GetCapability]
CoreMLExecutionProvider::GetCapability,
  number of partitions supported by CoreML: 32
  number of nodes in the graph: 2978
  number of nodes supported by CoreML: 2870
```

ORT then tries to build the MLModel and returns `SystemError : 20`
(ENOTDIR on BSD) with no further explanatory output. ORT falls back to
CPUExecutionProvider silently. The coverage gate passes; the implicit
"graph actually compiles" gate fails.

Per the task brief's explicit Phase 1 abort criterion (coverage < 90 %),
this is a **Phase 1 PASS** — the signal on which we were told to commit
to Phase 2 says green. That proved misleading: downstream MIL compile has
its own latent constraint that GetCapability doesn't surface.

## Phase 2 — 4-head full fusion (built successfully)

`v0/src/A0/fuse_ft.py` extends the 2-head approach:
1. Prefix all 4 heads (`h0__`, `h1__`, `h2__`, `h3__`), rename I/O.
2. Chain-merge with empty io_map.
3. Add Identity fanout from shared `mix` / `z_cac` to each head's
   renamed inputs.
4. Apply the I₄ specialist matrix via per-head `Gather(axis=1,
   indices=[i])` picking source i from head i's (1, 4, ...) output,
   then `Concat(axis=1)` along the source dim to reconstruct the 4-stem
   tensor. This is the mathematically-equivalent inlining of the bag
   weights matrix `[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]`.
5. Expose two graph outputs: `time_out_stacked` (1, 4, 2, 343 980) and
   `zout_cac_stacked` (1, 4, 4, 2 048, 336). The host still runs iSTFT
   on `zout_cac_stacked` and sums with `time_out_stacked` to get the
   final stems — identical post-processing to the unfused bag.

Artifact:

| field | value |
|---|---|
| path | `v0/build/models/htdemucs_ft/htdemucs_ft_fused.onnx` (+ `.data`) |
| onnx body | 25.8 MB |
| external data | 671.5 MB |
| **total** | **697.4 MB** |
| sha256 | `4a6f1d7861a83bd2162137fe67b353665b38a71b60c8a2a9c3090ec8e1b17621` |
| graph inputs | `mix` (1, 2, 343 980), `z_cac` (1, 4, 2 048, 336) |
| graph outputs | `time_out_stacked` (1, 4, 2, 343 980), `zout_cac_stacked` (1, 4, 4, 2 048, 336) |
| build time | 3.06 s |

Sanity pass — the graph is well-formed, passes `onnx.checker.check_model`,
and has exactly one opset_import entry `(onnx, 17)` after dedup.

## Phase 3 — Validation

### Parity (PASS, bit-exact)

`v0/src/A0/fusion_parity.py` feeds the same (mix, z_cac) tensors into
both the fused session and the 4 unfused head sessions (all CPU EP),
then compares per-stem.

| metric | value |
|---|---:|
| max abs err (time branch) | **0.0** |
| max abs err (zcac branch) | **0.0** |
| residual RMS dBFS (time) | **-240.0 (floor)** |
| parity gate (≤ -60 dBFS) | **PASS** |

Bit-exact per source 0..3. The Gather+Concat specialist wiring is a
numerical no-op against the head-i-emits-source-i behaviour of the
torch bag — exactly as designed.

### CPU-side latency (PASS)

| path | cold wall (10 s stereo, 1 segment) |
|---|---:|
| fused (1 session, CPU EP) | **7.60 s** |
| unfused bag (4 sessions sequential, CPU EP) | 10.44 s |
| **speedup** | **1.37×** |

Modest CPU win from shared graph-level optimisation + avoided per-session
init overhead. Not the 4× promised via CoreML, but still net-positive if
we shipped a CPU-only fused artifact.

### CoreML coverage (PASS)

Same methodology as Phase 1 but against the full 4-head fused graph:

| metric | value | criterion | verdict |
|---|---:|---:|:---:|
| total nodes | 5 944 | — | — |
| CoreML-supported nodes | 5 728 | — | — |
| **Partition coverage** | **96.4 %** | ≥ 90 % | **PASS** |
| CoreML partitions | 32 | — | — |

Verbose log excerpt preserved in
`v0/state/A/fusion_coreml_verbose.log`. Key line:

```
CoreMLExecutionProvider::GetCapability,
  number of partitions supported by CoreML: 32
  number of nodes in the graph: 5944
  number of nodes supported by CoreML: 5728
```

Note that the partition *count* did not scale with the fusion (32 partitions
for 1, 2 and 4 heads alike). CoreML EP's partitioner appears to
cluster the 4 parallel subgraphs into the same 32-partition topology as
a single head, which was the original ambition of fusion.

### CoreML MLProgram compile (FAIL)

The blocker. Same `SystemError : 20` as the 2-head smoke test:

```
*************** EP Error ***************
EP Error SystemError : 20 when using
[('CoreMLExecutionProvider',
   {'ModelFormat': 'MLProgram',
    'MLComputeUnits': 'ALL',
    'RequireStaticInputShapes': '1',
    'EnableOnSubgraphs': '1'}),
 'CPUExecutionProvider']
Falling back to ['CPUExecutionProvider'] and retrying.
```

Tried and not recovered by:
- Adding `ModelCacheDirectory` pointing at a fresh `/tmp/…` dir.
- Swapping `MLComputeUnits` to `CPUAndNeuralEngine`, `CPUAndGPU`,
  `CPUOnly`. The first attempt dirties the cache, subsequent attempts
  throw a follow-on compile error
  (`Failed to look up root model`) — cache-state issue, not root cause.
- Deduping `opset_import` entries (was a prime suspect but made no
  difference).
- Disabling EP fallback — ORT still falls back in this build
  (`disable_ep_fallback` session-config entry doesn't appear wired for
  per-provider compile failure in 1.24.4).

The CoreML framework's own stderr / NSLog output is not captured by
ORT's log redirection, so the actual `NSFileSystemError` root cause is
not visible from Python. Reproducing under Xcode Instruments or
`MLModel` diagnostics would likely surface it, but that's an in-depth
investigation outside this session's budget.

### CoreML latency (UNMEASURABLE)

Because compile falls back to CPU, any latency we'd collect from the
fused-session path in the Python probe would be the CPU number. Since we
already have CPU-path latency from Phase 3 §CPU-side latency (7.60 s),
reporting it here as "CoreML fused" would be misleading.

## Why this is a red-light abort, not a green-light ship

The primary motivation for fusion is the **4× CoreML session-load
amortisation** — one MLProgram compile (~10 s) instead of four (~40 s)
on the warm-cache end-to-end run. If CoreML compile fails on the fused
graph, we land on CPU and lose the per-segment 4× inference speedup that
the previous Track A.coreml-opt session already unlocked for the unfused
bag. The net effect would be:

- **Unfused status quo (shipping today):** warm wall ≈ 50 s (4 CoreML
  compile + 4 × 0.544 s inference per segment + overlap-add). Per
  `done.flag`.
- **Fused-if-it-shipped-CPU-only:** warm wall ≈ 7.6 s inference but lose
  CoreML acceleration entirely, so any future growth in segments also
  stays on CPU. Worse trajectory.
- **Fused with CoreML compile fixed:** target 10–12 s warm wall — **not
  measurable in this session.**

Flipping the manifest's default to `htdemucs_ft_fused` without
confirming the CoreML path works would be a latent regression: the fall-
back to CPU is silent (ORT prints a warning but the session still opens),
meaning end users would never know they lost acceleration until someone
timed it. That's exactly the "silent CPU fallback" failure mode that
Track A.coreml-opt just eliminated via the static-shape re-export. We
cannot re-introduce it.

## Recommendation (escalation to Architect)

Three viable paths forward, listed in priority order:

### 1. Keep the unfused 4-session bag as today's htdemucs_ft (default)

**Status quo is acceptable** if we accept the 50 s warm wall-clock as
an artefact of the v0 CLI one-shot model and trust PIVOT §D's promise
that the v2 M4L device (session-persistent) inverts the trade-off —
load once, many inferences, 4× per-segment speedup amortised.

No code changes. This is the do-nothing option.

### 2. Swap manifest `default_variant` to `htdemucs_6s` for v0

`htdemucs_6s` already hits 7.3 s warm wall-clock (well under the 12 s
target) with the same CoreML EP, and produces 6 stems instead of 4 (+
guitar, + piano). Downside: different separator model so may not match
the `htdemucs_ft` fine-tune quality on real music. Brief said this is
an OK abort-path call "if we think that's the right call"; I did NOT
make it, as this is a product-facing quality tradeoff the user should
choose.

If selected, the one-line change is in
`v0/build/models/manifest.json`:

```json
  "default_variant": "htdemucs_6s"
```

(NB: the current manifest doesn't carry an explicit `default_variant`
top-level — the default is encoded in `DemucsVariant::FT` /
`DemucsVariant::Default` in `sf_demucs.hpp`. Flipping requires source +
rebuild.)

### 3. Fix CoreML MLProgram compile and revive fusion

Investigate the actual NSLog error via:

- `ortrun --log_level=0 /path/to/fused.onnx` (if we build the ORT CLI
  against a debug dylib).
- Running the compile inside an Xcode Instruments "System Trace" or
  "CoreML" profile to capture MLProgram assembler output.
- Dumping the `mlpackage` that CoreML EP is trying to produce
  (`ORT_COREML_MLPACKAGE_DUMP` or similar — may need patching ORT) and
  running `coremlcompiler compile` on it manually for a direct CoreML
  compiler error.
- Testing whether `EnableOnSubgraphs=0` fixes it (may turn off the
  per-parallel-subgraph compile that's breaking).
- Removing the Identity fanout and instead embedding the shared inputs
  via `io_map` to a tiny source Identity-graph prepended with proper
  `merge_models` piping. Maybe CoreML dislikes multiple Identity nodes
  rooted at the graph input.
- Testing fusion via the **batch dimension**: stack the 4 heads'
  weights into a single torch `nn.Module` that batches over `dim=0`
  (so one graph sees B=4, not 4 graphs sharing inputs). Would need
  torch-side re-export rather than ONNX-side compose, but produces a
  structurally different (and probably more CoreML-friendly) graph.

Estimated effort: 1-2 day investigation unless the fix is trivial.

## Artifacts committed

**Scripts (v0/src/A0/):**
- `fusion_smoke.py` — Phase 1 2-head smoke test + CoreML coverage probe.
- `fuse_ft.py` — Phase 2 full 4-head fusion with I₄ specialist gather.
- `fusion_parity.py` — Phase 3 per-stem parity against unfused bag.

**Binaries (v0/build/models/htdemucs_ft/):**
- 4 x `htdemucs_ft.head{0..3}_static.onnx` — re-generated via
  `reexport_static.py`; sha256 matches existing manifest entries.
- `htdemucs_ft_fused.onnx` + `.onnx.data` — fused 4-head graph
  (697 MB total). **Left in tree but NOT added to manifest** until
  CoreML compile is fixed.

**State (v0/state/A/):**
- `fusion_aborted.md` — this file.
- `fusion_coreml_verbose.log` — full CoreML GetCapability + fallback
  log from the 4-head fused graph load.

**Untouched (per abort protocol):**
- `v0/build/models/manifest.json` — no new entry for the fused graph.
  Default variant unchanged.
- `v0/src/A/src/sf_demucs.hpp` — no fused-path fallback logic added.
- `v0/state/A/done.flag` — Track A.coreml-opt numbers remain canonical.
- `v0/build/stemforge-native` + dylib — not rebuilt. (Also not present
  on this host — unrelated to fusion.)
- `~/Library/Application Support/StemForge/` — not created; not
  touched.

## Reproducibility

From a fresh worktree on `feat/harness-patterns`:

```bash
# 1. branch + populate ONNX heads (~16 s)
git checkout -B feat/v0-demucs-ft-fused feat/harness-patterns
uv run --active python -m v0.src.A0.reexport_static \
    --models htdemucs_ft --skip-parity --skip-coreml

# 2. Phase 1 smoke (~3 s; expected PASS on coverage, FAIL at compile)
uv run --active python -m v0.src.A0.fusion_smoke

# 3. Phase 2 4-head fusion (~3 s; builds 697 MB artifact)
uv run --active python -m v0.src.A0.fuse_ft

# 4. Phase 3 parity (~20 s CPU; expected PASS at -240 dBFS)
uv run --active python -m v0.src.A0.fusion_parity
```

All four commands are hermetic to the repo — no further system
dependencies beyond ORT 1.24.4 + demucs pretrained weights, both
already present in the shared `.venv` at
`/Users/zak/zacharysbrown/stemforge/.venv`.
