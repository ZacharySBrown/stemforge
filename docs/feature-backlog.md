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
| `/forge-run` | Run `stemforge forge <source>` with current pipeline. Streams progress. |
| `/forge-commit` | Trigger the device's COMMIT action (writes track templates / pads to Live). |
| `/forge-all` | Composed skill: launch → pick → run → commit. One-shot. |

**Manifest-spec hookup.**
- Every skill that produces or consumes audio MUST go through the manifest layer — i.e. forge writes sidecar + batch manifests for its outputs, and any downstream skill (e.g. EP-133 upload via the `ep133-ppak` repo) reads them as `SampleMeta` / `BatchManifest`.
- Skills should pass **CLI flags as the highest-priority overrides** per the resolution order in the spec — never bake field values into the skill that conflict with what a user could pass through.

**Status (2026-04-25).**
- ✅ **Shipped:** `/forge-launch`, `/forge-run`, `/forge-all` (launch + run composition). Skills live at `.claude/skills/forge-{launch,run,all}/SKILL.md`.
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

## Cross-Cutting: Manifest-Spec Conformance

For all four items, when implemented:

1. Add `stemforge/manifest_schema.py` if it doesn't exist yet, mirroring the canonical schema in [specs/manifest-spec.md](../specs/manifest-spec.md). `ep133-ppak` mirrors this — keep them in sync.
2. Any code path that writes audio for downstream consumption (forge, bounce, collect, commit) must write:
   - A per-file sidecar `.manifest_<hash>.json` (hash = sha256 of WAV bytes, lowercase hex, first 16 chars), AND
   - A batch `.manifest.json` in the export root.
3. Loaders / consumers resolve in order: **CLI flags → sidecar → batch → built-in defaults**. CLI always wins.
4. Field-population guidance from the spec (name trimming, default playmodes, suggested_group/pad as advisory only) applies everywhere.

This sample-level manifest does NOT replace `stems.json` — that remains the pipeline-level contract.
