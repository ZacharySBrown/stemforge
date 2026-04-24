"""sf_deploy — sync StemForge JS + presets + .amxd to every live location.

What this does
--------------
1. Copies every `v0/src/m4l-js/*.js` to `v0/src/m4l-package/StemForge/javascript/`.
2. Copies every `v0/src/m4l-js/*.js` to `~/Documents/Max 9/Packages/StemForge/javascript/`
   (the Max-reloadable live package) so the running device sees changes.
3. Copies every `presets/*.json` to `~/Documents/Max 9/Packages/StemForge/presets/`.
4. Rebuilds `v0/build/StemForge.amxd` via `build_amxd.py`.
5. Copies the fresh `.amxd` into the Ableton User Library so a reload in Live
   picks up the new device.

Usage (from repo root):

    uv run python tools/sf_deploy.py          # do everything (default)
    uv run python tools/sf_deploy.py --js-only
    uv run python tools/sf_deploy.py --amxd-only
    uv run python tools/sf_deploy.py --dry-run

Idempotent — running repeatedly is safe. Skips unchanged files by comparing
size and mtime so watch-loops stay quiet.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_SRC_DIR = REPO_ROOT / "v0" / "src" / "m4l-js"
JS_PKG_DIR = REPO_ROOT / "v0" / "src" / "m4l-package" / "StemForge" / "javascript"
PRESETS_SRC_DIR = REPO_ROOT / "presets"
BUILD_AMXD = REPO_ROOT / "v0" / "src" / "maxpat-builder" / "build_amxd.py"
AMXD_OUT = REPO_ROOT / "v0" / "build" / "StemForge.amxd"

HOME = Path.home()
LIVE_PKG_JS_DIR = HOME / "Documents" / "Max 9" / "Packages" / "StemForge" / "javascript"
LIVE_PKG_PRESETS_DIR = HOME / "Documents" / "Max 9" / "Packages" / "StemForge" / "presets"
# Ableton User Library path — standard on macOS. Override with --ableton-lib.
DEFAULT_ABLETON_LIB = (
    HOME / "Music" / "Ableton" / "User Library" / "Presets" / "Audio Effects"
    / "Max Audio Effect"
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _need_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    if src.stat().st_size != dst.stat().st_size:
        return True
    if int(src.stat().st_mtime) > int(dst.stat().st_mtime):
        return True
    return False


def _copy_file(src: Path, dst: Path, *, dry_run: bool) -> bool:
    if not _need_copy(src, dst):
        return False
    if dry_run:
        print(f"  [dry] cp {src} → {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  cp {src.name} → {dst}")
    return True


# ── Sync JS ──────────────────────────────────────────────────────────────────


def sync_js(dry_run: bool, include_live: bool = True) -> int:
    if not JS_SRC_DIR.is_dir():
        print(f"error: {JS_SRC_DIR} not found", file=sys.stderr)
        return 2

    js_files = sorted(JS_SRC_DIR.glob("*.js"))
    if not js_files:
        print(f"error: no .js files in {JS_SRC_DIR}", file=sys.stderr)
        return 2

    total = 0
    print(f"→ sync {len(js_files)} JS files from {JS_SRC_DIR}")
    print(f"  target 1: {JS_PKG_DIR}")
    for src in js_files:
        if _copy_file(src, JS_PKG_DIR / src.name, dry_run=dry_run):
            total += 1

    if include_live:
        print(f"  target 2: {LIVE_PKG_JS_DIR}")
        for src in js_files:
            if _copy_file(src, LIVE_PKG_JS_DIR / src.name, dry_run=dry_run):
                total += 1

    print(f"  → {total} file(s) {'would be' if dry_run else ''} copied")
    return 0


# ── Sync presets ─────────────────────────────────────────────────────────────


def sync_presets(dry_run: bool) -> int:
    if not PRESETS_SRC_DIR.is_dir():
        print(f"error: {PRESETS_SRC_DIR} not found", file=sys.stderr)
        return 2

    preset_files = sorted(PRESETS_SRC_DIR.glob("*.json"))
    if not preset_files:
        print(f"  (no .json files in {PRESETS_SRC_DIR})")
        return 0

    total = 0
    print(f"→ sync {len(preset_files)} preset(s) → {LIVE_PKG_PRESETS_DIR}")
    for src in preset_files:
        if _copy_file(src, LIVE_PKG_PRESETS_DIR / src.name, dry_run=dry_run):
            total += 1
    print(f"  → {total} file(s) {'would be' if dry_run else ''} copied")
    return 0


# ── Rebuild + install AMXD ──────────────────────────────────────────────────


def rebuild_amxd(dry_run: bool) -> int:
    if dry_run:
        print(f"→ [dry] would run: python {BUILD_AMXD}")
        return 0
    if not BUILD_AMXD.exists():
        print(f"error: {BUILD_AMXD} not found", file=sys.stderr)
        return 2
    print(f"→ rebuild: python {BUILD_AMXD}")
    r = subprocess.run(
        [sys.executable, str(BUILD_AMXD)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("build_amxd failed:", file=sys.stderr)
        print(r.stdout, file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        return r.returncode
    print(r.stdout.strip())
    return 0


def install_amxd(ableton_lib: Path, dry_run: bool) -> int:
    if not AMXD_OUT.exists():
        print(f"error: {AMXD_OUT} not found — run rebuild first", file=sys.stderr)
        return 2
    dst = ableton_lib / AMXD_OUT.name
    print(f"→ install {AMXD_OUT.name} → {dst}")
    _copy_file(AMXD_OUT, dst, dry_run=dry_run)
    return 0


# ── Driver ───────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="sf-deploy",
        description="Sync StemForge JS + rebuild/install .amxd.",
    )
    ap.add_argument("--js-only", action="store_true",
                    help="Only sync JS files.")
    ap.add_argument("--amxd-only", action="store_true",
                    help="Only rebuild + install the .amxd.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen but make no changes.")
    ap.add_argument(
        "--skip-live",
        action="store_true",
        help="Skip copying to ~/Documents/Max 9/Packages/StemForge/javascript.",
    )
    ap.add_argument(
        "--ableton-lib",
        default=str(DEFAULT_ABLETON_LIB),
        help=f"Ableton User Library target dir (default: {DEFAULT_ABLETON_LIB})",
    )
    args = ap.parse_args(argv)

    ableton_lib = Path(args.ableton_lib).expanduser()

    if args.js_only and args.amxd_only:
        print("error: pass at most one of --js-only / --amxd-only", file=sys.stderr)
        return 2

    rc = 0
    if not args.amxd_only:
        rc = sync_js(dry_run=args.dry_run, include_live=not args.skip_live)
        if rc:
            return rc
        rc = sync_presets(dry_run=args.dry_run)
        if rc:
            return rc

    if not args.js_only:
        rc = rebuild_amxd(dry_run=args.dry_run)
        if rc:
            return rc
        rc = install_amxd(ableton_lib, dry_run=args.dry_run)
        if rc:
            return rc

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
