"""Generate a starter deck.yaml from a curated manifest.

Closes the workflow gap from Phase 2.5 COMMIT to Slice 2 build-deck:
takes a single manifest's ``session_tracks`` block (typically the
output of clicking COMMIT in the forge device), maps each group's
entries to the corresponding EP-133 group, and emits a deck plan
suitable for ``stemforge build-deck``.

Layout heuristic:
- session_tracks A → EP-133 group A, format_profile=vocal
- session_tracks B → EP-133 group B, format_profile=vocal
- session_tracks C → EP-133 group C, format_profile=drum
- session_tracks D → EP-133 group D, format_profile=texture

Each group takes its first 12 entries (slot-ordered) into pads 1..12.
**Spillover behavior:** if group A has >12 entries (the verse-swap
deck case where 14 vocals were curated onto track A in Live), the
overflow spills to group B's vacant pads (only when group B has fewer
than 12 entries of its own). Same mechanism for B→C, C→D in case the
user front-loaded one track.

The produced plan is a starting point — pad numbers, format profiles,
and project metadata are defaults the user is expected to tweak.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GROUPS_ORDER = ("A", "B", "C", "D")
DEFAULT_FORMAT_PROFILE: dict[str, str] = {
    "A": "vocal",
    "B": "vocal",
    "C": "drum",
    "D": "texture",
}
# Per-profile play_mode default. "key" (hold-to-play) is the right
# default for drum loops — tap and hold to drop the break in, release to
# cut. Vocals stay "oneshot" so a verse plays through after one tap.
# Texture defaults to oneshot for the same reason.
DEFAULT_PLAY_MODE: dict[str, str] = {
    "vocal": "oneshot",
    "drum": "key",
    "texture": "oneshot",
    "preserve_source": "oneshot",
}
PADS_PER_GROUP = 12


#: Valid format-profile names accepted by the ``--profile`` / ``--all-drum``
#: CLI flags. Kept in sync with the keys of :data:`DEFAULT_PLAY_MODE` so the
#: caller can't pick a profile we don't know how to map to a play_mode.
ALLOWED_FORMAT_PROFILES: tuple[str, ...] = ("vocal", "drum", "texture", "preserve_source")

#: Valid play-mode names accepted by the ``--play-mode`` CLI flag.
ALLOWED_PLAY_MODES: tuple[str, ...] = ("oneshot", "key", "loop")


def deck_from_manifest(
    manifest: dict,
    manifest_path: Path,
    *,
    project_name: str = "deck_v1",
    project_slot: int = 1,
    project_bpm: float | None = None,
    time_sig: tuple[int, int] = (4, 4),
    force_format_profile: str | None = None,
    force_play_mode: str | None = None,
) -> dict[str, Any]:
    """Build a deck-plan dict from a curated manifest.

    Returns a dict suitable for serializing to YAML or JSON and feeding
    back into ``stemforge build-deck``. The CLI wraps this with file I/O
    + Rich console output.

    Parameters
    ----------
    force_format_profile :
        If set, override the per-group default in
        :data:`DEFAULT_FORMAT_PROFILE` with this value for every group.
        Must be one of :data:`ALLOWED_FORMAT_PROFILES`. Use case:
        the breaks-n-beats build wanted ``drum`` everywhere instead of
        the default vocal/drum/texture mix — historically a regex patch.
    force_play_mode :
        If set, override the per-profile play_mode default
        (:data:`DEFAULT_PLAY_MODE`) with this value on every pad row.
        Must be one of :data:`ALLOWED_PLAY_MODES`. Independent of
        ``force_format_profile`` so a caller can keep heterogeneous
        format profiles but uniformly switch e.g. all-key playback.
    """
    if force_format_profile is not None and force_format_profile not in ALLOWED_FORMAT_PROFILES:
        raise ValueError(
            f"force_format_profile={force_format_profile!r} not in {ALLOWED_FORMAT_PROFILES!r}"
        )
    if force_play_mode is not None and force_play_mode not in ALLOWED_PLAY_MODES:
        raise ValueError(f"force_play_mode={force_play_mode!r} not in {ALLOWED_PLAY_MODES!r}")
    if project_bpm is None:
        raw = manifest.get("bpm")
        try:
            project_bpm = float(raw) if raw is not None else 92.0
        except (TypeError, ValueError):
            project_bpm = 92.0

    manifest_ref = str(manifest_path)
    session = manifest.get("session_tracks") or {}
    entries_by_group: dict[str, list[dict]] = {}
    for g in GROUPS_ORDER:
        entries = session.get(g) or session.get(g.lower()) or []
        entries_by_group[g] = sorted(entries, key=lambda e: int(e.get("slot", 0)))

    # Spill overflow forward: A→B→C→D. Only spill into a group whose
    # entry count is below 12, and only fill up to 12 total per group.
    spilled = _spill_forward(entries_by_group)

    groups_block: dict[str, dict[str, Any]] = {}
    for g in GROUPS_ORDER:
        entries = spilled[g]
        if not entries:
            # Skip empty groups in the output — keeps the deck.yaml
            # tight and the user can add the group back if they want.
            continue
        profile = force_format_profile or DEFAULT_FORMAT_PROFILE[g]
        play_mode = force_play_mode or DEFAULT_PLAY_MODE[profile]
        pads = []
        for pad_idx, item in enumerate(entries[:PADS_PER_GROUP], start=1):
            entry = item["entry"]
            origin_group = item["origin_group"]
            row: dict[str, Any] = {
                "pad": pad_idx,
                "source": manifest_ref,
                "clip": f"slot:{int(entry.get('slot', pad_idx - 1))}",
                "group": origin_group,
                "play_mode": play_mode,
            }
            name = entry.get("name")
            if name:
                row["name"] = name
            # 2026-05-11: propagate per-clip source_bpm from the M4L bounce.
            # The M4L captures each clip's warp_bpm BEFORE crop and writes
            # it into the manifest entry; we thread it through to the deck
            # row so deck_plan / kit_synthesizer get an exact value instead
            # of inferring from sample duration. Inference still kicks in
            # as a fallback for entries that pre-date the M4L change.
            source_bpm = entry.get("source_bpm")
            if isinstance(source_bpm, (int, float)) and source_bpm > 0:
                row["source_bpm"] = float(source_bpm)
            pads.append(row)
        groups_block[g] = {
            "format_profile": profile,
            "pads": pads,
        }

    return {
        "project": project_name,
        "project_slot": project_slot,
        "project_bpm": project_bpm,
        "time_sig": list(time_sig),
        "groups": groups_block,
    }


def _spill_forward(
    entries_by_group: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Distribute group entries into 12-pad buckets, spilling forward.

    Each output entry remembers its ``origin_group`` so the deck plan's
    ``clip: slot:N`` selector still resolves against the correct
    session_tracks group in the manifest. Without that, a vocal that
    started on track A but spilled to group B would fail to look up.

    Anything still pending after group D is dropped — there's no more
    capacity. Caller surfaces the truncation via input/output counts.
    """
    result: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUPS_ORDER}
    pending: list[dict[str, Any]] = []
    for g in GROUPS_ORDER:
        # 1) Drain pending spill into this group up to its cap.
        while pending and len(result[g]) < PADS_PER_GROUP:
            result[g].append(pending.pop(0))
        # 2) Consume this group's own entries; overflow goes to pending.
        for entry in entries_by_group[g]:
            item = {"entry": entry, "origin_group": g}
            if len(result[g]) < PADS_PER_GROUP:
                result[g].append(item)
            else:
                pending.append(item)
    return result


def to_yaml_string(plan: dict) -> str:
    """Serialize a deck plan to YAML (with sane formatting)."""
    import yaml  # type: ignore[import-untyped]

    return yaml.safe_dump(
        plan,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )


def to_json_string(plan: dict) -> str:
    """Serialize a deck plan to JSON (always available, no extra dep)."""
    return json.dumps(plan, indent=2)


__all__ = [
    "ALLOWED_FORMAT_PROFILES",
    "ALLOWED_PLAY_MODES",
    "DEFAULT_FORMAT_PROFILE",
    "DEFAULT_PLAY_MODE",
    "GROUPS_ORDER",
    "PADS_PER_GROUP",
    "deck_from_manifest",
    "to_json_string",
    "to_yaml_string",
]
