"""Memory-budget calculator + over-cap warning tests.

Per configurator spec v4 Decision 16: the projector estimates the
sample memory the project will consume and surfaces a warning when it
exceeds the device's 64 MB cap. The math is per-pad: duration × rate ×
2 bytes (mono 16-bit on EP-133).
"""

from __future__ import annotations

from stemforge.exporters.ep133.projector import (
    EP133_MEMORY_CAP_BYTES,
    Ep133Projector,
)
from stemforge.scene_model import (
    ClipRef,
    GroupSpec,
    PadSpec,
    Project,
    SceneSpec,
    Song,
)


def _pad_with_clip(pad_id: str, duration_sec: float) -> PadSpec:
    return PadSpec(
        pad_id=pad_id,
        clip=ClipRef(
            audio_hash="0" * 16,
            start_offset_sec=0.0,
            end_offset_sec=duration_sec,
        ),
    )


def _project_with_one_group(
    *,
    format_profile: str,
    pad_count: int,
    pad_duration_sec: float,
) -> Project:
    return Project(
        songs=[
            Song(
                song_id="s1",
                bpm=120.0,
                groups=[
                    GroupSpec(
                        group_id="A",
                        format_profile=format_profile,  # type: ignore[arg-type]
                        pads=[
                            _pad_with_clip(str(i + 1), pad_duration_sec) for i in range(pad_count)
                        ],
                    )
                ],
                scenes=[SceneSpec(scene_id="scn", bars=4)],
            )
        ]
    )


def test_estimate_zero_for_empty_project() -> None:
    p = Project(songs=[])
    assert Ep133Projector().estimate_memory_bytes(p) == 0


def test_estimate_zero_for_pads_without_clips() -> None:
    p = Project(
        songs=[
            Song(
                song_id="s",
                bpm=120,
                groups=[
                    GroupSpec(group_id="A", pads=[PadSpec(pad_id="1")]),
                ],
                scenes=[SceneSpec(scene_id="scn", bars=4)],
            )
        ]
    )
    assert Ep133Projector().estimate_memory_bytes(p) == 0


def test_preserve_source_uses_device_default_rate() -> None:
    """1 pad × 1 sec × 46875 Hz × 2 bytes = ~93750 bytes."""
    p = _project_with_one_group(
        format_profile="preserve_source",
        pad_count=1,
        pad_duration_sec=1.0,
    )
    bytes_used = Ep133Projector().estimate_memory_bytes(p)
    # Allow a few bytes of slack for int rounding.
    expected = int(1.0 * 46875 * 2)
    assert abs(bytes_used - expected) <= 2


def test_vocal_profile_uses_lower_rate() -> None:
    """Vocal at 24 kHz should be ~half of preserve_source."""
    full = Ep133Projector().estimate_memory_bytes(
        _project_with_one_group(format_profile="preserve_source", pad_count=1, pad_duration_sec=1.0)
    )
    vocal = Ep133Projector().estimate_memory_bytes(
        _project_with_one_group(format_profile="vocal", pad_count=1, pad_duration_sec=1.0)
    )
    assert vocal < full
    ratio = vocal / full
    # 24000 / 46875 = 0.512
    assert 0.45 < ratio < 0.6


def test_24_full_verses_at_preserve_source_exceeds_cap() -> None:
    """The motivating math from the v4 spec: 24 × 42-second verses at
    device-default rate is over the 64 MB cap."""
    p = _project_with_one_group(
        format_profile="preserve_source",
        pad_count=12,
        pad_duration_sec=42.0,
    )
    # 12 pads × 42s × 46875 × 2 ≈ 47.2 MB. Add another group to push over.
    p.songs[0].groups.append(
        GroupSpec(
            group_id="B",
            format_profile="preserve_source",
            pads=[_pad_with_clip(str(i + 1), 42.0) for i in range(12)],
        )
    )
    bytes_used = Ep133Projector().estimate_memory_bytes(p)
    assert bytes_used > EP133_MEMORY_CAP_BYTES, (
        f"24 × 42s preserve_source verses ({bytes_used / 1024 / 1024:.1f} MB) "
        f"should exceed 64 MB cap; if not, the math has changed"
    )


def test_24_full_verses_at_vocal_profile_fits() -> None:
    """Same 24 × 42s verses at vocal profile (24 kHz) fits the cap with margin."""
    p = _project_with_one_group(
        format_profile="vocal",
        pad_count=12,
        pad_duration_sec=42.0,
    )
    p.songs[0].groups.append(
        GroupSpec(
            group_id="B",
            format_profile="vocal",
            pads=[_pad_with_clip(str(i + 1), 42.0) for i in range(12)],
        )
    )
    bytes_used = Ep133Projector().estimate_memory_bytes(p)
    assert bytes_used < EP133_MEMORY_CAP_BYTES, (
        f"vocal-profile deck ({bytes_used / 1024 / 1024:.1f} MB) should fit cap"
    )
    # Headroom should be enough for groups C+D drum/synth content.
    headroom = EP133_MEMORY_CAP_BYTES - bytes_used
    assert headroom > 10 * 1024 * 1024, "want >10 MB headroom for groups C+D"


def test_validate_spec_warns_when_over_cap() -> None:
    p = _project_with_one_group(
        format_profile="preserve_source",
        pad_count=12,
        pad_duration_sec=200.0,  # absurdly long → way over cap
    )
    warnings = Ep133Projector().validate_spec(p)
    assert any("64 MB" in w for w in warnings), f"expected memory-cap warning, got: {warnings!r}"


def test_validate_spec_no_memory_warning_when_under_cap() -> None:
    p = _project_with_one_group(
        format_profile="vocal",
        pad_count=4,
        pad_duration_sec=10.0,
    )
    p.songs[0].scenes = [SceneSpec(scene_id="scn", bars=4)]
    warnings = Ep133Projector().validate_spec(p)
    assert not any("64 MB" in w for w in warnings)


def test_loop_region_takes_precedence_over_offsets() -> None:
    """When both loop_start/end and start/end_offset are present, loop
    duration is what the writer plays; the estimator must agree."""
    p = Project(
        songs=[
            Song(
                song_id="s",
                bpm=120,
                groups=[
                    GroupSpec(
                        group_id="A",
                        pads=[
                            PadSpec(
                                pad_id="1",
                                clip=ClipRef(
                                    audio_hash="0" * 16,
                                    start_offset_sec=0.0,
                                    end_offset_sec=10.0,
                                    loop_start_sec=2.0,
                                    loop_end_sec=4.0,  # 2-second loop
                                ),
                            )
                        ],
                    )
                ],
                scenes=[SceneSpec(scene_id="scn", bars=4)],
            )
        ]
    )
    bytes_used = Ep133Projector().estimate_memory_bytes(p)
    # Should reflect the 2-second loop, not the 10-second offset range.
    expected = int(2.0 * 46875 * 2)
    assert abs(bytes_used - expected) <= 2
