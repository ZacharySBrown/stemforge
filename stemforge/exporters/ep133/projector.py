"""EP-133 projector — wraps the song-mode export pipeline.

Implements :class:`stemforge.exporters.projector.AbstractProjector` for
the EP-133 K.O. II's ``.ppak`` format. Composes the existing pieces:
``resolve_scenes`` → ``synthesize`` → ``build_ppak``.

Public surface:

- :meth:`capabilities` — EP-133 limits as a flat dict.
- :meth:`validate` — pre-flight warnings (locator count, project slot,
  manifest shape) for the arrangement/manifest direct path.
- :meth:`validate_spec` — pre-flight warnings for the
  :class:`~stemforge.scene_model.Project` spec path (Phase 2).
- :meth:`synthesize_spec` — produce a :class:`PpakSpec` from arrangement
  + manifest. Useful for callers that want to inspect the intermediate
  before building bytes (e.g. CLI status prints).
- :meth:`synthesize_spec_from_project` — same, but driven by a
  :class:`~stemforge.scene_model.Project` (via ``project_translator``).
- :meth:`build_bytes_from_spec` — turn a :class:`PpakSpec` into ``.ppak``
  bytes, synthesizing a minimal template if no reference is supplied.
- :meth:`project` — full pipeline driven by arrangement + manifest.
- :meth:`project_from_spec` — full pipeline driven by a
  :class:`~stemforge.scene_model.Project`. Phase 2 acceptance contract:
  bytes byte-identical to :meth:`project` for any
  ``project_from_arrangement_and_manifest(arrangement, manifest)``.

The bytes produced are byte-identical to what the direct-call pipeline
emitted before this refactor (see ``tests/ep133/test_song_export_parity.py``).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from stemforge.exporters.projector import AbstractProjector
from stemforge.scene_model import Project

from .ppak_writer import build_ppak, build_synthetic_template_ppak
from .project_translator import project_to_snapshots
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

    # ── Project-spec path (Phase 2) ──────────────────────────────────────────
    #
    # The methods below mirror their arrangement/manifest counterparts but
    # drive the pipeline from the abstract :class:`Project` model. The byte-
    # shaping function (:func:`synthesize`) is the same; only the inputs
    # differ. Acceptance gate:
    # ``project_from_spec(project_from_arrangement_and_manifest(arr, mf), mf, ...)``
    # produces the same bytes as ``project(arr, mf, ...)``.

    def validate_spec(self, project: Project) -> list[str]:
        """Pre-flight warnings against a :class:`Project` (no manifest needed)."""
        warnings: list[str] = []
        warnings.extend(project.validate_v1())
        if not project.songs:
            warnings.append("project has zero songs — nothing to export.")
            return warnings
        song = project.songs[0]
        scene_count = len(song.scenes)
        if scene_count == 0:
            warnings.append("song has zero scenes — no scene chunks will be emitted.")
        elif scene_count > MAX_SCENES:
            warnings.append(f"song has {scene_count} scenes > EP-133 limit of {MAX_SCENES}.")
        for group in song.groups:
            if len(group.pads) > MAX_PADS_PER_GROUP:
                warnings.append(
                    f"group {group.group_id!r} has {len(group.pads)} pads "
                    f"> EP-133 limit of {MAX_PADS_PER_GROUP}."
                )
        return warnings

    def synthesize_spec_from_project(
        self,
        project: Project,
        manifest: dict,
        *,
        project_slot: int,
    ) -> PpakSpec:
        """Project → Snapshots → PpakSpec. Single-song only.

        ``project_bpm``, ``time_sig``, and ``arrangement_length_sec`` are
        read off ``project.songs[0]``; ``project_slot`` stays a per-export
        argument because it's not a property of the abstract project.
        """
        if len(project.songs) != 1:
            raise ValueError(
                f"synthesize_spec_from_project requires exactly 1 song, got {len(project.songs)}"
            )
        song = project.songs[0]
        snapshots = project_to_snapshots(project, manifest)
        return synthesize(
            snapshots,
            manifest,
            float(song.bpm),
            (int(song.time_sig[0]), int(song.time_sig[1])),
            project_slot,
            arrangement_length_sec=song.arrangement_length_sec,
        )

    def project_from_spec(
        self,
        project: Project,
        manifest: dict,
        *,
        project_slot: int,
        reference_template: Path | None = None,
    ) -> bytes:
        """Full export driven by a :class:`Project` instead of arrangement+manifest.

        Phase 2 acceptance: bytes from this method MUST byte-equal
        :meth:`project` when ``project`` was built via
        :func:`stemforge.exporters.ep133.project_translator.project_from_arrangement_and_manifest`.
        That invariant is pinned by ``test_projector_spec_parity.py``.
        """
        spec = self.synthesize_spec_from_project(
            project,
            manifest,
            project_slot=project_slot,
        )
        return self.build_bytes_from_spec(spec, reference_template=reference_template)
