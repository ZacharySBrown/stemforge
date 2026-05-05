"""Tests for `stemforge.prechop` — padded N-bar chopping + loop offsets."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from stemforge.prechop import (
    MIN_LEFTOVER_FRAC,
    SILENCE_THRESHOLD_DBFS,
    _decide_emit_partial,
    chunk_count_for,
    frames_per_bar,
    prechop,
    prechop_stem,
)


SR = 22050
BPM = 120.0  # 0.5 sec/beat → 2.0 sec/bar at 4/4 → 44100 frames/bar at SR=22050
FPB = frames_per_bar(BPM, SR, beats_per_bar=4)


def _write_silent_stem(path: Path, n_frames: int, n_chan: int = 2):
    y = np.zeros((n_frames, n_chan), dtype=np.float32)
    sf.write(str(path), y, SR, subtype="PCM_24")


def _write_marker_stem(path: Path, n_frames: int):
    """Stereo stem with a low-amplitude DC offset that varies by frame index.

    Lets us verify that loop_start/end map to the original audio offsets:
    the value of the audio at frame f equals f / float(n_frames). Reading
    back a chunk and checking its first/last sample tells us where in the
    source it came from.
    """
    t = np.arange(n_frames, dtype=np.float32) / float(n_frames)
    stereo = np.stack([t, t], axis=1)
    sf.write(str(path), stereo, SR, subtype="PCM_24")


def test_frames_per_bar_round_number():
    # 120 BPM, SR=22050, 4 beats/bar → 60/120 * 4 * 22050 = 44100
    assert frames_per_bar(120.0, 22050) == 44100


def test_chunk_count_pad_last_true_includes_partial():
    # 16 bars of audio + 0.5 bar leftover with pad_last=True → 17 chunks for bars=1.
    total = FPB * 16 + FPB // 2
    assert chunk_count_for(total, FPB, 1, pad_last=True) == 17
    assert chunk_count_for(total, FPB, 1, pad_last=False) == 16


def test_padded_chunk_total_frames_uniform(tmp_path):
    # 8 bars of audio, bars=4 → 2 chunks, both with full pre+post padding.
    bars = 4
    pad_bars = 1
    n_frames = FPB * 8
    stem = tmp_path / "drums.wav"
    _write_silent_stem(stem, n_frames)

    metas = prechop_stem(
        stem,
        tmp_path,
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=pad_bars,
        pad_last=True,
        write_sidecars=False,
    )

    assert len(metas) == 2
    expected_total = (bars + 2 * pad_bars) * FPB
    for cm in metas:
        wav = tmp_path / cm.file
        data, sr = sf.read(str(wav))
        assert sr == SR
        assert data.shape[0] == expected_total, (
            f"expected {expected_total} frames, got {data.shape[0]}"
        )


def test_loop_region_round_trips_to_target_audio(tmp_path):
    # Use the marker stem so we can read back chunk audio and prove the loop
    # region points at the right window of the source.
    bars = 2
    pad_bars = 1
    n_bars_total = 6
    n_frames = FPB * n_bars_total
    stem = tmp_path / "drums.wav"
    _write_marker_stem(stem, n_frames)

    metas = prechop_stem(
        stem,
        tmp_path,
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=pad_bars,
        pad_last=True,
        write_sidecars=False,
    )
    # 6 / 2 = 3 chunks; chunk 2 is the only one with full pre+post padding.
    assert len(metas) == 3
    interior = metas[1]

    # Loop region should be exactly [pad_bars, pad_bars + bars] in bars.
    assert abs(interior.pad_pre_bars - pad_bars) < 1e-6
    assert abs(interior.loop_start_sec - pad_bars * (FPB / float(SR))) < 1e-6
    assert abs(interior.loop_end_sec - (pad_bars + bars) * (FPB / float(SR))) < 1e-6

    # Read chunk 2; the sample at the loop_start frame should equal the source
    # audio at the start of chunk 2's target window (= 1 chunk in = bars*FPB).
    wav = tmp_path / interior.file
    data, sr = sf.read(str(wav), always_2d=True)
    loop_start_frame = int(round(interior.loop_start_sec * sr))
    expected_value = (bars * FPB) / float(n_frames)  # marker-stem: t=frame/n_frames
    actual_value = float(data[loop_start_frame, 0])
    assert abs(actual_value - expected_value) < 1e-3, (
        f"loop-start mapped to wrong source frame: "
        f"expected source value {expected_value}, got {actual_value}"
    )


def test_pre_chunk_crossing_source_zero_silence_pads_at_start(tmp_path):
    """Regression test for the 2026-05-03 prechop pre-chunk fix.

    When a pre-chunk's source range crosses source 0 (target_start < 0),
    earlier code appended silence at the END of the WAV via pad_last and
    wrote NEGATIVE loop_start_sec/loop_end_sec into the manifest. The M4L
    arrangement loader passes those values to Live's start_marker, which
    silently clamps negative values, producing visible gaps between
    chunks in the arrangement view.

    The fix: prepend silence to the WAV so the music body lands at the
    correct WAV-frame position; loop_start_frames is always pad_pre_frames
    (non-negative); the leading silence frames represent the missing
    pre-source region (source content that doesn't exist on disk).

    Setup: 1 bar of source intro, first_downbeat at exactly 1 bar in,
    then 8 bars of "real" song. With bars=4 chunks and pre_bars=4, the
    prechop generates one pre-chunk whose source range is [-3 bars, +1 bar]
    — i.e., target_start = -3 bars (NEGATIVE). The fix puts 3 bars of
    silence at the start of that chunk's WAV.
    """
    bars = 4
    pad_pre_bars = 1
    pad_post_bars = 1
    pre_bars = bars  # one pre-chunk's worth, identical to chunk size
    bar_frames = FPB
    n_intro_frames = 1 * bar_frames  # 1 bar of intro source
    n_total_frames = 9 * bar_frames  # 1 bar intro + 8 bars song
    first_downbeat_sec = bar_frames / float(SR)  # exactly 1 bar in

    stem = tmp_path / "drums.wav"
    _write_marker_stem(stem, n_total_frames)

    metas = prechop_stem(
        stem,
        tmp_path,
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=1,
        pad_last=True,
        first_downbeat_sec=first_downbeat_sec,
        pre_bars=pre_bars,
        pad_pre_bars=pad_pre_bars,
        pad_post_bars=pad_post_bars,
        write_sidecars=False,
    )

    # Layout: 1 pre-chunk + N post-chunks. Pre-chunk's target_start is
    # 1 bar (downbeat) - 4 bars (pre_bars) = -3 bars (negative).
    pre_chunk = metas[0]

    # Loop offsets must be NON-NEGATIVE (the bug-fix invariant).
    assert pre_chunk.loop_start_sec >= 0, (
        f"loop_start_sec must be non-negative; got {pre_chunk.loop_start_sec}. "
        "Negative values break the M4L loader's start_marker."
    )
    assert pre_chunk.loop_end_sec > pre_chunk.loop_start_sec
    # Every chunk's WAV total length should be (bars + pad_pre + pad_post) bars.
    expected_total_frames = (bars + pad_pre_bars + pad_post_bars) * bar_frames
    expected_total_sec = expected_total_frames / float(SR)
    assert abs(pre_chunk.total_sec - expected_total_sec) < 1e-6
    # Loop length should equal exactly bars worth of seconds (consistent across all chunks).
    expected_loop_sec = bars * (bar_frames / float(SR))
    assert abs((pre_chunk.loop_end_sec - pre_chunk.loop_start_sec) - expected_loop_sec) < 1e-6
    # Loop should start at the pad_pre boundary (always pad_pre_seconds in).
    assert abs(pre_chunk.loop_start_sec - pad_pre_bars * (bar_frames / float(SR))) < 1e-6

    # And the prepended silence is REAL silence — not source audio. Read the
    # first frames of the WAV; they must be zero.
    wav = tmp_path / pre_chunk.file
    data, _ = sf.read(str(wav), always_2d=True)
    # The first 3 bars (the missing-pre-source region) plus 1 bar pad_pre =
    # WAV frames [0, 4*FPB] should all be zero (silence).
    silence_region = data[: 3 * bar_frames + pad_pre_bars * bar_frames, :]
    assert np.allclose(silence_region, 0.0), (
        "pre-chunk's leading region must be silence (representing source < 0)"
    )

    # Sanity: every other chunk must have the same total + loop layout.
    for cm in metas[1:]:
        assert abs(cm.total_sec - expected_total_sec) < 1e-6
        assert abs((cm.loop_end_sec - cm.loop_start_sec) - expected_loop_sec) < 1e-6
        assert abs(cm.loop_start_sec - pre_chunk.loop_start_sec) < 1e-6


def test_first_chunk_silence_pads_pre_padding(tmp_path):
    # Convention (post-2026-05-03): every chunk's pad_pre region is exactly
    # pad_bars worth, silence-padded if the source can't supply real audio
    # there. So the first chunk's pad_pre_bars == pad_bars (silence), the
    # loop starts at WAV frame pad_pre_seconds, and loop length == bars
    # worth of seconds. This makes all chunks uniform — required by the
    # M4L arrangement loader (start_marker = pad_pre_seconds for every clip).
    bars = 2
    pad_bars = 1
    n_frames = FPB * 4
    stem = tmp_path / "drums.wav"
    _write_silent_stem(stem, n_frames)

    metas = prechop_stem(
        stem,
        tmp_path,
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=pad_bars,
        pad_last=True,
        write_sidecars=False,
    )
    first = metas[0]
    assert first.chunk_index == 1
    assert first.pad_pre_bars == pad_bars  # silence-padded to full pad_pre
    pad_pre_sec = pad_bars * (FPB / float(SR))
    assert abs(first.loop_start_sec - pad_pre_sec) < 1e-6
    assert abs(first.loop_end_sec - (pad_pre_sec + bars * (FPB / float(SR)))) < 1e-6


def test_last_chunk_silence_padded_to_uniform_length(tmp_path):
    # 16.07-bar problem: 4 bars + tiny scrap with bars=4, pad_last=True →
    # 2 chunks, both same length.
    bars = 4
    pad_bars = 1
    # 4 full bars + 0.07 of a bar
    n_frames = FPB * 4 + int(0.07 * FPB)
    stem = tmp_path / "drums.wav"
    _write_silent_stem(stem, n_frames)

    metas = prechop_stem(
        stem,
        tmp_path,
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=pad_bars,
        pad_last=True,
        write_sidecars=False,
    )
    assert len(metas) == 2
    expected_total = (bars + 2 * pad_bars) * FPB
    for cm in metas:
        wav = tmp_path / cm.file
        data, sr = sf.read(str(wav))
        assert data.shape[0] == expected_total

    # Last chunk should have audio in the first ~0.07 bar then silence.
    last = metas[1]
    last_data, _ = sf.read(str(tmp_path / last.file), always_2d=True)
    # Tail of file (well after the scrap audio) should be zero.
    assert np.allclose(last_data[-FPB:, :], 0.0)


def test_pad_last_false_truncates_final_chunk(tmp_path):
    bars = 4
    pad_bars = 1
    n_frames = FPB * 4 + int(0.5 * FPB)  # 4.5 bars
    stem = tmp_path / "drums.wav"
    _write_silent_stem(stem, n_frames)

    metas_pad = prechop_stem(
        stem,
        tmp_path / "with_pad",
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=pad_bars,
        pad_last=True,
        write_sidecars=False,
    )
    metas_nopad = prechop_stem(
        stem,
        tmp_path / "no_pad",
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=pad_bars,
        pad_last=False,
        write_sidecars=False,
    )
    # pad_last=True keeps the half-bar scrap; pad_last=False drops it.
    assert len(metas_pad) == 2
    assert len(metas_nopad) == 1


def test_top_level_manifest_has_pad_bars_and_chunk_metadata(tmp_path):
    bars = 4
    pad_bars = 1
    n_frames = FPB * 8
    stem_drums = tmp_path / "drums.wav"
    stem_bass = tmp_path / "bass.wav"
    _write_silent_stem(stem_drums, n_frames)
    _write_silent_stem(stem_bass, n_frames)

    out = tmp_path / "out"
    out.mkdir()
    manifest_path = prechop(
        {"drums": stem_drums, "bass": stem_bass},
        out,
        bpm=BPM,
        bars=bars,
        pad_bars=pad_bars,
        pad_last=True,
        write_sidecars=False,
    )
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())

    assert data["bpm"] == BPM
    assert data["bars"] == bars
    assert data["pad_bars"] == pad_bars
    assert data["pad_last"] is True
    assert "drums" in data["stems"]
    assert "bass" in data["stems"]

    drums = data["stems"]["drums"]
    assert drums["dir"] == "drums_prechop"
    assert drums["chunk_count"] == 2
    assert len(drums["chunks"]) == 2
    chunk = drums["chunks"][0]
    assert "loop_start_sec" in chunk
    assert "loop_end_sec" in chunk
    assert "pad_pre_bars" in chunk
    assert "pad_post_bars" in chunk
    assert "total_sec" in chunk


def test_pad_bars_zero_yields_unpadded_chunks(tmp_path):
    # pad_bars=0 → loop region is the whole file; total length = bars*FPB.
    bars = 2
    n_frames = FPB * 4
    stem = tmp_path / "drums.wav"
    _write_silent_stem(stem, n_frames)

    metas = prechop_stem(
        stem,
        tmp_path,
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=0,
        pad_last=True,
        write_sidecars=False,
    )
    expected = bars * FPB
    for cm in metas:
        wav = tmp_path / cm.file
        data, _ = sf.read(str(wav))
        assert data.shape[0] == expected
        assert cm.loop_start_sec == 0.0
        assert abs(cm.loop_end_sec - expected / float(SR)) < 1e-6


# ── Phase-3: leading partial chunk emission ─────────────────────────────────


def _write_marker_stem_offset(path: Path, n_frames: int, baseline: float = 0.5):
    """Stereo stem at constant amplitude `baseline` (way above the -60 dBFS
    silence floor — ~ -6 dBFS at baseline=0.5). Lets the RMS gate's content
    detection trigger predictably without depending on per-frame variation."""
    stereo = np.full((n_frames, 2), baseline, dtype=np.float32)
    sf.write(str(path), stereo, SR, subtype="PCM_24")


def test_emit_partial_disabled_by_default_in_prechop_stem(tmp_path):
    """`prechop_stem(emit_partial=False)` (the default) emits no leading
    partial chunk regardless of `first_downbeat_sec`. Ensures Phase-3
    behavior is opt-in at this layer (gating happens in `prechop()`)."""
    bars = 4
    n_frames = FPB * 8
    first_downbeat_sec = (FPB * 2) / float(SR)  # 2 bars in (50% leftover)
    stem = tmp_path / "drums.wav"
    _write_marker_stem(stem, n_frames)

    metas = prechop_stem(
        stem,
        tmp_path,
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=1,
        pad_last=True,
        first_downbeat_sec=first_downbeat_sec,
        write_sidecars=False,
        # emit_partial omitted → defaults to False
    )
    # First chunk's source_offset_sec is non-negative; a leading partial
    # would have set it to -silence_left/sr (negative).
    assert metas[0].source_offset_sec >= 0, (
        "default (emit_partial=False) must not emit a leading partial chunk"
    )


def test_emit_partial_creates_chunk_001_with_silence_left_pad(tmp_path):
    """When `emit_partial=True` and the leftover region has audio, chunk_001
    is emitted with: pre-pad silence + silence-LEFT inside the loop region +
    real leading audio + post-pad real audio."""
    bars = 4
    pad_pre_bars = 1
    pad_post_bars = 1
    leftover_bars = 2  # 50% leftover_frac (well above 0%, has audible content)
    first_downbeat_sec = (FPB * leftover_bars) / float(SR)
    n_frames = FPB * 8
    stem = tmp_path / "drums.wav"
    _write_marker_stem_offset(stem, n_frames, baseline=0.5)

    metas = prechop_stem(
        stem,
        tmp_path,
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=1,
        pad_last=True,
        first_downbeat_sec=first_downbeat_sec,
        pad_pre_bars=pad_pre_bars,
        pad_post_bars=pad_post_bars,
        write_sidecars=False,
        emit_partial=True,
    )

    chunk_frames = bars * FPB
    pad_pre_frames = pad_pre_bars * FPB
    pad_post_frames = pad_post_bars * FPB
    leftover_frames = leftover_bars * FPB
    silence_left_frames = chunk_frames - leftover_frames

    # First meta = the new partial chunk.
    partial = metas[0]
    assert partial.chunk_index == 1
    # source_offset_sec must be NEGATIVE (= -silence_left_frames/sr).
    assert partial.source_offset_sec < 0
    assert abs(partial.source_offset_sec - (-silence_left_frames / float(SR))) < 1e-6

    # Loop region spans the full chunk_frames (silence-left + real audio).
    assert abs(partial.loop_start_sec - pad_pre_frames / float(SR)) < 1e-6
    assert abs(partial.loop_end_sec - (pad_pre_frames + chunk_frames) / float(SR)) < 1e-6

    # WAV layout sanity check.
    wav_data, _ = sf.read(str(tmp_path / partial.file), always_2d=True)
    expected_total = pad_pre_frames + chunk_frames + pad_post_frames
    assert wav_data.shape[0] == expected_total

    # Pre-pad region: all silence.
    assert np.allclose(wav_data[0:pad_pre_frames, :], 0.0)
    # Silence-left part of the loop region: also silence.
    silence_left_start = pad_pre_frames
    silence_left_end = pad_pre_frames + silence_left_frames
    assert np.allclose(wav_data[silence_left_start:silence_left_end, :], 0.0)
    # Real-audio part of the loop region: non-silent (baseline=0.5).
    real_start = silence_left_end
    real_end = real_start + leftover_frames
    real_segment = wav_data[real_start:real_end, :]
    assert not np.allclose(real_segment, 0.0)
    # The real audio is the source's [0, leftover_frames) — constant 0.5
    # baseline, so RMS should be ~0.5.
    assert abs(float(np.sqrt(np.mean(real_segment ** 2))) - 0.5) < 0.01
    # Post-pad: also real audio (continues from leftover_frames into source).
    post_pad_start = real_end
    post_pad_end = post_pad_start + pad_post_frames
    post_pad = wav_data[post_pad_start:post_pad_end, :]
    assert not np.allclose(post_pad, 0.0)


def test_emit_partial_renumbers_subsequent_chunks(tmp_path):
    """When emit_partial=True, all post-downbeat chunks shift down by 1
    (timeline_index 0 → chunk_002, etc.)."""
    bars = 4
    leftover_bars = 2
    first_downbeat_sec = (FPB * leftover_bars) / float(SR)
    n_frames = FPB * 12  # leftover (2) + 2 full post-chunks (8 bars)
    stem = tmp_path / "drums.wav"
    _write_marker_stem_offset(stem, n_frames, baseline=0.3)

    metas_no_partial = prechop_stem(
        stem,
        tmp_path / "no_partial",
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=1,
        first_downbeat_sec=first_downbeat_sec,
        write_sidecars=False,
        emit_partial=False,
    )
    metas_with_partial = prechop_stem(
        stem,
        tmp_path / "with_partial",
        "drums",
        bpm=BPM,
        bars=bars,
        pad_bars=1,
        first_downbeat_sec=first_downbeat_sec,
        write_sidecars=False,
        emit_partial=True,
    )

    assert len(metas_with_partial) == len(metas_no_partial) + 1
    # The chunks that USED to be 1..N are now 2..N+1.
    for i, base in enumerate(metas_no_partial):
        bumped = metas_with_partial[i + 1]
        assert bumped.chunk_index == base.chunk_index + 1
        assert abs(bumped.source_offset_sec - base.source_offset_sec) < 1e-9


def test_decide_emit_partial_first_downbeat_zero(tmp_path):
    """No emit when there's no pre-downbeat region to consider."""
    stem = tmp_path / "drums.wav"
    _write_marker_stem_offset(stem, FPB * 4, baseline=0.5)
    decision = _decide_emit_partial(
        {"drums": stem},
        skip_set=set(),
        bpm=BPM,
        bars=4,
        beats_per_bar=4,
        first_downbeat_sec=0.0,
        n_pre_chunks=0,
    )
    assert decision is False


def test_decide_emit_partial_threshold_is_zero():
    """`MIN_LEFTOVER_FRAC=0` (Believer-bar-1-transient feedback 2026-05-04):
    any non-silent leading audio gets a visible chunk_001 instead of being
    hidden in the pad-stash. RMS gate is now the only content filter."""
    assert MIN_LEFTOVER_FRAC == 0.0


def test_decide_emit_partial_tiny_leftover_with_content_emits(tmp_path):
    """Believer-like: 0.16 chunk-period leftover. Pre-2026-05-04, this
    stayed latent in the pad-stash (below 25% threshold). Now it emits a
    visible chunk_001 so the pre-bar-1 transient is reachable in
    arrangement view."""
    stem = tmp_path / "drums.wav"
    _write_marker_stem_offset(stem, FPB * 4, baseline=0.5)
    bars = 4
    chunk_period_sec = (bars * FPB) / float(SR)
    # 16% leftover_frac
    first_downbeat_sec = chunk_period_sec * 0.16
    decision = _decide_emit_partial(
        {"drums": stem},
        skip_set=set(),
        bpm=BPM,
        bars=bars,
        beats_per_bar=4,
        first_downbeat_sec=first_downbeat_sec,
        n_pre_chunks=0,
    )
    assert decision is True


def test_decide_emit_partial_silent_leading_region(tmp_path):
    """Above leftover_frac threshold but the leading region itself is dead
    air → RMS gate fires, no emit. Gives Track-3-style tracks identical
    behavior to today."""
    stem = tmp_path / "drums.wav"
    # 8 bars, all silence — leading region is silence, RMS = 0 < floor.
    _write_silent_stem(stem, FPB * 8)
    bars = 4
    leftover_bars = 2  # 50% leftover_frac (above threshold)
    first_downbeat_sec = (FPB * leftover_bars) / float(SR)
    decision = _decide_emit_partial(
        {"drums": stem},
        skip_set=set(),
        bpm=BPM,
        bars=bars,
        beats_per_bar=4,
        first_downbeat_sec=first_downbeat_sec,
        n_pre_chunks=0,
    )
    assert decision is False
    assert SILENCE_THRESHOLD_DBFS == -60.0  # spec default


def test_decide_emit_partial_above_threshold_with_content_emits(tmp_path):
    """Both gates pass → emit."""
    stem = tmp_path / "drums.wav"
    _write_marker_stem_offset(stem, FPB * 8, baseline=0.5)
    bars = 4
    leftover_bars = 2
    first_downbeat_sec = (FPB * leftover_bars) / float(SR)
    decision = _decide_emit_partial(
        {"drums": stem},
        skip_set=set(),
        bpm=BPM,
        bars=bars,
        beats_per_bar=4,
        first_downbeat_sec=first_downbeat_sec,
        n_pre_chunks=0,
    )
    assert decision is True


def test_decide_emit_partial_any_stem_with_content_triggers_emit(tmp_path):
    """Decision is shared across stems (parallel chunks must align). If ANY
    stem's leading region has content, all stems emit a partial."""
    drums = tmp_path / "drums.wav"
    bass = tmp_path / "bass.wav"
    _write_silent_stem(drums, FPB * 8)             # silent
    _write_marker_stem_offset(bass, FPB * 8, 0.5)  # has content
    bars = 4
    leftover_bars = 2
    first_downbeat_sec = (FPB * leftover_bars) / float(SR)
    decision = _decide_emit_partial(
        {"drums": drums, "bass": bass},
        skip_set=set(),
        bpm=BPM,
        bars=bars,
        beats_per_bar=4,
        first_downbeat_sec=first_downbeat_sec,
        n_pre_chunks=0,
    )
    assert decision is True


def test_top_level_prechop_emit_partial_bumps_musical_bar_1_chunk_index(tmp_path):
    """When the orchestrator decides to emit, `musical_bar_1_chunk_index`
    must bump by 1 to account for chunk_001 being the partial."""
    bars = 4
    leftover_bars = 2
    first_downbeat_sec = (FPB * leftover_bars) / float(SR)
    n_frames = FPB * 12
    drums = tmp_path / "drums.wav"
    bass = tmp_path / "bass.wav"
    _write_marker_stem_offset(drums, n_frames, baseline=0.3)
    _write_marker_stem_offset(bass, n_frames, baseline=0.3)

    out = tmp_path / "out"
    out.mkdir()
    manifest_path = prechop(
        {"drums": drums, "bass": bass},
        out,
        bpm=BPM,
        bars=bars,
        pad_bars=1,
        first_downbeat_sec=first_downbeat_sec,
        write_sidecars=False,
    )
    data = json.loads(manifest_path.read_text())
    # Partial emitted → bar 1 chunk is now at 0-indexed position 1, since
    # chunk[0] is the leading partial.
    assert data["leading_partial_emitted"] is True
    assert data["musical_bar_1_chunk_index"] == 1
    # Both stems must have the same chunk count (emit decision is shared).
    drums_chunks = data["stems"]["drums"]["chunks"]
    bass_chunks = data["stems"]["bass"]["chunks"]
    assert len(drums_chunks) == len(bass_chunks)
    # Both stems' chunk_001 must be the partial (negative source_offset_sec).
    assert drums_chunks[0]["source_offset_sec"] < 0
    assert bass_chunks[0]["source_offset_sec"] < 0


def test_top_level_prechop_emit_partial_explicit_false_disables(tmp_path):
    """Caller can force `emit_partial=False` to skip the new path even when
    the gate would have passed (escape hatch + back-compat for callers
    that don't want the new behavior)."""
    bars = 4
    leftover_bars = 2
    first_downbeat_sec = (FPB * leftover_bars) / float(SR)
    drums = tmp_path / "drums.wav"
    _write_marker_stem_offset(drums, FPB * 8, baseline=0.5)

    out = tmp_path / "out"
    out.mkdir()
    manifest_path = prechop(
        {"drums": drums},
        out,
        bpm=BPM,
        bars=bars,
        pad_bars=1,
        first_downbeat_sec=first_downbeat_sec,
        write_sidecars=False,
        emit_partial=False,
    )
    data = json.loads(manifest_path.read_text())
    assert data["leading_partial_emitted"] is False
    assert data["musical_bar_1_chunk_index"] == 0


def test_skip_residual_by_default(tmp_path):
    n_frames = FPB * 4
    stem = tmp_path / "drums.wav"
    residual = tmp_path / "residual.wav"
    _write_silent_stem(stem, n_frames)
    _write_silent_stem(residual, n_frames)

    out = tmp_path / "out"
    out.mkdir()
    manifest_path = prechop(
        {"drums": stem, "residual": residual},
        out,
        bpm=BPM,
        bars=2,
        pad_bars=1,
        pad_last=True,
        write_sidecars=False,
    )
    data = json.loads(manifest_path.read_text())
    assert "drums" in data["stems"]
    assert "residual" not in data["stems"]
