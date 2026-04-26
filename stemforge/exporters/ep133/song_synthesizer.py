"""Snapshot → PpakSpec synthesizer.

Turns a list of :class:`Snapshot` (from the resolver) into a :class:`PpakSpec`
ready for Track A's ``build_ppak()`` byte builder.

Algorithm:
- For every (group, pad, bars) tuple appearing in any snapshot, emit ONE
  :class:`Pattern` containing a single trigger event at position 0 over the
  whole pattern length. Patterns are deduped across snapshots.
- For every (group, pad) used, emit ONE :class:`PadSpec` carrying the sample
  slot from ``manifest.session_tracks``.
- For every snapshot, emit ONE :class:`SceneSpec` mapping each group to the
  pattern index it triggers (or 0 if silent).

See ``specs/ep133-arrangement-song-export.md`` §"Snapshot resolution algorithm"
+ §"Component contracts".
"""

from __future__ import annotations

from pathlib import Path

from .song_format import Event, PadSpec, Pattern, PpakSpec, SceneSpec
from .song_resolver import (
    ArrangementClip,
    GROUPS,
    Snapshot,
    _index_session_tracks,
    lookup_pad,
)


# EP-133 limits
MAX_SCENES = 99
MAX_PATTERNS_PER_GROUP = 99
MAX_PADS_PER_GROUP = 12

# Global sample-slot base. Per Zak's convention, song-export writes always
# land at slot 700+ so they don't clobber the user's 1..699 sample library.
# Each group gets a 20-slot window so manifest's per-group 0..19 indices
# stay isolated:
#   A → 700..719   B → 720..739   C → 740..759   D → 760..779
SAMPLE_SLOT_BASE = 700
SAMPLE_SLOT_PER_GROUP = 20
_GROUP_SLOT_OFFSET = {"a": 0, "b": 20, "c": 40, "d": 60}


def global_sample_slot(group: str, manifest_slot: int) -> int:
    """Map (group, per-group manifest slot) → global EP-133 sample slot."""
    g = group.lower()
    if g not in _GROUP_SLOT_OFFSET:
        raise ValueError(f"group must be one of a/b/c/d, got {group!r}")
    if not (0 <= manifest_slot < SAMPLE_SLOT_PER_GROUP):
        raise ValueError(
            f"manifest_slot must be 0..{SAMPLE_SLOT_PER_GROUP - 1}, "
            f"got {manifest_slot}"
        )
    return SAMPLE_SLOT_BASE + _GROUP_SLOT_OFFSET[g] + manifest_slot

# Pattern timing
TICKS_PER_BAR = 384

# Bars inference. The EP-133's time-stretch bar field accepts only
# {0.25, 0.5, 1, 2, 4} (per phones24 parsers.ts and Track A's writer
# validation). Longer clips snap to the 4-bar maximum and let the EP's
# stretch slow the playback to fit.
_BARS_TOLERANCE_SEC = 0.4
_BARS_CANDIDATES_SNAP = (1, 2, 4)
_BARS_CANDIDATES_FALLBACK = (1, 2, 4)


def infer_bars(clip_length_sec: float, project_bpm: float) -> int:
    """Pick the EP-133 ``time.bars`` value for a clip.

    Two-stage decision (matches the hybrid loader's ``detect_bars_value``):

    1. If the clip duration is within ±400ms of an integer bar count at
       project BPM, snap to that bar count (chosen from {1, 2, 4}).
    2. Otherwise pick the closest of {1, 2, 4} bars and let the EP's stretch
       absorb the difference.
    """
    if project_bpm <= 0:
        raise ValueError(f"project_bpm must be positive, got {project_bpm!r}")
    bar_dur_sec = 60.0 * 4.0 / project_bpm
    for bars in _BARS_CANDIDATES_SNAP:
        if abs(clip_length_sec - bars * bar_dur_sec) <= _BARS_TOLERANCE_SEC:
            return bars
    return min(
        _BARS_CANDIDATES_FALLBACK,
        key=lambda b: abs(clip_length_sec - b * bar_dur_sec),
    )


def _entry_for_path(manifest: dict, group: str, file_path: str) -> dict:
    session = manifest.get("session_tracks") or {}
    entries = session.get(group) or session.get(group.lower()) or []
    for entry in entries:
        path = entry.get("file_path") or entry.get("file")
        if path == file_path:
            return entry
    raise KeyError(
        f"no session_tracks entry for {file_path!r} on group {group!r}"
    )


def _wav_path_for_pad(manifest: dict, group: str, pad: int) -> Path:
    """Return the WAV path for the entry whose pad ( = slot + 1) matches."""
    session = manifest.get("session_tracks") or {}
    entries = session.get(group) or session.get(group.lower()) or []
    target_slot = pad - 1
    for entry in entries:
        if int(entry.get("slot", -1)) != target_slot:
            continue
        path = entry.get("file_path") or entry.get("file")
        if path is None:
            raise KeyError(
                f"session_tracks[{group}] slot={target_slot} has no file path"
            )
        return Path(path)
    raise KeyError(
        f"no session_tracks[{group}] entry for pad {pad} (slot {target_slot})"
    )


def synthesize(
    snapshots: list[Snapshot],
    manifest: dict,
    project_bpm: float,
    time_sig: tuple[int, int],
    project_slot: int,
) -> PpakSpec:
    """Convert resolver output into a :class:`PpakSpec`.

    - Patterns deduped by ``(group, pad, bars)``.
    - One :class:`PadSpec` per ``(group, pad)`` actually used.
    - One :class:`SceneSpec` per snapshot.
    - ``sounds`` maps ``sample_slot`` → wav path.

    ``sample_slot`` in this implementation is the manifest's ``slot`` value
    (the per-group 0-indexed position) — Track A's writer maps it to whatever
    on-device global slot scheme it uses. ``pad`` is the EP-133 pad number
    (1..12), computed as ``slot + 1`` per the spec.

    Raises ``ValueError`` if the snapshot list exceeds the EP-133's 99-scene
    limit, or if any group exceeds 99 distinct patterns / 12 pads.
    """
    if len(snapshots) > MAX_SCENES:
        raise ValueError(
            f"too many scenes ({len(snapshots)} > {MAX_SCENES}). EP-133 song "
            "mode supports at most 99 scenes — drop fewer locators."
        )
    if not (1 <= project_slot <= 9):
        raise ValueError(f"project_slot must be 1..9, got {project_slot!r}")

    # Force a manifest scan up-front so we fail fast on missing files.
    _index_session_tracks(manifest)

    pattern_indices: dict[tuple[str, int, int], int] = {}
    per_group_counts: dict[str, int] = {g.lower(): 0 for g in GROUPS}
    pad_records: dict[tuple[str, int], PadSpec] = {}

    def _ensure_pattern(group_lower: str, pad: int, bars: int) -> int:
        key = (group_lower, pad, bars)
        if key in pattern_indices:
            return pattern_indices[key]
        per_group_counts[group_lower] += 1
        if per_group_counts[group_lower] > MAX_PATTERNS_PER_GROUP:
            raise ValueError(
                f"group {group_lower!r} would emit "
                f"{per_group_counts[group_lower]} patterns "
                f"(> {MAX_PATTERNS_PER_GROUP} EP-133 limit)."
            )
        idx = per_group_counts[group_lower]
        pattern_indices[key] = idx
        return idx

    scenes: list[SceneSpec] = []

    for snap in snapshots:
        per_scene: dict[str, int] = {}
        for group in GROUPS:
            clip: ArrangementClip | None = snap.clip_for(group)
            if clip is None:
                per_scene[group.lower()] = 0
                continue
            pad = lookup_pad(manifest, group, clip.file_path)
            bars = infer_bars(clip.length_sec, project_bpm)
            idx = _ensure_pattern(group.lower(), pad, bars)
            per_scene[group.lower()] = idx
            pad_key = (group.lower(), pad)
            if pad_key not in pad_records:
                entry = _entry_for_path(manifest, group, clip.file_path)
                pad_records[pad_key] = PadSpec(
                    group=group.lower(),
                    pad=pad,
                    sample_slot=global_sample_slot(group, int(entry["slot"])),
                    play_mode="oneshot",
                    time_stretch_bars=bars,
                )

        scenes.append(
            SceneSpec(
                a=per_scene["a"],
                b=per_scene["b"],
                c=per_scene["c"],
                d=per_scene["d"],
            )
        )

    # Build patterns in deterministic order (insertion order of pattern_indices).
    patterns: list[Pattern] = []
    for (group_lower, pad, bars), idx in pattern_indices.items():
        patterns.append(
            Pattern(
                group=group_lower,
                index=idx,
                bars=bars,
                events=[
                    Event(
                        position_ticks=0,
                        pad=pad,
                        # Captured patterns ALL use note=60 (0x3c), vel=100
                        # (0x64). Duration is a short trigger (one-shot
                        # samples play their full length regardless); using
                        # full bars*TICKS_PER_BAR triggers ERR PATTERN.
                        note=60,
                        velocity=100,
                        duration_ticks=96,
                    )
                ],
            )
        )

    # Validate per-group pad count.
    per_group_pads: dict[str, set[int]] = {g.lower(): set() for g in GROUPS}
    for (group_lower, pad), _ in pad_records.items():
        per_group_pads[group_lower].add(pad)
    for group_lower, pads in per_group_pads.items():
        if len(pads) > MAX_PADS_PER_GROUP:
            raise ValueError(
                f"group {group_lower!r} uses {len(pads)} pads "
                f"(> {MAX_PADS_PER_GROUP} EP-133 limit)."
            )

    # Build sounds dict: sample_slot → wav path.
    sounds: dict[int, Path] = {}
    for (group_lower, pad), spec in pad_records.items():
        wav = _wav_path_for_pad(manifest, group_lower.upper(), pad)
        sounds[spec.sample_slot] = wav

    pads_sorted = sorted(pad_records.values(), key=lambda p: (p.group, p.pad))

    return PpakSpec(
        project_slot=project_slot,
        bpm=float(project_bpm),
        time_sig=(int(time_sig[0]), int(time_sig[1])),
        patterns=patterns,
        scenes=scenes,
        pads=pads_sorted,
        sounds=sounds,
    )
