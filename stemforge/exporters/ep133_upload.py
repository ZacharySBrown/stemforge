"""
stemforge.exporters.ep133_upload — Upload samples to EP-133 via MIDI SysEx.

Reverse-engineered protocol from garrettjwilke/ep_133_sysex_thingy.
Sends WAV files to specific sound slots on the EP-133 over USB-MIDI.

Prerequisites:
    pip install mido python-rtmidi
    EP-133 connected via USB-C

Protocol:
    1. Init handshake (device identity request + session init)
    2. File metadata (slot number, filename, channels, size)
    3. Data chunks (~500 bytes each, 7-bit MIDI-safe encoded)
    4. Commit + finalize
"""

from __future__ import annotations

import struct
import time
from pathlib import Path

import numpy as np
import soundfile as sf

# ── Teenage Engineering SysEx constants ──────────────────────────────────

TE_SYSEX_HEADER = bytes([0x00, 0x20, 0x76])  # TE manufacturer ID
TE_DEVICE = bytes([0x33, 0x40])

# Message types
MSG_DEVICE_QUERY = bytes([0x61, 0x17])
MSG_INIT = bytes([0x61, 0x18])
MSG_FILE_META = bytes([0x6C, 0x13])
MSG_DATA_CHUNK = bytes([0x6C])  # followed by chunk sequence number
MSG_COMMIT = bytes([0x6C])
MSG_FINALIZE = bytes([0x6C])

CHUNK_SIZE = 500  # bytes of WAV data per SysEx message (before 7-bit encoding)

EP133_SAMPLE_RATE = 46875


def _encode_7bit(data: bytes) -> bytes:
    """Encode 8-bit data to 7-bit MIDI-safe format.

    MIDI SysEx can only carry values 0-127 (7-bit). For each group of 7 bytes,
    the high bits are stripped and packed into a leading byte.
    """
    result = bytearray()
    for i in range(0, len(data), 7):
        group = data[i:i+7]
        msb_byte = 0
        encoded = bytearray()
        for j, b in enumerate(group):
            if b & 0x80:
                msb_byte |= (1 << j)
            encoded.append(b & 0x7F)
        result.append(msb_byte)
        result.extend(encoded)
    return bytes(result)


def _make_sysex(msg_type: bytes, payload: bytes = b"") -> bytes:
    """Build a SysEx message with TE header."""
    return bytes([0xF0]) + TE_SYSEX_HEADER + TE_DEVICE + msg_type + payload + bytes([0xF7])


def _build_init_messages() -> list[bytes]:
    """Build the initialization handshake messages."""
    # Device identity request (universal SysEx)
    identity_req = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])

    # TE session init
    session_init = _make_sysex(MSG_DEVICE_QUERY, bytes([0x01]))

    # Transfer mode init
    transfer_init = _make_sysex(MSG_INIT, bytes([0x05, 0x00, 0x01, 0x01, 0x00, 0x40, 0x00, 0x00]))

    return [identity_req, session_init, transfer_init]


def _build_file_meta(slot: int, filename: str, wav_size: int, channels: int = 1) -> bytes:
    """Build the file metadata message."""
    # Encode slot number (3 digits, 0-padded)
    slot_bytes = f"{slot:03d}".encode("ascii")

    # Truncate filename to fit
    name = filename[:20].encode("ascii")

    # Channel info as JSON
    chan_json = f'{{"channels":{channels}}}'.encode("ascii")

    # Size encoding (this is approximate — exact format needs more RE)
    size_hi = (wav_size >> 7) & 0x7F
    size_lo = wav_size & 0x7F

    payload = bytearray()
    payload.extend([0x05, 0x40, 0x02, 0x00, 0x05, 0x00, 0x01])
    payload.extend([0x03])  # unknown flag
    payload.extend([0x68, 0x00, 0x00, 0x00])  # unknown
    payload.extend([size_lo, size_hi])  # WAV size
    payload.extend(name)
    payload.append(0x00)
    payload.extend(chan_json)

    return _make_sysex(MSG_FILE_META, bytes(payload))


def _build_data_chunks(wav_data: bytes) -> list[bytes]:
    """Split WAV data into SysEx chunks with 7-bit encoding."""
    chunks = []
    seq = 0x14  # starting sequence number
    offset = 0

    while offset < len(wav_data):
        chunk = wav_data[offset:offset + CHUNK_SIZE]
        encoded = _encode_7bit(chunk)

        # Build chunk header
        header = bytearray()
        header.extend([0x05])
        header.extend([0x60 if offset == 0 else 0x40])  # first chunk flag
        header.extend([0x02, 0x01, 0x00])

        # Offset encoding
        off_lo = offset & 0x7F
        off_hi = (offset >> 7) & 0x7F
        header.extend([off_lo, off_hi])

        msg = _make_sysex(bytes([0x6C, seq & 0x7F]), bytes(header) + encoded)
        chunks.append(msg)

        offset += CHUNK_SIZE
        seq += 1

    return chunks


def _build_commit(seq: int) -> bytes:
    """Build the commit message."""
    payload = bytes([0x05, 0x00, 0x02, 0x01, 0x00, seq & 0x7F])
    return _make_sysex(bytes([0x6C, (seq + 1) & 0x7F]), payload)


def _build_finalize() -> bytes:
    """Build the finalize message."""
    payload = bytes([0x05, 0x00, 0x0B, 0x00, 0x01])
    return _make_sysex(bytes([0x6C, 0x30]), payload)


def _prepare_wav_for_ep133(wav_path: Path) -> bytes:
    """Read and prepare a WAV file for EP-133 upload.

    Resamples to 46875 Hz, converts to 16-bit mono, adds TE metadata header.
    Returns the complete WAV file as bytes.
    """
    import io
    import librosa

    # Load and resample
    audio, sr = sf.read(str(wav_path))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # mono

    if sr != EP133_SAMPLE_RATE:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=EP133_SAMPLE_RATE)

    # Normalize to 16-bit range
    audio = np.clip(audio, -1.0, 1.0)
    audio_16 = (audio * 32767).astype(np.int16)

    # Build WAV with TE metadata header
    buf = io.BytesIO()
    sf.write(buf, audio_16, EP133_SAMPLE_RATE, format='WAV', subtype='PCM_16')
    wav_bytes = buf.getvalue()

    # Inject TE metadata (LIST/INFO/TNGE chunk) into the WAV
    te_metadata = _build_te_metadata()

    # Insert before the data chunk
    # WAV structure: RIFF header (12) + fmt chunk + [smpl chunk] + LIST chunk + data chunk
    # For simplicity, append the LIST chunk at the proper WAV position
    # The EP-133 expects: RIFF...WAVEfmt...smpl...LIST(TNGE metadata)...data...

    return wav_bytes  # TODO: inject TE metadata properly


def _build_te_metadata(
    playmode: str = "oneshot",
    rootnote: int = 60,
    pitch: int = 0,
    pan: int = 0,
    amplitude: int = 100,
    attack: int = 0,
    release: int = 255,
    time_mode: str = "off",
) -> bytes:
    """Build the TE metadata JSON for WAV header injection."""
    metadata = (
        f'{{"sound.playmode":"{playmode}",'
        f'"sound.rootnote":{rootnote},'
        f'"sound.pitch":{pitch},'
        f'"sound.pan":{pan},'
        f'"sound.amplitude":{amplitude},'
        f'"envelope.attack":{attack},'
        f'"envelope.release":{release},'
        f'"time.mode":"{time_mode}"}}'
    )
    return metadata.encode("ascii")


def find_ep133() -> str | None:
    """Find the EP-133 MIDI output port."""
    try:
        import mido
        for name in mido.get_output_names():
            if "EP-133" in name or "EP133" in name:
                return name
    except ImportError:
        pass
    return None


def upload_sample(
    wav_path: Path,
    slot: int,
    playmode: str = "oneshot",
    device_name: str | None = None,
    dry_run: bool = False,
) -> bool:
    """
    Upload a single WAV sample to a specific EP-133 sound slot.

    Args:
        wav_path: Path to WAV file
        slot: Sound slot number (1-999)
        playmode: "oneshot" or "loop"
        device_name: MIDI device name (auto-detect if None)
        dry_run: If True, build messages but don't send

    Returns:
        True if successful
    """
    try:
        import mido
    except ImportError:
        raise RuntimeError(
            "EP-133 upload requires mido + python-rtmidi.\n"
            "  Install: pip install mido python-rtmidi"
        )

    # Prepare WAV
    wav_data = _prepare_wav_for_ep133(wav_path)
    filename = wav_path.stem[:20]

    # Build all SysEx messages
    messages = []
    messages.extend(_build_init_messages())
    messages.append(_build_file_meta(slot, filename, len(wav_data)))
    data_chunks = _build_data_chunks(wav_data)
    messages.extend(data_chunks)
    messages.append(_build_commit(len(data_chunks)))
    messages.append(_build_finalize())

    if dry_run:
        print(f"  DRY RUN: {wav_path.name} → slot {slot:03d} ({len(messages)} SysEx messages, {len(wav_data)} bytes)")
        return True

    # Find device
    if device_name is None:
        device_name = find_ep133()
    if device_name is None:
        raise RuntimeError("EP-133 not found. Connect via USB-C and check MIDI settings.")

    # Send
    print(f"  Uploading {wav_path.name} → slot {slot:03d}...", end=" ", flush=True)
    with mido.open_output(device_name) as port:
        for msg_bytes in messages:
            port.send(mido.Message.from_bytes(msg_bytes))
            time.sleep(0.01)  # small delay between messages

    print("done")
    return True


def upload_export(
    export_dir: Path,
    start_slot: int = 1,
    device_name: str | None = None,
    dry_run: bool = False,
) -> int:
    """
    Upload all WAV files from an EP-133 export directory.

    Args:
        export_dir: Directory with numbered WAV files from stemforge export
        start_slot: Starting sound slot on EP-133
        device_name: MIDI device name
        dry_run: Preview without sending

    Returns:
        Number of samples uploaded
    """
    wav_files = sorted(export_dir.glob("*.wav"))
    if not wav_files:
        print(f"No WAV files in {export_dir}")
        return 0

    print(f"Uploading {len(wav_files)} samples to EP-133 (slots {start_slot}-{start_slot + len(wav_files) - 1})")

    uploaded = 0
    for i, wav in enumerate(wav_files):
        slot = start_slot + i
        try:
            if upload_sample(wav, slot, device_name=device_name, dry_run=dry_run):
                uploaded += 1
        except Exception as e:
            print(f"  ERROR: {wav.name} → slot {slot}: {e}")

    print(f"Uploaded {uploaded}/{len(wav_files)} samples")
    return uploaded
