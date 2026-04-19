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

VERSION="${STEMFORGE_VERSION:-0.0.1}"
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

WORK=$(mktemp -d -t stemforge-pkg)
trap 'rm -rf "$WORK"' EXIT

# ---------------------------------------------------------------------------
# Artifact resolution
# ---------------------------------------------------------------------------
_resolve_from_roots() {
    # Generic path resolver. Takes a subtree prefix (e.g. "v0/build" or
    # "v0/src/m4l-js") and a filename (optionally globbed), checks the current
    # worktree first, then the parent repo + any sibling worktrees under
    # .claude/worktrees/. Emits the first hit on stdout.
    #
    # $1 = subtree prefix (no trailing slash)
    # $2 = filename (may contain glob)
    local subtree="$1"
    local name="$2"

    local local_path="$REPO_ROOT/$subtree/$name"
    if [ -e "$local_path" ]; then
        echo "$local_path"
        return 0
    fi
    local hit
    hit=$(ls -1 "$REPO_ROOT"/$subtree/$name 2>/dev/null | head -1 || true)
    if [ -n "$hit" ]; then
        echo "$hit"
        return 0
    fi

    # Walk upward looking for the main repo first, then any sibling
    # worktrees. REPO_ROOT from a harness worktree is e.g.
    # <main>/.claude/worktrees/agent-*; from the main repo it's <main>.
    # Priority:
    #   1. this worktree               (already checked above)
    #   2. main repo (parent of .claude/worktrees, if we're in one)
    #   3. sibling worktrees under .claude/worktrees
    # Checking the main repo before siblings avoids picking up stale / broken
    # artifacts (e.g. a pre-fusion sibling's htdemucs_ft_fused.onnx + .data).
    local parent grandparent greatgrand
    parent=$(dirname "$REPO_ROOT")
    grandparent=$(dirname "$parent")
    greatgrand=$(dirname "$grandparent")

    # Priority 2: direct parent-repo hits (the main repo when we're in a
    # worktree). $greatgrand is /Users/.../stemforge when REPO_ROOT is
    # /Users/.../stemforge/.claude/worktrees/agent-*. $grandparent is
    # /Users/.../stemforge/.claude. $parent is /Users/.../stemforge/.claude/worktrees.
    local candidate
    for candidate in "$greatgrand" "$grandparent" "$parent"; do
        local direct
        # shellcheck disable=SC2086
        direct=$(ls -1 $candidate/$subtree/$name 2>/dev/null | head -1 || true)
        if [ -n "$direct" ]; then
            echo "$direct"
            return 0
        fi
    done

    # Priority 3: sibling worktrees (one-level-down wildcard).
    for candidate in "$parent" "$grandparent" "$greatgrand"; do
        local sibling
        # shellcheck disable=SC2086
        sibling=$(ls -1 $candidate/*/$subtree/$name 2>/dev/null | head -1 || true)
        if [ -n "$sibling" ]; then
            echo "$sibling"
            return 0
        fi
    done

    return 1
}

resolve_artifact() {
    # $1 = filename (optionally with glob characters), relative to v0/build/
    # $2 = "required" | "optional"
    local name="$1"
    local mode="$2"
    local hit
    if hit=$(_resolve_from_roots "v0/build" "$name"); then
        echo "$hit"
        return 0
    fi
    if [ "$mode" = "required" ]; then
        echo "ERROR: required artifact not found: $name" >&2
        echo "Checked: $REPO_ROOT/v0/build/, parent repo, and sibling worktrees." >&2
        return 1
    fi
    return 1
}

resolve_m4l_js() {
    # $1 = filename (no glob), under v0/src/m4l-js/
    # $2 = "required" | "optional"
    local name="$1"
    local mode="$2"
    local hit
    if hit=$(_resolve_from_roots "v0/src/m4l-js" "$name"); then
        echo "$hit"
        return 0
    fi
    if [ "$mode" = "required" ]; then
        echo "ERROR: required M4L JS not found: $name" >&2
        echo "Checked: $REPO_ROOT/v0/src/m4l-js/, parent repo, and sibling worktrees." >&2
        return 1
    fi
    return 1
}

echo "==> Resolving upstream artifacts"
NATIVE=$(resolve_artifact "stemforge-native" required)
ORT_DYLIB=$(resolve_artifact "libonnxruntime*.dylib" required)
AMXD=$(resolve_artifact "StemForge.amxd" required)
ALS=$(resolve_artifact "StemForge.als" optional || true)

# Model payload: the default htdemucs_ft_fused variant + manifest.
# Per v0-ship-spec §5 and v0/state/A/fusion_succeeded.md, we ship ONLY the
# fused .onnx (inline, no .data sidecar). Analyzer models (ast, clap) and
# fallbacks (htdemucs, htdemucs_6s, 4-head .head{0..3}_static.onnx) are
# explicitly out of scope for v0.
MANIFEST=$(resolve_artifact "models/manifest.json" required)
FUSED_ONNX=$(resolve_artifact "models/htdemucs_ft/htdemucs_ft_fused.onnx" required)

# Node-for-Max bridge/loader JS — must land alongside StemForge.amxd so that
# the device's embedded node.script can locate them at spawn time.
BRIDGE_JS=$(resolve_m4l_js "stemforge_bridge.v0.js" required)
LOADER_JS=$(resolve_m4l_js "stemforge_loader.v0.js" required)

echo "    stemforge-native       : $NATIVE"
echo "    onnxruntime dylib      : $ORT_DYLIB"
echo "    StemForge.amxd         : $AMXD"
echo "    models/manifest.json   : $MANIFEST"
echo "    htdemucs_ft_fused.onnx : $FUSED_ONNX"
echo "    stemforge_bridge.v0.js : $BRIDGE_JS"
echo "    stemforge_loader.v0.js : $LOADER_JS"
if [ -n "$ALS" ]; then
    echo "    StemForge.als          : $ALS"
    ALS_INCLUDED=true
else
    echo "    StemForge.als          : (missing — skeleton.als pending, template will not be bundled)"
    ALS_INCLUDED=false
fi

# ---------------------------------------------------------------------------
# Fusion-contract check: the fused .onnx MUST be a single inline file with no
# `.data` sidecar in the same directory. CoreML EP MLProgram compile silently
# falls back to CPU with SystemError 20 when weights are external. Bail loudly
# here rather than ship a broken pkg. See v0/state/A/fusion_succeeded.md.
# ---------------------------------------------------------------------------
FUSED_DIR=$(dirname "$FUSED_ONNX")
FUSED_BASE=$(basename "$FUSED_ONNX")
SIDECAR_COUNT=$(ls -1 "$FUSED_DIR" 2>/dev/null | awk -v base="$FUSED_BASE" '
    $0 == base ".data" || $0 == base ".data0" { c++ }
    END { print c+0 }')
if [ "$SIDECAR_COUNT" -gt 0 ]; then
    echo "ERROR: fused ONNX has an external .data sidecar alongside it." >&2
    echo "       $FUSED_DIR contains a .data file next to $FUSED_BASE." >&2
    echo "       CoreML EP cannot consume external-weight ONNX (see" >&2
    echo "       v0/state/A/fusion_succeeded.md). Rebuild the fused model" >&2
    echo "       with onnx.save(..., save_as_external_data=False) before" >&2
    echo "       attempting to ship a pkg." >&2
    exit 1
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

# Sync JS from v0/src/m4l-js/ into the Max Package source before staging.
# v0/src/m4l-js/ is the editing location; the Max Package is the distribution
# location. This sync ensures the installer always ships the latest JS.
M4L_PKG_JS="$REPO_ROOT/v0/src/m4l-package/StemForge/javascript"
M4L_JS_SRC="$REPO_ROOT/v0/src/m4l-js"
if [ -d "$M4L_PKG_JS" ] && [ -d "$M4L_JS_SRC" ]; then
    for js in "$M4L_JS_SRC"/*.js; do
        [ -f "$js" ] || continue
        cp "$js" "$M4L_PKG_JS/"
    done
    echo "    JS synced              : m4l-js/ → m4l-package/StemForge/javascript/"
fi

# Max Package — [js] resolves scripts by bare filename via Max's search path.
# The StemForge package (v0/src/m4l-package/StemForge/) ships JS in javascript/.
# postinstall deploys the package to ~/Documents/Max 9/Packages/StemForge/.
M4L_PKG_SRC="$REPO_ROOT/v0/src/m4l-package/StemForge"
if [ -d "$M4L_PKG_SRC" ]; then
    mkdir -p "$USR_ROOT/tmp/stemforge-staging/m4l-package"
    cp -R "$M4L_PKG_SRC" "$USR_ROOT/tmp/stemforge-staging/m4l-package/"
    echo "    Max Package            : $M4L_PKG_SRC (staged)"
else
    echo "WARNING: Max Package source not found at $M4L_PKG_SRC" >&2
    # Fallback: stage loose JS files next to .amxd
    cp "$BRIDGE_JS" "$USR_ROOT/tmp/stemforge-staging/stemforge_bridge.v0.js"
    cp "$LOADER_JS" "$USR_ROOT/tmp/stemforge-staging/stemforge_loader.v0.js"
fi

# Models — approach 1 (see v0-ship-spec §3 W2): stage under user-component
# staging, then postinstall mv's the tree into the target user's
# ~/Library/Application Support/StemForge/models/. Same pattern as the .amxd.
# v0 ships ONLY the htdemucs_ft_fused variant + manifest (≈0.9 GB total).
MODELS_STAGE="$USR_ROOT/tmp/stemforge-staging/models"
mkdir -p "$MODELS_STAGE/htdemucs_ft"
cp "$MANIFEST" "$MODELS_STAGE/manifest.json"
cp "$FUSED_ONNX" "$MODELS_STAGE/htdemucs_ft/htdemucs_ft_fused.onnx"

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
SIZE_GB=$(awk -v b="$SIZE" 'BEGIN{printf "%.2f", b/1024/1024/1024}')
PKG_SHA=$(shasum -a 256 "$OUT" | awk '{print $1}')
echo "==> Built $OUT ($SIZE bytes, ${SIZE_GB} GB)"
echo "    sha256       : $PKG_SHA"
echo "    als_included : $ALS_INCLUDED"
if [ "$ALS_INCLUDED" = "false" ]; then
    echo ""
    echo "    NOTE: Rerun this script after Track D lands StemForge.als to produce"
    echo "    a complete bundle (skeleton.als -> build_als.py -> v0/build/StemForge.als)."
fi
