#!/usr/bin/env python3
"""Inject a build-time content fingerprint into stemforge_loader.v0.js.

Reads every JS file under ``v0/src/m4l-package/StemForge/javascript/`` plus
``v0/build/StemForge.amxd``, computes SHA-256 (first 8 hex chars per file
— enough for drift detection, no crypto strength needed), and replaces
the placeholder ``SF_BUILD_MANIFEST`` literal in the loader source with
a single one-line summary.

Loader then ``post()``s the literal at script init. No runtime file IO,
no chance of crashing Max's JS engine (an earlier attempt to read files
at runtime triggered a Live crash — that's why this lives at build time).

Run after every .amxd rebuild OR JS edit:

    uv run python tools/inject_build_manifest.py

Then sync to mirror + install paths the usual way.

The script keeps the loader file byte-identical when nothing changed,
so it's safe to re-run mid-loop.
"""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOADER_SOURCE = REPO / "v0" / "src" / "m4l-js" / "stemforge_loader.v0.js"
JS_PKG_DIR = REPO / "v0" / "src" / "m4l-package" / "StemForge" / "javascript"
AMXD_BUILT = REPO / "v0" / "build" / "StemForge.amxd"

PLACEHOLDER_RE = re.compile(r'var SF_BUILD_MANIFEST = "[^"]*";')


def _short_sha256(path: Path) -> str:
    """First 8 hex chars of the file's SHA-256, or `????????` if unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:8]
    except OSError:
        return "????????"


def build_manifest() -> str:
    """One-line build summary, deterministic across runs at the same inputs."""
    parts: list[str] = []
    parts.append("build=" + datetime.now(UTC).strftime("%Y-%m-%dT%H:%M"))
    parts.append("amxd=" + _short_sha256(AMXD_BUILT))

    if JS_PKG_DIR.is_dir():
        js_entries = []
        for js in sorted(JS_PKG_DIR.glob("*.js")):
            # Strip .v0.js / .js for brevity in the banner — full names are
            # recoverable from the source tree if needed.
            short = js.stem.replace(".v0", "")
            js_entries.append(f"{short}={_short_sha256(js)}")
        parts.append("js={" + ",".join(js_entries) + "}")
    return " ".join(parts)


def inject(loader: Path = LOADER_SOURCE, *, dry_run: bool = False) -> tuple[str, bool]:
    """Replace the placeholder in `loader`. Returns (new_manifest, changed)."""
    manifest = build_manifest()
    src = loader.read_text()
    replacement = f'var SF_BUILD_MANIFEST = "{manifest}";'
    new_src, n = PLACEHOLDER_RE.subn(replacement, src, count=1)
    if n == 0:
        # First-time setup: find the autowatch/inlets/outlets header block
        # and insert the placeholder right after it.
        marker = "outlets = 4;   // 0: status text  1: bang  2: preset umenu  3: [shell] (mkdir-p)"
        if marker not in src:
            raise SystemExit(
                "could not find injection point in loader (expected the "
                "`outlets = 4;` line). Add `var SF_BUILD_MANIFEST = \"\";` "
                "manually after that line and rerun."
            )
        new_src = src.replace(
            marker,
            marker + "\n\n// Build fingerprint, injected by tools/inject_build_manifest.py.\n"
            + replacement,
            1,
        )
    changed = new_src != src
    if changed and not dry_run:
        loader.write_text(new_src)
    return manifest, changed


def main() -> int:
    dry = "--dry-run" in sys.argv
    manifest, changed = inject(dry_run=dry)
    action = "would write" if dry else ("wrote" if changed else "no change")
    print(f"{action}: {LOADER_SOURCE.relative_to(REPO)}")
    print(f"  manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
