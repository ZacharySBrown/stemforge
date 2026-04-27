# Curation Library — Session Handoff 2026-04-26

End-of-session state for the curation-library + song-form-templates + prechop work. Resume from here.

## Branch state

**Current branch:** `feat/curation-library-v2`
- **Base:** `feat/curation-engine-v2` (NOT `main` — main lacks the curation engine prereqs)
- **Pushed:** No. All work is local.
- **6 new commits** ahead of `feat/curation-engine-v2`:

```
e7fd1c6  docs(song-forms): per-template "Build in Live" recipes
dc24872  feat(prechop): bar-aligned stem chunker for arrangement-view import
aaf174c  docs(exec-plan): device-side changes for curation library (review gate)
b823753  docs(song-forms): five song-form template specs
6af0c42  feat(presets,tools): stems_only preset + init_library bootstrap
8d885f0  feat(router): library-curation router + `stemforge route` CLI
```

**Test status:** all green
- `tests/test_router.py` — 23 passing
- `tests/test_init_library.py` — 4 passing
- `tests/test_prechop.py` — 12 passing
- Total new-code coverage: 39 tests

## What's done

### 1. Curation router (`stemforge/router.py`, `stemforge route` CLI)
Reads a bounce dir's `.manifest.json` (`BatchManifest`), classifies each sample by `playmode`/`role`/`stem`/`name`, copies the WAV into `~/mus/Samples/<bucket>/` with a song-prefixed filename. Original `.manifest_<hash>.json` sidecar travels along (hash-based name stays valid). Per-run summary at `~/mus/Projects/Stems/<slug>/stemforge_curation.json`.

Buckets: `Oneshots/{Kicks,Snares,Hats,Percussion}`, `Loops/{Drums,Bass,Melodic,Vocal}`, `Vocals`, `_Incoming`.

Filename: `{song_slug}_{kind}[_{N}bar]_{NNN}.wav`, e.g. `oohlala_drumloop_4bar_001.wav`.

Idempotent: re-routing skips by `audio_hash` collision in the destination.

CLI:
```
uv run stemforge route <export_dir> [--library ~/mus] [--song-slug X] [--symlink] [--dry-run]
```

### 2. Library bootstrap (`tools/init_library.py`)
Creates the new `Loops/{Drums,Bass,Melodic,Vocal}` subdivision plus `Oneshots/*`, `Vocals/`, `_Incoming/`, `Projects/Stems/`. Idempotent — preserves existing user dirs (e.g. `Loops/pauls_loops/`).

```
uv run python tools/init_library.py            # default ~/mus
uv run python tools/init_library.py --dry-run  # preview only
```

### 3. `stems_only` preset (workaround until raw-stem loader lands)
`presets/stems_only.json` + `v0/src/m4l-package/StemForge/presets/stems_only.json` (mirrored). Drops one curated 8-bar phrase per `drums/bass/vocals/other` on its own track, no chains. Description honestly notes the limitation.

`drums_only_split` deferred — needs sub-stem manifest support; in the device plan as Change 3.

### 4. Five song-form template specs (`docs/song-forms/`)
Per-form: tempo, total bars, locator placements, track lanes, processing chains, sample-set inputs. Each ends with a numbered "Building this template in Live" recipe (~25-35 min user time).

| Form | BPM | Bars | Vibe |
|---|---|---|---|
| `lofi_aaba` | 86 | 84 | Lo-fi hip hop, AABA |
| `ambient_long_form` | 70 | 128 | Eno/Hecker layer evolution |
| `idm_squarepusher` | 160 | 80 | Vertical IDM, drum chaos escalation |
| `idm_fourtet_evolve` | 120 | 96 | Horizontal IDM, organic accumulation |
| `big_beat_drop` | 132 | 128 | Chems/Prodigy, BREAKDOWN→DROP |

Templates live in `~/mus/Templates/<slug> Project/<slug>.als` after building.

### 5. Prechop tool (`stemforge/prechop.py`, `stemforge prechop` CLI)
Slices each full stem into bar-aligned chunks for arrangement-view import. Output:

```
<output>/
  drums/{001,002,...}.wav  + .manifest_<hash>.json sidecars + .manifest.json batch
  bass/...
  vocals/...
  other/...
  prechop_manifest.json
```

Drag a stem subdir onto an arrangement-view track → Live places head-to-tail. Test fixture for ep133 song-mode export.

CLI:
```
uv run stemforge prechop <stems_dir> [--bars 4] [--output ~/Desktop/chunks]
```

Smoke-tested: `~/stemforge/processed/beware` (156.61 BPM) → 59 chunks × 4 stems × 6.13s/chunk. Output dir written to `/tmp/prechop_smoke` may still be on disk.

### 6. Device-changes plan (`docs/exec-plans/curation-library-device-changes.md`)
**Review-gate doc — no device JS edits made.** Three pending changes ordered by risk:

1. **Export-vs-distribute toggle** (low) — `sf_clip_export.js` UI dropdown + `spec.json` schema additions; bouncer issues a second `[shell]` call to `stemforge route` after bounce.
2. **Sub-stem paths in manifest** (low) — `stems.json` schema + `oneshot.py` plumbing; surfaces LarsNet `kick/snare/toms/hihat/cymbals` paths.
3. **Raw-stem loader target type** (medium) — new `target.type === "stem"` branch in `stemforge_loader.v0.js`; unblocks proper `stems_only` and `drums_only_split` presets.

Awaiting per-change sign-off. User said "BE CAREFUL ON THE DEVICE CHANGES!!!"

## Known issues / messy state

- **`tests/ep133/test_song_integration.py` left in DU (deleted by us) state on this branch.** The file got into the working tree from a parallel agent worktree's stash pop; it doesn't belong on `feat/curation-library-v2`. A `git rm` was issued but the user rejected the follow-up investigation. Easiest fix: `git restore --staged tests/ep133/test_song_integration.py && git checkout -- tests/ep133/test_song_integration.py` — but only if the file is supposed to be on this branch. Otherwise, accepting the deletion is correct.
- **Stash `stash@{0}`** holds `ep133-test-fixture-WIP-not-mine` — captured during a branch switch from `feat/ep133-song-export`. Belongs on `feat/ep133-song-export`, not here. Apply there with `git stash apply stash@{0}` after switching branches.
- **Worktree at `/private/tmp/sf-song-export`** has `feat/ep133-song-export` checked out, blocking direct `git checkout feat/ep133-song-export` from the main worktree.
- **Branch silently switched twice during the session** — once when the user manually edited cli.py (probably from the other worktree), once during automated tooling. Verify branch with `git rev-parse --abbrev-ref HEAD` before commits if continuing.

## What the user needs to do next

In rough order of leverage:

1. **Run `uv run python tools/init_library.py --dry-run`** to preview the new subdivisions, then run without `--dry-run` once happy.
2. **Test prechop on a real song:**
   ```
   uv run stemforge prechop ~/stemforge/processed/<song>
   ```
   Then drag the stem subdirs into a fresh Ableton arrangement-view session and run ep133 song-mode export against it.
3. **Build any one of the 5 `.als` templates** in `~/mus/Templates/` from its spec — `lofi_aaba` is the smallest (~25 min) for testing the workflow.
4. **Sign off on device changes** in `docs/exec-plans/curation-library-device-changes.md` — pick which of the 3 to start with.
5. **Push the branch** when ready: `git push -u origin feat/curation-library-v2`.

## What I would build next given a green light

Top of the list:
- Wire `stemforge route` into `m4l_export_clips.py` as an opt-in second pass, controlled by a new `post_action` field in `spec.json`. **Doesn't require device JS** — bouncer ignores unknown spec fields, and when sf_clip_export.js eventually adds the UI toggle, no further bouncer changes are needed.
- Or: a small Python `als_patcher.py` that reads an existing `.als`, patches tempo + locators in the gzipped XML, and saves a new `.als`. Tracks still manual but locator-set + tempo automated, which are the most repetitive parts of the build recipes. Fragile but bounded.

## Memory updates

- `reference_mus_library_structure.md` — canonical taxonomy at `~/mus/`
- `project_curation_library_v2_state.md` — branch state snapshot (this session)
