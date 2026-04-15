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

### Demucs (`htdemucs*.onnx`)

**Current status — see `v0/state/A0/blocker.md`.** The in-graph STFT
export fails in torch 2.11 / onnxruntime 1.24 with opset 17. The
documented fallback is the external-STFT wrapper (STFT/iSTFT outside
ONNX, only the learned NN inside). The refactor requires a small
upstream change to `demucs/htdemucs.py` to expose the post-spectrogram
sub-forward. Track A should **not** start integration work on Demucs
until A0 writes `done.flag` without a `demucs` blocker entry.

If/when the external-STFT path lands, the C++ host will need to own:

| Step | What | Where |
|------|------|-------|
| 1 | Read 44.1 kHz stereo input | `libsndfile` or `AudioToolbox` |
| 2 | Chunk into 7.8 s (`39/5`-s) segments with 50 % overlap | Demucs `apply_model` replica |
| 3 | STFT: `n_fft=4096`, `hop=1024`, hann, center, reflect-pad | Accelerate vDSP or KissFFT |
| 4 | Feed `(mix, z_real, z_imag)` into one ONNX session per head | `Ort::Session::Run` |
| 5 | iSTFT of frequency-branch output | same STFT code reversed |
| 6 | Sum time-branch + iSTFT output per segment | SIMD add |
| 7 | Overlap-add reconstruct full-length stems | Demucs `apply_model` replica |
| 8 | Average the 4 heads of `htdemucs_ft` | element-wise mean |

Authoritative STFT parameters are locked in `demucs_export.STFT` and
exposed via `demucs_export.stft_params()`. Keep the C++ constants in sync.

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
