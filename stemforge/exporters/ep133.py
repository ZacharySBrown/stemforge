"""
stemforge.exporters.ep133 — Teenage Engineering EP-133 KO II exporter.

Formats stems/slices for the EP-133:
  - 46875 Hz (or 22050 Hz budget mode), 16-bit, mono
  - 4 groups × 12 pads = 48 slots per project
  - Group A: drum one-shots, Group B: bass (KEYS), Group C: melodic (KEYS), Group D: loops
  - Memory: 128 MB (~24 min mono at native rate)
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from .base import (
    AbstractExporter, ExportManifest, ExportSlot,
    write_export_wav,
)

console = Console()

# EP-133 constants
NATIVE_RATE = 46875
BUDGET_RATE = 22050
MEMORY_BYTES = 128 * 1024 * 1024  # 128 MB
MAX_DURATION_S = 20.0
PADS_PER_GROUP = 12
GROUPS = ["A", "B", "C", "D"]

# Default stem → group mapping
DEFAULT_GROUP_MAP = {
    "A": "drums",       # drum one-shots
    "B": "bass",        # bass slices (KEYS mode)
    "C": "vocals",      # melodic snippets (KEYS mode)
    "D": "loops",       # short loops from any stem
}

STEM_NAMES = ["drums", "bass", "vocals", "other"]


class EP133Exporter(AbstractExporter):

    def __init__(self, budget: bool = False, group_overrides: dict[str, str] | None = None):
        self._budget = budget
        self._group_map = dict(DEFAULT_GROUP_MAP)
        if group_overrides:
            self._group_map.update(group_overrides)

    @property
    def device_name(self) -> str:
        return "ep133"

    @property
    def target_sample_rate(self) -> int:
        return BUDGET_RATE if self._budget else NATIVE_RATE

    @property
    def target_bit_depth(self) -> int:
        return 16

    @property
    def target_channels(self) -> int:
        return 1  # mono

    @property
    def max_sample_duration_s(self) -> float:
        return MAX_DURATION_S

    @property
    def memory_limit_bytes(self) -> int:
        return MEMORY_BYTES

    def _collect_stem_files(self, track_dir: Path, stem: str, subdir: str) -> list[Path]:
        """Collect WAV files from a stem's subdirectory."""
        d = track_dir / f"{stem}_{subdir}"
        if not d.exists():
            # Try curated dir
            d = track_dir / "curated" / stem / subdir
        if not d.exists():
            d = track_dir / "curated" / stem
        if not d.exists():
            return []
        return sorted(d.glob("*.wav"))

    def _collect_loops(self, track_dir: Path) -> list[tuple[Path, str]]:
        """Collect short loops from all stems for Group D."""
        loops: list[tuple[Path, str]] = []
        for stem in STEM_NAMES:
            bar_dir = track_dir / f"{stem}_bars"
            if bar_dir.exists():
                for f in sorted(bar_dir.glob("*.wav"))[:3]:  # max 3 per stem
                    loops.append((f, stem))
            # Also check curated loops
            curated = track_dir / "curated" / stem
            if curated.exists():
                for f in sorted(curated.glob("*.wav"))[:3]:
                    loops.append((f, stem))
        return loops

    def export_compose(self, track_dir: Path, output_dir: Path) -> ExportManifest:
        """Export all material from one track into an EP-133 project."""
        output_dir.mkdir(parents=True, exist_ok=True)
        track_name = track_dir.name
        manifest = self._new_manifest("compose", [track_name])

        console.print(f"  [cyan]EP-133[/cyan] compose: {track_name}")
        slot_num = 1

        # Group A: drum one-shots (beats or curated oneshots)
        drum_files = (
            self._collect_stem_files(track_dir, "drums", "oneshots")
            or self._collect_stem_files(track_dir, "drums", "beats")
        )
        for i, wav in enumerate(drum_files[:PADS_PER_GROUP]):
            audio, sr = self._prepare_sample(wav)
            fname = f"{slot_num:03d}_{track_name}_drums_{i+1}.wav"
            size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
            manifest.slots.append(ExportSlot(
                slot=slot_num, group="A", pad=i+1, file=fname,
                source_track=track_name, source_stem="drums", source_file=str(wav),
                duration_s=len(audio) / sr, size_bytes=size,
            ))
            manifest.memory_used_bytes += size
            slot_num += 1
        console.print(f"    Group A (drums): {min(len(drum_files), PADS_PER_GROUP)} pads")

        # Group B: bass slices
        bass_files = (
            self._collect_stem_files(track_dir, "bass", "oneshots")
            or self._collect_stem_files(track_dir, "bass", "beats")
        )
        for i, wav in enumerate(bass_files[:PADS_PER_GROUP]):
            audio, sr = self._prepare_sample(wav)
            fname = f"{slot_num:03d}_{track_name}_bass_{i+1}.wav"
            size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
            manifest.slots.append(ExportSlot(
                slot=slot_num, group="B", pad=i+1, file=fname,
                source_track=track_name, source_stem="bass", source_file=str(wav),
                duration_s=len(audio) / sr, size_bytes=size,
            ))
            manifest.memory_used_bytes += size
            slot_num += 1
        console.print(f"    Group B (bass):  {min(len(bass_files), PADS_PER_GROUP)} pads")

        # Group C: vocals/other (melodic)
        melodic_stem = self._group_map.get("C", "vocals")
        melodic_files = (
            self._collect_stem_files(track_dir, melodic_stem, "oneshots")
            or self._collect_stem_files(track_dir, melodic_stem, "beats")
        )
        for i, wav in enumerate(melodic_files[:PADS_PER_GROUP]):
            audio, sr = self._prepare_sample(wav)
            fname = f"{slot_num:03d}_{track_name}_{melodic_stem}_{i+1}.wav"
            size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
            manifest.slots.append(ExportSlot(
                slot=slot_num, group="C", pad=i+1, file=fname,
                source_track=track_name, source_stem=melodic_stem, source_file=str(wav),
                duration_s=len(audio) / sr, size_bytes=size,
            ))
            manifest.memory_used_bytes += size
            slot_num += 1
        console.print(f"    Group C ({melodic_stem}): {min(len(melodic_files), PADS_PER_GROUP)} pads")

        # Group D: short loops
        loops = self._collect_loops(track_dir)
        for i, (wav, stem) in enumerate(loops[:PADS_PER_GROUP]):
            audio, sr = self._prepare_sample(wav)
            fname = f"{slot_num:03d}_{track_name}_loop_{stem}_{i+1}.wav"
            size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
            manifest.slots.append(ExportSlot(
                slot=slot_num, group="D", pad=i+1, file=fname,
                source_track=track_name, source_stem=stem, source_file=str(wav),
                duration_s=len(audio) / sr, size_bytes=size,
            ))
            manifest.memory_used_bytes += size
            slot_num += 1
        console.print(f"    Group D (loops): {min(len(loops), PADS_PER_GROUP)} pads")

        console.print(f"    Memory: {manifest.memory_used_bytes / 1024:.0f} KB / {MEMORY_BYTES / 1024 / 1024:.0f} MB ({manifest.memory_pct:.1f}%)")
        manifest.write(output_dir / "export.json")
        return manifest

    def export_perform(self, tracks_dir: Path, output_dir: Path) -> ExportManifest:
        """Export curated material across multiple tracks."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Find all processed track directories
        track_dirs = sorted([
            d for d in tracks_dir.iterdir()
            if d.is_dir() and (d / "drums.wav").exists()
        ])
        track_names = [d.name for d in track_dirs]
        manifest = self._new_manifest("perform", track_names)

        console.print(f"  [cyan]EP-133[/cyan] perform: {len(track_dirs)} tracks")

        # Collect candidates across all tracks, then pick most diverse
        all_drums: list[tuple[Path, str]] = []
        all_bass: list[tuple[Path, str]] = []
        all_melodic: list[tuple[Path, str]] = []
        all_loops: list[tuple[Path, str]] = []

        for td in track_dirs:
            for f in self._collect_stem_files(td, "drums", "beats")[:4]:
                all_drums.append((f, td.name))
            for f in self._collect_stem_files(td, "bass", "beats")[:4]:
                all_bass.append((f, td.name))
            for f in self._collect_stem_files(td, "vocals", "beats")[:4]:
                all_melodic.append((f, td.name))
            for f, stem in self._collect_loops(td)[:2]:
                all_loops.append((f, td.name))

        # Export (simple round-robin for now; curator integration is future work)
        slot_num = 1
        for group, candidates, label in [
            ("A", all_drums, "drums"),
            ("B", all_bass, "bass"),
            ("C", all_melodic, "melodic"),
            ("D", all_loops, "loops"),
        ]:
            for i, (wav, track_name) in enumerate(candidates[:PADS_PER_GROUP]):
                audio, sr = self._prepare_sample(wav)
                fname = f"{slot_num:03d}_{track_name}_{label}_{i+1}.wav"
                size = write_export_wav(audio, sr, output_dir / fname, self.target_bit_depth)
                manifest.slots.append(ExportSlot(
                    slot=slot_num, group=group, pad=i+1, file=fname,
                    source_track=track_name, source_stem=label, source_file=str(wav),
                    duration_s=len(audio) / sr, size_bytes=size,
                ))
                manifest.memory_used_bytes += size
                slot_num += 1
            console.print(f"    Group {group} ({label}): {min(len(candidates), PADS_PER_GROUP)} pads")

        console.print(f"    Memory: {manifest.memory_used_bytes / 1024:.0f} KB / {MEMORY_BYTES / 1024 / 1024:.0f} MB ({manifest.memory_pct:.1f}%)")
        manifest.write(output_dir / "export.json")
        return manifest
