# EP-133 SysEx Protocol — Complete Spec

Everything we know about the Teenage Engineering EP-133 K.O. II SysEx protocol
as of 2026-04-24, assembled from live device probing, EP Sample Tool traffic
captures, and cross-referenced against phones24's open-source archive parser.

Scope: over-USB-MIDI SysEx only. Does not cover the internal .ppak archive
format (phones24 documents that separately).

---

## 1. Wire Framing

Every SysEx message to/from the device follows this layout:

```
F0 00 20 76 33 40 <flags> <req_lo> <cmd> <packed_payload> F7
  ^─────┬─────┘ ^┬ ^─┬─┘  ^─┬─┘  ^─┬─┘  ^──────┬───────┘
        │       │   │        │        │              │
   TE mfg ID    │  flags/req_id_hi    command    7-bit packed data
   (00 20 76)   │  bit6=is_request                (below)
                │  bit5=has_req_id
     identity (0x33 seen)  bit4..0=req_id_hi
```

- `F0` / `F7`: standard MIDI SysEx start/end
- `00 20 76`: Teenage Engineering manufacturer ID
- `33`: identity code (model? device? our device always uses `0x33`)
- `40`: TE constant (always `0x40`)
- Byte 6 `flags`: `BIT_IS_REQUEST=0x40`, `BIT_REQUEST_ID_AVAILABLE=0x20`,
  low 5 bits = high bits of 12-bit request id
- Byte 7: low 7 bits of request id
- Byte 8: top-level command (see §4)
- Bytes 9..−2: **7-bit packed** payload
- Byte −1: `F7`

### 7-bit packing

MIDI SysEx bytes must be ≤ `0x7F`. The device packs 8-bit bytes into 9-byte
groups: 1 flag byte + 7 data bytes. Flag byte bit `N` set ⇒ data byte `N` has
its high bit set (restore before decoding). Residual group of length < 7 at
the end still has its own flag byte.

Implementation: [`stemforge/exporters/ep133/packing.py`](../stemforge/exporters/ep133/packing.py)
— `pack_to_buffer`, `unpack_in_place`, `packed_length`.

---

## 2. FileId Hierarchy

The device exposes a filesystem-like namespace addressed by 16-bit fileIds.
Hierarchy confirmed 2026-04-24:

| fileId (hex) | fileId (dec) | Purpose |
|--------------|--------------|---------|
| `0x03E8` | 1000 | `sounds/` root |
| `<slot>` | 1..999 | individual sample slot (fileId = slot number) |
| `0x07D0` | 2000 | `projects/` root |
| `0x0BB8 + (N-1)×1000` | 3000 + (N-1)×1000 | project N (1..99) |
| `project_fid + 100` | | `groups/` root |
| `project_fid + 200` | | group A cursor |
| `project_fid + 300` | | group B cursor |
| `project_fid + 400` | | group C cursor |
| `project_fid + 500` | | group D cursor |
| `group_cursor + pad_num` | | pad (pad_num 1..12) |

Formula for pad fileId (verified against 8 fixtures):

```
pad_fid = 3200 + (project - 1) × 1000 + group_index × 100 + pad_num
        = group_cursor + pad_num
```

Implementation: [`stemforge/exporters/ep133/commands.py`](../stemforge/exporters/ep133/commands.py)
→ `PAD_BASE`, `PAD_PROJECT_STRIDE`, `PAD_GROUP_STRIDE`, `PAD_LABEL_TO_NUM`;
[`stemforge/exporters/ep133/project_reader.py`](../stemforge/exporters/ep133/project_reader.py)
→ `project_file_id()`.

### Pad-label / pad-num mapping

Physical keypad has labels `7..ENTER`; device's internal pad_num is visual
position top-to-bottom, left-to-right:

```
row 0 (top):    7=1   8=2   9=3
row 1:          4=4   5=5   6=6
row 2:          1=7   2=8   3=9
row 3 (bottom): .=10  0=11  ENTER/E=12
```

---

## 3. Commands

Top-level command byte (frame byte 8). Most known commands use `0x05` (FILE)
with a sub-command in the packed payload.

| Byte 8 | Name | Notes |
|--------|------|-------|
| `0x01` | `GREET` | No payload. Used as first message of a session. |
| `0x05` | `FILE` | All filesystem operations. See §4. |

### FILE sub-commands (after `0x05` command byte)

| Sub-cmd | Arg bytes | Purpose | Safe? |
|---------|-----------|---------|-------|
| `0x01 <flags:u8> <max_resp_len:u32 BE>` | `FILE_INIT` | flags=0 read, flags=1 write | ✅ |
| `0x02 0x00 ...` | `FILE_PUT_META` | create file + metadata | ✅ (for samples) |
| `0x02 0x01 <page:u16 BE> <data>` | `FILE_PUT_DATA` | stream data | ✅ (for samples) |
| `0x03 0x00 <fid:u16 BE> <offset:u32 BE>` | `FILE_READ_OPEN` | Open for raw binary read; offset must be 0 | ⚠️ Only for known-readable fileIds (samples, projects) |
| `0x03 0x01 <page:u16 BE>` | `FILE_READ_DATA` | Stream 327-byte page; short response = EOF | ✅ (if a file is open) |
| `0x04 0x00 0x00 <fid:u16 BE>` | `GROUP_DUMP` | Returns 151-byte list of pads in a group cursor. Only valid on group-cursor fileIds. | ✅ |
| `0x05 0x01 <fid:u16 BE> <pad bytes>` | `PLAY` | Trigger playback of a pad or sample slot | ✅ |
| `0x06 0x02 <fid:u16 BE>` | `FILE_DELETE` | Deletes a file. **Destructive.** | ❌ Don't call casually |
| `0x07 0x01 <fid:u16 BE> <json bytes> 0x00` | `FILE_METADATA_SET` | Partial JSON metadata write | ✅ |
| `0x07 0x02 <fid:u16 BE> 0x00 <page:u8>` | `FILE_METADATA_GET` | JSON metadata read, paginated | ✅ |
| `0x0B <fid:u16 BE>` | `STAT` | Small record with filename + a little metadata. Safe for any fileId — invalid ones return "invalid id". | ✅ (use liberally) |

### Responses

Success: flags byte has `BIT_IS_REQUEST=0` (request flag cleared). First unpacked
byte is status — `0x00` = OK, `0x01` = error (followed by ASCII reason).

Observed error strings:
- `invalid id` — the fileId doesn't exist or isn't valid for this command
- `invalid area` — wrong kind of fileId for this command
- `invalid offset` — `03 00` was called with non-zero offset
- `unknown command` — the sub-command byte isn't recognized
- `not initialized` — operation requires a prior `FILE_INIT`
- `failed to delete` — `06 02` on a non-deletable fileId
- `sample load failed` — some variant of `03 00` that's recognized but incomplete
- `offset not supported for raw` — project-file `03 00` with non-zero offset
- `directory not op...` — (truncated) likely "directory not opened"

---

## 4. Sample-Slot Metadata (JSON schema)

Accessed at fileId = slot number (1..999). The `FILE_METADATA_GET`/`SET`
interface returns/accepts an ASCII JSON blob. Reads are paginated — append
`<page:u8>` at the end of a GET payload (`00 00` = page 0, `00 01` = page 1,
etc.). Short response page = EOF.

17 observed fields (verified from pagination of slot 100):

| Field | Type | Range | Writable? | Honored at playback? |
|-------|------|-------|-----------|----------------------|
| `channels` | u8 | 1 or 2 | no (set at upload) | yes |
| `samplerate` | u32 | e.g. 46875 | no (set at upload) | yes |
| `format` | string | `"s16"` | no | yes |
| `crc` | u32 | computed | no | yes |
| `sound.loopstart` | i32 | -1 = none | ✅ writable | ❓ (not tested) |
| `sound.loopend` | i32 | -1 = none | ✅ writable | ❓ (not tested) |
| `name` | string ≤ 20 | filename | ✅ writable | N/A (display only) |
| `sound.amplitude` | u8 | 0..100 | ✅ | ❓ |
| `sound.playmode` | string | `"oneshot"` / `"key"` / `"legato"` | ✅ (string only!) | Slot default for new pad assignments |
| `sound.pan` | i8 | -16..16 | ✅ | ❓ |
| `sound.pitch` | float | semitones -12..12 | ✅ | ❓ |
| `sound.rootnote` | u8 | 0..127 (MIDI, default 60) | ✅ | affects key/legato pitch track |
| `time.mode` | string | `"off"` / `"bar"` / `"bpm"` | ✅ (string only!) | ✅ (stretch behavior) |
| `sound.bpm` | float | 1..200 | ✅ | Stored, but pad's own BPM (binary) takes precedence |
| `sound.bars` | float | device clamps to power-of-2 | ✅ | Likely pad override supersedes |
| `envelope.attack` | u8 | 0..255 | ✅ | ❓ |
| `envelope.release` | u8 | 0..255 | ✅ | yes (couples with playmode) |

Writes are **partial-merge** — only included fields are modified; others
retain their current value. Implementation:
[`SampleParams`](../stemforge/exporters/ep133/payloads.py) +
[`build_slot_metadata_set`](../stemforge/exporters/ep133/payloads.py).

### Important write-side gotchas

- **Strings only for enums** (`sound.playmode`, `time.mode`). Writing integer
  values ACKs as `status=1` (error). The device EMITS integer values in
  unsolicited broadcasts after UI changes, but that's the response schema —
  writes require the string form.
- **`sound.bpm` range:** 1.0..200.0 accepted; 240 rejected with status=1.
- **`name` max 20 bytes** of ASCII.

---

## 5. Pad JSON Metadata (12-field schema)

Accessed at a pad's fileId. Same `FILE_METADATA_GET` / `SET` interface, but
different schema. 12 fields (verified against every group-C pad after a
project load):

```json
{
  "sym": 100,                       // sample slot this pad plays
  "sound.playmode": "oneshot",      // string, device rejects int
  "sample.start": 0,                // u32 sample index
  "sample.end": 336870,             // u32, omitted if not trimmed
  "envelope.attack": 0,             // u8 0..255
  "envelope.release": 255,          // u8 0..255 — MUST pair with playmode
  "sound.pitch": 0.00,              // float semitones
  "sound.amplitude": 100,           // u8 0..100
  "sound.pan": 0,                   // i8 -16..16
  "sound.mutegroup": false,         // bool
  "time.mode": "off",               // string "off"/"bar"/"bpm"
  "midi.channel": 0                 // u8 0..15
}
```

No per-pad BPM field is exposed here — that lives in the binary record (§7).

### Playmode ↔ envelope.release coupling

Writing `sound.playmode` alone does NOT gate playback unless the matched
`envelope.release` is written in the same message. On-device UI always writes
both atomically:

| playmode | paired envelope.release | effect |
|----------|-------------------------|--------|
| `"oneshot"` | 255 | plays full, long tail |
| `"key"` | 15 | gates hard on release |
| `"legato"` | no paired release | inherits prior release value |

`PadParams` in our code auto-pairs these unless caller sets `release=`
explicitly. See
[`stemforge/exporters/ep133/payloads.py`](../stemforge/exporters/ep133/payloads.py)
`_PLAYMODE_DEFAULT_RELEASE`.

---

## 6. Pad Binary Record (inside project TAR)

The real per-pad state lives in the project file (a TAR archive, see §7).
Each pad occupies one 1024-byte block: 512-byte TAR header + pad record
within the content area. Record is ≤27 bytes per phones24.

Byte offsets **within the pad record** (i.e., relative to `block_offset + 512`).
Some verified by us, some from phones24 research only:

| Offset (0-idx) | Field | Source | Verified? |
|----------------|-------|--------|-----------|
| 0-1 | `soundId` u16 LE (sample slot) | phones24 | ✅ (pad 6 shows `64 00` = slot 100) |
| 2 | `midiChannel` | phones24 | ⬜ |
| 3-5 | `trimLeft` u24 LE | phones24 | ⬜ |
| 7-9 | `trimRight` delta u24 LE | phones24 | ⬜ |
| 12-15 | **BPM** (see below — two encodings) | phones24 + us | ⚠️ contested |
| 15 | `volume` u8 | phones24 | ⬜ |
| 16 | `pitch` i8 (signed, wraps 256) | phones24 | ⬜ |
| 17 | `pan` u8 (÷16, wraps 240) | phones24 | ⬜ |
| 18 | `attack` | phones24 | ⬜ |
| 19 | `release` | phones24 | ⬜ |
| 20 | `timeStretch mode` (0=off, 1=bpm, 2=bars) | phones24 | ⬜ |
| 21 | `inChokeGroup` | phones24 | ⬜ |
| 22 | `playMode` (0=oneshot, 1=key, 2=legato) | phones24 | ⬜ |
| 24 | `timeStretchBars` (via lookup table) | phones24 | ⬜ |
| 25 | `pitchDecimal` | phones24 | ⬜ |

### BPM encodings at offset +12..+15 (our key contribution)

**We observed TWO distinct encodings** at the same byte range depending on
pad history. Detection rule: byte +13 == `0x80` ⇒ override; else ⇒ float32.

**Encoding A — "Override" (3 bytes at +13..+15):**
- `+13 = 0x80` — has-override flag
- `+14 = BPM byte`
- `+15 = precision flag` (`0x00` = ×2 mode, `0x80` = ×1 mode)

Decoder: `BPM = byte if (+15 & 0x80) else byte / 2`

Low-range mode (×2) gives 0.5 BPM precision for BPM < 128.
High-range mode (×1) gives 1 BPM precision for BPM ≥ 128.

Validated across three saves of pad C-9 on-device:
- BPM=92: `80 B8 00` → 184/2 = 92 ✓
- BPM=100: `80 C8 00` → 200/2 = 100 ✓
- BPM=150: `80 96 80` → 150×1 = 150 ✓

**Encoding B — "Float32" (4 bytes at +12..+15):**
- `+12..+15` = IEEE 754 float32 LE of **BPM / 2** (tentative)

Validated against one data point only (pad C-6 at BPM=70, stored as
`00 01 0C 42` LE ≈ 35.001). Default (unset) pads store float32 60.0 here,
implying "default BPM = 120" under this interpretation.

**phones24 says the float32 is BPM directly, not BPM/2.** One of us is wrong
or there's a scaling field we haven't decoded. Our single data point isn't
enough to be confident.

**When does each encoding appear?** Unclear. Pad 9 (we only ever set BPM
via knobY while in BPM mode) got override encoding. Pad 6 (toggled BAR→BPM→
BAR→BPM before save) got float32 encoding. Hypothesis: BAR-mode history
forces the float32 format. Needs more test points.

Decoder: [`stemforge/exporters/ep133/pad_record.py`](../stemforge/exporters/ep133/pad_record.py)
`decode_bpm()`.

---

## 7. Project File Structure

Project N's fileId is `3000 + (N-1) × 1000`. The file itself is a TAR-like
archive containing pad records, patterns, scenes, and project metadata.
Observed size for a populated project: ~53 KB for Project 7 with 12 pads
configured.

### TAR block layout

- Standard 512-byte block alignment
- Each pad: one 512-byte header block + one 512-byte data block (= 1024-byte pair)
- Header contains a filename like `pads/{a|b|c|d}/p{01..12}`, but the name can
  have interspersed null bytes due to the device's internal formatting
- Content begins at `block_offset + 512`

To find pad blocks programmatically, scan for `pNN` (N=01..12) in the first
100 bytes of each 512-byte-aligned block —
[`pad_record.find_pad_records`](../stemforge/exporters/ep133/pad_record.py).

### Project-read procedure

```
1. FILE_INIT(flags=0)                                # enter read mode
2. 03 00 <project_fid:u16 BE> <offset:u32 BE = 0>    # open; offset MUST be 0
3. loop page in 0..∞:
      03 01 <page:u16 BE>
      if response shorter than 327 bytes: EOF, stop
4. strip 3-byte page header (00 00 NN) from each page, concat content
```

Implementation: [`stemforge/exporters/ep133/project_reader.py`](../stemforge/exporters/ep133/project_reader.py)
`read_project_file()`.

### Write path — UNKNOWN

`FILE_INIT(w)` + `03 00 <project_fid>` is accepted (handshake opens), but:
- The data-phase sub-command isn't mapped
- Speculative probing (`03 02`, `02 01` on project fid, etc.) **wedged the
  device twice** during discovery, requiring a power cycle
- No known-safe write mechanism for project files via live SysEx

Current production path for writing: use on-device knobY + save, or (eventually)
port phones24's `.ppak` archive re-import flow.

---

## 8. Behavioral Notes

### Emit ≠ accept (integer vs string enums)

The device EMITS integer values for `sound.playmode` and `time.mode` in
unsolicited broadcasts after on-device UI changes. Writing integers back
via `FILE_METADATA_SET` returns `status=1` (error). **Always write strings.**

| Field | Values accepted on write |
|-------|--------------------------|
| `sound.playmode` | `"oneshot"`, `"key"`, `"legato"` |
| `time.mode` | `"off"`, `"bar"`, `"bpm"` |

The integer enum values used in responses/broadcasts:
- `sound.playmode`: `0`=oneshot, `1`=key, `2`=legato
- `time.mode`: `0`=off, `1`=bpm, `2`=bar (note BPM=1, BAR=2 — confirmed via
  transition capture 2026-04-24)

### Silently-inert fields

Some fields accept writes but don't affect playback:
- `sound.playmode` written alone (without matching `envelope.release`)
- `sound.bpm` at slot level (the binary pad record takes precedence)
- `time.bpm` — not a real field; writes ACK but silently ignored

### Partial writes merge

`FILE_METADATA_SET` writes are partial-merge: unlisted fields keep their
current value. BUT — writing a partial field list to a PAD fileId can cause
the device to **re-sync all pad fields from the pad's sample slot**, clobbering
other overrides you set earlier. Don't assume a partial write leaves
everything else untouched.

### Play/trigger command

`cmd=0x05 sub=0x05 0x01 <fid:u16 BE> 00 00 00 00 00 00 03 E8` triggers
playback of a pad (uses pad's stored params) or a sample slot (uses slot's
defaults). The trailing `00 00 00 00 00 00 03 E8` might be `start:u32` +
`length:u32` but hasn't been varied to confirm.

---

## 9. Safety Rules

Hard-won from the two ERROR 8200 incidents 2026-04-24:

1. **Never `03 00` a fileId without first confirming `0B` stat returns
   non-"invalid id".** Speculative opens accumulate error state that
   eventually requires a power cycle.
2. **Never `FILE_INIT(write)` + `03 00` on unknown fileIds.** Even without
   data writes, the open-without-close leaves state that wedges the device.
3. **`06 02` is FILE_DELETE.** Don't invoke casually.
4. **`0B <fileId>` is always safe.** Use it liberally to enumerate before
   opening anything.
5. **After any error-state incident, power-cycle (not just USB-unplug).**
   The device has internal state that doesn't clear on USB reset.

---

## 10. Implementation Map (our Python library)

| Module | Purpose |
|--------|---------|
| [`ep133/commands.py`](../stemforge/exporters/ep133/commands.py) | Constants: command bytes, sub-command bytes, pad fileId formula, PAD_LABEL_TO_NUM |
| [`ep133/sysex.py`](../stemforge/exporters/ep133/sysex.py) | Frame building/parsing, request id allocator, status codes |
| [`ep133/packing.py`](../stemforge/exporters/ep133/packing.py) | 7-bit pack/unpack |
| [`ep133/transport.py`](../stemforge/exporters/ep133/transport.py) | MIDI port discovery, send/recv |
| [`ep133/client.py`](../stemforge/exporters/ep133/client.py) | High-level: `EP133Client.upload_sample`, `.assign_pad`, session management |
| [`ep133/payloads.py`](../stemforge/exporters/ep133/payloads.py) | `PadParams`, `SampleParams`, `build_*` payload builders |
| [`ep133/audio.py`](../stemforge/exporters/ep133/audio.py) | WAV → 46875 Hz mono PCM |
| [`ep133/transfer.py`](../stemforge/exporters/ep133/transfer.py) | Upload message sequence generator |
| [`ep133/project_reader.py`](../stemforge/exporters/ep133/project_reader.py) | **NEW**: live read of project TAR via SysEx |
| [`ep133/pad_record.py`](../stemforge/exporters/ep133/pad_record.py) | **NEW**: TAR scan + per-pad BPM decoder |
| [`tools/ep133_load_project.py`](../tools/ep133_load_project.py) | CLI: bulk-load a curated manifest into an EP-133 project |

Tests: 108 in `tests/ep133/`, all passing as of commit `b92903d`.

---

## 11. Open Questions / Next Research

1. **Which pad state triggers float32 vs override BPM encoding?** Only two
   data points so far; BAR-mode history is the leading hypothesis.
2. **Does phones24's "float32 = BPM" or our "float32 = BPM/2" interpretation
   match more test points?** Need to capture more pad saves.
3. **What's the data-write sub-command for project files?** Writes would
   unlock programmatic per-pad BPM / loop / playmode control without the
   archive round-trip.
4. **Other pad-record fields** (byte 3 midiChannel, bytes 4-6 trimLeft, etc.)
   beyond what phones24 documents — none independently verified yet.
5. **Patterns and scenes** (sequencer data) — fileId region unknown. The
   project TAR we read stopped at `pads/d/...` + trailing metadata; no
   pattern data observed. May be in separate project sub-files.
6. **Multi-project state** — is there a "current project" pointer we can
   read/write to switch projects programmatically?

---

## 12. Memory Pointers

Key memory files (under `~/.claude/projects/.../memory/`) for session continuity:

- `project_ep133_protocol_findings.md` — 2026-04-24 findings summary
- `project_ep133_binary_pad_record.md` — phones24 research + our observations
- `feedback_ep133_emit_vs_accept.md` — the integer vs string writes story
- `feedback_ep133_coupled_fields.md` — playmode ↔ envelope.release coupling
- `feedback_ep133_probing_safety.md` — safety rules, ERROR 8200 recovery

## 13. Commit Lineage (2026-04-24 session)

```
b92903d  feat(ep133): project-file reader + per-pad BPM decoder
8d1b11f  feat(ep133): SampleParams — partial-write dataclass for sample-slot metadata
99cf42c  feat(ep133): auto-pair envelope.release with playmode
67c0337  fix(ep133): revert integer wire encoding — device accepts strings only
```

108 tests pass. Every finding above is reflected in code or tests — nothing
documented here is conjecture unless explicitly marked so.
