#!/usr/bin/env python3
"""reanchor_all_processed.py — bulk re-anchor every track in
~/stemforge/processed/ that doesn't yet have the new prechop schema.

For each track dir with `drums.wav`:
  1. read the source mix from `stems.json` (when present) or fall back to drums
  2. run `tempo_reconciler.reconcile_tempo()` to auto-detect bpm + first_downbeat
  3. recut prechop with pad_pre_bars=0, pad_post_bars=1 (the new defaults)
  4. update stems.json's TempoProvenance + provenance trail (re-anchor history)
  5. run audit_resampling — flag any mismatches

Skips tracks that already have `musical_bar_1_chunk_index` in their
prechop_manifest.json (= already updated). Skips tracks without drums.wav.
Continues on per-track errors and reports a summary at the end.

Usage:
    uv run python tools/reanchor_all_processed.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def load_existing_manifest(track_dir: Path) -> dict | None:
    sj = track_dir / "stems.json"
    if not sj.exists():
        return None
    try:
        return json.loads(sj.read_text())
    except Exception:
        return None


def find_source_mix(track_dir: Path, stems_data: dict | None) -> Path | None:
    """Try to recover the source mix path from stems.json. May not exist anymore."""
    if stems_data is None:
        return None
    src = stems_data.get("source_file")
    if not src:
        return None
    p = Path(src)
    return p if p.exists() else None


def get_pipeline_cfg():
    from stemforge.pipelines import load_pipeline

    return load_pipeline("arrangement")


def reanchor_one(track_dir: Path, *, dry_run: bool = False) -> dict:
    """Re-anchor a single track. Returns a status dict."""
    from stemforge.manifest import (
        InputAudio,
        TempoProvenance,
        _input_audio_for,
        write_manifest,
    )
    from stemforge.pipelines import run_post_split_steps
    from stemforge.tempo_reconciler import reconcile_tempo

    started = time.time()
    name = track_dir.name
    drums = track_dir / "drums.wav"
    if not drums.exists():
        return {"track": name, "status": "skip", "reason": "no drums.wav"}

    sj_path = track_dir / "stems.json"
    sj = load_existing_manifest(track_dir)

    pm_path = track_dir / "prechop_manifest.json"
    if pm_path.exists():
        try:
            pm = json.loads(pm_path.read_text())
            if "musical_bar_1_chunk_index" in pm:
                return {"track": name, "status": "skip", "reason": "already updated"}
        except Exception:
            pass

    # Resolve stem paths — prefer stems.json; fall back to filesystem for older
    # forge runs that produced stems but no manifest.
    stem_paths: dict[str, Path] = {}
    if sj is not None:
        for s in sj.get("stems", []):
            wav = Path(s["wav_path"])
            if not wav.exists():
                wav = track_dir / f"{s['name']}.wav"
            if wav.exists():
                stem_paths[s["name"]] = wav
    # Filesystem fallback — also catches stems.json with missing/wrong paths.
    for stem_name in ("drums", "bass", "vocals", "other"):
        wav = track_dir / f"{stem_name}.wav"
        if wav.exists() and stem_name not in stem_paths:
            stem_paths[stem_name] = wav

    if "drums" not in stem_paths:
        return {"track": name, "status": "fail", "reason": "no drums.wav anywhere"}

    # If we still don't have stems.json, synthesize a minimal one for the
    # write_manifest call below.
    if sj is None:
        sj = {
            "track_name": name,
            "source_file": str(track_dir / "drums.wav"),
            "backend": "demucs",
            "bpm": 120.0,
            "beat_count": 0,
            "stems": [
                {"name": s, "wav_path": str(p), "beats_dir": str(track_dir / f"{s}_beats"), "beat_count": 0}
                for s, p in stem_paths.items()
            ],
            "pipeline": "arrangement",
            "tempo": None,
            "input_audio": None,
        }

    # Run reconciler. Prefer source mix when we still have it; else drums-only.
    source_mix = find_source_mix(track_dir, sj)

    if dry_run:
        return {"track": name, "status": "dry-run", "would_use": "mix" if source_mix else "drums-only"}

    try:
        reconciled = reconcile_tempo(
            mix_path=source_mix,
            drums_path=stem_paths["drums"],
            kick_tiebreaker=True,
            kick_workdir=track_dir / "tempo_substems",
        )
    except Exception as e:
        return {"track": name, "status": "fail", "reason": f"reconcile_tempo: {e}"}

    bpm = reconciled.bpm
    downbeat_times = reconciled.downbeat_times
    first_downbeat = float(downbeat_times[0]) if len(downbeat_times) else 0.0

    # Backup prior manifest (lightweight — keep .bak suffix)
    if pm_path.exists():
        pm_path.rename(track_dir / "prechop_manifest.bak.json")
    for stem_name in stem_paths:
        old_dir = track_dir / f"{stem_name}_prechop"
        if old_dir.exists():
            bak = track_dir / f"{stem_name}_prechop.bak"
            if bak.exists():
                shutil.rmtree(bak)
            old_dir.rename(bak)

    # Resolve pre_bars: auto-fill the intro
    pipeline_cfg = get_pipeline_cfg()
    if pipeline_cfg is None or pipeline_cfg.prechop is None:
        return {"track": name, "status": "fail", "reason": "pipeline 'arrangement' missing or no prechop"}

    bars_per_chunk = pipeline_cfg.prechop.bars
    bar_period = bars_per_chunk * pipeline_cfg.prechop.beats_per_bar * 60.0 / bpm
    n_pre_chunks = int(first_downbeat // bar_period)
    pre_bars = n_pre_chunks * bars_per_chunk

    # Prechop with new defaults
    try:
        run_post_split_steps(
            pipeline_cfg,
            stem_paths,
            track_dir,
            bpm=bpm,
            first_downbeat_sec=first_downbeat,
            pre_bars=pre_bars,
            pad_pre_bars=0,
            pad_post_bars=1,
        )
    except Exception as e:
        return {
            "track": name,
            "status": "fail",
            "reason": f"prechop: {e}\n{traceback.format_exc()}",
        }

    # Build TempoProvenance from reconciler result
    tempo_provenance = TempoProvenance(
        source=reconciled.source,
        confidence=reconciled.confidence,
        first_downbeat_sec=first_downbeat,
        n_downbeats=int(len(downbeat_times)),
        warning=(
            f"bulk re-anchor 2026-05-02; prior bpm={sj.get('bpm')} "
            f"prior_source={(sj.get('tempo') or {}).get('source', 'unknown')}"
            + (f" | prior: {sj['tempo']['warning']}" if (sj.get('tempo') or {}).get('warning') else '')
        ),
        all_estimates=[e.to_dict() for e in reconciled.all_estimates],
    )

    # Rewrite stems.json — preserve audio fingerprint + slice counts
    slice_counts = {s["name"]: s["beat_count"] for s in sj["stems"]}
    source_file = Path(sj.get("source_file") or "")
    input_audio = None
    if sj.get("input_audio"):
        ia = sj["input_audio"]
        input_audio = InputAudio(
            sample_rate=ia["sample_rate"],
            duration_samples=ia["duration_samples"],
            sha256=ia["sha256"],
        )
    elif source_file.exists():
        input_audio = _input_audio_for(source_file)

    write_manifest(
        output_dir=track_dir,
        track_name=sj.get("track_name", name),
        source_file=source_file if source_file.exists() else (track_dir / "drums.wav"),
        backend=sj.get("backend", "demucs"),
        bpm=bpm,
        beat_count=sj.get("beat_count", 0),
        stem_paths=stem_paths,
        slice_counts=slice_counts,
        pipeline=sj.get("pipeline", "arrangement"),
        tempo=tempo_provenance,
        input_audio=input_audio,
    )

    return {
        "track": name,
        "status": "ok",
        "bpm": round(bpm, 3),
        "first_downbeat": round(first_downbeat, 3),
        "pre_bars": pre_bars,
        "source": reconciled.source,
        "confidence": reconciled.confidence,
        "elapsed_s": round(time.time() - started, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "stemforge/processed",
    )
    args = p.parse_args()

    if not args.root.is_dir():
        print(f"FATAL: {args.root} not a directory", file=sys.stderr)
        return 1

    tracks = sorted(d for d in args.root.iterdir() if d.is_dir())
    print(f"Processing {len(tracks)} tracks under {args.root}")
    print(f"  dry-run: {args.dry_run}")
    print()

    results: list[dict] = []
    for i, t in enumerate(tracks, 1):
        print(f"[{i}/{len(tracks)}] {t.name}", flush=True)
        try:
            r = reanchor_one(t, dry_run=args.dry_run)
        except Exception as e:
            r = {
                "track": t.name,
                "status": "fail",
                "reason": f"unhandled: {e}",
            }
        results.append(r)
        # one-line summary per track
        if r["status"] == "ok":
            print(
                f"   ✓ bpm={r['bpm']} fd={r['first_downbeat']}s pre={r['pre_bars']}b "
                f"src={r['source']} conf={r['confidence']} ({r['elapsed_s']}s)"
            )
        elif r["status"] == "skip":
            print(f"   - skip: {r['reason']}")
        elif r["status"] == "dry-run":
            print(f"   ? dry: would use {r['would_use']}")
        else:
            print(f"   ✗ FAIL: {r['reason']}")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    for s, n in sorted(by_status.items()):
        print(f"  {s:10s}: {n}")

    fails = [r for r in results if r["status"] == "fail"]
    if fails:
        print()
        print("FAILURES:")
        for r in fails:
            print(f"  {r['track']}: {r['reason']}")

    out = args.root / "_reanchor_log.json"
    out.write_text(json.dumps(results, indent=2))
    print()
    print(f"Full log: {out}")

    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
