"""
beat_curator.py — Proto-tools for rhythmic beat curation.
Analyzes beat slices for transient patterns, spectral character,
and rhythmic diversity to curate optimal sample sets for IDM chopping.
"""

import numpy as np
import soundfile as sf
from pathlib import Path
from dataclasses import dataclass, field
import json


@dataclass
class BeatProfile:
    """Analysis profile for a single beat slice."""
    path: Path
    index: int
    # Timing / transients
    duration: float = 0.0
    onset_times: list = field(default_factory=list)  # relative onset positions (0-1)
    onset_count: int = 0
    onset_density: float = 0.0  # onsets per second
    # Envelope
    rms: float = 0.0
    peak: float = 0.0
    crest_factor: float = 0.0  # peak/rms ratio — higher = more transient
    attack_time: float = 0.0  # time to reach peak (s)
    # Spectral
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    spectral_flatness: float = 0.0
    # Rhythmic pattern fingerprint (quantized onset grid)
    rhythm_fingerprint: tuple = ()  # e.g. (1,0,0,1,0,1,0,0) for 8th-note grid
    # Energy distribution
    energy_curve: list = field(default_factory=list)  # energy in N equal slices


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    """Load audio file, mix to mono, normalize."""
    data, sr = sf.read(str(path))
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


def detect_onsets(audio: np.ndarray, sr: int, threshold_ratio: float = 0.3) -> list[float]:
    """
    Simple onset detection via spectral flux.
    Returns onset times in seconds.
    """
    hop = sr // 100  # 10ms hop
    n_fft = 2048

    # Compute spectral flux
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

    # Peak picking with minimum distance
    min_dist = int(0.03 * sr / hop)  # 30ms minimum between onsets
    onsets = []
    for i in range(1, len(flux) - 1):
        if flux[i] > threshold and flux[i] > flux[i-1] and flux[i] >= flux[i+1]:
            if not onsets or (i - onsets[-1]) >= min_dist:
                onsets.append(i)

    return [i * hop / sr for i in onsets]


def compute_rhythm_fingerprint(onset_times: list, duration: float, grid_size: int = 16) -> tuple:
    """
    Quantize onsets to a grid (e.g., 16th notes) to create a binary rhythm pattern.
    """
    grid = [0] * grid_size
    for t in onset_times:
        pos = int((t / duration) * grid_size) if duration > 0 else 0
        if 0 <= pos < grid_size:
            grid[pos] = 1
    return tuple(grid)


def compute_energy_curve(audio: np.ndarray, n_segments: int = 8) -> list[float]:
    """Split audio into segments, compute RMS of each."""
    seg_len = len(audio) // n_segments
    if seg_len == 0:
        return [0.0] * n_segments
    energies = []
    for i in range(n_segments):
        seg = audio[i * seg_len:(i + 1) * seg_len]
        energies.append(float(np.sqrt(np.mean(seg ** 2))))
    return energies


def spectral_features(audio: np.ndarray, sr: int) -> dict:
    """Compute spectral centroid, bandwidth, flatness."""
    n_fft = min(2048, len(audio))
    if n_fft < 64:
        return {"centroid": 0.0, "bandwidth": 0.0, "flatness": 0.0}

    spec = np.abs(np.fft.rfft(audio[:n_fft] * np.hanning(n_fft)))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)

    total = np.sum(spec) + 1e-10
    centroid = float(np.sum(freqs * spec) / total)
    bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * spec) / total))

    # Spectral flatness: geometric mean / arithmetic mean
    log_spec = np.log(spec + 1e-10)
    geo_mean = np.exp(np.mean(log_spec))
    arith_mean = np.mean(spec)
    flatness = float(geo_mean / (arith_mean + 1e-10))

    return {"centroid": centroid, "bandwidth": bandwidth, "flatness": flatness}


def analyze_beat(path: Path, index: int) -> BeatProfile:
    """Full analysis of a single beat slice."""
    audio, sr = load_mono(path)
    duration = len(audio) / sr

    # Skip very short or silent beats
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if duration < 0.05 or rms < 0.001:
        return BeatProfile(path=path, index=index, duration=duration, rms=rms)

    # Onsets
    onsets = detect_onsets(audio, sr)

    # Envelope
    peak = float(np.max(np.abs(audio)))
    crest = peak / (rms + 1e-10)

    # Attack time: time to reach peak
    peak_idx = np.argmax(np.abs(audio))
    attack_time = peak_idx / sr

    # Spectral
    spec = spectral_features(audio, sr)

    # Rhythm fingerprint
    fingerprint = compute_rhythm_fingerprint(onsets, duration, grid_size=16)

    # Energy curve
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
    """Analyze all beat slices in a directory."""
    files = sorted(beats_dir.glob("*.wav"))
    profiles = []
    for i, f in enumerate(files):
        bp = analyze_beat(f, i + 1)
        profiles.append(bp)
    return profiles


# ── Clustering / Dedup Tools ──

def rhythm_distance(a: BeatProfile, b: BeatProfile) -> float:
    """Hamming distance between rhythm fingerprints, normalized 0-1."""
    if not a.rhythm_fingerprint or not b.rhythm_fingerprint:
        return 1.0
    return sum(x != y for x, y in zip(a.rhythm_fingerprint, b.rhythm_fingerprint)) / len(a.rhythm_fingerprint)


def spectral_distance(a: BeatProfile, b: BeatProfile) -> float:
    """Normalized distance in spectral feature space."""
    dc = abs(a.spectral_centroid - b.spectral_centroid) / (max(a.spectral_centroid, b.spectral_centroid) + 1e-10)
    db = abs(a.spectral_bandwidth - b.spectral_bandwidth) / (max(a.spectral_bandwidth, b.spectral_bandwidth) + 1e-10)
    df = abs(a.spectral_flatness - b.spectral_flatness)
    return (dc + db + df) / 3


def energy_distance(a: BeatProfile, b: BeatProfile) -> float:
    """Euclidean distance between energy curves, normalized."""
    if not a.energy_curve or not b.energy_curve:
        return 1.0
    ea = np.array(a.energy_curve)
    eb = np.array(b.energy_curve)
    mx = max(np.max(ea), np.max(eb), 1e-10)
    return float(np.sqrt(np.mean(((ea - eb) / mx) ** 2)))


def composite_distance(a: BeatProfile, b: BeatProfile,
                       w_rhythm: float = 0.5, w_spectral: float = 0.25, w_energy: float = 0.25) -> float:
    """Weighted composite distance."""
    return (w_rhythm * rhythm_distance(a, b) +
            w_spectral * spectral_distance(a, b) +
            w_energy * energy_distance(a, b))


def greedy_diverse_select(profiles: list[BeatProfile], n: int,
                          dist_fn=composite_distance) -> list[BeatProfile]:
    """
    Greedy farthest-point selection for maximum diversity.
    Start with the highest-energy beat, then iteratively pick the beat
    most distant from all already-selected beats.
    """
    if len(profiles) <= n:
        return profiles

    # Filter out near-silent beats
    active = [p for p in profiles if p.rms > 0.005 and p.onset_count > 0]
    if len(active) <= n:
        return active

    # Seed: highest crest factor (most punchy)
    selected = [max(active, key=lambda p: p.crest_factor)]
    remaining = [p for p in active if p is not selected[0]]

    while len(selected) < n and remaining:
        # Pick beat with maximum minimum distance to any selected beat
        best = max(remaining, key=lambda p: min(dist_fn(p, s) for s in selected))
        selected.append(best)
        remaining.remove(best)

    return selected


def cluster_by_rhythm(profiles: list[BeatProfile], threshold: float = 0.2) -> dict[tuple, list[BeatProfile]]:
    """
    Group beats by similar rhythm fingerprints.
    Beats within `threshold` hamming distance are merged into same cluster.
    """
    clusters: dict[tuple, list[BeatProfile]] = {}

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
    """
    Within a rhythm cluster, pick variants that differ in spectral/energy character.
    """
    if len(cluster) <= max_variants:
        return cluster

    def variant_dist(a, b):
        return spectral_distance(a, b) * 0.5 + energy_distance(a, b) * 0.5

    return greedy_diverse_select(cluster, max_variants, dist_fn=variant_dist)


# ── Output / Reporting ──

def format_beat_report(profiles: list[BeatProfile], label: str = "") -> str:
    """Human-readable report of selected beats."""
    lines = [f"\n{'='*60}", f"  CURATED BEAT SET: {label}", f"  {len(profiles)} beats selected", f"{'='*60}\n"]

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
    """Copy selected beats to a curated output directory with manifest."""
    import shutil
    out = output_dir / label
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "label": label,
        "count": len(profiles),
        "beats": []
    }

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

    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    return out
