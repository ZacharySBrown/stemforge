"""Pure scene-model math: bar inference, event tiling, scene-length derivation.

Lifted from :mod:`stemforge.exporters.ep133.song_synthesizer` (Configurator
Phase 1). Everything here is target-agnostic — no device-specific imports,
no project types. The EP-133 exporter wraps these to plug into its own
data shapes; future projectors do the same.
"""

from __future__ import annotations

from typing import Sequence

# ── Bar inference ───────────────────────────────────────────────────────────

# A clip's duration counts as "exactly N bars" if it's within this many
# seconds of the integer bar boundary. Wide enough to absorb arrangement-
# render quantization noise without snapping musically-distinct clips.
BARS_TOLERANCE_SEC = 0.4

# Bar counts a clip can snap to when it's near a bar boundary. The EP-133
# exporter currently uses {1, 2, 4} (the device's accepted ``time.bars``
# set is {0.25, 0.5, 1, 2, 4}). Other projectors with different valid
# bar sets will widen this when they're ported.
BARS_CANDIDATES_SNAP: tuple[int, ...] = (1, 2, 4)

# Fallback candidates when the clip duration falls between snap bars: pick
# the closest of these and let the device's stretch absorb the difference.
# Today this is the same set as snap; kept separate so future projectors
# can diverge (e.g. allow snapping to 8 but never falling back to it).
BARS_CANDIDATES_FALLBACK: tuple[int, ...] = (1, 2, 4)


def infer_bars(clip_length_sec: float, project_bpm: float) -> int:
    """Pick a bar count for a clip given its duration + project BPM.

    Two-stage decision:

    1. If the clip duration is within ±:data:`BARS_TOLERANCE_SEC` of an
       integer bar count at ``project_bpm``, snap to that bar count
       (chosen from :data:`BARS_CANDIDATES_SNAP`).
    2. Otherwise pick the closest of :data:`BARS_CANDIDATES_FALLBACK`
       and let downstream stretch absorb the difference.

    Raises :class:`ValueError` if ``project_bpm`` is non-positive.
    """
    if project_bpm <= 0:
        raise ValueError(f"project_bpm must be positive, got {project_bpm!r}")
    bar_dur_sec = 60.0 * 4.0 / project_bpm
    for bars in BARS_CANDIDATES_SNAP:
        if abs(clip_length_sec - bars * bar_dur_sec) <= BARS_TOLERANCE_SEC:
            return bars
    return min(
        BARS_CANDIDATES_FALLBACK,
        key=lambda b: abs(clip_length_sec - b * bar_dur_sec),
    )


# ── Event tiling (fan a short slice across a longer pattern) ────────────────

# Cap on multi-event tiling density. 32 events per pattern is a 32nd-note
# grid at 4/4 — the finest density that's musically useful. Beyond that
# the slice is shorter than typical rhythmic resolution and a single
# trigger sounds the same.
MAX_EVENTS_PER_PATTERN = 32

# Total trigger counts per pattern that multi-event tiling snaps to.
# Subdivisions of the WHOLE pattern, not per-bar — chosen so spacing
# always lands on a familiar grid:
#   1 = single fire, 2 = halves, 4 = quarters, 8 = eighths,
#   16 = sixteenths, 32 = thirty-seconds (relative to pattern length).
# A slice that lands between these snaps to the closest. Never produces
# a 6- or 7-tuplet feel that fights the underlying tempo.
MUSICAL_TRIGGER_COUNTS: tuple[int, ...] = (1, 2, 4, 8, 16, 32)


def tile_event_positions(slice_bars: float, pattern_bars: int) -> list[float]:
    """Compute event positions (in bars) for a multi-event pattern.

    A clip whose slice is shorter than the pattern needs to fire multiple
    times to mimic loop-fill behavior. The trigger count snaps to the
    nearest power-of-2 subdivision of the pattern length so the result
    lands on a familiar rhythmic grid instead of an awkward 6- or
    7-tuplet. Slices that are roughly pattern-length or longer return
    a single trigger at position 0.

    Examples:
      pattern_bars=1, slice_bars=1.0     → [0.0]                 (1× whole)
      pattern_bars=1, slice_bars=0.5     → [0.0, 0.5]            (halves)
      pattern_bars=1, slice_bars=0.156   → 8 events (eighth-grid)
      pattern_bars=4, slice_bars=2.0     → [0.0, 2.0]            (every 2 bars)
      pattern_bars=4, slice_bars=1.0     → 4 events (one per bar)
    """
    if slice_bars <= 0 or pattern_bars <= 0:
        return [0.0]
    raw_count = pattern_bars / slice_bars
    # Slices roughly pattern-length (or longer) → single fire. Threshold
    # at 1.5 keeps the snap from picking n=2 below it.
    if raw_count < 1.5:
        return [0.0]
    candidates = [c for c in MUSICAL_TRIGGER_COUNTS if c <= MAX_EVENTS_PER_PATTERN]
    # Tie-break to the smaller count when raw_count sits exactly between
    # two subdivisions (musically the more conservative choice).
    n = min(candidates, key=lambda c: (abs(c - raw_count), c))
    if n == 1:
        return [0.0]
    spacing = pattern_bars / n
    return [i * spacing for i in range(n)]


# ── Scene length derivation (locator-gap → scene length) ────────────────────


def scene_lengths_in_bars(
    locator_times_sec: Sequence[float],
    project_bpm: float,
    arrangement_length_sec: float | None,
) -> list[int]:
    """Derive each scene's length in bars from its locator and the next.

    Strategy:

    1. Quantize each locator's time to its nearest integer-bar position
       (so a drag-imprecise locator at t=3.6s on a 1.765s/bar project
       snaps to bar 2 instead of producing a fractional gap).
    2. Scene N's length in bars = quantized_bar(N+1) − quantized_bar(N).
    3. For the trailing scene, end at ``arrangement_length_sec``
       (also quantized) if provided; else fall back to the median of
       preceding gaps; else default to 2 bars.

    Any positive integer bar count is allowed (1, 2, 3, 4, 5, ...) — odd
    counts are NOT silently snapped to powers of 2. A 3-bar scene is a
    valid musical section (Take Five, etc); a power-of-2 conformity mode
    is earmarked as a future opt-in.

    Result is clamped to 1..255 (uint8 range — narrowest projector's
    pattern-header constraint).
    """
    if not locator_times_sec:
        return []
    if project_bpm <= 0:
        raise ValueError(f"project_bpm must be positive, got {project_bpm!r}")
    bar_dur_sec = 240.0 / project_bpm

    def to_bars(t: float) -> int:
        return int(round(t / bar_dur_sec))

    quantized_bars = [to_bars(t) for t in locator_times_sec]

    if arrangement_length_sec is not None:
        end_bar: int | None = to_bars(arrangement_length_sec)
    else:
        end_bar = None

    bar_gaps: list[int] = []
    n = len(locator_times_sec)
    for i in range(n):
        if i + 1 < n:
            bar_gaps.append(quantized_bars[i + 1] - quantized_bars[i])
        elif end_bar is not None:
            bar_gaps.append(end_bar - quantized_bars[i])
        else:
            bar_gaps.append(-1)
    # Fix non-positive trailing gap (single-locator with no length, or an
    # end_bar that landed on/before the last locator due to rounding).
    if bar_gaps[-1] <= 0 and len(bar_gaps) > 1:
        prior = sorted(g for g in bar_gaps[:-1] if g > 0)
        bar_gaps[-1] = prior[len(prior) // 2] if prior else 2
    elif bar_gaps[-1] <= 0:
        bar_gaps[-1] = 2  # single-locator default
    return [max(1, min(255, g)) for g in bar_gaps]
