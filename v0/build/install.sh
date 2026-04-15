#!/bin/bash
# install.sh — curl-pipeable StemForge installer.
#
#   curl -fsSL https://stemforge.dev/install | bash
#
# Downloads the latest (or pinned) StemForge .pkg from GitHub releases and
# hands it to /usr/sbin/installer. Honors STEMFORGE_VERSION for pinning:
#
#   STEMFORGE_VERSION=0.1.0 curl -fsSL https://stemforge.dev/install | bash
set -e

VERSION="${STEMFORGE_VERSION:-latest}"

if [ "$VERSION" = "latest" ]; then
    URL="https://github.com/ZacharySBrown/stemforge/releases/latest/download/StemForge.pkg"
else
    URL="https://github.com/ZacharySBrown/stemforge/releases/download/${VERSION}/StemForge-${VERSION}.pkg"
fi

echo "==> Downloading StemForge ($VERSION)"
echo "    $URL"
TMP=$(mktemp -d -t stemforge-install)
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "$URL" -o "$TMP/StemForge.pkg"

echo "==> Installing (requires admin password)"
sudo installer -pkg "$TMP/StemForge.pkg" -target /

cat <<'EOF'

StemForge installed.

Next steps:
  1. Open Ableton Live 12.
  2. File -> New from Template -> StemForge
     (if the template is missing, this build did not bundle StemForge.als;
      drop the .amxd onto any MIDI track manually from the User Library).
  3. Drag an audio file onto the device to split it.

Remove with:  stemforge-uninstall
EOF
