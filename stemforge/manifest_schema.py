"""StemForge sample-manifest schema (canonical) — mirrored by ep133-ppak.

The schema and the read helpers here MUST match `ep133-ppak/ep133/manifest.py`
byte-for-byte. The producer-side write helpers below have no consumer-side
counterpart.

What this is for: a tiny, hardware-loader-friendly metadata blob written next
to every audio file StemForge emits, so consumers (the EP-133 loader, future
samplers, etc.) can pick the right pad / playmode / BPM without having to
re-derive any of it.

NOT a replacement for `stems.json` — that remains the pipeline-level
manifest. This is a per-sample sidecar.

Resolution order (consumer side, highest to lowest):
  1. CLI flags
  2. Sidecar `.manifest_<hash>.json` next to the WAV
  3. Batch `.manifest.json` in the WAV's directory
  4. Built-in defaults

CLI always wins. The producer's job is to fill in good defaults.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, Field

PadLabel = Literal["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "ENTER"]
Group = Literal["A", "B", "C", "D"]
TimeMode = Literal["off", "bar", "bpm"]
PlayMode = Literal["oneshot", "key", "legato"]
Stem = Literal["drums", "bass", "vocals", "other", "full"]

SIDECAR_PREFIX = ".manifest_"
SIDECAR_SUFFIX = ".json"
BATCH_FILENAME = ".manifest.json"
HASH_LENGTH = 16  # hex chars from sha256

# Bottom-up, left-right pad rotation matching the EP-133 keypad face.
# Index 0 → bottom-left ".", index 11 → top-right "9".
BAR_INDEX_TO_LABEL: tuple[PadLabel, ...] = (
    ".", "0", "ENTER", "1", "2", "3", "4", "5", "6", "7", "8", "9",
)


class SampleMeta(BaseModel):
    """Per-sample metadata (sidecar contents OR a batch entry)."""

    file: str | None = None
    audio_hash: str | None = None

    name: str | None = None

    bpm: float | None = None
    time_mode: TimeMode | None = None
    bars: float | None = None

    playmode: PlayMode | None = None

    source_track: str | None = None
    stem: Stem | None = None
    role: str | None = None

    suggested_group: Group | None = None
    suggested_pad: PadLabel | None = None

    model_config = {"extra": "ignore"}


class BatchManifest(BaseModel):
    """Directory-level manifest. Filename: `.manifest.json` in the dir root."""

    version: int = 1
    track: str | None = None
    bpm: float | None = None
    samples: list[SampleMeta] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# ── Hashing ──────────────────────────────────────────────────────────────────

def compute_audio_hash(path: Path, *, length: int = HASH_LENGTH) -> str:
    """Return sha256 of a file's raw bytes, lowercase hex, first `length` chars."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


# ── Sidecar / batch path helpers ─────────────────────────────────────────────

def sidecar_path_for(wav_path: Path, *, audio_hash: str | None = None) -> Path:
    """Return the expected sidecar path for a given WAV. Hashes if needed."""
    h = audio_hash or compute_audio_hash(wav_path)
    return wav_path.parent / f"{SIDECAR_PREFIX}{h}{SIDECAR_SUFFIX}"


def find_sidecar(wav_path: Path) -> Path | None:
    p = sidecar_path_for(wav_path)
    return p if p.exists() else None


def find_batch(wav_path: Path) -> Path | None:
    p = wav_path.parent / BATCH_FILENAME
    return p if p.exists() else None


# ── Read helpers (mirrored from ep133-ppak) ──────────────────────────────────

def load_sidecar(wav_path: Path) -> SampleMeta | None:
    p = find_sidecar(wav_path)
    if p is None:
        return None
    return SampleMeta.model_validate_json(p.read_text())


def load_batch(manifest_path: Path) -> BatchManifest:
    return BatchManifest.model_validate_json(manifest_path.read_text())


def lookup_in_batch(batch: BatchManifest, wav_path: Path) -> SampleMeta | None:
    """Find the entry in `batch` matching `wav_path` by hash or filename.

    Hash match wins (rename-robust). Falls back to filename match against
    `SampleMeta.file`.
    """
    if not batch.samples:
        return None

    target_name = wav_path.name
    target_hash: str | None = None
    by_name: SampleMeta | None = None

    for s in batch.samples:
        if s.audio_hash:
            if target_hash is None:
                target_hash = compute_audio_hash(wav_path)
            if s.audio_hash == target_hash:
                return s
        if s.file and Path(s.file).name == target_name and by_name is None:
            by_name = s

    return by_name


def resolve_meta(
    wav_path: Path,
    *,
    manifest_override: Path | None = None,
    use_sidecar: bool = True,
    use_batch: bool = True,
) -> SampleMeta | None:
    """Standard lookup chain: explicit → sidecar → batch → None."""
    if manifest_override is not None:
        raw = json.loads(manifest_override.read_text())
        if isinstance(raw, dict) and "samples" in raw:
            return lookup_in_batch(BatchManifest.model_validate(raw), wav_path)
        return SampleMeta.model_validate(raw)

    if use_sidecar:
        side = load_sidecar(wav_path)
        if side is not None:
            return side

    if use_batch:
        batch_path = find_batch(wav_path)
        if batch_path is not None:
            entry = lookup_in_batch(load_batch(batch_path), wav_path)
            if entry is not None:
                return entry

    return None


def merge_batch_default_bpm(meta: SampleMeta, batch: BatchManifest) -> SampleMeta:
    """Fill `meta.bpm` from `batch.bpm` if absent. Returns a new SampleMeta."""
    if meta.bpm is None and batch.bpm is not None:
        return meta.model_copy(update={"bpm": batch.bpm})
    return meta


# ── Producer-side write helpers (StemForge-only) ─────────────────────────────

def display_name(stem_filename: str, *, max_len: int = 16) -> str:
    """Trim a filename to a device-friendly display string.

    Drops the extension, replaces underscores with spaces, truncates to
    `max_len` (the EP-133 sample browser caps at 16 chars).
    """
    base = Path(stem_filename).stem.replace("_", " ").strip()
    return base[:max_len]


def write_sidecar(
    wav_path: Path,
    meta: SampleMeta,
    *,
    fill_audio_hash: bool = True,
    fill_file: bool = True,
) -> Path:
    """Write a `.manifest_<hash>.json` next to a WAV. Returns the sidecar path.

    The on-disk filename ALWAYS uses the real sha256 of the WAV — that's the
    consumer's lookup key. The meta's `audio_hash` field is preserved as-is
    (so callers can stash a different hash in metadata if they want), but
    `fill_audio_hash=True` will populate it with the real hash when absent.

    By default also fills `file` (the bare filename) when absent.
    """
    real_hash = compute_audio_hash(wav_path)

    updates: dict = {}
    if fill_audio_hash and meta.audio_hash is None:
        updates["audio_hash"] = real_hash
    if fill_file and meta.file is None:
        updates["file"] = wav_path.name

    final = meta.model_copy(update=updates) if updates else meta
    out = sidecar_path_for(wav_path, audio_hash=real_hash)
    out.write_text(final.model_dump_json(indent=2, exclude_none=True))
    return out


def write_batch(
    directory: Path,
    batch: BatchManifest,
) -> Path:
    """Write a `.manifest.json` BatchManifest into `directory`. Returns the path."""
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / BATCH_FILENAME
    out.write_text(batch.model_dump_json(indent=2, exclude_none=True))
    return out


def assign_pad_rotation(
    metas: Iterable[SampleMeta],
    *,
    group: Group | None = None,
    start_index: int = 0,
) -> list[SampleMeta]:
    """Stamp `suggested_pad` (and optionally `suggested_group`) onto each meta
    using the bottom-up EP-133 rotation. Returns new SampleMeta objects.

    Caps at 12 pads per group. If `metas` exceeds 12, the overflow gets
    `suggested_pad=None` (consumer falls back to its own placement strategy).

    This is the producer-side rotation policy: StemForge decides physical
    placement so loaders never have to.
    """
    out: list[SampleMeta] = []
    for i, m in enumerate(metas):
        idx = start_index + i
        updates: dict = {}
        if idx < len(BAR_INDEX_TO_LABEL):
            updates["suggested_pad"] = BAR_INDEX_TO_LABEL[idx]
        if group is not None and m.suggested_group is None:
            updates["suggested_group"] = group
        out.append(m.model_copy(update=updates) if updates else m)
    return out


__all__ = [
    "BAR_INDEX_TO_LABEL",
    "BATCH_FILENAME",
    "HASH_LENGTH",
    "SIDECAR_PREFIX",
    "SIDECAR_SUFFIX",
    "BatchManifest",
    "Group",
    "PadLabel",
    "PlayMode",
    "SampleMeta",
    "Stem",
    "TimeMode",
    "assign_pad_rotation",
    "compute_audio_hash",
    "display_name",
    "find_batch",
    "find_sidecar",
    "load_batch",
    "load_sidecar",
    "lookup_in_batch",
    "merge_batch_default_bpm",
    "resolve_meta",
    "sidecar_path_for",
    "write_batch",
    "write_sidecar",
]
