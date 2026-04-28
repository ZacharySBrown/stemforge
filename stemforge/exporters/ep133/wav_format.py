"""EP-133 K.O. II native WAV format + metadata.

The device requires samples in a specific format with two non-standard
metadata chunks; bundling raw user WAVs causes Sample Tool transfers to
hang. Verified against ``factory_default.pak`` (a freshly factory-reset
device backup — every sample in the factory library follows this exact
format):

- **mono, 16-bit, 46875 Hz** PCM
- ``smpl`` chunk (36 bytes) with ``MIDIUnityNote=60`` (other fields zero)
- ``LIST/INFO/TNGE`` chunk (176 bytes) holding a JSON blob with default
  per-sample parameters (playmode, rootnote, amplitude, envelope, etc.)
- chunk order: ``fmt`` → ``smpl`` → ``LIST`` → ``data``

This module owns the conversion + metadata-chunk authoring.
"""

from __future__ import annotations

import audioop  # noqa: TODO migrate before Python 3.13 (removal); scipy.signal.resample_poly is the most likely successor.
import io
import struct
import wave

EP133_SAMPLE_RATE = 46875
EP133_CHANNELS = 1
EP133_SAMPLE_WIDTH = 2  # 16-bit

# Default per-sample metadata JSON. Verified verbatim against every
# factory sample. The 164-byte padding is also factory-verified.
DEFAULT_SOUND_METADATA_JSON = (
    '{"sound.playmode":"oneshot","sound.rootnote":60,"sound.pitch":0,'
    '"sound.pan":0,"sound.amplitude":100,"envelope.attack":0,'
    '"envelope.release":255,"time.mode":"off"}'
)
TNGE_PAYLOAD_SIZE = 164


def convert_wav_to_ep133(wav_bytes: bytes) -> tuple[bytes, int]:
    """Convert a WAV to EP-133 native format with metadata chunks.

    Accepts any standard PCM WAV; returns ``(new_wav_bytes, frame_count)``
    where ``frame_count`` is the post-conversion sample-frame count
    suitable for writing into the pad record's bytes 8..11.

    Raises ``wave.Error`` on unparseable input.
    """
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        data = wf.readframes(wf.getnframes())

    # 1. Sample width → 16-bit
    if width != EP133_SAMPLE_WIDTH:
        data = audioop.lin2lin(data, width, EP133_SAMPLE_WIDTH)

    # 2. Channels → mono
    if channels == 2:
        data = audioop.tomono(data, EP133_SAMPLE_WIDTH, 0.5, 0.5)
    elif channels != 1:
        raise ValueError(
            f"unsupported channel count {channels} (need 1 or 2)"
        )

    # 3. Sample rate → 46875 Hz
    if rate != EP133_SAMPLE_RATE:
        data, _ = audioop.ratecv(
            data,
            EP133_SAMPLE_WIDTH,
            EP133_CHANNELS,
            rate,
            EP133_SAMPLE_RATE,
            None,
        )

    frames = len(data) // (EP133_SAMPLE_WIDTH * EP133_CHANNELS)
    return _build_ep133_wav(data), frames


def _chunk(cid: bytes, payload: bytes) -> bytes:
    """RIFF chunk: 4-byte ID + 4-byte LE size + payload + odd-byte pad."""
    pad = b"\x00" if len(payload) & 1 else b""
    return cid + struct.pack("<I", len(payload)) + payload + pad


def _build_ep133_wav(pcm_data: bytes) -> bytes:
    """Wrap PCM data + EP-133 metadata in a RIFF/WAVE container."""
    # fmt chunk (16 bytes)
    byte_rate = EP133_SAMPLE_RATE * EP133_CHANNELS * EP133_SAMPLE_WIDTH
    block_align = EP133_CHANNELS * EP133_SAMPLE_WIDTH
    fmt_payload = struct.pack(
        "<HHIIHH",
        1,                            # PCM format
        EP133_CHANNELS,
        EP133_SAMPLE_RATE,
        byte_rate,
        block_align,
        EP133_SAMPLE_WIDTH * 8,       # bits per sample
    )

    # smpl chunk (36 bytes): only MIDIUnityNote (=60) is non-zero
    smpl_payload = struct.pack(
        "<9I",
        0,    # Manufacturer
        0,    # Product
        0,    # SamplePeriod (ns)
        60,   # MIDIUnityNote
        0,    # MIDIPitchFraction
        0,    # SMPTEFormat
        0,    # SMPTEOffset
        0,    # NumSampleLoops
        0,    # SamplerDataLen
    )

    # LIST/INFO/TNGE: JSON metadata padded to factory's 164-byte slot
    json_bytes = DEFAULT_SOUND_METADATA_JSON.encode("utf-8")
    if len(json_bytes) > TNGE_PAYLOAD_SIZE:
        raise ValueError(
            f"metadata JSON too large: {len(json_bytes)} > {TNGE_PAYLOAD_SIZE}"
        )
    json_padded = json_bytes + b"\x00" * (TNGE_PAYLOAD_SIZE - len(json_bytes))
    tnge_chunk = b"TNGE" + struct.pack("<I", TNGE_PAYLOAD_SIZE) + json_padded
    list_payload = b"INFO" + tnge_chunk

    # Body = WAVE + chunks (factory order: fmt, smpl, LIST, data)
    body = (
        b"WAVE"
        + _chunk(b"fmt ", fmt_payload)
        + _chunk(b"smpl", smpl_payload)
        + _chunk(b"LIST", list_payload)
        + _chunk(b"data", pcm_data)
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body
