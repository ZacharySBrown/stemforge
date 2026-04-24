# EP-133 SysEx Upload — Python Port Spec

**Goal:** Port the proven SysEx protocol to a working Python uploader.
**Target:** `stemforge/exporters/ep133_sysex.py`

---

## What's Proven

1. **mido transport works** — Garrett's `.syx` files sent via mido land on the EP-133 (`1_KICK_01`, `2_SNARE_01` confirmed on device)
2. **7-bit packing matches** — Our `pack()` / `unpack()` round-trips identically to phones24's `packToBuffer` / `unpackInPlace`
3. **Payload encoding is correct** — Byte-for-byte identical to Garrett's files (verified in `/tmp/ep133_send_v2.py --verify`)
4. **The ONLY difference that broke uploads was request IDs** — bytes 6-7 of each message. Garrett's init uses IDs 151-152 (flags=`0x61`), then JUMPS to 1555+ (flags=`0x6C`) for file operations. Our sequential IDs (151, 152, 153...) stayed at flags=`0x61` and the device rejected them.

## Reference Materials

| Path | What |
|------|------|
| `/tmp/ep133_sysex_ref/` | Garrett's repo — working `.syx` files for upload, delete, project switch, pad assign |
| `/tmp/ep133_daw_ref/src/lib/midi/` | phones24's de-obfuscated TE SysEx library (TypeScript) |
| `/tmp/ep133_send_v2.py` | Our almost-working sender (payload correct, request IDs wrong) |
| `/tmp/ep133_unpack.py` | Unpacker that verified Garrett's protocol structure |
| `stemforge/exporters/ep133_upload.py` | Old broken SysEx code (don't use — wrong encoding throughout) |
| `stemforge/exporters/ep133_mapping.py` | Mapping data classes — **keep and reuse** |

---

## SysEx Message Structure

```
[F0] [00 20 76] [identity] [40] [flags|reqID_hi] [reqID_lo] [command] [7bit-packed payload] [F7]
```

| Byte(s) | Value | Notes |
|---------|-------|-------|
| 0 | `F0` | SysEx start |
| 1-3 | `00 20 76` | TE manufacturer ID |
| 4 | `0x33` | Identity code (EP-133 specific) |
| 5 | `0x40` | TE SysEx marker |
| 6 | `0x60 \| (reqID >> 7) & 0x1F` | Flags: BIT_IS_REQUEST(64) + BIT_REQUEST_ID_AVAILABLE(32) + reqID high 5 bits |
| 7 | `reqID & 0x7F` | Request ID low 7 bits |
| 8 | command byte | See command table below |
| 9+ | 7-bit packed payload | ALL data after command is packed |
| last | `F7` | SysEx end |

### Request ID Sequence (CRITICAL)

Garrett's working sequence:
- **Init messages:** reqID 151, 152 → flags byte = `0x61`
- **File operations:** reqID 1555, 1556, 1557... → flags byte = `0x6C`

The jump from 152 to 1555 appears intentional. The device may check the flags byte pattern. **Match this exact sequence for the first working version**, then experiment with other IDs later.

```python
# Init phase
req_ids = [151, 152]  # flags = 0x61
# File phase (metadata + data chunks + commit + finalize)
req_ids += [1555 + i for i in range(num_file_messages)]  # flags = 0x6C
```

---

## 7-bit Packing Algorithm

From phones24's `packToBuffer` (utils.ts line 112-128):

```python
def pack(data: bytes) -> bytes:
    """7-bit pack: for every 7 input bytes, output 8 (MSB byte first)."""
    packed_len = len(data) + (len(data) + 6) // 7
    out = bytearray(packed_len)
    out_idx = 1
    msb_idx = 0

    for i, byte in enumerate(data):
        pos = i % 7
        out[msb_idx] |= (byte >> 7) << pos
        out[out_idx] = byte & 0x7F
        out_idx += 1

        if pos == 6 and i < len(data) - 1:
            msb_idx += 8
            out_idx += 1

    return bytes(out)
```

**Verified:** `pack(unpack(garrett_data)) == garrett_data` for ALL messages ✓

---

## Upload Protocol (decoded from Garrett's kick upload)

### Message 1: Universal Identity Request
```
F0 7E 7F 06 01 F7
```
Raw bytes, no TE framing. reqID=N/A.

### Message 2: TE Greet (command=0x01)
```
Header: F0 00 20 76 33 40 [flags] [reqID_lo] 01
Payload: (empty)
```
reqID=151. Gets device info.

### Message 3: File Init (command=0x05)
```
Header: F0 00 20 76 33 40 [flags] [reqID_lo] 05
Raw payload: 01 01 00 40 00 00 (6 bytes, packed to 7)
```
reqID=152. Sub-command=0x01 (FILE_INIT), sets up transfer.

### Message 4: File Metadata (command=0x05)
```
Raw payload structure (35 bytes for kick):
  [02]           sub-command (file write metadata)
  [00]           flags
  [05 00]        unknown (maybe file type)
  [SLOT]         1 byte: slot number (1-255; >255 needs investigation)
  [03]           flag (FILE type?)
  [E8]           unknown (0xE8 = 232; high bit set → needs packing)
  [00 00]        padding
  [SIZE_HI]      PCM byte count >> 8
  [SIZE_LO]      PCM byte count & 0xFF
  [FILENAME\0]   null-terminated ASCII (format: "SLOT_NAME", e.g. "1_kick_01")
  {"channels":1} channel JSON
```

reqID=1555. Note: SIZE is the **raw PCM byte count** (samples × 2 for 16-bit), big-endian, as raw bytes in the unpacked payload (can be >0x7F since the whole payload gets 7-bit packed).

### Messages 5 to N-2: Data Chunks (command=0x05)

```
Raw payload per chunk:
  [02]           sub-command (file write data)
  [01]           transfer direction
  [00]           padding
  [CHUNK_IDX]    0-indexed chunk counter
  [PCM bytes]    up to 433 bytes of raw PCM audio
```

reqID=1556+. Each chunk carries **433 bytes** of PCM data (which packs to 500 encoded bytes → 510-byte total SysEx message).

### Message N-1: Commit (command=0x05)
```
Raw payload: 02 01 00 [NEXT_CHUNK_IDX]
```
4 bytes. `NEXT_CHUNK_IDX` = total number of data chunks sent.

### Message N: Finalize (command=0x05)
```
Raw payload: 0B 00 01
```
3 bytes. Fixed content.

---

## Audio Preparation

The EP-133 requires:
- **Sample rate:** 46875 Hz
- **Bit depth:** 16-bit signed PCM
- **Channels:** Mono
- **What gets sent:** Raw PCM bytes (NOT a WAV file — no RIFF header, no TNGE metadata in SysEx)

```python
import librosa, numpy as np, soundfile as sf

audio, sr = sf.read(wav_path, dtype='float32')
if audio.ndim > 1:
    audio = audio.mean(axis=1)  # mono
audio = librosa.resample(audio, orig_sr=sr, target_sr=46875)
audio = np.clip(audio, -1.0, 1.0)
pcm = (audio * 32767).astype(np.int16).tobytes()
```

---

## Other Commands (from Garrett's .syx files)

### Delete Sample
```
F0 00 20 76 33 40 [flags] [reqID_lo]
Command byte in Garrett's: 7E 07
Raw payload: 05 00 06 00 [SLOT]
```
(Note: this uses a different command byte structure — may be a different TE command, not command 5)

### Switch Project
```
Raw contains: {"active":NNNN}
```

### Assign Pad to Slot
```
Raw contains: {"sym":SLOT_NUM}
```

These are lower priority — get uploads working first.

---

## Slot Number Encoding

Garrett's examples only go to slot 4. For slots >127 (like USER 1 slots 700-799), the slot byte in the unpacked metadata payload can be any value since it's inside the 7-bit packed stream. The value `0xFF` would pack fine. For slots >255, need to check if it's 1 or 2 bytes — test empirically by uploading to slot 256+ and seeing what happens.

**Recommendation:** Start with slots 1-99 (KICK range) for testing. Move to USER 1 (700+) once basic uploads work.

---

## Implementation Checklist

1. [ ] Port `pack()` from phones24 (already done and verified in `/tmp/ep133_send_v2.py`)
2. [ ] Build message framer with correct request ID sequence (151, 152, then 1555+)
3. [ ] Build file metadata message (sub-command 0x02)
4. [ ] Build data chunk messages (sub-command 0x02, 433 PCM bytes per chunk)
5. [ ] Build commit + finalize messages
6. [ ] Send via mido with 20ms inter-message delay
7. [ ] Test: send Garrett's kick PCM to slot 1 → verify `1_kick_01` appears
8. [ ] Test: send a Beware drum loop to slot 1 → verify it plays
9. [ ] Test: send to slot 700 (USER 1) → verify slot encoding for >127
10. [ ] Wire into `EP133Mapping` and CLI
11. [ ] Add delete command
12. [ ] Add pad assign command

## Dependencies

- `mido` (installed, sees EP-133)
- `python-rtmidi` (installed, mido backend)
- `librosa`, `soundfile`, `numpy` (installed, for audio prep)
- No new deps

## What to Delete

- `stemforge/exporters/ep133_playwright.py` — no longer needed
- `stemforge/exporters/ep133_playwright_driver.py` — no longer needed
- `playwright` from pyproject.toml optional deps
- Keep `ep133_mapping.py` (reuse for slot/pad mapping)
- Keep `ep133.py` (reuse for WAV formatting/export)
