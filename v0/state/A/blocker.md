# Track A — Blocker: A0's .onnx files missing from `v0/build/models/`

**Status:** Track A code is built, signed, all unit tests pass, NDJSON
emission validated against schema. However, end-to-end inference cannot
be verified because Track A0's ONNX model files are absent on disk.

## What Track A completed

- `v0/src/A/` — full C++ source tree (`libstemforge` static lib + CLI wrapper).
- `v0/build/include/stemforge.h` — **frozen C ABI** (v2 Max external links unchanged).
- `v0/build/libstemforge.a` — built, arm64, 457 KB (release -O3).
- `v0/build/stemforge-native` — built, ad-hoc codesigned with hardened
  runtime, arm64, 368 KB. Links `libonnxruntime.1.24.4.dylib` via
  `@executable_path/`.
- `v0/build/libonnxruntime.1.24.4.dylib` — ONNX Runtime shipped alongside.
- `v0/build/entitlements.plist` — hardened runtime + network.client only
  (no JIT, no executable memory).
- `v0/build/build-native.sh` — reproducible build (arch-configurable).
- 13 unit tests: **all pass** (STFT round-trip 120.7 dB SNR, NDJSON
  schema coverage for every event type + every progress phase, manifest
  byte-shape identical to Python writer, index.json dedup).
- Error-path NDJSON validated against `v0/interfaces/ndjson.schema.json`
  (3/3 valid events on a deliberate-failure split run).
- SHA256 integrity check verified (fake .onnx file rejected with the
  exact expected sha256 mismatch message).

## Blocker

`v0/build/models/manifest.json` declares these files and their SHAs:

| key | expected path |
|---|---|
| htdemucs_ft_head{0..3} | `v0/build/models/htdemucs_ft/htdemucs_ft.head{0..3}.onnx` |
| htdemucs_6s | `v0/build/models/htdemucs_6s/htdemucs_6s.onnx` |
| htdemucs | `v0/build/models/htdemucs/htdemucs.onnx` |
| ast_audioset | `v0/build/models/ast/ast_audioset.onnx` |
| clap_htsat_unfused | `v0/build/models/clap/clap.fp16.onnx` |

Only `manifest.json` and `clap_genre_embeddings.json` are present on disk:

```
$ ls -la v0/build/models/
-rw-r--r--  clap_genre_embeddings.json  (187 KB)
-rw-r--r--  manifest.json               (11 KB)
# No subdirs; no .onnx files.
```

A0's `v0/state/A0/done.flag` declares these files as artifacts, but they
appear to have been generated on another machine/branch and not pushed
to the integrated mainline (`feat/harness-patterns`, @ 4185448).

## Reproduce

```bash
STEMFORGE_MODEL_DIR=v0/build/models ./v0/build/stemforge-native split \
    /tmp/sf_fixture_sine.wav --json-events --out /tmp/sf_out
# → exit 5
# → {"event":"error","fatal":true,
#    "message":"model file missing: .../htdemucs_ft.head0.onnx",
#    "phase":"splitting"}
```

## Consequences for the `done.flag` schema

The brief specified these fields:

```json
{
  "completed_at": "...",
  "branch": "feat/v0-A-native",
  "binary_path": "v0/build/stemforge-native",
  "universal2": true/false,
  "codesigned": true/false,
  "coreml_ep_active": true/false,
  "demucs_latency_sec": <float>,
  "tests_pass": true
}
```

- `universal2`: **false** — arm64-only build. Reason: the ORT 1.24.4
  release channel doesn't ship a universal2 asset (only
  `onnxruntime-osx-arm64-*.tgz` and `onnxruntime-osx-x86_64-*.tgz`
  separately). `build-native.sh --universal` is wired to lipo the two
  arch binaries. x86_64 leg not built here (no x86 toolchain on this
  host; CI matrix per Track F handles it).
- `codesigned`: **true** (ad-hoc + hardened runtime). Developer ID signing
  is CI's job.
- `coreml_ep_active`: **unknown** — cannot verify without loadable .onnx
  files. CoreML EP configuration is wired per A0 README (MLProgram,
  MLComputeUnits=ALL, RequireStaticInputShapes=0) and gated on
  `manifest.coreml_ep_supported[model]`. A0's current manifest reports
  `coreml_ep_supported: false` for every model, so even when .onnx files
  land, our code will fall through to CPU EP per spec. This is a Track A0
  decision, not a Track A regression.
- `demucs_latency_sec`: **unknown** — no model, no latency measurement.
- `tests_pass`: **true** (13/13 unit tests; error-path NDJSON valid).

## Recommendation

**Unblock path 1 — preferred:** copy the A0 artifacts from whichever
branch/worktree they live on into `v0/build/models/<variant>/*.onnx`
(total ~1 GB for the full set). Then rerun:

```bash
cmake --build v0/src/A/build-test --target test  # 13/13 pass
STEMFORGE_MODEL_DIR=v0/build/models \
  ./v0/build/stemforge-native split tests/fixtures/<real_music>.wav \
  --json-events --out /tmp/sf_out
```

This should produce a complete stems.json, beat-sliced WAVs, and a CoreML
EP residency log under `ORT_LOGGING_LEVEL=VERBOSE`. If CoreML EP loads
successfully, Track A's `done.flag` can be written; if it doesn't, the
force-cpu-only path is already wired.

**Unblock path 2 — fallback:** run A0's export pipeline from
`v0/src/A0/demucs_export.py` on this machine and commit the .onnx files
to LFS (they're large; out of scope for me to do in Track A's lane).

**Unblock path 3 — cross-track dependency audit:** confirm whether A0 was
expected to leave .onnx files committed (huge-file policy?), gitignored,
or via a release-download step. If the latter, wire that download into
`build-native.sh` — the existing libcurl-free code path can use the same
urllib fetcher I used to vendor ORT.

## C ABI surface (frozen)

Per PIVOT §A, the ABI is frozen from this point — v2 links
`libstemforge.a` via `v0/build/include/stemforge.h` unchanged. Surface
emitted:

```c
sf_handle sf_create(const sf_config*);
void      sf_destroy(sf_handle);
const char *sf_version(void);
const char *sf_last_error(sf_handle);
void      sf_cancel(sf_handle);
sf_status sf_split(sf_handle, const char *input_wav, const char *out_dir,
                   sf_event_cb cb, void *user);
sf_status sf_forge(sf_handle, const char *input_wav,
                   const struct sf_pipeline *pipe,
                   sf_event_cb cb, void *user);
typedef void (*sf_event_cb)(const char *event_json, void *user);
```

`sf_config` carries `model_dir`, `log_level`, `num_threads`,
`force_cpu_only`, `demucs_variant` — and `_reserved[8]` future-proof
padding so v2 additions don't break ABI.

## Deviations from the brief's sketch

- `sf_pipeline` is forward-declared (struct yet to be defined by the
  forge YAML spec). `sf_forge(h, in, NULL, cb, u)` works in v0 and
  falls through to `sf_split` semantics.
- Added `sf_cancel()` because v2 Max devices need user-initiated cancel;
  cost is trivial (an atomic flag).
- Added `sf_version()` (strictly better than a macro).
- Added `sf_last_error()` — needed for CLI stderr reporting; harmless for
  v2.
- Used AudioToolbox for WAV I/O + sample-rate conversion in place of
  libsndfile + libsamplerate. Rationale: zero vendoring, native Apple
  resampler, cleaner rpath story. When Linux/Windows support lands post
  v0 we'll swap in dr_wav + speexdsp_resampler behind the same
  `sf_wav.hpp` API.
- Built arm64-only, not universal2, due to ORT release-asset channel
  (see above). `build-native.sh --universal` is in place for CI.

## Lines of code

```
src/sf_lib.cpp         ~200 LOC   (orchestration only, no business logic)
src/sf_ndjson.hpp       ~90 LOC
src/sf_manifest.hpp     ~90 LOC
src/sf_wav.hpp         ~130 LOC
src/sf_stft.hpp        ~250 LOC
src/sf_beat.hpp        ~240 LOC
src/sf_slicer.hpp       ~70 LOC
src/sf_model_manifest.hpp ~100 LOC
src/sf_demucs.hpp      ~300 LOC
cli/main.cpp           ~120 LOC   (PIVOT §A <200-LOC wrapper budget)
```

## Risks the Reviewer should check

1. **Beat tracker parity vs librosa.** `sf_beat.hpp` is a pragmatic
   onset-strength + Ellis-DP port, not a bit-exact librosa
   reproduction. Expect ±1 BPM and ±1-hop beat offsets. If Track G's
   golden fixtures demand tighter parity, wire aubio (vendored from
   source, not brew) or add a librosa-subprocess fallback that invokes
   `python3 -c "import librosa; ..."`.
2. **CoreML EP on models A0 flagged `coreml_ep_supported=false`.** Our
   code honours that flag and falls to CPU EP. If A0 re-runs its probe
   and turns the flag on, our MLProgram config is ready. If the user
   intends us to attempt CoreML regardless, that's a 1-line change
   (remove the `&& entry.coreml_ep_supported` guard in
   `build_session()`).
3. **Overlap-add window vs demucs default (transition=0.25).** We use a
   triangular window; demucs uses a hann-half-cosine ramp only on the
   overlap region. Audible seam risk at segment boundaries — verify
   against torch reference on first A0-artifacts-present integration
   run.
4. **STFT parity with demucs.spec.spectro.** Our implementation fuses
   demucs's explicit reflect-pad with torch.stft's `center=True` reflect
   pad. The 120.7 dB reconstruction SNR on sinusoidal input suggests
   framing is correct; the real test is a sample-level diff against
   `stemforge/_vendor/demucs_patched.py::apply_stft` on a golden fixture,
   which needs a model to run end-to-end.

## Next-session checklist

- [ ] Copy A0 .onnx files into `v0/build/models/<variant>/`.
- [ ] Run `./v0/build/stemforge-native split <short_loop>.wav
      --json-events --out /tmp/sf_out` under
      `ORT_LOGGING_LEVEL=VERBOSE` 2>&1 | grep CoreML.
- [ ] Measure end-to-end latency for the htdemucs_ft path.
- [ ] Replace `blocker.md` with `done.flag` carrying real numbers.
