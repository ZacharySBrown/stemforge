# Track A0 — ONNX Model Conversion + Parity Validation

**Gates:** Track A cannot start until A0 writes `done.flag`.
**Parallel with:** B, D, F (they don't touch models).

## Goal

Convert all three PyTorch / HuggingFace models used by StemForge to ONNX, validate numerical parity against the torch reference implementations, publish the `.onnx` files and their metadata to `v0/build/models/`.

## Inputs

- `stemforge/backends/demucs.py` — existing demucs wrapper (torch reference)
- `stemforge/analyzer.py` — existing CLAP + AST wrappers (torch reference)
- `stemforge/config.py` — model name → checkpoint mapping
- HuggingFace / Facebook public checkpoints (downloaded at build time, not committed)
- Test fixture: `tests/fixtures/short_loop.wav` (if missing, A0 creates a 30s silence+click WAV)

## Outputs

- `v0/build/models/htdemucs_ft.onnx` — **primary** (fine-tuned, highest-quality 4-stem)
- `v0/build/models/htdemucs_6s.onnx` — secondary (6-stem, required by analyzer routing)
- `v0/build/models/htdemucs.onnx` — fallback (fast 4-stem)
- `v0/build/models/clap_htsat_unfused.onnx` — genre classifier
- `v0/build/models/ast_audioset.onnx` — instrument classifier
- `v0/build/models/manifest.json` — `{model_name → {path, sha256, size, input_shape, output_shape, torch_ref_checkpoint, max_abs_err, max_rel_err}}`
- `v0/src/A0/convert.py` — reproducible conversion script (uses `torch.onnx.export` / `optimum.exporters.onnx`)
- `v0/src/A0/validate.py` — numerical parity harness
- `v0/state/A0/progress.ndjson`, `artifacts.json`, `done.flag`

## Subtasks

### A0.1 — Demucs → ONNX
Demucs is a hybrid time-frequency model. Known gotchas:
- Dynamic input length. Export with dynamic axes: `{"input": {0: "batch", 2: "samples"}}`.
- Uses complex STFT internally. `torch.onnx.export` with `opset_version >= 17` for `STFT` op, OR refactor the model to real/imag split before export.
- `htdemucs_ft` is a bag-of-models (4 finetuned models averaged). Either export each head separately and average at runtime, or fuse into one ONNX graph. Prefer fused for simplicity unless graph size blows up.
- Validate on a **10s drum loop** and a **30s full mix** — at least two fixtures, diverse content.

Parity target: `max_abs_err < 1e-3` on the separated stem waveforms, `max_rel_err < 1e-2`. Wider tolerance OK if user A/B listening confirms indistinguishability; log exact numbers either way.

### A0.2 — CLAP → ONNX
Use `optimum[exporters]` which has first-class CLAP audio-branch export. Only the audio encoder + projection head is needed (text branch is not used at inference in StemForge — genre labels are pre-embedded).

**Option:** bake text embeddings for the known genre prompts (`stemforge/analyzer.py:45-78`) into a JSON sidecar `v0/build/models/clap_genre_embeddings.json` so the ONNX graph only does audio→embedding and dot-product happens host-side. Smaller graph, same numerics.

Parity target: cosine similarity ≥ 0.999 between torch and ONNX audio embeddings on the full genre eval set.

### A0.3 — AST → ONNX
`MIT/ast-finetuned-audioset` is a standard HF `AutoModelForAudioClassification`. `optimum-cli export onnx --model MIT/ast-finetuned-audioset out/ast/` works off the shelf. Validate top-20 logits parity.

Parity target: top-5 labels identical, max logit absolute diff < 1e-3.

### A0.4 — Validation harness
`v0/src/A0/validate.py` loads both torch reference and ONNX, runs the same fixture through each, asserts parity thresholds. Writes `validation_report.json` per model. Fails loudly if any threshold breached.

### A0.5 — CoreML EP smoke test
For each `.onnx`, instantiate `ort.InferenceSession(..., providers=['CoreMLExecutionProvider', 'CPUExecutionProvider'])` on a representative Apple Silicon machine. Record:
- Whether CoreML EP loaded (`session.get_providers()`)
- Whether any op fell back to CPU (set `coreml_flags={"COREML_FLAG_ONLY_ENABLE_DEVICE_WITH_ANE": "1"}` and log what doesn't fit)
- Wall-clock latency on a 30s stereo @ 44.1kHz input

If Demucs has a critical op that CoreML EP doesn't support, document it in `blocker.md` with the op name and propose a workaround (graph rewrite, or CPU-EP fallback for just that model). Do **not** silently fall back without flagging.

### A0.7 — fp16 export investigation (v2 perf prep)
Apple Silicon's ANE is fp16-native. For each Demucs variant, attempt fp16 export:
```python
from onnxconverter_common import float16
model_fp16 = float16.convert_float_to_float16(onnx.load("htdemucs_ft.onnx"),
                                              keep_io_types=True)
```
Rerun validation with tightened listening-test criteria (null-test: invert fp16 output against fp32 output, RMS of residual must be inaudible — target < -60 dB). If passes, ship fp16 and record this in `manifest.json` as `precision: "fp16"`. If fails, ship fp32 and document in `v0/state/A0/fp16_report.md` which stems degraded.

Same investigation for CLAP / AST — these are classifiers so thresholds differ: top-1 label must match torch reference across a ≥200-sample eval set.

### A0.8 — int8 quantization investigation (speculative)
Only for AST + CLAP (Demucs is almost certainly too lossy). Use `onnxruntime.quantization.quantize_dynamic`. Ship only if top-1 accuracy on eval set is within 1% of fp32 reference. Skip entirely if non-trivial — this is a stretch goal.

### A0.6 — Manifest + publish
Write `v0/build/models/manifest.json`. Upload model artifacts to S3/R2/GitHub Release asset (Track F will wire the download URL; for now, just stage them locally). Record SHA256 for Track E's installer to verify on install.

## Acceptance

- All 5 `.onnx` files exist under `v0/build/models/`.
- `validate.py` passes all parity thresholds. Report committed to `v0/state/A0/validation_report.json`.
- CoreML EP successfully loads each model on Apple Silicon (M1+). Ops that fall back to CPU are enumerated.
- `manifest.json` conforms to schema (define inline in this track; Track A reads it).

## Risks

- **Demucs STFT export** — highest-risk item. Budget a full day iterating on opset / graph rewrites. Fallback: export Demucs with STFT done in Python wrapper (pre/post processing outside ONNX graph, only the learned network inside ONNX). Ugly but reliable.
- **CLAP multi-branch** — keep audio branch only; text stays torch-side (not shipped) or baked as a sidecar.
- **File sizes** — `htdemucs_ft` is a bag-of-4; fused ONNX could exceed 500MB. If it does, ship per-head ONNX + average at runtime (adds latency, reduces memory).

## Do not

- Do not convert LALAL.AI or Music.AI "models" — they are cloud APIs, there is nothing to convert.
- Do not ONNX-ify librosa (it's classical DSP; no model).
- Do not touch `stemforge/backends/demucs.py` behavior in ways that change `split` command output before A0.4 proves parity. A0 is additive only.

## Subagent Brief

You are implementing Track A0 (ONNX model conversion + parity) of StemForge ONNX-first v0.

**Read first:**
- `v0/PLAN.md`
- `v0/PIVOT.md` (overrides portions of PLAN.md)
- `v0/SHARED.md`
- `v0/tracks/A0-onnx-conversion.md` (this file)
- `stemforge/backends/demucs.py`, `stemforge/analyzer.py`, `stemforge/config.py`

**Produce:** files listed under *Outputs* above.

**Do not touch:** anything under `v0/interfaces/`, anything under any other track's `v0/state/<id>/`, any non-A0 source in `stemforge/`.

**On blocker:** write `v0/state/A0/blocker.md` with the model, the failing op / threshold, what you tried, and your recommendation.
