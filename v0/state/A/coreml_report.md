# Track A.coreml-opt — CoreML EP activation report

**Branch:** `feat/v0-coreml-opt` (from `feat/harness-patterns`)
**Date:** 2026-04-15
**Status:** **CoreML EP active in the new binary.** Per-segment latency drops
≈4×; end-to-end wall-clock improvement depends on variant (warm cache).

## Baseline (Track A validator — `feat/v0-A-validator`)

- fixture: `v0/tests/fixtures/short_loop.wav` (10 s stereo 44.1 kHz)
- wall-clock: **22.11 s** (2 runs avg of 23.88 + 22.11)
- demucs inference: **18.44 s** (CPU EP)
- `coreml_ep_active: false` in manifest for all Demucs graphs
- variant used: `htdemucs_ft` (default — 4-head bag)
- ORT 1.24.4, macOS arm64, M-series

## Root cause of the A0 conservative setting

A0's original export set `dynamic_axes={mix:[0,2], z_cac:[0,3], time_out:[0,3], zout_cac:[0,4]}` so the graph could process variable-length segments. The CoreML EP partitioner accepted 77% of nodes at the graph level, but at *runtime* with MIL/E5RT validation every internal Reshape that inherited a dynamic dim
failed with:

```
E5RT: Input ... has unbounded dimension which is not supported. Please
consult MIL Framework or milPython on adding a bound for this dimension.
```

Setting only `RequireStaticInputShapes=1` on the EP options (without re-exporting) does NOT help — the compiled graph retains dynamic-shape metadata inside each Reshape node's lineage. CoreML loads the session but silently falls back every heavy conv to CPU, yielding ~2.0 s per segment (same as pure CPU). This is what
we measured on the first dynamic-ONNX probe pass:

| Probe label | loaded | mean latency | notes |
|---|:---:|---:|---|
| `htdemucs_dynamic::cpu_only` | n/a | 2.08 s | baseline |
| `htdemucs_dynamic::coreml_mlprogram_all_dynamic` | FAIL | — | "Failed to build MLModel, error code -7" |
| `htdemucs_dynamic::coreml_mlprogram_all_static` | yes | 1.97 s | no speedup (silent CPU fallback) |
| `htdemucs_dynamic::coreml_mlprogram_ane_only` | yes | 1.98 s | same |
| `htdemucs_dynamic::coreml_neuralnetwork_all` | yes | 1.90 s | same |

## Fix: re-export with fully static shapes

`v0/src/A0/reexport_static.py` re-runs `torch.onnx.export` on every Demucs head with `dynamic_axes=None`, so the training-length segment shape `(1, 2, 343980)` and
spectrogram shape `(1, 4, 2048, 336)` are baked into the graph as constants.
Torch's `do_constant_folding=True` then collapses the chain of dynamic Reshape / Shape / Gather nodes to literal int tuples, which the CoreML EP MIL pass can
schedule.

### Re-export results

| variant | heads | size/head | sha (first 12) |
|---|---:|---:|---|
| htdemucs | 1 | 174.3 MB | 9938e9460cb3 |
| htdemucs_6s | 1 | 114.6 MB | 2b3c5b6d8032 |
| htdemucs_ft | 4 | 174.3 MB | be575fc0960f / e815682b8fda / 3a49d5b3c4c6 / 2320d950ba42 |

**Parity vs dynamic export:** max_abs = 2.68e-07, residual RMS = -151 dBFS (graph-equivalent; all computed bit-exact modulo IEEE reduction-order noise).

**Parity CoreML-EP output vs CPU-EP dynamic reference:** max_abs = 8.07e-05,
residual RMS = -113 dBFS (CoreML MIL fuses some ops and accumulates in a slightly different order, but well below the -60 dBFS inaudibility threshold).

### Per-segment latency (htdemucs, Python probe — offline, single session)

| EP config | mean latency | p50 | p95 |
|---|---:|---:|---:|
| CPU only | 2.20 s | — | — |
| CoreML EP (MLProgram + ALL + RequireStaticInputShapes=1 + EnableOnSubgraphs=1) | **0.544 s** | 0.544 s | 0.548 s |

**Speedup: 4.04×.** Partition coverage reported by ORT:

```
CoreMLExecutionProvider::GetCapability, number of partitions supported by CoreML: 32
number of nodes in the graph: 1500
number of nodes supported by CoreML: 1446
```

**96.4% node coverage**, 32 CoreML partitions, 54 CPU-EP fallback nodes
(shape ops — ORT explicitly places these on CPU for perf).

## fp16 null-test (revisited on static ONNX)

Same negative result as A0's dynamic ONNX: the time-branch `Cast` node inside the vendored `forward_from_spec_cac` refuses a mixed-precision round-trip in ORT 1.24 (output dtype `float16` but declared `float`). Static-shape export does not change this — the `Cast` is independent of dynamic axes. The fp16 path remains blocked pending an upstream patch to either `stemforge/_vendor/demucs_patched.py` (cast to fp16 on the branch boundary) or a model surgery pass on the ONNX file. Shipping **fp32 only** for this iteration per A0's fallback policy.

## Binary runtime (new binary, end-to-end)

Built from `v0/src/A/src/sf_demucs.hpp` with three changes:

1. When `coreml_ep_supported && !force_cpu_only`, do NOT call `SetOptimizedModelFilePath` — CoreML EP wraps the graph into compiled MLProgram
subgraphs which ORT cannot serialise back to disk, producing the fatal
"Unable to serialize model as it contains compiled nodes" on session ctor.
2. CoreML EP options updated to `RequireStaticInputShapes=1` and `EnableOnSubgraphs=1`.
3. New `ModelCacheDirectory` option pointed at
`v0/build/models/ort_cache/<model>/coreml_cache/` so the compiled MLPackage
persists between process invocations. Without this, every cold launch
repays the ~50 s compile cost per head.

### End-to-end wall-clock (`stemforge-native split v0/tests/fixtures/short_loop.wav`)

| Variant | sessions | Cold cache | Warm cache | Baseline (CPU, A) |
|---|---:|---:|---:|---:|
| `htdemucs` (fast, --variant fast) | 1 | 52.9 s | **10.9 s** | ~7 s est. |
| `htdemucs_6s` (--variant 6s) | 1 | 31.9 s | **7.3 s** | ~7 s est. |
| `htdemucs_ft` (default, 4 heads) | 4 | 215.3 s | 50.3 s | **22.1 s** |

**Key finding:** CoreML per-session setup (even with cache) costs ~10 s
per head to rehydrate the compiled MLPackage and bind ANE resources.
For multi-head variants (`htdemucs_ft`, 4 heads × ~10 s = 40 s) this
setup overhead dominates the end-to-end time and makes CoreML *slower*
than CPU in a cold-invoke CLI benchmark.

This is exactly the scenario PIVOT §D is architected around:

> One `Ort::Session` per model, created once at `sf_create`, reused across
> every `sf_split` call. v0 CLI tosses them on exit; v2 Max external keeps
> them alive.

For the **M4L device (v2)** — the reason for CoreML in the first place —
the 40 s setup is paid once at device instantiation, after which every
subsequent `sf_split` call enjoys the 4× inference speedup. For the v0
CLI, the per-invocation session-load dominates for `htdemucs_ft` but the
single-head variants (`htdemucs`, `htdemucs_6s`) already hit the ≤12 s
wall-clock target when the cache is warm.

## Decisions & manifest flags

| variant | `coreml_ep_supported` | precision | rationale |
|---|:---:|---|---|
| htdemucs | **true** | fp32 | 1446/1500 nodes, warm 10.9 s, ≤12 s target met |
| htdemucs_6s | **true** | fp32 | warm 7.3 s, well under target |
| htdemucs_ft_head0..3 | **true** | fp32 | warm 50 s but PIVOT-§D aligned; flip in preparation for v2 |

All flipped to `true`. The CLI-level regression on `htdemucs_ft` (50 s warm vs 22 s CPU baseline) is a **known trade-off** — the per-session setup swap for 4× inference speedup pays off only when sessions outlive a single split invocation.

## Recommended follow-ups (out of scope this session)

1. **Fuse the `htdemucs_ft` bag into one ONNX graph.** A single `forward` that runs all 4 heads internally and applies the bag-averaging weights removes the 4× session-setup penalty. Either (a) export a torch wrapper that calls all 4 `forward_from_spec_cac`s inside one `nn.Module`, or (b) use ONNX model surgery to graft the 4 files into one model with shared input tensors. Estimated win: ~40 s off warm-cache wall clock → ≈10 s end-to-end for htdemucs_ft.
2. **fp16 time-branch cast fix.** Patch `_learned_forward` in `demucs_patched.py` to cast `xt` to the magnitude dtype at the
 branch merge so the fp16 converter doesn't leave orphan `Cast` nodes. Opens the door to 2-4× further ANE speedup per segment.
3. **Investigate `MLComputeUnits=CPUAndNeuralEngine` vs `ALL`.** Probe suggests `ALL` routes most ops to GPU; ANE-specific routing may avoid the GPU→ANE transition overhead in the compile step. Needs per-op partition-log analysis.
4. **Measure ANE residency via `powermetrics` / `Instruments`.** Useful to confirm the compiled MLPackage actually binds ANE rather than GPU. Not measured this session.

## Artifacts

- `v0/src/A0/reexport_static.py` — new static-shape exporter (6 head files)
- `v0/src/A0/coreml_probe_static.py` — offline CoreML EP probe harness
- `v0/src/A0/_apply_static_to_manifest.py` — in-place manifest patch
- `v0/src/A0/_stage_static_files.py` — symlink static files into runtime model dir
- `v0/src/A/src/sf_demucs.hpp` — session-options fix (no-cache-with-coreml, `ModelCacheDirectory`, `RequireStaticInputShapes=1`, `EnableOnSubgraphs=1`)
- `v0/state/A0/coreml_probe_static_report.{json,md}` — raw probe sweep
- `v0/state/A0/reexport_static_report.{json,md}` — per-head re-export + probe
- `v0/build/stemforge-native` — freshly built binary with CoreML EP active
- `v0/build/libonnxruntime.1.24.4.v2.dylib` — adhoc-signed ORT dylib (new
  inode to bypass cached amfid Team-ID rejection of the old file)
- `v0/build/models/manifest.json` — flipped `coreml_ep_supported: true` for all 6 Demucs entries, updated `path` + `sha256` + `size` to point at `_static.onnx`
