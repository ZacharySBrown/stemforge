#!/usr/bin/env bash
# build-native.sh — reproducible build for stemforge-native + libstemforge.
#
# Usage:
#   ./build-native.sh                # native arch
#   ./build-native.sh --arch arm64
#   ./build-native.sh --arch x86_64
#   ./build-native.sh --universal    # lipo arm64+x86_64 (requires prior arm64 + x86_64 builds or cross tooling)
#
# Env overrides:
#   ORT_VERSION         (default 1.24.4)
#   CODESIGN_ID         (optional — if set, ad-hoc sign is replaced by Developer ID)
#
# The script:
#   1. Fetches ONNX Runtime + KissFFT + nlohmann/json into v0/src/A/vendor/ if missing.
#   2. Configures + builds with CMake Release.
#   3. Copies libonnxruntime.*.dylib alongside the binary and adjusts rpath.
#   4. Ad-hoc codesigns (or Developer ID if CODESIGN_ID set) with entitlements.plist.
#   5. Reports architecture + CoreML EP probe result.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC_A="$REPO_ROOT/v0/src/A"
BUILD_OUT="$REPO_ROOT/v0/build"
VENDOR="$SRC_A/vendor"
ORT_VERSION="${ORT_VERSION:-1.24.4}"

ARCH=""
UNIVERSAL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch) ARCH="$2"; shift 2;;
    --universal) UNIVERSAL=1; shift;;
    -h|--help)
      echo "usage: $0 [--arch arm64|x86_64] [--universal]"; exit 0;;
    *) echo "unknown: $1"; exit 2;;
  esac
done

if [[ -z "$ARCH" && "$UNIVERSAL" -eq 0 ]]; then
  ARCH="$(uname -m)"
fi

mkdir -p "$VENDOR"

# 1. Fetch ONNX Runtime (universal2 not published; fetch per-arch).
fetch_ort_arch () {
  local a="$1"
  local name="onnxruntime-osx-${a}-${ORT_VERSION}"
  local url="https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VERSION}/${name}.tgz"
  local target="$VENDOR/${name}"
  if [[ ! -f "$target/include/onnxruntime_cxx_api.h" ]]; then
    echo ">> fetching ORT $a"
    curl -sSL "$url" -o "$VENDOR/${name}.tgz"
    tar -xzf "$VENDOR/${name}.tgz" -C "$VENDOR"
    rm -f "$VENDOR/${name}.tgz"
  fi
}

if [[ "$UNIVERSAL" -eq 1 ]]; then
  fetch_ort_arch arm64
  fetch_ort_arch x86_64
else
  fetch_ort_arch "$ARCH"
fi

# 2. Fetch header-only vendored deps (if missing).
[[ -f "$VENDOR/nlohmann_json.hpp" ]] || curl -sSL \
  "https://raw.githubusercontent.com/nlohmann/json/v3.11.3/single_include/nlohmann/json.hpp" \
  -o "$VENDOR/nlohmann_json.hpp"

if [[ ! -d "$VENDOR/kissfft" ]]; then
  curl -sSL "https://github.com/mborgerding/kissfft/archive/refs/tags/131.1.0.tar.gz" \
    -o "$VENDOR/kissfft.tgz"
  tar -xzf "$VENDOR/kissfft.tgz" -C "$VENDOR"
  mv "$VENDOR/kissfft-131.1.0" "$VENDOR/kissfft"
  rm -f "$VENDOR/kissfft.tgz"
fi

# 3. Configure + build per arch.
build_arch () {
  local a="$1"
  local ort="$VENDOR/onnxruntime-osx-${a}-${ORT_VERSION}"
  local bd="$BUILD_OUT/cmake-${a}"
  mkdir -p "$bd"
  pushd "$bd" >/dev/null
  cmake "$SRC_A" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_OSX_ARCHITECTURES="$a" \
    -DORT_DIR="$ort"
  cmake --build . --parallel
  popd >/dev/null
  # Symlink the vendor dir CMakeLists saw — CMake caches paths so just
  # make sure libstemforge.a and stemforge-native were produced.
  ls -l "$bd/libstemforge.a" "$bd/stemforge-native"
}

OUT_BIN="$BUILD_OUT/stemforge-native"
OUT_LIB="$BUILD_OUT/libstemforge.a"

if [[ "$UNIVERSAL" -eq 1 ]]; then
  build_arch arm64
  build_arch x86_64
  lipo -create \
    "$BUILD_OUT/cmake-arm64/stemforge-native" \
    "$BUILD_OUT/cmake-x86_64/stemforge-native" \
    -output "$OUT_BIN"
  # libonnxruntime lipo — both archs publish single-arch dylibs.
  mkdir -p "$BUILD_OUT/lib"
  lipo -create \
    "$VENDOR/onnxruntime-osx-arm64-${ORT_VERSION}/lib/libonnxruntime.${ORT_VERSION}.dylib" \
    "$VENDOR/onnxruntime-osx-x86_64-${ORT_VERSION}/lib/libonnxruntime.${ORT_VERSION}.dylib" \
    -output "$BUILD_OUT/lib/libonnxruntime.${ORT_VERSION}.dylib"
  ln -sf "libonnxruntime.${ORT_VERSION}.dylib" "$BUILD_OUT/libonnxruntime.dylib"
  cp "$BUILD_OUT/cmake-arm64/libstemforge.a" "$OUT_LIB"  # static archives aren't lipoable trivially; CI matrix ships per-arch.
else
  build_arch "$ARCH"
  cp "$BUILD_OUT/cmake-${ARCH}/stemforge-native" "$OUT_BIN"
  cp "$BUILD_OUT/cmake-${ARCH}/libstemforge.a" "$OUT_LIB"
  # Copy ORT dylib alongside binary so @executable_path rpath finds it.
  ORT_DYLIB="$VENDOR/onnxruntime-osx-${ARCH}-${ORT_VERSION}/lib/libonnxruntime.${ORT_VERSION}.dylib"
  cp "$ORT_DYLIB" "$BUILD_OUT/"
  ln -sf "libonnxruntime.${ORT_VERSION}.dylib" "$BUILD_OUT/libonnxruntime.dylib"
fi

# 4. install_name fix: libonnxruntime ships with absolute install_name.
install_name_tool -change \
  "@rpath/libonnxruntime.${ORT_VERSION}.dylib" \
  "@executable_path/libonnxruntime.${ORT_VERSION}.dylib" \
  "$OUT_BIN" 2>/dev/null || true

# 5. Sign.
if [[ -n "${CODESIGN_ID:-}" ]]; then
  codesign --force --options runtime \
    --entitlements "$BUILD_OUT/entitlements.plist" \
    --sign "$CODESIGN_ID" "$BUILD_OUT/libonnxruntime.${ORT_VERSION}.dylib" || true
  codesign --force --options runtime \
    --entitlements "$BUILD_OUT/entitlements.plist" \
    --sign "$CODESIGN_ID" "$OUT_BIN"
else
  echo ">> ad-hoc codesign (dev build)"
  codesign --force --options runtime \
    --entitlements "$BUILD_OUT/entitlements.plist" \
    --sign - "$BUILD_OUT/libonnxruntime.${ORT_VERSION}.dylib" 2>/dev/null || true
  codesign --force --options runtime \
    --entitlements "$BUILD_OUT/entitlements.plist" \
    --sign - "$OUT_BIN"
fi

echo ">> built: $OUT_BIN"
file "$OUT_BIN"
codesign -dvv "$OUT_BIN" 2>&1 | head -4 || true
"$OUT_BIN" --version
