# Changelog

All notable changes to StemForge. Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

The marquee delivery in this cycle is the **EP-133 K.O. II hardware pipeline** — Ableton arrangement → bounced WAVs → multi-pad `.ppak` deck imported on-device — fully hardware-validated against real hip-hop verse-swap kits. Beneath that, substantial hardening, schema work, and beat-detection corrections shipped across ~160 commits since `v0.0.2-beta`.

### Added

#### EP-133 K.O. II pipeline
- Full SysEx upload library — WAV → device over USB-MIDI, slots 1..255 (89 tests).
- `stemforge export-song` — arrangement-view snapshot → song-mode `.ppak`.
- `stemforge deck-from-manifest` + `stemforge build-deck` — session-view manifest → multi-pad deck `.ppak` with per-clip warp BPM, projectspec sidecar.
- `--profile drum|vocal|texture|preserve_source`, `--all-drum`, `--play-mode oneshot|key|legato` flags on `deck-from-manifest` to retire inline regex patches.
- `tools/ep133_load_project.py` — batch loader with project-archive round-trip; pad layout `bar_001='.'` ascending bottom-left.
- Reference-ppak capture flow + integration tests + workflow doc.
- Protocol additions: `time.mode=bpm` clip stretching, `playmode`↔`envelope.release` auto-pairing, per-pad BPM decoder, project-file reader, per-slot BPM tagging.
- Per-sample 20s cap enforced with skip-warning rather than truncate.
- Drum-profile defaults locked in: `key` play-mode + `envelope.release=15` + float32→clip→int16 conversion (hardware-validated).
- `.ppak` writer hardening: `pak_type=project` default, `patterns/d05` marker collision fix, off-by-one in `project_reader` corrected.

#### M4L device
- COMMIT, BOUNCE, EXPORT, ANCH buttons + supporting JS.
- `_collapseToLoopRegion` — bakes Live's loop region into bounced WAVs (looping clips materialize correctly).
- Atomic-rename bounce-stub flow (`<manifest>.tmp` → final) — readers can no longer race a half-written manifest.
- Arrangement-view loader for prechop output + arrangement-view snapshot reader for EP-133 export.
- v8ui patcher builder — matrix UI + native preset/source dropdowns + COMMIT button + per-target track colors + pill-color migration to Ableton palette.
- In-Ableton locator-anchor workflow for re-cutting bar 1; ANCH as pure timeline shift (no source rewrite).
- Wipe prior stemforge clips before placing new ones on (re)load.
- Per-stem `warp_mode` (`drums`/`bass` = Beats) via `BAR_WARP_MODES`.
- `sf_remote` UDP receiver + `sf-remote fire forge {bounceTracks,reload,...}` forwarder.
- `_alFindClipAtBeat` reverse-walk (kills O(N²) load cost).
- Hardened LiveAPI mock with backing liveTree (Hardening Stream B.2).

#### CLI & pipelines
- `stemforge route` — library-curation router (cherry-picked from `feat/curation-library-router`).
- `stemforge prechop` with padded chunks + `--emit-partial` flag.
- `stemforge reslice-curated` subcommand + auto-reslice on re-anchor.
- `arrangement` mode runs prechop with configurable padding; downbeat-anchored.
- `refine_bpm` always-on + locator bar-snap.
- Vibe-preset library: `ambient_veil`, `brutalism`, `dub_echo`, `spectral_glitch`.
- Session-mode + production-mode curation YAMLs; outlier filter + duration normalize + ref-stem onset alignment.
- Koala sampler bank-zip exporter.
- Bulk re-anchor tool for all processed tracks.
- Five song-form template specs + per-template "Build in Live" recipes.

#### Beat detection / tempo
- Multi-source tempo reconciler (`beat-this:mix` + `beat-this:drums` + librosa fallback) with mean-not-median estimator.
- Bar-period BPM + manual `--bpm` / `--first-downbeat` overrides.
- Mode-walk downbeat + refine-downbeat audit.
- Canonical real-world tempo regression fixtures (Definition / Ooh La La / Believer) gated by `@pytest.mark.has_phase3_inputs`.
- Drums-first-downbeat preference when phase-equivalent to mix (resolves GH #55).

#### Hardening Streams A–E
- A.1 — `audio_hash` on `ChunkMeta`.
- A.2 — Pydantic schemas for the three undocumented JSON contracts.
- B.1 — synthetic-song fixture.
- B.2 — hardened LiveAPI mock with backing liveTree.
- B.3+B.4 — CliRunner smoke + `@pytest.mark.live` opt-in.
- C.1 — vendored `forge_device.audit` + wired to CLI entry points.
- C.2 — vendored `forge_device.verifiers` + non-blocking CI gate.
- C.3 — vendored `forge_device.load_verifier` + CLI wiring.
- D.1 — `m4l.button.commit` Tier-3 tests against the hardened LiveAPI mock.
- D.2 — path-coverage audit + triage closures.
- E — canonical tempo regression fixtures + `refine_bpm` always-on + locator bar-snap.
- HW-3 (.amxd→.maxpat) + HW-4 (`sf_remote` UDP receiver) closed.

#### Configurator (Phases 1–2.5)
- `AbstractProjector` + `Ep133Projector` wrapping song-export; byte-identity acceptance gate.
- `scene_model` schema + serialize (Project / Song / SceneSpec / GroupSpec / PadSpec / ClipRef).
- `Ep133Projector.project_from_spec` + byte-identity test.
- `export-song --write-spec` flag for ProjectSpec dump.
- JS reader emits `songs[]` wrapper + Python shape detector.
- `--then-curate` flag + re-anchor flow.
- COMMIT now walks arrangement view (closes the session_tracks gap).

#### Repo, DX & docs
- Top-level README augmented with elevator pitch, 3-zone architecture, pipeline catalog, EP-133 workflow section, pointers.
- New guides: `docs/guides/ep133-workflow.md`, `docs/guides/cli-reference.md`.
- Mermaid architecture + EP-133 flow diagrams.
- Configurator docs rehomed under `docs/configurator/{research,archive}/`.
- `.local/mus/{mus_tree,mus_events,mus_setup}` split out of monolithic `DUMP` + `tools/refresh_mus_dump.sh`.
- `.pre-commit-config.yaml` with `ruff format --check` gate.
- JS-mock suite auto-discovery in `test_js_bridge.py` — 3 → 8 wired files, 48 → 116 individual cases.
- Phase 2 root-level inventory at `docs/cleanup/2026-05-12_root_inventory.md`.

### Changed

- Backends: dropped LALAL.AI and Music.AI; Demucs is the only stem backend on main (Modal cloud backend preserved on `experimental/cloud-compute`).
- M4L loader: dropped legacy v1/v2 paths — production-mode is the only supported layout.
- `pyproject.toml`: setuptools find scope tightened from `tools*` → `tools`.
- `stemforge curate` uses `stems.json` tempo instead of re-detecting BPM/downbeat.
- `--pipeline` implies `layout_mode=production` when injecting `processing_config`.

### Fixed

- canonical_tempos full-suite torch-double-init flake — tests now run `stemforge split` in a subprocess for guaranteed isolation (PR #70).
- Bounce stub race — atomic rename via `<manifest>.tmp` → final.
- `_getLomString` returned the string `"undefined"` for missing LOM props; now returns `""`.
- `clip.call("crop")` renders at `warp_bpm`, not session BPM — pipeline captures per-clip `warp_bpm` pre-crop and tags WAV TNGE + pad-record bytes 12–15.
- M4L file reader: chunked `readstring`/`writestring` at signed-short cap (32767).
- M4L file reader: robust single-read fast path + position-guarded loop.
- `prechop` `musical_bar_1_chunk_index` is 0-indexed (was 1-indexed).
- `prechop` silence-pads pre-source region; restores `pad_pre_bars=1` default.
- `prechop` always emits leading partial chunk by default.
- Clip-export: wrap-around source when `loop_end` exceeds source length; bpm-derived seconds_per_beat; rotate bounce to `start_marker`.
- EP-133 song-export: post-merge integration of tracks A+C; full byte-level rewrite; soft-skip slots whose WAVs are missing on disk; silent groups reference empty pattern, not 0; prefer `loop_start/end_sec` over `clip_length_sec`.
- M4L: arrangement-view loader honors padded chunks + correct LOM units.
- M4L: warp markers via `move_warp_marker` + beats-unit for clip bounds; drop write to read-only `Clip.length`; clip start at `raw_start`, clear auto-warp before setting markers.
- M4L: shift right-column button stack up 20px so LOAD/ANCH clears chrome.
- Curation: normalize stem shape + defer torch import in `drum_separator`.
- EP-133: revert integer wire encoding — device accepts strings only; `sound.playmode` uses integer wire encoding only on the specific field where the device demands it.
- M4L: unwrap Max named-dict root envelope in loader.

### Removed

- `EP133_DEBRIEF.md` from repo root (superseded by `docs/sessions/2026-05-12_breaks_n_beats_complete.md`).
- Stale 28-day-old `.claude/sessions/` files.
- 18 empty orphan worktree shells from prior multi-agent sessions.
- `STEMFORGE_CONFIGURATOR_SPEC_v{2,3}.md` from root (archived to `docs/configurator/archive/`; superseded by v4).

### Hardware validation

End-to-end pipeline validated on EP-133 K.O. II hardware 2026-05-12 with `breaks-n-beats1.ppak` (46 pads across A=12 / B=12 / C=10 / D=12 with hold-to-play drum profile). One hour of live play, no issues.

## [v0.0.2-beta] — earlier

See git tag `v0.0.2-beta`.

## [v0.0.1-beta] — earlier

See git tag `v0.0.1-beta`.
