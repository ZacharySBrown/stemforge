# Track E — Installer / Distribution

## Goal

One signed, notarized macOS `.pkg` that installs everything. Also a `curl | bash` path that downloads and runs the .pkg non-interactively.

## Approach

Standard macOS packaging: `pkgbuild` + `productbuild`, signed with Developer ID Installer cert, notarized.

## Inputs

- `v0/build/stemforge-native` (Track A)
- `v0/build/StemForge.amxd` (Track C)
- `v0/build/StemForge.als` (Track D)
- Developer ID Installer cert (CI secret)

## Outputs

- `v0/build/StemForge-0.0.0.pkg` — signed, notarized installer
- `v0/build/install.sh` — curl-pipeable wrapper that downloads .pkg and invokes `installer`
- `v0/build/uninstall.sh` — removes all installed files
- `v0/src/installer/` — distribution XML, component plists, scripts
- `v0/state/E/done.flag`

## Install Layout

Per `v0/interfaces/device.yaml` paths section:

| File | Destination |
|---|---|
| `stemforge-native` | `/usr/local/bin/stemforge-native` |
| `StemForge.amxd` | `$AbletonUserLibrary/Presets/Audio Effects/Max Audio Effect/StemForge.amxd` |
| `StemForge.als` | `$AbletonUserLibrary/Templates/StemForge.als` |
| — | `~/Library/Application Support/StemForge/` (mkdir) |
| — | `~/stemforge/{inbox,processed,logs}/` (mkdir) |

## Subtasks

### E1 — Component plist
```bash
pkgbuild --analyze --root payload/ component.plist
# then edit to set BundleIsRelocatable=false
```

### E2 — Two-component bundle
One component for `/usr/local/bin/` (system-wide). One for `~/Music/Ableton/...` and `~/Library/...` (user-local).

User-local components require the installer to run as the user, not root. Use a postinstall script.

### E3 — Postinstall: detect Ableton User Library
```bash
#!/bin/bash
# Priority order for detecting Ableton User Library:
# 1. Read ~/Library/Preferences/Ableton/Live */Preferences.cfg (key: UserLibraryFolder)
# 2. Default: ~/Music/Ableton/User Library
detect_ableton_lib() {
    local prefs=$(ls -1d "$HOME/Library/Preferences/Ableton/Live "* 2>/dev/null | sort -V | tail -1)
    if [ -n "$prefs" ] && [ -f "$prefs/Preferences.cfg" ]; then
        grep -oE '"UserLibraryFolder"[^"]*"[^"]+"' "$prefs/Preferences.cfg" | tail -1 | grep -oE '"[^"]+"$' | tr -d '"' && return 0
    fi
    echo "$HOME/Music/Ableton/User Library"
}
LIB=$(detect_ableton_lib)
mkdir -p "$LIB/Presets/Audio Effects/Max Audio Effect"
mkdir -p "$LIB/Templates"
cp /tmp/stemforge-staging/StemForge.amxd "$LIB/Presets/Audio Effects/Max Audio Effect/"
cp /tmp/stemforge-staging/StemForge.als "$LIB/Templates/"
```

### E4 — PATH for GUI apps
Ableton Live launched from Dock does not inherit shell PATH. The M4L device resolves the binary via absolute paths from `device.yaml:binary.search_paths`, so PATH isn't strictly needed — but `stemforge-native` at `/usr/local/bin/` is in the GUI-default path on macOS.

### E5 — Uninstall script
```bash
#!/bin/bash
rm -f /usr/local/bin/stemforge-native
LIB=$(detect_ableton_lib)  # reuse postinstall detection
rm -f "$LIB/Presets/Audio Effects/Max Audio Effect/StemForge.amxd"
rm -f "$LIB/Templates/StemForge.als"
# preserve ~/Library/Application Support/StemForge (weights + user data)
# preserve ~/stemforge/ (user audio)
echo "StemForge uninstalled. User data preserved at ~/stemforge/ and ~/Library/Application Support/StemForge/."
```
Install at `/usr/local/bin/stemforge-uninstall`.

### E6 — curl | bash wrapper
```bash
# v0/build/install.sh (served from stemforge.dev/install)
#!/bin/bash
set -e
VERSION="${STEMFORGE_VERSION:-latest}"
URL="https://github.com/ZacharySBrown/stemforge/releases/${VERSION}/download/StemForge-${VERSION}.pkg"
TMP=$(mktemp -d)
curl -fsSL "$URL" -o "$TMP/StemForge.pkg"
sudo installer -pkg "$TMP/StemForge.pkg" -target /
rm -rf "$TMP"
echo "Installed. Open Ableton → File → New from Template → StemForge."
```

### E7 — Sign + notarize
```bash
productbuild --distribution distribution.xml \
    --package-path stage/ \
    --sign "Developer ID Installer: ..." \
    StemForge-0.0.0.pkg

xcrun notarytool submit StemForge-0.0.0.pkg \
    --apple-id "$APPLE_ID" --team-id "$TEAM_ID" \
    --password "$APP_PW" --wait
xcrun stapler staple StemForge-0.0.0.pkg
```

## Acceptance

- `installer -pkg StemForge-0.0.0.pkg -target /` completes without error on a fresh Mac.
- `spctl -a -v --type install StemForge-0.0.0.pkg` → "accepted"
- All destination files exist after install.
- Ableton Live 12 shows "StemForge" under File → New from Template.
- `stemforge-uninstall` removes everything and reports correctly.

## Risk / Unknowns

- `.pkg` postinstall runs as root; `$HOME` resolution requires `sudo -u $USER`. Common pattern, not a blocker.
- Ableton User Library path varies: ~/Music/Ableton/User Library is default, but users can change it. Detection in E3 covers most cases.

## Subagent Brief

You are implementing Track E. Dependencies: A, C, D all have `done.flag`.

**Block on all three:**
```bash
for t in A C D; do
    while [ ! -f v0/state/$t/done.flag ]; do sleep 10; done
    [ -f v0/state/$t/blocker.md ] && { echo "Upstream blocked"; exit 1; }
done
```

**Read:**
- `v0/PLAN.md`, `v0/SHARED.md`
- `v0/interfaces/device.yaml` (paths section)
- `v0/state/{A,C,D}/artifacts.json` (actual artifact paths)

**Produce:** everything in Outputs.

**Do not:** modify artifacts from A/C/D.

Write `v0/state/E/done.flag` when the .pkg installs cleanly on a test VM.
