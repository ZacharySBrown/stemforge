# Breaks-n-Beats Session Debrief — 2026-05-11/12

## Status

**SHIPPED + HARDWARE-VALIDATED.** A full multi-source hip-hop verse-swap kit (`breaks-n-beats1.ppak`, 46 pads across A/B/C/D) loads, plays, and beat-matches on the EP-133 K.O. II. User confirmed an hour of live play with no issues.

Two commits ship the underlying machinery:

1. **PR #62 (merged)** — `feat(ep133): deck-from-manifest + build-deck pipeline w/ per-clip warp_bpm` — the bulk of the EP-133 deck pipeline + five bug fixes + initial per-clip BPM capture.
2. **Pending commit on `main`** — `_collapseToLoopRegion` helper in the bounce flow + 6 JS mock tests + pytest bridge.

This doc covers what was learned *across both commits and the hardware-validation pass*. It supersedes the prior in-tree `EP133_DEBRIEF.md` (now removed; disposition tracked in [`docs/issues/ep133-debrief-disposition.md`](../issues/ep133-debrief-disposition.md)).

## What works end-to-end

```
   Ableton session view (manual arrangement)
              ↓
   sf-remote fire forge bounceTracks <manifest-path>
              ↓                              ↑
   _bounceCropTrack per A/B/C/D              │ via UDP/OSC on port 7420
     ├─ _capturePreCropMeta (warp_bpm slope) │ patcher route /forge
     ├─ _collapseToLoopRegion (NEW)          │
     └─ clip.call("crop") — renders at warp_bpm
              ↓
   _commitSessionTracks writes session_tracks block
              ↓
   stemforge deck-from-manifest → deck.yaml
              ↓
   patch format_profile / play_mode if needed
              ↓
   stemforge build-deck → .ppak  (+ .projectspec.json sidecar)
              ↓
   K.O. II Sample Tool → import as project → slot 8
```

End-to-end timing for a 46-clip deck: **~12 seconds** (bounce 3s × 4 tracks, COMMIT <1s, deck-from-manifest <1s, build-deck <1s).

## Key technical findings

### Live LOM (Max for Live)

1. **`warp_bpm` does not exist on Clip — read OR write.** Verified against Cycling '74's official LOM reference. Both `set` and `get` raise `'Clip' object has no attribute 'warp_bpm'`. Memory: [`feedback_arrangement_clip_lom.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_arrangement_clip_lom.md).

2. **The warp BPM IS recoverable** — `warp_markers` (dict, read-only, observe) is exposed. Slope between the first two markers equals the displayed warp BPM. `clipApi.get("warp_markers")` returns `["<json-string>"]` (one-element array wrapping `{warp_markers: [{sample_time, beat_time}, ...]}`). Implementation: `_warpBpmFromMarkers` in [`stemforge_loader.v0.js:1741`](../../v0/src/m4l-package/StemForge/javascript/stemforge_loader.v0.js#L1741).

3. **`sample_time` unit ambiguity** — LOM docs don't say whether it's samples or seconds. We try the seconds interpretation first (`bpm = Δbeats × 60 / Δtime`); if that lands outside 30–400, retry as samples (multiply by `sample_rate`). Validated on 21 clips across 4 source tempos.

4. **`clip.call("crop")` renders at warp_bpm, not session BPM.** Memory: [`feedback_clip_crop_renders_at_warp_bpm.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_clip_crop_renders_at_warp_bpm.md). Consequences:
   - Pre-crop metadata capture is mandatory (`_capturePreCropMeta` runs *before* `crop`).
   - The manifest's `end_offset_sec` (computed at project tempo) is **not** a reliable slice point on the bounced WAV.
   - The kit synthesizer must use the full bounced WAV and infer source BPM from its actual duration when no explicit `source_bpm` is available.

5. **Loop region vs play region — separate writable markers.** `start_marker`, `end_marker`, `loop_start`, `loop_end` are all writable. Units flip with `warping` (beats if 1, seconds if 0). The new `_collapseToLoopRegion` writes loop bounds onto play-region markers *before* crop so the loop region gets materialized into the bounced WAV.

6. **`launch_mode` exists on Clip** — int property, observable. Relevant for the M4L pipeline → device's `play_mode` (we currently set it via the deck row, not by reading the clip).

### EP-133 K.O. II protocol

1. **Per-sample 20-second cap.** Memory: [`feedback_ep133_per_sample_cap_20s.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_ep133_per_sample_cap_20s.md). The kit synthesizer now **skips with warning** rather than truncating — clips >20s never make it to the device.

2. **`.ppak` `pak_type` must be `"project"` for project-import.** Memory: [`feedback_ppak_writer_pak_type_default.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_ppak_writer_pak_type_default.md). Sample Tool's project-import rejects `"user"` paks.

3. **`patterns/d05` marker collision** — `ppak_writer` was emitting an empty song-mode marker pattern at `d05`. When a deck populates a real `d05`, the TAR has a duplicate that kills Sample Tool partway. Memory: [`feedback_ppak_writer_d05_marker_collision.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_ppak_writer_d05_marker_collision.md).

4. **`project_reader` off-by-one** — `raw[10:-1]` not `raw[9:-1]`. Plus EOF threshold relaxed to half-page so slight unpack length differences don't false-trip.

5. **Drum profile = `key` play-mode + envelope.release=15.** Memory: [`feedback_drum_profile_defaults.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_drum_profile_defaults.md). Hardware-validated for hold-to-play drum loops.

6. **Coupled fields** — `playmode` must pair with `envelope.release` or gate behavior silently fails. Memory: [`feedback_ep133_coupled_fields.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_ep133_coupled_fields.md).

### Bar-count inference (kit synthesizer fallback)

When per-clip `source_bpm` isn't captured (e.g. unwarped clip, M4L predates the warp_markers change), `kit_synthesizer._infer_source_bpm` snaps duration to one of `{0.25, 0.5, 1, 2, 3, 4, 8}` bars. **5/6/7 are excluded** — they steal scoring wins from the right 4-bar interpretation (e.g. an 11.29s 4-bar @ 85 BPM was misclassified as 5-bar @ 106 BPM). Memory: [`feedback_bar_inference_candidates.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_bar_inference_candidates.md). Followup: [`docs/issues/bar-inference-canopy.md`](../issues/bar-inference-canopy.md) if Take Five-like content is ever needed.

### BPM detection caveats (real-world)

Of 14 grooves auto-detected, **3 needed manual overrides**:
- `braun_blek_blu` — detected 282.54, real 141.27 (doubled, krautrock).
- `tombo_in_7_4` — detected 507.67, real 138 in 7/4 (Airto Moreira's odd-time piece confused the 4/4 grid).
- `heather` — detected 66.12, real 132.24 (halved, slow ballad).

The 4/4 grid bias is structural: beat-this:mix returns implausible numbers for odd meters, librosa fallback can halve/double. **`--time-sig` only works on `stemforge forge`, not `stemforge split`** — see [`docs/issues/split-time-sig-flag.md`](../issues/split-time-sig-flag.md). For now, just override `--bpm` directly.

## File-level changes (since PR #62 merged)

- `v0/src/m4l-{js,package/StemForge/javascript}/stemforge_loader.v0.js` — new `_collapseToLoopRegion` helper + 2 call sites in `_bounceCropTrack`. JS in both locations must stay in sync per [`feedback_js_source_of_truth.md`](../../../.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/feedback_js_source_of_truth.md). Installed runtime copy at `~/Documents/Max 9/Packages/StemForge/javascript/` also kept in sync after .pkg install.
- `tests/js_mocks/test_bounce.test.js` — 6 new test cases covering looping=1 + divergent bounds, looping=0 unchanged, idempotent same-bounds, degenerate bounds safety guard, plus `_collapseToLoopRegion` unit tests.
- `tests/test_js_bridge.py` — new pytest test `test_js_bounce_suite` runs the Node test file. Brings pytest total to 843.
- `tools/batch_grooves.sh` + `tools/batch_grooves_overrides.sh` — sequential batch processors for the grooves directory (one-time use, kept for reproducibility).
- `v0/build/StemForge.amxd` — rebuilt for current JS staging (.amxd doesn't inline the JS, but byte-identical rebuilds prevent drift).
- `v0/build/StemForge-0.0.1.pkg` — rebuilt with the new JS staged.

## Grooves processing run (one-time data)

14 source tracks (Isaac Hayes, Fela, Neu!, Mingus/Blakey, The Mohawks, Bobby Womack, Charles Wright, Roy Ayers, Airto Moreira, James Brown, Lee Perry, Keith Mansfield) → processed via `stemforge split --pipeline arrangement` + `stemforge_curate_bars.py --curation pipelines/curation.yaml`. All 14 have `stems.json` + `prechop_manifest.json` + `curated/manifest.json` under `~/stemforge/processed/<slug>/`.

The 14 slugs (BPM in parens after overrides):

| Slug | BPM | Notes |
|------|-----|-------|
| disc_2_12_run_fay_run | 119.06 | |
| expensive_shit_explicit | 124.44 | |
| hallogallo_stephen_morris_and_gabe_gurnsey_remix | 152.99 | possibly doubled? |
| moanin | 145.17 | |
| the_champ_original_version | 112.02 | |
| across_110th_street_bobby_womack_master_cut | 110.05 | |
| express_yourself | 92.71 | |
| **braun_blek_blu** | **141.27** | manual override (×½) |
| taurian_matador | 132.27 | |
| **heather** | **132.24** | manual override (×2) |
| **tombo_in_7_4** | **138.0** | manual override + 7/4 numerator |
| hot_pants_i_m_coming_i_m_coming | 111.93 | |
| roast_fish_cornbread | 115.20 | |
| funky_fanfare | 95.85 | |

The deck file picker in the M4L device picks these up automatically — they appear in the song-selection dropdown alphabetically (sorted in `sf_manifest_loader.js:253`).

## The breaks-n-beats1 .ppak

Built end-to-end on 2026-05-12 via:

```bash
# In Ableton: 46 clips manually arranged on tracks A=12, B=12, C=10, D=12
uv run sf-remote fire forge bounceTracks /Users/zak/stemforge/decks/breaks_n_beats1/curated/manifest.json
# Wait for bounce + COMMIT (~12s for 46 clips)
uv run stemforge deck-from-manifest <manifest> --out <deck.yaml> --project breaks_n_beats1 --project-slot 8
# Patch all format_profile→drum + play_mode→oneshot→key (regex)
uv run stemforge build-deck <deck.yaml> --out ~/Desktop/breaks-n-beats1.ppak
```

Result: 9.5 MB .ppak, memory 12.1/60 MB on device, drag-drop into Sample Tool → import as project → slot 8.

## What's NOT addressed by this stream

Followup issues are tracked individually under `docs/issues/`:

- [`ep133-delete-tracks.md`](../issues/ep133-delete-tracks.md) — feature gap: no way to delete individual tracks/pads from a project via our CLI.
- [`udp-osc-cleanup.md`](../issues/udp-osc-cleanup.md) — `reload` forwarder is broken; bounce stub race; misc UDP loose ends.
- [`js-reload-forwarder-broken.md`](../issues/js-reload-forwarder-broken.md) — `sf-remote fire forge reload` doesn't actually reload Max [js] (no handler in loader).
- [`bounce-stub-race.md`](../issues/bounce-stub-race.md) — `_deriveDeckManifestPath` writes 217-byte stub before crop loop; readers can race against the fill.
- [`loop-region-collapse-second-bounce.md`](../issues/loop-region-collapse-second-bounce.md) — `_collapseToLoopRegion` is untested against re-bouncing already-cropped clips.
- [`bar-inference-canopy.md`](../issues/bar-inference-canopy.md) — 5/6/7-bar exclusions revisit if odd-meter content needs supporting.
- [`split-time-sig-flag.md`](../issues/split-time-sig-flag.md) — `stemforge split` is missing `--time-sig`; only `forge` has it.
- [`presets-clean-json-disposition.md`](../issues/presets-clean-json-disposition.md) — color refactor excluded from PR #62, needs decision.
- [`worktree-cleanup.md`](../issues/worktree-cleanup.md) — `.claude/worktrees/{curation-library-router,tempo-detection-half-time}/` need disposition.
- [`dump-file-split.md`](../issues/dump-file-split.md) — root `DUMP` is a hybrid tree+log+docs.
- [`log-file-collision.md`](../issues/log-file-collision.md) — root `log` is a text file blocking `mkdir log/` patterns.
- [`max-startup-sendmessage-errors.md`](../issues/max-startup-sendmessage-errors.md) — three `SendMessage error 2` at Max startup, unexplained.
- [`ep133-debrief-disposition.md`](../issues/ep133-debrief-disposition.md) — root `EP133_DEBRIEF.md` is now redundant.
- [`hardening-test-coverage-gaps.md`](../issues/hardening-test-coverage-gaps.md) — JS mock suites not all wired into pytest; CLI-command tests missing for `deck-from-manifest` + `build-deck`.

## Pointers for the next agent

The handoff for steps 1-4 in the user's request (finish hardening, clean repo, polish docs, consider release) lives at [`docs/handoff/2026-05-12_next_agent_brief.md`](../handoff/2026-05-12_next_agent_brief.md).
