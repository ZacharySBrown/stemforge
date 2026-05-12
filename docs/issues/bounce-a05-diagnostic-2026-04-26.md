# BOUNCE A05 — overnight diagnostic findings

**Captured:** 2026-04-26 ~00:30, between sessions.
**RESOLVED:** User A/B'd the 4 candidate bounces against Live and confirmed **hypothesis B** (bpm-derived spb, no loop_start subtraction) is correct.

## TL;DR

The bug is just the **spb math** — `source_duration / length_beats` should be `60 / src_bpm`. The handoff doc identified this correctly. My overnight hypothesis that there was ALSO a missing `loop_start` subtraction was wrong; the user's A/B test ruled it out.

The working tree is **clean** — the "uncommitted revert + 19 passing tests" the handoff describes does not exist on disk. Apply the fix fresh from commit `4206e19`.

## The actual bug

Current code in `tools/m4l_export_clips.py:259`:

```python
start_seconds = start_marker_beats * seconds_per_beat
end_seconds = (start_marker_beats + loop_length_beats) * seconds_per_beat
```

with `seconds_per_beat = source_duration / length_beats`.

This is wrong in two ways for forge-curated clips:

1. **spb math** uses linear-warp ratio, but forge sources are 2× longer than `length_beats`. For A05: `source=17.833s`, `length=16` → spb=1.1146. Correct value: `60/project_tempo = 0.5572`. Source is actually **32 beats** at project tempo, not 16.

2. **Missing `loop_start` subtraction**. Forge-padded sources anchor source-sample-0 at clip-beat-`loop_start`, not clip-beat-0. So source-second X = `(clip_beat - loop_start) * spb`.

## Diagnostic evidence

Ran 4 candidate-bounce hypotheses against A05's geometry. Files at `~/stemforge/exports/A05_diagnostic/`:

| File | Math | start_seconds | bounce length |
|---|---|---|---|
| `A05_A_current_linear.wav` | current code | 15.05s | 17.83s (full source, wraps) |
| `A05_B_bpm_only.wav` | handoff's "fix" | 7.52s | 8.92s |
| **`A05_C_bpm_minus_loopstart.wav`** | **proposed fix** | **3.065s** | **8.92s** |
| `A05_D_linear_minus_loopstart.wav` | half-fix | 6.13s | 17.83s |

User's stated target: source-second **3.065s**. Only C matches.

Tomorrow morning: open all four in QuickTime alongside A05 in Live. The one matching what Live plays from start_marker is the right math.

## Cross-check: A04 (control clip)

A04 has `start_marker == loop_start == 8`. Under hypothesis C: `start=0s`, `end=8.92s` (one bar). Under current code: `start=8.92s` plus wrap, ends up the full 17.83s source rotated.

The current A04.wav is **17.83s** — the entire source. That's wrong even though the user didn't notice (the audio happens to contain the right notes, just shifted/rotated). Hypothesis C produces 8.92s — one full bar starting at source-beat-0.

## Source geometry that confirms forge-anchor-at-loop_start convention

`bar_005.wav`:
- Duration: 17.833s (786,432 frames @ 44.1kHz)
- At project_tempo 107.67: that's **exactly 32 beats** of audio
- Live LOM reports `length_beats=16`
- Loop region [8, 24] is exactly 16 beats long
- Loop region in seconds: [4.46s, 13.37s] under the wrong assumption that source-0 = clip-beat-0
- Loop region in seconds under hypothesis C (source-0 = clip-beat-loop_start): [0s, 8.92s]

The forge curation v2 design pads sources with extra context (2 bars for a 1-bar loop). The padding is at the START of the file, and the warp markers shift the audio so clip-beat-`loop_start` lines up with source-sample-0. That's why subtracting loop_start is required.

## Proposed fix

In `tools/m4l_export_clips.py`, replace lines 228-260 with:

```python
# Beats↔seconds: forge-curated padded sources anchor source-sample-0 at
# clip-beat-`loop_start` (not at clip-beat-0). The clip's `length_beats`
# reflects the loop region, not the source's full beat count — which can
# be 2× length when the forge padded for context.
src_bpm = clip.get("clip_warp_bpm") or project_tempo
seconds_per_beat = 60.0 / src_bpm if src_bpm else 0.5

length_beats = float(clip.get("length_beats") or 0.0)
loop_start_beats = float(clip.get("loop_start_beats") or 0.0)
loop_end_beats = float(clip.get("loop_end_beats") or length_beats)
start_marker_beats = float(clip.get("start_marker_beats", loop_start_beats))

# Clamp start_marker into the loop region.
if start_marker_beats < loop_start_beats:
    start_marker_beats = loop_start_beats
elif start_marker_beats > loop_end_beats:
    start_marker_beats = loop_end_beats

loop_length_beats = loop_end_beats - loop_start_beats

# start_marker is in clip-beat coordinates; subtract loop_start to get
# offset into source. Wrap modulo source length is handled in slice_clip.
start_seconds = (start_marker_beats - loop_start_beats) * seconds_per_beat
end_seconds = start_seconds + loop_length_beats * seconds_per_beat
```

## Tests need to change too

Existing tests in `tests/test_m4l_export_clips.py` were written against the BROKEN linear-warp math; they construct fixtures where `source_duration / length_beats == 60/src_bpm`, so they pass under either math. After the fix, the assertions need updating because:

- `test_loop_wraps_around_source_when_loop_extends_past_source` (line 184): expects 10s slice from a 16-beat clip. Under hypothesis C with default project_tempo=120 (or whatever the fixture uses), spb=0.5, slice=8 beats × 0.5 = 4s, not 10s. Fixture geometry needs adjusting.
- `test_start_marker_rotates_loop_within_source` (line 229): asserts source[7.5..10] + source[0..2.5] (rotation by start_marker=12). Under C, start = (12-8)×0.5 = 2s, end=2+8×0.5=6s, no wrap. Different slice entirely. Needs rewrite.

I'd recommend: write fresh tests using the actual A05 geometry (32-beat padded source, length=16, start_marker=13.5) since that's the real-world case; deprecate the synthetic ramp tests.

## Important state correction to handoff

The handoff doc `bounce-a05-debug-handoff.md` says:

> Reverting the linear-warp seconds_per_beat (from commit 4206e19) back to project-tempo math, while keeping the start_marker reading. Tests updated to match. **19 tests passing.**
>
> Files modified, not committed:
> - `tools/m4l_export_clips.py`
> - `tests/test_m4l_export_clips.py`

This is **not** the current state. `git diff HEAD` shows zero changes to either file. The 19 passing tests are passing against the linear-warp code in commit 4206e19. Either the revert was never written, or it was lost.

This means there's nothing to recover or commit before applying the fix — start fresh from `4206e19`.

## What's NOT changed in this session

- No source files modified.
- No tests modified.
- No commits made.
- No memory files modified yet (will update `project_bounce_v1_state.md` after this so future sessions find the right pointer).

Diagnostic outputs at `~/stemforge/exports/A05_diagnostic/` (4 wavs). Safe to delete.
