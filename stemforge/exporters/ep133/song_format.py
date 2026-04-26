"""EP-133 song-mode dataclass spec.

TODO: this is a placeholder authored by Track C while Track A is in flight.
Once Track A lands, delete the body of this module and re-export the canonical
dataclasses from there. Track A owns this file per
``docs/exec-plans/ep133-song-export.md``.

Shape matches ``specs/ep133-arrangement-song-export.md`` §"Component contracts".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Event:
    """One pattern trigger row (8 bytes on disk)."""
    position_ticks: int
    pad: int               # 1..12
    note: int              # MIDI 0..127 (60 = C4 = natural pitch)
    velocity: int          # 0..127
    duration_ticks: int


@dataclass
class Pattern:
    """One pattern file (``patterns/{group}/{index:02d}``)."""
    group: str             # 'a' | 'b' | 'c' | 'd'
    index: int             # 1..99
    bars: int
    events: list[Event] = field(default_factory=list)


@dataclass
class SceneSpec:
    """One scene row (one chunk in the ``scenes`` file)."""
    a: int                 # pattern index 1..99, or 0 = silent
    b: int
    c: int
    d: int


@dataclass
class PadSpec:
    """One pad config record (``pads/{group}/p{NN}``, 27 bytes on disk)."""
    group: str             # 'a' | 'b' | 'c' | 'd'
    pad: int               # 1..12
    sample_slot: int
    play_mode: str         # 'oneshot' | 'key' | 'legato'
    time_stretch_bars: int # 1, 2, or 4 (raw value before encoding)


@dataclass
class PpakSpec:
    """Top-level spec passed to ``build_ppak()`` (Track A)."""
    project_slot: int      # 1..9
    bpm: float
    time_sig: tuple[int, int]
    patterns: list[Pattern] = field(default_factory=list)
    scenes: list[SceneSpec] = field(default_factory=list)
    pads: list[PadSpec] = field(default_factory=list)
    sounds: dict[int, Path] = field(default_factory=dict)  # sample_slot → wav path
