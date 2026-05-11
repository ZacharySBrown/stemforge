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
from stemforge.scene_model import Project, resolve_format_profile

from .clip_index import ClipIndex
from .kit_synthesizer import synthesize_kit
from .ppak_writer import build_ppak, build_synthetic_template_ppak
from .project_translator import project_to_snapshots
from .song_format import PpakSpec
from .song_resolver import resolve_scenes
from .song_synthesizer import (
    MAX_PADS_PER_GROUP,
    MAX_PATTERNS_PER_GROUP,
    MAX_SCENES,
    SAMPLE_SLOT_PER_GROUP,
    global_sample_slot,
    synthesize,
)
from .wav_format import EP133_SAMPLE_RATE


# Device-wide memory cap. EP-133 K.O. II ships with "64 MB" sample RAM in
# the spec, but the device's own max_capacity SysEx report returns
# 62,853,120 bytes = 59.94 MiB usable (system reserves the rest).
# Verified 2026-05-09 against a real device. Per-group format profiles
# are the lever that lets denser projects fit (configurator spec v4
# Decision 16). Sample Tool likely needs a few MB of staging headroom on
# top — treat anything over ~58 MB as risky in practice.
EP133_MEMORY_CAP_BYTES = 62_853_120


def _ep133_rate_for_profile(profile: str) -> int:
    """Resolve a format profile to its concrete EP-133 output rate.

    Channels and bit-depth are device-locked (always mono / 16-bit), so
    the only lever is sample rate. The abstract profile's
    ``sample_rate_hz`` is clamped to ``EP133_SAMPLE_RATE`` (the device
    can't store higher rates).
    """
    abstract = resolve_format_profile(profile)
    return min(abstract.sample_rate_hz, EP133_SAMPLE_RATE)


def _slots_for_group(group_letter: str) -> range:
    """Global sample-slot range owned by one group (e.g. 'A' → 700..719)."""
    g = group_letter.lower()
    base = global_sample_slot(g, 0)
    return range(base, base + SAMPLE_SLOT_PER_GROUP)


def apply_group_format_to_spec(spec: PpakSpec, project: Project) -> None:
    """Populate ``spec.slot_sample_rate`` from per-group ``format_profile``.

    For every group in ``project.songs[0]`` whose ``format_profile`` is
    not ``preserve_source``, mark every slot owned by that group with
    the resolved rate. The writer reads ``slot_sample_rate.get(slot)``;
    unmarked slots use the device default (today's behavior).

    Mutates ``spec`` in place. No-op when the project has no songs.
    """
    if not project.songs:
        return
    song = project.songs[0]
    for group in song.groups:
        # Only emit rates for non-default profiles. Keeping the dict
        # empty in the all-`preserve_source` case is what guarantees
        # byte-identity with the pre-Decision-16 path.
        if group.format_profile == "preserve_source":
            continue
        rate = _ep133_rate_for_profile(group.format_profile)
        if rate == EP133_SAMPLE_RATE:
            # Profile resolved to the device default — same byte path as
            # ``preserve_source``. Skip so the writer takes the existing
            # branch (no per-slot rate override).
            continue
        for slot in _slots_for_group(group.group_id):
            if slot in spec.sounds:
                spec.slot_sample_rate[slot] = rate


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
        # PHASE 3 CLEANUP: this method (and :meth:`synthesize_spec` /
        # :meth:`validate`) accept the legacy arrangement+manifest signature.
        # When :meth:`project_from_spec` is the only callsite (CLI default
        # flips to --write-spec; M4L device strip drives the spec path),
        # delete the arrangement/manifest variants. Byte identity guarantees
        # the swap is invisible.
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
        # Memory budget: per Decision 16, validate against the device's
        # 64 MB cap before export so over-budget projects surface here
        # rather than as a silent device-side failure.
        memory_bytes = self.estimate_memory_bytes(project)
        if memory_bytes > EP133_MEMORY_CAP_BYTES:
            over_mb = (memory_bytes - EP133_MEMORY_CAP_BYTES) / (1024 * 1024)
            used_mb = memory_bytes / (1024 * 1024)
            warnings.append(
                f"estimated sample memory {used_mb:.1f} MB exceeds EP-133 cap "
                f"of 64 MB (over by {over_mb:.1f} MB) — drop a group to a lower "
                f"format_profile (e.g. 'vocal' = 24 kHz) or trim verse lengths."
            )
        return warnings

    def estimate_memory_bytes(self, project: Project) -> int:
        """Estimate total sample memory the project will consume on device.

        Per Decision 16: walks every pad's clip, infers the playable
        duration (preferring trim region over full clip length), resolves
        the group's format profile to a concrete sample rate, and
        accumulates ``duration_sec × rate × 2 bytes`` (mono 16-bit).

        Pure function over the :class:`Project`. No disk I/O — relies on
        the durations encoded in each :class:`ClipRef`. Pads without a
        clip duration contribute zero (a real export would skip them).
        """
        if not project.songs:
            return 0
        total = 0
        for group in project.songs[0].groups:
            rate = _ep133_rate_for_profile(group.format_profile)
            for pad in group.pads:
                clip = pad.clip
                if clip is None:
                    continue
                # Source-of-truth precedence mirrors the writer's:
                # loop region > end_offset > 0 (pad contributes nothing
                # if duration can't be inferred).
                if clip.loop_start_sec is not None and clip.loop_end_sec is not None:
                    duration = float(clip.loop_end_sec) - float(clip.loop_start_sec)
                elif clip.end_offset_sec is not None:
                    duration = float(clip.end_offset_sec) - float(clip.start_offset_sec or 0.0)
                else:
                    continue
                if duration <= 0:
                    continue
                total += int(duration * rate * 2)
        return total

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

        Per-group ``format_profile`` is applied after synthesis: any group
        not on ``preserve_source`` gets its slots tagged with the
        resolved sample rate so the writer downsamples at conversion time.
        """
        if len(project.songs) != 1:
            raise ValueError(
                f"synthesize_spec_from_project requires exactly 1 song, got {len(project.songs)}"
            )
        song = project.songs[0]
        snapshots = project_to_snapshots(project, manifest)
        spec = synthesize(
            snapshots,
            manifest,
            float(song.bpm),
            (int(song.time_sig[0]), int(song.time_sig[1])),
            project_slot,
            arrangement_length_sec=song.arrangement_length_sec,
        )
        apply_group_format_to_spec(spec, project)
        return spec

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

    # ── Kit projection (Slice 2 — Workflow B, multi-source decks) ────────────
    #
    # The verse-swap deck workflow puts clips from many forge runs onto one
    # device project. There is no arrangement-view source of truth — the
    # ``Project`` is hand-assembled by the build-deck CLI from N manifests +
    # raw WAV paths. This path skips snapshot/manifest plumbing entirely.

    def synthesize_kit_spec(
        self,
        project: Project,
        clip_index: ClipIndex,
        *,
        project_slot: int,
    ) -> PpakSpec:
        """Project + ClipIndex → PpakSpec for the Workflow B kit path.

        Single-scene; one event per pad fired at scene launch. Per-group
        ``format_profile`` is applied so vocal groups get their target
        sample rate at conversion time.
        """
        spec = synthesize_kit(project, clip_index, project_slot=project_slot)
        apply_group_format_to_spec(spec, project)
        return spec

    def project_kit(
        self,
        project: Project,
        clip_index: ClipIndex,
        *,
        project_slot: int,
        reference_template: Path | None = None,
    ) -> bytes:
        """Full kit export driven by a :class:`Project` + :class:`ClipIndex`.

        End-to-end Workflow B path: assembles every populated pad,
        downsamples per group's ``format_profile``, builds bytes.
        """
        spec = self.synthesize_kit_spec(
            project,
            clip_index,
            project_slot=project_slot,
        )
        return self.build_bytes_from_spec(spec, reference_template=reference_template)
