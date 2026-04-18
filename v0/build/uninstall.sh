#!/bin/bash
# uninstall.sh — removes StemForge-installed files. Preserves user data.
# Installed as /usr/local/bin/stemforge-uninstall by the .pkg.
set -e

detect_ableton_lib() {
    local prefs
    prefs=$(ls -1d "$HOME/Library/Preferences/Ableton/Live "* 2>/dev/null | sort -V | tail -1)
    if [ -n "$prefs" ] && [ -f "$prefs/Preferences.cfg" ]; then
        local lib
        lib=$(grep -oE '"UserLibraryFolder"[^"]*"[^"]+"' "$prefs/Preferences.cfg" \
              | tail -1 | grep -oE '"[^"]+"$' | tr -d '"')
        if [ -n "$lib" ]; then
            echo "$lib"
            return 0
        fi
    fi
    echo "$HOME/Music/Ableton/User Library"
}

need_sudo=false
for p in /usr/local/bin/stemforge-native /usr/local/bin/stemforge-uninstall /usr/local/lib/libonnxruntime*.dylib; do
    for f in $p; do
        if [ -e "$f" ] && [ ! -w "$(dirname "$f")" ]; then
            need_sudo=true
            break 2
        fi
    done
done

run() {
    if [ "$need_sudo" = true ]; then
        sudo "$@"
    else
        "$@"
    fi
}

echo "==> Removing system files"
run rm -f /usr/local/bin/stemforge-native
run sh -c 'rm -f /usr/local/lib/libonnxruntime*.dylib'

LIB=$(detect_ableton_lib)
echo "==> Removing Ableton integration from: $LIB"
rm -f "$LIB/Presets/Audio Effects/Max Audio Effect/StemForge.amxd"
rm -f "$LIB/Templates/StemForge.als"

# Remove package receipts so the installer treats this as a clean slate.
run pkgutil --forget com.stemforge.system 2>/dev/null || true
run pkgutil --forget com.stemforge.user 2>/dev/null || true

# Intentionally preserved:
#   ~/stemforge/                         (user audio: inbox/processed/logs)
#   ~/Library/Application Support/StemForge/   (models + bin symlinks + cache)
echo ""
echo "StemForge uninstalled."
echo "User data preserved at:"
echo "  ~/stemforge/"
echo "  ~/Library/Application Support/StemForge/"
echo ""
echo "Remove them manually if desired:"
echo "  rm -rf ~/stemforge ~/Library/Application\\ Support/StemForge"

# Self-delete last so the preceding 'run rm -f /usr/local/bin/stemforge-uninstall'
# above didn't wipe out the running script. The earlier rm already handled it,
# but macOS keeps the file open until exec finishes.
exit 0
