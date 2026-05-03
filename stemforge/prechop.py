"""
stemforge.prechop — Pad-aware bar-aligned WAV chopper for arrangement-view loading.

Slices full-song stem WAVs into N-bar chunks, with optional padding bars on
either side so each chunk has audio room to drag-extend or pre-roll. Each chunk
records a "loop region" inside the padded WAV — the offsets of the *target*
N-bar window, so consumers (the M4L arrangement-view loader) can set the
clip's loop-start/loop-end to play only the target region by default while
still letting the user expand into the padding.

Two key decisions baked into this module:

1.  Loop-region convention: `loop_start_sec`/`loop_end_sec` are offsets WITHIN
    the padded WAV (not into the original stem). For a fully-padded interior
    chunk both are nonzero; for the first chunk where there's no audio to pad
    `loop_start_sec` is 0; etc.

2.  Last-chunk uniformity: when `pad_last=True` (default), the final chunk is
    silence-padded to the same total frame count as every other chunk so all
    files in a batch share a uniform timeline. Otherwise the final chunk is
    truncated to whatever audio is actually available.

Output layout (per stem):
    {output_dir}/{stem_name}_prechop/
        {stem_name}_chunk_001.wav   ← (bars + 2*pad_bars) bars wide
        {stem_name}_chunk_002.wav
        ...
        .manifest_<hash>.json       ← per-chunk SampleMeta sidecars

Top-level summary (across all stems):
    {output_dir}/prechop_manifest.json
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import soundfile as sf

from .manifest_schema import SampleMeta, Stem, write_sidecar


# ── Math helpers ─────────────────────────────────────────────────────────────


def frames_per_bar(bpm: float, sr: int, beats_per_bar: int = 4) -> int:
    """Frames in one bar at given tempo. 4 beats/bar by default."""
    # TODO(time-sig): support 6/8, 3/4 — manifest already records beats_per_bar
    # but the loader assumes 4/4 (Live treats "beat" as quarter-note; for 6/8
    # we'd need to map eighth-note beats to Live's quarter-note clock or pass
    # a separate `denominator` field through the manifest schema).
    seconds_per_beat = 60.0 / float(bpm)
    return int(round(seconds_per_beat * beats_per_bar * sr))


def chunk_count_for(total_frames: int, fpb: int, bars: int, pad_last: bool = True) -> int:
    """How many N-bar chunks fit in `total_frames`.

    With `pad_last=True`, any partial trailing chunk that contains *any* audio
    counts as a full chunk (we'll silence-pad it). With `pad_last=False`, only
    fully-covered N-bar windows count.
    """
    chunk_frames = fpb * bars
    if chunk_frames <= 0:
        return 0
    if pad_last:
        # ceil division — any leftover audio earns a chunk.
        return (total_frames + chunk_frames - 1) // chunk_frames
    return total_frames // chunk_frames


# ── Per-chunk metadata ───────────────────────────────────────────────────────


@dataclass
class ChunkMeta:
    """One row in `prechop_manifest.json` per chunk file."""

    file: str  # path relative to manifest dir
    stem: str  # "drums", "bass", ...
    chunk_index: int  # 1-based
    bars: int  # target bars (the loop region length)
    pad_bars: int  # configured padding (per side)
    pad_pre_bars: float  # ACTUAL bars of pre-roll padding (clamped at start)
    pad_post_bars: float  # ACTUAL bars of post-roll padding (clamped at end)
    loop_start_sec: float
    loop_end_sec: float
    total_sec: float  # total duration of the padded WAV
    chunk_duration_samples: int = 0  # integer frame count — catches silent resamples
    sample_rate: int = 0  # WAV sample rate
    source_offset_sec: float = 0.0  # where in the source stem this chunk's bar 1 sits

    def asdict(self) -> dict:
        return asdict(self)


# ── Core: chunk a single stem ────────────────────────────────────────────────


def prechop_stem(
    stem_path: Path,
    output_dir: Path,
    stem_name: str,
    *,
    bpm: float,
    bars: int = 4,
    pad_bars: int = 1,
    pad_last: bool = True,
    beats_per_bar: int = 4,
    write_sidecars: bool = True,
    first_downbeat_sec: float = 0.0,
    pre_bars: int = 0,
    pad_pre_bars: int | None = None,
    pad_post_bars: int | None = None,
) -> list[ChunkMeta]:
    """Chop one stem into padded N-bar chunks. See module docstring.

    `first_downbeat_sec`: where bar 1 starts in the source stem. Pre-downbeat
    audio (the intro / count-in / measure-fragment that precedes the first
    musical bar) is dropped from the chunk grid so chunks align on real
    musical bar boundaries. Default 0.0 preserves the legacy "start at frame
    zero" behavior for callers that don't have downbeat information.

    `pre_bars`: how many bars of intro material BEFORE bar 1 to include as
    additional chunks at the same bar grid. Useful when first_downbeat_sec
    is large (e.g. hip-hop tracks with long DJ intros) and you don't want
    to lose the intro. The pre-chunks come first in the timeline; chunk 1
    is the OLDEST pre-chunk, and the chunk corresponding to musical bar 1
    is `(pre_bars // bars) + 1`. Pre-chunks that would land entirely before
    the audio file's first frame are silently skipped.

    `pad_pre_bars` / `pad_post_bars`: split-controllable padding (default to
    `pad_bars` for backward compat). Setting `pad_pre_bars=0` makes WAV
    frame 0 == loop_start == bar 1's audio, which is what you want when
    you don't trust the downstream loader's start_marker handling. When
    chunk 1's source frames would otherwise be clamped (= source has less
    audio before bar 1 than `pad_pre_bars × bar_period`), trimming pre-pad
    avoids embedding pure silence at the chunk's start.
    """
    if bars <= 0:
        raise ValueError(f"bars must be > 0, got {bars}")
    if pad_bars < 0:
        raise ValueError(f"pad_bars must be >= 0, got {pad_bars}")
    if bpm <= 0:
        raise ValueError(f"bpm must be > 0, got {bpm}")
    if first_downbeat_sec < 0:
        raise ValueError(f"first_downbeat_sec must be >= 0, got {first_downbeat_sec}")
    if pre_bars < 0:
        raise ValueError(f"pre_bars must be >= 0, got {pre_bars}")

    # Resolve pre/post pad (back-compat default = symmetric pad_bars).
    if pad_pre_bars is None:
        pad_pre_bars = pad_bars
    if pad_post_bars is None:
        pad_post_bars = pad_bars
    if pad_pre_bars < 0 or pad_post_bars < 0:
        raise ValueError(
            f"pad_pre_bars and pad_post_bars must be >= 0, got {pad_pre_bars}/{pad_post_bars}"
        )

    y, sr = sf.read(str(stem_path), always_2d=True)  # (frames, channels)
    total = y.shape[0]

    fpb = frames_per_bar(bpm, sr, beats_per_bar=beats_per_bar)
    chunk_frames = fpb * bars
    pad_pre_frames = fpb * pad_pre_bars
    pad_post_frames = fpb * pad_post_bars
    target_total_frames = chunk_frames + pad_pre_frames + pad_post_frames

    # Anchor the chunk grid on the first detected downbeat.
    downbeat_offset = int(round(first_downbeat_sec * sr))

    # Available audio AFTER the downbeat — that's what the post-downbeat chunk
    # count covers.
    audio_after_downbeat = max(0, total - downbeat_offset)
    n_post_chunks = chunk_count_for(audio_after_downbeat, fpb, bars, pad_last=pad_last)

    # Pre-downbeat chunks: how many full N-bar windows of intro material we
    # want, capped by what fits before downbeat_offset (skip windows that
    # would land entirely before the audio file's start).
    n_pre_chunks_requested = pre_bars // bars
    n_pre_chunks = 0
    for k in range(1, n_pre_chunks_requested + 1):
        cand_start = downbeat_offset - k * chunk_frames
        # Skip if the entire chunk window (including its loop region end)
        # would land before the audio file starts.
        if cand_start + chunk_frames <= 0:
            break
        n_pre_chunks = k

    if n_post_chunks == 0 and n_pre_chunks == 0:
        return []

    out_dir = output_dir / f"{stem_name}_prechop"
    out_dir.mkdir(parents=True, exist_ok=True)

    metas: list[ChunkMeta] = []
    # Iterate from the OLDEST pre-chunk to the NEWEST post-chunk so chunk
    # filenames are 1-indexed in timeline order.
    iter_indices = list(range(-n_pre_chunks, n_post_chunks))
    for timeline_index, i in enumerate(iter_indices):
        target_start = downbeat_offset + i * chunk_frames
        target_end = target_start + chunk_frames

        # Read window (clamped to file). Pre-pad and post-pad are now
        # independently configurable via pad_pre_frames / pad_post_frames.
        read_start = max(0, target_start - pad_pre_frames)
        read_end = min(total, target_end + pad_post_frames)
        chunk = y[read_start:read_end, :]

        # Actual padding applied (in frames, may be < requested at edges).
        actual_pre = target_start - read_start
        actual_post = read_end - target_end  # may be negative if last chunk truncated

        # If we want every chunk to be the same length, pad with silence.
        if pad_last:
            # Silence-pad the END so the last chunk reaches target_total_frames.
            if chunk.shape[0] < target_total_frames:
                missing = target_total_frames - chunk.shape[0]
                silence = np.zeros((missing, chunk.shape[1]), dtype=chunk.dtype)
                chunk = np.concatenate([chunk, silence], axis=0)
            # Note: actual_post is recomputed against the (now silence-extended)
            # written length so the loop region still points at real audio +
            # the silence tail past target_end is padding.
            actual_post = chunk.shape[0] - chunk_frames - actual_pre

        # Loop-region offsets within the padded WAV.
        loop_start_frames = actual_pre
        loop_end_frames = actual_pre + chunk_frames
        # Clamp loop_end to actual chunk length (in case of pad_last=False on a
        # truncated final chunk).
        loop_end_frames = min(loop_end_frames, chunk.shape[0])

        loop_start_sec = loop_start_frames / float(sr)
        loop_end_sec = loop_end_frames / float(sr)
        total_sec = chunk.shape[0] / float(sr)

        # 1-indexed in timeline order — pre-chunks come first, then post.
        chunk_index_1based = timeline_index + 1
        fname = out_dir / f"{stem_name}_chunk_{chunk_index_1based:03d}.wav"
        sf.write(str(fname), chunk, sr, subtype="PCM_24")

        cm = ChunkMeta(
            file=str(fname.relative_to(output_dir)),
            stem=stem_name,
            chunk_index=chunk_index_1based,
            bars=bars,
            pad_bars=pad_bars,
            pad_pre_bars=actual_pre / float(fpb) if fpb else 0.0,
            pad_post_bars=actual_post / float(fpb) if fpb else 0.0,
            loop_start_sec=loop_start_sec,
            loop_end_sec=loop_end_sec,
            total_sec=total_sec,
            chunk_duration_samples=int(chunk.shape[0]),
            sample_rate=int(sr),
            source_offset_sec=float(target_start) / float(sr),
        )
        metas.append(cm)

        if write_sidecars:
            stem_literal: Stem | None = (
                stem_name  # type: ignore[assignment]
                if stem_name in {"drums", "bass", "vocals", "other", "full"}
                else None
            )
            meta = SampleMeta(
                name=f"{stem_name} {chunk_index_1based:03d}",
                bpm=float(bpm),
                time_mode="bpm",
                bars=float(bars),
                playmode="key",
                stem=stem_literal,
                role="loop",
            )
            write_sidecar(fname, meta)

    return metas


# ── Top-level orchestrator ───────────────────────────────────────────────────


def prechop(
    stem_paths: dict[str, Path],
    output_dir: Path,
    *,
    bpm: float,
    bars: int = 4,
    pad_bars: int = 1,
    pad_last: bool = True,
    beats_per_bar: int = 4,
    write_sidecars: bool = True,
    skip_stems: Iterable[str] = ("residual",),
    first_downbeat_sec: float = 0.0,
    pre_bars: int = 0,
    pad_pre_bars: int | None = None,
    pad_post_bars: int | None = None,
) -> Path:
    """Run prechop_stem across a stems dict. Writes a top-level manifest.

    `pre_bars`: bars of intro material BEFORE the first downbeat to include
    as additional chunks at the same bar grid (see `prechop_stem`).
    Records `musical_bar_1_chunk_index` in the manifest so loaders can
    distinguish intro chunks from main-beat chunks.

    `pad_pre_bars` / `pad_post_bars`: split-control padding (default to
    `pad_bars` for back-compat). Set `pad_pre_bars=0` to make WAV frame 0
    of every chunk land on bar 1 of that chunk — eliminates leading-silence
    artifacts from the loader.

    Returns the path to `prechop_manifest.json`.
    """
    skip_set = set(skip_stems)
    n_pre_chunks = pre_bars // bars  # chunks before bar 1 (timeline-leading)
    musical_bar_1_chunk_index = n_pre_chunks + 1  # 1-indexed
    resolved_pre = pad_bars if pad_pre_bars is None else pad_pre_bars
    resolved_post = pad_bars if pad_post_bars is None else pad_post_bars
    summary: dict = {
        "bpm": float(bpm),
        "bars": int(bars),
        "pad_bars": int(pad_bars),
        "pad_pre_bars": int(resolved_pre),
        "pad_post_bars": int(resolved_post),
        "pad_last": bool(pad_last),
        "beats_per_bar": int(beats_per_bar),
        "first_downbeat_sec": float(first_downbeat_sec),
        "pre_bars": int(pre_bars),
        "musical_bar_1_chunk_index": int(musical_bar_1_chunk_index),
        "stems": {},
    }

    for stem_name, stem_path in stem_paths.items():
        if stem_name in skip_set:
            continue
        metas = prechop_stem(
            stem_path,
            output_dir,
            stem_name,
            bpm=bpm,
            bars=bars,
            pad_bars=pad_bars,
            pad_last=pad_last,
            beats_per_bar=beats_per_bar,
            write_sidecars=write_sidecars,
            first_downbeat_sec=first_downbeat_sec,
            pre_bars=pre_bars,
            pad_pre_bars=pad_pre_bars,
            pad_post_bars=pad_post_bars,
        )
        summary["stems"][stem_name] = {
            "dir": f"{stem_name}_prechop",
            "chunks": [m.asdict() for m in metas],
            "chunk_count": len(metas),
        }

    out_path = output_dir / "prechop_manifest.json"
    out_path.write_text(json.dumps(summary, indent=2))
    return out_path


__all__ = [
    "ChunkMeta",
    "chunk_count_for",
    "frames_per_bar",
    "prechop",
    "prechop_stem",
]
