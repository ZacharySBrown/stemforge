"""
stemforge.exporters.chompi — Chase Bliss Chompi (TEMPO firmware) exporter.

Formats stems/slices for Chompi:
  - 48000 Hz, 16-bit, stereo REQUIRED
  - Flat SD card root, no folders
  - Slice engine: slice_a1.wav – slice_a14.wav (auto-chopped into 16 segments)
  - Chroma engine: chroma_a1.wav – chroma_a14.wav (chromatic playback)
  - Max 10 seconds per slot
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from rich.console import Console

from .base import (
    AbstractExporter, ExportManifest, ExportSlot,
    resample_audio, to_stereo, peak_normalize, trim_to_duration,
    write_export_wav,
)

console = Console()

# Chompi TEMPO constants
SAMPLE_RATE = 48000
MAX_DURATION_S = 10.0
SLICE_SLOTS = 14
CHROMA_SLOTS = 14
MEMORY_BYTES = 4 * 1024 * 1024 * 1024  # 4 GB SD

STEM_NAMES = ["drums", "bass", "vocals", "other"]


def _bar_align_trim(audio: np.ndarray, sr: int, bpm: float, time_sig: int = 4) -> np.ndarray:
    """Trim audio to the nearest complete bar boundary (≤ max duration)."""
    if bpm <= 0:
        return trim_to_duration(audio, sr, MAX_DURATION_S)

    bar_duration_s = (60.0 / bpm) * time_sig
    total_samples = audio.shape[-1]
    total_duration = total_samples / sr

    # Find the largest number of complete bars that fits in max duration
    max_bars = int(min(total_duration, MAX_DURATION_S) / bar_duration_s)
    if max_bars <= 0:
        max_bars = 1

    trim_samples = int(max_bars * bar_duration_s * sr)
    if audio.ndim == 1:
        return audio[:trim_samples]
    return audio[:, :trim_samples]


class ChompiExporter(AbstractExporter):

    def __init__(self, firmware: str = "tempo"):
        self._firmware = firmware

    @property
    def device_name(self) -> str:
        return "chompi"

    @property
    def target_sample_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def target_bit_depth(self) -> int:
        return 16

    @property
    def target_channels(self) -> int:
        return 2  # stereo required

    @property
    def max_sample_duration_s(self) -> float:
        return MAX_DURATION_S

    @property
    def memory_limit_bytes(self) -> int:
        return MEMORY_BYTES

    def _prepare_for_chompi(self, wav_path: Path, bpm: float = 0) -> tuple[np.ndarray, int]:
        """Load, convert to stereo 48kHz 16-bit, bar-align trim."""
        audio, sr = sf.read(str(wav_path), always_2d=True)
        audio = audio.T  # (samples, channels) → (channels, samples)

        audio = to_stereo(audio)
        audio = resample_audio(audio, sr, SAMPLE_RATE)

        if bpm > 0:
            audio = _bar_align_trim(audio, SAMPLE_RATE, bpm)
        else:
            audio = trim_to_duration(audio, SAMPLE_RATE, MAX_DURATION_S)

        audio = peak_normalize(audio)
        return audio, SAMPLE_RATE

    def _read_bpm(self, track_dir: Path) -> float:
        """Try to read BPM from stems.json or curated manifest."""
        import json
        for mf_name in ["curated/manifest.json", "stems.json"]:
            mf_path = track_dir / mf_name
            if mf_path.exists():
                data = json.loads(mf_path.read_text())
                if "bpm" in data:
                    return float(data["bpm"])
        return 0

    def export_compose(self, track_dir: Path, output_dir: Path) -> ExportManifest:
        """Export one track for Chompi — stems to Slice, phrases to Chroma."""
        output_dir.mkdir(parents=True, exist_ok=True)
        track_name = track_dir.name
        bpm = self._read_bpm(track_dir)
        manifest = self._new_manifest("compose", [track_name])

        console.print(f"  [cyan]Chompi[/cyan] compose: {track_name} ({bpm:.0f} BPM)")

        # Slice engine: full stems (drums, bass preferred — clear transients)
        slice_slot = 1
        for stem in ["drums", "bass", "other", "vocals"]:
            if slice_slot > SLICE_SLOTS:
                break
            stem_path = track_dir / f"{stem}.wav"
            if not stem_path.exists():
                continue

            audio, sr = self._prepare_for_chompi(stem_path, bpm)
            fname = f"slice_a{slice_slot}.wav"
            size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)

            manifest.slots.append(ExportSlot(
                slot=slice_slot, group="slice", pad=slice_slot,
                file=fname, source_track=track_name, source_stem=stem,
                source_file=str(stem_path),
                duration_s=audio.shape[-1] / sr, size_bytes=size,
            ))
            manifest.memory_used_bytes += size
            slice_slot += 1

        # Also add curated bar loops to remaining Slice slots
        for stem in STEM_NAMES:
            if slice_slot > SLICE_SLOTS:
                break
            curated = track_dir / "curated" / stem
            if not curated.exists():
                continue
            for wav in sorted(curated.glob("*.wav"))[:2]:
                if slice_slot > SLICE_SLOTS:
                    break
                audio, sr = self._prepare_for_chompi(wav, bpm)
                fname = f"slice_a{slice_slot}.wav"
                size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
                manifest.slots.append(ExportSlot(
                    slot=slice_slot, group="slice", pad=slice_slot,
                    file=fname, source_track=track_name, source_stem=stem,
                    source_file=str(wav),
                    duration_s=audio.shape[-1] / sr, size_bytes=size,
                ))
                manifest.memory_used_bytes += size
                slice_slot += 1

        console.print(f"    Slice engine: {slice_slot - 1} slots")

        # Chroma engine: melodic phrases (vocals, guitar, bass notes)
        chroma_slot = 1
        for stem in ["vocals", "other", "bass"]:
            if chroma_slot > CHROMA_SLOTS:
                break
            # Prefer curated phrases
            phrase_dir = track_dir / f"{stem}_phrases"
            if not phrase_dir.exists():
                phrase_dir = track_dir / "curated" / stem
            if not phrase_dir.exists():
                continue

            for wav in sorted(phrase_dir.glob("*.wav"))[:4]:
                if chroma_slot > CHROMA_SLOTS:
                    break
                audio, sr = self._prepare_for_chompi(wav, bpm)
                fname = f"chroma_a{chroma_slot}.wav"
                size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
                manifest.slots.append(ExportSlot(
                    slot=chroma_slot, group="chroma", pad=chroma_slot,
                    file=fname, source_track=track_name, source_stem=stem,
                    source_file=str(wav),
                    duration_s=audio.shape[-1] / sr, size_bytes=size,
                ))
                manifest.memory_used_bytes += size
                chroma_slot += 1

        console.print(f"    Chroma engine: {chroma_slot - 1} slots")
        console.print(f"    Size: {manifest.memory_used_bytes / 1024 / 1024:.1f} MB")

        manifest.write(output_dir / "export.json")
        return manifest

    def export_perform(self, tracks_dir: Path, output_dir: Path) -> ExportManifest:
        """Export curated material across tracks for Chompi performance."""
        output_dir.mkdir(parents=True, exist_ok=True)

        track_dirs = sorted([
            d for d in tracks_dir.iterdir()
            if d.is_dir() and (d / "drums.wav").exists()
        ])
        track_names = [d.name for d in track_dirs]
        manifest = self._new_manifest("perform", track_names)

        console.print(f"  [cyan]Chompi[/cyan] perform: {len(track_dirs)} tracks")

        # Slice engine: best drum/groove stems across tracks
        slice_slot = 1
        for td in track_dirs:
            if slice_slot > SLICE_SLOTS:
                break
            bpm = self._read_bpm(td)
            # Prefer drums for slice engine
            stem_path = td / "drums.wav"
            if not stem_path.exists():
                continue

            audio, sr = self._prepare_for_chompi(stem_path, bpm)
            fname = f"slice_a{slice_slot}.wav"
            size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
            manifest.slots.append(ExportSlot(
                slot=slice_slot, group="slice", pad=slice_slot,
                file=fname, source_track=td.name, source_stem="drums",
                source_file=str(stem_path),
                duration_s=audio.shape[-1] / sr, size_bytes=size,
            ))
            manifest.memory_used_bytes += size
            slice_slot += 1

        console.print(f"    Slice engine: {slice_slot - 1} slots across {min(len(track_dirs), SLICE_SLOTS)} tracks")

        # Chroma engine: melodic phrases across tracks
        chroma_slot = 1
        for td in track_dirs:
            if chroma_slot > CHROMA_SLOTS:
                break
            bpm = self._read_bpm(td)
            # Find a melodic phrase
            for stem in ["vocals", "other", "bass"]:
                phrase_dir = td / "curated" / stem
                if not phrase_dir.exists():
                    phrase_dir = td / f"{stem}_phrases"
                if not phrase_dir.exists():
                    continue
                wavs = sorted(phrase_dir.glob("*.wav"))
                if not wavs:
                    continue
                wav = wavs[0]  # best phrase

                audio, sr = self._prepare_for_chompi(wav, bpm)
                fname = f"chroma_a{chroma_slot}.wav"
                size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
                manifest.slots.append(ExportSlot(
                    slot=chroma_slot, group="chroma", pad=chroma_slot,
                    file=fname, source_track=td.name, source_stem=stem,
                    source_file=str(wav),
                    duration_s=audio.shape[-1] / sr, size_bytes=size,
                ))
                manifest.memory_used_bytes += size
                chroma_slot += 1
                break  # one phrase per track

        console.print(f"    Chroma engine: {chroma_slot - 1} slots")
        console.print(f"    Size: {manifest.memory_used_bytes / 1024 / 1024:.1f} MB")

        manifest.write(output_dir / "export.json")
        return manifest
