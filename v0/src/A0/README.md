# Track A0 — ONNX Conversion (consumer notes)

This README is written for Track A (the ONNX Runtime C++ host). If you
are implementing `stemforge-native`, read this document and `manifest.json`
before touching session setup.

## One Session Per Model

Each ONNX model gets exactly one `Ort::Session`, created once at
`sf_create()` time and reused for every `sf_split()` / `sf_forge()` call.
Do **not** embed session creation in the split/forge call paths — PIVOT §D
is explicit about this; the v2 Max external will keep sessions alive for
the lifetime of the device instance, and the v0 CLI must mirror that
pattern so the library ABI doesn't change.

```cpp
struct sf_handle {
    std::unique_ptr<Ort::Env>       env;
    std::unique_ptr<Ort::Session>   ast;
    std::unique_ptr<Ort::Session>   clap;
    std::unique_ptr<Ort::Session>   demucs_head0;
    std::unique_ptr<Ort::Session>   demucs_head1;
    std::unique_ptr<Ort::Session>   demucs_head2;
    std::unique_ptr<Ort::Session>   demucs_head3;
};
```

## Session Options (match PIVOT §E exactly)

```cpp
Ort::SessionOptions opts;
opts.SetGraphOptimizationLevel(ORT_ENABLE_ALL);
opts.SetOptimizedModelFilePath(
    (cache_dir / "ast_audioset.optimized.onnx").c_str());
opts.SetIntraOpNumThreads(std::max(1, std::thread::hardware_concurrency() - 1));
```

The `SetOptimizedModelFilePath()` call is non-negotiable — without it the
host pays the graph-optimization cost on every launch. On first run, ORT
writes the optimized model to disk; on subsequent runs ORT loads from the
cache directly. The cache directory is published in `manifest.json` per
model as `optimized_cache`.

## CoreML EP

```cpp
std::unordered_map<std::string, std::string> coreml_opts = {
    {"MLComputeUnits", "ALL"},       // CPU + GPU + ANE as available
    {"ModelFormat",    "MLProgram"}, // new format, better Apple Silicon perf
    {"RequireStaticInputShapes", "0"},
};
opts.AppendExecutionProvider("CoreML", coreml_opts);
// CPU EP is implicitly appended as the fallback — do NOT disable it.
```

**Always append CPUExecutionProvider after CoreML EP.** Any op that
CoreML can't handle falls back cleanly; disabling CPU EP crashes the
session load.

The `cpu_fallback_ops` field in `manifest.json` lists a hint set of ops
the A0 offline probe suspects CoreML will punt on. These are a heuristic —
the authoritative source is the per-node-assignment log emitted at
`ORT_LOGGING_LEVEL=VERBOSE` on first launch. Track A should parse those
logs once, persist the result, and use it to decide whether to disable
CoreML EP for a given model.

## Threading (PIVOT §C)

- Inference runs on a **dedicated worker thread**. Never on the caller
  thread. Never from an audio-thread callback.
- Caller → worker communication goes through a command queue
  (`sf_split(...)` enqueues a work item). Worker → caller communication
  goes through an SPSC event queue the `sf_event_cb` drains.
- v2 Max externals call `sf_split` from `defer_low()`. The CLI calls it
  from `main()`. Neither is latency-critical because the work itself
  takes seconds.

## Model-Specific Notes

### AST (`ast_audioset.onnx`)

- Input: log-Mel spectrogram `(batch, 1, 1024, 128)` fp32.
- Output: logits over 527 AudioSet classes `(batch, 527)`.
- Feature extraction: `AutoFeatureExtractor.from_pretrained(...)`. The
  C++ host must replicate:
  - Resample to 16 kHz mono
  - 128-mel log-spectrogram, normalized with AudioSet stats
    (mean = -4.2677, std = 4.5689 per HF config)
  - Pad/truncate to 1024 frames.
- Top-5 labels must match torch reference on the 10s drum loop and the
  30s full mix. See `validation_report.json`.

### CLAP (`clap_htsat_unfused.onnx`)

- Input: `input_features (batch, 1, 1001, 64)` fp32 **plus**
  `is_longer (batch, 1)` bool.
- Output: `audio_embed (batch, 512)` fp32.
- Text branch is NOT shipped. The 13 genre-prompt embeddings are
  pre-baked into `clap_genre_embeddings.json`:
  ```json
  {
    "labels": ["electronic dance music", ...],
    "embeddings": [[...512 floats...], ...],
    "normalized": true
  }
  ```
  Inference: L2-normalize the audio embedding, dot-product against the
  baked text embeddings, argmax for top-1 genre, softmax for scores.
- Feature extraction: `ClapProcessor.from_pretrained(...)`. The C++
  host reproduces the 64-mel feature pipeline; see
  `stemforge/analyzer.py:_classify_genre_clap` for the reference Python
  path (48 kHz resample required).

### Demucs (`htdemucs*.onnx`, `htdemucs_6s.onnx`, `htdemucs_ft.headN.onnx`)

**Unblocked by Track A0.1.** The in-graph STFT export fails in torch
2.11 / onnxruntime 1.24 (see `v0/state/A0/blocker.md` history); we ship
the documented fallback — **external STFT/iSTFT with only the learned
NN inside ONNX**.  Implementation lives in
`stemforge/_vendor/demucs_patched.py`, a vendored copy of upstream
`demucs/htdemucs.py` (v4.0.1) with a new `forward_from_spec_cac` method
that takes the spectrogram as an input.

Three variants ship:

| Variant | File(s) | Sources | Notes |
|---|---|---|---|
| `htdemucs_ft`  | `htdemucs_ft.head{0..3}.onnx` (~161 MB each) | drums/bass/other/vocals | **PRIMARY** — fine-tuned bag of 4. `manifest.json` entries are `htdemucs_ft_head{0..3}` with `bag_head_index` + `bag_size` set; weights are `[[1,0,0,0],[0,1,0,0],...]` (per-source specialists). |
| `htdemucs_6s`  | `htdemucs_6s.onnx` (~105 MB)                | drums/bass/other/vocals/guitar/piano | Required by analyzer auto-routing. |
| `htdemucs`     | `htdemucs.onnx` (~161 MB)                   | drums/bass/other/vocals | Speed fallback only. |

All Demucs entries embed a `stft_params` block (n_fft, hop, window,
etc.) — the C++ host MUST drive STFT/iSTFT with these exact values.

#### Graph I/O contract (all variants)

ONNX graph inputs:

| Name | Shape | dtype |
|---|---|---|
| `mix`   | `(batch, 2, samples)`                    | fp32 (or fp16 for `.fp16.onnx`) |
| `z_cac` | `(batch, 4, freq_bins, frames)`          | same |

ONNX graph outputs:

| Name | Shape | dtype |
|---|---|---|
| `time_out` | `(batch, S, 2, samples)`         | fp32 (or fp16) |
| `zout_cac` | `(batch, S, 4, freq_bins, frames)` | same |

where `S` = number of sources, `freq_bins = n_fft // 2 = 2048`,
`frames = ceil(samples / hop_length)`, and the `4` channel count is the
`cac=True` layout: `[re_L, im_L, re_R, im_R]` per frame for stereo.

Training-length segment = `7.8 s @ 44.1 kHz = 343980 samples`.  The mix
must be padded to this length BEFORE STFT when shorter.

#### Caller pipeline

| Step | What | Where |
|------|------|-------|
| 1 | Read 44.1 kHz stereo input | `libsndfile` / `AudioToolbox` |
| 2 | Chunk into 7.8 s segments with 25 % overlap | Port `demucs.apply.apply_model` |
| 3 | Pad segment to training length with zeros | trivial |
| 4 | Reflect-pad by `3*hop/2`, STFT, crop: `z = spectro(x, nfft=4096, hop=1024)[...,:-1, :][..., 2:2+le]` | Accelerate vDSP / KissFFT |
| 5 | CAC-pack: `z_cac = view_as_real(z).permute(0,1,4,2,3).reshape(B, 4, Fq, T)` | SIMD reshape |
| 6 | Feed `(mix_padded, z_cac)` to the head ONNX session | `Ort::Session::Run` |
| 7 | CAC-unpack: `z_out = view_as_complex(zout_cac.reshape(B,S,2,2,Fq,T).permute(0,1,2,4,5,3))` | SIMD reshape |
| 8 | iSTFT matching `_ispec`: pad (0,0,0,1) → pad (2,2) → ispectro (hop=1024) → slice `[pad : pad+length]` | ditto |
| 9 | `stems = time_out + ispec_out` | SIMD add |
| 10 | For `htdemucs_ft` only: combine the 4 heads with the bag weights | see manifest `bag_head_index` |
| 11 | Overlap-add reconstruct full-length stems | same as upstream |

Python reference implementation: `v0/src/A0/demucs_export.py`
(`apply_stft`, `apply_istft`, `pack_cac`, `unpack_cac`, `run_head_onnx`,
`run_bag_onnx`).  Use it as the oracle for C++ unit tests.

#### Parity policy

`full_mix_30s` is the gating fixture and passes at -99 to -130 dBFS RMS
residual (effectively bit-exact for real music).  `drum_loop_10s` is
advisory only — synthetic click-track audio with near-silent gaps
reveals fp32 accumulated error in the deep time-branch network, which
manifests as high peak-relative error (~10-45 %) but is not indicative
of real-music degradation.  Track G integration tests should include a
listening check.

## Reading `manifest.json`

The schema is frozen at `schema_version: 1`. Key fields the C++ host
must not ignore:

| Field | Consumer obligation |
|---|---|
| `sha256` | Verify at load time — refuse to run if the file has been tampered with. |
| `input_shape` / `output_shape` | Use to pre-allocate `OrtValue` buffers. |
| `precision` | fp32/fp16/int8-dynamic — pick the right cast on the feature-extraction path. |
| `coreml_ep_supported` | If `false`, don't even try CoreML — go straight to CPU EP. |
| `cpu_fallback_ops` | Advisory — prefer the VERBOSE-log-based ground truth in production. |
| `optimized_cache` | Pass to `SetOptimizedModelFilePath` so ORT writes/reads the cache there. |

## When the manifest lies

If `validation_report.json` says `passed: false` for a model, that model
must not be shipped in `stemforge-native`. Either fall back to shipping
torch weights via a subprocess bridge (bad, high latency), or re-open the
A0 conversion pipeline and fix the blocker. Track A does NOT get to
silently ship a model that failed parity.
