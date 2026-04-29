# EP-133 SysEx Upload — Plan v2 (phones24 protocol)

**Status:** Ready to build. Transport proven (Garrett's .syx → mido → EP-133 works). Protocol now fully understood via phones24's de-obfuscated library.

---

## Key Discovery

The EP-133 exposes an **internal filesystem via SysEx**. The Sample Tool is just a SysEx file-manager GUI. The protocol is:

```
[F0] [00 20 76] [identity] [40] [flags|reqID_hi] [reqID_lo] [command] [7bit-packed payload] [F7]
```

### Message Structure (from phones24/device.ts)
- Byte 0: `F0` (SysEx start)
- Bytes 1-3: `00 20 76` (TE manufacturer ID)
- Byte 4: identity code (device-specific, usually 0)
- Byte 5: `40` (TE SysEx marker)
- Byte 6: flags (`BIT_IS_REQUEST=64` | `BIT_REQUEST_ID_AVAILABLE=32` | `reqID >> 7`)
- Byte 7: `reqID & 0x7F`
- Byte 8: command byte
- Bytes 9+: 7-bit packed payload (entire payload is packed, not just data portions)
- Last byte: `F7` (SysEx end)

### 7-bit Packing (from phones24/utils.ts `packToBuffer`)
- For every 7 input bytes, produce 8 output bytes
- MSB byte comes FIRST, then 7 stripped data bytes
- MSB byte has bit N set if input byte N had its high bit set
- This matches our `encode_7bit()` implementation

### Request/Response Protocol
- Each request has a 12-bit ID (bytes 6-7)
- Device responds with the same ID
- Garrett's `.syx` files have HARDCODED request IDs — that's why they work (the device doesn't validate the ID, it just echoes it back)

### Filesystem Commands (from phones24/constants.ts)
| Command | Value | Purpose |
|---------|-------|---------|
| `TE_SYSEX_GREET` | 1 | Get device info (sku, serial, firmware) |
| `TE_SYSEX_FILE_INIT` | 1 | Init file transfer |
| `TE_SYSEX_FILE_GET` | 3 | Read file (init=0, data=1) |
| `TE_SYSEX_FILE_LIST` | 4 | List directory contents |
| `TE_SYSEX_FILE` | 5 | File operations |
| `TE_SYSEX_FILE_METADATA` | 7 | Get/set file metadata |
| `TE_SYSEX_FILE_INFO` | 11 | Get file info (size, name, flags) |

### File Info Response Format (from phones24/fsSysex.ts)
```
nodeId:   2 bytes (big-endian)
parentId: 2 bytes (big-endian)  
flags:    1 byte
fileSize: 4 bytes (big-endian)
fileName: null-terminated string
```

### What Garrett's upload does (now understood)
1. Identity request (universal SysEx)
2. TE greet (command 1) — gets device info
3. File transfer init (command 5 with sub-command) — sets up the write
4. File data chunks — the WAV file content, chunked and 7-bit packed
5. Commit + finalize

The "header bytes" in each data chunk (05 60 02 01 00 ...) are part of the 7-bit packed payload, not a separate header. The ENTIRE payload after byte 8 is one continuous 7-bit stream.

---

## Implementation Plan v2

### Approach: Port phones24's protocol, use Garrett's .syx as test vectors

Since Garrett's `.syx` files work with hardcoded request IDs, and we proved mido transport works, the simplest path is:

**Phase 1: Send Garrett's files for arbitrary WAVs (quick win)**
- Take Garrett's init sequence as-is (hardcoded IDs are fine)
- Build data chunks that match his encoding
- Focus on: correct 7-bit packing of the FULL message payload
- Verify by sending a Beware drum loop to an empty slot

**Phase 2: Port phones24's protocol properly (clean implementation)**
- Implement `sendTESysEx()` with dynamic request IDs
- Implement filesystem commands (list, write, delete)
- Handle responses (ACK/NAK)
- This becomes the production `ep133_sysex.py`

### Key Files to Port
| Source (TypeScript) | Target (Python) | Purpose |
|---------------------|-----------------|---------|
| `midi/utils.ts: packToBuffer` | `encode_7bit()` | 7-bit encoding (already have, verified) |
| `midi/utils.ts: unpackInPlace` | `decode_7bit()` | 7-bit decoding |
| `midi/device.ts: sendTESysEx` | `send_te_sysex()` | Message framing with request IDs |
| `midi/device.ts: parseTeenageSysex` | `parse_te_sysex()` | Response parsing |
| `midi/fsSysex.ts` | filesystem commands | File list, info, get, write |
| `midi/constants.ts` | constants | Protocol constants |

### Estimated Effort
- Phase 1 (quick win): 2-3 hours — fix the encoding to match Garrett's bytes exactly
- Phase 2 (proper): 3-4 hours — port phones24's protocol to Python

---

## Dependencies
- `mido` + `python-rtmidi` (already installed, already sees EP-133)
- No new deps needed

## References
- `/tmp/ep133_sysex_ref/` — Garrett's working .syx files
- `/tmp/ep133_daw_ref/src/lib/midi/` — phones24's de-obfuscated protocol library
- `stemforge/exporters/ep133_upload.py` — our existing (broken) SysEx code
