"""Per-group format-profile WAV writer tests.

Locks two contracts:

1. ``preserve_source`` (default) is byte-identical to the
   pre-Decision-16 path. The byte-identity test in
   ``test_song_export_parity`` is the broader gate; this one isolates
   the WAV writer specifically.
2. ``vocal`` profile produces a WAV whose fmt chunk declares the lower
   sample rate (~24 kHz on EP-133, clamped from the abstract 24 kHz
   value).

These tests use synthetic WAV bytes; they don't need a real device
fixture.
"""

from __future__ import annotations

import io
import struct
import wave

import pytest

from stemforge.exporters.ep133.wav_format import (
    EP133_SAMPLE_RATE,
    convert_wav_to_ep133,
)


def _make_input_wav(duration_sec: float = 1.0, sample_rate: int = 44100) -> bytes:
    """Build a tiny mono 16-bit PCM WAV in memory (silence)."""
    n_frames = int(duration_sec * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def _read_fmt_chunk_rate(wav_bytes: bytes) -> int:
    """Return the sample rate declared in the WAV's fmt chunk."""
    # We can't use wave.open directly because the EP-133 WAV has
    # extra chunks the wave module sometimes trips on; parse the
    # fmt chunk manually instead.
    assert wav_bytes[:4] == b"RIFF"
    pos = 12  # skip RIFF header + 'WAVE'
    while pos < len(wav_bytes) - 8:
        cid = wav_bytes[pos : pos + 4]
        size = struct.unpack("<I", wav_bytes[pos + 4 : pos + 8])[0]
        if cid == b"fmt ":
            # fmt chunk: format(2), channels(2), sample_rate(4), ...
            return struct.unpack("<I", wav_bytes[pos + 12 : pos + 16])[0]
        pos += 8 + size + (size & 1)
    raise ValueError("fmt chunk not found")


def test_default_target_sample_rate_is_device_default() -> None:
    inp = _make_input_wav(duration_sec=0.1)
    out, _ = convert_wav_to_ep133(inp)
    assert _read_fmt_chunk_rate(out) == EP133_SAMPLE_RATE


def test_target_sample_rate_none_matches_default() -> None:
    inp = _make_input_wav(duration_sec=0.1)
    out_default, _ = convert_wav_to_ep133(inp)
    out_explicit, _ = convert_wav_to_ep133(inp, target_sample_rate=None)
    assert out_default == out_explicit


def test_vocal_profile_rate_24000_emits_24000_in_fmt() -> None:
    inp = _make_input_wav(duration_sec=0.1)
    out, _ = convert_wav_to_ep133(inp, target_sample_rate=24000)
    assert _read_fmt_chunk_rate(out) == 24000


def test_lower_target_rate_produces_smaller_data_chunk() -> None:
    inp = _make_input_wav(duration_sec=1.0)
    full, full_frames = convert_wav_to_ep133(inp)
    half, half_frames = convert_wav_to_ep133(inp, target_sample_rate=24000)
    # 24 kHz is roughly half of 46875; data should be ~half size.
    # Use loose bounds so resampler interpolation doesn't make this
    # flaky.
    assert half_frames < full_frames
    ratio = half_frames / full_frames
    assert 0.4 < ratio < 0.7, f"expected ~50% reduction, got {ratio:.2f}"


def test_target_rate_above_device_default_clamps() -> None:
    inp = _make_input_wav(duration_sec=0.1)
    out_clamped, _ = convert_wav_to_ep133(inp, target_sample_rate=96000)
    assert _read_fmt_chunk_rate(out_clamped) == EP133_SAMPLE_RATE


def test_aiff_input_decoded_via_soundfile() -> None:
    """Live's Consolidate emits AIFF by default. The writer must decode it."""
    import numpy as np
    import soundfile as sf

    # Synthesize a 0.1s mono AIFF directly in memory.
    rate = 44100
    samples = np.zeros(int(0.1 * rate), dtype=np.int16)
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="AIFF", subtype="PCM_16")
    aiff_bytes = buf.getvalue()
    assert aiff_bytes[:4] == b"FORM", "input should be AIFF magic"

    out, frames = convert_wav_to_ep133(aiff_bytes)
    # Output should be a real EP-133 RIFF/WAVE.
    assert out[:4] == b"RIFF"
    assert _read_fmt_chunk_rate(out) == EP133_SAMPLE_RATE
    assert frames > 0


def test_32bit_float_wav_decoded_via_soundfile() -> None:
    """Live's Bounce default is 32-bit float WAV. Python's stdlib `wave`
    rejects these; the writer must fall back to soundfile."""
    import numpy as np
    import soundfile as sf

    rate = 48000
    samples = np.zeros(int(0.5 * rate), dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="FLOAT")
    float_wav_bytes = buf.getvalue()

    out, frames = convert_wav_to_ep133(float_wav_bytes)
    assert out[:4] == b"RIFF"
    assert _read_fmt_chunk_rate(out) == EP133_SAMPLE_RATE  # downsampled
    assert frames > 0


def test_24bit_wav_decoded_via_soundfile() -> None:
    """24-bit PCM is another wave.Error trigger; soundfile handles it."""
    import numpy as np
    import soundfile as sf

    rate = 44100
    samples = np.zeros(int(0.3 * rate), dtype=np.int32)
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="PCM_24")
    wav24_bytes = buf.getvalue()

    out, frames = convert_wav_to_ep133(wav24_bytes)
    assert out[:4] == b"RIFF"
    assert _read_fmt_chunk_rate(out) == EP133_SAMPLE_RATE
    assert frames > 0


def test_32bit_float_with_intersample_peaks_preserves_amplitude() -> None:
    """libsndfile 1.2.2 quirk: direct dtype=int16 read of float32 WAVs whose
    peaks exceed 1.0 (Live's Bounce default) silently returns near-zero PCM.
    Our reader must clip to [-1, 1] then scale to int16 manually.

    Caught 2026-05-09: ``d1 def [...131431].wav`` (peak=1.026) loaded as
    -90 dBFS silence on the EP-133 — slots p01/p02 played nothing.
    """
    import numpy as np
    import soundfile as sf

    rate = 48000
    # Sine wave that hits the full [-1, 1] range, with a few inter-sample
    # peaks above 1.0 to mimic Live's bounce behavior.
    n = int(0.2 * rate)
    samples = (np.sin(np.linspace(0, 200, n)) * 1.026).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="FLOAT")
    out, _ = convert_wav_to_ep133(buf.getvalue())

    # Output should be loud (peak near 32767), not the libsndfile-bug -90 dBFS.
    import struct as _struct

    data_pos = out.find(b"data") + 8
    data_size = _struct.unpack("<I", out[out.find(b"data") + 4 : out.find(b"data") + 8])[0]
    pcm = np.frombuffer(out[data_pos : data_pos + data_size], dtype="<i2")
    peak = int(np.abs(pcm).max())
    assert peak > 30000, (
        f"expected peak ~32767 (full-scale audio preserved), got {peak} "
        f"({20 * np.log10(peak / 32767) if peak else float('-inf'):+.1f} dBFS) "
        f"— libsndfile int16 conversion regression"
    )


def test_stereo_32bit_float_downmixes_to_mono(tmp_path) -> None:
    """The exact case from the user's deck: stereo 32-bit float 48 kHz."""
    import numpy as np
    import soundfile as sf

    rate = 48000
    samples = np.zeros((int(0.4 * rate), 2), dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="FLOAT")

    out, _ = convert_wav_to_ep133(buf.getvalue(), target_sample_rate=24000)
    # Inspect output: mono, 16-bit, 24 kHz.
    import wave as wave_mod

    with wave_mod.open(io.BytesIO(out), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24000


def test_aiff_input_with_target_rate_downsamples() -> None:
    """End-to-end: AIFF → vocal profile → 24 kHz output."""
    import numpy as np
    import soundfile as sf

    rate = 48000
    samples = np.zeros(int(0.5 * rate), dtype=np.int16)
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="AIFF", subtype="PCM_16")
    aiff_bytes = buf.getvalue()

    out, _ = convert_wav_to_ep133(aiff_bytes, target_sample_rate=24000)
    assert _read_fmt_chunk_rate(out) == 24000


def _read_tnge_json(wav_bytes: bytes) -> dict:
    """Pull the TNGE-chunk JSON dict out of an EP-133 WAV."""
    import json
    import struct

    pos = 12
    while pos < len(wav_bytes) - 8:
        cid = wav_bytes[pos : pos + 4]
        size = struct.unpack("<I", wav_bytes[pos + 4 : pos + 8])[0]
        if cid == b"LIST":
            payload = wav_bytes[pos + 8 : pos + 8 + size]
            tnge_pos = payload.find(b"TNGE")
            if tnge_pos >= 0:
                tnge_size = struct.unpack(
                    "<I", payload[tnge_pos + 4 : tnge_pos + 8]
                )[0]
                blob = payload[tnge_pos + 8 : tnge_pos + 8 + tnge_size]
                return json.loads(blob.split(b"\x00")[0].decode())
            break
        pos += 8 + size + (size & 1)
    raise ValueError("TNGE chunk not found")


def test_default_playmode_is_oneshot_with_release_255() -> None:
    inp = _make_input_wav()
    out, _ = convert_wav_to_ep133(inp)
    meta = _read_tnge_json(out)
    assert meta["sound.playmode"] == "oneshot"
    assert meta["envelope.release"] == 255


def test_key_playmode_pairs_release_15() -> None:
    inp = _make_input_wav()
    out, _ = convert_wav_to_ep133(inp, play_mode="key")
    meta = _read_tnge_json(out)
    assert meta["sound.playmode"] == "key"
    assert meta["envelope.release"] == 15


def test_legato_playmode_pairs_release_15() -> None:
    inp = _make_input_wav()
    out, _ = convert_wav_to_ep133(inp, play_mode="legato")
    meta = _read_tnge_json(out)
    assert meta["sound.playmode"] == "legato"
    assert meta["envelope.release"] == 15


def test_invalid_play_mode_rejected() -> None:
    inp = _make_input_wav()
    with pytest.raises(ValueError, match="play_mode must be one of"):
        convert_wav_to_ep133(inp, play_mode="hold")


def test_key_playmode_with_bpm_carries_both_couplings() -> None:
    inp = _make_input_wav()
    out, _ = convert_wav_to_ep133(inp, sound_bpm=92.0, play_mode="key")
    meta = _read_tnge_json(out)
    assert meta["sound.playmode"] == "key"
    assert meta["envelope.release"] == 15
    assert meta["time.mode"] == "bpm"
    assert meta["sound.bpm"] == 92.0


def test_target_rate_zero_or_negative_rejected() -> None:
    inp = _make_input_wav(duration_sec=0.1)
    with pytest.raises(ValueError, match="must be > 0"):
        convert_wav_to_ep133(inp, target_sample_rate=0)
    with pytest.raises(ValueError, match="must be > 0"):
        convert_wav_to_ep133(inp, target_sample_rate=-1000)
