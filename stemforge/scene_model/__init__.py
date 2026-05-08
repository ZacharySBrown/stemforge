"""Target-agnostic scene-model helpers.

Pure math used by the song-mode export pipeline, lifted out of the EP-133
exporter so future projectors (Koala, Chompi, MPC, ...) can share it. No
device-specific imports or types live here.

Public API (re-exported from :mod:`.helpers`):

- :func:`infer_bars` — pick a bar count for a clip given its duration + BPM.
- :func:`tile_event_positions` — fan out a sub-pattern slice across multiple
  triggers on a musically clean grid.
- :func:`scene_lengths_in_bars` — derive each scene's length in bars from a
  flat list of locator times.

Constants exposed for callers that need to assert behavior:
:data:`BARS_TOLERANCE_SEC`, :data:`BARS_CANDIDATES_SNAP`,
:data:`BARS_CANDIDATES_FALLBACK`, :data:`MAX_EVENTS_PER_PATTERN`,
:data:`MUSICAL_TRIGGER_COUNTS`.
"""

from .helpers import (
    BARS_CANDIDATES_FALLBACK,
    BARS_CANDIDATES_SNAP,
    BARS_TOLERANCE_SEC,
    MAX_EVENTS_PER_PATTERN,
    MUSICAL_TRIGGER_COUNTS,
    infer_bars,
    scene_lengths_in_bars,
    tile_event_positions,
)

__all__ = [
    "BARS_CANDIDATES_FALLBACK",
    "BARS_CANDIDATES_SNAP",
    "BARS_TOLERANCE_SEC",
    "MAX_EVENTS_PER_PATTERN",
    "MUSICAL_TRIGGER_COUNTS",
    "infer_bars",
    "scene_lengths_in_bars",
    "tile_event_positions",
]
