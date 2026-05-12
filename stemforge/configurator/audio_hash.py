"""Channel-collapse-invariant audio hash with on-disk cache.

The configurator's clip identity is hash-based (spec v4 Decision 3).
StemForge already has ``compute_audio_hash`` in
:mod:`stemforge.manifest_schema`, but that one hashes the raw WAV bytes —
which means re-encoding the same audio (mono ↔ stereo, 48 kHz ↔ 24 kHz)
produces a different hash. For the configurator we want a **content** hash
that survives format conversion at projector time.

:func:`audio_hash` reads the float32 PCM, averages channels to mono, and
hashes the bytes of that float32 mono buffer. Two WAVs with identical
musical content but different channel counts or bit depths produce the
same hash.

A disk cache at ``~/stemforge/.audio_hash_cache.json`` keyed by
``(path, mtime, size)`` avoids re-reading on every state-rebuild. Cache
entries that point at no-longer-existing files are trimmed lazily on
read.

This module is intentionally self-contained — no imports from
``stemforge.configurator.*`` — so it can be reused by other surfaces
(future bounce-to-clip, splice editor, etc.) without taking on the
HTTP-server dependency tree.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Final

import numpy as np
import soundfile as sf

HASH_LENGTH: Final[int] = 16
DEFAULT_CACHE_PATH: Final[Path] = Path.home() / "stemforge" / ".audio_hash_cache.json"


def _cache_key(path: Path) -> str:
    """Build the cache key for a path: ``"abs|mtime_ns|size"``."""
    stat = path.stat()
    return f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"


def _load_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.is_file():
        return {}
    try:
        return json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache_path: Path, cache: dict[str, str]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))
    except OSError:
        # Cache write is best-effort; don't let it surface as an error.
        pass


def _hash_buffer(samples: np.ndarray) -> str:
    """Hash a float32 mono buffer's bytes. ``HASH_LENGTH`` hex chars."""
    # Force C-contiguous float32 so the byte layout is canonical regardless
    # of the source dtype/strides.
    mono = np.ascontiguousarray(samples, dtype=np.float32)
    return hashlib.sha256(mono.tobytes()).hexdigest()[:HASH_LENGTH]


def _read_mono(path: Path) -> np.ndarray:
    """Read audio and average channels to mono float32. Raises if unreadable."""
    data, _sr = sf.read(str(path), dtype="float32", always_2d=True)
    # data shape: (frames, channels). Mean across channel axis.
    mono = data.mean(axis=1)
    return mono.astype(np.float32, copy=False)


def audio_hash(
    wav_path: Path | str,
    *,
    cache_path: Path | None = None,
    use_cache: bool = True,
) -> str:
    """Return a 16-char hex hash of ``wav_path``'s mono-mixdown PCM.

    Channel-collapse-invariant: stereo and mono renderings of the same
    musical content produce the same hash. The hash is computed against
    float32 samples so format conversion (bit depth, sample rate not
    changed) doesn't perturb it.

    .. note::

       Sample-rate changes DO change the hash — different rates produce
       different sample arrays. That's intentional: a 24 kHz vocal
       export is a derived artifact, not the same clip as the 48 kHz
       source.

    Args:
        wav_path: Path to the audio file. Anything ``soundfile`` can read.
        cache_path: Override the cache location. Defaults to
            :data:`DEFAULT_CACHE_PATH`.
        use_cache: When ``False``, bypass the cache entirely (still
            updates it on miss). Useful for testing.

    Returns:
        Lowercase hex string of length :data:`HASH_LENGTH`.

    Raises:
        FileNotFoundError: ``wav_path`` doesn't exist.
        RuntimeError: ``soundfile`` couldn't decode the file.
    """
    path = Path(wav_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"audio file not found: {path}")

    cache_p = cache_path or DEFAULT_CACHE_PATH
    cache: dict[str, str] = _load_cache(cache_p) if use_cache else {}

    key = _cache_key(path)
    if use_cache and key in cache:
        return cache[key]

    # Cache miss — compute the hash. Wrap soundfile errors in a friendly
    # RuntimeError so callers don't have to know about libsndfile error
    # taxonomy.
    try:
        samples = _read_mono(path)
    except (sf.LibsndfileError, RuntimeError) as exc:  # pragma: no cover
        raise RuntimeError(f"could not read audio from {path}: {exc}") from exc

    digest = _hash_buffer(samples)

    if use_cache:
        # Trim stale entries lazily — anything that points at a missing
        # file or has a key whose path no longer exists.
        cache = _prune_cache(cache)
        cache[key] = digest
        _save_cache(cache_p, cache)

    return digest


def _prune_cache(cache: dict[str, str]) -> dict[str, str]:
    """Drop cache entries whose path component no longer exists on disk."""
    pruned: dict[str, str] = {}
    for key, value in cache.items():
        try:
            raw_path = key.split("|", 1)[0]
        except (IndexError, AttributeError):
            continue
        if os.path.exists(raw_path):
            pruned[key] = value
    return pruned


__all__ = [
    "DEFAULT_CACHE_PATH",
    "HASH_LENGTH",
    "audio_hash",
]
