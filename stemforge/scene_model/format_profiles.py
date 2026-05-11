"""Format profile → audio resolution mapping.

Per configurator spec v4 Decision 16: groups carry a `format_profile`
that drives sample-format choice at projection time. The abstract values
(channels, sample_rate, bit_depth) below are *target hints*; each
projector clamps them to its device's capability set.

For the EP-133 projector specifically, channels and bit-depth are locked
by hardware (always mono / 16-bit / 46875 Hz native). The lever that
actually moves storage size is `sample_rate_hz` — and the projector
clamps `sample_rate_hz` to ``EP133_SAMPLE_RATE`` so values above the
native rate produce native-rate output.

A `vocal` profile at 24 kHz halves storage versus the device default;
this is what makes the 24-verse hip-hop deck fit inside the 64 MB cap.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import FormatProfile


@dataclass(frozen=True)
class AudioFormat:
    """Abstract audio resolution: hint to projectors."""

    channels: int
    sample_rate_hz: int
    bit_depth: int


# Profile name → abstract resolution. Keep these as *hints*: the projector
# is the source of truth on what its device can actually represent.
RESOLUTIONS: dict[FormatProfile, AudioFormat] = {
    "vocal": AudioFormat(channels=1, sample_rate_hz=24000, bit_depth=16),
    "drum": AudioFormat(channels=2, sample_rate_hz=48000, bit_depth=16),
    "texture": AudioFormat(channels=2, sample_rate_hz=48000, bit_depth=16),
    "preserve_source": AudioFormat(channels=2, sample_rate_hz=48000, bit_depth=16),
}


def resolve(profile: FormatProfile) -> AudioFormat:
    """Resolve a profile to its abstract :class:`AudioFormat`."""
    return RESOLUTIONS[profile]


__all__ = [
    "RESOLUTIONS",
    "AudioFormat",
    "resolve",
]
