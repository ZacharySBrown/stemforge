#!/usr/bin/env bash
# 04_collect.sh — tarball all fusion_debug outputs for transport.
set -eu
set -o pipefail

OUT_DIR="/tmp/sf_fusion_debug"
if [[ ! -d "$OUT_DIR" ]]; then
    echo "ERROR: $OUT_DIR does not exist — run 01/02/03 first." >&2
    exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
HOST="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
TARBALL="/tmp/sf_fusion_debug_${HOST}_${STAMP}.tar.gz"

# Include system context alongside the logs.
SYSINFO="$OUT_DIR/00_sysinfo.txt"
{
    echo "host: $HOST"
    echo "date: $(date -u +%FT%TZ)"
    echo "uname: $(uname -a)"
    echo "sw_vers:"
    sw_vers | sed 's/^/  /'
    echo "arch: $(arch)"
    echo "chip:"
    sysctl -n machdep.cpu.brand_string 2>/dev/null | sed 's/^/  /'
    echo "xcrun: $(xcrun --version 2>&1 | head -1)"
    echo "python: $(uv run --active python --version 2>&1)"
    echo "onnxruntime:"
    uv run --active python -c "import onnxruntime as o; print(' ', o.__version__); print(' providers:', o.get_available_providers())" 2>&1 | sed 's/^/  /'
    echo "git HEAD: $(git -C "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" rev-parse HEAD 2>/dev/null || echo '?')"
} > "$SYSINFO"

tar -czf "$TARBALL" -C "$(dirname "$OUT_DIR")" "$(basename "$OUT_DIR")"
echo ""
echo "tarball: $TARBALL"
echo "size:    $(du -sh "$TARBALL" | awk '{print $1}')"
echo ""
echo "Contents:"
tar -tzf "$TARBALL" | head -40
echo ""
echo "Bring that tarball back to the Intel machine and unpack with:"
echo "  tar -xzf $(basename "$TARBALL") -C /tmp/"
