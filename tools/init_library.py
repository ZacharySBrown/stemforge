#!/usr/bin/env python3
"""init_library — create the StemForge subdivisions inside the user's library.

Idempotent. Creates only the directories that are missing; never moves or
deletes existing files.

Adds the Loops/ subdivision (Drums/, Bass/, Melodic/, Vocal/) on top of the
user's existing taxonomy at ~/mus/Samples/. See specs/library-routing.md.

Usage:
    uv run python tools/init_library.py             # default: ~/mus
    uv run python tools/init_library.py --root /other/library
    uv run python tools/init_library.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Subdivisions the curation router writes into. Match stemforge/router.py
# bucket subpaths.
SUBDIRS = (
    "Samples/Loops/Drums",
    "Samples/Loops/Bass",
    "Samples/Loops/Melodic",
    "Samples/Loops/Vocal",
    "Samples/Oneshots/Kicks",
    "Samples/Oneshots/Snares",
    "Samples/Oneshots/Hats",
    "Samples/Oneshots/Percussion",
    "Samples/Vocals",
    "Samples/_Incoming",
    "Projects/Stems",
)


def init_library(root: Path, *, dry_run: bool = False) -> tuple[list[Path], list[Path]]:
    created: list[Path] = []
    existed: list[Path] = []
    for sub in SUBDIRS:
        path = root / sub
        if path.exists():
            existed.append(path)
            continue
        if dry_run:
            created.append(path)
            continue
        path.mkdir(parents=True, exist_ok=True)
        created.append(path)
    return created, existed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", "-r", type=Path, default=Path("~/mus").expanduser(),
                    help="Library root (default: ~/mus)")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="Print what would be created without writing")
    args = ap.parse_args(argv)

    root = args.root.expanduser()
    if not root.exists():
        print(f"[!] Library root does not exist: {root}", file=sys.stderr)
        print(f"    Create it first or pass --root <path>.", file=sys.stderr)
        return 2

    created, existed = init_library(root, dry_run=args.dry_run)

    label = "WOULD CREATE" if args.dry_run else "CREATED"
    if created:
        print(f"\n{label} ({len(created)}):")
        for p in created:
            print(f"  + {p}")
    if existed:
        print(f"\nALREADY EXIST ({len(existed)}):")
        for p in existed:
            print(f"  · {p}")
    if not created and not existed:
        print("Nothing to do — library_root has no expected subpaths and dry-run was off?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
