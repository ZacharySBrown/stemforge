"""Kit synthesizer tests — Workflow B single-scene EP-133 path."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from stemforge.exporters.ep133.clip_index import ClipIndex
from stemforge.exporters.ep133.kit_synthesizer import synthesize_kit
from stemforge.exporters.ep133.projector import Ep133Projector
from stemforge.exporters.ep133.song_synthesizer import (
    global_sample_slot,
)
from stemforge.scene_model import (
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    Song,
)


def _write_wav(path: Path, *, duration_sec: float = 0.5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(duration_sec * 22050)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * n)


def _project_with_pads(tmp_path: Path, *, group_pads: dict[str, dict[int, str]]) -> Project:
    """Build a Project with WAVs on disk for every requested pad."""
    groups = []
    for group_letter, pads_dict in group_pads.items():
        pads = []
        for pad_num, name in pads_dict.items():
            wav = tmp_path / group_letter.lower() / f"{name}.wav"
            _write_wav(wav)
            pads.append(
                PadSpec(
                    pad_id=str(pad_num),
                    clip=ClipRef(
                        audio_hash="0" * 16,
                        path=str(wav),
                        name=name,
                        source_bpm=92.0,
                    ),
                )
            )
        groups.append(GroupSpec(group_id=group_letter, pads=pads))

    return Project(
        songs=[
            Song(
                song_id="kit",
                bpm=92.0,
                groups=groups,
                scenes=[],
            )
        ]
    )


def test_kit_synthesizer_emits_single_scene(tmp_path: Path) -> None:
    project = _project_with_pads(tmp_path, group_pads={"A": {1: "v1"}})
    spec = synthesize_kit(project, ClipIndex(), project_slot=1)
    assert len(spec.scenes) == 1
    assert spec.song_positions == [1]


def test_kit_synthesizer_one_pattern_per_pad(tmp_path: Path) -> None:
    project = _project_with_pads(tmp_path, group_pads={"A": {1: "v1", 2: "v2", 3: "v3"}})
    spec = synthesize_kit(project, ClipIndex(), project_slot=1)
    real_patterns = [p for p in spec.patterns if p.events]
    assert len(real_patterns) == 3


def test_kit_synthesizer_global_slot_allocation(tmp_path: Path) -> None:
    project = _project_with_pads(tmp_path, group_pads={"A": {1: "a"}, "C": {1: "c"}})
    spec = synthesize_kit(project, ClipIndex(), project_slot=1)
    # Group A pad 1 → slot 700; Group C pad 1 → slot 740 per global_sample_slot.
    pads_by_group = {p.group: p.sample_slot for p in spec.pads}
    assert pads_by_group["a"] == global_sample_slot("a", 0)
    assert pads_by_group["c"] == global_sample_slot("c", 0)


def test_kit_synthesizer_silent_groups_get_empty_marker(tmp_path: Path) -> None:
    """Groups with no pads must still have a pattern reference in the
    scene chunk; we use the empty-marker convention from song_synthesizer."""
    project = _project_with_pads(tmp_path, group_pads={"A": {1: "v1"}})
    spec = synthesize_kit(project, ClipIndex(), project_slot=1)
    scene = spec.scenes[0]
    assert scene.a == 1
    assert scene.b == 99  # empty marker
    assert scene.c == 99
    assert scene.d == 99
    # And there should be empty patterns to back the markers.
    empty_patterns = [p for p in spec.patterns if not p.events]
    assert len(empty_patterns) == 3


def test_kit_synthesizer_rejects_invalid_pad_id(tmp_path: Path) -> None:
    project = _project_with_pads(tmp_path, group_pads={"A": {99: "x"}})
    with pytest.raises(ValueError, match="out of EP-133 range"):
        synthesize_kit(project, ClipIndex(), project_slot=1)


def test_kit_synthesizer_rejects_unknown_group(tmp_path: Path) -> None:
    project = _project_with_pads(tmp_path, group_pads={"X": {1: "x"}})
    with pytest.raises(ValueError, match="unknown group"):
        synthesize_kit(project, ClipIndex(), project_slot=1)


def test_kit_synthesizer_rejects_invalid_project_slot(tmp_path: Path) -> None:
    project = _project_with_pads(tmp_path, group_pads={"A": {1: "v1"}})
    with pytest.raises(ValueError, match="project_slot"):
        synthesize_kit(project, ClipIndex(), project_slot=10)


def test_kit_synthesizer_clip_without_path_raises(tmp_path: Path) -> None:
    """Hash-only resolution is v2; v1 requires the path hint."""
    project = Project(
        songs=[
            Song(
                song_id="kit",
                bpm=92.0,
                groups=[
                    GroupSpec(
                        group_id="A",
                        pads=[
                            PadSpec(
                                pad_id="1",
                                clip=ClipRef(audio_hash="abc1234567890def"),
                            )
                        ],
                    )
                ],
            )
        ]
    )
    with pytest.raises(ValueError, match="no path hint"):
        synthesize_kit(project, ClipIndex(), project_slot=1)


def test_project_kit_method_applies_format_profile(tmp_path: Path) -> None:
    """End-to-end: vocal profile should populate slot_sample_rate."""
    project = _project_with_pads(tmp_path, group_pads={"A": {1: "v1", 2: "v2"}})
    project.songs[0].groups[0].format_profile = "vocal"

    spec = Ep133Projector().synthesize_kit_spec(project, ClipIndex(), project_slot=1)
    # Both pads on group A should be tagged with the vocal rate (24000).
    a_slots = [
        global_sample_slot("a", 0),
        global_sample_slot("a", 1),
    ]
    for slot in a_slots:
        assert slot in spec.slot_sample_rate
        assert spec.slot_sample_rate[slot] == 24000


def test_project_kit_preserve_source_leaves_slot_sample_rate_empty(tmp_path: Path) -> None:
    project = _project_with_pads(tmp_path, group_pads={"A": {1: "v1"}})
    # default group profile is preserve_source.
    spec = Ep133Projector().synthesize_kit_spec(project, ClipIndex(), project_slot=1)
    assert spec.slot_sample_rate == {}
