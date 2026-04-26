# Device-side changes for curation library — exec plan

Three device-touching changes follow the curation-router work landing on
`feat/curation-library-v2`. None are written yet. **This doc is review-
gate** — once you sign off on a change set, we cut a focused branch and
follow the standard pipeline (debug patch in standalone Max → build_amxd.py →
build-pkg.sh → install). Per the Test & Deploy Discipline memory, no manual
.amxd copies, no skipped steps.

## Change 1 — Export-vs-distribute toggle (smallest, do first)

**What it does:** UI control on the device that picks one of three modes:

| Mode | Behavior |
|---|---|
| `export only` (default) | Bounce writes to `~/stemforge/exports/<song>/`. Library untouched. |
| `distribute only` | Bounce writes to a tmp dir, then router relocates everything into `~/mus/Samples/`, then tmp dir is cleaned up. |
| `export and distribute` | Bounce writes to `~/stemforge/exports/<song>/` AND router copies into `~/mus/Samples/`. (Default after first use, probably.) |

**Where it lives:**
- `sf_clip_export.js` (in BOTH `v0/src/m4l-js/` and `v0/src/m4l-package/StemForge/javascript/` — JS dual-location sync)
- The bounce spec (`spec.json` written by sf_clip_export.js → consumed by `tools/m4l_export_clips.py`) gains a new field:
  ```
  "post_action": "export_only" | "distribute_only" | "export_and_distribute",
  "library_root": "/Users/zak/mus"     # only present when post_action != export_only
  ```
- After the bouncer finishes, sf_clip_export.js issues a second `[shell]` call:
  ```
  uv run stemforge route <export_dir> --library <library_root>
  ```
  (Or, in `distribute_only` mode, runs route then deletes the temp dir.)

**Risk assessment:**
- **Low** for the JS UI control — adding one umenu/dropdown to the bounce panel.
- **Low** for the spec.json schema additions — bouncer ignores unknown fields.
- **Low** for the second shell call — independent of bounce, errors don't cascade.
- **Medium** for the dual-location sync discipline — easy to forget to copy JS into both `v0/src/m4l-js/` and `v0/src/m4l-package/`. Will run the existing build-pkg.sh which copies for us.

**Configurability question** (your earlier ask): the export dir path
(`~/stemforge/exports/`) becomes a device-level setting too, in case you
later want it inside `~/mus/Exports/` to consolidate everything in `~/mus/`.
Default stays at `~/stemforge/exports/`.

## Change 2 — Raw-stem loader target type (medium)

**What it does:** Adds a new `target.type === "stem"` (or `"raw_stem"`)
handler in `stemforge_loader.v0.js`. When the preset says
`{ "type": "stem" }`, the loader skips curation entirely and loads the
full stem WAV onto a single track, in clip slot 1.

**Why this matters:** unblocks the *real* `stems_only.json` preset (drop
each main stem on its own track, no slicing) AND the
`drums_only_split.json` preset (one track per LarsNet sub-stem). Today's
`stems_only.json` is a workaround that drops one curated 8-bar phrase per
stem because there's no raw-stem path.

**What changes:**
- `v0/src/m4l-package/StemForge/javascript/stemforge_loader.v0.js` —
  add a third branch alongside `target.type === "clips"` and `"rack"`:
  ```javascript
  } else if (target.type === "stem") {
      var stemWavPath = manifest.stems[stemName].wav_path;
      if (!stemWavPath) { status("    skipped (no stem wav)"); continue; }
      var trackIdx = trackCount();
      createAudioTrack(trackIdx);
      renameTrack(trackIdx, targetName + " | " + songName, targetColor);
      if (chain.length > 0) applyInsertChain(trackIdx, chain);
      loadClipToTrack(trackIdx, stemWavPath, /*slotIdx*/ 0);
      loaded += 1;
  }
  ```
- `stems_only.json` — change all 4 targets from `"type": "clips"` to
  `"type": "stem"`, drop the curation params.
- `drums_only_split.json` — new preset with 6 stem-type tracks (drums +
  kick/snare/hat/toms/cymbals via sub-stem refs, see Change 3) on top of
  the existing 6 curated drum tracks.

**Risk assessment:**
- **Medium**. Touches the core loader's main switch. New code path = new
  failure mode. Mitigation: small, isolated branch, debug in standalone
  Max with the existing harness, add a debug-bang test before deploying
  via build-pkg.sh.
- The loader memory ("M4L Device Development Guide" — 20 pitfalls) is
  the required reading before this branch. Especially the [shell]+[js]
  architecture and the build_amxd.py → build-pkg.sh discipline.

## Change 3 — Sub-stem paths in manifest (small, blocks Change 2 for sub-stems)

**What it does:** When LarsNet runs (today, only as part of one-shot
extraction in `stemforge/oneshot.py`), persist the sub-stem WAV paths
into `stems.json` so the loader can find them.

**What changes:**
- `stemforge/manifest.py` — extend `StemInfo` with optional
  `sub_stems: dict[str, str]` field (e.g. `{"kick": "/path/to/kick.wav", ...}`)
- `stemforge/oneshot.py` — after `separate_drums()` returns the sub-stem
  paths, surface them up to the manifest writer.
- `stemforge_loader.v0.js` — when `target.params.source_substem === "kick"`
  is set on a `"stem"`-type target, look up `stem.sub_stems[<key>]` instead
  of `stem.wav_path`.

**Risk assessment:**
- **Low** for the manifest schema (additive field, ignored by old readers).
- **Low** for oneshot.py (we already have the paths, just plumbing).
- **Low** for the loader change once Change 2 is in (it's an extension of
  the new `"stem"` branch).

## Recommended order

1. **Change 1** first — small, reversible, immediately useful. Land it,
   use it for a couple of bounces, build confidence in the JS shell-call
   pattern before touching the loader.
2. **Change 3** second — pure pipeline change, no device behavior change
   yet. Sub-stem paths show up in manifests.
3. **Change 2** last — the loader extension. By this point we have JS
   call patterns proven (Change 1) and sub-stem paths available (Change 3),
   so the loader change can do everything in one branch.

## Things I'm explicitly NOT doing without your sign-off

- Touching `stemforge_loader.v0.js`
- Touching `sf_clip_export.js`
- Modifying the .amxd
- Running build-pkg.sh or installing a new package
- Changing the manifest writer in `stemforge/manifest.py`

Sign off per change number (e.g. "Change 1 yes, Change 2 hold") and I'll
cut a focused branch off this one for whichever you want to start.
