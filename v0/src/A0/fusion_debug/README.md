# Fusion debug pack — run on M-series Mac

Four scripts for diagnosing the `htdemucs_ft` 4-head fusion CoreML MLProgram
compile failure (`SystemError: 20 / ENOTDIR`) documented in
`v0/state/A/fusion_aborted.md`.

All scripts write to `/tmp/sf_fusion_debug/` so `04_collect.sh` can tarball
the results for you to bring back to the Intel machine.

---

## Prerequisites (on the M-series)

```bash
cd <repo>
git fetch origin
git checkout feat/harness-patterns
git pull

# Make sure static ONNX heads exist (they live in a gitignored dir).
# If v0/build/models/htdemucs_ft/htdemucs_ft.head{0..3}_static.onnx are missing:
uv run --active python -m v0.src.A0.reexport_static \
    --models htdemucs_ft --skip-parity --skip-coreml

# Make sure the fused 697MB artifact exists; rebuild if not.
uv run --active python -m v0.src.A0.fuse_ft
#   → writes v0/build/models/htdemucs_ft/htdemucs_ft_fused.onnx (+ .data)

# Xcode command-line tools must be installed for xcrun coremlcompiler:
xcode-select -p   # should print a path
```

Expected wall time end-to-end: **~20–30 min**.

---

## Run order

```bash
mkdir -p /tmp/sf_fusion_debug
cd <repo>

# (1) Capture the REAL CoreML error — this is the big one.
bash v0/src/A0/fusion_debug/01_capture_mlpackage_error.sh

# (2) Rule out stale cache / deterministic path collisions.
uv run --active python v0/src/A0/fusion_debug/02_uuid_cache_retry.py

# (3) Try EnableOnSubgraphs=0 + explicit MLProgram variants.
uv run --active python v0/src/A0/fusion_debug/03_subgraphs_off_retry.py

# (4) Tarball everything for transport back to Intel.
bash v0/src/A0/fusion_debug/04_collect.sh
#   → writes /tmp/sf_fusion_debug_<hostname>_<timestamp>.tar.gz
```

---

## What each script does

### 01_capture_mlpackage_error.sh
Runs the 2-head smoke fusion to trigger the compile failure, finds the
`.mlpackage` CoreML EP just wrote, then runs `xcrun coremlcompiler compile`
on it manually. **This surfaces the actual CoreML error** instead of the
BSD `ENOTDIR` syscall we've been seeing. Output: `01_xcrun_error.log`.

### 02_uuid_cache_retry.py
Builds an ORT session on the 697MB fused graph with a UUID'd
`ModelCacheDirectory` — rules out "stale partial write from a previous
failed attempt" as root cause. Also runs one inference to trigger full
compile. Output: `02_uuid_cache.log` + `02_uuid_cache.json`.

### 03_subgraphs_off_retry.py
Tries four CoreML EP option combinations on the fused graph:
- `EnableOnSubgraphs=0` + `ModelFormat=MLProgram`
- `EnableOnSubgraphs=0` + `ModelFormat=NeuralNetwork`
- `EnableOnSubgraphs=1` + `ModelFormat=NeuralNetwork` (baseline reference)
- `MLComputeUnits=CPUOnly` (sanity: should always compile)

For each: logs compile outcome, provider fallback state, and inference time
if it loads. Output: `03_subgraphs_off.log` + `03_subgraphs_off.json`.

### 04_collect.sh
Tarballs `/tmp/sf_fusion_debug/` (logs + JSON summaries) into a single
artifact. Bring it back to the Intel machine and share the tarball.

---

## What to look for (quick triage)

Once `01_xcrun_error.log` exists, grep it first:

```bash
grep -iE "error|fail|unsupported|invalid" /tmp/sf_fusion_debug/01_xcrun_error.log | head -30
```

If it points at:
- **a specific op / layer** → the fusion is structurally incompatible (try Path F2 batch-dim)
- **a size / disk / path limit** → the 697MB bundle is tripping a bundle-bytes cap (fusion possibly salvageable by splitting initializers)
- **a bundle manifest / plist error** → ORT's MLPackage writer is producing invalid bundle metadata (ORT bug; file upstream)
- **nothing illuminating** → commit to Path F3 (parallel `Ort::Session` in C++)

Next, check `02` and `03`:
- If any row in `03_subgraphs_off.json` has `"coreml_compiled": true` → we have a working option combo, fusion is viable with that setting.
- If `02_uuid_cache.json` shows `coreml_compiled: true` → stale cache was the problem; wire UUID cache dirs into the C++ runtime.
- If every variant still fails → Path F2 or F3, per the handoff.
