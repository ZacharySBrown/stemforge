#!/bin/bash
# sign-notarize-pkg.sh — productsign + notarytool wrapper for Track F (CI).
#
# Required env:
#   INSTALLER_ID    — "Developer ID Installer: Name (TEAMID)"
#   APPLE_ID        — Apple ID email for notarytool
#   APPLE_TEAM_ID   — Apple Developer team id
#   APPLE_APP_PW    — app-specific password (or use keychain profile)
#
# Usage: sign-notarize-pkg.sh <path/to/StemForge-X.Y.Z.pkg>
set -euo pipefail

PKG="${1:?path to .pkg required}"
: "${INSTALLER_ID:?INSTALLER_ID env var required}"
: "${APPLE_ID:?APPLE_ID env var required}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID env var required}"
: "${APPLE_APP_PW:?APPLE_APP_PW env var required}"

SIGNED="${PKG%.pkg}-signed.pkg"

echo "==> productsign"
productsign --sign "$INSTALLER_ID" "$PKG" "$SIGNED"
mv "$SIGNED" "$PKG"

echo "==> notarytool submit (wait)"
xcrun notarytool submit "$PKG" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PW" \
    --wait

echo "==> stapler staple"
xcrun stapler staple "$PKG"

echo "==> Verify"
spctl -a -v --type install "$PKG" || true
xcrun stapler validate "$PKG"
echo "Signed + notarized: $PKG"
