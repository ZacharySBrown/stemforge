#!/usr/bin/env python3
"""
run_plans.py — Execute 3 curation strategies on Hot Pants drum beats.
Each plan produces a curated set of 12-16 beats optimized for IDM chopping.
"""

import sys
sys.path.insert(0, "/Users/zak/zacharysbrown/stemforge")

from pathlib import Path
from tools.beat_curator import (
    analyze_all_beats, BeatProfile,
    greedy_diverse_select, cluster_by_rhythm, select_variants_from_cluster,
    composite_distance, rhythm_distance, spectral_distance, energy_distance,
    format_beat_report, export_curated_set,
)
import numpy as np
import json

BEATS_DIR = Path.home() / "stemforge/processed/hot_pants_i_m_coming_i_m_coming/drums_beats"
OUTPUT_DIR = Path.home() / "stemforge/curated/hot_pants"

# ── Analyze all beats ──
print("Analyzing 267 beats...")
profiles = analyze_all_beats(BEATS_DIR)
active = [p for p in profiles if p.rms > 0.005 and p.onset_count > 0]
print(f"  {len(profiles)} total, {len(active)} active (non-silent)")

# Quick stats
onset_counts = [p.onset_count for p in active]
centroids = [p.spectral_centroid for p in active]
crests = [p.crest_factor for p in active]
print(f"  Onset count range: {min(onset_counts)}-{max(onset_counts)} (mean {np.mean(onset_counts):.1f})")
print(f"  Spectral centroid range: {min(centroids):.0f}-{max(centroids):.0f}Hz")
print(f"  Crest factor range: {min(crests):.1f}-{max(crests):.1f}")

# Rhythm pattern diversity
unique_patterns = set(p.rhythm_fingerprint for p in active)
print(f"  Unique rhythm patterns: {len(unique_patterns)}")


# ══════════════════════════════════════════════════════════════════════
# PLAN A: "Maximum Diversity" — Greedy farthest-point on composite distance
# Strategy: Pure diversity maximization. No clustering. Just pick beats
# that are as different from each other as possible across ALL dimensions.
# Good for: varied chop palettes where every hit feels distinct.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  PLAN A: Maximum Diversity (greedy farthest-point)")
print("="*60)

plan_a = greedy_diverse_select(active, n=14, dist_fn=composite_distance)
plan_a.sort(key=lambda p: p.index)  # sort by position in track

report_a = format_beat_report(plan_a, "Plan A — Maximum Diversity")
print(report_a)

out_a = export_curated_set(plan_a, OUTPUT_DIR, "plan_a_max_diversity")
print(f"  Exported to: {out_a}")

# Learnings
print("\n  LEARNINGS — Plan A:")
print(f"  - Selected beats span indices {plan_a[0].index}-{plan_a[-1].index} (of 267)")
coverage = len(set(p.rhythm_fingerprint for p in plan_a))
print(f"  - Covers {coverage} unique rhythm patterns")
print(f"  - Onset count range in selection: {min(p.onset_count for p in plan_a)}-{max(p.onset_count for p in plan_a)}")
print(f"  - Centroid range: {min(p.spectral_centroid for p in plan_a):.0f}-{max(p.spectral_centroid for p in plan_a):.0f}Hz")


# ══════════════════════════════════════════════════════════════════════
# PLAN B: "Rhythm Taxonomy" — Cluster by rhythm pattern, then pick
# the best representative + interesting variants from each cluster.
# Strategy: First group by rhythmic similarity (transient timing),
# then within each group, select timbral variants.
# Good for: understanding the song's rhythmic vocabulary, getting
# one "canonical" version of each pattern plus variations.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  PLAN B: Rhythm Taxonomy (cluster + variant selection)")
print("="*60)

clusters = cluster_by_rhythm(active, threshold=0.25)
print(f"  Found {len(clusters)} rhythm clusters")

# Sort clusters by size (largest first = most common patterns)
sorted_clusters = sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True)

plan_b = []
cluster_report = []

for i, (pattern, members) in enumerate(sorted_clusters):
    pat_str = ''.join(['x' if b else '.' for b in pattern])
    size = len(members)

    if size >= 3:
        # Large cluster: pick up to 2 variants (canonical + interesting alt)
        variants = select_variants_from_cluster(members, max_variants=2)
        plan_b.extend(variants)
        cluster_report.append(f"  Cluster {i+1}: [{pat_str}] ({size} beats) → picked {len(variants)} variants")
    elif size >= 1:
        # Small cluster or singleton: pick the punchiest one
        best = max(members, key=lambda p: p.crest_factor)
        plan_b.append(best)
        cluster_report.append(f"  Cluster {i+1}: [{pat_str}] ({size} beats) → picked 1 best")

    if len(plan_b) >= 16:
        break

# If under 12, add more from largest clusters
if len(plan_b) < 12:
    for pattern, members in sorted_clusters:
        extras = [m for m in members if m not in plan_b]
        for e in extras:
            if len(plan_b) >= 12:
                break
            plan_b.append(e)

plan_b.sort(key=lambda p: p.index)

for line in cluster_report:
    print(line)

report_b = format_beat_report(plan_b, "Plan B — Rhythm Taxonomy")
print(report_b)

out_b = export_curated_set(plan_b, OUTPUT_DIR, "plan_b_rhythm_taxonomy")
print(f"  Exported to: {out_b}")

print("\n  LEARNINGS — Plan B:")
print(f"  - {len(clusters)} distinct rhythm patterns found in 267 beats")
print(f"  - Largest cluster has {len(sorted_clusters[0][1])} beats (most common pattern)")
print(f"  - {sum(1 for _,m in sorted_clusters if len(m)==1)} singleton patterns (unique one-off rhythms)")
print(f"  - Selected {len(plan_b)} beats covering {len(set(p.rhythm_fingerprint for p in plan_b))} patterns")


# ══════════════════════════════════════════════════════════════════════
# PLAN C: "Sectional Narrative" — Divide track into sections, pick
# the most interesting/punchy beat from each section, plus outliers.
# Strategy: The song has structure (intro, verse, chorus, bridge,
# breakdown). Sample each section for its most characteristic beat,
# then add global outliers for spice.
# Good for: capturing the feel of different song sections,
# great for IDM where you want to "tell a story" with chops.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  PLAN C: Sectional Narrative (positional + outlier selection)")
print("="*60)

# Divide 267 beats into ~8 sections (roughly 33 beats each, ~16 bars)
n_sections = 8
section_size = len(active) // n_sections

# Sort active by index for positional sectioning
by_position = sorted(active, key=lambda p: p.index)

plan_c = []
section_report = []

for s in range(n_sections):
    start = s * section_size
    end = start + section_size if s < n_sections - 1 else len(by_position)
    section = by_position[start:end]

    if not section:
        continue

    # Pick the most "interesting" beat: high crest + moderate onset density
    # (punchy but not just noise)
    scored = [(p, p.crest_factor * (1 + p.onset_density * 0.3)) for p in section]
    best = max(scored, key=lambda x: x[1])[0]
    plan_c.append(best)
    section_report.append(
        f"  Section {s+1} (beats {section[0].index}-{section[-1].index}): "
        f"picked beat_{best.index:03d} (crest={best.crest_factor:.1f}, onsets={best.onset_count})"
    )

# Add outliers: beats with unusual spectral character or rhythm
mean_centroid = np.mean([p.spectral_centroid for p in active])
std_centroid = np.std([p.spectral_centroid for p in active])
mean_density = np.mean([p.onset_density for p in active])
std_density = np.std([p.onset_density for p in active])

outliers = [
    p for p in active
    if p not in plan_c and (
        abs(p.spectral_centroid - mean_centroid) > 1.5 * std_centroid or
        abs(p.onset_density - mean_density) > 1.5 * std_density
    )
]

# Pick the most diverse outliers
if outliers:
    outlier_picks = greedy_diverse_select(outliers, n=min(6, 16 - len(plan_c)),
                                          dist_fn=composite_distance)
    plan_c.extend(outlier_picks)
    section_report.append(f"  + {len(outlier_picks)} outliers (spectrally/rhythmically unusual)")

# Fill to 12 if needed
if len(plan_c) < 12:
    remaining = [p for p in active if p not in plan_c]
    extras = greedy_diverse_select(remaining, n=12 - len(plan_c), dist_fn=composite_distance)
    plan_c.extend(extras)

plan_c.sort(key=lambda p: p.index)

for line in section_report:
    print(line)

report_c = format_beat_report(plan_c, "Plan C — Sectional Narrative")
print(report_c)

out_c = export_curated_set(plan_c, OUTPUT_DIR, "plan_c_sectional_narrative")
print(f"  Exported to: {out_c}")

print("\n  LEARNINGS — Plan C:")
section_indices = [p.index for p in plan_c[:n_sections]]
print(f"  - Section picks span: {section_indices}")
print(f"  - {len(outliers)} total outlier candidates found")
print(f"  - {len(plan_c)} final beats selected")
print(f"  - Unique patterns: {len(set(p.rhythm_fingerprint for p in plan_c))}")


# ══════════════════════════════════════════════════════════════════════
# SUMMARY COMPARISON
# ══════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  COMPARISON SUMMARY")
print("="*60)

for label, picks in [("Plan A", plan_a), ("Plan B", plan_b), ("Plan C", plan_c)]:
    patterns = len(set(p.rhythm_fingerprint for p in picks))
    avg_crest = np.mean([p.crest_factor for p in picks])
    centroid_range = max(p.spectral_centroid for p in picks) - min(p.spectral_centroid for p in picks)
    idx_spread = picks[-1].index - picks[0].index
    avg_density = np.mean([p.onset_density for p in picks])
    print(f"  {label}: {len(picks)} beats, {patterns} patterns, "
          f"avg_crest={avg_crest:.1f}, centroid_span={centroid_range:.0f}Hz, "
          f"idx_spread={idx_spread}, avg_density={avg_density:.1f}/s")

print(f"\n  All outputs in: {OUTPUT_DIR}")
print("  Each folder contains WAVs + manifest.json")
print("  Done!")
