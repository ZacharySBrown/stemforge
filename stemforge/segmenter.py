"""
stemforge.segmenter — Song structure detection via self-similarity analysis.

Detects structural boundaries (verse→chorus, chorus→bridge) using chroma-based
recurrence matrices and novelty curves. Output is a SongStructure that the
curator uses for sectional and transition strategies.

Algorithm:
  1. Compute chroma features (12D harmonic representation)
  2. Build recurrence matrix (self-similarity)
  3. Compute novelty curve via checkerboard kernel on the diagonal
  4. Peak-pick boundaries, snap to bar grid
  5. Label segments by mutual similarity (A, B, C, ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import find_peaks

from .config import SongConfig


@dataclass
class SongSegment:
    label: str              # "A", "B", "C", etc.
    start_bar: int          # 1-indexed
    end_bar: int            # inclusive
    start_time: float       # seconds
    end_time: float
    novelty_score: float    # how different this boundary is from neighbors (0-1)
    is_transition: bool     # True if near a structural boundary


@dataclass
class SongStructure:
    segments: list[SongSegment]
    form: str                           # e.g. "AABA", "ABAB"
    boundaries_bars: list[int]          # bar numbers where structure changes
    bar_importance: dict[int, float]    # per-bar structural importance score (0-1)
    total_bars: int

    def importance_for_bar(self, bar_idx: int) -> float:
        """Get structural importance for a bar (1-indexed). Higher = near boundary."""
        return self.bar_importance.get(bar_idx, 0.0)

    def section_for_bar(self, bar_idx: int) -> str | None:
        """Get section label for a bar (1-indexed)."""
        for seg in self.segments:
            if seg.start_bar <= bar_idx <= seg.end_bar:
                return seg.label
        return None


def _compute_novelty(recurrence: np.ndarray, kernel_size: int = 64) -> np.ndarray:
    """Compute novelty curve from recurrence matrix using checkerboard kernel."""
    n = recurrence.shape[0]
    if n < kernel_size:
        kernel_size = max(4, n // 2)

    half = kernel_size // 2
    # Checkerboard kernel: +1 on diagonal blocks (same section = high similarity),
    # -1 on off-diagonal blocks (cross section = low similarity at boundary)
    kernel = -np.ones((kernel_size, kernel_size))
    kernel[:half, :half] = 1
    kernel[half:, half:] = 1

    novelty = np.zeros(n)
    for i in range(half, n - half):
        patch = recurrence[i - half:i + half, i - half:i + half]
        if patch.shape == kernel.shape:
            novelty[i] = np.sum(patch * kernel)

    # Normalize to [0, 1]
    mx = np.max(np.abs(novelty))
    if mx > 0:
        novelty = novelty / mx
    # Only keep positive novelty (transitions, not self-similarity)
    novelty = np.maximum(novelty, 0)
    return novelty


def _label_segments(
    boundaries: list[int],
    total_frames: int,
    chroma: np.ndarray,
    hop_length: int,
    sr: int,
    mfcc: np.ndarray | None = None,
) -> list[str]:
    """Label segments by chroma + MFCC similarity.

    Chroma captures harmonic content (key/chord changes).
    MFCC captures timbral content (voice changes, instrument texture shifts).
    Combined, they distinguish sections that share harmony but differ in
    timbre (e.g., different rappers over the same beat).
    """
    n_segments = len(boundaries) + 1
    if n_segments == 1:
        return ["A"]

    all_bounds = [0] + boundaries + [total_frames]

    # Build per-segment feature vectors: chroma (12D) + optional MFCC (13D)
    segment_features = []
    for i in range(n_segments):
        start_frame = all_bounds[i]
        end_frame = all_bounds[i + 1]

        if start_frame < chroma.shape[1] and end_frame <= chroma.shape[1]:
            seg_chroma = chroma[:, start_frame:end_frame].mean(axis=1)
        else:
            seg_chroma = np.zeros(12)

        if mfcc is not None and start_frame < mfcc.shape[1] and end_frame <= mfcc.shape[1]:
            seg_mfcc_mean = mfcc[:, start_frame:end_frame].mean(axis=1)
            seg_mfcc_std = mfcc[:, start_frame:end_frame].std(axis=1)
        else:
            seg_mfcc_mean = np.zeros(13) if mfcc is not None else np.array([])
            seg_mfcc_std = np.zeros(13) if mfcc is not None else np.array([])

        # Concatenate: chroma (12D harmony) + MFCC mean (13D timbre) + MFCC std (13D variability)
        # The std captures voice texture differences that mean alone washes out
        feature = np.concatenate([seg_chroma, seg_mfcc_mean, seg_mfcc_std])
        segment_features.append(feature)

    segment_features = np.array(segment_features)

    # Cosine similarity between all pairs
    norms = np.linalg.norm(segment_features, axis=1, keepdims=True)
    norms = np.where(norms < 1e-10, 1.0, norms)
    normalized = segment_features / norms
    similarity = normalized @ normalized.T

    # Assign labels: first segment = "A", subsequent segments get the same
    # label as the most similar earlier segment (if similarity > threshold),
    # otherwise get a new label
    threshold = 0.92
    labels = [""] * n_segments
    next_label = 0

    for i in range(n_segments):
        best_match = -1
        best_sim = 0
        for j in range(i):
            if similarity[i, j] > best_sim:
                best_sim = similarity[i, j]
                best_match = j

        if best_match >= 0 and best_sim > threshold:
            labels[i] = labels[best_match]
        else:
            labels[i] = chr(ord("A") + next_label)
            next_label = min(next_label + 1, 25)  # cap at Z

    return labels


def detect_song_structure(
    audio_path: Path,
    beat_times: np.ndarray | None = None,
    bpm: float | None = None,
    time_sig: int = 4,
    config: SongConfig | None = None,
) -> SongStructure:
    """
    Detect song structure from an audio file.

    Args:
        audio_path: Path to WAV (typically the full mix or drums stem)
        beat_times: Pre-computed beat times (seconds). If None, auto-detects.
        bpm: BPM (used for bar duration calculation)
        time_sig: Time signature numerator
        config: Song segmentation config

    Returns:
        SongStructure with labeled segments and per-bar importance scores
    """
    if config is None:
        config = SongConfig()

    # Load audio
    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)

    # Beat tracking if not provided
    if beat_times is None:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        if bpm is None:
            bpm = float(np.atleast_1d(tempo)[0])

    # Compute bar times
    bar_beat_count = int(time_sig)
    bar_times = beat_times[::bar_beat_count]
    total_bars = len(bar_times)

    if total_bars < 4:
        # Too short for meaningful structure detection
        return SongStructure(
            segments=[SongSegment("A", 1, total_bars, 0, len(y) / sr, 0, False)],
            form="A",
            boundaries_bars=[],
            bar_importance={i: 0.0 for i in range(1, total_bars + 1)},
            total_bars=total_bars,
        )

    # Compute chroma features
    hop_length = 512
    chroma = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=hop_length)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=hop_length, n_mfcc=13)

    # Build recurrence matrix
    rec = librosa.segment.recurrence_matrix(
        chroma, mode="affinity", sym=True, width=3,
    )

    # Compute novelty curve
    kernel_size = min(64, rec.shape[0] // 2)
    novelty = _compute_novelty(rec, kernel_size=kernel_size)

    # Convert bar times to frame indices for boundary snapping
    bar_frames = librosa.time_to_frames(bar_times, sr=sr, hop_length=hop_length)

    # Min distance between boundaries (in frames)
    min_bar_frames = config.min_segment_bars * bar_beat_count
    if bpm and bpm > 0:
        min_dist_frames = int(config.min_segment_bars * (60 / bpm) * bar_beat_count * sr / hop_length)
    else:
        min_dist_frames = min_bar_frames * 4  # fallback

    # Peak-pick boundaries from novelty curve
    # Use a lower prominence to catch more boundaries, then rank by prominence
    peaks, properties = find_peaks(
        novelty,
        distance=max(1, min_dist_frames // 2),
        prominence=0.05,
    )

    if len(peaks) == 0:
        return SongStructure(
            segments=[SongSegment("A", 1, total_bars, 0, len(y) / sr, 0, False)],
            form="A",
            boundaries_bars=[],
            bar_importance={i: 0.0 for i in range(1, total_bars + 1)},
            total_bars=total_bars,
        )

    # Rank by prominence, keep top max_segments-1 boundaries
    prominences = properties.get("prominences", novelty[peaks])
    ranked = np.argsort(prominences)[::-1]
    top_peaks = sorted(peaks[ranked[:config.max_segments - 1]])

    # Snap each peak to the nearest bar boundary
    boundaries_bars = []
    for peak_frame in top_peaks:
        distances = np.abs(bar_frames - peak_frame)
        nearest_bar_idx = int(np.argmin(distances))
        bar_num = nearest_bar_idx + 1  # 1-indexed
        if 1 < bar_num < total_bars and bar_num not in boundaries_bars:
            boundaries_bars.append(bar_num)

    boundaries_bars.sort()

    # Label segments
    labels = _label_segments(
        [librosa.time_to_frames(bar_times[b - 1], sr=sr, hop_length=hop_length)
         for b in boundaries_bars],
        chroma.shape[1],
        chroma,
        hop_length,
        sr,
        mfcc=mfcc,
    )

    # Build segments
    all_bounds = [1] + boundaries_bars + [total_bars + 1]
    segments = []
    for i in range(len(all_bounds) - 1):
        start_bar = all_bounds[i]
        end_bar = all_bounds[i + 1] - 1

        start_time = float(bar_times[start_bar - 1]) if start_bar - 1 < len(bar_times) else 0
        end_time = float(bar_times[end_bar - 1]) if end_bar - 1 < len(bar_times) else len(y) / sr

        # Novelty score = max novelty near this boundary
        if i > 0:
            boundary_frame = librosa.time_to_frames(
                bar_times[boundaries_bars[i - 1] - 1], sr=sr, hop_length=hop_length
            )
            window = max(1, min_dist_frames // 4)
            start_f = max(0, boundary_frame - window)
            end_f = min(len(novelty), boundary_frame + window)
            nov_score = float(np.max(novelty[start_f:end_f]))
        else:
            nov_score = 0.0

        segments.append(SongSegment(
            label=labels[i],
            start_bar=start_bar,
            end_bar=end_bar,
            start_time=start_time,
            end_time=end_time,
            novelty_score=nov_score,
            is_transition=False,
        ))

    # Compute per-bar structural importance
    # Bars near boundaries get high importance; bars in the middle get low
    bar_importance: dict[int, float] = {}
    transition_window = config.transition_window_bars

    for bar in range(1, total_bars + 1):
        min_dist_to_boundary = total_bars  # large default
        for b in boundaries_bars:
            dist = abs(bar - b)
            min_dist_to_boundary = min(min_dist_to_boundary, dist)

        if min_dist_to_boundary <= transition_window:
            importance = 1.0 - (min_dist_to_boundary / (transition_window + 1))
        else:
            importance = 0.0
        bar_importance[bar] = importance

    # Mark transition bars in segments
    for seg in segments:
        for bar in range(seg.start_bar, seg.end_bar + 1):
            if bar_importance.get(bar, 0) > 0.5:
                seg.is_transition = True
                break

    form = "".join(labels)

    return SongStructure(
        segments=segments,
        form=form,
        boundaries_bars=boundaries_bars,
        bar_importance=bar_importance,
        total_bars=total_bars,
    )
