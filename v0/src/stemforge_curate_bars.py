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

from stemforge.slicer import detect_bpm_and_beats, slice_at_bars
from stemforge.curator import curate


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
) -> Path:
    """Run bar slicing + curation on stems in stems_dir.

    Returns path to the curated manifest.
    """
    stems_dir = Path(stems_dir)
    stems = find_stems(stems_dir)

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
    stem_bar_dirs: dict[str, Path] = {}
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

    # Step 3: Curate from drums (or first available stem)
    curation_source = "drums" if "drums" in stem_bar_dirs else next(iter(stem_bar_dirs))
    curation_bar_dir = stem_bar_dirs[curation_source]

    if json_events:
        emit({
            "event": "progress",
            "phase": "curating",
            "pct": 55,
            "message": f"Selecting {n_bars} most diverse bars from {curation_source}",
        })

    selected_paths = curate(
        curation_bar_dir,
        n_bars=n_bars,
        strategy=strategy,
    )

    if not selected_paths:
        if json_events:
            emit({"event": "error", "phase": "curate", "message": "Curation returned no bars"})
        raise RuntimeError("Curation returned no bars")

    # Extract bar indices from selected filenames
    selected_indices = []
    for p in selected_paths:
        m = re.search(r"_bar_(\d+)\.wav$", p.name)
        if m:
            selected_indices.append(int(m.group(1)))

    if json_events:
        emit({
            "event": "progress",
            "phase": "curating",
            "pct": 70,
            "message": f"Selected {len(selected_indices)} bars, mirroring across stems",
        })

    # Step 4: Mirror selection across all stems
    curated_root = stems_dir / "curated"
    if curated_root.exists():
        shutil.rmtree(curated_root)
    curated_root.mkdir()

    curated_manifest = {
        "track": stems_dir.name,
        "source_dir": str(stems_dir),
        "strategy": strategy,
        "n_bars": n_bars,
        "bpm": bpm,
        "beat_count": len(beat_times),
        "time_signature_numerator": time_sig,
        "stems": {},
    }

    for stem_name, bar_dir in stem_bar_dirs.items():
        stem_curated_dir = curated_root / stem_name
        stem_curated_dir.mkdir()

        # Build index: bar number → path
        bar_files = sorted(bar_dir.glob(f"{stem_name}_bar_*.wav"))
        bar_index = {}
        for bf in bar_files:
            m = re.search(r"_bar_(\d+)\.wav$", bf.name)
            if m:
                bar_index[int(m.group(1))] = bf

        # Copy selected bars
        stem_bars = []
        for position, bar_idx in enumerate(selected_indices):
            src = bar_index.get(bar_idx)
            if src and src.exists():
                dst = stem_curated_dir / f"bar_{position + 1:03d}.wav"
                shutil.copy2(src, dst)
                stem_bars.append({
                    "position": position + 1,
                    "source_bar_index": bar_idx,
                    "file": str(dst),
                })

        curated_manifest["stems"][stem_name] = stem_bars

    # Write curated manifest
    manifest_path = curated_root / "manifest.json"
    manifest_path.write_text(json.dumps(curated_manifest, indent=2))

    # Also update the main stems.json if it exists
    main_manifest = stems_dir / "stems.json"
    if main_manifest.exists():
        main_data = json.loads(main_manifest.read_text())
        main_data["curated"] = {
            "manifest": str(manifest_path),
            "n_bars": n_bars,
            "strategy": strategy,
            "bars_per_stem": len(selected_indices),
        }
        main_manifest.write_text(json.dumps(main_data, indent=2))

    if json_events:
        emit({
            "event": "progress",
            "phase": "curating",
            "pct": 95,
            "message": f"Curated {len(selected_indices)} bars × {len(stems)} stems",
        })
        emit({
            "event": "curated",
            "manifest": str(manifest_path),
            "bars_per_stem": len(selected_indices),
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
    args = ap.parse_args()

    try:
        manifest = run(
            stems_dir=args.stems_dir,
            n_bars=args.n_bars,
            strategy=args.strategy,
            time_sig=args.time_sig,
            json_events=args.json_events,
        )
        if not args.json_events:
            print(f"Curated manifest: {manifest}")
    except Exception as e:
        if args.json_events:
            emit({"event": "error", "phase": "curate", "message": str(e)})
        raise


if __name__ == "__main__":
    main()
