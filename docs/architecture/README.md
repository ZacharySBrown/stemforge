# StemForge architecture diagrams

Visual overview of the full StemForge pipeline — every model, every config knob, every audio granularity, the Ableton landing surface, and the export targets. Style adapted from `ep133-ppak/docs/diagrams` (lowercase, sans-serif Inter + IBM Plex Mono mono, palette `#fafaf7 / #1a1a1a / #3a85ff / #e85d3a / #3aaa6e`, 8px grid). See [STYLE.md](diagrams/STYLE.md).

## Diagrams

| # | Title | Status |
|---|---|---|
| [00](diagrams/00_system_overview.md) | system overview — full pipeline hero | ✓ shipped |
| [01](diagrams/01_audio_granularity.md) | audio granularity matrix — every unit StemForge operates on | ✓ shipped |
| [02](diagrams/02_tempo_detection_lineage.md) | tempo / BPM detection lineage | ✓ shipped |
| [03](diagrams/03_first_downbeat_lineage.md) | first-downbeat detection lineage + override loop | ✓ shipped |
| [04](diagrams/04_m4l_surface.md) | Max-for-Live integration surface | ✓ shipped |
| 05 | arrangement-load invariants (zoom-in on the loader) | TODO |
| [06](diagrams/06_export_targets.md) | export-target fan-out from manifests to devices | ✓ shipped (svg + md) |
| 07 | device × flavor matrix (3×4 grid: ep133, spdsx, koala × a/b/c/d) | TODO |
| [08](diagrams/08_pipeline_configs.md) | pipeline config layers + resolution order | ✓ shipped (svg + md) |
| 09 | integrated test plan (synth fixture spine + 5 phases) | TODO |

## Background — what was built

This documentation was generated as the closing artifact of a multi-day debug session that:

1. Diagnosed why librosa beat detection fails on half-time hip-hop (Black Star "Definition" detected as 120 BPM vs true 90)
2. Built a multi-source tempo reconciler combining beat-this neural detection, librosa fallback, bar-period BPM derivation, and LarsNet kick-isolation tiebreaker
3. Added `--bpm`, `--first-downbeat`, `--refine-downbeat` overrides on `stemforge split` for tracks where auto-detection isn't precise
4. Added the `stemforge re-anchor` subcommand for sub-2-second iteration without re-running Demucs
5. Split symmetric `pad_bars` into `pad_pre_bars` and `pad_post_bars` (default `pad_pre_bars=0` — chunk WAV frame 0 is bar 1, eliminates Ableton start_marker snap-to-grid issues)
6. Added `pre_bars` for including intro material as additional chunks on the same bar grid
7. Validated end-to-end on three test tracks: Black Star "Definition" (89.88 BPM, anchored on main beat at 12.28s), Greg Nice "Ooh La La" (85.11 BPM, anchored on snare at 22.59s), Imagine Dragons "Believer" (125.00 BPM, anchored on attack onset at 0.282s).

These diagrams are the **first step toward a fully automated test suite** per the request — the integrated test plan diagram (09) will wire the pieces together.

## Read order

For a new contributor: 00 → 01 → 02 → 03 → 04 → 08. The export pipeline (06, 07) is downstream and can be skimmed unless you're working on hardware integration. The arrangement-load deep-dive (05) is most useful when debugging M4L behavior. The integrated test plan (09) is the operational picture once it lands.
