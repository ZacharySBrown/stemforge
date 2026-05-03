"""Tests for `stemforge.prechop` — padded N-bar chopping + loop offsets."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from stemforge.prechop import (
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
