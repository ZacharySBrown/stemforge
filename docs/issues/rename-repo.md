# Rename the repo

**Status:** Deferred — captured 2026-04-25, do later.

## Why

(TBD — fill in when you pick the new name.)

## Pick the new name first

Options to consider — do not act until one is chosen:

- Brand vs. tool naming (is "StemForge" the product, the CLI, or both?)
- Whether the new name should encompass the EP-133 / hardware-loader work
  that's growing alongside the stem-splitting core
- Conflict check on PyPI, GitHub, npm, social handles

## Surface area to update when renaming

Everything below references the current name `stemforge` / `StemForge` and
will need a coordinated rename. Group by blast radius.

### Hot path (breaks if missed)

- [ ] `pyproject.toml` — `name = "stemforge"`, `[project.scripts] stemforge = "stemforge.cli:cli"`
- [ ] Top-level package dir `stemforge/` (rename + update all imports)
- [ ] `[tool.setuptools.packages.find] include = ["stemforge*"]`
- [ ] CLI command `stemforge` (will change to `<newname>`; document the
      transition in CLAUDE.md)
- [ ] GitHub repo URL — coordinate the rename via repo settings; GitHub
      auto-redirects but git remotes will need updating for collaborators
- [ ] Local clones — note `git remote set-url origin <new-url>` in CHANGELOG
- [ ] All four agent-fleet `.claude/agents/*.md` references and skills

### Visible-to-user (functional impact)

- [ ] Max Package dir name `StemForge` in `v0/src/m4l-package/StemForge/`
      (Max sees this as the package — affects installed-side path
      `~/Documents/Max 9/Packages/StemForge/`)
- [ ] `.amxd` filename `StemForge.amxd`
- [ ] Build artifacts: `StemForge-X.Y.Z.pkg`, `stemforge-native` binary
- [ ] Installer URL `stemforge.dev/install` (in `v0/build/install.sh`)
- [ ] Postinstall script paths in `v0/src/installer/`
- [ ] User-data dirs: `~/stemforge/`, `~/stemforge/processed/`,
      `~/stemforge/exports/`, `~/stemforge/logs/`
- [ ] Native binary search paths in `v0/interfaces/device.yaml`:
      `/usr/local/bin/stemforge-native`,
      `~/Library/Application Support/StemForge/...`
- [ ] Any `bundle_identifier: com.stemforge.m4l.v0` style strings
- [ ] Status text / device version strings in sf_ui.js

### Cosmetic / safe to lag

- [ ] All `docs/`, `specs/`, `README.md` references
- [ ] All `.claude/CLAUDE.md` mentions
- [ ] All `m4l/*.html` build guide pages
- [ ] All log file prefixes (`[sf_forge]`, `[sf_clip_export]`, etc — these
      use `sf_` prefix which is already abbreviated; may not need to change)
- [ ] Memory files in `~/.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/`

### Cross-repo coordination

- [ ] `ep133-ppak/ep133/manifest.py` references the canonical schema in
      this repo by path (`stemforge/manifest_schema.py`) in its docstring.
      Update there too.
- [ ] Any other repo that has hardcoded `stemforge` paths
      (`/Users/zak/zacharysbrown/stemforge/...` shows up in the M4L JS,
      will need to be configurable or renamed in lockstep)

## Migration strategy (rough)

1. Pick new name; verify availability on PyPI + GitHub.
2. Create a feature branch off main: `chore/rename-to-<new>`.
3. Rename in this order to minimize broken intermediate states:
   a. Cosmetic + docs first (zero functional impact).
   b. Python package + CLI script.
   c. Max Package + .amxd + installer artifacts.
   d. User-data dirs (provide a migration script that symlinks the old
      path to the new one for one release cycle).
4. Tag a final release on the old name, then merge the rename PR.
5. Add a top-level redirect note in the old README pointing at the new
   repo URL.
6. Update `~/.claude/projects/...` memory directory paths.

## Risks

- Anyone with local clones needs to `git remote set-url origin <new>`.
- Anyone with the v0.0.1 .pkg installed will keep writing to the old
  user-data dirs unless they reinstall.
- Hardcoded paths in JS (`HELPER_PATH = "/Users/zak/zacharysbrown/stemforge/tools/m4l_export_clips.py"`)
  WILL break — sf_clip_export already needs a path-resolution overhaul
  (tracked elsewhere) so do these together.

## When

Not now. Wait until:
- The export/import path UAT is stable
- The V2 freeze pipeline (issue #33) decision is made
- A new name is chosen and conflict-checked
