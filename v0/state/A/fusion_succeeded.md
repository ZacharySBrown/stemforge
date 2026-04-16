# Track A.fusion — htdemucs_ft 4→1 ONNX fusion: SUCCEEDED

**Branch:** `feat/harness-patterns`
**Date:** 2026-04-15 (root cause found) → 2026-04-16 (baked in + integrated)
**Status:** **Shipped — fused graph compiles under CoreML EP MLProgram, 4.54s warm inference per 10s segment vs 50s baseline (11x speedup).**

## Result

| variant | per-segment warm | session-load (cold) | sessions | EP |
|---|---:|---:|---:|---|
| htdemucs_ft (4-head bag, fallback) | ~50s | 4 × ~10s = 40s | 4 | CoreML (when each compile succeeds) |
| **htdemucs_ft_fused (DEFAULT)** | **4.54s** | **125s once, cached after** | **1** | **CoreML MLProgram** |

The previous `fusion_aborted.md` (now superseded) declared this path dead because the graph silently fell back to CPU with `SystemError: 20`. That diagnosis was wrong on **both** counts — it wasn't a CoreML compile-size limit, and the partition-coverage gate WAS predictive. See "Why the original abort was wrong" below.

## Root cause of the original failure

The fused graph had a leaked `dim_param` on `time_out_stacked` axis 2 (channel). The output value_info read `?Addtime_out_dim_2`, which made CoreML EP refuse the entire graph at `GetCapability` time — silent fallback to CPU, no compile attempted. ORT's lenient "I'll take it anyway" merge then masked the failure mode.

Two compounding factors made this hard to debug:

1. **ORT does not surface CoreML framework stderr (NSLog).** The actual `NSFileSystemError` was invisible from Python.
2. **`SystemError: 20` (BSD `ENOTDIR`) is misleading.** It's not a compile error — it's CoreML EP failing to construct its `.mlpackage` cache path because no graph nodes were claimed for compilation in the first place.

## The fix

Two-part change in `v0/src/A0/fuse_ft.py`:

1. **Hardcode the output value_info to topologically-correct static shape.** Derived from the (already-static) graph inputs:
   - `time_out_stacked = [mix.batch, 4, mix.channels, mix.samples] = [1, 4, 2, 343980]`
   - `zout_cac_stacked = [zcac.batch, 4, zcac.sources, zcac.freq, zcac.frames] = [1, 4, 4, 2048, 336]`
2. **Save inline (no `.data` sidecar).** Discovered during this triage: **CoreML EP MLProgram compile rejects ONNX models that load weights from external `.data` files** with the same `SystemError: 20`. Same graph, identical bytes, just split file → CoreML refuses.

| variant | output rank | save mode | CoreML result |
|---|---|---|---|
| dynamic shape | 4 (with `?` axis) | external | `SystemError: 20`, fallback to CPU |
| static `[1,4,2,343980]` | 4 | external | `SystemError: 20`, fallback to CPU |
| static `[4,2,343980]` (rank-3) | 3 | inline | claims, compiles in 125s, lenient-merge warning |
| **static `[1,4,2,343980]`** | **4** | **inline** | **claims, compiles in 125s, no warnings** |

Yesterday's breakthrough snippet happened to use rank-3 + inline. Both were assumed necessary. Only inline was — the rank-3 trick triggered an unwanted `MergeShapeInfo` lenient-merge warning that we've now eliminated.

## Why the original abort was wrong

`fusion_aborted.md` claimed:

> "the resulting graph is rejected by the CoreML Execution Provider at MLProgram compile time."

It wasn't compile time. It was `GetCapability` time — before any compile attempt. The original triage saw `partition coverage = 96.4%` (5728/5944 nodes) and concluded the static analysis passed but the compile gate didn't. In fact:

- `GetCapability` ran **after** ORT's lenient-merge papered over the dynamic axis, so the partition count looked normal.
- Then `.mlpackage` allocation hit the dynamic axis (now exposed in the actual subgraph) and bailed.

The aborted doc's "Three viable paths forward" recommendations (status quo, swap to `htdemucs_6s`, fix CoreML compile) all assumed the wrong root cause. None of those paths is needed.

## Verification

```
providers: ['CoreMLExecutionProvider', 'CPUExecutionProvider']
session load + compile (cold): 125.0s    ← one-time, cached for subsequent loads
warm inference: 4.54s per 10s segment    ← target was ~5s, we beat it
output shapes: (1, 4, 2, 343980), (1, 4, 4, 2048, 336)   ← canonical
```

Artifact:
- `v0/build/models/htdemucs_ft/htdemucs_ft_fused.onnx` — 697 MB single inline file
- sha256: `71828190efe191a622f9c9273471de1458fe0e108f277872d43c5c81cbe29ce9`

## Integration

- Manifest entry added: `htdemucs_ft_fused` (see `v0/build/models/manifest.json`).
- C++ runtime: new `DemucsVariant::FTFused` enum value, `SF_DEMUCS_DEFAULT` rerouted to it, `SF_DEMUCS_FT` retained as the unfused-bag fallback.
- CLI: `--variant ft-fused` accepted.
- Postinstall warmup pending (gh-issue #8) so users don't see the 125s first-load pause.

## Bonus finding

`onnx.save(..., save_as_external_data=True)` **appends** to existing `.data` sidecars rather than truncating. Each rebuild silently 2-3xs the sidecar size (671MB → 1.3GB → 2.0GB → 2.7GB across consecutive rebuilds). `fuse_ft.py` now `unlink()`s the sidecar before each save.
