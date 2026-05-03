# StemForge architecture diagrams

Visual overview of the full StemForge pipeline — every model, every config knob, every audio granularity, the Ableton landing surface, and the export targets. Style adapted from `ep133-ppak/docs/diagrams` (lowercase, sans-serif Inter + IBM Plex Mono mono, palette `#fafaf7 / #1a1a1a / #3a85ff / #e85d3a / #3aaa6e`, 8px grid, SVG with `viewBox` only — no width/height). See [STYLE.md](diagrams/STYLE.md).

## Diagrams

| # | Title | Coverage |
|---|---|---|
| [00](diagrams/00_system_overview.md) | system overview — full pipeline hero | demucs → stems → slice/chunk/oneshot/curate → manifests → exports |
| [01](diagrams/01_audio_granularity.md) | audio granularity matrix | full mix → stems → sub-stems → bars → beats → chunks → loops → one-shots |
| [02](diagrams/02_tempo_detection_lineage.md) | tempo / BPM detection lineage | librosa, beat-this, bar-period, factor-ratio reconciliation, kick tiebreaker, override |
| [03](diagrams/03_first_downbeat_lineage.md) | first-downbeat detection lineage + override loop | beat-this, mode-walk, find_best_downbeat_offset, refine_downbeat, probe_loop + re-anchor |
| [04](diagrams/04_m4l_surface.md) | Max-for-Live integration surface | 5 js modules → LOM mutations, sf_settings dict, warp/stem invariants |
| [05](diagrams/05_arrangement_load_invariants.md) | arrangement-load invariants | step-by-step `sf_arrangement_loader.js` + LOM gotchas, recovery procedure |
| [06](diagrams/06_export_targets.md) | export-target fan-out from manifests to devices | shipped (ep-133) vs scaffold (spdsx, koala), AbstractExporter blocking item |
| [07](diagrams/07_device_matrix.md) | device × export-flavor matrix | 3×4 status grid + planned `DeviceProfile` dataclass |
| [08](diagrams/08_pipeline_configs.md) | pipeline config layers + resolution order | yaml → curation → cli flags, recently-added tempo flags highlighted |
| [09](diagrams/09_test_plan_integrated.md) | integrated test plan visualization | synth fixture spine + 5 phases, tier targets, what's shipped vs planned |

All 10 SVGs parse as valid XML. All have paired narrative `.md` files. GitHub renders the SVGs inline — open any of the `.md` files for the embedded image plus prose.

## Background — what was built

This documentation was generated as the closing artifact of a multi-day debug session that:

1. Diagnosed why librosa beat detection fails on half-time hip-hop (Black Star "Definition" detected as 120 BPM vs true 90)
2. Built a multi-source tempo reconciler combining beat-this neural detection, librosa fallback, bar-period BPM derivation, and LarsNet kick-isolation tiebreaker
3. Added `--bpm`, `--first-downbeat`, `--refine-downbeat` overrides on `stemforge split` for tracks where auto-detection isn't precise
4. Added the `stemforge re-anchor` subcommand for sub-2-second iteration without re-running Demucs
5. Split symmetric `pad_bars` into `pad_pre_bars` and `pad_post_bars` (default `pad_pre_bars=0` — chunk WAV frame 0 is bar 1, eliminates Ableton start_marker snap-to-grid issues)
6. Added `pre_bars` for including intro material as additional chunks on the same bar grid
7. Validated end-to-end on three test tracks: Black Star "Definition" (89.88 BPM, anchored on main beat at 12.28s), Greg Nice "Ooh La La" (85.11 BPM, anchored on snare at 22.59s), Imagine Dragons "Believer" (125.00 BPM, anchored on attack onset at 0.282s).

These diagrams are the **first step toward a fully automated test suite** — see [09](diagrams/09_test_plan_integrated.md) for the integrated test plan that will wire the pieces together.

## Read order

For a new contributor:

1. **[00](diagrams/00_system_overview.md)** for the 30-second overview — what the whole pipeline does
2. **[01](diagrams/01_audio_granularity.md)** for the audio-data hierarchy — what units everything operates on
3. **[02](diagrams/02_tempo_detection_lineage.md)** + **[03](diagrams/03_first_downbeat_lineage.md)** for the tempo + downbeat detection (the closing-session work)
4. **[04](diagrams/04_m4l_surface.md)** + **[05](diagrams/05_arrangement_load_invariants.md)** for Ableton integration (essential when debugging M4L)
5. **[06](diagrams/06_export_targets.md)** + **[07](diagrams/07_device_matrix.md)** for hardware export (skip unless touching exporters)
6. **[08](diagrams/08_pipeline_configs.md)** for the config knobs across pipelines/curation/CLI
7. **[09](diagrams/09_test_plan_integrated.md)** last — operational view of testing strategy
