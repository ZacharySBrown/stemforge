"""
stemforge.exporters.ep133_mapping — EP-133 slot + pad assignment data classes.

Maps export WAV files to library slots (1-999) and project/group/pad assignments.
Loaded from YAML files at <export_dir>/ep133_mapping.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


VALID_GROUPS = {"A", "B", "C", "D"}
MAX_SLOT = 999
MAX_PROJECT = 9
MAX_PAD = 12


@dataclass
class EP133PadAssignment:
    project: int     # 1-9
    group: str       # 'A' | 'B' | 'C' | 'D'
    pad: int         # 1-12
    slot: int        # 1-999 (library slot)


@dataclass
class EP133Mapping:
    """Maps export WAVs to library slots and project/group/pad assignments."""

    slot_assignments: dict[str, int] = field(default_factory=dict)   # filename -> slot
    pad_assignments: list[EP133PadAssignment] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Return list of validation errors. Empty list = valid."""
        errors: list[str] = []

        # Slot validation
        seen_slots: dict[int, str] = {}
        for filename, slot in self.slot_assignments.items():
            if not (1 <= slot <= MAX_SLOT):
                errors.append(f"Slot {slot} for '{filename}' out of range (1-{MAX_SLOT})")
            if slot in seen_slots:
                errors.append(
                    f"Duplicate slot {slot}: '{filename}' and '{seen_slots[slot]}'"
                )
            seen_slots[slot] = filename

        # Pad assignment validation
        assigned_slots = set(self.slot_assignments.values())
        seen_pads: set[tuple[int, str, int]] = set()

        for pa in self.pad_assignments:
            if not (1 <= pa.project <= MAX_PROJECT):
                errors.append(f"Project {pa.project} out of range (1-{MAX_PROJECT})")
            if pa.group not in VALID_GROUPS:
                errors.append(f"Group '{pa.group}' invalid (must be A-D)")
            if not (1 <= pa.pad <= MAX_PAD):
                errors.append(f"Pad {pa.pad} out of range (1-{MAX_PAD})")
            if pa.slot not in assigned_slots:
                errors.append(
                    f"Pad {pa.group}{pa.pad} references slot {pa.slot} "
                    f"which has no slot_assignment"
                )

            key = (pa.project, pa.group, pa.pad)
            if key in seen_pads:
                errors.append(
                    f"Duplicate pad assignment: project {pa.project} {pa.group}{pa.pad}"
                )
            seen_pads.add(key)

        return errors

    @classmethod
    def from_yaml(cls, path: Path) -> EP133Mapping:
        """Load mapping from a YAML file."""
        data = yaml.safe_load(path.read_text())

        slot_assignments = data.get("slot_assignments", {})

        pad_assignments = []
        for pa in data.get("pad_assignments", []):
            pad_assignments.append(EP133PadAssignment(
                project=pa.get("project", 1),
                group=pa["group"],
                pad=pa["pad"],
                slot=pa["slot"],
            ))

        return cls(
            slot_assignments=slot_assignments,
            pad_assignments=pad_assignments,
        )

    def to_yaml(self, path: Path) -> None:
        """Write mapping to a YAML file."""
        data = {
            "slot_assignments": self.slot_assignments,
            "pad_assignments": [
                {
                    "project": pa.project,
                    "group": pa.group,
                    "pad": pa.pad,
                    "slot": pa.slot,
                }
                for pa in self.pad_assignments
            ],
        }
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    @classmethod
    def auto_from_export(
        cls,
        export_dir: Path,
        project: int = 1,
        start_slot: int = 1,
    ) -> EP133Mapping:
        """Generate a mapping automatically from an EP-133 export directory.

        Uses the export.json manifest if present, otherwise assigns sequentially.
        Groups are inferred from filenames: drums->A, bass->B, vocals/melodic->C, loops->D.
        """
        import json

        manifest_path = export_dir / "export.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            slot_assignments = {}
            pad_assignments = []
            for entry in manifest.get("slots", []):
                filename = entry["file"]
                slot = start_slot + entry["slot"] - 1
                slot_assignments[filename] = slot
                pad_assignments.append(EP133PadAssignment(
                    project=project,
                    group=entry["group"],
                    pad=entry["pad"],
                    slot=slot,
                ))
            return cls(slot_assignments=slot_assignments, pad_assignments=pad_assignments)

        # Fallback: sequential assignment from WAV files
        wav_files = sorted(export_dir.glob("*.wav"))
        slot_assignments = {}
        pad_assignments = []
        group_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}

        for wav in wav_files:
            name = wav.name.lower()
            if "drum" in name or "kick" in name or "snare" in name or "hat" in name:
                group = "A"
            elif "bass" in name:
                group = "B"
            elif "vocal" in name or "melodic" in name:
                group = "C"
            else:
                group = "D"

            if group_counts[group] >= MAX_PAD:
                continue  # skip overflow

            slot = start_slot + len(slot_assignments)
            group_counts[group] += 1
            slot_assignments[wav.name] = slot
            pad_assignments.append(EP133PadAssignment(
                project=project,
                group=group,
                pad=group_counts[group],
                slot=slot,
            ))

        return cls(slot_assignments=slot_assignments, pad_assignments=pad_assignments)
