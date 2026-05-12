#!/usr/bin/env bash
# refresh_mus_dump.sh — refresh the local mus library snapshot used by agents.
#
# Agents are sandbox-blocked from reading ~/mus directly. This script writes a
# tree snapshot to .local/mus/mus_tree.txt so agents can reason about library
# structure. Re-run whenever you reorganize ~/mus.
#
# Outputs:
#   .local/mus/mus_tree.txt   — every file under ~/mus, depth-unbounded.
#
# Does NOT touch:
#   .local/mus/mus_events.log — historical organize-event log (append-only).
#   .local/mus/mus_setup.md   — prose docs about the library setup.

set -euo pipefail

MUS_DIR="${HOME}/mus"
OUT_DIR="$(git rev-parse --show-toplevel)/.local/mus"
OUT_FILE="${OUT_DIR}/mus_tree.txt"

if [[ ! -d "${MUS_DIR}" ]]; then
  echo "error: ${MUS_DIR} not found" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"

# Full file list under ~/mus, relative paths, sorted.
( cd "${MUS_DIR}" && find . -type f | LC_ALL=C sort ) > "${OUT_FILE}"

echo "wrote $(wc -l < "${OUT_FILE}") lines to ${OUT_FILE}"
