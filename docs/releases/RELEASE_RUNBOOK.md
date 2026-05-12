# Manual release runbook — v0.X.0

This is the **one-time manual flow** for the next StemForge release. We picked manual over CI for this cut so we can ship without first auditing/fixing the heavyweight `release.yml` or wiring up new PyPI automation. After we've shipped one release this way, we revisit and automate.

## Prereqs (one-time)

- [ ] **PyPI account + project ownership.** Confirm you own (or can publish to) `stemforge` on PyPI. If the name is unclaimed, register it now via PyPI's web UI — claim the name **before** uploading anything.
- [ ] **PyPI API token.** Generate a project-scoped token at <https://pypi.org/manage/account/token/>. Save to `~/.pypirc`:
  ```ini
  [pypi]
  username = __token__
  password = pypi-AgEIcHl...your-token-here
  ```
  Or export `TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-...` for the upload command.
- [ ] **`uv build` and `twine` installed.** `uv` is already a project dep. `twine` is not — install with `uv tool install twine` (preferred) or `pipx install twine`.
- [ ] **macOS signing identities ready** (only if attaching a notarized `.pkg`). Need `Developer ID Application` for the binary and `Developer ID Installer` for the .pkg. Check with `security find-identity -v -p codesigning`.

## Step 1 — Decide the version

Right now the source-of-truth is split:

| Where | Value |
|---|---|
| `pyproject.toml` | `0.2.0` |
| `v0/build/build-pkg.sh` default | `0.0.1` |
| `v0/src/installer/distribution.xml` | `0.0.1` |
| Git tags | `v0.0.1-beta`, `v0.0.2-beta` |

Pick one of:
- `0.1.0` — first real minor release (matches your earlier preference; means downgrading `pyproject.toml` from `0.2.0`, which is safe because `0.2.0` was never published).
- `0.2.0` — accept what `pyproject.toml` already says.
- `0.0.3` — continue the existing tag sequence; conservative.

Record your pick here: `STEMFORGE_VERSION=___`.

## Step 2 — Align all version sources

```bash
export STEMFORGE_VERSION=0.X.0  # your pick from step 1

# pyproject.toml
sed -i '' -e "s/^version = \".*\"/version = \"${STEMFORGE_VERSION}\"/" pyproject.toml

# v0/build/build-pkg.sh — default fallback
sed -i '' -e "s/^VERSION=\"\${STEMFORGE_VERSION:-.*}\"/VERSION=\"\${STEMFORGE_VERSION:-${STEMFORGE_VERSION}}\"/" v0/build/build-pkg.sh

# v0/src/installer/distribution.xml — 3 references
sed -i '' -e "s/StemForge 0\\.0\\.1/StemForge ${STEMFORGE_VERSION}/" v0/src/installer/distribution.xml
sed -i '' -e "s/version=\"0\\.0\\.1\"/version=\"${STEMFORGE_VERSION}\"/g" v0/src/installer/distribution.xml
```

Verify:
```bash
grep -nE "0\.[012]\.[0-9]|0\.0\.0" pyproject.toml v0/build/build-pkg.sh v0/src/installer/distribution.xml
```

Commit on a branch:
```bash
git checkout -b release/v${STEMFORGE_VERSION}
git add pyproject.toml v0/build/build-pkg.sh v0/src/installer/distribution.xml
git commit -m "chore(release): bump version to ${STEMFORGE_VERSION}"
```

## Step 3 — Update CHANGELOG.md

Open `CHANGELOG.md`, rename `## [Unreleased]` to `## [v${STEMFORGE_VERSION}] — YYYY-MM-DD`, and add a fresh empty `## [Unreleased]` section at the top for future work.

Verify locally:
```bash
head -50 CHANGELOG.md
```

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): cut v${STEMFORGE_VERSION}"
```

## Step 4 — Tests must be green

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

If `canonical_tempos` fails with content mismatches (not torch double-init), the `/private/tmp/phase3_inputs/*.wav` fixtures may be missing or stem-reconstructed. Make sure the originals are present before claiming green. The torch flake itself should be gone post-PR #70.

If anything red, stop. Fix, recommit, restart this step.

## Step 5 — Build the Python distributions

```bash
rm -rf dist/ build/ *.egg-info
uv build  # produces dist/stemforge-${STEMFORGE_VERSION}.tar.gz and ...-py3-none-any.whl
ls -lh dist/
```

Sanity-check the wheel installs cleanly into a fresh venv:
```bash
uv venv /tmp/sftest && /tmp/sftest/bin/pip install dist/stemforge-${STEMFORGE_VERSION}-py3-none-any.whl
/tmp/sftest/bin/stemforge --help | head -20
rm -rf /tmp/sftest
```

## Step 6 — Build the .pkg

```bash
STEMFORGE_VERSION=${STEMFORGE_VERSION} bash v0/build/build-pkg.sh
ls -lh v0/build/StemForge-${STEMFORGE_VERSION}.pkg
```

Optional: codesign + notarize the .pkg. Skip if this is an internal/preview release. If notarizing:
```bash
xcrun notarytool submit v0/build/StemForge-${STEMFORGE_VERSION}.pkg \
  --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PW" \
  --wait
xcrun stapler staple v0/build/StemForge-${STEMFORGE_VERSION}.pkg
```

## Step 7 — Open + merge a release PR

```bash
git push -u origin release/v${STEMFORGE_VERSION}
gh pr create --base main --head release/v${STEMFORGE_VERSION} \
  --title "release: v${STEMFORGE_VERSION}" \
  --body "Version bump + CHANGELOG cut. See CHANGELOG.md for the full delta."
# Wait for CI green, then merge via GitHub UI or:
gh pr merge --squash --delete-branch
git checkout main && git pull
```

## Step 8 — Tag

```bash
git tag -a "v${STEMFORGE_VERSION}" -m "StemForge v${STEMFORGE_VERSION}"
git push origin "v${STEMFORGE_VERSION}"
```

**Note:** the existing heavyweight `.github/workflows/release.yml` triggers on `v*` tags. It may attempt the ONNX→universal2-native→notarize→.pkg→GitHub-release pipeline and **fail** because some of its referenced scripts are broken (e.g. `v0/src/installer/build-pkg.sh` doesn't exist; the actual script is at `v0/build/build-pkg.sh`). If the workflow fails, that's expected — we ship the GitHub release manually in step 10 below. Optionally disable the workflow first by renaming it or pushing a tag like `v${STEMFORGE_VERSION}-skip-ci` then re-tagging.

## Step 9 — Publish to PyPI

```bash
twine check dist/*
twine upload dist/*
```

Verify by installing from PyPI in a fresh venv:
```bash
uv venv /tmp/sf-pypi && /tmp/sf-pypi/bin/pip install stemforge==${STEMFORGE_VERSION}
/tmp/sf-pypi/bin/stemforge --help | head -10
rm -rf /tmp/sf-pypi
```

## Step 10 — Publish the GitHub release

```bash
gh release create "v${STEMFORGE_VERSION}" \
  v0/build/StemForge-${STEMFORGE_VERSION}.pkg \
  dist/stemforge-${STEMFORGE_VERSION}-py3-none-any.whl \
  dist/stemforge-${STEMFORGE_VERSION}.tar.gz \
  --title "v${STEMFORGE_VERSION}" \
  --notes-from-tag  # uses the tag annotation; or use --notes-file CHANGELOG.md
```

Or open the release in the browser to write a richer description that links to CHANGELOG sections:
```bash
gh release create "v${STEMFORGE_VERSION}" \
  v0/build/StemForge-${STEMFORGE_VERSION}.pkg \
  dist/* \
  --title "v${STEMFORGE_VERSION}" \
  --draft
gh release view --web "v${STEMFORGE_VERSION}"
```

## Step 11 — Post-release smoke

- [ ] `pip install stemforge==${STEMFORGE_VERSION}` works on a fresh machine / fresh venv.
- [ ] `stemforge --help`, `stemforge split --help`, `stemforge build-deck --help` all render.
- [ ] `.pkg` installs cleanly on a fresh Ableton-equipped Mac (only if notarized).
- [ ] EP-133 deck workflow runs end-to-end on at least one new track.
- [ ] Announce in whatever channel makes sense (Slack / Discord / Twitter / nowhere).

## Step 12 — Cleanup

- [ ] Delete the `release/v${STEMFORGE_VERSION}` branch on origin if not auto-deleted by the merge.
- [ ] If you bumped `pyproject.toml` to a new development version (e.g. `0.X.1.dev0`), commit that to main now to mark "next release in progress."

## Rollback (if anything breaks)

- **Bad PyPI upload:** PyPI doesn't allow re-uploading a deleted version. Yank with `twine yank stemforge ${STEMFORGE_VERSION} --reason "..."` and ship `${NEXT_PATCH}` with a fix.
- **Bad GitHub release:** `gh release delete "v${STEMFORGE_VERSION}" --yes --cleanup-tag`. Delete the tag locally too: `git tag -d "v${STEMFORGE_VERSION}"`. Then redo.
- **Bad .pkg:** edit the release on GitHub, delete the asset, upload a corrected one with `gh release upload`.

---

## Followups for the next release (out of scope this time)

- Replace this runbook with a working `release-minimal.yml` workflow:
  - Trigger on `v*` tag push.
  - Build wheel + sdist via `uv build`.
  - Publish to PyPI via `pypa/gh-action-pypi-publish` (use OIDC trusted publisher; no API token in secrets).
  - Build the `.pkg` via the existing `v0/build/build-pkg.sh`.
  - Create GitHub release with auto-generated notes + attach `.pkg` + dist artifacts.
- Either fix the broken paths in `.github/workflows/release.yml` and consolidate, or delete it once `release-minimal.yml` covers the same ground.
- Adopt `python-semantic-release` or similar if you want to automate version bumps from conventional-commit messages.
