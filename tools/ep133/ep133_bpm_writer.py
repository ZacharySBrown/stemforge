#!/usr/bin/env python3
"""
EP-133 .ppak Generator v3 — patch-from-real strategy
====================================================

v2 (build-from-scratch) was silently rejected by Sample Tool despite matching
the real backup's structure on every observable axis (meta.json, blank-pad
bytes, ZIP order/timestamps, TAR entries). Some byte-level detail still
differs.

v3 abandons from-scratch. It takes a real Sample Tool backup as the base,
modifies ONLY the bytes that need to change (pad records, optionally meta
timestamp), and repacks. Format drift = 0.

Required: a real `.ppak` from Sample Tool's Backup, used as the base.

Usage:
    python3 ep133_bpm_writer_v3.py \\
        --base /tmp/ep133_real_backup.ppak \\
        --preset mvp \\
        --out /tmp/ep133_v3_mvp.ppak

The base's audio (whatever was in the real backup's /sounds/) is reused
as-is. The base's project number is preserved (e.g., if base has P01.tar,
output also targets P01).
"""

import argparse
import os
import struct
import sys
import zipfile
from datetime import datetime, timezone
from io import BytesIO

PAD_RECORD_SIZE = 27
TAR_BLOCK = 512


def encode_bpm_override(bpm: int) -> tuple[int, int, int, int]:
    if bpm < 128:
        return (0x20, 0x80, bpm * 2, 0x00)
    return (0x00, 0x80, bpm, 0x80)


def patch_pad_record(record: bytes, sample_slot: int, sample_length_frames: int,
                     bpm: int | None = None, bpm_override: bool = False,
                     time_mode: str = "off") -> bytes:
    """Patch a 27-byte pad record using VERIFIED offsets (see
    `memory/project_ep133_pad_record_correct.md`).

    Byte layout (verified 2026-04-25 by diffing two real Sample Tool backups):
      +1    : slot u8 (sample-library slot 1..255)
      +8..11: sample length in frames (u32 LE) — REQUIRED, the binding
              is broken without this.
      +12..15: BPM float32 LE (when override flag at +13 is NOT 0x80)
      +13..15 (override mode): byte +13 = 0x80, +14 = bpm×2 (low) or bpm (high),
              +15 = 0x00 (low-range, BPM<128) or 0x80 (high-range)

    If bpm_override=False, writes BPM as float32 at +12..+15. If True,
    writes the 3-byte override at +13..+15 (overrides the float32).
    """
    rec = bytearray(record)
    rec[1] = sample_slot & 0xFF
    rec[8:12] = struct.pack("<I", sample_length_frames)

    if bpm is not None:
        if bpm_override:
            _, b13, b14, b15 = encode_bpm_override(bpm)
            rec[13] = b13
            rec[14] = b14
            rec[15] = b15
            # byte +12 stays 0 in override mode (verified from on-device captures)
            rec[12] = 0
        else:
            rec[12:16] = struct.pack("<f", float(bpm))

    rec[21] = {"off": 0, "bpm": 1, "bar": 2}[time_mode]
    return bytes(rec)


def find_pad_record_offsets(tar_bytes: bytes) -> dict:
    """Scan the TAR and return a dict of (group, pad_num) -> data_offset.
    The data offset is where the 27-byte pad record starts (i.e., right
    after the 512-byte header block)."""
    offsets = {}
    pos = 0
    while pos + TAR_BLOCK <= len(tar_bytes):
        header = tar_bytes[pos:pos + TAR_BLOCK]
        if header[:4] == b"\x00\x00\x00\x00":
            break
        name = header[:100].rstrip(b"\x00/").decode("ascii", errors="replace")
        try:
            size = int(header[124:135].rstrip(b"\x00 ") or b"0", 8)
        except ValueError:
            size = 0
        typeflag = chr(header[156]) if header[156] else "0"

        # Match pads/<group>/p<NN>
        if typeflag in ("0", "\x00") and name.startswith("pads/") and len(name) == len("pads/x/pNN"):
            group = name[5]
            try:
                pad_num = int(name[8:10])
                if group in "abcd" and 1 <= pad_num <= 12:
                    offsets[(group, pad_num)] = pos + TAR_BLOCK
            except ValueError:
                pass

        # Advance past header + data (rounded to 512-block)
        data_blocks = (size + TAR_BLOCK - 1) // TAR_BLOCK
        pos += TAR_BLOCK + data_blocks * TAR_BLOCK
    return offsets


# Real default-blank pad bytes (verbatim from a fresh Sample Tool backup).
# Used to reset all pads before applying the spec — ensures the output
# contains ONLY what we specified, not stray bindings from the base.
DEFAULT_BLANK_PAD = bytes([
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0x42,
    0x64, 0x00, 0x00, 0x00, 0xff, 0x00, 0x00, 0x00,
    0x3c, 0x00, 0x00,
])
assert len(DEFAULT_BLANK_PAD) == PAD_RECORD_SIZE


def patch_tar(tar_bytes: bytes, spec: dict, reset_others: bool = True) -> bytes:
    """Apply the spec to a TAR's pad records, returning new TAR bytes.

    If `reset_others` is True (default), every pad NOT in the spec is
    reset to DEFAULT_BLANK_PAD first — guaranteeing the output project
    contains exactly the bindings specified, no more.

    Each cfg in spec must include `slot` and `length` (frames).
    """
    out = bytearray(tar_bytes)
    offsets = find_pad_record_offsets(tar_bytes)

    if reset_others:
        for key, off in offsets.items():
            if key not in spec:
                out[off:off + PAD_RECORD_SIZE] = DEFAULT_BLANK_PAD

    for (group, pad_num), cfg in spec.items():
        key = (group, pad_num)
        if key not in offsets:
            print(f"WARNING: pad {group.upper()}-{pad_num} not found in base TAR", file=sys.stderr)
            continue
        off = offsets[key]
        # Always start from the verified default — don't trust the base bytes
        new = patch_pad_record(
            DEFAULT_BLANK_PAD,
            sample_slot=cfg["slot"],
            sample_length_frames=cfg["length"],
            bpm=cfg.get("bpm"),
            bpm_override=cfg.get("bpm_override", False),
            time_mode=cfg.get("time_mode", "off"),
        )
        out[off:off + PAD_RECORD_SIZE] = new

    return bytes(out)


def preset_mvp(sample_length: int) -> dict:
    """One pad: C-01 → slot 100, BPM 120 (float32 mode, no override).

    Mirrors what Sample Tool does on assignment: set slot + length, leave
    BPM as a float32. Uses 120.0 as a sane default.
    """
    return {("c", 1): {"slot": 100, "length": sample_length, "bpm": 120, "time_mode": "off"}}


def preset_mvp_override(sample_length: int) -> dict:
    """Same as mvp but uses override-BPM encoding at bytes 13-15."""
    return {
        ("c", 1): {
            "slot": 100, "length": sample_length, "bpm": 120,
            "bpm_override": True, "time_mode": "bpm",
        },
    }


def preset_matrix(sample_length: int) -> dict:
    """12-pad BPM matrix using override encoding (BPMs 60-200)."""
    pads = [
        (1,  60), (2,  80), (3, 100), (4, 120),
        (5, 130), (6, 140), (7, 150), (8, 160),
        (9, 170), (10, 180), (11, 190), (12, 200),
    ]
    return {
        ("c", n): {
            "slot": 100, "length": sample_length, "bpm": bpm,
            "bpm_override": True, "time_mode": "bpm",
        }
        for n, bpm in pads
    }


def preset_matrix_tight(sample_length: int) -> dict:
    """12-pad BPM matrix in 120-180 range — avoids aggressive compression
    that produces 'blip' playback when source_bpm << project_bpm."""
    pads = [
        (1, 120), (2, 125), (3, 130), (4, 135),
        (5, 140), (6, 145), (7, 150), (8, 155),
        (9, 160), (10, 165), (11, 170), (12, 180),
    ]
    return {
        ("c", n): {
            "slot": 100, "length": sample_length, "bpm": bpm,
            "bpm_override": True, "time_mode": "bpm",
        }
        for n, bpm in pads
    }


PRESETS = {
    "mvp": preset_mvp,
    "mvp_override": preset_mvp_override,
    "matrix": preset_matrix,
    "matrix_tight": preset_matrix_tight,
}


def patch_meta_timestamp(meta_json_bytes: bytes) -> bytes:
    """Refresh `generated_at` to current ms-precision UTC. Leaves all
    other fields untouched (so device_sku, base_sku, author, pak_type
    stay exactly as Sample Tool emitted them)."""
    import json
    meta = json.loads(meta_json_bytes.decode("utf-8"))
    now = datetime.now(timezone.utc)
    meta["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return json.dumps(meta, indent=2).encode("utf-8")


def get_sample_length_frames(base_path: str) -> int:
    """Read the WAV inside the base ppak and return its frame count."""
    import wave
    with zipfile.ZipFile(base_path, "r") as zf:
        wav_entries = [i for i in zf.infolist() if i.filename.startswith("/sounds/") and i.filename.endswith(".wav")]
        if not wav_entries:
            raise RuntimeError("base has no WAV in /sounds/")
        wav_data = zf.read(wav_entries[0].filename)
    with wave.open(BytesIO(wav_data), "rb") as wf:
        return wf.getnframes()


def build_from_base(base_path: str, output_path: str, spec: dict, refresh_meta: bool = True):
    """Build a new .ppak by patching pad records in the base's project TAR.

    The base ZIP is decompressed entry-by-entry, the project TAR is
    patched, then everything is re-zipped using the same compression
    method and (where possible) the same metadata.
    """
    if not os.path.exists(base_path):
        print(f"Error: base file {base_path} not found", file=sys.stderr)
        sys.exit(1)

    with zipfile.ZipFile(base_path, "r") as base_zf:
        info_list = base_zf.infolist()
        # Find the project TAR
        project_entries = [i for i in info_list if "/projects/" in i.filename and i.filename.endswith(".tar")]
        if not project_entries:
            print("Error: base has no /projects/*.tar entry", file=sys.stderr)
            sys.exit(1)
        if len(project_entries) > 1:
            print(f"Warning: base has {len(project_entries)} project TARs; patching the first one ({project_entries[0].filename})")
        project_info = project_entries[0]

        # Read everything
        entries = []
        for info in info_list:
            data = base_zf.read(info.filename)
            if info.filename == project_info.filename:
                data = patch_tar(data, spec)
            elif info.filename.endswith("/meta.json") and refresh_meta:
                data = patch_meta_timestamp(data)
            entries.append((info, data))

        # Re-zip with the original entry order, names, and per-entry attrs
        with zipfile.ZipFile(output_path, "w") as out_zf:
            for info, data in entries:
                # Refresh ZIP entry mtime to now (matches Sample Tool's behavior)
                now = datetime.now()
                new_info = zipfile.ZipInfo(
                    filename=info.filename,
                    date_time=(now.year, now.month, now.day,
                               now.hour, now.minute, now.second),
                )
                new_info.compress_type = info.compress_type
                new_info.external_attr = info.external_attr
                new_info.create_system = info.create_system
                out_zf.writestr(new_info, data)

    print(f"✓ Wrote {output_path}")
    print(f"  Patched: {project_info.filename}")
    print(f"  Meta refreshed: {refresh_meta}")
    print()
    print("Pad layout:")
    for (group, pad), cfg in sorted(spec.items()):
        bpm = cfg.get("bpm", "—")
        tm = cfg.get("time_mode", "off")
        print(f"  {group.upper()}-{pad:02d} (slot {cfg['slot']}, bpm={bpm}, time.mode={tm})")


def main():
    p = argparse.ArgumentParser(description="EP-133 .ppak generator (v3, patch-from-real-backup)")
    p.add_argument("--base", required=True, help="Real .ppak from Sample Tool Backup (used as format-clean base)")
    p.add_argument("--preset", choices=PRESETS.keys(), default="mvp")
    p.add_argument("--out", default=os.path.expanduser("~/Desktop/ep133_v3.ppak"))
    p.add_argument("--no-refresh-meta", action="store_true",
                   help="Skip refreshing the generated_at timestamp")
    args = p.parse_args()

    sample_length = get_sample_length_frames(args.base)
    print(f"Base sample length: {sample_length:,} frames")
    spec = PRESETS[args.preset](sample_length)
    build_from_base(args.base, args.out, spec, refresh_meta=not args.no_refresh_meta)


if __name__ == "__main__":
    main()
