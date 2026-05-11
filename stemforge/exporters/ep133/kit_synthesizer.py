"""Kit projection — single-scene Workflow B path for the EP-133.

The ``song_synthesizer`` path consumes ``(snapshots, manifest)`` derived
from one Live arrangement + one forge run; it emits a multi-scene
``.ppak`` where each scene corresponds to one locator-bounded section.

The kit path is shaped for the verse-swap deck use case (configurator
spec v4 Decision 12, Workflow B): N source manifests, one default
"kit" scene, every assigned pad fires its sample at scene launch.
There is no song structure — just a 4 × 12 pad bank.

Inputs:
  - :class:`Project` — a single-song project whose
    ``project.songs[0].groups[*].pads`` carries the deck. Each
    ``PadSpec.clip`` references an audio clip by ``audio_hash`` (and a
    ``path`` hint for resolution).
  - :class:`ClipIndex` — federated resolver that turns the abstract
    clip refs into on-disk WAV paths, durations, and BPM hints.
  - ``project_slot``, ``project_bpm`` — explicit args (per the existing
    projector contract; ``project_bpm`` overrides
    ``project.songs[0].bpm`` if both are set).

Output: a :class:`PpakSpec` ready for ``build_ppak``. Per-group
``format_profile`` is honored by the projector layer (see
``apply_group_format_to_spec``); this module emits the slots and
patterns.

Pattern shape per pad:
  - Each pad fires once at position 0 of a 1-bar pattern. Tempo
    stretching makes the playback length scale with project BPM —
    appropriate for both verses (long, full-bar) and one-shots
    (short, retriggered manually).
  - ``stretch_mode`` is taken from ``PadSpec.stretch_mode``, which
    defaults to ``"bpm"`` per the schema. Vocals at ``bpm`` mode get
    their per-pad ``sound_bpm`` from ``ClipRef.source_bpm``;
    one-shot pads should set ``stretch_mode="none"`` (today's schema
    accepts ``"bpm"``/``"bar"``/``"none"`` — the kit synthesizer maps
    these onto the writer's vocabulary below).
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from stemforge.scene_model import Project

from .clip_index import ClipIndex
from .song_format import (
    Event,
    PadSpec as PpakPadSpec,
    Pattern,
    PpakSpec,
    SceneSpec as PpakSceneSpec,
)
from .song_synthesizer import (
    MAX_PADS_PER_GROUP,
    MAX_SCENES,
    global_sample_slot,
)

GROUPS = ("a", "b", "c", "d")

# Single default scene for Workflow B kits — every pad fires from
# position 0. Per Decision 12 the scene strip is collapsible in the UI
# when only one scene exists; the build-deck CLI emits exactly one.
KIT_SCENE_BARS = 1
KIT_SCENE_NAME = "kit"

# Per-sample length cap. Verified 2026-05-11: 21.36s sample broke Sample Tool's
# import on the 21-pad breaks-n-beats deck (loaded ~10 of 21 then aborted);
# an 11.30s sample loaded cleanly. The device's documented cap is ~20s/sample.
# Pipeline skips pads whose source exceeds this and warns the caller.
_MAX_SAMPLE_SEC = 20.0


def _stretch_mode_for_writer(schema_value: str) -> str:
    """Map abstract :data:`StretchMode` onto the writer's vocabulary."""
    # Schema literal is "none" | "bar" | "bpm"; writer takes
    # "none" | "bars" | "bpm" (note plural). One-letter fix.
    if schema_value == "bar":
        return "bars"
    return schema_value


def _read_source_duration_sec(path: Path) -> float | None:
    """Return audio duration in seconds for a WAV or AIFF, or None on failure.

    Lightweight header-only parse — avoids loading the full audio.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 44:
        return None
    if data[:4] == b"FORM" and data[8:12] in (b"AIFF", b"AIFC"):
        # AIFF/AIFC: walk chunks for COMM (filed in big-endian).
        pos = 12
        while pos + 8 <= len(data):
            cid = data[pos : pos + 4]
            csize = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
            if cid == b"COMM":
                # COMM: channels(2) + nframes(4) + bw(2) + sample_rate(10 IEEE-80)
                nframes = struct.unpack(">I", data[pos + 8 + 2 : pos + 8 + 6])[0]
                sr_bytes = data[pos + 8 + 8 : pos + 8 + 18]
                # Decode 80-bit IEEE extended float (sample rate is always positive int)
                exp = ((sr_bytes[0] & 0x7F) << 8) | sr_bytes[1]
                mantissa = int.from_bytes(sr_bytes[2:10], "big")
                if exp == 0 and mantissa == 0:
                    return None
                sr = int(mantissa / (1 << (63 - (exp - 16383))))
                if sr <= 0 or nframes <= 0:
                    return None
                return nframes / sr
            pos += 8 + csize
            if csize % 2:
                pos += 1
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        # WAV: read fmt + data chunks. Use wave for plain PCM, fall back to
        # raw struct parse for float-encoded WAVs (Live's bounce output).
        try:
            with wave.open(str(path), "rb") as wf:
                return wf.getnframes() / wf.getframerate()
        except wave.Error:
            fmt_pos = data.find(b"fmt ")
            if fmt_pos < 0:
                return None
            _, channels, sr, _, block_align, _ = struct.unpack(
                "<HHIIHH", data[fmt_pos + 8 : fmt_pos + 24]
            )
            data_pos = data.find(b"data")
            if data_pos < 0:
                return None
            data_size = struct.unpack("<I", data[data_pos + 4 : data_pos + 8])[0]
            if not block_align:
                return None
            return (data_size // block_align) / sr
    return None


# Plausible loop bar counts to consider when inferring source BPM. Power-of-2
# values cover most drum/texture loops; 3 is included for the real-but-rarer
# 3-bar phrase (turnarounds, intro tags, atmospheric textures). 5/6/7 are
# deliberately excluded — they're vanishingly rare and they steal scoring
# wins from the right 4-bar interpretation on long pads (see 2026-05-11
# audit: an 11.29s 4-bar @ 85 BPM oll texture was misclassified as 5-bar
# @ 106 BPM when 5 was a candidate).
_BAR_CANDIDATES = (0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 8.0)


def _infer_source_bpm(path: Path, target_bpm: float) -> float:
    """Snap a source file's duration to the bar count that lands closest to
    ``target_bpm`` (typically the project tempo).

    Assumes the source contains an integer-bar loop. Computes
    ``bpm = n_bars * 240 / duration_sec`` for each candidate n and picks
    the one whose resulting BPM is closest to ``target_bpm`` AND lies in
    the device-accepted 1..200 range.

    Why ``target_bpm`` rather than a hardcoded "near 100"? Because clips
    from a session typically have source tempos close to the session tempo,
    so this disambiguates ambiguous durations (e.g. 7.33s is 3 bars at
    98 BPM or 4 bars at 131 BPM — picking the closer-to-target wins).

    Returns 0.0 if the file is unreadable or no candidate fits the device's
    BPM range. Callers should treat 0.0 as "couldn't infer, use fallback".

    The fix that made this necessary: ``clip.call("crop")`` in Ableton
    renders each clip at its OWN ``warp_bpm``, not at the project tempo.
    The manifest's ``end_offset_sec`` is computed at project tempo, so
    blindly trusting it truncates clips whose warp_bpm differs. Inferring
    from the file's actual duration sidesteps both bugs.
    """
    dur = _read_source_duration_sec(path)
    if dur is None or dur <= 0:
        return 0.0
    if target_bpm <= 0:
        target_bpm = 100.0  # neutral target if no project hint available
    best = None
    for n in _BAR_CANDIDATES:
        bpm = n * 240.0 / dur
        if 50.0 <= bpm <= 200.0:
            score = abs(bpm - target_bpm)
            if best is None or score < best[0]:
                best = (score, bpm)
    if best is None:
        return 0.0
    return round(best[1], 2)


def synthesize_kit(
    project: Project,
    clip_index: ClipIndex,
    *,
    project_slot: int,
) -> PpakSpec:
    """Build a single-scene :class:`PpakSpec` for a Workflow B deck.

    Walks ``project.songs[0]``; for each pad with a non-null
    :class:`ClipRef`, resolves to disk via the :class:`ClipIndex`,
    allocates a sample slot under the group's namespace, and emits a
    one-event 1-bar pattern. Returns a single scene wired to fire
    every populated group.

    Validation:
      - exactly one song (v1 advisory).
      - per-group pad count ≤ ``MAX_PADS_PER_GROUP`` (12).
      - ``project_slot`` ∈ 1..9.

    Memory budget is computed by the projector caller, not here — this
    module produces the spec; the projector decides whether to abort.
    """
    if len(project.songs) != 1:
        raise ValueError(f"synthesize_kit requires exactly 1 song, got {len(project.songs)}")
    if not (1 <= project_slot <= 9):
        raise ValueError(f"project_slot must be 1..9, got {project_slot!r}")
    song = project.songs[0]
    project_bpm = float(song.bpm)
    time_sig = (int(song.time_sig[0]), int(song.time_sig[1]))

    # One scene, one pattern per populated pad. Pattern indices are
    # allocated per group, starting at 1; scene references each
    # group's pattern (or a per-group empty marker if silent).
    pattern_indices: dict[tuple[str, int], int] = {}  # (group, pad) → idx
    per_group_pattern_count: dict[str, int] = {g: 0 for g in GROUPS}
    pad_records: list[PpakPadSpec] = []
    sounds: dict[int, Path] = {}
    slot_slices: dict[int, tuple[float, float]] = {}
    slot_play_mode: dict[int, str] = {}
    per_scene: dict[str, int] = {g: 0 for g in GROUPS}

    for group in song.groups:
        group_letter = group.group_id.lower()
        if group_letter not in GROUPS:
            raise ValueError(f"unknown group {group.group_id!r}; expected one of {GROUPS}")
        if len(group.pads) > MAX_PADS_PER_GROUP:
            raise ValueError(
                f"group {group.group_id!r} has {len(group.pads)} pads "
                f"> EP-133 limit of {MAX_PADS_PER_GROUP}."
            )
        for pad in group.pads:
            clip = pad.clip
            if clip is None:
                continue
            try:
                pad_num = int(pad.pad_id)
            except ValueError as e:
                raise ValueError(
                    f"pad_id must be an integer for the EP-133 kit projector "
                    f"(got {pad.pad_id!r} on group {group.group_id!r})"
                ) from e
            if not (1 <= pad_num <= MAX_PADS_PER_GROUP):
                raise ValueError(
                    f"pad_id {pad_num} out of EP-133 range 1..{MAX_PADS_PER_GROUP} "
                    f"(group {group.group_id!r})"
                )
            resolved = _resolve_clip(clip, clip_index)

            # Skip pads whose source audio exceeds the EP-133's per-sample
            # cap. Empirical limit verified 2026-05-11: a 21.36s sample
            # broke the Sample Tool import (loaded ~10 pads then aborted);
            # an 11.30s sample loaded fine. Per the user's recollection
            # the device documents a 20s/pad ceiling. Skip with a warning
            # rather than truncate — truncation would silently drop the
            # tail and produce off-bar loops.
            dur_sec = _read_source_duration_sec(Path(resolved.path))
            if dur_sec is not None and dur_sec > _MAX_SAMPLE_SEC:
                import warnings

                warnings.warn(
                    f"pad {group_letter}/p{pad_num:02d}: source "
                    f"{Path(resolved.path).name!r} is {dur_sec:.2f}s, "
                    f"exceeds EP-133's {_MAX_SAMPLE_SEC}s per-sample cap. "
                    f"Pad will be omitted from the kit. Shorten the source "
                    f"in Live or split into multiple shorter clips.",
                    UserWarning,
                    stacklevel=2,
                )
                continue

            slot_index = pad_num - 1
            sample_slot = global_sample_slot(group_letter, slot_index)
            sounds[sample_slot] = resolved.path
            # Tag the slot's WAV TNGE metadata to match the pad record's
            # play mode so the device's coupled fields stay consistent.
            slot_play_mode[sample_slot] = pad.play_mode

            # NOTE 2026-05-11: slot_slices used to mirror song_synthesizer
            # by taking the manifest's start_offset_sec/end_offset_sec as a
            # source-file slice. That truncated bounced clips whose
            # warp_bpm differed from project_bpm — the M4L computes
            # end_offset_sec at project tempo while clip.call("crop")
            # renders at warp_bpm, so the seconds don't line up. For the
            # kit/bounced workflow we now use the FULL source file and
            # let _infer_source_bpm derive the per-clip BPM from its
            # actual duration. If a future explicit-slice workflow needs
            # it back, gate it behind a deck.yaml flag rather than
            # blanket-trusting the manifest.

            per_group_pattern_count[group_letter] += 1
            idx = per_group_pattern_count[group_letter]
            if idx > MAX_SCENES:
                raise ValueError(
                    f"group {group_letter!r} would emit {idx} patterns "
                    f"(> {MAX_SCENES} EP-133 per-group limit)."
                )
            pattern_indices[(group_letter, pad_num)] = idx

            stretch_mode_writer = _stretch_mode_for_writer(pad.stretch_mode)
            sound_bpm: float | None = None
            if stretch_mode_writer == "bpm":
                # Per-clip BPM precedence (2026-05-11 reordering):
                #   1. explicit clip.source_bpm from the deck spec — only
                #      set when the user/upstream knows it precisely
                #   2. inferred from the source file's actual duration
                #      (snap to integer bars) — the right answer for the
                #      bounced workflow where clip.call("crop") renders
                #      each clip at its warp_bpm, NOT project_bpm
                #   3. ClipIndex's resolved.bpm — only useful as a fallback
                #      because it's often just the manifest's global bpm
                #      (= project_bpm), which is wrong per-clip
                #   4. project_bpm as a last-ditch fallback
                if clip.source_bpm is not None:
                    sound_bpm = float(clip.source_bpm)
                else:
                    # Pass project_bpm as the target so ambiguous durations
                    # (e.g. 7.33s could be 3 bars @ 98 or 4 bars @ 131) snap
                    # to the bar count nearer the session tempo.
                    inferred = _infer_source_bpm(Path(resolved.path), project_bpm)
                    if inferred > 0:
                        sound_bpm = inferred
                    elif resolved.bpm is not None:
                        sound_bpm = float(resolved.bpm)
                    else:
                        sound_bpm = project_bpm
                # Clamp to device-accepted range (PROTOCOL.md §5).
                sound_bpm = max(1.0, min(200.0, round(sound_bpm, 2)))

            pad_records.append(
                PpakPadSpec(
                    group=group_letter,
                    pad=pad_num,
                    sample_slot=sample_slot,
                    play_mode=pad.play_mode,
                    time_stretch_bars=pad.bars or KIT_SCENE_BARS,
                    stretch_mode=stretch_mode_writer,
                    sound_bpm=sound_bpm,
                )
            )

    # Build patterns: one event per pattern, fired at position 0.
    patterns: list[Pattern] = []
    for (group_letter, pad_num), idx in pattern_indices.items():
        events = [
            Event(
                position_ticks=0,
                pad=pad_num,
                note=60,
                velocity=100,
                duration_ticks=96,
            )
        ]
        patterns.append(
            Pattern(
                group=group_letter,
                index=idx,
                bars=KIT_SCENE_BARS,
                events=events,
            )
        )

    # Single kit scene. Each group's chunk references its first pattern
    # (pattern index 1) — the kit "scene" launches all groups
    # simultaneously; individual pads are then triggered manually by
    # the performer.
    #
    # Empty-pattern markers: groups with zero pads need a marker so the
    # device's scene-length rule doesn't truncate everything to 0.
    # We allocate from index 99 down per song_synthesizer's convention.
    empty_marker_idx = 99
    for group_letter in GROUPS:
        if per_group_pattern_count[group_letter] > 0:
            per_scene[group_letter] = 1  # first real pattern
        else:
            per_scene[group_letter] = empty_marker_idx
            patterns.append(
                Pattern(
                    group=group_letter,
                    index=empty_marker_idx,
                    bars=KIT_SCENE_BARS,
                    events=[],
                )
            )

    scenes = [
        PpakSceneSpec(
            a=per_scene["a"],
            b=per_scene["b"],
            c=per_scene["c"],
            d=per_scene["d"],
        )
    ]

    pads_sorted = sorted(pad_records, key=lambda p: (p.group, p.pad))

    return PpakSpec(
        project_slot=project_slot,
        bpm=project_bpm,
        time_sig=time_sig,
        patterns=patterns,
        scenes=scenes,
        pads=pads_sorted,
        sounds=sounds,
        song_positions=[1],
        slot_slices=slot_slices,
        slot_play_mode=slot_play_mode,
    )


def _resolve_clip(clip, clip_index: ClipIndex):
    """Resolve a :class:`ClipRef` to a :class:`ResolvedClip`.

    Prefers the path hint on the ClipRef (the deck-builder writes
    a path here). Falls back to error — hash-only resolution would
    require scanning every loaded manifest, which we punt to v2.
    """
    if clip.path is None:
        raise ValueError(
            f"ClipRef has no path hint; kit synthesizer can't hash-resolve "
            f"in v1 (audio_hash={clip.audio_hash!r})"
        )
    return clip_index.resolve_path(clip.path)


__all__ = ["KIT_SCENE_BARS", "KIT_SCENE_NAME", "synthesize_kit"]
