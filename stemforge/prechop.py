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

from .manifest_schema import SampleMeta, Stem, compute_audio_hash, write_sidecar


# ── Phase-3 leading-partial-chunk gates ──────────────────────────────────────
# A "leading partial chunk" is an extra chunk_001 that holds the sub-chunk-
# period intro material that sits before bar 1 (and before any whole-chunk
# pre-bars chunks). It exists because the pad-stash convention can only hide
# audio shorter than `pad_pre_bars` worth; anything longer needs a visible
# clip in arrangement view to be reachable.

# Minimum fraction of one chunk-period for the leftover region to be
# considered worth emitting. Default 0 = any non-empty leftover triggers
# a visible chunk_001 so users can reach pre-bar-1 transients without
# manual clip-edge dragging. Tweak only if you have a specific reason.
MIN_LEFTOVER_FRAC = 0.0


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
    audio_hash: str | None = None  # 16-hex sha256 prefix of the chunk WAV

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
    emit_partial: bool = False,
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

    # Phase-3 leading-partial-chunk: covers the sub-chunk-period intro
    # remainder that sits BEFORE the first whole-chunk pre-bars chunk
    # (or before the first post-downbeat chunk, when no pre-bars).
    # Composes with arbitrary `pre_bars` because leftover is computed
    # against the actual `n_pre_chunks` we'll emit.
    do_emit_partial = False
    leftover_frames = 0
    silence_left_frames = 0
    if emit_partial and first_downbeat_sec > 0:
        leftover_frames = downbeat_offset - n_pre_chunks * chunk_frames
        if 0 < leftover_frames < chunk_frames:
            do_emit_partial = True
            silence_left_frames = chunk_frames - leftover_frames

    if n_post_chunks == 0 and n_pre_chunks == 0 and not do_emit_partial:
        return []

    out_dir = output_dir / f"{stem_name}_prechop"
    out_dir.mkdir(parents=True, exist_ok=True)

    metas: list[ChunkMeta] = []
    partial_offset = 1 if do_emit_partial else 0
    # Iterate from the OLDEST pre-chunk to the NEWEST post-chunk so chunk
    # filenames are 1-indexed in timeline order. `partial_offset` shifts
    # everything to make room for a chunk_001 emitted below.
    iter_indices = list(range(-n_pre_chunks, n_post_chunks))
    for timeline_index, i in enumerate(iter_indices):
        target_start = downbeat_offset + i * chunk_frames
        target_end = target_start + chunk_frames

        # Read window (clamped to file). Pre-pad and post-pad are now
        # independently configurable via pad_pre_frames / pad_post_frames.
        read_start = max(0, target_start - pad_pre_frames)
        read_end = min(total, target_end + pad_post_frames)
        chunk = y[read_start:read_end, :]

        # Pre-source silence padding. When the chunk's WAV layout would extend
        # left of source frame 0 — either because target_start < 0 (a pre-chunk
        # whose loop region crosses source 0) or because target_start <
        # pad_pre_frames (a near-start chunk whose pad_pre region runs off the
        # left edge) — prepend silence to make the music body land at the
        # correct WAV-frame position. Without this, actual_pre below either
        # goes negative (loop_start_sec/loop_end_sec turn negative in the
        # manifest, breaking the M4L loader and showing as visual gaps in
        # Ableton) or under-fills the pre-pad region inconsistently across
        # chunks. Silence at the START represents source frames before file
        # start that don't exist on disk.
        silence_before_frames = max(0, pad_pre_frames - target_start)
        if silence_before_frames > 0:
            silence_before = np.zeros((silence_before_frames, chunk.shape[1]), dtype=chunk.dtype)
            chunk = np.concatenate([silence_before, chunk], axis=0)
            actual_pre = pad_pre_frames
        else:
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
        # `partial_offset` shifts indices to leave chunk_001 for the
        # leading-partial chunk emitted after this loop.
        chunk_index_1based = timeline_index + 1 + partial_offset
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
            audio_hash=compute_audio_hash(fname),
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

    if do_emit_partial:
        # Leading partial chunk: holds the [0, leftover_sec) intro
        # remainder, silence-padded on the LEFT inside the loop region so
        # arrangement-view bars stay aligned. Pre-pad is all silence
        # (nothing exists earlier than source 0); post-pad reads the start
        # of what's in chunk_002.
        n_chan = y.shape[1]
        partial_index = 1

        pre_pad_silence = np.zeros((pad_pre_frames, n_chan), dtype=y.dtype)
        loop_silence_left = np.zeros((silence_left_frames, n_chan), dtype=y.dtype)
        leading_region = y[0:leftover_frames, :]

        post_pad_end = min(total, leftover_frames + pad_post_frames)
        post_pad_real = y[leftover_frames:post_pad_end, :]
        if post_pad_real.shape[0] < pad_post_frames:
            tail = np.zeros(
                (pad_post_frames - post_pad_real.shape[0], n_chan),
                dtype=y.dtype,
            )
            post_pad_real = np.concatenate([post_pad_real, tail], axis=0)

        partial_wav = np.concatenate(
            [pre_pad_silence, loop_silence_left, leading_region, post_pad_real],
            axis=0,
        )

        partial_fname = out_dir / f"{stem_name}_chunk_{partial_index:03d}.wav"
        sf.write(str(partial_fname), partial_wav, sr, subtype="PCM_24")

        loop_start_sec = pad_pre_frames / float(sr)
        loop_end_sec = (pad_pre_frames + chunk_frames) / float(sr)
        # Map "loop region start" → source frame -silence_left (the silent
        # part of the loop region represents source frames before disk
        # frame 0). Lets `_sourceTimeAtTimelineBeat` produce 0 at the
        # WAV-frame boundary where real audio begins.
        partial_source_offset_sec = -silence_left_frames / float(sr)

        partial_meta = ChunkMeta(
            file=str(partial_fname.relative_to(output_dir)),
            stem=stem_name,
            chunk_index=partial_index,
            bars=bars,
            pad_bars=pad_bars,
            pad_pre_bars=float(pad_pre_bars),
            pad_post_bars=float(pad_post_bars),
            loop_start_sec=loop_start_sec,
            loop_end_sec=loop_end_sec,
            total_sec=partial_wav.shape[0] / float(sr),
            chunk_duration_samples=int(partial_wav.shape[0]),
            sample_rate=int(sr),
            source_offset_sec=partial_source_offset_sec,
            audio_hash=compute_audio_hash(partial_fname),
        )
        metas.insert(0, partial_meta)

        if write_sidecars:
            stem_literal_partial: Stem | None = (
                stem_name  # type: ignore[assignment]
                if stem_name in {"drums", "bass", "vocals", "other", "full"}
                else None
            )
            partial_sidecar = SampleMeta(
                name=f"{stem_name} {partial_index:03d}",
                bpm=float(bpm),
                time_mode="bpm",
                bars=float(bars),
                playmode="key",
                stem=stem_literal_partial,
                role="loop",
            )
            write_sidecar(partial_fname, partial_sidecar)

    return metas


# ── Top-level orchestrator ───────────────────────────────────────────────────


def _decide_emit_partial(
    stem_paths: dict[str, Path],
    skip_set: set[str],
    *,
    bpm: float,
    bars: int,
    beats_per_bar: int,
    first_downbeat_sec: float,
    n_pre_chunks: int,
) -> bool:
    """Phase-3 gating: should we emit a leading partial chunk?

    Two boundary gates, AND-combined:

    1. `first_downbeat_sec > 0` — there's pre-downbeat material to consider.
    2. `0 < leftover_frames < chunk_frames` — the leftover region (the
       sub-chunk-period intro that sits between source frame 0 and the
       first whole pre-chunk, or between source 0 and the first
       post-downbeat chunk when no pre-bars) has audio worth a chunk
       AND isn't already covered by a whole pre-bars chunk.

    No content gate: when the user supplies an explicit downbeat (split
    --first-downbeat or re-anchor), they intend to keep the intro
    regardless of audio level. The previous RMS gate (≥ -60 dBFS across
    any stem) was a binary cliff that flipped the decision based on
    sub-dB noise-floor drift between Demucs runs. Per
    ``feedback_downbeat_alignment``, we trust user-driven downbeats
    explicitly; auto-detection paths funnel through the same gate but
    typically land on first_downbeat=0 or a whole-bar-aligned position
    where the leftover region is already empty.

    Decision is shared across all stems for arrangement-loader consistency
    (parallel chunks must align across tracks). The ``stem_paths`` /
    ``skip_set`` parameters are retained for ABI back-compat with callers
    who pass them; they're no longer read.
    """
    del stem_paths, skip_set  # retained for ABI; no longer consulted
    if first_downbeat_sec <= 0:
        return False
    if bpm <= 0 or bars <= 0 or beats_per_bar <= 0:
        return False

    # Reference SR comes from the first stem path's sample rate normally;
    # since we no longer open files for the RMS gate, we compute everything
    # in beat-period space which is sample-rate-agnostic.
    bar_period_sec = bars * beats_per_bar * 60.0 / bpm
    if bar_period_sec <= 0:
        return False
    leftover_sec = first_downbeat_sec - n_pre_chunks * bar_period_sec
    if leftover_sec <= 0 or leftover_sec >= bar_period_sec:
        return False
    leftover_frac = leftover_sec / bar_period_sec
    if leftover_frac < MIN_LEFTOVER_FRAC:
        return False
    return True


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
    emit_partial: bool | None = None,
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

    if emit_partial is None:
        emit_partial = _decide_emit_partial(
            stem_paths,
            skip_set,
            bpm=bpm,
            bars=bars,
            beats_per_bar=beats_per_bar,
            first_downbeat_sec=first_downbeat_sec,
            n_pre_chunks=n_pre_chunks,
        )

    # 0-indexed: chunks[0..n_pre_chunks-1] are intro, chunks[n_pre_chunks]
    # is the first chunk that starts at first_downbeat_sec (i.e., bar 1).
    # Earlier versions stored this 1-indexed by accident; the only consumer
    # (sf_locator_anchor.js) treats it 0-indexed.
    # When a leading partial chunk is emitted, it sits at chunks[0] and
    # bumps everything down by one.
    musical_bar_1_chunk_index = n_pre_chunks + (1 if emit_partial else 0)
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
        "leading_partial_emitted": bool(emit_partial),
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
            emit_partial=emit_partial,
        )
        summary["stems"][stem_name] = {
            "dir": f"{stem_name}_prechop",
            "chunks": [m.asdict() for m in metas],
            "chunk_count": len(metas),
        }

    out_path = output_dir / "prechop_manifest.json"
    # Hardening Stream A.2 — validate at the write boundary so producer-side
    # shape drift fails loud at the CLI rather than at downstream M4L read.
    from .schemas import validate_prechop_manifest

    validate_prechop_manifest(summary)
    out_path.write_text(json.dumps(summary, indent=2))
    return out_path


__all__ = [
    "ChunkMeta",
    "chunk_count_for",
    "frames_per_bar",
    "prechop",
    "prechop_stem",
]
