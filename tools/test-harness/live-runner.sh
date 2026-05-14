#!/usr/bin/env bash
# live-runner.sh — Phase 5 Live-in-the-loop smoke suite wrapper.
#
# Wraps tools/test-harness/live_runner.py with preflight checks:
#   1. Ableton Live is installed (any 11/12 Suite/Standard/Beta).
#   2. StemForge.amxd is deployed (Max Package + Ableton User Library).
#   3. Configurator HTTP server is reachable (or print actionable error).
#
# Then hands off to the Python orchestrator.
#
# Usage:
#   tools/test-harness/live-runner.sh --help
#   tools/test-harness/live-runner.sh --list
#   tools/test-harness/live-runner.sh --all
#   tools/test-harness/live-runner.sh --test smoke_1_empty_boot
#   tools/test-harness/live-runner.sh --skip-fixture-check    # meta-tests
#   tools/test-harness/live-runner.sh --skip-preflight --all  # debugging
#
# Exit codes:
#   0  every non-skipped test passed
#   1  one or more tests failed
#   2  preflight check failed (no Live, no .amxd, no server)
#   64 bad arguments
#
# Per docs/configurator/EXECUTION_PLAN_v1.md Phase 5. Required reading:
# docs/configurator/SMOKE_TEST_GUIDE.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PY_RUNNER="${SCRIPT_DIR}/live_runner.py"
FIXTURES_DIR="${REPO_ROOT}/tests/fixtures/als"
PORT_FILE="${HOME}/stemforge/.configurator_port"
DEFAULT_PORT=7430

# Candidate Live install paths, in resolution order. Mirrors osa.CANDIDATE_APPS.
LIVE_APP_CANDIDATES=(
  "/Applications/Ableton Live 12 Beta.app"
  "/Applications/Ableton Live 12 Suite.app"
  "/Applications/Ableton Live 12 Standard.app"
  "/Applications/Ableton Live 11 Suite.app"
  "/Applications/Ableton Live 11 Standard.app"
)

usage() {
  cat <<'EOF'
live-runner.sh — StemForge Configurator Live-in-the-loop smoke suite

USAGE:
  live-runner.sh --help                       Show this message.
  live-runner.sh --list                       List all smoke tests and exit.
  live-runner.sh --all                        Run every smoke test.
  live-runner.sh --test <name>                Run one smoke (repeatable).
  live-runner.sh --skip-fixture-check         Meta-test mode — emit skips
                                              without opening Live.
  live-runner.sh --skip-preflight             Skip the Live/amxd/server
                                              install checks.

ENVIRONMENT:
  SF_LIVE_APP            Override Live .app path (default: auto-detect).
  SF_CONFIGURATOR_PORT   Override server port (default: read port file or 7430).
  SF_FIXTURES_DIR        Override fixtures dir (default: tests/fixtures/als).

EXIT CODES:
   0 — all non-skipped tests passed.
   1 — one or more tests failed.
   2 — preflight failed (Live not installed, .amxd missing, etc.).
  64 — bad arguments.

See docs/configurator/SMOKE_TEST_GUIDE.md for the full operator guide.
EOF
}

# Parse flags ahead of preflight so --help / --list work even without Live.
WANT_HELP=0
WANT_LIST=0
WANT_SKIP_PRE=0
WANT_SKIP_FIX=0
PASSTHROUGH=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      WANT_HELP=1
      shift
      ;;
    --list)
      WANT_LIST=1
      PASSTHROUGH+=("$1")
      shift
      ;;
    --skip-preflight)
      WANT_SKIP_PRE=1
      shift
      ;;
    --skip-fixture-check)
      WANT_SKIP_FIX=1
      PASSTHROUGH+=("$1")
      shift
      ;;
    *)
      PASSTHROUGH+=("$1")
      shift
      ;;
  esac
done

if [[ $WANT_HELP -eq 1 ]]; then
  usage
  exit 0
fi

# --list and --skip-fixture-check both bypass the preflight (the user
# is asking for static info / running meta-tests on a CI box without Live).
if [[ $WANT_LIST -eq 1 || $WANT_SKIP_FIX -eq 1 ]]; then
  WANT_SKIP_PRE=1
fi

# ── Preflight ────────────────────────────────────────────────────────────────

find_live_app() {
  if [[ -n "${SF_LIVE_APP:-}" ]]; then
    if [[ -d "$SF_LIVE_APP" ]]; then
      printf '%s' "$SF_LIVE_APP"
      return 0
    fi
    return 1
  fi
  for candidate in "${LIVE_APP_CANDIDATES[@]}"; do
    if [[ -d "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

resolve_port() {
  if [[ -n "${SF_CONFIGURATOR_PORT:-}" ]]; then
    printf '%s' "${SF_CONFIGURATOR_PORT}"
    return 0
  fi
  if [[ -f "$PORT_FILE" ]]; then
    local raw
    raw="$(tr -d '[:space:]' < "$PORT_FILE")"
    if [[ "$raw" =~ ^[0-9]+$ ]]; then
      printf '%s' "$raw"
      return 0
    fi
  fi
  printf '%s' "$DEFAULT_PORT"
}

preflight() {
  local rc=0

  printf '→ preflight 1/3: locate Ableton Live install...\n' >&2
  if LIVE_APP="$(find_live_app)"; then
    printf '  found: %s\n' "$LIVE_APP" >&2
  else
    printf '  ✗ no Ableton Live install found in:\n' >&2
    for c in "${LIVE_APP_CANDIDATES[@]}"; do
      printf '      %s\n' "$c" >&2
    done
    printf '    Set SF_LIVE_APP=/path/to/Ableton Live X Suite.app to override.\n' >&2
    rc=2
  fi

  printf '→ preflight 2/3: StemForge.amxd deployed...\n' >&2
  local pkg_dir="${HOME}/Documents/Max 9/Packages/StemForge"
  local pkg_dir_v8="${HOME}/Documents/Max 8/Packages/StemForge"
  if [[ -d "$pkg_dir" || -d "$pkg_dir_v8" ]]; then
    if [[ -d "$pkg_dir" ]]; then
      printf '  found: %s\n' "$pkg_dir" >&2
    else
      printf '  found: %s\n' "$pkg_dir_v8" >&2
    fi
  else
    printf '  ✗ StemForge Max package not installed. Run:\n' >&2
    printf '      uv run python tools/sf_deploy.py\n' >&2
    printf '    to install JS + .amxd to ~/Documents/Max 9/Packages/StemForge/\n' >&2
    rc=2
  fi

  printf '→ preflight 3/3: configurator HTTP server reachable...\n' >&2
  local port
  port="$(resolve_port)"
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS "http://127.0.0.1:${port}/healthz" --max-time 2 >/dev/null 2>&1; then
      printf '  found: http://127.0.0.1:%s/healthz responds OK\n' "$port" >&2
    else
      printf '  ✗ configurator server not responding on port %s.\n' "$port" >&2
      printf '    Open Live with StemForge.amxd → device autostarts the server,\n' >&2
      printf '    OR run manually: uv run python tools/m4l_configurator_server.py\n' >&2
      rc=2
    fi
  else
    printf '  (curl not installed — skipping server reachability check)\n' >&2
  fi

  return $rc
}

if [[ $WANT_SKIP_PRE -eq 0 ]]; then
  if ! preflight; then
    exit 2
  fi
fi

# ── Hand off to the Python orchestrator ──────────────────────────────────────

cd "$REPO_ROOT"

# Prefer uv if available (matches CLAUDE.md conventions); fall back to
# system python3 so --help works on minimal CI runners.
if command -v uv >/dev/null 2>&1; then
  exec uv run --extra dev python "$PY_RUNNER" "${PASSTHROUGH[@]}"
else
  exec python3 "$PY_RUNNER" "${PASSTHROUGH[@]}"
fi
