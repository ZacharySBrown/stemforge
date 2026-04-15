# Track F — CI/CD

## Goal

GitHub Actions pipeline that, on tag push, runs every other track's build scripts, produces the signed .pkg, and publishes a GitHub release.

## Inputs

- All of A, C, D, E tooling (build scripts, spec files)
- GitHub Secrets (list in `.github/SECRETS.md`, values set by human out-of-band)

## Outputs

- `.github/workflows/release.yml` — on tag `v*`
- `.github/workflows/ci.yml` — on PR / push to main
- `.github/SECRETS.md` — documents required secrets (names only, never values)
- `.github/actions/` — composite actions for shared steps (notarize, lipo-merge, etc.)
- `v0/state/F/done.flag`

## release.yml Skeleton

```yaml
name: Release
on:
  push:
    tags: ['v*']

jobs:
  build-native-arm64:
    runs-on: macos-14  # Apple Silicon
    outputs:
      artifact: ${{ steps.build.outputs.path }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: |
          pip install -e '.[native,dev]'
          bash v0/build/build-native.sh --arch arm64
      - uses: actions/upload-artifact@v4
        with:
          name: stemforge-native-arm64
          path: v0/build/stemforge-native-arm64

  build-native-x86_64:
    runs-on: macos-13  # Intel
    # same steps, --arch x86_64

  merge-universal2:
    needs: [build-native-arm64, build-native-x86_64]
    runs-on: macos-14
    steps:
      - uses: actions/download-artifact@v4
      - run: |
          lipo -create stemforge-native-arm64/stemforge-native-arm64 \
                       stemforge-native-x86_64/stemforge-native-x86_64 \
                       -output v0/build/stemforge-native
      - name: Sign + notarize
        env: { CODESIGN_ID: ${{ secrets.CODESIGN_ID }}, ... }
        run: bash v0/build/sign-notarize.sh v0/build/stemforge-native

  build-amxd:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      - run: python v0/src/maxpat-builder/builder.py
      - uses: actions/upload-artifact@v4
        with: { name: amxd, path: v0/build/StemForge.amxd }

  build-als:
    runs-on: macos-14  # any platform works, macos for consistency
    steps:
      - run: python v0/src/als-builder/builder.py
      - uses: actions/upload-artifact@v4
        with: { name: als, path: v0/build/StemForge.als }

  package:
    needs: [merge-universal2, build-amxd, build-als]
    runs-on: macos-14
    steps:
      - uses: actions/download-artifact@v4
      - run: bash v0/src/installer/build-pkg.sh
      - name: Sign + notarize pkg
        run: bash v0/src/installer/sign-notarize-pkg.sh
      - uses: softprops/action-gh-release@v2
        with:
          files: v0/build/StemForge-*.pkg
          generate_release_notes: true
```

## ci.yml Skeleton

On PR / push to main:
- Lint (ruff, mypy-strict on `stemforge/`)
- Unit tests (pytest, no Ableton, no real audio files > 5s)
- Smoke-build: run Track D's builder (no signing), validate .als opens as XML
- Smoke-build: run Track C's builder in Path-2 mode, validate .amxd structure
- Do NOT build native binary on every PR (too slow) — only on tag

## Required Secrets

Documented in `.github/SECRETS.md`:

| Name | Purpose |
|---|---|
| `CODESIGN_ID` | Developer ID Application cert Common Name |
| `CODESIGN_CERT_P12_B64` | Base64-encoded .p12 cert for keychain import |
| `CODESIGN_CERT_PW` | Password to decrypt the .p12 |
| `INSTALLER_ID` | Developer ID Installer cert CN |
| `INSTALLER_CERT_P12_B64` | Base64 .p12 for installer cert |
| `APPLE_ID` | Notary account email |
| `APPLE_TEAM_ID` | Notary team ID |
| `APPLE_APP_PW` | App-specific password for notarytool |

## Acceptance

- Tag `v0.0.0-test` triggers release workflow end-to-end.
- Produces signed, notarized .pkg as a GitHub release asset.
- ci.yml runs on every PR in <10 minutes without ML dependencies.
- No secrets appear in logs.

## Risk / Unknowns

- GitHub macOS runners: Apple Silicon (`macos-14`) quota is limited. Budget accordingly.
- Notarization can take long; use `--wait` but set job timeout to 30 min.
- Secrets rotation: document renewal cadence in SECRETS.md.

## Subagent Brief

You are implementing Track F. Can start immediately alongside A, B, D.

**Read:** `v0/PLAN.md`, `v0/SHARED.md`, and all other track briefs (to understand what the workflows invoke).

**Produce:** workflow YAMLs, secrets docs, composite actions.

**Do not:**
- Commit any real secret values
- Invoke the workflows yourself — orchestrator controls when tags get pushed
- Modify `stemforge/`, `m4l/`, or any other track's build scripts

**Iterate in two phases:**
1. Skeleton workflows that reference build scripts (even if those scripts don't exist yet). Commit, move on.
2. Once A's `build-native.sh` is committed, refine the matrix job references.

Write `v0/state/F/done.flag` when workflows are syntactically valid (`actionlint`) and reference real build scripts.
