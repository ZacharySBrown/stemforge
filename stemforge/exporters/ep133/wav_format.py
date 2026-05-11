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
import json
import struct
import wave

EP133_SAMPLE_RATE = 46875
EP133_CHANNELS = 1
EP133_SAMPLE_WIDTH = 2  # 16-bit

# EP-133 couples ``sound.playmode`` with ``envelope.release`` — writing
# one without the other leaves the device in an inconsistent state and
# causes the on-device UI to render the pad with stale settings until
# something else writes both fields atomically. Per the EP-133 Coupled
# Fields memory (2026-04-24), the documented pairings are:
#   - oneshot ↔ release=255
#   - key     ↔ release=15
# Legato isn't documented; treating it as key-like (release=15) is the
# safe default until we capture concrete fixtures.
_PLAYMODE_RELEASE_PAIR: dict[str, int] = {
    "oneshot": 255,
    "key": 15,
    "legato": 15,
}


def _read_via_soundfile(audio_bytes: bytes) -> tuple[int, int, int, bytes]:
    """Decode any soundfile-supported audio → (rate, channels, width, pcm).

    Reads as float32, clips to [-1.0, 1.0], then scales to int16 by
    hand. Forced explicit conversion because libsndfile 1.2.2's direct
    ``dtype="int16"`` read returns near-zero PCM for some 32-bit float
    WAVs whose peak floats are just above 1.0 (Ableton's Bounce-default
    output exhibits this — see slot 740/741 silence regression caught
    2026-05-09 against ``d1 def [...131431].wav``).

    Used by ``convert_wav_to_ep133`` to handle:
      - AIFF (Ableton's Consolidate default).
      - 32-bit float WAVs (Ableton's Bounce default — Python's stdlib
        ``wave`` module rejects these with ``wave.Error``).
      - 24-bit PCM WAVs (also rejected by stdlib ``wave``).
      - Any other soundfile-readable format that isn't a plain 16-bit PCM WAV.

    ``width`` is bytes-per-sample (always 2 here — we force 16-bit).

    Raises ``wave.Error`` if soundfile can't decode (stub fixtures, truly
    corrupt input). Wrapping libsndfile's exception lets the writer's
    existing ``except wave.Error`` fallback continue to handle stubs.
    """
    import io as _io

    import numpy as np  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415

    try:
        audio_f, rate = sf.read(_io.BytesIO(audio_bytes), dtype="float32", always_2d=True)
    except (sf.LibsndfileError, RuntimeError) as e:
        raise wave.Error(f"soundfile decode failed: {e}") from e
    channels = audio_f.shape[1]
    # Clip out-of-range values (32-bit float can exceed [-1, 1]; Live's
    # bounces routinely hit ~1.026 due to inter-sample peaks). Without
    # this, libsndfile's direct int16 conversion silently zeroes them.
    np.clip(audio_f, -1.0, 1.0, out=audio_f)
    audio = (audio_f * 32767.0).astype(np.int16)
    # Channels are interleaved in row-major order, which is what the
    # downstream audioop calls expect.
    pcm = audio.tobytes()
    return int(rate), int(channels), 2, pcm


# Backwards-compat alias used by tests written against the AIFF-only name.
_read_aiff_as_pcm = _read_via_soundfile

# Default per-sample metadata JSON for one-shot mode. Verified verbatim
# against every factory sample. The 164-byte padding is also
# factory-verified for this no-BPM form.
DEFAULT_SOUND_METADATA_JSON = (
    '{"sound.playmode":"oneshot","sound.rootnote":60,"sound.pitch":0,'
    '"sound.pan":0,"sound.amplitude":100,"envelope.attack":0,'
    '"envelope.release":255,"time.mode":"off"}'
)


def _build_default_metadata_json(play_mode: str) -> bytes:
    """Default metadata JSON parameterized on play_mode (no-BPM variant).

    Used when a slot doesn't carry a per-clip BPM (e.g. a one-shot drum
    hit). The play_mode/release pair is set per the device's coupling
    rule.
    """
    if play_mode not in _PLAYMODE_RELEASE_PAIR:
        raise ValueError(
            f"play_mode must be one of {sorted(_PLAYMODE_RELEASE_PAIR)}, got {play_mode!r}"
        )
    release = _PLAYMODE_RELEASE_PAIR[play_mode]
    return (
        f'{{"sound.playmode":"{play_mode}","sound.rootnote":60,"sound.pitch":0,'
        f'"sound.pan":0,"sound.amplitude":100,"envelope.attack":0,'
        f'"envelope.release":{release},"time.mode":"off"}}'
    ).encode("utf-8")


# Factory's per-sample TNGE chunk size. Used as the floor when sizing
# BPM-mode chunks so the WAV layout stays close to factory.
TNGE_PAYLOAD_SIZE = 164


def convert_wav_to_ep133(
    wav_bytes: bytes,
    *,
    sound_bpm: float | None = None,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    target_sample_rate: int | None = None,
    play_mode: str = "oneshot",
) -> tuple[bytes, int]:
    """Convert a WAV to EP-133 native format with metadata chunks.

    Accepts any standard PCM WAV; returns ``(new_wav_bytes, frame_count)``
    where ``frame_count`` is the post-conversion sample-frame count
    suitable for writing into the pad record's bytes 8..11.

    When ``sound_bpm`` is provided, the embedded TNGE JSON sets
    ``time.mode=bpm`` and ``sound.bpm=<value>`` so the device stretches
    playback to project tempo (``playback_speed = project_bpm /
    sound.bpm``). Per ZacharySBrown/ep133-ppak/PROTOCOL.md §5/§7.2 the
    pad-record's float32 BPM at bytes 12..15 overrides this slot value
    when both are set, so the WAV metadata is effectively a fallback;
    we still write it so the slot library is consistent.

    ``start_sec`` / ``end_sec`` slice the WAV in input-time seconds (i.e.
    seconds of the original file at its native sample rate, before any
    conversion). The slice is taken before resample/mono/16-bit so that
    rounding errors stay below one input frame. Use this to upload only
    the bar-aligned region of a longer rendered stem (forge curation
    typically stores 6-bar renders sliced to 1- or 2-bar regions in the
    manifest's ``start_offset_sec`` / ``end_offset_sec`` fields).

    ``target_sample_rate`` (per configurator spec v4 Decision 16) selects
    a non-default output rate to save device memory. ``None`` (default)
    uses ``EP133_SAMPLE_RATE`` — today's behavior, byte-identical to the
    pre-Decision-16 path. Values above ``EP133_SAMPLE_RATE`` are clamped
    down to it (the device can't store higher rates). The output WAV's
    fmt chunk declares the chosen rate so the device plays it back
    correctly. A 24 kHz vocal sample is roughly half the byte count of
    a 46875 Hz one — the lever that lets 24 verses fit in 64 MB.

    Raises ``wave.Error`` on unparseable input.

    AIFF inputs (Ableton Live's "Consolidate" default) are routed through
    ``soundfile`` and re-encoded as 16-bit PCM bytes before the rest of
    the pipeline runs. Detection is by RIFF/AIFF magic at offset 0;
    everything else falls through to ``wave.open`` (preserves byte
    identity for the existing WAV path).
    """
    if wav_bytes[:4] == b"FORM":
        # AIFF (Live's default Consolidate format).
        rate, channels, width, data = _read_via_soundfile(wav_bytes)
        nframes = len(data) // (channels * width)
    else:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                rate = wf.getframerate()
                channels = wf.getnchannels()
                width = wf.getsampwidth()
                nframes = wf.getnframes()
                data = wf.readframes(nframes)
        except wave.Error:
            # Python's stdlib `wave` only handles plain PCM. 32-bit float
            # WAVs (Live's default Bounce format) raise here. Route to
            # soundfile, which decodes the broader family transparently.
            rate, channels, width, data = _read_via_soundfile(wav_bytes)
            nframes = len(data) // (channels * width)

    if start_sec < 0:
        raise ValueError(f"start_sec must be >= 0, got {start_sec}")
    if end_sec is not None and end_sec <= start_sec:
        raise ValueError(f"end_sec ({end_sec}) must be > start_sec ({start_sec})")

    # Resolve output rate: None means "use device default", values above
    # the device default clamp down (the device tops out at 46875 Hz).
    out_rate = EP133_SAMPLE_RATE if target_sample_rate is None else int(target_sample_rate)
    if out_rate <= 0:
        raise ValueError(f"target_sample_rate must be > 0, got {target_sample_rate}")
    if out_rate > EP133_SAMPLE_RATE:
        out_rate = EP133_SAMPLE_RATE

    # Slice before any conversion so the frame indices line up exactly
    # with the input WAV's sample rate.
    if start_sec > 0 or end_sec is not None:
        bytes_per_frame = width * channels
        start_frame = int(round(start_sec * rate))
        end_frame = int(round(end_sec * rate)) if end_sec is not None else nframes
        start_frame = max(0, min(start_frame, nframes))
        end_frame = max(start_frame, min(end_frame, nframes))
        data = data[start_frame * bytes_per_frame : end_frame * bytes_per_frame]

    # 1. Sample width → 16-bit
    if width != EP133_SAMPLE_WIDTH:
        data = audioop.lin2lin(data, width, EP133_SAMPLE_WIDTH)

    # 2. Channels → mono
    if channels == 2:
        data = audioop.tomono(data, EP133_SAMPLE_WIDTH, 0.5, 0.5)
    elif channels != 1:
        raise ValueError(f"unsupported channel count {channels} (need 1 or 2)")

    # 3. Sample rate → out_rate (default 46875 Hz; lower for size savings)
    if rate != out_rate:
        data, _ = audioop.ratecv(
            data,
            EP133_SAMPLE_WIDTH,
            EP133_CHANNELS,
            rate,
            out_rate,
            None,
        )

    frames = len(data) // (EP133_SAMPLE_WIDTH * EP133_CHANNELS)
    return (
        _build_ep133_wav(
            data,
            sound_bpm=sound_bpm,
            sample_rate=out_rate,
            play_mode=play_mode,
        ),
        frames,
    )


def _build_metadata_json(sound_bpm: float | None, play_mode: str = "oneshot") -> bytes:
    """Build the TNGE-chunk JSON, optionally tagged with sound.bpm.

    ``play_mode`` controls both ``sound.playmode`` and the paired
    ``envelope.release`` value (the EP-133 couples these two fields —
    writing one without the other leaves the device in an inconsistent
    state).
    """
    if play_mode not in _PLAYMODE_RELEASE_PAIR:
        raise ValueError(
            f"play_mode must be one of {sorted(_PLAYMODE_RELEASE_PAIR)}, got {play_mode!r}"
        )
    release = _PLAYMODE_RELEASE_PAIR[play_mode]
    if sound_bpm is None:
        # No-BPM form. Default oneshot path stays byte-identical to the
        # pre-key-mode metadata blob; key/legato emit the same shape with
        # the paired release value.
        if play_mode == "oneshot":
            return DEFAULT_SOUND_METADATA_JSON.encode("utf-8")
        return _build_default_metadata_json(play_mode)
    if not (1.0 <= sound_bpm <= 200.0):
        # Device rejects writes outside this range (PROTOCOL.md §5).
        raise ValueError(f"sound_bpm {sound_bpm} must be 1.0..200.0 (device rejects higher)")
    # Match ep133-ppak SampleParams: 2-decimal float, formatted without
    # exponent notation. json.dumps gives the right shape.
    bpm_str = json.dumps(round(float(sound_bpm), 2))
    return (
        f'{{"sound.playmode":"{play_mode}","sound.rootnote":60,"sound.pitch":0,'
        f'"sound.pan":0,"sound.amplitude":100,"envelope.attack":0,'
        f'"envelope.release":{release},"time.mode":"bpm","sound.bpm":{bpm_str}}}'
    ).encode("utf-8")


def _chunk(cid: bytes, payload: bytes) -> bytes:
    """RIFF chunk: 4-byte ID + 4-byte LE size + payload + odd-byte pad."""
    pad = b"\x00" if len(payload) & 1 else b""
    return cid + struct.pack("<I", len(payload)) + payload + pad


def _build_ep133_wav(
    pcm_data: bytes,
    *,
    sound_bpm: float | None = None,
    sample_rate: int = EP133_SAMPLE_RATE,
    play_mode: str = "oneshot",
) -> bytes:
    """Wrap PCM data + EP-133 metadata in a RIFF/WAVE container.

    ``sample_rate`` defaults to ``EP133_SAMPLE_RATE``; non-default values
    are written into the fmt chunk so the device knows to play back at
    the chosen rate. Used by the per-group format-profile path
    (configurator spec v4 Decision 16).

    ``play_mode`` controls the slot's TNGE ``sound.playmode`` field and
    the paired ``envelope.release``. Values: ``"oneshot"``, ``"key"``,
    ``"legato"``.
    """
    # fmt chunk (16 bytes)
    byte_rate = sample_rate * EP133_CHANNELS * EP133_SAMPLE_WIDTH
    block_align = EP133_CHANNELS * EP133_SAMPLE_WIDTH
    fmt_payload = struct.pack(
        "<HHIIHH",
        1,  # PCM format
        EP133_CHANNELS,
        sample_rate,
        byte_rate,
        block_align,
        EP133_SAMPLE_WIDTH * 8,  # bits per sample
    )

    # smpl chunk (36 bytes): only MIDIUnityNote (=60) is non-zero
    smpl_payload = struct.pack(
        "<9I",
        0,  # Manufacturer
        0,  # Product
        0,  # SamplePeriod (ns)
        60,  # MIDIUnityNote
        0,  # MIDIPitchFraction
        0,  # SMPTEFormat
        0,  # SMPTEOffset
        0,  # NumSampleLoops
        0,  # SamplerDataLen
    )

    # LIST/INFO/TNGE: JSON metadata padded to a chunk slot. Factory uses
    # 164 bytes for the no-BPM JSON; BPM-mode JSON is longer, so we round
    # up to the next 4-byte boundary at or above the factory size.
    json_bytes = _build_metadata_json(sound_bpm, play_mode)
    payload_size = max(TNGE_PAYLOAD_SIZE, (len(json_bytes) + 3) & ~3)
    if len(json_bytes) > payload_size:
        raise ValueError(f"metadata JSON too large: {len(json_bytes)} > {payload_size}")
    json_padded = json_bytes + b"\x00" * (payload_size - len(json_bytes))
    tnge_chunk = b"TNGE" + struct.pack("<I", payload_size) + json_padded
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
