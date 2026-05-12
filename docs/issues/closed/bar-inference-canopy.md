# Bar-count inference: 5/6/7 excluded — revisit if odd-meter content needs supporting

**Status:** Open / informational — captured 2026-05-12.

## Background

`kit_synthesizer._infer_source_bpm` snaps a clip's actual duration to one of `{0.25, 0.5, 1, 2, 3, 4, 8}` bars to derive `source_bpm` when no explicit one was captured. Memory: [`feedback_bar_inference_candidates.md`].

5, 6, and 7 are deliberately **excluded**. Reason (2026-05-11 audit): an 11.29s 4-bar @ 85 BPM oll texture was misclassified as 5-bar @ 106 BPM when 5 was in the candidate set. The "vanishingly rare" odd phrase length stole the scoring win from the right 4-bar interpretation.

## When this might bite

- **Take Five** (Dave Brubeck) — literally 5-beat (5/4) phrases, often arranged as 5-bar groupings.
- **Tombo in 7/4** (Airto) — we worked around this in this session by passing `--bpm 138 --time-sig 7/4` manually to curate, but the bar-count inference would still snap to 4 or 8 bars wrong if asked.
- Odd-meter prog rock, Indian classical, etc.

For now the M4L pre-crop capture of `source_bpm` (via warp_markers slope) sidesteps this for any *warped* clip — the inference is only the fallback for unwarped clips or clips that pre-date the warp_markers capture.

## What to do (if needed)

1. **Don't add 5/6/7 to the candidate set.** That regressed the 4-bar case.
2. **Gate inclusion on user hint.** If `deck.yaml` has `time_sig: [5, 4]` for a pad, include `5` in the candidates for that pad's inference.
3. **Use the project's `time_sig`** field (already in manifests) as a hint for which candidates to enable.

## Done when

Either:
- We hit a real case where odd-meter content fails to load on EP-133.
- We add an explicit user-hint path for 5/6/7-bar clips.

Out of scope: building an actual meter detector. That's a separate research project.
