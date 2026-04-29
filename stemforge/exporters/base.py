"""
stemforge.exporters.base — Abstract base class for hardware sample exporters.

Shared utilities: resample, bit-depth conversion, mono/stereo, normalization,
peak trim. Device-specific exporters extend this.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


@dataclass
class ExportSlot:
    """One sample slot in the export."""
    slot: int
    group: str                  # "A"/"B"/"C"/"D" (EP-133) or "slice"/"chroma" (Chompi)
    pad: int                    # pad number within group (1-indexed)
    file: str                   # output filename
    source_track: str = ""
    source_stem: str = ""
    source_file: str = ""       # original WAV path
    duration_s: float = 0.0
    size_bytes: int = 0


@dataclass
class ExportManifest:
    """Export result manifest."""
    device: str
    workflow: str
    source_tracks: list[str] = field(default_factory=list)
    sample_rate: int = 44100
    bit_depth: int = 16
    channels: int = 1
    slots: list[ExportSlot] = field(default_factory=list)
    memory_used_bytes: int = 0
    memory_total_bytes: int = 0
    exported_at: str = ""

    @property
    def memory_pct(self) -> float:
        if self.memory_total_bytes == 0:
            return 0
        return round(self.memory_used_bytes / self.memory_total_bytes * 100, 2)

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "workflow": self.workflow,
            "source_tracks": self.source_tracks,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "slots": [
                {
                    "slot": s.slot,
                    "group": s.group,
                    "pad": s.pad,
                    "file": s.file,
                    "source_track": s.source_track,
                    "source_stem": s.source_stem,
                    "duration_s": round(s.duration_s, 3),
                    "size_bytes": s.size_bytes,
                }
                for s in self.slots
            ],
            "memory_used_bytes": self.memory_used_bytes,
            "memory_total_bytes": self.memory_total_bytes,
            "memory_pct": self.memory_pct,
            "exported_at": self.exported_at,
        }

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))


def resample_audio(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Resample audio array. Handles both mono and stereo."""
    if sr_in == sr_out:
        return audio
    if audio.ndim == 1:
        return librosa.resample(audio, orig_sr=sr_in, target_sr=sr_out)
    # Stereo: resample each channel
    return np.stack([
        librosa.resample(audio[i], orig_sr=sr_in, target_sr=sr_out)
        for i in range(audio.shape[0])
    ])


def to_mono(audio: np.ndarray) -> np.ndarray:
    """Downmix to mono. Input: (channels, samples) or (samples,)."""
    if audio.ndim == 1:
        return audio
    return audio.mean(axis=0)


def to_stereo(audio: np.ndarray) -> np.ndarray:
    """Ensure stereo. Input: (samples,) or (channels, samples)."""
    if audio.ndim == 1:
        return np.stack([audio, audio])
    if audio.shape[0] == 1:
        return np.stack([audio[0], audio[0]])
    return audio[:2]  # take first 2 channels


def peak_normalize(audio: np.ndarray, headroom_db: float = -1.0) -> np.ndarray:
    """Peak-normalize to target headroom."""
    peak = np.max(np.abs(audio))
    if peak == 0:
        return audio
    target = 10 ** (headroom_db / 20)
    return audio * (target / peak)


def trim_to_duration(audio: np.ndarray, sr: int, max_duration_s: float) -> np.ndarray:
    """Trim audio to max duration."""
    max_samples = int(max_duration_s * sr)
    if audio.ndim == 1:
        return audio[:max_samples]
    return audio[:, :max_samples]


def write_export_wav(
    audio: np.ndarray,
    sr: int,
    path: Path,
    bit_depth: int = 16,
) -> int:
    """Write WAV file and return size in bytes."""
    subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[bit_depth]
    # soundfile expects (samples, channels) for stereo
    if audio.ndim > 1:
        write_data = audio.T
    else:
        write_data = audio
    sf.write(str(path), write_data, sr, subtype=subtype)
    return path.stat().st_size


class AbstractExporter(ABC):
    """Base class for hardware sample exporters."""

    @property
    @abstractmethod
    def device_name(self) -> str:
        ...

    @property
    @abstractmethod
    def target_sample_rate(self) -> int:
        ...

    @property
    @abstractmethod
    def target_bit_depth(self) -> int:
        ...

    @property
    @abstractmethod
    def target_channels(self) -> int:
        """1 = mono, 2 = stereo."""
        ...

    @property
    @abstractmethod
    def max_sample_duration_s(self) -> float:
        ...

    @property
    @abstractmethod
    def memory_limit_bytes(self) -> int:
        ...

    @abstractmethod
    def export_compose(self, track_dir: Path, output_dir: Path) -> ExportManifest:
        """Export all material from a single track."""
        ...

    @abstractmethod
    def export_perform(self, tracks_dir: Path, output_dir: Path) -> ExportManifest:
        """Export curated material across multiple tracks."""
        ...

    def _prepare_sample(self, wav_path: Path) -> tuple[np.ndarray, int]:
        """Load and convert a WAV to the target format."""
        audio, sr = sf.read(str(wav_path), always_2d=True)
        audio = audio.T  # (samples, channels) → (channels, samples)

        # Channel conversion
        if self.target_channels == 1:
            audio = to_mono(audio)
        else:
            audio = to_stereo(audio)

        # Resample
        audio = resample_audio(audio, sr, self.target_sample_rate)

        # Trim
        audio = trim_to_duration(audio, self.target_sample_rate, self.max_sample_duration_s)

        # Normalize
        audio = peak_normalize(audio)

        return audio, self.target_sample_rate

    def _new_manifest(self, workflow: str, source_tracks: list[str]) -> ExportManifest:
        return ExportManifest(
            device=self.device_name,
            workflow=workflow,
            source_tracks=source_tracks,
            sample_rate=self.target_sample_rate,
            bit_depth=self.target_bit_depth,
            channels=self.target_channels,
            memory_total_bytes=self.memory_limit_bytes,
            exported_at=datetime.now(timezone.utc).isoformat(),
        )
