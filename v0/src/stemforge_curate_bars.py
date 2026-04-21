#!/usr/bin/env python3
"""stemforge_curate_bars.py — Bar-slice + diversity-curate stems from a split session.

Takes the output of `stemforge-native split` (4 stem WAVs in a directory)
and runs bar-level slicing + greedy diversity curation to produce N curated
bars per stem. Emits NDJSON events on stdout for M4L device integration.

Usage:
    uv run python v0/src/stemforge_curate_bars.py \
        --stems-dir ~/stemforge/processed/the_champ_30s \
        --n-bars 16 \
        --strategy max-diversity \
        --json-events

Input:  directory with drums.wav, bass.wav, vocals.wav, other.wav
Output: curated/ subdirectory with N bars per stem + updated stems.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# Add repo root to path so we can import stemforge modules
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from stemforge.slicer import detect_bpm_and_beats, slice_at_bars, group_bars_into_phrases
from stemforge.curator import curate, section_stratified_select
from stemforge.config import load_curation_config, CurationConfig
from stemforge.oneshot import extract_oneshots, extract_kicks_from_bass, select_diverse_oneshots, extract_drum_oneshots_via_larsnet
from stemforge.drum_classifier import classify_and_assign, arrange_drum_pads
from stemforge.layout import build_stems_layout, layout_to_manifest


STEM_NAMES = ["drums", "bass", "vocals", "other"]


def emit(event: dict) -> None:
    """Emit an NDJSON event to stdout."""
    print(json.dumps(event), flush=True)


def find_stems(stems_dir: Path) -> dict[str, Path]:
    """Find stem WAVs in the directory."""
    stems = {}
    for name in STEM_NAMES:
        p = stems_dir / f"{name}.wav"
        if p.exists():
            stems[name] = p
    return stems


def run(
    stems_dir: Path,
    n_bars: int = 16,
    strategy: str = "max-diversity",
    time_sig: int = 4,
    json_events: bool = True,
    curation_config: CurationConfig | None = None,
    pipeline: Path | None = None,
) -> Path:
    """Run bar slicing + curation on stems in stems_dir.

    When curation_config is provided, per-stem phrase_bars and distance_weights
    are used. Otherwise falls back to single-bar curation.

    Returns path to the curated manifest.
    """
    stems_dir = Path(stems_dir)
    stems = find_stems(stems_dir)
    if curation_config is None:
        curation_config = CurationConfig()

    layout_mode = curation_config.layout.mode
    is_loops_only = layout_mode == "loops-only"
    is_production = layout_mode == "production"

    if is_loops_only and json_events:
        emit({"event": "progress", "phase": "config", "pct": 0,
              "message": "loops-only mode: 16 bar loops per stem, no one-shots"})
    if is_production and json_events:
        emit({"event": "progress", "phase": "config", "pct": 0,
              "message": "production mode: 16 loops per stem + drum one-shots"})

    if not stems:
        if json_events:
            emit({"event": "error", "phase": "curate", "message": f"No stems found in {stems_dir}"})
        raise FileNotFoundError(f"No stems found in {stems_dir}")

    if json_events:
        emit({
            "event": "progress",
            "phase": "slicing",
            "pct": 0,
            "message": f"Slicing {len(stems)} stems into bars (time sig: {time_sig}/4)",
        })

    # Step 1: Detect BPM from drums (best rhythmic source)
    bpm_source = stems.get("drums", next(iter(stems.values())))
    bpm, beat_times = detect_bpm_and_beats(bpm_source)

    if json_events:
        emit({"event": "bpm", "bpm": bpm, "beat_count": len(beat_times)})

    # Step 2: Slice each stem into bars
    # Clean existing bar dirs first to avoid stale files from previous runs
    stem_bar_dirs: dict[str, Path] = {}
    for stem_name in stems:
        bar_dir = stems_dir / f"{stem_name}_bars"
        if bar_dir.exists():
            shutil.rmtree(bar_dir)

    for i, (stem_name, stem_path) in enumerate(stems.items()):
        bar_paths = slice_at_bars(
            stem_path=stem_path,
            output_dir=stems_dir,
            stem_name=stem_name,
            time_sig_numerator=time_sig,
            beat_times=beat_times,
        )
        # slice_at_bars creates {stem_name}_bars/ inside output_dir
        bar_dir = stems_dir / f"{stem_name}_bars"
        stem_bar_dirs[stem_name] = bar_dir

        pct = int(((i + 1) / len(stems)) * 50)  # slicing = 0-50%
        if json_events:
            emit({
                "event": "progress",
                "phase": "slicing",
                "pct": pct,
                "message": f"{stem_name}: {len(bar_paths)} bars",
            })

    # Step 3: Per-stem phrase grouping + curation
    # Each stem gets its own phrase_bars and strategy from the config.
    # When all stems use phrase_bars=1 and the same strategy, we mirror
    # bar indices (v0 behavior). Otherwise, each stem is curated independently.
    curated_root = stems_dir / "curated"
    if curated_root.exists():
        shutil.rmtree(curated_root)
    curated_root.mkdir()

    # Check if all stems share the same phrase_bars — enables mirroring
    stem_configs = {s: curation_config.for_stem(s) for s in stems}

    # In loops-only and production modes, override loop/oneshot counts
    if is_loops_only or is_production:
        from stemforge.config import StemCurationConfig
        for s in stem_configs:
            sc = stem_configs[s]
            # Production mode: 16 loops for all stems, plus 8 drum one-shots
            # Loops-only: 16 loops, 0 one-shots for all stems
            os_count = 8 if (is_production and s == "drums") else 0
            os_mode = "classify" if s == "drums" else "diverse"
            stem_configs[s] = StemCurationConfig(
                phrase_bars=sc.phrase_bars,
                loop_count=16,
                oneshot_count=os_count,
                strategy=sc.strategy,
                oneshot_mode=os_mode,
                chromatic=False,
                midi_extract=False,
                rms_floor=sc.rms_floor,
                crest_min=sc.crest_min,
                distance_weights=sc.distance_weights,
                processing=sc.processing,
            )
    phrase_bars_set = {sc.phrase_bars for sc in stem_configs.values()}
    # In loops-only mode, always use per-stem curation — mirroring from drums
    # causes silent bars in non-drum stems (e.g. vocal bars from instrumental sections).
    all_same_phrase = (
        len(phrase_bars_set) == 1
        and next(iter(phrase_bars_set)) == 1
        and not is_loops_only
    )

    curated_manifest = {
        "version": 2,
        "track": stems_dir.name,
        "source_dir": str(stems_dir),
        "strategy": strategy,
        "n_bars": n_bars,
        "bpm": bpm,
        "beat_count": len(beat_times),
        "time_signature_numerator": time_sig,
        "layout_mode": curation_config.layout.mode,
        "stems": {},
    }

    if all_same_phrase:
        # ── Mirror mode (v0 behavior): curate from drums, mirror indices ──
        per_stem_indices: dict[str, set[int]] = {}
        for stem_name, bar_dir in stem_bar_dirs.items():
            indices = set()
            for bf in bar_dir.glob(f"{stem_name}_bar_*.wav"):
                m = re.search(r"_bar_(\d+)\.wav$", bf.name)
                if m:
                    indices.add(int(m.group(1)))
            per_stem_indices[stem_name] = indices

        common_indices = set.intersection(*per_stem_indices.values()) if per_stem_indices else set()
        curation_source = "drums" if "drums" in stem_bar_dirs else next(iter(stem_bar_dirs))
        curation_bar_dir = stem_bar_dirs[curation_source]
        sc = stem_configs[curation_source]

        # Build temp pool with only common-range bars
        import tempfile
        curation_pool = Path(tempfile.mkdtemp(prefix="sf_curate_"))
        common_bar_paths = []
        for bf in sorted(curation_bar_dir.glob(f"{curation_source}_bar_*.wav")):
            m = re.search(r"_bar_(\d+)\.wav$", bf.name)
            if m and int(m.group(1)) in common_indices:
                dst = curation_pool / bf.name
                shutil.copy2(bf, dst)
                common_bar_paths.append(dst)

        if json_events:
            emit({
                "event": "progress",
                "phase": "curating",
                "pct": 55,
                "message": f"Selecting {n_bars} from {curation_source} ({len(common_bar_paths)} mirrorable)",
            })

        selected_paths = curate(
            curation_pool, n_bars=n_bars, strategy=sc.strategy,
            rms_floor=sc.rms_floor, crest_min=sc.crest_min,
            content_density_min=sc.content_density_min,
            distance_weights=sc.distance_weights,
        )
        shutil.rmtree(curation_pool, ignore_errors=True)

        if not selected_paths:
            if json_events:
                emit({"event": "error", "phase": "curate", "message": "Curation returned no bars"})
            raise RuntimeError("Curation returned no bars")

        selected_indices = []
        for p in selected_paths:
            m = re.search(r"_bar_(\d+)\.wav$", p.name)
            if m:
                selected_indices.append(int(m.group(1)))

        if json_events:
            emit({
                "event": "progress", "phase": "curating", "pct": 70,
                "message": f"Selected {len(selected_indices)} bars, mirroring across stems",
            })

        # Mirror across all stems
        for stem_name, bar_dir in stem_bar_dirs.items():
            stem_curated_dir = curated_root / stem_name
            stem_curated_dir.mkdir()

            bar_files = sorted(bar_dir.glob(f"{stem_name}_bar_*.wav"))
            bar_index = {}
            for bf in bar_files:
                m = re.search(r"_bar_(\d+)\.wav$", bf.name)
                if m:
                    bar_index[int(m.group(1))] = bf

            stem_bars = []
            for position, bar_idx in enumerate(selected_indices):
                src = bar_index.get(bar_idx)
                if src and src.exists():
                    dst = stem_curated_dir / f"bar_{position + 1:03d}.wav"
                    shutil.copy2(src, dst)
                    stem_bars.append({
                        "position": position + 1,
                        "source_bar_index": bar_idx,
                        "phrase_bars": 1,
                        "file": str(dst),
                    })
            curated_manifest["stems"][stem_name] = stem_bars

    else:
        # ── Per-stem mode: each stem curated independently with its own phrase_bars ──
        for si, (stem_name, bar_dir) in enumerate(stem_bar_dirs.items()):
            sc = stem_configs[stem_name]
            stem_curated_dir = curated_root / stem_name
            stem_curated_dir.mkdir()

            # Group bars into phrases if phrase_bars > 1
            if sc.phrase_bars > 1:
                phrase_dir = stems_dir / f"{stem_name}_phrases"
                if phrase_dir.exists():
                    shutil.rmtree(phrase_dir)
                phrase_paths = group_bars_into_phrases(
                    bar_dir, stem_name, sc.phrase_bars, output_dir=stems_dir,
                )
                curation_dir = phrase_dir
                file_pattern = f"{stem_name}_phrase_*.wav"
                item_label = f"{sc.phrase_bars}-bar phrase"
            else:
                curation_dir = bar_dir
                file_pattern = f"{stem_name}_bar_*.wav"
                item_label = "bar"

            n_available = len(list(curation_dir.glob(file_pattern)))

            if json_events:
                emit({
                    "event": "progress",
                    "phase": "curating",
                    "pct": 55 + int((si / len(stem_bar_dirs)) * 35),
                    "message": f"{stem_name}: selecting {sc.loop_count} {item_label}s from {n_available}",
                })

            # Use section-stratified selection for melodic mode when structure is available
            song_structure = None
            if sc.bottom_mode == "melodic" and sc.midi_extract:
                # Detect song structure for section-aware loop selection
                try:
                    from stemforge.segmenter import detect_song_structure
                    song_structure = detect_song_structure(
                        stems.get(stem_name, next(iter(stems.values()))),
                        beat_times=beat_times, bpm=bpm, time_sig=time_sig,
                    )
                    if json_events and song_structure.boundaries_bars:
                        emit({
                            "event": "progress",
                            "phase": "curating",
                            "pct": 55 + int((si / len(stem_bar_dirs)) * 35),
                            "message": f"{stem_name}: form={song_structure.form}, selecting across sections",
                        })
                except Exception:
                    pass  # fall back to regular curation

            if song_structure and song_structure.boundaries_bars:
                selected = section_stratified_select(
                    curation_dir,
                    n_bars=sc.loop_count,
                    song_structure=song_structure,
                    rms_floor=sc.rms_floor,
                    crest_min=sc.crest_min,
                    content_density_min=sc.content_density_min,
                    distance_weights=sc.distance_weights,
                )
            else:
                selected = curate(
                    curation_dir,
                    n_bars=sc.loop_count,
                    strategy=sc.strategy,
                    rms_floor=sc.rms_floor,
                    crest_min=sc.crest_min,
                    content_density_min=sc.content_density_min,
                    distance_weights=sc.distance_weights,
                )

            stem_bars = []
            for position, src in enumerate(selected):
                dst = stem_curated_dir / f"bar_{position + 1:03d}.wav"
                shutil.copy2(src, dst)
                stem_bars.append({
                    "position": position + 1,
                    "phrase_bars": sc.phrase_bars,
                    "file": str(dst),
                })

            curated_manifest["stems"][stem_name] = stem_bars

    # Step 5: Extract one-shots per stem (if configured)
    # loops-only: skip all one-shots
    # production: only extract drum one-shots
    if is_loops_only and json_events:
        emit({"event": "progress", "phase": "oneshots", "pct": 80,
              "message": "loops-only mode: skipping one-shot extraction"})

    for stem_name, stem_path in stems.items():
        if is_loops_only:
            continue
        if is_production and stem_name != "drums":
            continue  # production mode: only drum one-shots
        sc = stem_configs[stem_name]
        if sc.oneshot_count <= 0:
            continue

        if json_events:
            emit({
                "event": "progress",
                "phase": "oneshots",
                "pct": 80,
                "message": f"{stem_name}: extracting one-shots",
            })

        # Extract one-shots — try LarsNet first for drums (clean sub-stem separation)
        os_profiles = []
        if stem_name == "drums":
            from stemforge.drum_separator import is_available as _larsnet_ok
            if _larsnet_ok():
                if json_events:
                    emit({"event": "progress", "phase": "oneshots", "pct": 81,
                          "message": "drums: using LarsNet sub-stem separation (kick/snare/hihat/toms/cymbals)"})
                os_profiles = extract_drum_oneshots_via_larsnet(
                    stem_path, curated_root, config=sc)

        if not os_profiles:
            # Fallback: spectral heuristic extraction
            os_profiles = extract_oneshots(stem_path, curated_root, stem_name, config=sc)

            # For drums: also extract kicks from bass stem (htdemucs bleed)
            if stem_name == "drums" and "bass" in stems:
                kicks = extract_kicks_from_bass(stems["bass"], curated_root, config=sc)
                os_profiles.extend(kicks)

            # Classify drum hits via spectral heuristics
            if stem_name == "drums" and sc.oneshot_mode == "classify":
                classify_and_assign(os_profiles)

        # Select diverse subset
        selected_os = select_diverse_oneshots(os_profiles, n=sc.oneshot_count)

        # For drums, reclassify after diversity selection and arrange into pad layout
        if stem_name == "drums" and sc.oneshot_mode == "classify":
            classify_and_assign(selected_os)
            pads = arrange_drum_pads(selected_os, n_pads=sc.oneshot_count)
            selected_os = [p for p in pads if p is not None]

        # Copy selected one-shots to curated dir
        stem_os_dir = curated_root / stem_name / "oneshots"
        stem_os_dir.mkdir(parents=True, exist_ok=True)

        oneshot_entries = []
        for oi, profile in enumerate(selected_os):
            if profile is None or profile.path is None:
                continue
            dst = stem_os_dir / f"os_{oi + 1:03d}.wav"
            shutil.copy2(profile.path, dst)
            oneshot_entries.append({
                "position": oi + 1,
                "file": str(dst),
                "classification": profile.classification,
                "spectral": {
                    "centroid_hz": round(profile.spectral_centroid, 1),
                    "brightness": round(min(profile.spectral_centroid / 10000, 1.0), 3),
                },
                "duration_ms": round(profile.duration * 1000, 1),
                "rms": round(profile.rms, 4),
                "crest_factor": round(profile.crest_factor, 2),
            })

        # Upgrade manifest stem entry to v2 format (loops + oneshots)
        existing = curated_manifest["stems"].get(stem_name, [])
        if isinstance(existing, list):
            curated_manifest["stems"][stem_name] = {
                "loops": existing,
                "oneshots": oneshot_entries,
            }
        elif isinstance(existing, dict):
            existing["oneshots"] = oneshot_entries

        if json_events:
            emit({
                "event": "progress",
                "phase": "oneshots",
                "pct": 85,
                "message": f"{stem_name}: {len(oneshot_entries)} one-shots selected",
            })

    # Embed processing config (pipeline targets) into manifest for M4L loader
    if pipeline and pipeline.exists():
        import yaml
        pipeline_data = yaml.safe_load(pipeline.read_text())
        if "stems" in pipeline_data:
            curated_manifest["processing_config"] = pipeline_data["stems"]
    elif pipeline and not pipeline.exists():
        # Try JSON variant (compiled from YAML)
        json_pipeline = pipeline.with_suffix(".json")
        if json_pipeline.exists():
            pipeline_data = json.loads(json_pipeline.read_text())
            if "stems" in pipeline_data:
                curated_manifest["processing_config"] = pipeline_data["stems"]

    # Write curated manifest
    manifest_path = curated_root / "manifest.json"
    manifest_path.write_text(json.dumps(curated_manifest, indent=2))

    # Also update the main stems.json if it exists
    main_manifest = stems_dir / "stems.json"
    if main_manifest.exists():
        main_data = json.loads(main_manifest.read_text())
        # Count items per stem from the manifest we just built
        bars_per_stem = max(
            (len(v) for v in curated_manifest["stems"].values()), default=0
        )
        main_data["curated"] = {
            "manifest": str(manifest_path),
            "n_bars": n_bars,
            "strategy": strategy,
            "bars_per_stem": bars_per_stem,
        }
        main_manifest.write_text(json.dumps(main_data, indent=2))

    # Summary counts from manifest (handles both v1 list and v2 dict formats)
    def _count_items(v):
        if isinstance(v, list):
            return len(v)
        if isinstance(v, dict):
            return len(v.get("loops", [])) + len(v.get("oneshots", []))
        return 0

    total_items = sum(_count_items(v) for v in curated_manifest["stems"].values())
    items_per_stem = {k: _count_items(v) for k, v in curated_manifest["stems"].items()}

    if json_events:
        emit({
            "event": "progress",
            "phase": "curating",
            "pct": 95,
            "message": f"Curated {total_items} items across {len(stems)} stems",
        })
        emit({
            "event": "curated",
            "manifest": str(manifest_path),
            "items_per_stem": items_per_stem,
            "stems": list(stems.keys()),
            "bpm": bpm,
        })

    return manifest_path


def main():
    ap = argparse.ArgumentParser(description="Bar-slice + curate stems from a split session")
    ap.add_argument("--stems-dir", required=True, type=Path,
                    help="Directory containing drums.wav, bass.wav, etc.")
    ap.add_argument("--n-bars", type=int, default=16,
                    help="Number of bars to select per stem (default: 16)")
    ap.add_argument("--strategy", default="max-diversity",
                    choices=["max-diversity", "rhythm-taxonomy", "sectional"])
    ap.add_argument("--time-sig", type=int, default=4,
                    help="Time signature numerator (default: 4)")
    ap.add_argument("--json-events", action="store_true",
                    help="Emit NDJSON events on stdout")
    ap.add_argument("--curation", type=Path, default=None,
                    help="Curation config YAML (default: pipelines/curation.yaml)")
    ap.add_argument("--pipeline", type=Path, default=None,
                    help="Processing pipeline YAML to embed in manifest (e.g. pipelines/production_idm.yaml)")
    args = ap.parse_args()

    curation_cfg = load_curation_config(args.curation) if args.curation else None

    try:
        manifest = run(
            stems_dir=args.stems_dir,
            n_bars=args.n_bars,
            strategy=args.strategy,
            time_sig=args.time_sig,
            json_events=args.json_events,
            curation_config=curation_cfg,
            pipeline=args.pipeline,
        )
        if not args.json_events:
            print(f"Curated manifest: {manifest}")
    except Exception as e:
        if args.json_events:
            emit({"event": "error", "phase": "curate", "message": str(e)})
        raise


if __name__ == "__main__":
    main()
