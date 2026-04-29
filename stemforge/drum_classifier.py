"""
stemforge.drum_classifier — Classify extracted drum one-shots by type.

Spectral heuristic classifier that handles both acoustic and electronic
drums (808, 909, synth percussion). No ML dependencies — just numpy and
the spectral features already computed by oneshot.py.

Optional AST refinement when stemforge[analyzer] is installed.
"""

from __future__ import annotations

from .oneshot import OneshotProfile

# ── Classification categories ────────────────────────────────────────────

DRUM_TYPES = ["kick", "snare", "clap", "hat_closed", "hat_open", "rim", "perc"]

# Standard drum pad positions (kick bottom-left, snare above, hats right of snare)
DRUM_PAD_ORDER = [
    # Bottom row (R5 in quadrant): kick left, perc right
    "kick", "kick", "perc", "perc",
    # Top row (R6 in quadrant): snare left, hats right
    "snare", "hat_closed", "hat_open", "perc",
]


def _has_double_onset(profile: OneshotProfile) -> bool:
    """Check for clap-like double onset (flam pattern, 2+ transients within 40ms)."""
    # Use attack_time as a proxy: claps have a very short attack followed by
    # a second peak. If attack_time < 10ms and duration > 50ms, likely a flam.
    # A more accurate check would re-analyze the onset envelope, but this
    # catches most claps without re-reading the audio.
    return (
        profile.attack_time < 0.010
        and profile.duration > 0.050
        and 800 < profile.spectral_centroid < 6000
        and profile.crest_factor > 4.0
    )


def classify_drum_hit(profile: OneshotProfile) -> str:
    """
    Classify a drum one-shot by spectral heuristics.

    Rules are ordered — first match wins. Handles both acoustic
    and electronic drums (808 kicks, synth snares, noise hats).

    Returns one of: kick, snare, clap, hat_closed, hat_open, rim, perc
    """
    centroid = profile.spectral_centroid
    flatness = profile.spectral_flatness
    crest = profile.crest_factor
    bandwidth = profile.spectral_bandwidth
    dur = profile.duration

    # 1. Kick: low frequency, some body
    #    Acoustic: centroid < 200 Hz, flatness < 0.3
    #    808/electronic: centroid < 300 Hz, may have long sub-bass tail
    if centroid < 300 and dur > 0.050:
        return "kick"

    # 2. Rim / click: very short, very transient — check before snare/clap
    if dur < 0.030 and crest > 8.0:
        return "rim"

    # 3. Closed hi-hat: high frequency, noisy, short
    if centroid > 5000 and flatness > 0.35 and dur < 0.120:
        return "hat_closed"

    # 4. Open hi-hat / cymbal: high frequency, noisy, sustained
    if centroid > 5000 and flatness > 0.35 and dur > 0.120:
        return "hat_open"

    # 5. Snare: mid-frequency, high crest, wide bandwidth (snare wires)
    if 500 < centroid < 5000 and crest > 5.0 and bandwidth > 1500:
        return "snare"

    # 6. Clap: mid-frequency with double onset (flam pattern)
    #    Checked after snare so single-transient snares don't get misclassified
    if _has_double_onset(profile):
        return "clap"

    # 7. Default: percussion (toms, shakers, FX)
    return "perc"


def classify_and_assign(
    profiles: list[OneshotProfile],
) -> list[OneshotProfile]:
    """
    Classify all drum one-shots and assign classifications.
    Returns the profiles with .classification set.
    """
    for p in profiles:
        p.classification = classify_drum_hit(p)
    return profiles


def arrange_drum_pads(
    profiles: list[OneshotProfile],
    n_pads: int = 8,
) -> list[OneshotProfile | None]:
    """
    Arrange classified drum one-shots into the standard pad layout.

    Layout (8 pads, 2 rows × 4 cols):
      Row 2 (top):    [snare] [hat_closed] [hat_open] [perc]
      Row 1 (bottom): [kick]  [kick2]      [perc]     [perc]

    Returns list of n_pads entries (None for empty pads).
    """
    # Group by classification
    by_type: dict[str, list[OneshotProfile]] = {}
    for p in profiles:
        by_type.setdefault(p.classification, []).append(p)

    # Sort each group by crest factor (punchiest first)
    for group in by_type.values():
        group.sort(key=lambda p: p.crest_factor, reverse=True)

    # Fill pads according to the layout order
    pads: list[OneshotProfile | None] = [None] * n_pads
    type_cursors: dict[str, int] = {t: 0 for t in DRUM_TYPES}

    for pad_idx in range(min(n_pads, len(DRUM_PAD_ORDER))):
        wanted_type = DRUM_PAD_ORDER[pad_idx]
        candidates = by_type.get(wanted_type, [])
        cursor = type_cursors.get(wanted_type, 0)

        if cursor < len(candidates):
            pads[pad_idx] = candidates[cursor]
            type_cursors[wanted_type] = cursor + 1
        else:
            # Fall back: try any remaining unassigned hit
            for fallback_type in DRUM_TYPES:
                fb_candidates = by_type.get(fallback_type, [])
                fb_cursor = type_cursors.get(fallback_type, 0)
                if fb_cursor < len(fb_candidates):
                    pads[pad_idx] = fb_candidates[fb_cursor]
                    type_cursors[fallback_type] = fb_cursor + 1
                    break

    return pads
