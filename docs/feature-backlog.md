# StemForge Feature Backlog

Captured 2026-04-25. Source: user brainstorm. Implementation note for **all** items: any audio export must conform to the EP-133 manifest contract in [specs/manifest-spec.md](../specs/manifest-spec.md) — per-file `.manifest_<hash>.json` sidecars and/or directory-level `.manifest.json` batch manifests, with the `SampleMeta` / `BatchManifest` Pydantic schemas as the source of truth.

---

## 1. Bounce-to-Clip + Recent-Clip Collector  (NOW — if possible; beta release goal)

**Status (2026-04-25, evening).**
- ✅ Shipped: [v0/src/m4l-js/sf_clip_export.js](../v0/src/m4l-js/sf_clip_export.js) (JS module, dual-located in m4l-js + m4l-package), [tools/m4l_export_clips.py](../tools/m4l_export_clips.py) (Python helper), 11 round-trip tests in [tests/test_m4l_export_clips.py](../tests/test_m4l_export_clips.py), `sf_clip_export` registered in [v0/interfaces/device.yaml](../v0/interfaces/device.yaml).
- ⚠️ **Remaining (Max-editor work):** add the BOUNCE button to `sf_ui.js` paint+click, route `bounce_clips_click` → `sf_clip_export.exportClips` in the patcher builder, wire NDJSON return path. Step-by-step in [docs/clip-export-button-wiring.md](clip-export-button-wiring.md).
- ⚠️ **V1 limitation:** warped clips are bounced from the SOURCE audio (no warp baking). Trimming to active loop region works; warp markers don't apply. V2 needs `track.freeze()` + polling.



**Problem.** Forge currently consumes audio files. The user is often working on cropped clips inside a live Ableton session and has to export them by hand before forging.

**Two-part feature.**

- **a) Find & collect recent cropped clip(s) from the currently open Live session.** Reach into the LOM (or Node-for-Max bridge) to enumerate recently edited / selected audio clips, pull their underlying audio + clip start/end + warp markers, and stage them as forge inputs.
- **b) "Bounce-to-clip" button in the M4L device.** Bounces the **selected tracks** in place to audio clips so they become collectable forge inputs. Should respect track selection in the Live session view (not the device's own selection).

**Manifest-spec hookup.**
- For every bounced/collected `.wav` staged as a forge input, write a sidecar `.manifest_<hash>.json` populated with:
  - `name` — clip name (≤16 char trim)
  - `bpm` — Live session tempo (or per-clip warp BPM if non-default)
  - `time_mode` — `"bpm"` for warped loops
  - `source_track` — Live track name
  - `stem` — only if the bounce comes from a known stem track; otherwise omit
  - `role` — `"loop"` for a phrase, `"one_shot"` for a hit
- If multiple clips are collected in one operation, also drop a `.manifest.json` batch manifest in the staging dir.

**Open questions.**
- Bounce-in-place semantics: do we render with effects or pre-fader? Default to **post-fader, with effects** (matches Ableton's "Freeze and Flatten").
- Where do bounced files live? Proposal: `<session_dir>/_stemforge_bounce/<timestamp>/`.
- Must work whether forge runs from CLI or from the M4L device.

---

## 2. Forge Skills — Full CLI + In-Live Device Control  (NOW — urgent)

**Problem.** The forge workflow spans CLI commands (`stemforge split`, `forge`, `generate-pipeline-json`) and M4L device interactions (load, select source, commit). There's no single Claude-invocable surface for the end-to-end loop.

**Deliverable.** A set of Claude Code skills under `.claude/skills/` that wrap the full forge lifecycle:

| Skill (proposed) | What it does |
|------|------|
| `/forge-launch` | Launch Ableton Live; open the StemForge default set if no set is already open. |
| `/forge-pick` | Pick patch + source via the M4L device (LOM script or device-bridge call). |
| `/forge-default` | Run `stemforge forge <source>` with the standard defaults — produces both the auto-curation and the arrangement manifests. Streams progress. |
| `/forge-commit` | Trigger the device's COMMIT action (writes track templates / pads to Live). |
| `/forge-all` | Composed skill: launch → pick → run → commit. One-shot. |

**Manifest-spec hookup.**
- Every skill that produces or consumes audio MUST go through the manifest layer — i.e. forge writes sidecar + batch manifests for its outputs, and any downstream skill (e.g. EP-133 upload via the `ep133-ppak` repo) reads them as `SampleMeta` / `BatchManifest`.
- Skills should pass **CLI flags as the highest-priority overrides** per the resolution order in the spec — never bake field values into the skill that conflict with what a user could pass through.

**Status (2026-04-25).**
- ✅ **Shipped:** `/forge-launch`, `/forge-default`, `/forge-all` (launch + run composition). Skills live at `.claude/skills/forge-{launch,default,all}/SKILL.md`. (`/forge-default` replaced the original `/forge-run` once `stemforge forge` started producing auto-curation + arrangement.)
- ⛔ **Blocked:** `/forge-pick` and `/forge-commit`. The M4L device has **no external control surface today** — all triggers come from UI buttons routed through `sf_forge.js` / `stemforge_bridge.v0.js` inlets. To make these skills work, the device needs an externally-pokeable input (cheapest path: add a `[fswatcher]` on a control file like `~/.stemforge/cmd.json`; the device JS reads + dispatches the command on file change). Until that lands, the user has to hit the buttons inside Live by hand.

**Open questions.**
- Device control transport: chosen direction is **fswatcher on a JSON control file** (lightest device change, no network port, no permissions dialogs). Confirm before authoring the device-side patch.
- Should `/forge-launch` boot a known `.als` template, or attach to the front-most Live session? **Decided:** opens `v0/build/StemForge.als` if the user mentions "StemForge"/"the template", otherwise just launches Live.

---

## 3. Commit-With-Bounce — Freeze Warp + Post-Processing  (LATER)

**Problem.** Once warp markers are dialed in or a post-processing pipeline (e.g. saturation, EQ, time-stretch) is applied inside Live, those changes are not baked into the output. Re-loading the source rehydrates the un-processed audio.

**Deliverable.** Extend the M4L device's COMMIT action with an optional **bounce** step:
- Render the in-Live state (warped + post-processed) to audio.
- Replace (or augment) the source files in the manifest with the bounced versions.
- Re-curate / re-slice if needed (open question — see below).

**Manifest-spec hookup.**
- Bounced files get fresh `audio_hash` (sha256 first 16 hex of new bytes) and fresh sidecars.
- Old sidecars must be invalidated/replaced; never leave a sidecar pointing to the un-bounced hash.
- `bpm` on the bounced output reflects the Live session tempo (since warp is now baked).

**Dependencies.**
- Post-processing pipelines must exist as a first-class concept (currently they don't — see "must-have eventually" callout from user).
- This implies a `pipelines/post/*.yaml` sibling to existing pipelines, with stages applied in Ableton via the M4L device.

**Open questions.**
- Bounce only the freezable bits, or full track render? Probably **per-track render** so we can keep stem identity in the manifest.
- Re-slice after bounce? Likely **yes** for warp-frozen drum loops (slice grid changes after warp bake).

---

## 4. VST Extraction — Strip Non-Native Devices, Preserve on Branch  (NOW — should be quick)

**Problem.** Some existing track templates / pipeline configs depend on third-party VSTs. This kills portability — anyone without those plugins can't load the templates. Track templates with specific VSTs are not really templates.

**Deliverable.**
1. Audit the current main branch for any track template / preset / pipeline config that references a third-party VST (i.e. anything not a stock Ableton Live device — cross-reference against [stemforge/data/live_devices.json](../stemforge/data/live_devices.json)).
2. **Preserve the VST work** on a new GH branch — proposed name: `experimental/vst-templates`. Push it. Don't lose it.
3. On `main` (or a feature branch off main): **remove** the VST-dependent templates and any code paths that hard-code those VSTs. Replace with Ableton-native equivalents where a clean swap exists; otherwise just delete the template and note its absence.
4. Verify all remaining templates load cleanly in a vanilla Ableton Live install (no extra plugins).

**Manifest-spec hookup.**
- Indirect: the manifest schema is plugin-agnostic, but removing VST dependencies means the `.ppak` / EP-133 path can be exercised on more machines. Sidecars don't change.

**Important.** **Keep the work around.** The branch is preservation, not deletion. Revisit when we want a "premium" template tier or a known-VST environment.

**Open questions.**
- Which templates are affected? Needs a quick grep before scoping.
- Are there device chains (`stemforge/data/...`) that bake VST UUIDs? Those need extracting too.

---

## Bug: stems.json bakes absolute paths

**Captured 2026-05-02** during the tempo-reconciler beat-match test. After
forging Definition + Ooh La La to `/tmp/sf_*_out/...` and copying both
processed dirs to `~/stemforge/processed/UPDATE/`, `stems.json` still
referenced `/private/tmp/...` for `output_dir`, `stems[*].wav_path`, and
`stems[*].beats_dir`. Consumers (M4L `sf_state.js`, arrangement loader,
exporters) follow those absolute paths and load the wrong files (or fail
silently if the original `/tmp` is cleaned up).

**Why it matters.** The user moves processed dirs around frequently —
copying to USB sticks, syncing to other machines, archiving old runs. Any
absolute path in a manifest is a portability landmine.

**Scope.**
- [stemforge/manifest.py](../stemforge/manifest.py) `write_manifest`
  currently calls `.resolve()` on every path before writing. Switch to
  paths relative to the manifest's own directory (the prechop manifest
  already does this — copy that pattern).
- Decide what to do with `source_file`: it's a back-reference to the
  *input* mix, which lives outside the processed dir, so it's legitimately
  absolute. Either keep it absolute and document the meaning, or store as
  `null` after copy and rely on `input_audio.sha256` + filename for
  identity.
- One-time migration: a small `stemforge migrate-manifests` command that
  walks `~/stemforge/processed/` and rewrites baked-absolute paths to
  relative ones. Cheap to write; saves the user's existing forge history.

**Manifest-spec hookup.**
- The per-sample sidecar/batch contract in [specs/manifest-spec.md](../specs/manifest-spec.md)
  already uses `file: str` as a bare filename or relative path — it's only
  `stems.json` (the pipeline-level manifest) that has this bug.

**Workaround until fixed.** A path-rewrite snippet patches stems.json
after-the-fact (see the rewriter used in the 2026-05-02 UPDATE/ copy):

```python
# Rewrite absolute paths in a copied stems.json to point at the new dir.
sj['output_dir']            = str(new_root / track)
sj['stems'][*].wav_path     = str(new_root / track / f'{stem}.wav')
sj['stems'][*].beats_dir    = str(new_root / track / f'{stem}_beats')
```

---

## Ableton-anchored auto-detection (the auto-detection ceiling closer)

**Captured 2026-05-02** during the Ooh La La / Definition tempo-fix session.
Auto-detection (beat-this + bar-period BPM + mode-walk first downbeat) gives
a CORRECT BAR GRID, but the algorithm cannot tell which bar of the grid is
musically bar 1 — that's a perceptual call only the user can make. The
current workflow makes the user iterate `probe_loop.py` candidates to find
the right `first_downbeat`, then `re-anchor` the forge in place. Iteration
is fast (re-anchor is ~2s) but it's still N round-trips through Ableton.

**Two Ableton-integrated affordances would close the gap:**

1. **Anchor from a locator / warp marker.** User drops a locator (or warp
   marker) at what they hear as the song's bar 1, then triggers an
   "anchor here" command in the M4L device. The device reads the marker
   position from the LOM, exports it to disk, and the Python side
   re-anchors the forge to that exact source-time. Single click, no CLI.
   Probably reuses sf_arrangement_loader's LOM access patterns.

2. **Validate BPM from a dragged loop region.** User drags the loop region
   to enclose a known-clean N-bar loop, triggers "verify BPM." The device
   reads `loop_start` / `loop_end` (in seconds, with warping=0), computes
   `60×4×N / (loop_end - loop_start)` for various N (in 1, 2, 4, 8, 16),
   shows the candidate BPMs, and lets the user pick + re-anchor. Catches
   the cases where bar-period detection lands ~1% off.

Both build on the LOM access we already have. Polish needed: button on the
device, status feedback, error handling for missing source file, etc.

**Also worth flagging — Ableton timeline display drift.**
Confirmed 2026-05-02: when first_downbeat in the manifest is 22.59s, Ableton's
arrangement-view timeline shows the corresponding chunk start at ~22.56s.
~30ms of display drift between our seconds-precise `start_marker` /
`source_offset_sec` and what Ableton renders. Doesn't affect playback (clip
content is correct, beats align with the project grid), but it's confusing
for the manual fine-tune workflow because the user can't read off the same
seconds value the manifest claims. Possible causes: Ableton rounding to its
display granularity, latency from start_marker setting, our chunk's WAV
header reporting durations a few samples shorter than expected. Investigate
before shipping the locator-anchor feature so the user's eyeballed time
matches what the device records.

---

## Trim-leading-silence preprocessor

**Captured 2026-05-02.** When a source audio file has true silence at the
start (e.g. studio recordings with cold-cut intros: Believer-class tracks),
we currently still detect first_downbeat via kick onset analysis + override
iteration. A simple `--trim-leading-silence-below DB` preprocessor would
strip leading frames whose RMS is below threshold (e.g. -60 dB) from the
source mix BEFORE Demucs / detection runs. For silent-intro tracks, the
trimmed source has bar 1 near frame 0 — auto-detection becomes trivial.

For tracks with non-silent intros (Ooh La La's 22s of DJ scratching, etc.),
the trim is a no-op since RMS exceeds the threshold from frame 0.

**Scope** (~30 lines):
- `stemforge.preprocess.trim_leading_silence(audio_path, threshold_db) -> trimmed_audio_path`
- CLI flag `--trim-leading-silence-below DB` on `split` (default off; set to e.g. -60 to enable)
- Record `trimmed_leading_seconds` in stems.json so `source_offset_sec` math
  in prechop_manifest stays consistent with the original source file
  (consumer adds back the trimmed offset if it cares about original timeline)

**Caveats** (the failure modes that mean this can't be the only fix):
- Vinyl crackle, room tone, noise floor → "silence" is at -40 dB not -inf;
  threshold becomes track-dependent
- Fade-ins → ambiguous cut point
- Bar 1 starting on a rest (anacrusis pickup precedes) → trim would skip past
- Leading content IS musical (intros, count-ins, samples) → trim discards
  legitimate audio that user might want as `--pre-bars` material

So: useful as an opt-in preprocessor for the easy case. Doesn't replace
first_downbeat detection.

---

## Cross-Cutting: Manifest-Spec Conformance

For all four items, when implemented:

1. Add `stemforge/manifest_schema.py` if it doesn't exist yet, mirroring the canonical schema in [specs/manifest-spec.md](../specs/manifest-spec.md). `ep133-ppak` mirrors this — keep them in sync.
2. Any code path that writes audio for downstream consumption (forge, bounce, collect, commit) must write:
   - A per-file sidecar `.manifest_<hash>.json` (hash = sha256 of WAV bytes, lowercase hex, first 16 chars), AND
   - A batch `.manifest.json` in the export root.
3. Loaders / consumers resolve in order: **CLI flags → sidecar → batch → built-in defaults**. CLI always wins.
4. Field-population guidance from the spec (name trimming, default playmodes, suggested_group/pad as advisory only) applies everywhere.

This sample-level manifest does NOT replace `stems.json` — that remains the pipeline-level contract.
