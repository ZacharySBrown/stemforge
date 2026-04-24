# EP-133 Library Port Map

Source: `phones24/ep133-export-to-daw` at `/tmp/ep133_daw_ref/src/lib/midi/`.

## Important: phones24's library is read-only

It only downloads samples off the device for DAW export. It has **no**
`uploadSample`, `writeFile`, `deleteFile`, `assignPad`, or `switchProject`.
The write-path bytes in this port were reverse-engineered from Garrett's
captured `.syx` files at `tests/ep133/fixtures/kick_*.syx` (30 messages
representing a single kick upload to slot 1).

## Port map

| phones24 TS file    | What it does                         | Target Py module        | Status        |
|---------------------|--------------------------------------|-------------------------|---------------|
| `constants.ts`      | Protocol magic numbers               | `ep133/commands.py`     | **ported**    |
| `utils.ts` (pack)   | `packToBuffer` — 7-bit encode        | `ep133/packing.py`      | **ported**    |
| `utils.ts` (unpack) | `unpackInPlace` — 7-bit decode       | `ep133/packing.py`      | **ported**    |
| `utils.ts` (reqId)  | `getNextRequestId` — random + inc    | `ep133/sysex.py`        | **ported**    |
| `utils.ts` (crc)    | `crc32` (poly 0xEDB88320)            | `ep133/packing.py`      | **ported**    |
| `device.ts`         | `sendTESysEx` framing, identity      | `ep133/sysex.py`        | **ported**    |
| `device.ts`         | `parseTeenageSysex` response parsing | `ep133/sysex.py`        | **ported**    |
| `fsSysex.ts`        | FILE_INIT / FILE_INFO builders       | `ep133/payloads.py`     | **ported**    |
| `fsSysex.ts`        | FILE_GET, FILE_LIST, metadata reads  | —                       | skipped (read) |
| `fs.ts`             | `getFile` etc.                       | —                       | skipped (read) |

## Reverse-engineered from captures (not ported, derived)

| Capture message        | Decoded structure                                          | Target           |
|------------------------|------------------------------------------------------------|------------------|
| `kick_00_init.syx` #1  | Universal identity (`F0 7E 7F 06 01 F7`)                   | `sysex.py`       |
| `kick_00_init.syx` #2  | `cmd=1` GREET                                              | `payloads.py`    |
| `kick_00_init.syx` #3  | `cmd=5` FILE_INIT, flags=0x01 (write), maxLen=4MB          | `payloads.py`    |
| `kick_01.syx`          | `cmd=5 sub=02 00` file-create + metadata                   | `payloads.py`    |
| `kick_02…kick_28.syx`  | `cmd=5 sub=02 01 [page:u16 BE] [≤433 bytes PCM]` data     | `payloads.py`    |
| `kick_29.syx`          | `cmd=5 sub=02 01 [lastPage+1:u16]` empty terminator        | `payloads.py`    |
| `kick_30.syx`          | `cmd=5 sub=0B [nodeId:u16 BE]` FILE_INFO finalize          | `payloads.py`    |

## Known unknowns (empirical constants, flagged in `commands.py`)

Four bytes in the file-create metadata header: `05 00 01 03 E8 00 00` (minus
the size uint32 which we decode). Substituted verbatim from the capture. If
a future firmware rejects them, check phones24 for semantic names first, then
vary empirically.

## Intentionally out of scope for v1

- `delete_sample` — no capture fixture
- `assign_pad` — no capture fixture
- `switch_project` — no capture fixture
- Slots > 127 — capture only exercises slot 1; nodeId encoding may differ

Additive to reach these without rewriting: capture more `.syx` files with
the device in a known state, decode, add payload builders.
