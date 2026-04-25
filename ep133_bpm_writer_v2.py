#!/usr/bin/env python3
"""
EP-133 .ppak Generator v2 — reverse-engineered against real Sample Tool backup
==============================================================================

v1 (`ep133_bpm_writer.py`) triggered ERROR CLOCK 43 on import + required a
flash format. This v2 fixes every difference we found between v1's output
and a real Sample Tool backup (`/tmp/ep133_real_backup.ppak`, 2026-04-25):

  - Pad records start from a real default-blank template
    (BPM 120.0 float32, volume 100, release 255, rootNote 60),
    not zero-filled. v1's all-zero blanks meant 47 pads with BPM=0.0 —
    almost certainly the CLOCK 43 trigger.
  - No `settings` file in the project TAR — real format doesn't have one.
  - `meta.json` matches Sample Tool's format: pak_type="project",
    author="computer", current ISO timestamp with millisecond precision.
  - Pad-record byte offsets corrected (phones24's table was shifted by ~1):
    volume@16, release@20, time.mode@21, playMode@23, rootNote@24.

Presets (--preset):
  mvp     One pad (C-1), BPM 120, no loop, time.mode=off.
          Goal: validate the container format. Run this FIRST.
  matrix  12-pad BPM × loop matrix. Run only after mvp loads cleanly.

Usage:
    python3 ep133_bpm_writer_v2.py <audio.wav> [--preset mvp|matrix] \\
        [--out file.ppak] [--sku TE032AS001] [--project 7]
"""

import argparse
import json
import os
import struct
import sys
import tarfile
import wave
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

PAD_RECORD_SIZE = 27

# ----------------------------------------------------------------------
# REAL default blank pad — extracted byte-for-byte from a Sample Tool
# backup (P01.tar / pads/a/p01 of an empty device, 2026-04-25).
#
# Layout (every default value matches the corresponding JSON metadata
# default for an unconfigured pad — strong cross-check):
#
#   0-1    soundId u16 LE         (slot, 0 = empty)
#   2      midiChannel
#   3-5    trimLeft u24 LE
#   7-9    trimRight delta u24 LE (overlaps byte 8 BPM-flag — see note)
#   12-15  BPM float32 LE         (default 120.0)
#   16     volume u8              (default 100)
#   17     pitch i8
#   18     pan i8
#   19     attack u8
#   20     release u8             (default 255)
#   21     time.mode u8           (0=off, 1=bpm, 2=bar)
#   22     inChokeGroup u8
#   23     playMode u8            (0=oneshot, 1=key, 2=legato)
#   24     rootNote u8            (default 60 = middle C)
#   25-26  unknown
# ----------------------------------------------------------------------

BLANK_PAD_TEMPLATE = bytes([
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,   # 0-7
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xf0, 0x42,   # 8-15  (float32 LE 120.0)
    0x64,                                              # 16: volume=100
    0x00, 0x00, 0x00,                                  # 17-19
    0xff,                                              # 20: release=255
    0x00, 0x00,                                        # 21-22
    0x00,                                              # 23: playMode=oneshot
    0x3c,                                              # 24: rootNote=60
    0x00, 0x00,                                        # 25-26
])
assert len(BLANK_PAD_TEMPLATE) == PAD_RECORD_SIZE


def encode_bpm_override(bpm: int) -> tuple[int, int, int, int]:
    """Return (b8, b13, b14, b15) for the override-BPM encoding.

    Verified across three pad C-9 saves on-device (2026-04-24):
      BPM=92  → 80 B8 00  → 184/2 = 92  (low-range)
      BPM=100 → 80 C8 00  → 200/2 = 100 (low-range)
      BPM=150 → 80 96 80  → 150        (high-range)

    Byte 8 is a low-range companion flag; bytes 13-15 are the override
    triple. The float32 at +12..+15 is partially overwritten by bytes
    14-15 when override is set.
    """
    if bpm < 128:
        return (0x20, 0x80, bpm * 2, 0x00)
    return (0x00, 0x80, bpm, 0x80)


def make_pad_record(
    sample_slot: int = 0,
    bpm: int | None = None,
    loopstart: int = 0,
    loopend: int = 0,
    time_mode: str = "off",
) -> bytes:
    """Build a 27-byte pad record from the real default-blank template.

    Only the supplied fields are overwritten; the rest keep real defaults
    (volume=100, release=255, rootNote=60, BPM float=120.0).

    NOTE: byte 8 (BPM low-range flag) overlaps with the trimRight u24 LE
    range (bytes 7-9). Writing both `bpm` and a non-zero `loopend` will
    corrupt one or the other. trimRight offsets are unverified anyway.
    """
    record = bytearray(BLANK_PAD_TEMPLATE)

    record[0:2] = struct.pack("<H", sample_slot)

    if loopstart > 0:
        record[3:6] = struct.pack("<I", loopstart)[:3]
    if loopend > 0:
        record[7:10] = struct.pack("<I", loopend)[:3]

    if bpm is not None:
        b8, b13, b14, b15 = encode_bpm_override(bpm)
        record[8] = b8
        record[13] = b13
        record[14] = b14
        record[15] = b15

    time_mode_map = {"off": 0, "bpm": 1, "bar": 2}
    record[21] = time_mode_map[time_mode]

    return bytes(record)


# ----------------------------------------------------------------------
# Presets — each returns dict[(group, pad_num)] -> pad config dict
# ----------------------------------------------------------------------

def preset_mvp() -> dict:
    """One pad: C-1, slot 100, BPM 120, no loop, time.mode=off.

    Minimum viable test for the container format. If this loads, the
    meta.json + TAR layout + blank-pad defaults are right; the only
    thing being verified for playback is override-BPM byte placement.
    """
    return {
        ("c", 1): {"slot": 100, "bpm": 120, "time_mode": "off"},
    }


def preset_matrix() -> dict:
    """12-pad BPM × loop matrix (the v1 test plan). Run only after MVP."""
    pads = [
        (1,  60,  0.0,  1.0),
        (2,  80,  0.0,  1.0),
        (3, 100,  0.0,  1.0),
        (4, 120,  0.0,  1.0),
        (5, 130,  0.5,  1.0),
        (6, 140,  0.5,  1.0),
        (7, 150,  0.5,  1.0),
        (8, 160,  0.5,  1.0),
        (9, 170,  0.25, 0.75),
        (10, 180, 0.25, 0.75),
        (11, 190, 0.25, 0.75),
        (12, 200, 0.25, 0.75),
    ]
    return {
        ("c", pad_num): {
            "slot": 100 + (pad_num - 1),
            "bpm": bpm,
            "frac_start": frac_start,
            "frac_end": frac_end,
            "time_mode": "bpm",
        }
        for pad_num, bpm, frac_start, frac_end in pads
    }


PRESETS = {
    "mvp": preset_mvp,
    "matrix": preset_matrix,
}


# ----------------------------------------------------------------------
# TAR + ZIP assembly
# ----------------------------------------------------------------------

def get_audio_frame_count(audio_path: str) -> int:
    try:
        with wave.open(audio_path, "rb") as wf:
            return wf.getnframes()
    except wave.Error:
        return os.path.getsize(audio_path) // 4


def build_project_tar(spec: dict, audio_frame_count: int) -> bytes:
    """Build the project TAR.

    Real format: pads/{a,b,c,d}/p{01..12} + patterns/. Nothing else.
    """
    DIR_MODE = 0o755  # match real backup (Sample Tool emits 0755)

    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="pads")
        info.type = tarfile.DIRTYPE
        info.mode = DIR_MODE
        tar.addfile(info)

        for group in ("a", "b", "c", "d"):
            info = tarfile.TarInfo(name=f"pads/{group}")
            info.type = tarfile.DIRTYPE
            info.mode = DIR_MODE
            tar.addfile(info)

            for pad_num in range(1, 13):
                cfg = spec.get((group, pad_num))
                if cfg:
                    loopstart = int(audio_frame_count * cfg.get("frac_start", 0))
                    loopend_frac = cfg.get("frac_end", 0)
                    loopend = int(audio_frame_count * loopend_frac) if loopend_frac else 0
                    record = make_pad_record(
                        sample_slot=cfg["slot"],
                        bpm=cfg.get("bpm"),
                        loopstart=loopstart,
                        loopend=loopend,
                        time_mode=cfg.get("time_mode", "off"),
                    )
                else:
                    record = BLANK_PAD_TEMPLATE

                info = tarfile.TarInfo(name=f"pads/{group}/p{pad_num:02d}")
                info.size = len(record)
                tar.addfile(info, BytesIO(record))

        info = tarfile.TarInfo(name="patterns")
        info.type = tarfile.DIRTYPE
        info.mode = DIR_MODE
        tar.addfile(info)

    return buf.getvalue()


def build_meta_json(device_sku: str = "TE032AS001") -> str:
    """Match Sample Tool's emit format. ms-precision ISO timestamp."""
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return json.dumps({
        "info": "teenage engineering - pak file",
        "pak_version": 1,
        "pak_type": "project",
        "pak_release": "1.2.0",
        "device_name": "EP-133",
        "device_sku": device_sku,
        "device_version": "2.0.5",
        "generated_at": ts,
        "author": "computer",
        "base_sku": device_sku,
    }, indent=2)


def build_ppak(
    audio_path: str,
    output_path: str,
    spec: dict,
    project_num: int = 7,
    device_sku: str = "TE032AS001",
):
    """Build a .ppak ZIP. Entry order matches Sample Tool's emit:
    projects/ → sounds/ → meta.json. Entry mtimes set to current time
    (Python's zipfile default of 1980 was being rejected by Sample Tool)."""
    with open(audio_path, "rb") as f:
        audio_data = f.read()
    audio_frames = get_audio_frame_count(audio_path)
    audio_filename = Path(audio_path).stem

    tar_data = build_project_tar(spec, audio_frames)
    meta_json = build_meta_json(device_sku)

    slots = sorted({cfg["slot"] for cfg in spec.values()})

    now = datetime.now()
    zip_mtime = (now.year, now.month, now.day, now.hour, now.minute, now.second)

    def _add(zf, name, data):
        info = zipfile.ZipInfo(name, date_time=zip_mtime)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, data)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        _add(zf, f"/projects/P{project_num:02d}.tar", tar_data)
        for slot in slots:
            _add(zf, f"/sounds/{slot:03d} {audio_filename}.wav", audio_data)
        _add(zf, "/meta.json", meta_json)

    print(f"✓ Created {output_path}")
    print(f"  Project: P{project_num:02d}")
    print(f"  Configured pads: {len(spec)}")
    print(f"  Audio slots: {slots}")
    print(f"  Audio frames: {audio_frames:,}")
    print()
    print("Pad layout:")
    for (group, pad), cfg in sorted(spec.items()):
        bpm = cfg.get("bpm", "—")
        tm = cfg.get("time_mode", "off")
        loop = ""
        if cfg.get("frac_start") or cfg.get("frac_end"):
            loop = f", loop {cfg.get('frac_start', 0):.0%}-{cfg.get('frac_end', 1.0):.0%}"
        print(f"  {group.upper()}-{pad:02d} (slot {cfg['slot']}, bpm={bpm}, time.mode={tm}{loop})")


def main():
    p = argparse.ArgumentParser(description="EP-133 .ppak generator (v2, real-default-aware)")
    p.add_argument("audio", help="WAV audio file")
    p.add_argument("--preset", choices=PRESETS.keys(), default="mvp",
                   help="Preset config (default: mvp = one-pad safety test)")
    p.add_argument("--out", default="ep133_v2.ppak", help="Output .ppak path")
    p.add_argument("--sku", default="TE032AS001", help="Device SKU")
    p.add_argument("--project", type=int, default=7, help="Target project slot 1..99")
    args = p.parse_args()

    if not os.path.exists(args.audio):
        print(f"Error: {args.audio} not found", file=sys.stderr)
        sys.exit(1)

    spec = PRESETS[args.preset]()
    build_ppak(args.audio, args.out, spec, args.project, args.sku)


if __name__ == "__main__":
    main()
