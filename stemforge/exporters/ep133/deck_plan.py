"""Deck-plan → :class:`Project` builder for the multi-source kit path.

The build-deck CLI reads a deck plan (YAML or JSON) describing one or
more groups × pads × clip references, then turns it into an abstract
:class:`Project` ready for the kit projector. This is the human-edited
shape of a verse-swap deck.

Plan shape:

.. code-block:: yaml

    project: "verse_swap_deck_v1"
    project_slot: 8
    project_bpm: 92
    time_sig: [4, 4]
    groups:
      A:
        format_profile: vocal
        pads:
          - {pad: 1, source: "songs/01_hey_mami/curated/manifest.json", clip: "vocals_v1"}
          - {pad: 2, path: "/abs/path/verse_2.wav", source_bpm: 88}
          - {pad: 3, source: "songs/02_benjamins/curated/manifest.json", group: A, clip: "slot:0"}
      B:
        format_profile: vocal
        pads: [...]
      C:
        format_profile: drum
        pads: [...]
      D:
        format_profile: texture
        pads: [...]

A pad row picks one of two reference shapes:

- ``source: <manifest>`` + ``clip: <selector>`` — resolve through a
  manifest's ``session_tracks`` block. Selector grammar is documented in
  :class:`stemforge.exporters.ep133.clip_index.ClipIndex`.
- ``path: <wav>`` — raw WAV reference. ``source_bpm`` may be supplied
  inline if the WAV doesn't carry it; otherwise the kit synthesizer
  falls back to the project's BPM (1× playback).

The loader is the single source of truth for the YAML/JSON shape; the
CLI wraps it with click args + Rich console output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stemforge.scene_model import (
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    Song,
)

from .clip_index import ClipIndex

# Per Decision 12 — the kit scene is single, named "kit" (or "Default";
# choose at popup time). Bars=1 because we don't know structure here.
_KIT_BARS = 1
_DEFAULT_PROJECT_BPM = 120.0
_DEFAULT_TIME_SIG = (4, 4)


def load_deck_plan(plan_path: Path) -> dict:
    """Load a deck plan from JSON (YAML support deferred — pyyaml optional)."""
    text = plan_path.read_text()
    if plan_path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ModuleNotFoundError as e:
            raise ModuleNotFoundError(
                "YAML deck plans require pyyaml. Install with `uv add pyyaml` or "
                "convert the plan to JSON."
            ) from e
        return yaml.safe_load(text)
    return json.loads(text)


def project_from_deck_plan(
    plan: dict,
    *,
    plan_dir: Path,
    clip_index: ClipIndex | None = None,
) -> tuple[Project, ClipIndex]:
    """Turn a deck-plan dict into an abstract :class:`Project` + populated index.

    Manifest paths in the plan are resolved relative to ``plan_dir``.
    Raw WAV paths may be absolute or relative to ``plan_dir``.

    Returns ``(project, clip_index)``. The clip index is loaded with every
    manifest the plan references; the kit projector consumes both.
    """
    project_name = str(plan.get("project") or "")
    project_bpm = float(plan.get("project_bpm", _DEFAULT_PROJECT_BPM))
    time_sig_raw = plan.get("time_sig") or list(_DEFAULT_TIME_SIG)
    time_sig = (int(time_sig_raw[0]), int(time_sig_raw[1]))

    if clip_index is None:
        clip_index = ClipIndex()

    plan_groups = plan.get("groups") or {}
    groups: list[GroupSpec] = []
    for group_letter, group_block in plan_groups.items():
        format_profile = str(group_block.get("format_profile", "preserve_source"))
        pads_block = group_block.get("pads") or []
        pad_specs: list[PadSpec] = []
        for pad_row in pads_block:
            pad_spec = _pad_spec_from_row(
                pad_row,
                group_letter=group_letter,
                plan_dir=plan_dir,
                clip_index=clip_index,
                project_bpm=project_bpm,
            )
            if pad_spec is not None:
                pad_specs.append(pad_spec)
        groups.append(
            GroupSpec(
                group_id=group_letter.upper(),
                pads=pad_specs,
                format_profile=format_profile,  # type: ignore[arg-type]
            )
        )

    project = Project(
        schema_version=2,
        name=project_name,
        songs=[
            Song(
                song_id="kit",
                name=project_name,
                bpm=project_bpm,
                time_sig=time_sig,
                groups=groups,
                scenes=[],  # kit synthesizer emits the single default scene
            )
        ],
    )
    return project, clip_index


def _pad_spec_from_row(
    row: dict[str, Any],
    *,
    group_letter: str,
    plan_dir: Path,
    clip_index: ClipIndex,
    project_bpm: float,
) -> PadSpec | None:
    pad_num = int(row["pad"])
    play_mode = str(row.get("play_mode", "oneshot"))
    stretch_mode = str(row.get("stretch_mode", "bpm"))
    bars = row.get("bars")

    raw_path = row.get("path")
    source = row.get("source")
    selector = row.get("clip")

    if raw_path is not None:
        wav = Path(raw_path).expanduser()
        if not wav.is_absolute():
            wav = (plan_dir / wav).resolve()
        else:
            wav = wav.resolve()
        resolved = clip_index.resolve_path(wav)
        # 2026-05-11: BPM precedence is per-clip → never manifest-global.
        #   1. row's explicit source_bpm (deck.yaml override)
        #   2. resolved.source_bpm (per-clip from manifest entry)
        #   3. None → kit_synthesizer infers from source duration
        # Don't fall back to resolved.bpm — that's the manifest's session
        # tempo, which is wrong per-clip.
        chosen_bpm = _coerce_float(row.get("source_bpm")) or resolved.source_bpm
        clip_ref = ClipRef(
            audio_hash=resolved.audio_hash,
            path=str(wav),
            source_bpm=chosen_bpm,
            name=row.get("name"),
        )
    elif source is not None and selector is not None:
        manifest_path = Path(source).expanduser()
        if not manifest_path.is_absolute():
            manifest_path = (plan_dir / manifest_path).resolve()
        clip_index.add_manifest(manifest_path)
        resolved = clip_index.resolve_manifest_clip(
            manifest_path,
            selector,
            group=row.get("group") or group_letter,
        )
        clip_kwargs: dict[str, Any] = {
            "audio_hash": resolved.audio_hash,
            "path": str(resolved.path),
            "source_song_id": row.get("source_song_id") or str(manifest_path.parent.name),
            "name": row.get("name") or resolved.name,
        }
        # ClipRef.start_offset_sec is a non-nullable float; only set when
        # the manifest carries one, otherwise the schema default (0.0) wins.
        start_off = _coerce_float(row.get("start_offset_sec")) or resolved.start_offset_sec
        if start_off is not None:
            clip_kwargs["start_offset_sec"] = start_off
        end_off = _coerce_float(row.get("end_offset_sec")) or resolved.end_offset_sec
        if end_off is not None:
            clip_kwargs["end_offset_sec"] = end_off
        if resolved.loop_start_sec is not None:
            clip_kwargs["loop_start_sec"] = resolved.loop_start_sec
        if resolved.loop_end_sec is not None:
            clip_kwargs["loop_end_sec"] = resolved.loop_end_sec
        # 2026-05-11: BPM precedence same as path-mode branch above —
        # explicit row value beats per-clip from manifest entry, never
        # fall back to manifest-global bpm (which is the session tempo).
        chosen_bpm = _coerce_float(row.get("source_bpm")) or resolved.source_bpm
        if chosen_bpm is not None:
            clip_kwargs["source_bpm"] = chosen_bpm
        clip_ref = ClipRef(**clip_kwargs)
    else:
        raise ValueError(
            f"pad {pad_num} on group {group_letter!r}: must specify either "
            f"`path:` or `source:` + `clip:` (got {row!r})"
        )

    return PadSpec(
        pad_id=str(pad_num),
        clip=clip_ref,
        play_mode=play_mode,  # type: ignore[arg-type]
        stretch_mode=stretch_mode,  # type: ignore[arg-type]
        bars=int(bars) if bars is not None else None,
    )


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["load_deck_plan", "project_from_deck_plan"]
