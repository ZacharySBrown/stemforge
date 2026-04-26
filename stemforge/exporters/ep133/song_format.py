"""EP-133 K.O. II song-mode binary format builders.

Pure-byte builders for the four file types that live inside an EP-133
project TAR: ``patterns/{group}/{NN}``, ``scenes``, ``pads/{group}/p{NN}``,
and ``settings``.

Format references (see ``specs/ep133-arrangement-song-export.md`` for the
full spec including the bugs we work around in DannyDesert's
``create_ppak.py``):

- Read reference (canonical truth):
  ``~/repos/ep133-export-to-daw/src/lib/parsers.ts``
- Format spec: ``~/repos/ep133-export-to-daw/docs/EP133_FORMATS.md``

Every builder in this module returns ``bytes`` and is paired with an
in-Python parser in :mod:`tests.ep133.test_song_format` that mirrors the
phones24 read logic for round-trip validation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

# ----- Constants -------------------------------------------------------------

PATTERN_HEADER_SIZE = 4
PATTERN_EVENT_SIZE = 8
PATTERN_MAX_EVENTS = 255

SCENES_HEADER_SIZE = 7
SCENES_CHUNK_SIZE = 6
SCENES_MAX = 99

PAD_RECORD_SIZE = 27
SETTINGS_SIZE = 222

TICKS_PER_BAR = 384  # used by callers; not enforced inside builders

# Time-stretch bars encoding (parsers.ts: timeStretchBars())
#   raw 0   → 1 bar
#   raw 1   → 2 bars
#   raw 2   → 4 bars  (note: phones24 spec says raw==2; FORMATS.md said raw==3
#                       which appears to be a typo. parsers.ts is authoritative.)
#   raw 255 → 1/2 bar
#   raw 254 → 1/4 bar
TIME_STRETCH_BARS_ENCODING = {1: 0, 2: 1, 4: 2, 0.5: 255, 0.25: 254}

PLAY_MODE_ENCODING = {"oneshot": 0, "key": 1, "legato": 2}


# ----- Dataclasses -----------------------------------------------------------

@dataclass
class Event:
    """A single trigger event inside a pattern."""

    position_ticks: int      # 0 .. bars*TICKS_PER_BAR - 1 (uint16 LE)
    pad: int                 # 1..12 (encoded as pad*8 in byte 2)
    note: int                # MIDI 0..127 (60 = C4, natural pitch)
    velocity: int            # 0..127
    duration_ticks: int      # uint16 LE


@dataclass
class Pattern:
    """One pattern file: ``patterns/{group}/{index:02d}``."""

    group: str               # 'a' | 'b' | 'c' | 'd'
    index: int               # 1..99
    bars: int                # 1, 2, 4, ...
    events: list[Event] = field(default_factory=list)


@dataclass
class SceneSpec:
    """One scene row in the ``scenes`` file. Pattern index 0 = silent."""

    a: int                   # pattern index 1..99 or 0 (silent)
    b: int
    c: int
    d: int


@dataclass
class PadSpec:
    """One pad assignment that produces a ``pads/{group}/p{NN}`` file."""

    group: str               # 'a' | 'b' | 'c' | 'd'
    pad: int                 # 1..12
    sample_slot: int         # uint16 LE — sample-library slot
    play_mode: str           # 'oneshot' | 'key' | 'legato'
    time_stretch_bars: int   # 1, 2, or 4 (raw value before encoding)


@dataclass
class PpakSpec:
    """Top-level spec consumed by :func:`stemforge.exporters.ep133.ppak_writer.build_ppak`."""

    project_slot: int                # 1..9
    bpm: float
    time_sig: tuple[int, int]
    patterns: list[Pattern]
    scenes: list[SceneSpec]
    pads: list[PadSpec]
    sounds: dict[int, Path]          # sample_slot → wav file path


# ----- Pattern builder -------------------------------------------------------

def build_pattern(events: list[Event], bars: int) -> bytes:
    """Build one pattern file.

    Layout (verified against captured reference patterns):

    ====  =================================================================
    off   value
    ====  =================================================================
    0     0x00
    1     bars (uint8)
    2     event_count (uint8, max 255)
    3     0x00
    4..   event_count × 8-byte event records, each:
          [pos_lo, pos_hi, pad*8, note, velocity, dur_lo, dur_hi, flag]
          - position_ticks (uint16 LE) — bytes 0-1
          - pad*8 — byte 2 (so pad 1 = 0x08, pad 11 = 0x58)
          - note — byte 3 (always 0x3c = 60 = C4 in captured patterns)
          - velocity — byte 4 (always 0x64 = 100 in captured patterns)
          - duration_ticks (uint16 LE) — bytes 5-6
          - flag — byte 7 (mostly 0x00; sometimes 0x08 on last event)
    ====  =================================================================
    """
    if not (1 <= bars <= 255):
        raise ValueError(f"bars must be 1..255, got {bars}")
    if len(events) > PATTERN_MAX_EVENTS:
        raise ValueError(
            f"too many events: {len(events)} (max {PATTERN_MAX_EVENTS})"
        )

    out = bytearray()
    out.append(0x00)
    out.append(bars)
    out.append(len(events))
    out.append(0x00)

    for ev in sorted(events, key=lambda e: e.position_ticks):
        if not (0 <= ev.position_ticks <= 0xFFFF):
            raise ValueError(
                f"position_ticks out of uint16 range: {ev.position_ticks}"
            )
        if not (1 <= ev.pad <= 12):
            raise ValueError(f"pad must be 1..12, got {ev.pad}")
        if not (0 <= ev.note <= 127):
            raise ValueError(f"note must be 0..127, got {ev.note}")
        if not (0 <= ev.velocity <= 127):
            raise ValueError(f"velocity must be 0..127, got {ev.velocity}")
        if not (0 <= ev.duration_ticks <= 0xFFFF):
            raise ValueError(
                f"duration_ticks out of uint16 range: {ev.duration_ticks}"
            )

        out += struct.pack("<H", ev.position_ticks)
        # IMPORTANT: pad encoding in event is 0-indexed (file path is
        # 1-indexed). Verified against minimal reference where the "."
        # pad is stored at pads/{group}/p10 (1-indexed file 10) and
        # fires from event byte 0x48 (= 72 = 9 * 8 → 0-indexed pad 9).
        out.append((ev.pad - 1) * 8)
        out.append(ev.note)
        out.append(ev.velocity)
        out += struct.pack("<H", ev.duration_ticks)
        out.append(0x00)

    assert len(out) == PATTERN_HEADER_SIZE + len(events) * PATTERN_EVENT_SIZE
    return bytes(out)


# ----- Scenes builder --------------------------------------------------------

def build_scenes(scenes: list[SceneSpec], time_sig: tuple[int, int]) -> bytes:
    """Build the ``scenes`` file.

    Layout:

    ====  =================================================================
    off   value
    ====  =================================================================
    0..4  zero-fill (header padding)
    5     time-sig numerator   (FORMATS.md byte 5)
    6     time-sig denominator (FORMATS.md byte 6)
    7..   N × 6-byte scene chunks:
          [pat_a, pat_b, pat_c, pat_d, numerator, denominator]
    ====  =================================================================

    The per-scene numerator/denominator at chunk offsets 4-5 is what the
    device actually reads (see ``parsers.ts:collectScenesSettings`` —
    it reads bytes 11/12 of the file, which are bytes 4/5 of chunk 0).
    We emit the same numerator/denominator on every scene chunk for
    safety; phones24 confirms the device tolerates this.
    """
    if len(scenes) > SCENES_MAX:
        raise ValueError(f"too many scenes: {len(scenes)} (max {SCENES_MAX})")
    num, denom = time_sig
    if not (0 <= num <= 255) or not (0 <= denom <= 255):
        raise ValueError(f"time_sig values must fit in uint8: {time_sig}")

    # Device requires the scenes file to be a fixed 712 bytes, regardless of
    # how many scenes are populated:
    #   - 7-byte header (4 zero + numerator + denominator + ???=0)
    #   - 99 × 6-byte scene chunks (unused chunks zero-fill pat_a..pat_d but
    #     keep the per-chunk numerator/denominator at offsets 4-5)
    #   - 111-byte trailer (purpose: TBD; appears to hold "current scene" +
    #     song-mode metadata. Empty trailer = all zeros works for fresh
    #     exports.)
    #
    # Verified against captured minimal reference: 7 + 99*6 + 111 = 712.
    # An incomplete/short scenes file causes the device to error on load
    # ("ERR PATTERN ...").
    SCENES_TOTAL_SIZE = 712
    SCENES_TRAILER_SIZE = (
        SCENES_TOTAL_SIZE - SCENES_HEADER_SIZE - SCENES_MAX * 6
    )

    # Validate populated scenes
    for sc in scenes:
        for v, name in ((sc.a, "a"), (sc.b, "b"), (sc.c, "c"), (sc.d, "d")):
            if not (0 <= v <= 99):
                raise ValueError(
                    f"scene.{name} pattern index must be 0..99, got {v}"
                )

    out = bytearray(SCENES_HEADER_SIZE)
    out[5] = num
    out[6] = denom

    # Emit all 99 scene slots: populated ones first, then empty ones.
    for i in range(SCENES_MAX):
        if i < len(scenes):
            sc = scenes[i]
            out += bytes([sc.a, sc.b, sc.c, sc.d, num, denom])
        else:
            out += bytes([0, 0, 0, 0, num, denom])

    # Trailer (111 bytes). Two non-zero fields verified from the minimal
    # captured reference (which had 3 scenes populated):
    #   trailer[0..3]:  scene count, BIG-endian uint32
    #   trailer[11..12]: 01 01 (purpose TBD — possibly "song mode" flag +
    #                    "current scene"; safe to mirror the reference)
    # Zero-filling these caused "ERR SCENE 146" on load — device reads
    # past the populated chunks looking for a stop marker / count.
    trailer = bytearray(SCENES_TRAILER_SIZE)
    scene_count = len(scenes)
    trailer[0:4] = scene_count.to_bytes(4, "big")
    trailer[11] = 0x01
    trailer[12] = 0x01
    out += bytes(trailer)

    assert len(out) == SCENES_TOTAL_SIZE, (
        f"scenes file size {len(out)} != {SCENES_TOTAL_SIZE}"
    )
    return bytes(out)


# ----- Pad builder -----------------------------------------------------------

def build_pad(
    sample_slot: int,
    play_mode: str,
    time_stretch_bars: int,
    template: bytes | None = None,
    *,
    project_bpm: float | None = None,
) -> bytes:
    """Build a 27-byte pad record.

    Patches the four fields we own (sample_slot, time-stretch BPM if
    ``project_bpm`` given, time-stretch mode + bars, play_mode) into the
    template; everything else is preserved from the template (or zero-
    filled if no template).

    Args:
        sample_slot: uint16 LE at bytes 1..2 — sample library slot.
        play_mode:   one of 'oneshot' | 'key' | 'legato' (byte 23).
        time_stretch_bars: 1, 2, or 4 (raw bar count). Encoded at byte 25
            and byte 21 is forced to 2 (=BARS mode).
        template:    bytes-like, must be 27 bytes when provided. ``None``
            yields a zero-filled base.
        project_bpm: if given, written as float32 LE at bytes 12..15
            (matches the project's stretch-BPM target).
    """
    if template is None:
        data = bytearray(PAD_RECORD_SIZE)
    else:
        if len(template) != PAD_RECORD_SIZE:
            raise ValueError(
                f"pad template must be {PAD_RECORD_SIZE} bytes, got {len(template)}"
            )
        data = bytearray(template)

    if not (0 <= sample_slot <= 0xFFFF):
        raise ValueError(f"sample_slot must fit in uint16, got {sample_slot}")
    if play_mode not in PLAY_MODE_ENCODING:
        raise ValueError(
            f"play_mode must be one of {sorted(PLAY_MODE_ENCODING)}, got {play_mode!r}"
        )
    if time_stretch_bars not in TIME_STRETCH_BARS_ENCODING:
        raise ValueError(
            f"time_stretch_bars must be one of "
            f"{sorted(TIME_STRETCH_BARS_ENCODING)}, got {time_stretch_bars}"
        )

    # Bytes 1..2 — instrument number / sample slot
    struct.pack_into("<H", data, 1, sample_slot)

    # Bytes 12..15 — time-stretch BPM (float32 LE), only when supplied.
    if project_bpm is not None:
        struct.pack_into("<f", data, 12, float(project_bpm))

    # Byte 21 — time-stretch mode: 2 = BARS (since we're providing a bar count)
    data[21] = 2

    # Byte 23 — play mode
    data[23] = PLAY_MODE_ENCODING[play_mode]

    # Byte 25 — time-stretch bars (encoded)
    data[25] = TIME_STRETCH_BARS_ENCODING[time_stretch_bars]

    return bytes(data)


# ----- Settings builder ------------------------------------------------------

def build_settings(bpm: float, template: bytes) -> bytes:
    """Patch BPM into a 222-byte settings template.

    The settings file holds a lot of internal device state (per-group
    fader params, fader assignments, etc.) we don't fully understand.
    We MUST preserve every byte outside the BPM range — the spec is
    explicit about this.

    Bytes 4..7 hold the project BPM as float32 LE. Everything else in
    ``template`` is copied verbatim.
    """
    if len(template) != SETTINGS_SIZE:
        raise ValueError(
            f"settings template must be {SETTINGS_SIZE} bytes, got {len(template)}"
        )
    data = bytearray(template)
    struct.pack_into("<f", data, 4, float(bpm))
    return bytes(data)


# ----- Path helpers (used by the .ppak writer) -------------------------------

def pattern_filename(group: str, index: int) -> str:
    """``patterns/{group}{NN}`` — index zero-padded to 2 digits.

    NOTE: device uses NO slash between group letter and index (e.g.
    ``patterns/a01``, not ``patterns/a/01``). DannyDesert and the original
    spec docs both wrote ``patterns/{group}/{NN}`` — verified WRONG against
    a real captured backup; the device silently ignores nested-path entries
    and the patterns never play, leaving pads dark even though pad records
    correctly bind to samples.
    """
    if group not in {"a", "b", "c", "d"}:
        raise ValueError(f"group must be a|b|c|d, got {group!r}")
    if not (1 <= index <= 99):
        raise ValueError(f"index must be 1..99, got {index}")
    return f"patterns/{group}{index:02d}"


def pad_filename(group: str, pad: int) -> str:
    """``pads/{group}/p{NN}`` — pad zero-padded to 2 digits."""
    if group not in {"a", "b", "c", "d"}:
        raise ValueError(f"group must be a|b|c|d, got {group!r}")
    if not (1 <= pad <= 12):
        raise ValueError(f"pad must be 1..12, got {pad}")
    return f"pads/{group}/p{pad:02d}"
