# PIVOT — ONNX-First (supersedes portions of v0/PLAN.md)

**Date:** 2026-04-14
**Author:** zak + Claude (reconciliation with feat/harness-patterns)

## Decision

The v0 plan as originally authored in `claude/review-packaging-strategy-NNuOc` deferred ONNX to v1 and used PyInstaller-frozen torch for v0. **We are skipping the PyInstaller path.** StemForge's first shippable M4L device will ship with ONNX Runtime + CoreML Execution Provider from day one.

## Why

- PyInstaller + torch + demucs is known finicky (600MB–1.2GB binaries, universal2 headaches, JIT entitlements, fragile hiddenimports). Time spent making that ship is time not spent on the actual performance story.
- CoreML EP via ONNX Runtime is the target architecture anyway. Two pipelines (PyInstaller now, ONNX later) is more work than one pipeline done once.
- User explicit preference: get to ONNX ASAP, autonomously.

## What this changes

| Doc / track | Status under ONNX-first |
|---|---|
| `v0/PLAN.md` — "Version Roadmap" table | **Superseded.** The "v1" row is now the thing we're building. |
| `v0/PLAN.md` — "What v0 ships" table | Track A artifact changes (see below). Others unchanged. |
| `v0/tracks/A-native-binary.md` | **Rewritten.** Now builds an ONNX Runtime C++ host, not a PyInstaller bundle. |
| `v0/tracks/A0-onnx-conversion.md` | **New.** Converts Demucs/CLAP/AST to ONNX, validates numerical parity with torch reference. Gates Track A. |
| `v0/tracks/B-package-split.md` | Minor. Native/core split lines shift: native target is `stemforge-native` (ONNX host), core stays Python for dev + cloud backends. |
| `v0/tracks/C-m4l-device.md` | **Unchanged.** NDJSON contract with the binary is identical. |
| `v0/tracks/D-als-template.md` | **Unchanged.** |
| `v0/tracks/E-installer.md` | Minor. `.pkg` bundles the ONNX host + ONNX model files in `~/Library/Application Support/StemForge/models/`. |
| `v0/tracks/F-cicd.md` | Minor. Matrix drops PyInstaller-specific steps; adds ONNX conversion + model validation job. |
| `v0/tracks/G-integration-tests.md` | Adds ONNX numerical-parity regression test. |
| `v0/interfaces/ndjson.schema.json` | **Unchanged.** Event contract is model-agnostic. |
| `v0/interfaces/tracks.yaml`, `device.yaml` | **Unchanged.** |
| `v0/SHARED.md` | **Unchanged.** Filesystem shared-memory convention still applies. |

## Models in scope

Three PyTorch / HuggingFace models ship as ONNX. **Quality over speed is the rule** — we ship the highest-fidelity variant in each family and let CoreML EP claw back performance.

1. **Demucs** — priority order:
   - **`htdemucs_ft`** (fine-tuned 4-stem: drums/bass/vocals/other) — **primary, highest quality in the Demucs family.** ~4× slower than base `htdemucs` on CPU; CoreML EP should reduce that gap.
   - **`htdemucs_6s`** (6-stem: adds guitar/piano) — **secondary**, required by the analyzer's auto-routing (`stemforge/analyzer.py:227`) and the "6stem" pipeline preset.
   - `htdemucs` (base 4-stem) — converted too but only as a speed fallback. Not the default.
   - *Explicitly not chasing:* MDX23 / BS-Roformer / other non-Demucs SOTA. Re-scope if the user asks.
2. **CLAP** — `laion/clap-htsat-unfused` (genre classification, from `stemforge/analyzer.py`). Use the unfused checkpoint as-is; it's already the reference quality.
3. **AST** — `MIT/ast-finetuned-audioset` (instrument detection, from `stemforge/analyzer.py`). Use the MIT reference checkpoint as-is.

**Default model for `stemforge split` should change to `htdemucs_ft`** (currently `htdemucs` per `stemforge/config.py:44`). Track A0 owns this config flip after numerical parity is proven.

**Out of scope for ONNX:**
- LALAL.AI, Music.AI backends — cloud APIs, no local inference
- librosa beat-tracking — classical DSP, no model
- Any future model not listed above — re-scope explicitly

## New DAG (Wave 1.5)

```
Wave 1 — interfaces  (unchanged)
   ▼
Wave 1.5 — A0 (ONNX conversion + parity tests)   ◄── NEW, gates A
   ▼
Wave 2 — A (native host) ║ B (pkg split) ║ D (als) ║ F (CI skel)   ║ runs in parallel
   ▼
Wave 3 — C (amxd)   gated on A
   ▼
Wave 4 — E (pkg)    gated on A + C + D
   ▼
Wave 5 — G (tests) ║ F (finish release wiring)
```

A0 must finish first because Track A needs validated `.onnx` files to test against. B/D/F can still run parallel to A0 — they don't touch models.

## Success criteria override

`v0/PLAN.md`'s "Acceptance Criteria" section still applies, plus one addition:

> 7. Running `stemforge-native split test.mp3 --json-events` performs inference using ONNX Runtime with CoreML EP active (verified via `ORT_LOGGING_LEVEL=VERBOSE` or profile output). No Python interpreter present in the bundled binary.

## v2 forward-compatibility (new constraints, applied now)

User directive: *"optimize this as much as humanly possible for v2."* v2 in the original roadmap = compiled Max external (`[stemforge~]`), ONNX in-process, no subprocess. To keep v2 a linking change and not a rewrite, Track A must obey these constraints **now**:

### A. Library-first architecture
- Inference + slicing + manifest logic ships as `libstemforge.a` (static) or `libstemforge.dylib` with a **stable C ABI**.
- `stemforge-native` is a ~200-line CLI wrapper that links the library. v2's Max external links the same library directly.
- C ABI surface (first draft — finalize in Track A.1):
  ```c
  typedef void (*sf_event_cb)(const char* event_json, void* user);
  sf_handle sf_create(const sf_config* cfg);
  int sf_split(sf_handle, const char* input_wav, const char* out_dir,
               sf_event_cb cb, void* user);
  int sf_forge(sf_handle, const char* input_wav, const sf_pipeline* pipe,
               sf_event_cb cb, void* user);
  void sf_destroy(sf_handle);
  ```
- No global state. Everything reentrant. Max externals may be instantiated multiple times per Live session.

### B. NDJSON is a serialization of the event stream, not the event stream itself
- CLI: the `sf_event_cb` callback emits one JSON line per event to stdout.
- v2 Max external: the same callback routes events to Max outlets via `outlet_anything()`.
- Same schema (`v0/interfaces/ndjson.schema.json`); different sink. Don't hardcode `printf` inside the library.

### C. Threading model designed for v2 now
- Inference runs on a dedicated worker thread. Never on the caller thread.
- Inter-thread communication: lock-free SPSC queue for events (library → caller), and a command queue (caller → library).
- Audio-thread safety: the library exposes *no* function that is safe to call from a real-time audio thread. Max externals schedule work via `defer_low()` — document this in the C ABI header.

### D. Session reuse
- One `Ort::Session` per model, created once at `sf_create`, reused across every `sf_split` call. v0 CLI tosses them on exit; v2 Max external keeps them alive. Don't embed session creation inside the split/forge call paths.

### E. Aggressive ONNX optimization (applies to A0 + A)
- `ORT_ENABLE_ALL` graph optimization, save optimized models to disk cache on first run (`sess_options.SetOptimizedModelFilePath(...)`).
- CoreML EP flags: enable ANE path where supported (`COREML_FLAG_USE_CPU_AND_GPU` for unsupported-op fallback, measure ANE residency).
- **Investigate** (A0.7 — new subtask): mixed-precision (`fp16`) export for Demucs. Apple Silicon ANE is fp16-native. Parity tolerance tightens *after* fp16 conversion — need listening test + numerical report. If fp16 fails parity, ship fp32 and flag.
- **Investigate** (A0.8 — new subtask): weight quantization. int8 dynamic quantization may work for AST/CLAP (classifiers, more tolerance) but likely too lossy for Demucs. Defer to a later track if non-trivial.
- Pre-allocate I/O buffers, use `OrtValue` pooling. No allocations in the hot loop.
- Build flags: `-O3 -flto -ffast-math` (audit `-ffast-math` impact on STFT/DSP correctness), strip symbols, static link everything.

### F. Profile-driven
- A0.5 smoke-test evolves into A.10 full-profile: per-stage latency breakdown (load, resample, STFT, inference, slicing, write) logged to `v0/state/A/perf.json`. Any regression in v2 compared to v0 is a bug.

### G. Don't do for v0 (explicit non-goals, to prevent scope creep):
- Streaming / chunked inference. Demucs v0 processes the full file in one shot.
- Real-time separation. v2 may add it; v0 does not.
- GPU support beyond CoreML (Metal, CUDA, DirectML). macOS-only, CoreML-only for v0.

## What is *not* changed

- Everything in `v0/SHARED.md` — filesystem coordination, done.flag, blocker.md, write lanes.
- NDJSON event contract (but see §B: now a serialization, not the primary API).
- Ableton template spec.
- Harness role / lane / skills model from `.claude/CLAUDE.md`.
