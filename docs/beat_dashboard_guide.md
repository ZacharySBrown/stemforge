# Beat Analysis Dashboard — Review Guide

## Opening the Dashboard

```bash
# Regenerate (analyzes all tracks, takes 5-10 min with beat-this):
uv run python tools/beat_dashboard.py

# Open:
open tools/beat_dashboard.html
```

## Summary Bar (top)

Quick health check across all tracks:
- **Clean (CV < 1%)** — these are solid, no review needed
- **Issues (CV > 3%)** — these need attention
- **Heuristic corrections** — tracks where ghost filter or downbeat offset improved CV
- **beat-this wins** — tracks where neural downbeat detection outperformed librosa

## Main Table

### Key columns

| Column | What it means | What to look for |
|--------|--------------|-----------------|
| **CV% (lib)** | Bar duration regularity from librosa. Lower = more consistent bars. | Green (<1%) is great. Red (>3%) needs review. |
| **CV% (bt-drm)** | beat-this on drums stem. Often worse than librosa on isolated stems. | Compare against librosa — if lower, the neural model found better downbeats. |
| **CV% (bt-mix)** | beat-this on full mix. Usually the best neural result. | The key comparison column. If green while librosa is red, beat-this should be used for this track. |
| **Best** | Which method won (lowest CV). | `bt-mix` = beat-this on full mix won. `librosa` = heuristic approach won. |
| **Ghosts** | Number of ghost beats removed by the filter. | High numbers (>5) suggest heavy syncopation — the track may need manual review. |
| **Offset** | Downbeat offset correction applied (0 = none). | Non-zero means librosa's beat 0 wasn't the actual downbeat. |
| **Deviant** | Bars deviating >5% from median duration. | High numbers mean many bars have wrong boundaries. |
| **Drift** | Tempo stability score. >5 = significant drift. | High drift often means librosa detected half/double time in some sections. |

### Sorting

Click any column header to sort. Useful sorts:
- **CV% (lib) descending** — worst tracks first, prioritize review
- **Deviant descending** — most problematic bar boundaries first
- **Best** — group by which detection method won

### Filtering

- Search box: type a track name
- Dropdown: "Has issues" shows only CV > 3% tracks

## Detail View (click a row)

### Bar Durations chart
- Green bars: within 5% of median (good)
- Yellow bars: 5-8% off (borderline)
- Red bars: >8% off (misaligned)
- Dashed line: median bar duration

**What to look for:** A flat row of green bars = perfect. Red bars clustered at the start = intro at different tempo. Red bars scattered throughout = beat detection instability.

### Energy Timeline
- Bright blocks: drums playing
- Dark gaps: drum dropouts (intros, breakdowns, sample sections)

**What to look for:** If deviant bars coincide with energy gaps, the problem is structural (drums drop out, beat tracker loses the grid). Those bars should be filtered, not "fixed."

### Downbeat Offset Scores
- Shows onset energy for each possible beat offset (0 to time_sig-1)
- Green bar = the chosen offset

**What to look for:** If the best offset has only slightly more energy than others, the track has weak downbeats (e.g., no strong kick on beat 1). These tracks are harder for any algorithm.

### Beat Detection Comparison
- Side-by-side table: librosa vs beat-this (drums) vs beat-this (mix)
- Shows BPM, bar count, CV%, and downbeat count for each method

**What to look for:** If beat-this BPM is wildly different from librosa (e.g., double), it's hallucinating — ignore that result. If BPMs match but CV is lower, beat-this found better bar boundaries.

### Deviant Bars list
- Each entry: bar number, timestamp, duration, deviation %

**What to do:** Click the audio player, skip to the timestamp of a deviant bar, listen. Is it:
- **A real misalignment?** The bar starts mid-beat. → The track needs better beat detection or manual correction.
- **A structural change?** The bar is in an intro/breakdown with different tempo. → Add a bar duration filter to skip these during curation.
- **Syncopation artifact?** The bar sounds fine but the measured duration is off because of a ghost beat. → The ghost filter should handle this; if not, the track may need the beat-this approach.

## Triage Workflow

1. Sort by CV% descending
2. Skip anything green (<1%) — those are fine
3. For yellow (1-3%): glance at the detail. If deviant bars are just first/last bar, ignore.
4. For red (>3%): open detail, check:
   - Does beat-this (mix) have lower CV? → That track should use neural detection
   - Are deviant bars in energy gaps? → Structural, add duration filter
   - Are deviant bars scattered? → Beat detection instability, may need manual review
5. Note tracks that need attention for future manual correction
