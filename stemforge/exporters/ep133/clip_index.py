"""Federated clip index for the multi-source deck-builder path.

The existing song-export pipeline takes ONE manifest (one source song)
and projects it onto the device. The hip-hop verse-swap deck workflow
(per :doc:`../../../new_specs/VERSE_SWAP_DECK_PLAN.md`) puts clips from
**N** source songs onto one device project — 12+ vocals across 12+
forge runs. This module makes that federation explicit.

Resolution model:

- A :class:`ClipIndex` aggregates entries from multiple manifests plus
  raw WAV paths.
- Lookups are by ``(source, selector)`` where ``source`` is a manifest
  path (or ``None`` for a raw-WAV reference) and ``selector`` is one of:

  - ``slot:N`` and a ``group`` letter — pick by manifest slot index.
  - ``name:NAME`` — pick by entry name (curated manifests).
  - ``file:BASENAME`` — pick by file basename match.
  - bare string — try ``name:`` first, then ``file:`` as fallback.

- :meth:`ClipIndex.resolve_path` returns a raw WAV reference: the
  resolved absolute path plus optional manifest-supplied metadata
  (bpm, audio_hash, trim region).
- :class:`ClipIndex` computes ``audio_hash`` lazily from file bytes
  when the manifest entry doesn't carry one (closes Phase 2 loose-end #1).

This is **not** a single-writer-of-truth — it's a read-only resolver.
The build-deck CLI walks the deck plan and queries this index per pad.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from stemforge.manifest_schema import compute_audio_hash


@dataclass(frozen=True)
class ResolvedClip:
    """Result of a clip-index lookup.

    BPM fields are split (2026-05-11):
    - ``source_bpm`` — per-clip BPM from the entry's ``source_bpm`` or
      ``bpm`` field. Reliable per-clip data when present.
    - ``bpm`` — manifest-global fallback (= the manifest's top-level
      ``bpm``, which is the SESSION tempo, NOT a per-clip rate). Kept
      for back-compat with callers that need a tempo hint even when no
      per-clip value exists, but downstream code should prefer
      ``source_bpm`` and treat ``bpm`` as a weak fallback.
    """

    path: Path
    audio_hash: str
    bpm: float | None
    source_bpm: float | None
    name: str | None
    duration_sec: float | None
    start_offset_sec: float | None
    end_offset_sec: float | None
    loop_start_sec: float | None
    loop_end_sec: float | None


class ClipIndex:
    """Read-only resolver across N forge manifests + raw WAV paths."""

    def __init__(self) -> None:
        # source manifest path (resolved) → loaded manifest dict
        self._manifests: dict[Path, dict] = {}
        # source manifest path → manifest's parent directory (for relative
        # WAV paths)
        self._manifest_dirs: dict[Path, Path] = {}
        # cache: absolute WAV path → audio_hash
        self._hash_cache: dict[Path, str] = {}

    @classmethod
    def from_manifests(cls, manifest_paths: Iterable[Path]) -> "ClipIndex":
        """Build an index from a list of manifest paths."""
        idx = cls()
        for p in manifest_paths:
            idx.add_manifest(p)
        return idx

    def add_manifest(self, manifest_path: Path) -> None:
        """Load a manifest into the index."""
        resolved = Path(manifest_path).resolve()
        if resolved in self._manifests:
            return
        if not resolved.is_file():
            raise FileNotFoundError(f"manifest not found: {resolved}")
        self._manifests[resolved] = json.loads(resolved.read_text())
        self._manifest_dirs[resolved] = resolved.parent

    def manifests(self) -> dict[Path, dict]:
        """Return the loaded manifests, keyed by resolved path."""
        return dict(self._manifests)

    # ---- resolution -------------------------------------------------------

    def resolve_path(self, path: Path | str) -> ResolvedClip:
        """Resolve a raw WAV path (no manifest lookup)."""
        wav_path = Path(path).expanduser().resolve()
        if not wav_path.is_file():
            raise FileNotFoundError(f"WAV not found: {wav_path}")
        return ResolvedClip(
            path=wav_path,
            audio_hash=self._hash_for(wav_path),
            bpm=None,
            source_bpm=None,
            name=None,
            duration_sec=None,
            start_offset_sec=None,
            end_offset_sec=None,
            loop_start_sec=None,
            loop_end_sec=None,
        )

    def resolve_manifest_clip(
        self,
        manifest_path: Path | str,
        selector: str,
        *,
        group: str | None = None,
    ) -> ResolvedClip:
        """Resolve a clip selector against one of the loaded manifests.

        ``selector`` may be:
        - ``slot:N`` (requires ``group``) — entry at session_tracks[group][i] where slot==N
        - ``name:NAME`` — entry whose ``name`` field matches
        - ``file:BASENAME`` — entry whose file basename (no extension) matches
        - bare string — try ``name:`` first, then ``file:`` as fallback
        """
        resolved_manifest = Path(manifest_path).expanduser().resolve()
        if resolved_manifest not in self._manifests:
            self.add_manifest(resolved_manifest)
        manifest = self._manifests[resolved_manifest]
        manifest_dir = self._manifest_dirs[resolved_manifest]

        entry = self._lookup_entry(manifest, selector, group=group)
        if entry is None:
            raise KeyError(
                f"no entry matches selector {selector!r} "
                f"(group={group!r}) in manifest {resolved_manifest}"
            )
        wav_path = self._resolve_wav_path(entry, manifest_dir)
        if not wav_path.is_file():
            raise FileNotFoundError(
                f"WAV referenced by manifest entry not on disk: {wav_path} "
                f"(manifest={resolved_manifest}, selector={selector!r})"
            )

        audio_hash = str(entry.get("audio_hash") or "") or self._hash_for(wav_path)
        # source_bpm: prefer the new explicit field, fall back to legacy `bpm`
        # on the entry. Either represents a per-clip BPM (e.g. clip's warp_bpm
        # captured by M4L pre-crop).
        source_bpm = _coerce_float(entry.get("source_bpm")) or _coerce_float(entry.get("bpm"))
        # bpm: manifest-global fallback. Useful as a "what tempo was the
        # session?" hint but NOT meaningful per-clip.
        bpm = _coerce_float(manifest.get("bpm"))
        return ResolvedClip(
            path=wav_path,
            audio_hash=audio_hash,
            bpm=bpm,
            source_bpm=source_bpm,
            name=entry.get("name"),
            duration_sec=_coerce_float(entry.get("clip_length_sec")),
            start_offset_sec=_coerce_float(entry.get("start_offset_sec")),
            end_offset_sec=_coerce_float(entry.get("end_offset_sec")),
            loop_start_sec=_coerce_float(entry.get("loop_start_sec")),
            loop_end_sec=_coerce_float(entry.get("loop_end_sec")),
        )

    # ---- internals --------------------------------------------------------

    def _hash_for(self, wav_path: Path) -> str:
        cached = self._hash_cache.get(wav_path)
        if cached is not None:
            return cached
        h = compute_audio_hash(wav_path)
        self._hash_cache[wav_path] = h
        return h

    def _lookup_entry(
        self,
        manifest: dict,
        selector: str,
        *,
        group: str | None,
    ) -> dict | None:
        session = manifest.get("session_tracks") or {}
        if selector.startswith("slot:"):
            if group is None:
                raise ValueError(f"slot: selector requires group (selector={selector!r})")
            target_slot = int(selector.split(":", 1)[1])
            entries = session.get(group.upper()) or session.get(group.lower()) or []
            for e in entries:
                if int(e.get("slot", -1)) == target_slot:
                    return e
            return None
        if selector.startswith("name:"):
            target = selector.split(":", 1)[1]
            return _scan_all(session, lambda e: e.get("name") == target)
        if selector.startswith("file:"):
            target = selector.split(":", 1)[1]
            return _scan_all(session, lambda e: _basename_no_ext(e) == target)
        # Bare selector — try name first, then file basename.
        by_name = _scan_all(session, lambda e: e.get("name") == selector)
        if by_name is not None:
            return by_name
        return _scan_all(session, lambda e: _basename_no_ext(e) == selector)

    def _resolve_wav_path(self, entry: dict, manifest_dir: Path) -> Path:
        raw = entry.get("file_path") or entry.get("file")
        if raw is None:
            raise KeyError(f"manifest entry has no file path: {entry!r}")
        wav = Path(raw).expanduser()
        if not wav.is_absolute():
            wav = (manifest_dir / wav).resolve()
        else:
            wav = wav.resolve()
        return wav


def _scan_all(session: dict, predicate) -> dict | None:
    for entries in session.values():
        for entry in entries or []:
            if predicate(entry):
                return entry
    return None


def _basename_no_ext(entry: dict) -> str | None:
    raw = entry.get("file_path") or entry.get("file")
    if raw is None:
        return None
    return Path(raw).stem


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["ClipIndex", "ResolvedClip"]
