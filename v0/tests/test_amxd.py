"""Structural tests for ``StemForge.amxd`` (Track C output).

These tests parse the built .amxd container and confirm:

1. The file exists and is of non-trivial size.
2. The container magic bytes and version chunk match Max 9 / Live 12's format.
3. The patcher JSON round-trips through ``amxd_pack.unpack_amxd``.
4. The node.script loads ``stemforge_bridge.v0.js``.
5. Every UI element id declared in ``device.yaml`` has a corresponding box.

We reuse the Track C container reader (``v0/src/maxpat-builder/amxd_pack.py``)
rather than re-implementing the format. conftest adds it to ``sys.path``.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Iterable

import pytest


# ── helpers ────────────────────────────────────────────────────────────────

def _walk_boxes(patcher: dict) -> Iterable[dict]:
    """Yield every ``box`` dict under ``patcher.boxes[].box`` recursively.

    Max nests subpatchers under ``box.patcher.boxes``. We traverse them so
    UI elements inside bpatchers still register.
    """
    root = patcher.get("patcher", patcher)
    stack: list[dict] = [root]
    while stack:
        p = stack.pop()
        for item in p.get("boxes", []) or []:
            box = item.get("box") if isinstance(item, dict) else None
            if not isinstance(box, dict):
                continue
            yield box
            # Recurse into embedded subpatchers if present.
            sub = box.get("patcher")
            if isinstance(sub, dict):
                stack.append(sub)


def _expected_box_id(yaml_id: str) -> str:
    """Builder convention (v0/src/maxpat-builder/builder.py): ``obj-<id>`` with
    underscores replaced by dashes."""
    return f"obj-{yaml_id.replace('_', '-')}"


# ── tests ──────────────────────────────────────────────────────────────────

def test_amxd_exists(amxd_path: Path) -> None:
    """Built device is present and at least 1KB (rules out empty/truncated)."""
    assert amxd_path.exists(), f"not found: {amxd_path}"
    size = amxd_path.stat().st_size
    assert size > 1024, f"suspiciously small: {size} bytes"


def test_amxd_magic_bytes(amxd_path: Path) -> None:
    """Header: magic=b'ampf', version=4 (LE u32)."""
    raw = amxd_path.read_bytes()
    assert raw[:4] == b"ampf", f"unexpected magic: {raw[:4]!r}"
    version = struct.unpack_from("<I", raw, 4)[0]
    assert version == 4, f"unexpected container version: {version}"


def test_amxd_valid_container(amxd_path: Path) -> None:
    """``unpack_amxd`` parses the file without error and returns a patcher."""
    from amxd_pack import unpack_amxd  # added to sys.path by conftest

    parsed = unpack_amxd(amxd_path)
    assert isinstance(parsed, dict)
    assert "patcher" in parsed, f"unpack result missing 'patcher': {parsed.keys()}"
    assert isinstance(parsed["patcher"], dict)
    assert parsed.get("version") == 4


def test_amxd_references_bridge_js(amxd_path: Path) -> None:
    """The embedded patcher JSON references ``stemforge_bridge.v0.js``."""
    from amxd_pack import unpack_amxd

    parsed = unpack_amxd(amxd_path)
    # Full-text search on the serialized patcher is robust to wherever the
    # filename ends up (node.script filename arg, inspector data, etc).
    blob = json.dumps(parsed["patcher"])
    assert "stemforge_bridge.v0.js" in blob, (
        "patcher does not reference stemforge_bridge.v0.js"
    )


def test_amxd_ui_matches_device_yaml(amxd_path: Path, device_yaml: dict) -> None:
    """Every ``ui.elements[].id`` in device.yaml has a matching box in the patcher.

    Naming convention (builder.py): ``obj-<yaml_id_with_dashes>``. We accept
    either an exact-id match or a suffix match against ``obj-<id>`` forms to
    stay resilient to future renames that preserve the id stem.
    """
    from amxd_pack import unpack_amxd

    parsed = unpack_amxd(amxd_path)
    box_ids = {b.get("id") for b in _walk_boxes(parsed["patcher"]) if b.get("id")}
    assert box_ids, "no boxes with ids found in patcher"

    missing = []
    for element in device_yaml["ui"]["elements"]:
        yaml_id = element["id"]
        expected = _expected_box_id(yaml_id)
        if expected in box_ids:
            continue
        # Fallback: accept a partial match on the underscore/dashless stem.
        stem = yaml_id.replace("_", "-")
        if any(stem in (bid or "") for bid in box_ids):
            continue
        missing.append((yaml_id, expected))

    assert not missing, (
        "UI elements from device.yaml not found as boxes in the amxd patcher: "
        f"{missing}. Boxes seen: {sorted(box_ids)}"
    )
