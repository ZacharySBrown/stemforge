# Track A — Native Inference Binary (ONNX Runtime + CoreML EP)

**Supersedes:** the original PyInstaller-based Track A. See `v0/PIVOT.md` for rationale.
**Gates:** requires Track A0 `done.flag` (validated `.onnx` files must exist).

## Goal

Produce a signed, notarized, universal2 macOS binary `stemforge-native` that runs the StemForge inference pipeline using **ONNX Runtime with CoreML Execution Provider**, no Python interpreter present.

## Approach

**Library-first** (v2 forward-compat, per `v0/PIVOT.md` §v2-forward-compat). The deliverable is `libstemforge` (static lib + stable C ABI header) *plus* a thin CLI wrapper `stemforge-native` that links it. v2's Max external will link the same library — this is the whole point.

C++ host program, single static binary where feasible. Links:

- ONNX Runtime (static libs, universal2, with CoreML EP enabled)
- libsndfile + libsamplerate (WAV I/O + resampling — replaces soundfile + librosa.resample)
- A small DSP module for STFT / beat tracking (replaces librosa beat_track — either port the Ellis algorithm in C++, or ship a second tiny binary `stemforge-beats` that embeds librosa via a minimal Python subset… prefer C++ port)
- nlohmann/json for NDJSON emission + manifest writing
- libcurl (static) for model weight download on first run (if not bundled)
- ffmpeg (universal2 static) bundled alongside for non-WAV input formats — same as original plan

No Python at runtime. Cloud backends (LALAL.AI, Music.AI) are **not** in this binary; they stay in the Python `stemforge` CLI for dev use. The shipped binary only does local inference (the ONNX Demucs path) + slicing + manifest.

## Inputs

- `v0/build/models/*.onnx` from Track A0
- `v0/interfaces/ndjson.schema.json` — event contract
- `stemforge/cli.py` (read-only reference — port `forge` / `split` command flow)
- `stemforge/slicer.py` (read-only reference — port beat/bar slicing logic)
- `stemforge/manifest.py` or equivalent (read-only reference — port manifest writing)
- Apple Developer ID Application certificate (CI secret)

## Outputs

- `v0/build/libstemforge.a` — universal2 static library (the actual work)
- `v0/build/include/stemforge.h` — stable C ABI header (frozen after A.1; v2 must link unmodified)
- `v0/build/stemforge-native` — universal2 Mach-O binary (CLI wrapper over libstemforge), signed, notarized
- `v0/src/A/` — C++ source tree (CMake-based, `libstemforge` + `stemforge-native` as two targets)
- `v0/src/A/CMakeLists.txt`
- `v0/build/build-native.sh` — reproducible build script (cmake + codesign + notarize)
- `v0/build/entitlements.plist`
- `v0/state/A/artifacts.json` — metadata
- `v0/state/A/done.flag`

## Subtasks

### A.1 — C++ host skeleton
- `main()` parses subcommand: `split`, `forge`, `--version`, `--json-events`
- Emits NDJSON to stdout conforming to `v0/interfaces/ndjson.schema.json`
- No Rich-style output; if `--json-events` is absent, emits minimal human-readable progress to stderr only
- Exit codes match Python CLI conventions

### A.2 — Model loader
- Reads `v0/build/models/manifest.json` at runtime from `~/Library/Application Support/StemForge/models/` (or `$STEMFORGE_MODEL_DIR` override for dev)
- Verifies SHA256 against manifest before loading
- Constructs `Ort::SessionOptions` with `SessionOptionsAppendExecutionProvider_CoreML` (flags: use ANE when possible, fall back gracefully to CPU EP per-op)
- Caches sessions across invocations if run as daemon (not v1; single-shot is fine)

### A.3 — Demucs inference path
- Load WAV via libsndfile; resample to 44.1kHz stereo if needed (libsamplerate)
- Feed into ONNX Demucs session. If `htdemucs_ft` is bag-of-heads, run each head, average outputs.
- Write each separated stem to `~/stemforge/processed/<track>/<stem>.wav`
- Emit `stem` NDJSON events per stem

### A.4 — Beat tracking + slicing
- Port the Ellis onset+tempo algorithm used by librosa, or use aubio (C library, liberal license). **Prefer aubio** — well-tested, permissive, no Python baggage.
- BPM detection → emit `bpm` event
- Beat-grid + bar-level slicing per `stemforge/slicer.py` logic
- Write slice WAVs to `<stem>_beats/` dirs; emit `slice_dir` events

### A.5 — Manifest writer
- Emit `stems.json` matching existing schema (crib from `stemforge/manifest.py` or wherever it lives — read-only reference, port to C++)
- Must be byte-for-byte schema-compatible with Python output so Track C's .amxd loader doesn't care which produced it

### A.6 — First-run model download
- If `~/Library/Application Support/StemForge/models/` missing or SHA mismatch, fetch ONNX files from release URL (Track F provides URL via a build-time `#define` or config file)
- Emit `progress phase=downloading_weights pct=…` events during download

### A.7 — Universal2 build
- Two arch slices built separately on x86_64 and arm64 runners (or cross-compile via CMake osx architectures), then `lipo -create`. See original Track F brief for CI matrix.
- ONNX Runtime publishes universal2 release assets — use those to skip cross-arch pain.

### A.8 — Codesign + notarize
Same as original plan:
```bash
codesign --force --deep --options runtime \
  --entitlements entitlements.plist \
  --sign "$CODESIGN_ID" v0/build/stemforge-native
ditto -c -k --keepParent v0/build/stemforge-native v0/build/stemforge-native.zip
xcrun notarytool submit v0/build/stemforge-native.zip \
  --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APP_PW" --wait
xcrun stapler staple v0/build/stemforge-native
```

Entitlements are simpler than PyInstaller — **no JIT needed** (ONNX Runtime is AOT). Probably just hardened runtime + network (for model download).

### A.9 — Self-test
```bash
./stemforge-native split tests/fixtures/short_loop.wav --json-events 2>/dev/null \
  | jq -c 'select(.event)' \
  | v0/tests/validate-ndjson.py
# then:
diff <(jq -S . ~/stemforge/processed/short_loop/stems.json) \
     <(jq -S . v0/tests/golden/short_loop.stems.json)
```

## Acceptance

- `file v0/build/stemforge-native` → universal2 Mach-O
- `codesign -dvv` → valid Developer ID
- `spctl -a -t exec` → accepted
- `--version` prints + exit 0
- `split test.wav --json-events` emits valid NDJSON, produces stems.json matching golden fixture (within float tolerance)
- `ORT_LOGGING_LEVEL=VERBOSE ./stemforge-native split …` shows CoreML EP actively executing Demucs ops (not full CPU fallback)
- Binary runs on freshly-imaged Mac — no Homebrew, no Python, no Xcode tooling

## Risks

- **C++ port of slicing / beat tracking is real work** — aubio gives us BPM but the bar-level slicing + curation logic in `stemforge/slicer.py` + `stemforge/curator.py` is non-trivial. Budget 2–3 days. Alternative: keep slicer in Python and embed CPython via `Py_Initialize` in the host — but that defeats the "no Python" goal. Prefer the C++ port.
- **ONNX Runtime binary size** — ~40MB. Add Demucs `.onnx` (100–500MB) and we're in the 150–600MB range. Still smaller than PyInstaller would have been.
- **ORT CoreML EP op coverage** — some Demucs ops may fall back to CPU. A0.5 flags this; A then accepts whatever A0 greenlit.

## Subagent Brief

You are implementing Track A (native ONNX host) of StemForge v0.

**Read first:**
- `v0/PLAN.md`, `v0/PIVOT.md`, `v0/SHARED.md`, this file
- `v0/interfaces/ndjson.schema.json`
- `v0/state/A0/artifacts.json` (the model manifest A0 produced)
- `stemforge/cli.py`, `stemforge/slicer.py`, `stemforge/curator.py`, `stemforge/backends/demucs.py` — read to port

**Produce:** files under *Outputs* above.

**Do not touch:** `stemforge/**` (Python source is read-only reference — if Python needs changes for `--json-events` parity, open a blocker and escalate), `v0/interfaces/**`, other tracks' state dirs, the `.onnx` files (those are A0's artifacts).

**Constraints:**
- Binary must run without any env vars set.
- NDJSON output must validate against schema on every code path (including error paths).

**On blocker:** write `v0/state/A/blocker.md` with specifics. Do not partially commit a broken binary.
