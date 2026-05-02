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
) -> list[ChunkMeta]:
    """Chop one stem into padded N-bar chunks. See module docstring.

    `first_downbeat_sec`: where bar 1 starts in the source stem. Pre-downbeat
    audio (the intro / count-in / measure-fragment that precedes the first
    musical bar) is dropped from the chunk grid so chunks align on real
    musical bar boundaries. Default 0.0 preserves the legacy "start at frame
    zero" behavior for callers that don't have downbeat information.
    """
    if bars <= 0:
        raise ValueError(f"bars must be > 0, got {bars}")
    if pad_bars < 0:
        raise ValueError(f"pad_bars must be >= 0, got {pad_bars}")
    if bpm <= 0:
        raise ValueError(f"bpm must be > 0, got {bpm}")
    if first_downbeat_sec < 0:
        raise ValueError(f"first_downbeat_sec must be >= 0, got {first_downbeat_sec}")

    y, sr = sf.read(str(stem_path), always_2d=True)  # (frames, channels)
    total = y.shape[0]

    fpb = frames_per_bar(bpm, sr, beats_per_bar=beats_per_bar)
    chunk_frames = fpb * bars
    pad_frames = fpb * pad_bars
    target_total_frames = chunk_frames + 2 * pad_frames

    # Anchor the chunk grid on the first detected downbeat. Audio before that
    # is preserved on disk (used for pre-roll padding of chunk 1) but the
    # chunk-start positions advance from `downbeat_offset` onward.
    downbeat_offset = int(round(first_downbeat_sec * sr))

    # Available audio AFTER the downbeat — that's what the chunk count covers.
    audio_after_downbeat = max(0, total - downbeat_offset)
    n_chunks = chunk_count_for(audio_after_downbeat, fpb, bars, pad_last=pad_last)
    if n_chunks == 0:
        return []

    out_dir = output_dir / f"{stem_name}_prechop"
    out_dir.mkdir(parents=True, exist_ok=True)

    metas: list[ChunkMeta] = []

    for i in range(n_chunks):
        target_start = downbeat_offset + i * chunk_frames
        target_end = target_start + chunk_frames

        # Read window (clamped to file).
        read_start = max(0, target_start - pad_frames)
        read_end = min(total, target_end + pad_frames)
        chunk = y[read_start:read_end, :]

        # Actual padding applied (in frames, may be < pad_frames at edges).
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

        fname = out_dir / f"{stem_name}_chunk_{i + 1:03d}.wav"
        sf.write(str(fname), chunk, sr, subtype="PCM_24")

        cm = ChunkMeta(
            file=str(fname.relative_to(output_dir)),
            stem=stem_name,
            chunk_index=i + 1,
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
                name=f"{stem_name} {i + 1:03d}",
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
) -> Path:
    """Run prechop_stem across a stems dict. Writes a top-level manifest.

    Returns the path to `prechop_manifest.json`.
    """
    skip_set = set(skip_stems)
    summary: dict = {
        "bpm": float(bpm),
        "bars": int(bars),
        "pad_bars": int(pad_bars),
        "pad_last": bool(pad_last),
        "beats_per_bar": int(beats_per_bar),
        "first_downbeat_sec": float(first_downbeat_sec),
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
