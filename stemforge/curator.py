"""
stemforge.curator — Diversity-based beat/bar curation.

Analyzes beat/bar slices for transient patterns, spectral character,
and rhythmic fingerprints, then selects a diverse subset via greedy
farthest-point selection.
"""

from __future__ import annotations

import json
import shutil
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .segmenter import SongStructure

import numpy as np
import soundfile as sf


@dataclass
class BeatProfile:
    path: Path
    index: int
    duration: float = 0.0
    onset_times: list = field(default_factory=list)
    onset_count: int = 0
    onset_density: float = 0.0
    rms: float = 0.0
    peak: float = 0.0
    crest_factor: float = 0.0
    attack_time: float = 0.0
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    spectral_flatness: float = 0.0
    rhythm_fingerprint: tuple = ()
    energy_curve: list = field(default_factory=list)


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path))
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


def detect_onsets(audio: np.ndarray, sr: int, threshold_ratio: float = 0.3) -> list[float]:
    hop = max(1, sr // 100)
    n_fft = 2048
    if len(audio) < n_fft:
        return []

    flux = []
    prev_spec = np.zeros(n_fft // 2 + 1)
    for i in range(0, len(audio) - n_fft, hop):
        frame = audio[i:i + n_fft] * np.hanning(n_fft)
        spec = np.abs(np.fft.rfft(frame))
        diff = np.maximum(spec - prev_spec, 0)
        flux.append(np.sum(diff))
        prev_spec = spec

    if not flux:
        return []

    flux = np.array(flux)
    threshold = np.mean(flux) + threshold_ratio * np.std(flux)
    min_dist = max(1, int(0.03 * sr / hop))
    onsets = []
    for i in range(1, len(flux) - 1):
        if flux[i] > threshold and flux[i] > flux[i - 1] and flux[i] >= flux[i + 1]:
            if not onsets or (i - onsets[-1]) >= min_dist:
                onsets.append(i)
    return [i * hop / sr for i in onsets]


def compute_rhythm_fingerprint(onset_times: list, duration: float, grid_size: int = 16) -> tuple:
    grid = [0] * grid_size
    for t in onset_times:
        pos = int((t / duration) * grid_size) if duration > 0 else 0
        if 0 <= pos < grid_size:
            grid[pos] = 1
    return tuple(grid)


def compute_energy_curve(audio: np.ndarray, n_segments: int = 8) -> list[float]:
    seg_len = len(audio) // n_segments
    if seg_len == 0:
        return [0.0] * n_segments
    return [
        float(np.sqrt(np.mean(audio[i * seg_len:(i + 1) * seg_len] ** 2)))
        for i in range(n_segments)
    ]


def spectral_features(audio: np.ndarray, sr: int) -> dict:
    n_fft = min(2048, len(audio))
    if n_fft < 64:
        return {"centroid": 0.0, "bandwidth": 0.0, "flatness": 0.0}
    spec = np.abs(np.fft.rfft(audio[:n_fft] * np.hanning(n_fft)))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    total = np.sum(spec) + 1e-10
    centroid = float(np.sum(freqs * spec) / total)
    bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * spec) / total))
    log_spec = np.log(spec + 1e-10)
    geo_mean = np.exp(np.mean(log_spec))
    arith_mean = np.mean(spec)
    flatness = float(geo_mean / (arith_mean + 1e-10))
    return {"centroid": centroid, "bandwidth": bandwidth, "flatness": flatness}


def analyze_beat(path: Path, index: int) -> BeatProfile:
    audio, sr = load_mono(path)
    duration = len(audio) / sr if sr else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    if duration < 0.05 or rms < 1e-6:
        return BeatProfile(path=path, index=index, duration=duration, rms=rms)

    onsets = detect_onsets(audio, sr)
    peak = float(np.max(np.abs(audio)))
    crest = peak / (rms + 1e-10)
    peak_idx = int(np.argmax(np.abs(audio)))
    attack_time = peak_idx / sr
    spec = spectral_features(audio, sr)
    fingerprint = compute_rhythm_fingerprint(onsets, duration, grid_size=16)
    energy = compute_energy_curve(audio, n_segments=8)

    return BeatProfile(
        path=path, index=index,
        duration=duration,
        onset_times=onsets, onset_count=len(onsets),
        onset_density=len(onsets) / duration if duration > 0 else 0,
        rms=rms, peak=peak, crest_factor=crest,
        attack_time=attack_time,
        spectral_centroid=spec["centroid"],
        spectral_bandwidth=spec["bandwidth"],
        spectral_flatness=spec["flatness"],
        rhythm_fingerprint=fingerprint,
        energy_curve=energy,
    )


def analyze_all_beats(beats_dir: Path) -> list[BeatProfile]:
    files = sorted(Path(beats_dir).glob("*.wav"))
    return [analyze_beat(f, i + 1) for i, f in enumerate(files)]


# ── Distance functions (kept for back-compat with beat_curator.py shim) ──

def rhythm_distance(a: BeatProfile, b: BeatProfile) -> float:
    if not a.rhythm_fingerprint or not b.rhythm_fingerprint:
        return 1.0
    return sum(x != y for x, y in zip(a.rhythm_fingerprint, b.rhythm_fingerprint)) / len(a.rhythm_fingerprint)


def spectral_distance(a: BeatProfile, b: BeatProfile) -> float:
    dc = abs(a.spectral_centroid - b.spectral_centroid) / (max(a.spectral_centroid, b.spectral_centroid) + 1e-10)
    db = abs(a.spectral_bandwidth - b.spectral_bandwidth) / (max(a.spectral_bandwidth, b.spectral_bandwidth) + 1e-10)
    df = abs(a.spectral_flatness - b.spectral_flatness)
    return (dc + db + df) / 3


def energy_distance(a: BeatProfile, b: BeatProfile) -> float:
    if not a.energy_curve or not b.energy_curve:
        return 1.0
    ea = np.array(a.energy_curve)
    eb = np.array(b.energy_curve)
    mx = max(np.max(ea), np.max(eb), 1e-10)
    return float(np.sqrt(np.mean(((ea - eb) / mx) ** 2)))


def composite_distance(a: BeatProfile, b: BeatProfile,
                       w_rhythm: float = 0.5, w_spectral: float = 0.25, w_energy: float = 0.25) -> float:
    return (w_rhythm * rhythm_distance(a, b) +
            w_spectral * spectral_distance(a, b) +
            w_energy * energy_distance(a, b))


def greedy_diverse_select(profiles: list[BeatProfile], n: int,
                          dist_fn=composite_distance) -> list[BeatProfile]:
    if len(profiles) <= n:
        return list(profiles)
    active = [p for p in profiles if p.rms > 0.005 and p.onset_count > 0]
    if len(active) <= n:
        return active
    selected = [max(active, key=lambda p: p.crest_factor)]
    remaining = [p for p in active if p is not selected[0]]
    while len(selected) < n and remaining:
        best = max(remaining, key=lambda p: min(dist_fn(p, s) for s in selected))
        selected.append(best)
        remaining.remove(best)
    return selected


# ── Feature-vector-based selection (primary path used by `curate`) ──

def _feature_vector(p: BeatProfile, weights: dict[str, float] | None = None) -> np.ndarray:
    if weights is None:
        weights = {"rhythm": 0.5, "spectral": 0.25, "energy": 0.25}
    w_r = weights.get("rhythm", 0.5)
    w_s = weights.get("spectral", 0.25)
    w_e = weights.get("energy", 0.25)

    fp = np.array(p.rhythm_fingerprint, dtype=float) if p.rhythm_fingerprint else np.zeros(16)
    # Scale feature groups by their weights so GFP respects the balance
    spectral = np.array([p.spectral_centroid, p.spectral_bandwidth], dtype=float) * w_s
    transient = np.array([p.crest_factor, p.onset_density], dtype=float) * w_e
    rhythm = fp * w_r
    return np.concatenate([spectral, transient, rhythm])


def _znorm(matrix: np.ndarray) -> np.ndarray:
    mu = matrix.mean(axis=0)
    sd = matrix.std(axis=0)
    sd = np.where(sd < 1e-10, 1.0, sd)
    return (matrix - mu) / sd


def _greedy_farthest_point(features: np.ndarray, seed_idx: int, n: int) -> list[int]:
    n_points = features.shape[0]
    selected = [seed_idx]
    min_dist = np.linalg.norm(features - features[seed_idx], axis=1)
    min_dist[seed_idx] = -np.inf
    while len(selected) < min(n, n_points):
        nxt = int(np.argmax(min_dist))
        if min_dist[nxt] == -np.inf:
            break
        selected.append(nxt)
        new_dist = np.linalg.norm(features - features[nxt], axis=1)
        min_dist = np.minimum(min_dist, new_dist)
        min_dist[nxt] = -np.inf
    return selected


def _select_rhythm_taxonomy(
    profiles: list[BeatProfile], n: int, weights: dict | None,
) -> tuple[list[BeatProfile], np.ndarray, list[int]]:
    """Cluster by rhythm fingerprint, then pick diverse variants per cluster."""
    clusters = cluster_by_rhythm(profiles, threshold=0.25)

    if not clusters:
        # Fallback: treat all as one cluster
        clusters = {(0,) * 16: profiles}

    # Allocate slots proportional to cluster size, at least 1 per cluster
    total = sum(len(c) for c in clusters.values())
    allocation: dict[tuple, int] = {}
    remaining = n
    for key, members in sorted(clusters.items(), key=lambda x: -len(x[1])):
        slots = max(1, round(len(members) / total * n))
        allocation[key] = min(slots, remaining)
        remaining -= allocation[key]
        if remaining <= 0:
            break

    # Select variants from each cluster using spectral+energy diversity
    selected: list[BeatProfile] = []
    for key, members in clusters.items():
        slots = allocation.get(key, 0)
        if slots == 0:
            continue
        variants = select_variants_from_cluster(members, max_variants=slots)
        selected.extend(variants)

    selected = selected[:n]
    feature_matrix = np.array([_feature_vector(p, weights) for p in selected]) if selected else np.zeros((0, 20))
    selected_idx = list(range(len(selected)))
    return selected, feature_matrix, selected_idx


def _select_sectional(
    profiles: list[BeatProfile], n: int, weights: dict | None,
    song_structure: "SongStructure",
) -> tuple[list[BeatProfile], np.ndarray, list[int]]:
    """Weight bars by structural importance, then greedy-select with bias toward boundaries."""
    if not profiles:
        return [], np.zeros((0, 20)), []

    features = _znorm(np.array([_feature_vector(p, weights) for p in profiles]))

    # Compute importance-weighted distance: boost bars near boundaries
    importance = np.array([
        song_structure.importance_for_bar(p.index) for p in profiles
    ])
    # Add importance as an extra feature dimension (scaled to match others)
    importance_col = (importance * 3.0).reshape(-1, 1)  # weight importance heavily
    features_boosted = np.hstack([features, importance_col])

    # Seed with the most important bar (nearest to a boundary)
    seed = int(np.argmax(importance)) if np.max(importance) > 0 else int(np.argmax([p.crest_factor for p in profiles]))
    selected_idx = _greedy_farthest_point(features_boosted, seed, n)
    selected = [profiles[i] for i in selected_idx]
    return selected, features, selected_idx


def _select_transition(
    profiles: list[BeatProfile], n: int, weights: dict | None,
    song_structure: "SongStructure",
) -> tuple[list[BeatProfile], np.ndarray, list[int]]:
    """Select only bars near structural boundaries."""
    if not profiles:
        return [], np.zeros((0, 20)), []

    # Filter to bars with importance > 0 (near boundaries)
    transition_profiles = [
        p for p in profiles
        if song_structure.importance_for_bar(p.index) > 0
    ]

    if not transition_profiles:
        # No transitions found — fall back to max-diversity on all bars
        transition_profiles = profiles

    if len(transition_profiles) <= n:
        selected = transition_profiles
        feature_matrix = np.array([_feature_vector(p, weights) for p in selected]) if selected else np.zeros((0, 20))
        return selected, feature_matrix, list(range(len(selected)))

    # Greedy-select diverse bars from the transition pool
    features = _znorm(np.array([_feature_vector(p, weights) for p in transition_profiles]))
    seed = int(np.argmax([p.crest_factor for p in transition_profiles]))
    selected_idx = _greedy_farthest_point(features, seed, n)
    selected = [transition_profiles[i] for i in selected_idx]
    return selected, features, selected_idx


def curate(
    beat_dir: Path,
    n_bars: int = 14,
    strategy: str = "max-diversity",
    rms_floor: float = 0.005,
    crest_min: float = 4.0,
    distance_weights: dict[str, float] | None = None,
    song_structure: "SongStructure | None" = None,
) -> list[Path]:
    """
    Analyze every WAV in `beat_dir`, filter by rms_floor and crest_min,
    then select `n_bars` bars using the specified strategy.

    Strategies:
      - max-diversity: Greedy farthest-point in feature space (default)
      - rhythm-taxonomy: Cluster by rhythm fingerprint, pick diverse variants per cluster
      - sectional: Weight bars by structural importance (needs song_structure)
      - transition: Select only bars near structural boundaries (needs song_structure)

    Returns list of selected Paths in selection order.
    """
    beat_dir = Path(beat_dir)
    valid_strategies = ("max-diversity", "rhythm-taxonomy", "sectional", "transition")
    if strategy not in valid_strategies:
        raise ValueError(f"Unknown strategy: {strategy}. Valid: {valid_strategies}")

    # Sectional/transition need song structure — fall back if missing
    if strategy in ("sectional", "transition") and song_structure is None:
        warnings.warn(
            f"Strategy '{strategy}' requires song_structure; falling back to max-diversity.",
            stacklevel=2,
        )
        strategy = "max-diversity"

    profiles = analyze_all_beats(beat_dir)
    if not profiles:
        return []

    filtered = [p for p in profiles if p.rms >= rms_floor and p.crest_factor >= crest_min]
    if not filtered:
        filtered = [p for p in profiles if p.rms >= rms_floor] or profiles

    # ── Strategy dispatch ────────────────────────────────────────────────
    if strategy == "rhythm-taxonomy":
        selected, feature_matrix, selected_idx = _select_rhythm_taxonomy(
            filtered, n_bars, distance_weights
        )
    elif strategy == "sectional":
        selected, feature_matrix, selected_idx = _select_sectional(
            filtered, n_bars, distance_weights, song_structure
        )
    elif strategy == "transition":
        selected, feature_matrix, selected_idx = _select_transition(
            filtered, n_bars, distance_weights, song_structure
        )
    else:
        # max-diversity (default)
        if len(filtered) <= n_bars:
            selected = filtered
            feature_matrix = np.array([_feature_vector(p, distance_weights) for p in filtered]) if filtered else np.zeros((0, 20))
            selected_idx = list(range(len(filtered)))
        else:
            feature_matrix = _znorm(np.array([_feature_vector(p, distance_weights) for p in filtered]))
            seed = int(np.argmax([p.crest_factor for p in filtered]))
            selected_idx = _greedy_farthest_point(feature_matrix, seed, n_bars)
            selected = [filtered[i] for i in selected_idx]

    manifest = {
        "strategy": strategy,
        "n_bars": n_bars,
        "rms_floor": rms_floor,
        "crest_min": crest_min,
        "total_analyzed": len(profiles),
        "total_after_filter": len(filtered),
        "bars": [
            {
                "index": i + 1,
                "file": selected[i].path.name,
                "path": str(selected[i].path),
                "source_index": selected[i].index,
                "feature_vector": feature_matrix[selected_idx[i]].tolist() if len(feature_matrix) else [],
                "rms": round(selected[i].rms, 6),
                "crest_factor": round(selected[i].crest_factor, 3),
                "onset_count": selected[i].onset_count,
                "onset_density": round(selected[i].onset_density, 3),
                "spectral_centroid_hz": round(selected[i].spectral_centroid, 2),
                "spectral_bandwidth_hz": round(selected[i].spectral_bandwidth, 2),
                "rhythm_fingerprint": list(selected[i].rhythm_fingerprint),
            }
            for i in range(len(selected))
        ],
    }
    (beat_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return [p.path for p in selected]


# ── Back-compat helpers used by tools/ scripts ──

def cluster_by_rhythm(profiles: list[BeatProfile], threshold: float = 0.2) -> dict:
    clusters: dict = {}
    for p in profiles:
        if p.onset_count == 0:
            continue
        matched = False
        for key in clusters:
            ref = BeatProfile(path=Path(), index=0, rhythm_fingerprint=key)
            if rhythm_distance(p, ref) <= threshold:
                clusters[key].append(p)
                matched = True
                break
        if not matched:
            clusters[p.rhythm_fingerprint] = [p]
    return clusters


def select_variants_from_cluster(cluster: list[BeatProfile], max_variants: int = 3) -> list[BeatProfile]:
    if len(cluster) <= max_variants:
        return cluster
    def variant_dist(a, b):
        return spectral_distance(a, b) * 0.5 + energy_distance(a, b) * 0.5
    return greedy_diverse_select(cluster, max_variants, dist_fn=variant_dist)


def format_beat_report(profiles: list[BeatProfile], label: str = "") -> str:
    lines = [f"\n{'='*60}", f"  CURATED BEAT SET: {label}",
             f"  {len(profiles)} beats selected", f"{'='*60}\n"]
    for i, p in enumerate(profiles):
        fp_str = ''.join(['x' if b else '.' for b in p.rhythm_fingerprint])
        lines.append(
            f"  #{i+1:02d}  beat_{p.index:03d}  "
            f"onsets={p.onset_count}  density={p.onset_density:.1f}/s  "
            f"crest={p.crest_factor:.1f}  centroid={p.spectral_centroid:.0f}Hz  "
            f"pattern=[{fp_str}]"
        )
    lines.append("")
    return "\n".join(lines)


def export_curated_set(profiles: list[BeatProfile], output_dir: Path, label: str = "curated"):
    out = Path(output_dir) / label
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"label": label, "count": len(profiles), "beats": []}
    for i, p in enumerate(profiles):
        dest = out / f"{label}_{i+1:02d}_beat{p.index:03d}.wav"
        shutil.copy2(p.path, dest)
        manifest["beats"].append({
            "file": dest.name,
            "source_beat": p.index,
            "onset_count": p.onset_count,
            "onset_density": round(p.onset_density, 2),
            "crest_factor": round(p.crest_factor, 2),
            "spectral_centroid_hz": round(p.spectral_centroid, 1),
            "rhythm_pattern": ''.join(['x' if b else '.' for b in p.rhythm_fingerprint]),
            "rms": round(p.rms, 4),
        })
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return out
