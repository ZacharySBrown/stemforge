"""Curation router — distribute bounced StemForge outputs into the user's library.

Reads a bounce directory's `.manifest.json` (BatchManifest), classifies each
sample by its metadata (playmode/role/stem/name), and copies it into the
matching `~/mus/Samples/<bucket>/` location with a song-prefixed filename.
The original per-WAV `.manifest_<hash>.json` sidecar travels alongside (the
hash is content-based, so the filename stays valid after rename).

A per-run curation manifest is written to:
    <library_root>/Projects/Stems/<song_slug>/stemforge_curation.json

This is the only place that records *where every output went* — the routed
files themselves carry only their hash sidecar, which points back via the
audio_hash + the run manifest.

The router does NOT touch the source bounce dir. Routing is additive and
idempotent (re-routing the same bounce updates the run manifest and skips
files already in place by hash).
"""
from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .manifest_schema import (
    BATCH_FILENAME,
    BatchManifest,
    SampleMeta,
    compute_audio_hash,
    load_batch,
    sidecar_path_for,
)

DEFAULT_LIBRARY_ROOT = Path("~/mus").expanduser()
RUN_MANIFEST_FILENAME = "stemforge_curation.json"


# ── Bucket taxonomy ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Bucket:
    """A target destination in the library, with a filename "kind" tag."""
    subpath: str   # relative to <library_root>/Samples/, e.g. "Oneshots/Kicks"
    kind: str      # filename tag, e.g. "kick"


# Order matters — first matching rule wins.
ONESHOT_BUCKETS: tuple[tuple[re.Pattern, Bucket], ...] = (
    (re.compile(r"\bkick", re.I),                 Bucket("Oneshots/Kicks",       "kick")),
    (re.compile(r"\bsnare|\bsnr|\brim", re.I),    Bucket("Oneshots/Snares",      "snare")),
    (re.compile(r"\bhat|\bhh\b|\bhi[- ]?hat", re.I), Bucket("Oneshots/Hats",     "hat")),
    (re.compile(r"\bclap|\btom|\bcymbal|\bcrash|\bride|\bperc|\bshaker", re.I),
                                                  Bucket("Oneshots/Percussion",  "perc")),
    (re.compile(r"\bvox|\bvocal", re.I),          Bucket("Vocals",               "vocalshot")),
)

LOOP_BY_STEM: dict[str, Bucket] = {
    "drums":  Bucket("Loops/Drums",   "drumloop"),
    "bass":   Bucket("Loops/Bass",    "bassloop"),
    "vocals": Bucket("Loops/Vocal",   "vocalloop"),
    "other":  Bucket("Loops/Melodic", "melodyloop"),
}

LOOP_NAME_HEURISTICS: tuple[tuple[re.Pattern, Bucket], ...] = (
    # More specific stems first so "Bass Loop" doesn't drift to Drums on "loop".
    (re.compile(r"\bbass|\bsub\b|\b808", re.I),     Bucket("Loops/Bass",    "bassloop")),
    (re.compile(r"\bvox|\bvocal", re.I),            Bucket("Loops/Vocal",   "vocalloop")),
    (re.compile(r"\bdrum|\bbreak", re.I),           Bucket("Loops/Drums",   "drumloop")),
    (re.compile(r"\bsynth|\bpad|\bkey|\blead|\bchord|\bmelod|\botherk?\b", re.I),
                                                    Bucket("Loops/Melodic", "melodyloop")),
)

INCOMING = Bucket("_Incoming", "unsorted")


def classify(meta: SampleMeta) -> Bucket:
    """Pick a destination bucket for a single SampleMeta. First match wins."""
    name = (meta.name or "").strip()

    # One-shots: classify by role first (most reliable), then name keywords.
    if meta.playmode == "oneshot":
        role = (meta.role or "").lower()
        if role in {"kick", "snare", "hat", "perc", "clap", "tom", "cymbal"}:
            for pattern, bucket in ONESHOT_BUCKETS:
                if pattern.search(role):
                    return bucket
        for pattern, bucket in ONESHOT_BUCKETS:
            if pattern.search(name):
                return bucket
        # Fallback: unknown one-shot → percussion bucket (catch-all)
        return Bucket("Oneshots/Percussion", "perc")

    # Loops (playmode key/legato/None — treat None as loop if bars >= 1).
    if meta.stem in LOOP_BY_STEM:
        return LOOP_BY_STEM[meta.stem]
    for pattern, bucket in LOOP_NAME_HEURISTICS:
        if pattern.search(name):
            return bucket

    return INCOMING


# ── Slug + filename rules ──────────────────────────────────────────────────

_SLUG_STRIP = re.compile(r"^\d+[\s_\-\.]*")
_SLUG_NONALPHANUM = re.compile(r"[^a-zA-Z0-9]+")
_SLUG_REPEAT = re.compile(r"_+")


def to_slug(raw: str) -> str:
    """Normalize an arbitrary string to snake_case ASCII slug."""
    s = _SLUG_STRIP.sub("", raw or "")
    s = _SLUG_NONALPHANUM.sub("_", s)
    s = _SLUG_REPEAT.sub("_", s).strip("_")
    return s.lower() or "untitled"


def build_filename(slug: str, bucket: Bucket, n: int, *, bars: float | None = None) -> str:
    """Construct the routed filename. e.g. `oohlala_drumloop_4bar_001.wav`."""
    parts = [slug, bucket.kind]
    if bars and bucket.kind in {"drumloop", "bassloop", "vocalloop", "melodyloop"}:
        # Round to nearest int when nearly-whole; preserve fractions otherwise.
        b_int = int(round(bars))
        if abs(bars - b_int) < 0.01 and b_int > 0:
            parts.append(f"{b_int}bar")
    parts.append(f"{n:03d}")
    return "_".join(parts) + ".wav"


def next_index(dest_dir: Path, slug: str, bucket: Bucket) -> int:
    """Find the next free 3-digit index for `<slug>_<kind>_NNN.wav` in dest_dir."""
    if not dest_dir.exists():
        return 1
    prefix = f"{slug}_{bucket.kind}_"
    pat = re.compile(rf"{re.escape(prefix)}(?:\d+bar_)?(\d{{3}})\.wav$")
    used = set()
    for p in dest_dir.glob(f"{prefix}*.wav"):
        m = pat.search(p.name)
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return n


# ── Routing records & result ───────────────────────────────────────────────

@dataclass
class RouteRecord:
    source_wav: Path
    dest_wav: Path
    bucket: str          # e.g. "Loops/Drums"
    audio_hash: str
    meta: SampleMeta


@dataclass
class RouteResult:
    song_slug: str
    library_root: Path
    records: list[RouteRecord] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


# ── Core routing ───────────────────────────────────────────────────────────

def derive_song_slug(
    *,
    explicit: str | None,
    batch: BatchManifest | None,
    export_dir: Path,
) -> str:
    """Pick a song slug. Explicit > batch.track > export_dir basename."""
    if explicit:
        return to_slug(explicit)
    if batch and batch.track:
        return to_slug(batch.track)
    return to_slug(export_dir.name)


def _samples_with_paths(
    batch: BatchManifest, export_dir: Path,
) -> Iterable[tuple[Path, SampleMeta]]:
    """Yield (wav_path, meta) for each batch entry that resolves to a real file."""
    for entry in batch.samples:
        if not entry.file:
            continue
        wav = export_dir / entry.file
        if wav.exists():
            yield wav, entry


def _copy_with_sidecar(
    src_wav: Path,
    dest_wav: Path,
    *,
    audio_hash: str,
    copy_mode: bool = True,
) -> None:
    """Copy WAV + its hash-named sidecar (if present) to the destination dir.

    The sidecar's name is based on the audio hash, which is content-derived,
    so it stays valid after a content-preserving copy.
    """
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    if copy_mode:
        shutil.copy2(src_wav, dest_wav)
    else:
        if dest_wav.exists() or dest_wav.is_symlink():
            dest_wav.unlink()
        dest_wav.symlink_to(src_wav.resolve())

    src_sidecar = sidecar_path_for(src_wav, audio_hash=audio_hash)
    if src_sidecar.exists():
        dest_sidecar = dest_wav.parent / src_sidecar.name
        if copy_mode:
            shutil.copy2(src_sidecar, dest_sidecar)
        else:
            if dest_sidecar.exists() or dest_sidecar.is_symlink():
                dest_sidecar.unlink()
            dest_sidecar.symlink_to(src_sidecar.resolve())


def _write_run_manifest(
    library_root: Path,
    result: RouteResult,
    *,
    source_export_dir: Path,
    project_bpm: float | None,
) -> Path:
    """Write per-run curation manifest at Projects/Stems/<slug>/."""
    import json

    run_dir = library_root / "Projects" / "Stems" / result.song_slug
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / RUN_MANIFEST_FILENAME

    payload = {
        "version": 1,
        "song_slug": result.song_slug,
        "source_export_dir": str(source_export_dir.resolve()),
        "library_root": str(library_root.resolve()),
        "project_bpm": project_bpm,
        "routed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "records": [
            {
                "source_wav": str(r.source_wav.resolve()),
                "dest_wav": str(r.dest_wav.resolve()),
                "bucket": r.bucket,
                "audio_hash": r.audio_hash,
                "meta": r.meta.model_dump(exclude_none=True),
            }
            for r in result.records
        ],
        "skipped": [{"path": str(p), "reason": reason} for p, reason in result.skipped],
    }
    out.write_text(json.dumps(payload, indent=2))
    return out


def route_export_dir(
    export_dir: Path,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    song_slug: str | None = None,
    copy: bool = True,
    write_run_manifest: bool = True,
) -> RouteResult:
    """Route every sample in `export_dir` into `<library_root>/Samples/<bucket>/`.

    Returns a RouteResult. Idempotent: re-routing skips by hash collision in
    the destination (a file with the same audio_hash already routed).
    """
    export_dir = Path(export_dir).expanduser()
    library_root = Path(library_root).expanduser()

    batch_path = export_dir / BATCH_FILENAME
    if not batch_path.exists():
        raise FileNotFoundError(f"No {BATCH_FILENAME} in {export_dir}")
    batch = load_batch(batch_path)

    slug = derive_song_slug(explicit=song_slug, batch=batch, export_dir=export_dir)
    result = RouteResult(song_slug=slug, library_root=library_root)

    samples_root = library_root / "Samples"

    for src_wav, meta in _samples_with_paths(batch, export_dir):
        try:
            audio_hash = meta.audio_hash or compute_audio_hash(src_wav)
        except OSError as e:
            result.skipped.append((src_wav, f"hash_failed: {e}"))
            continue

        bucket = classify(meta)
        dest_dir = samples_root / bucket.subpath

        if _hash_already_in_dir(dest_dir, audio_hash):
            result.skipped.append((src_wav, "already_routed"))
            continue

        n = next_index(dest_dir, slug, bucket)
        filename = build_filename(slug, bucket, n, bars=meta.bars)
        dest_wav = dest_dir / filename

        try:
            _copy_with_sidecar(src_wav, dest_wav, audio_hash=audio_hash, copy_mode=copy)
        except OSError as e:
            result.skipped.append((src_wav, f"copy_failed: {e}"))
            continue

        # Stamp the meta we record with the audio_hash (in case it was missing)
        recorded_meta = meta.model_copy(update={"audio_hash": audio_hash, "file": filename})
        result.records.append(RouteRecord(
            source_wav=src_wav,
            dest_wav=dest_wav,
            bucket=bucket.subpath,
            audio_hash=audio_hash,
            meta=recorded_meta,
        ))

    if write_run_manifest:
        _write_run_manifest(library_root, result,
                            source_export_dir=export_dir,
                            project_bpm=batch.bpm)
    return result


def _hash_already_in_dir(dest_dir: Path, audio_hash: str) -> bool:
    """Return True if any sidecar in `dest_dir` already references this hash."""
    if not dest_dir.exists():
        return False
    target = f".manifest_{audio_hash}.json"
    return (dest_dir / target).exists()
