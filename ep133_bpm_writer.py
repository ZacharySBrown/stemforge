#!/usr/bin/env python3
"""
EP-133 BPM + Loop Point Test Generator
======================================

Creates a .ppak file with all 12 Group C pads assigned different BPMs and
loop regions. All pads point to the same audio file (replicated as slots
100-111 so each pad has its own slot).

Usage:
    python3 ep133_bpm_writer.py <audio.wav> [output.ppak] [device_sku]

Defaults:
    output.ppak  = ep133_bpm_test.ppak
    device_sku   = TE032AS001  (extract real one from Sample Tool backup
                                if the import fails)

What you'll get:
    Project 7, Group C, all 12 pads assigned, with this layout:

    pad  | BPM  | loop region        | encoding mode
    -----+------+--------------------+----------------
     1   |  60  | full sample        | low-range
     2   |  80  | full sample        | low-range
     3   | 100  | full sample        | low-range
     4   | 120  | full sample        | low-range
     5   | 130  | last half (50-100) | high-range
     6   | 140  | last half (50-100) | high-range
     7   | 150  | last half (50-100) | high-range
     8   | 160  | last half (50-100) | high-range
     9   | 170  | middle (25-75)     | high-range
    10   | 180  | middle (25-75)     | high-range
    11   | 190  | middle (25-75)     | high-range
    12   | 200  | middle (25-75)     | high-range

Encoding boundary is at 128 — pads 1-4 use low-range (BPM*2), pads 5-12
use high-range (BPM as-is).

Validation checklist:
    - In EP Sample Tool waveform view, pads 1-4 should show full sample,
      pads 5-8 should show only the right half, pads 9-12 should show only
      the middle section.
    - On-device, playing pad 1 (60 BPM) vs pad 7 (150 BPM) should produce
      audibly different stretch ratios.
    - The 7→8 jump (120→130) crosses the encoding boundary — if both BPMs
      sound right, both encoding modes work.

No dependencies beyond Python stdlib.
"""

import struct
import tarfile
import zipfile
import json
import sys
import os
import wave
from io import BytesIO
from pathlib import Path

# ------------------------------------------------------------------
# Pad-record encoding (from 2026-04-24 reverse-engineering session)
# ------------------------------------------------------------------

PAD_RECORD_SIZE = 27

def encode_bpm_override(bpm):
    """
    Encode BPM as override format. Returns (byte_8, byte_13, byte_14, byte_15).

    Detection rule: byte 13 == 0x80 means override encoding.
      - byte 8:  0x20 for low-range (<128), 0x00 for high-range (>=128)
      - byte 13: always 0x80 (override flag)
      - byte 14: BPM*2 for low-range, BPM for high-range
      - byte 15: 0x00 for low-range, 0x80 for high-range
    """
    if bpm < 128:
        return (0x20, 0x80, bpm * 2, 0x00)
    else:
        return (0x00, 0x80, bpm, 0x80)


def create_pad_record(sample_slot, bpm=None, loopstart=0, loopend=0):
    """
    Build a 27-byte pad record.

    sample_slot : 1..999 (which sample library slot this pad plays)
    bpm         : int, or None for default
    loopstart   : sample-frame index for loop start (0 = beginning)
    loopend     : sample-frame index for loop end (0 = end of sample)

    Byte layout (per spec §6, partially verified by 2026-04-24 captures):
      0-1   : sample slot u16 LE                           ✓ verified
      3-5   : trimLeft u24 LE (loopstart)                  unverified offset
      7-9   : trimRight u24 LE (loopend)                   unverified offset
      8     : BPM low-range companion flag (0x20 / 0x00)   ✓ verified
      13    : BPM override flag (0x80)                     ✓ verified
      14    : BPM value (or value*2 if low-range)          ✓ verified
      15    : BPM precision flag (0x80 high / 0x00 low)    ✓ verified
      20    : time.mode (0=off, 1=bpm, 2=bars)             unverified offset

    NOTE: bytes 8 and 20 conflict — both are claimed by different fields
    in the spec. We're writing byte 8 as the BPM companion (verified) and
    byte 20 as time.mode (unverified). If time.mode doesn't stick at +20,
    try +21 or check whether the device infers BPM mode from byte 8
    alone.
    """
    record = bytearray(PAD_RECORD_SIZE)

    # Bytes 0-1: sample slot, u16 LE
    record[0:2] = struct.pack('<H', sample_slot)

    # Loop points (working hypothesis based on phones24 offsets)
    if loopstart > 0 or loopend > 0:
        record[3:6] = struct.pack('<I', loopstart)[:3]   # trimLeft, u24 LE
        record[7:10] = struct.pack('<I', loopend)[:3]    # trimRight, u24 LE

    # BPM override encoding (verified)
    if bpm is not None:
        b8, b13, b14, b15 = encode_bpm_override(bpm)
        record[8] = b8
        record[13] = b13
        record[14] = b14
        record[15] = b15

        # time.mode = "bpm" so the device actually time-stretches on playback
        record[20] = 1  # 0=off, 1=bpm, 2=bars

    return bytes(record)


# ------------------------------------------------------------------
# Audio helpers
# ------------------------------------------------------------------

def get_audio_frame_count(audio_path):
    """Return the number of sample frames in a WAV file."""
    try:
        with wave.open(audio_path, 'rb') as wf:
            return wf.getnframes()
    except wave.Error:
        # If the file isn't a standard WAV (e.g., 24-bit), fall back to
        # estimating from file size / typical bytes-per-frame
        size = os.path.getsize(audio_path)
        # Assume 16-bit stereo 44.1kHz as a guess; this is just for
        # picking loop-point offsets, not for the actual playback
        return size // 4


# ------------------------------------------------------------------
# Project layout
# ------------------------------------------------------------------

# Pad-by-pad spec: (pad_num, bpm, loop_fraction_start, loop_fraction_end)
PAD_SPEC = [
    (1,  60,  0.0,  1.0),    # full sample, low-range BPM
    (2,  80,  0.0,  1.0),
    (3, 100,  0.0,  1.0),
    (4, 120,  0.0,  1.0),    # last low-range pad before encoding boundary
    (5, 130,  0.5,  1.0),    # crossed to high-range, last half of sample
    (6, 140,  0.5,  1.0),
    (7, 150,  0.5,  1.0),
    (8, 160,  0.5,  1.0),
    (9, 170,  0.25, 0.75),   # middle section
    (10, 180, 0.25, 0.75),
    (11, 190, 0.25, 0.75),
    (12, 200, 0.25, 0.75),
]


def create_project_tar(audio_frame_count):
    """
    Create the TAR archive containing all 4 groups (a/b/c/d) of 12 pads
    each, plus a settings file and patterns directory.

    Group C is configured per PAD_SPEC; other groups get default (blank)
    pad records assigned to slot 0 (no sample).
    """
    tar_buffer = BytesIO()

    with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
        # Group C — the test pads
        for pad_num, bpm, frac_start, frac_end in PAD_SPEC:
            sample_slot = 100 + (pad_num - 1)  # slots 100..111
            loopstart = int(audio_frame_count * frac_start)
            loopend = int(audio_frame_count * frac_end)

            record = create_pad_record(
                sample_slot=sample_slot,
                bpm=bpm,
                loopstart=loopstart,
                loopend=loopend,
            )

            info = tarfile.TarInfo(name=f'pads/c/p{pad_num:02d}')
            info.size = len(record)
            tar.addfile(info, BytesIO(record))

        # Groups A, B, D — empty placeholder pads (slot 0 = no sample)
        for group in ['a', 'b', 'd']:
            for pad_num in range(1, 13):
                record = create_pad_record(sample_slot=0)
                info = tarfile.TarInfo(name=f'pads/{group}/p{pad_num:02d}')
                info.size = len(record)
                tar.addfile(info, BytesIO(record))

        # Settings file (222 zero bytes — minimal valid)
        settings = bytes(222)
        info = tarfile.TarInfo(name='settings')
        info.size = len(settings)
        tar.addfile(info, BytesIO(settings))

        # Empty patterns directory
        info = tarfile.TarInfo(name='patterns/')
        info.type = tarfile.DIRTYPE
        tar.addfile(info)

    return tar_buffer.getvalue()


def create_ppak(audio_path, output_path, device_sku='TE032AS001'):
    """Create the complete .ppak file."""

    # Read audio file
    with open(audio_path, 'rb') as f:
        audio_data = f.read()

    audio_frames = get_audio_frame_count(audio_path)
    audio_filename = Path(audio_path).stem  # without extension

    print(f"Audio file: {audio_path}")
    print(f"  size: {len(audio_data):,} bytes")
    print(f"  frame count: {audio_frames:,}")
    print()

    # Build project TAR
    tar_data = create_project_tar(audio_frames)

    # Build meta.json
    meta = {
        "info": "teenage engineering - pak file",
        "pak_version": 1,
        "pak_type": "user",
        "pak_release": "1.2.0",
        "device_name": "EP-133",
        "device_sku": device_sku,
        "device_version": "2.0.5",
        "generated_at": "2026-04-24T00:00:00.000Z",
        "author": "ep133_bpm_writer",
        "base_sku": device_sku
    }

    # Build .ppak ZIP
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Project TAR — leading slash is CRITICAL
        info = zipfile.ZipInfo('/projects/P07.tar')
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, tar_data)

        # meta.json
        info = zipfile.ZipInfo('/meta.json')
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, json.dumps(meta, indent=2))

        # Audio file replicated as slots 100..111
        for slot in range(100, 112):
            info = zipfile.ZipInfo(f'/sounds/{slot:03d} {audio_filename}.wav')
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, audio_data)

    # Report
    print(f"✓ Created {output_path}")
    print()
    print("Group C pad layout:")
    print("  pad | BPM  | loop region        | encoding mode")
    print("  ----+------+--------------------+----------------")
    for pad_num, bpm, frac_start, frac_end in PAD_SPEC:
        if frac_start == 0.0 and frac_end == 1.0:
            region = "full sample"
        elif frac_start == 0.5:
            region = "last half"
        elif frac_start == 0.25:
            region = "middle"
        else:
            region = f"{frac_start:.0%}-{frac_end:.0%}"
        encoding = "low-range" if bpm < 128 else "high-range"
        print(f"   {pad_num:2d} | {bpm:4d} | {region:18s} | {encoding}")
    print()
    print("Next steps:")
    print(f"  1. Open EP Sample Tool in Chrome")
    print(f"  2. Drag {output_path} into the tool")
    print(f"  3. Upload to your EP-133")
    print(f"  4. Open Project 7 → Group C")
    print(f"  5. Listen for tempo differences between pads")
    print(f"  6. In Sample Tool waveform view: pads 1-4 full, 5-8 right half, 9-12 middle")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    audio_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else 'ep133_bpm_test.ppak'
    device_sku = sys.argv[3] if len(sys.argv) > 3 else 'TE032AS001'

    if not os.path.exists(audio_path):
        print(f"Error: {audio_path} not found", file=sys.stderr)
        sys.exit(1)

    if not audio_path.lower().endswith('.wav'):
        print(f"Warning: {audio_path} doesn't end in .wav — EP-133 may reject it", file=sys.stderr)

    try:
        create_ppak(audio_path, output_path, device_sku)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
