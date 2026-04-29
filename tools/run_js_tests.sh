#!/usr/bin/env bash
# Run StemForge's offline JS regression tests (Node stdlib only).
# Exits 0 on pass, non-zero on any failure.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Node 18+ required (uses `node:test`, `node:assert`).
if ! command -v node >/dev/null 2>&1; then
    echo "run_js_tests.sh: node not on PATH" >&2
    exit 2
fi

exec node tests/js_mocks/test_preset_resolution.test.js
