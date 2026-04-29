# EP-133 SysEx Upload — Implementation Plan

**Status:** Ready to build
**Replaces:** Playwright-based approach (blocked on Chrome drag-and-drop security)
**Reference:** [garrettjwilke/ep_133_sysex_thingy](https://github.com/garrettjwilke/ep_133_sysex_thingy) — working SysEx protocol with `.syx` files
**Target:** `stemforge/exporters/ep133_sysex.py` (new file, replaces `ep133_upload.py`)

---

## Why This Will Work

Garrett has **working `.syx` files** that successfully upload samples, delete slots, switch projects, and assign pads. The protocol is fully decoded with hex dumps we can compare against byte-for-byte. We already have `mido` installed and it sees the EP-133:

```python
>>> import mido
>>> print(mido.get_output_names())
['EP-133', 'to Max 1', 'to Max 2']
```

No browser. No Playwright. No drag-and-drop. Just MIDI SysEx over USB.

---

## Protocol Decoded (from Garrett's .syx files)

### SysEx Header
All messages: `F0 00 20 76 33 40` (TE manufacturer ID `00 20 76`, device `33 40`)

### Init Sequence (3 messages)
```
1. F0 7E 7F 06 01 F7                           — Universal SysEx identity request
2. F0 00 20 76 33 40 61 17 01 F7               — TE device query
3. F0 00 20 76 33 40 61 18 05 00 01 01 00 40 00 00 F7  — Transfer mode init
```

### File Metadata (1 message per upload)
```
F0 00 20 76 33 40 6C 13  — header + msg type (6C = transfer, 13 = file meta)
05 40 02 00              — transfer flags
05 00 SS                 — SS = slot number (1-byte, 7-bit encoded)
03 68 00 00 00           — file type flags
LL HH                    — WAV size (7-bit encoded: low 7 bits, high 7 bits)
NN...                    — filename (null-terminated ASCII, max ~16 chars)
00                       — separator
{"channels":1}           — channel count JSON
F7                       — end
```

**Slot encoding (from comparing kick=01, snare=02, hat=03):**
- Slot 1: byte = `01`
- Slot 2: byte = `02`
- Slot 3: byte = `03`
- Simple 1-byte value for slots 1-127; likely 2 bytes for 128+

**Size encoding (from kick: 0x2C 0x08 = 1068 bytes? Need to verify):**
- 7-bit packed: `size_lo = size & 0x7F`, `size_hi = (size >> 7) & 0x7F`
- For larger files: may need 3+ bytes

**Sequence counter:** The second byte after `6C` increments per message:
- Metadata: `6C 13`
- First data chunk: `6C 14`
- Each subsequent chunk: `6C 15`, `6C 16`, ...
- Counter wraps at 0x7F

### Data Chunks (~510 bytes each)
```
F0 00 20 76 33 40 6C NN  — NN = sequence counter (increments from 14)
05 60 02 01 00           — first chunk: 60; subsequent: 40
OO OO                    — offset (7-bit encoded, 2 bytes)
[7-bit encoded data]     — 500 bytes of WAV data, 7-bit packed → ~571 bytes
F7
```

**First chunk flag:** byte 9 = `0x60` for first chunk, `0x40` for subsequent
**Offset encoding:** 2-byte 7-bit: `off_lo = offset & 0x7F`, `off_hi = (offset >> 7) & 0x7F`
**7-bit encoding:** Groups of 7 bytes → 8 bytes (MSB byte + 7 data bytes with high bit stripped)

### Commit (1 message)
```
F0 00 20 76 33 40 6C NN 05 00 02 01 00 CC F7
```
- NN = sequence counter (continues from last data chunk)
- CC = chunk count (number of data chunks sent)

### Finalize (1 message)
```
F0 00 20 76 33 40 6C 30 05 00 0B 00 01 F7
```
Fixed message, always the same.

### Delete Sample
```
F0 00 20 76 33 40 7E 07 05 00 06 00 SS F7
```
- SS = slot number

### Switch Project
```
F0 00 20 76 33 40 7C 2A 05 08 07 01 07 50
{"active":NNNN}
00 F7
```
- NNNN = project number (as string, e.g. "8000" for project 6 — encoding TBD)

### Assign Pad to Slot
```
F0 00 20 76 33 40 77 30 05 00 07 01 14 5B
{"sym":SS}
00 F7
```
- SS = slot number (inside JSON)
- The 5B byte area likely encodes project/group/pad

---

## What We Already Have vs What We Need

### Already have (in `ep133_upload.py`):
- ✅ TE SysEx header constants
- ✅ 7-bit encoding (`_encode_7bit`) — **needs verification against Garrett's data**
- ✅ WAV preparation (resample to 46875, mono, 16-bit)
- ✅ TNGE metadata JSON builder
- ✅ `find_ep133()` device detection via mido
- ⚠️ File metadata builder — **slot/size encoding is wrong**
- ⚠️ Data chunk builder — **offset encoding and flags need fixing**
- ❌ TNGE WAV header injection — **TODO on line 187, never implemented**
- ❌ ACK/NAK handling
- ❌ Delete, project switch, pad assign

### Need to build:
1. **TNGE WAV header injection** — insert the LIST/INFO/TNGE chunk into the WAV before sending
2. **Fix file metadata encoding** — compare our output byte-for-byte against Garrett's `01.syx`
3. **Fix data chunk encoding** — verify 7-bit encoding, offset bytes, first-chunk flag
4. **Fix size encoding** — may need more than 2 bytes for large files
5. **Add inter-message timing** — real SysEx needs ~10-50ms between messages
6. **Add delete/project/pad commands** — straightforward from Garrett's reference
7. **Verification step** — after upload, query device to confirm sample landed

---

## Implementation Steps

### Step 1: Verify 7-bit encoding (30 min)
Compare our `_encode_7bit()` output against Garrett's `02.syx` data chunk. Take the original WAV bytes, encode them, and diff against the known-good SysEx file.

### Step 2: Fix TNGE WAV header injection (1 hour)
The WAV format requirement from Garrett's notes:
```
Standard WAV: RIFF...WAVEfmt...data...
EP-133 WAV:   RIFF...WAVEfmt...smpl...LIST(INFO/TNGE{json})...data...
```
The `smpl` chunk is 36 bytes (all zeros except root note at offset 12).
The `LIST` chunk contains an `INFO` sub-chunk with `TNGE` tag + JSON metadata.
Exact bytes are documented in `notes/notes.hmls`.

### Step 3: Fix file metadata message (1 hour)
Build the metadata message and compare byte-for-byte against Garrett's `01.syx` for kick (slot 1, ~10KB file). Fix slot encoding, size encoding, filename encoding.

### Step 4: Fix data chunk encoding (1 hour)
Verify: first-chunk flag (0x60 vs 0x40), offset encoding, sequence counter, chunk boundary handling. Compare against `02.syx` through `27.syx`.

### Step 5: Wire up mido sending (30 min)
```python
import mido
port = mido.open_output('EP-133')
for msg_bytes in messages:
    port.send(mido.Message.from_bytes(msg_bytes))
    time.sleep(0.02)  # 20ms between messages
```

### Step 6: Test single upload (30 min)
Upload one curated drum loop to slot 700 and verify it appears on the device.

### Step 7: Add delete + pad assign (1 hour)
Implement from Garrett's reference `.syx` files. Simple fixed-format messages.

### Step 8: Integration with mapping system (30 min)
Wire into `EP133Mapping` + `upload_curated_export()` from the Playwright code. The CLI interface stays the same, just the transport changes.

---

## Total Estimated Effort: 5-6 hours

Most of the time is verification (comparing our bytes against Garrett's known-good files). The actual code changes are small — we're mostly fixing the existing `ep133_upload.py`.

## Dependencies
- `mido` (already installed, already sees EP-133)
- `python-rtmidi` (already installed as mido backend)
- No new dependencies needed

## Risk Assessment
- **Low risk:** Garrett's `.syx` files are proven working. We're just reproducing them in Python.
- **Main risk:** Large file size encoding. Garrett's examples are small (~10KB kicks). Our drum loops may be 100KB-1MB. The size encoding might need 3+ bytes for files >16KB. If this breaks, we can test with a tiny sample first.
- **Mitigation:** Start with a short drum hit, verify it works, then scale up to loops.

## What Gets Deleted
- `stemforge/exporters/ep133_playwright.py` — no longer needed
- `stemforge/exporters/ep133_playwright_driver.py` — no longer needed
- Playwright dependency in `pyproject.toml` — can remove

## What Stays
- `stemforge/exporters/ep133_mapping.py` — mapping data classes, reused
- `stemforge/exporters/ep133.py` — WAV formatting, reused
- CLI interface pattern — same subcommands, just different transport
