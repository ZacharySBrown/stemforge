#!/usr/bin/env python3
"""export_koala_all.py — bulk Koala export across all processed tracks
that have a `curated/manifest.json`.

For each track:
  1. checks for curated/manifest.json
  2. runs export_koala() with default config (4 loops/stem in bank 1,
     auto-fill oneshots in bank 2)
  3. drops the .zip into ~/stemforge/koala_exports/

Skips tracks without curated/. Continues on per-track errors.

Usage:
    uv run python tools/export_koala_all.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "stemforge/processed",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "stemforge/koala_exports",
    )
    p.add_argument("--loops-per-stem", type=int, default=4)
    p.add_argument("--oneshots-per-part", type=int, default=None)
    args = p.parse_args()

    from stemforge.exporters.koala import KoalaExportConfig, export_koala

    if not args.root.is_dir():
        print(f"FATAL: {args.root} not a directory", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)

    tracks = sorted(d for d in args.root.iterdir() if d.is_dir())
    eligible = [t for t in tracks if (t / "curated" / "manifest.json").exists()]
    print(f"Processing {len(eligible)} of {len(tracks)} tracks (have curated/manifest.json)")
    print(f"  output: {args.output_dir}")
    print()

    results: list[dict] = []
    for i, t in enumerate(eligible, 1):
        print(f"[{i}/{len(eligible)}] {t.name}", flush=True)
        started = time.time()
        try:
            config = KoalaExportConfig(
                loops_per_stem=args.loops_per_stem,
                oneshots_per_part=args.oneshots_per_part,
                output_dir=args.output_dir,
            )
            zip_path = export_koala(t / "curated", config)
            elapsed = time.time() - started
            size_mb = zip_path.stat().st_size / 1024 / 1024
            print(f"   ✓ {zip_path.name} ({size_mb:.1f} MB, {elapsed:.1f}s)")
            results.append(
                {
                    "track": t.name,
                    "status": "ok",
                    "zip": str(zip_path),
                    "size_mb": round(size_mb, 2),
                    "elapsed_s": round(elapsed, 1),
                }
            )
        except Exception as e:
            print(f"   ✗ FAIL: {e}")
            results.append(
                {
                    "track": t.name,
                    "status": "fail",
                    "reason": str(e),
                    "trace": traceback.format_exc(),
                }
            )

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    for s, n in sorted(by_status.items()):
        print(f"  {s:8s}: {n}")

    fails = [r for r in results if r["status"] == "fail"]
    if fails:
        print()
        print("FAILURES:")
        for r in fails:
            print(f"  {r['track']}: {r['reason']}")

    log = args.output_dir / "_export_log.json"
    log.write_text(json.dumps(results, indent=2))
    print()
    print(f"Full log: {log}")

    total_size = sum(r.get("size_mb", 0) for r in results if r["status"] == "ok")
    print(f"Total: {len([r for r in results if r['status'] == 'ok'])} zips, {total_size:.1f} MB")

    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
