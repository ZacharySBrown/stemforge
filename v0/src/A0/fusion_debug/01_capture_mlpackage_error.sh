#!/usr/bin/env bash
# 01_capture_mlpackage_error.sh
#
# Capture the REAL CoreML compile error for the fused htdemucs_ft graph.
#
# ORT's CoreML EP reports SystemError: 20 (BSD ENOTDIR) because it's a syscall
# failure — the actual CoreML framework error is swallowed by NSLog. To see it
# we must invoke `xcrun coremlcompiler compile` on the .mlpackage directly.
#
# Strategy:
#   1. Clear CoreML caches + mark a timestamp.
#   2. Run fusion_smoke (2 heads) → triggers CoreML EP to materialize a
#      .mlpackage somewhere under ~/Library/Caches or the ORT cache dir.
#      The 2-head fusion reproduces the same compile failure mode as 4-head
#      (confirmed in fusion_aborted.md) and is much cheaper.
#   3. Also run fuse_ft + load the 697MB fused model so we have both artifacts.
#   4. Find newly-written .mlpackage bundles and run `xcrun coremlcompiler
#      compile` on each, capturing stdout + stderr.

set -u
set -o pipefail

OUT_DIR="/tmp/sf_fusion_debug"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/01_xcrun_error.log"
: > "$LOG"

log() { echo "[01] $*" | tee -a "$LOG"; }

log "==== 01_capture_mlpackage_error.sh starting $(date -u +%FT%TZ) ===="
log "repo root: $(git rev-parse --show-toplevel 2>/dev/null || pwd)"
log "uname: $(uname -a)"
log "xcrun version: $(xcrun --version 2>&1 | head -1)"
log ""

# --- 1. Clear caches + marker ------------------------------------------------
MARKER="$OUT_DIR/01_marker_$(date +%s)"
touch "$MARKER"
log "cache-clear marker: $MARKER"

# Don't nuke the whole CoreML cache — just our ORT cache subdir + /tmp fusion bits.
rm -rf /tmp/sf_fusion_* /tmp/sf_coreml_* 2>/dev/null || true
rm -rf v0/build/models/ort_cache/htdemucs_ft_fused* 2>/dev/null || true
log "cleared /tmp/sf_fusion_* /tmp/sf_coreml_* and ORT cache subdirs"
log ""

# --- 2. Run 2-head smoke to trigger compile failure --------------------------
log "---- running fusion_smoke (2-head) to reproduce compile failure ----"
uv run --active python -m v0.src.A0.fusion_smoke >> "$LOG" 2>&1 || \
    log "(fusion_smoke returned non-zero — expected)"
log ""

# --- 3. Also try loading the 4-head fused graph ------------------------------
FUSED="v0/build/models/htdemucs_ft/htdemucs_ft_fused.onnx"
if [[ -f "$FUSED" ]]; then
    log "---- loading 4-head fused graph ($FUSED) under CoreML EP ----"
    uv run --active python - <<'PY' >> "$LOG" 2>&1 || log "(4-head load returned non-zero — expected)"
import onnxruntime as ort
so = ort.SessionOptions()
so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
so.log_severity_level = 0
try:
    sess = ort.InferenceSession(
        "v0/build/models/htdemucs_ft/htdemucs_ft_fused.onnx",
        so,
        providers=[
            ("CoreMLExecutionProvider",
             {"ModelFormat": "MLProgram", "MLComputeUnits": "ALL",
              "RequireStaticInputShapes": "1"}),
            "CPUExecutionProvider",
        ],
    )
    print("4-head providers:", sess.get_providers())
except Exception as e:
    print(f"4-head load raised: {type(e).__name__}: {e}")
PY
else
    log "SKIP 4-head: $FUSED not found — run `uv run --active python -m v0.src.A0.fuse_ft` first"
fi
log ""

# --- 4. Locate newly-written .mlpackage bundles ------------------------------
log "---- searching for newly-written .mlpackage bundles ----"
# Typical locations:
#   ~/Library/Caches/com.apple.CoreML/*
#   ~/Library/Caches/com.github.microsoft.onnxruntime/*
#   v0/build/models/ort_cache/*
#   /tmp/ort.* /tmp/onnx*
CANDIDATE_ROOTS=(
    "$HOME/Library/Caches/com.apple.CoreML"
    "$HOME/Library/Caches/com.github.microsoft.onnxruntime"
    "$HOME/Library/Caches/onnxruntime"
    "v0/build/models/ort_cache"
    "/tmp"
)

FOUND_PACKAGES=()
for root in "${CANDIDATE_ROOTS[@]}"; do
    [[ -d "$root" ]] || continue
    # shellcheck disable=SC2207
    while IFS= read -r p; do
        FOUND_PACKAGES+=("$p")
    done < <(find "$root" -name "*.mlpackage" -newer "$MARKER" 2>/dev/null | head -20)
done

log "found ${#FOUND_PACKAGES[@]} .mlpackage bundle(s) written since marker"
for p in "${FOUND_PACKAGES[@]}"; do
    log "  $p  (size=$(du -sh "$p" 2>/dev/null | awk '{print $1}'))"
done
log ""

if [[ ${#FOUND_PACKAGES[@]} -eq 0 ]]; then
    log "WARNING: no .mlpackage bundles found — CoreML EP may not have written"
    log "one to a discoverable path, or compile may have failed before write."
    log "Check ORT verbose log in $LOG above for clues."
fi

# --- 5. Run xcrun coremlcompiler compile on each bundle ----------------------
COMPILE_OUT="$OUT_DIR/01_compiled"
mkdir -p "$COMPILE_OUT"

i=0
for pkg in "${FOUND_PACKAGES[@]}"; do
    i=$((i+1))
    log "---- xcrun coremlcompiler compile [$i/${#FOUND_PACKAGES[@]}] ----"
    log "  input: $pkg"
    dest="$COMPILE_OUT/pkg_${i}"
    mkdir -p "$dest"
    # Capture BOTH stdout + stderr; xcoremlcompiler uses both.
    set +e
    xcrun coremlcompiler compile "$pkg" "$dest" > "$OUT_DIR/01_xcrun_${i}.stdout" 2> "$OUT_DIR/01_xcrun_${i}.stderr"
    rc=$?
    set -e
    log "  rc=$rc"
    log "  stdout ($OUT_DIR/01_xcrun_${i}.stdout):"
    sed 's/^/    /' "$OUT_DIR/01_xcrun_${i}.stdout" | tee -a "$LOG"
    log "  stderr ($OUT_DIR/01_xcrun_${i}.stderr):"
    sed 's/^/    /' "$OUT_DIR/01_xcrun_${i}.stderr" | tee -a "$LOG"
    log ""
done

log "==== 01 DONE — primary log: $LOG ===="
log "(review $LOG then run 02_uuid_cache_retry.py)"
