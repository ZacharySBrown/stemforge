"""
amxd_pack — write a Max for Live device container (.amxd) from patch JSON.

Reverse-engineered format (verified against Ableton Live 12 / Max 9 devices
shipped in m4l/*.amxd):

    Offset  Field          Value
    ------  -------------  ----------------------------------------------------
    0       magic          b'ampf'
    4       version (u32)  0x00000004  (LE; container format v4)
    8       iiii           b'iiii' — a fixed sentinel prefix for the meta chunk
    12      meta           b'meta'
    16      meta_len (u32) 4 (LE)
    20      meta_val (u32) 1 for an audio-effect device, 7 for audio-effect+js
                            project (observed in StemForgeLoader.amxd). A
                            value of 1 works for both; Live upgrades it on save.
    24      ptch           b'ptch'
    28      ptch_len (u32) length of the patch payload that follows (LE)
    32      ptch_data      UTF-8 patcher JSON, optionally null-terminated.

The template builder device in m4l/StemForgeTemplateBuilder.amxd ends its
patch chunk with b'\\n}\\n\\x00' — a null byte pad. We reproduce that here so
byte-for-byte round-tripping of a simple device is exact.

Usage:

    from amxd_pack import pack_amxd
    pack_amxd(patch_dict, "StemForge.amxd", device_type=1)
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

AMPF_MAGIC = b"ampf"
AMPF_VERSION = 4  # u32 LE — v4 is what Live 12 / Max 9 writes.
IIII_SENTINEL = b"iiii"
META_TAG = b"meta"
PTCH_TAG = b"ptch"

# Observed device_type values:
#   1 — plain audio effect (StemForgeTemplateBuilder.amxd)
#   7 — audio effect with additional JS/Node project resources
#       (StemForgeLoader.amxd, which embeds its loader .js after the JSON)
# We default to 1; Live 12 rewrites on save if it needs more features.
DEFAULT_DEVICE_TYPE = 1


def _u32_le(value: int) -> bytes:
    return struct.pack("<I", value)


def _build_patch_chunk(patcher_json: str) -> bytes:
    """Encode patch JSON + trailing null pad into the `ptch` chunk body.

    Max writes a trailing b'\\x00' after the JSON in simple audio-effect
    devices. We replicate that behavior. Final payload is the raw bytes the
    length field refers to.
    """
    data = patcher_json.encode("utf-8")
    if not data.endswith(b"\x00"):
        data = data + b"\x00"
    return data


def pack_amxd(
    patcher: dict[str, Any] | str,
    out_path: str | Path,
    *,
    device_type: int = DEFAULT_DEVICE_TYPE,
    pretty: bool = True,
) -> Path:
    """Serialize a patcher dict (or pre-serialized JSON string) to an .amxd.

    Args:
        patcher: Either a dict matching the Max patcher schema
                 ({"patcher": {...}}), or a JSON string of same.
        out_path: Destination file path.
        device_type: Meta chunk value. Default 1 = audio effect.
        pretty: If True and `patcher` is a dict, indent JSON with tabs to
                mimic Max's output style.

    Returns:
        Path of the written file.
    """
    if isinstance(patcher, dict):
        if pretty:
            patcher_json = json.dumps(patcher, indent="\t")
        else:
            patcher_json = json.dumps(patcher)
    elif isinstance(patcher, str):
        patcher_json = patcher
    else:
        raise TypeError(f"patcher must be dict or str, got {type(patcher)}")

    ptch_body = _build_patch_chunk(patcher_json)

    # Header layout
    blob = bytearray()
    blob += AMPF_MAGIC
    blob += _u32_le(AMPF_VERSION)
    blob += IIII_SENTINEL
    blob += META_TAG
    blob += _u32_le(4)
    blob += _u32_le(int(device_type))
    blob += PTCH_TAG
    blob += _u32_le(len(ptch_body))
    blob += ptch_body

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(blob))
    return out


def unpack_amxd(path: str | Path) -> dict[str, Any]:
    """Read an .amxd and return {'device_type': int, 'patcher': dict, 'raw_tail': bytes}.

    Used by tests to verify round-trip integrity and by debugging tools.
    """
    raw = Path(path).read_bytes()
    if raw[:4] != AMPF_MAGIC:
        raise ValueError(f"not an amxd file: magic={raw[:4]!r}")

    version = struct.unpack_from("<I", raw, 4)[0]
    if version != AMPF_VERSION:
        # not fatal — log and continue
        pass

    # Expect 'iiii' at offset 8
    if raw[8:12] != IIII_SENTINEL:
        raise ValueError(f"missing iiii sentinel at offset 8: {raw[8:12]!r}")

    # Expect 'meta' at offset 12
    if raw[12:16] != META_TAG:
        raise ValueError(f"missing meta tag at offset 12: {raw[12:16]!r}")
    meta_len = struct.unpack_from("<I", raw, 16)[0]
    meta_val = struct.unpack_from("<I", raw, 20)[0] if meta_len >= 4 else 0

    ptch_off = 20 + meta_len
    if raw[ptch_off : ptch_off + 4] != PTCH_TAG:
        raise ValueError(
            f"missing ptch tag at offset {ptch_off}: {raw[ptch_off:ptch_off + 4]!r}"
        )
    ptch_len = struct.unpack_from("<I", raw, ptch_off + 4)[0]
    ptch_body = raw[ptch_off + 8 : ptch_off + 8 + ptch_len]

    # Body may be JSON-then-null, or JSON-then-appended-resources (loader case).
    decoder = json.JSONDecoder()
    try:
        patcher, end = decoder.raw_decode(ptch_body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise ValueError(f"patch chunk is not valid JSON: {e}") from e

    tail = ptch_body[end:]
    return {
        "version": version,
        "device_type": meta_val,
        "patcher": patcher,
        "raw_tail": tail,
    }
