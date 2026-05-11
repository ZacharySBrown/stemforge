"""Target-agnostic scene-model helpers + schema.

Pure math used by the song-mode export pipeline, lifted out of the EP-133
exporter so future projectors (Koala, Chompi, MPC, ...) can share it. No
device-specific imports or types live here.

Public API split into two layers:

**Helpers** (re-exported from :mod:`.helpers`) — pure math:

- :func:`infer_bars` — pick a bar count for a clip given its duration + BPM.
- :func:`tile_event_positions` — fan out a sub-pattern slice across multiple
  triggers on a musically clean grid.
- :func:`scene_lengths_in_bars` — derive each scene's length in bars from a
  flat list of locator times.

Constants exposed for callers that need to assert behavior:
:data:`BARS_TOLERANCE_SEC`, :data:`BARS_CANDIDATES_SNAP`,
:data:`BARS_CANDIDATES_FALLBACK`, :data:`MAX_EVENTS_PER_PATTERN`,
:data:`MUSICAL_TRIGGER_COUNTS`.

**Schema** (re-exported from :mod:`.schema` and :mod:`.serialize`) — wire
format for the configurator's abstract scene model:

- :class:`Project` (alias :class:`ProjectSpec`), :class:`Song`,
  :class:`SceneSpec`, :class:`GroupSpec`, :class:`PadSpec`, :class:`ClipRef`.
- :func:`project_to_json`, :func:`project_from_json`,
  :func:`project_to_path`, :func:`project_from_path`.
- :data:`MAX_SONGS_V1` and the :data:`PlayMode` / :data:`StretchMode` /
  :data:`Provenance` literals.
"""

from .builders import GROUPS_DEFAULT, empty_project_from_manifest
from .format_profiles import RESOLUTIONS, AudioFormat
from .format_profiles import resolve as resolve_format_profile
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
from .schema import (
    MAX_SONGS_V1,
    ClipRef,
    FormatProfile,
    GroupSpec,
    PadSpec,
    PlayMode,
    Project,
    ProjectSpec,
    Provenance,
    SceneSpec,
    Song,
    StretchMode,
)
from .serialize import (
    project_from_json,
    project_from_path,
    project_to_json,
    project_to_path,
)

__all__ = [
    "BARS_CANDIDATES_FALLBACK",
    "BARS_CANDIDATES_SNAP",
    "BARS_TOLERANCE_SEC",
    "GROUPS_DEFAULT",
    "MAX_EVENTS_PER_PATTERN",
    "MAX_SONGS_V1",
    "MUSICAL_TRIGGER_COUNTS",
    "RESOLUTIONS",
    "AudioFormat",
    "ClipRef",
    "FormatProfile",
    "GroupSpec",
    "PadSpec",
    "PlayMode",
    "Project",
    "ProjectSpec",
    "Provenance",
    "SceneSpec",
    "Song",
    "StretchMode",
    "empty_project_from_manifest",
    "infer_bars",
    "project_from_json",
    "project_from_path",
    "project_to_json",
    "project_to_path",
    "resolve_format_profile",
    "scene_lengths_in_bars",
    "tile_event_positions",
]
