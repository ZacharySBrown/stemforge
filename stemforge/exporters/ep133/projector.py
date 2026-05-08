"""EP-133 projector — wraps the song-mode export pipeline.

Implements :class:`stemforge.exporters.projector.AbstractProjector` for
the EP-133 K.O. II's ``.ppak`` format. Composes the existing pieces:
``resolve_scenes`` → ``synthesize`` → ``build_ppak``.

Public surface:

- :meth:`capabilities` — EP-133 limits as a flat dict.
- :meth:`validate` — pre-flight warnings (locator count, project slot,
  manifest shape).
- :meth:`synthesize_spec` — produce a :class:`PpakSpec` from arrangement
  + manifest. Useful for callers that want to inspect the intermediate
  before building bytes (e.g. CLI status prints).
- :meth:`build_bytes_from_spec` — turn a :class:`PpakSpec` into ``.ppak``
  bytes, synthesizing a minimal template if no reference is supplied.
- :meth:`project` — full pipeline; calls the two helpers in sequence.

The bytes produced are byte-identical to what the direct-call pipeline
emitted before this refactor (see ``tests/ep133/test_song_export_parity.py``).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from stemforge.exporters.projector import AbstractProjector

from .ppak_writer import build_ppak, build_synthetic_template_ppak
from .song_format import PpakSpec
from .song_resolver import resolve_scenes
from .song_synthesizer import (
    MAX_PADS_PER_GROUP,
    MAX_PATTERNS_PER_GROUP,
    MAX_SCENES,
    synthesize,
)


class Ep133Projector(AbstractProjector):
    """Project an Ableton arrangement + stems manifest onto a ``.ppak``."""

    def capabilities(self) -> dict:
        return {
            "device": "ep133",
            "max_scenes": MAX_SCENES,
            "max_patterns_per_group": MAX_PATTERNS_PER_GROUP,
            "max_pads_per_group": MAX_PADS_PER_GROUP,
            "groups": ("a", "b", "c", "d"),
            "project_slot_range": (1, 9),
            "supported_bar_counts": (1, 2, 4),
        }

    def validate(
        self,
        arrangement: dict,
        manifest: dict,
        *,
        project_slot: int,
    ) -> list[str]:
        warnings: list[str] = []
        locators = arrangement.get("locators") or []
        if not locators:
            warnings.append("arrangement has zero locators — no scenes will be emitted.")
        elif len(locators) > MAX_SCENES:
            warnings.append(
                f"arrangement has {len(locators)} locators > EP-133 limit of {MAX_SCENES} scenes."
            )
        if not (1 <= int(project_slot) <= 9):
            warnings.append(f"project_slot {project_slot} out of EP-133 range 1..9.")
        if not (manifest.get("session_tracks") or {}):
            warnings.append("manifest has no session_tracks block — every group will be silent.")
        return warnings

    def synthesize_spec(
        self,
        arrangement: dict,
        manifest: dict,
        *,
        project_bpm: float,
        time_sig: tuple[int, int],
        project_slot: int,
        arrangement_length_sec: float | None = None,
    ) -> PpakSpec:
        snapshots = resolve_scenes(arrangement, manifest)
        return synthesize(
            snapshots,
            manifest,
            project_bpm,
            time_sig,
            project_slot,
            arrangement_length_sec=arrangement_length_sec,
        )

    def build_bytes_from_spec(
        self,
        spec: PpakSpec,
        *,
        reference_template: Path | None = None,
    ) -> bytes:
        if reference_template is None:
            with tempfile.TemporaryDirectory() as td:
                synth = Path(td) / "synthetic_template.ppak"
                build_synthetic_template_ppak(synth, project_slot=int(spec.project_slot))
                return build_ppak(spec, synth)
        return build_ppak(spec, reference_template)

    def project(
        self,
        arrangement: dict,
        manifest: dict,
        *,
        project_bpm: float,
        time_sig: tuple[int, int],
        project_slot: int,
        arrangement_length_sec: float | None = None,
        reference_template: Path | None = None,
    ) -> bytes:
        spec = self.synthesize_spec(
            arrangement,
            manifest,
            project_bpm=project_bpm,
            time_sig=time_sig,
            project_slot=project_slot,
            arrangement_length_sec=arrangement_length_sec,
        )
        return self.build_bytes_from_spec(spec, reference_template=reference_template)
