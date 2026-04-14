"""
beat_curator.py — thin shim for back-compat.

All functionality has moved to `stemforge.curator`. This module
re-exports the public API so existing scripts in tools/ keep working.
"""

from stemforge.curator import (  # noqa: F401
    BeatProfile,
    load_mono,
    detect_onsets,
    compute_rhythm_fingerprint,
    compute_energy_curve,
    spectral_features,
    analyze_beat,
    analyze_all_beats,
    rhythm_distance,
    spectral_distance,
    energy_distance,
    composite_distance,
    greedy_diverse_select,
    cluster_by_rhythm,
    select_variants_from_cluster,
    format_beat_report,
    export_curated_set,
    curate,
)
