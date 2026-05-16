#!/usr/bin/env bash
# setup.sh — one-shot install of the full StemForge dev environment.
#
# Installs the `all` extra (Demucs / native stem split, beat-this neural
# tempo, audio classification, the configurator server, the EP-133 SysEx
# exporter, and the test/lint/build toolchain) plus the popup's npm deps.
#
# This is the cure for venv drift: `uv run` / `uv sync` with a narrower
# `--extra` set silently prunes packages, so always sync `--extra all`.
#
#   ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Python deps  (uv sync --extra all)"
uv sync --extra all

if [ -d web/configurator ]; then
    echo "==> Popup deps   (web/configurator: npm ci)"
    ( cd web/configurator && npm ci )
fi

cat <<'EOF'

StemForge dev environment ready.

  Python   — `uv run pytest`              run the suite
             `uv run stemforge forge X`   run the pipeline
  Popup    — `cd web/configurator && npm test`
  Device   — device-JS tests via the harness vitest config

The `all` extra omits `modal` (cloud-GPU backend) and `onnx` (native M4L
binary build) on purpose — install those separately if you need them:
  uv sync --extra all --extra modal      # or --extra onnx
EOF
