"""build_amxd — CLI that produces v0/build/StemForge.amxd.

Usage (from repo root):
    python -m v0.src.maxpat-builder.build_amxd           # default paths
    python v0/src/maxpat-builder/build_amxd.py           # same, script form

Default paths are resolved relative to the repo root (two levels up from this
file), so the script is safe to run from any cwd.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make sibling modules importable when run as a script.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from amxd_pack import pack_amxd  # noqa: E402
from builder import build_patcher  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent  # maxpat-builder → src → v0 → repo-root

DEFAULT_DEVICE_YAML = REPO_ROOT / "v0" / "interfaces" / "device.yaml"
DEFAULT_OUT = REPO_ROOT / "v0" / "build" / "StemForge.amxd"
M4L_JS_DIR = REPO_ROOT / "v0" / "src" / "m4l-js"

JS_FILES = ["stemforge_bridge.v0.js", "stemforge_loader.v0.js"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build StemForge.amxd from device.yaml")
    ap.add_argument("--device-yaml", default=str(DEFAULT_DEVICE_YAML))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument(
        "--device-type",
        type=int,
        default=1,
        help="amxd meta value (1=plain audio effect, 7=project with embedded resources)",
    )
    args = ap.parse_args(argv)

    # JS files are distributed via Max Package (~/Documents/Max 9/Packages/StemForge/),
    # NOT embedded in the .amxd. The mx@c embedding format has undocumented checksums
    # that cause "error -1 making directory" on load. See m4l_device_development_guide.md.
    patcher = build_patcher(args.device_yaml)
    path = pack_amxd(patcher, args.out, device_type=args.device_type)
    size = path.stat().st_size
    print(f"wrote {path} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
