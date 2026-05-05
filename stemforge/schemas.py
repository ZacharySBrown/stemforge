"""Pydantic schemas for StemForge's three undocumented JSON contracts.

Hardening Stream A.2. Until now `stems.json`, `prechop_manifest.json`, and
`snapshot.json` had only a Python dataclass (or JS comment) as their
source-of-truth shape. This module gives each one a runtime-validatable
Pydantic model so producers and consumers can fail loud when shape drifts.

The models intentionally use `extra="ignore"` — they are forward-compatible:
adding a field to a writer doesn't break a reader on an older schema. New
required fields are a breaking change and need a deliberate version bump.

The existing dataclasses in `stemforge.manifest` and `stemforge.prechop`
keep working unchanged. These models are an opt-in validation layer; reach
for them at boundaries (CLI write, M4L read) rather than internal call paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── stems.json (Track A — Demucs split + slice manifest) ─────────────────────


class StemInfoModel(BaseModel):
    name: str
    wav_path: str
    beats_dir: str
    beat_count: int

    model_config = {"extra": "ignore"}


class TempoProvenanceModel(BaseModel):
    source: str
    confidence: str
    first_downbeat_sec: float | None = None
    n_downbeats: int = 0
    warning: str | None = None
    all_estimates: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class InputAudioModel(BaseModel):
    sample_rate: int
    duration_samples: int
    sha256: str

    model_config = {"extra": "ignore"}


class StemsManifestModel(BaseModel):
    """`stems.json` — Track A's per-track split-and-slice output."""

    track_name: str
    source_file: str
    backend: str
    bpm: float
    beat_count: int
    stems: list[StemInfoModel]
    output_dir: str
    pipeline: str
    processed_at: str
    tempo: TempoProvenanceModel | None = None
    input_audio: InputAudioModel | None = None

    model_config = {"extra": "ignore"}


# ── prechop_manifest.json (padded N-bar chunk descriptors) ───────────────────


class ChunkMetaModel(BaseModel):
    """One row in `prechop_manifest.json` per chunk file. Mirrors the
    `ChunkMeta` dataclass in `stemforge.prechop`; `audio_hash` (Stream A.1)
    is the content-stable identifier downstream consumers (configurator
    clip-refs, future projectors) use to detect chunk content changes."""

    file: str
    stem: str
    chunk_index: int
    bars: int
    pad_bars: int
    pad_pre_bars: float
    pad_post_bars: float
    loop_start_sec: float
    loop_end_sec: float
    total_sec: float
    chunk_duration_samples: int = 0
    sample_rate: int = 0
    source_offset_sec: float = 0.0
    audio_hash: str | None = None

    model_config = {"extra": "ignore"}


class StemPrechopModel(BaseModel):
    dir: str
    chunks: list[ChunkMetaModel]
    chunk_count: int

    model_config = {"extra": "ignore"}


class PrechopManifestModel(BaseModel):
    """`prechop_manifest.json` — top-level summary of a prechop run."""

    bpm: float
    bars: int
    pad_bars: int
    pad_pre_bars: int
    pad_post_bars: int
    pad_last: bool
    beats_per_bar: int
    first_downbeat_sec: float
    pre_bars: int
    musical_bar_1_chunk_index: int
    leading_partial_emitted: bool
    stems: dict[str, StemPrechopModel]

    model_config = {"extra": "ignore"}


# ── snapshot.json (Track B — arrangement-view export) ────────────────────────


class LocatorModel(BaseModel):
    time_sec: float
    name: str = ""

    model_config = {"extra": "ignore"}


class ArrangementClipModel(BaseModel):
    file_path: str
    start_time_sec: float
    length_sec: float
    warping: int = 1

    model_config = {"extra": "ignore"}


class SnapshotModel(BaseModel):
    """`snapshot.json` — Track B's arrangement-view dump.

    Source-of-truth shape is documented inline at the top of
    `v0/src/m4l-js/sf_arrangement_reader.js`. Per-track clip lists are
    keyed by group label A/B/C/D today; future configurator work will
    generalize to N-group dicts but this model only constrains today's
    contract.
    """

    tempo: float
    time_sig: tuple[int, int]
    arrangement_length_sec: float
    locators: list[LocatorModel]
    tracks: dict[str, list[ArrangementClipModel]]

    model_config = {"extra": "ignore"}

    @field_validator("time_sig", mode="before")
    @classmethod
    def _coerce_time_sig(cls, v: Any) -> Any:
        # JSON arrays come in as `list`; the model wants a 2-tuple.
        if isinstance(v, list) and len(v) == 2:
            return tuple(v)
        return v


# ── Validation helpers (use these at write/read boundaries) ──────────────────


def validate_stems_manifest(data: dict | str | Path) -> StemsManifestModel:
    """Validate a `stems.json` payload (dict, JSON string, or path)."""
    return _validate(StemsManifestModel, data)


def validate_prechop_manifest(data: dict | str | Path) -> PrechopManifestModel:
    """Validate a `prechop_manifest.json` payload."""
    return _validate(PrechopManifestModel, data)


def validate_snapshot(data: dict | str | Path) -> SnapshotModel:
    """Validate a `snapshot.json` payload."""
    return _validate(SnapshotModel, data)


def _validate(model: type[BaseModel], data: dict | str | Path) -> Any:
    if isinstance(data, Path):
        return model.model_validate_json(data.read_text())
    if isinstance(data, str):
        return model.model_validate_json(data)
    if isinstance(data, dict):
        return model.model_validate(data)
    raise TypeError(f"unsupported payload type: {type(data).__name__}")


__all__ = [
    "ArrangementClipModel",
    "ChunkMetaModel",
    "InputAudioModel",
    "LocatorModel",
    "PrechopManifestModel",
    "SnapshotModel",
    "StemInfoModel",
    "StemPrechopModel",
    "StemsManifestModel",
    "TempoProvenanceModel",
    "validate_prechop_manifest",
    "validate_snapshot",
    "validate_stems_manifest",
]
