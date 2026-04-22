"""
beat_detect.py — Neural downbeat detection via beat-this transformer.

Uses the CPJKU beat-this model (ISMIR 2024) for joint beat + downbeat
detection. Falls back to librosa beat_track() when beat-this is not
installed.

Requires: beat-this>=1.1.0, torch>=2.1.0
Install:  uv pip install 'stemforge[beat]'
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def _select_device(requested: str = "auto") -> str:
    """Pick the best available torch device.

    Priority: requested > MPS (Apple Silicon) > CPU.
    Returns a device string suitable for torch and beat-this.
    """
    if requested not in ("auto", "cpu", "mps", "cuda"):
        return "cpu"
    if requested != "auto":
        return requested

    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def detect_beats_and_downbeats(
    audio_path: Path,
    device: str = "auto",
) -> tuple[float, np.ndarray, np.ndarray]:
    """Detect BPM, beats, and downbeats using beat-this transformer model.

    Uses the 'final0' checkpoint (large model, best accuracy).
    Falls back to librosa beat_track() if beat-this is not available.

    Args:
        audio_path: Path to audio file (WAV, FLAC, etc.).
        device: Torch device — "auto" (default), "cpu", "mps", or "cuda".
            "auto" tries MPS first (Apple Silicon), then CUDA, then CPU.

    Returns:
        Tuple of (bpm, beat_times, downbeat_times).
        beat_times: all beat positions in seconds.
        downbeat_times: bar start positions in seconds (subset of beat_times).
    """
    try:
        from beat_this.inference import File2Beats

        device_str = _select_device(device)
        logger.info("beat-this: using device=%s, checkpoint=final0", device_str)

        model = File2Beats(checkpoint_path="final0", device=device_str, dbn=False)
        beats, downbeats = model(audio_path)

        # beats and downbeats are numpy arrays of times in seconds
        beats = np.asarray(beats, dtype=float)
        downbeats = np.asarray(downbeats, dtype=float)

        if len(beats) < 2:
            logger.warning("beat-this returned <2 beats, falling back to librosa")
            return _fallback_librosa(audio_path)

        # Calculate BPM from median inter-beat interval
        ibis = np.diff(beats)
        bpm = 60.0 / float(np.median(ibis))

        logger.info(
            "beat-this: %.1f BPM, %d beats, %d downbeats",
            bpm,
            len(beats),
            len(downbeats),
        )
        return bpm, beats, downbeats

    except ImportError:
        logger.info("beat-this not installed, falling back to librosa beat_track()")
        return _fallback_librosa(audio_path)
    except Exception as e:
        logger.warning("beat-this failed (%s), falling back to librosa", e)
        return _fallback_librosa(audio_path)


def _fallback_librosa(audio_path: Path) -> tuple[float, np.ndarray, np.ndarray]:
    """Fallback: use librosa beat_track() when beat-this is unavailable.

    Returns (bpm, beat_times, empty_downbeats). The empty downbeat array
    signals to callers that proper downbeat detection was not available.
    """
    from stemforge.slicer import detect_bpm_and_beats

    bpm, beat_times = detect_bpm_and_beats(audio_path)
    # Return empty downbeat array — callers should use stride-based bar detection
    return bpm, beat_times, np.array([], dtype=float)
