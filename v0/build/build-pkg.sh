#!/bin/bash
# build-pkg.sh — assemble StemForge.pkg (unsigned dev build).
#
# Resolves upstream artifacts in this priority order:
#   1. v0/build/<name> in this worktree
#   2. v0/build/<name> in any sibling git worktree (harness multi-agent layout)
#
# If StemForge.als is missing (Track D pending on skeleton.als) we log a
# warning and build the .pkg without it. Rerun this script after D lands to
# bundle the template.
set -euo pipefail

VERSION="${STEMFORGE_VERSION:-0.0.0}"
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

WORK=$(mktemp -d -t stemforge-pkg)
trap 'rm -rf "$WORK"' EXIT

# ---------------------------------------------------------------------------
# Artifact resolution
# ---------------------------------------------------------------------------
resolve_artifact() {
    # $1 = filename (optionally with glob characters)
    # $2 = "required" | "optional"
    local name="$1"
    local mode="$2"
    local local_path="$REPO_ROOT/v0/build/$name"

    # Direct match (no glob).
    if [ -e "$local_path" ]; then
        echo "$local_path"
        return 0
    fi
    # Glob in local tree.
    local hit
    hit=$(ls -1 "$REPO_ROOT"/v0/build/$name 2>/dev/null | head -1 || true)
    if [ -n "$hit" ]; then
        echo "$hit"
        return 0
    fi
    # Search sibling worktrees (harness layout: .claude/worktrees/agent-*).
    local parent
    parent=$(dirname "$REPO_ROOT")
    # Walk up to find the shared repo + its siblings.
    for candidate_root in "$parent" "$parent/.." "$parent/../.."; do
        local found
        # shellcheck disable=SC2086
        found=$(ls -1 $candidate_root/*/v0/build/$name 2>/dev/null | head -1 || true)
        if [ -n "$found" ]; then
            echo "$found"
            return 0
        fi
    done

    if [ "$mode" = "required" ]; then
        echo "ERROR: required artifact not found: $name" >&2
        echo "Checked: $REPO_ROOT/v0/build/ and sibling worktrees." >&2
        return 1
    fi
    return 1
}

echo "==> Resolving upstream artifacts"
NATIVE=$(resolve_artifact "stemforge-native" required)
ORT_DYLIB=$(resolve_artifact "libonnxruntime*.dylib" required)
AMXD=$(resolve_artifact "StemForge.amxd" required)
ALS=$(resolve_artifact "StemForge.als" optional || true)
echo "    stemforge-native : $NATIVE"
echo "    onnxruntime dylib: $ORT_DYLIB"
echo "    StemForge.amxd   : $AMXD"
if [ -n "$ALS" ]; then
    echo "    StemForge.als    : $ALS"
    ALS_INCLUDED=true
else
    echo "    StemForge.als    : (missing — skeleton.als pending, template will not be bundled)"
    ALS_INCLUDED=false
fi

# ---------------------------------------------------------------------------
# Stage payloads
# ---------------------------------------------------------------------------
SYS_ROOT="$WORK/system"
USR_ROOT="$WORK/user"
mkdir -p "$SYS_ROOT/usr/local/bin" "$SYS_ROOT/usr/local/lib"
mkdir -p "$USR_ROOT/tmp/stemforge-staging"

cp "$NATIVE" "$SYS_ROOT/usr/local/bin/stemforge-native"
chmod 0755 "$SYS_ROOT/usr/local/bin/stemforge-native"
cp "$ORT_DYLIB" "$SYS_ROOT/usr/local/lib/"

# Uninstaller shipped as a system-scoped helper.
cp "$REPO_ROOT/v0/build/uninstall.sh" "$SYS_ROOT/usr/local/bin/stemforge-uninstall"
chmod 0755 "$SYS_ROOT/usr/local/bin/stemforge-uninstall"

cp "$AMXD" "$USR_ROOT/tmp/stemforge-staging/StemForge.amxd"
if [ -n "$ALS" ]; then
    cp "$ALS" "$USR_ROOT/tmp/stemforge-staging/StemForge.als"
fi

# ---------------------------------------------------------------------------
# Build per-component pkgs
# ---------------------------------------------------------------------------
SCRIPTS_DIR="$REPO_ROOT/v0/src/installer/scripts"
# Ensure scripts are executable inside the pkg payload.
chmod 0755 "$SCRIPTS_DIR/postinstall"

echo "==> pkgbuild: system component"
# Non-bundle payload (plain Mach-O + dylib), so no --component-plist is needed.
# BundleIsRelocatable only applies to bundle payloads (.app/.framework).
pkgbuild \
    --root "$SYS_ROOT" \
    --identifier com.stemforge.system \
    --version "$VERSION" \
    --install-location / \
    "$WORK/system.pkg"

echo "==> pkgbuild: user component (with postinstall)"
pkgbuild \
    --root "$USR_ROOT" \
    --identifier com.stemforge.user \
    --version "$VERSION" \
    --install-location / \
    --scripts "$SCRIPTS_DIR" \
    "$WORK/user.pkg"

# ---------------------------------------------------------------------------
# Combine with productbuild
# ---------------------------------------------------------------------------
OUT="$REPO_ROOT/v0/build/StemForge-$VERSION.pkg"
echo "==> productbuild: StemForge-$VERSION.pkg"
productbuild \
    --distribution "$REPO_ROOT/v0/src/installer/distribution.xml" \
    --package-path "$WORK" \
    "$OUT"

SIZE=$(stat -f%z "$OUT")
echo "==> Built $OUT ($SIZE bytes)"
echo "    als_included: $ALS_INCLUDED"
if [ "$ALS_INCLUDED" = "false" ]; then
    echo ""
    echo "    NOTE: Rerun this script after Track D lands StemForge.als to produce"
    echo "    a complete bundle (skeleton.als -> build_als.py -> v0/build/StemForge.als)."
fi
