# EP-133 SysEx Uploader — Port Spec

**Goal:** Port phones24's working TypeScript SysEx library to Python, ship a clean
programmatic uploader. One-shot.
**Target:** `stemforge/exporters/ep133/` (Python package, not a single file).
**Reference:** phones24's library at `/tmp/ep133_daw_ref/src/lib/midi/`.

---

## Guiding principle

**This is a port, not a reimplementation.** Phones24 already solved this. They
de-obfuscated TE's Sample Tool, reverse-engineered the file format, and shipped a
working library that millions of bytes have flowed through. Our job is to
translate TypeScript → Python, not to re-derive the protocol.

Rule of thumb: if a question arises ("what does this flag do?", "what's this
magic number?"), the answer is in phones24's source. Read it there. Don't guess
from Garrett's captured `.syx` files. Captured bytes show *what* works; the
library shows *why*.

The previous session's failure is instructive: they observed that Garrett's
request IDs jumped from 152 to 1555, hardcoded that jump, and called it done.
But the real reason is almost certainly in phones24's code as a plain
`nextRequestId()` function with a cleaner rule than "jump by 1403". Port the
function, not the observation.

---

## Step 0 — Orient

Before writing a line of code, produce a **port map**: a spreadsheet (or just a
markdown table in `stemforge/exporters/ep133/PORT_MAP.md`) that lists every file
in `/tmp/ep133_daw_ref/src/lib/midi/` with:

| TS file | Purpose (one line) | Target Py module | Priority | Notes |
|---------|-------------------|------------------|----------|-------|
| `sysex.ts` | SysEx framing + request IDs | `ep133/sysex.py` | 1 | Core |
| `utils.ts` | `packToBuffer` / `unpackInPlace` | `ep133/packing.py` | 1 | Already verified |
| `commands.ts` | Command byte constants | `ep133/commands.py` | 1 | Enum/constants |
| `transfer.ts` | File upload/download orchestration | `ep133/transfer.py` | 2 | The upload logic |
| `transport.ts` | Web MIDI abstraction | `ep133/transport.py` | 2 | Swap to mido |
| ... | ... | ... | ... | ... |

This takes 30 minutes and saves 10 hours. It also surfaces what can be skipped
(project export, MIDI note extraction — all read-path concerns) vs. what's
critical for our write-path (upload, slot assign, delete).

**We only need the write path.** Phones24's tool is read-focused; we're porting
the subset that writes to the device.

---

## Port priorities (do in this order)

### Tier 1 — Pure logic (no I/O)
These ports are mechanical TS→Python translations. Test with fixtures from
Garrett's captured `.syx` files.

1. **`packing.py`** — 7-bit pack/unpack. Already done in the previous session
   and verified against phones24's `packToBuffer`. Keep this work.
2. **`commands.py`** — Every command byte, sub-command byte, flag bit, and
   magic constant from phones24's source as named Python constants. No magic
   numbers anywhere downstream.
3. **`sysex.py`** — Message framing. Takes `(command, payload, request_id)` →
   SysEx bytes. Port phones24's request ID sequencing verbatim.
4. **`payloads.py`** — Structured payload builders for each message type
   (greet, file_init, file_metadata, file_chunk, commit, finalize, delete,
   assign_pad, switch_project). Each is a pure function: inputs → bytes.

### Tier 2 — I/O boundary

5. **`transport.py`** — Thin wrapper over `mido`. Opens the EP-133 port, sends
   SysEx messages with configurable inter-message delay, receives responses.
   Single class, ~50 lines.
6. **`audio.py`** — WAV → 46875 Hz / 16-bit / mono / raw PCM bytes. Isolated
   from everything else. Already sketched in the previous spec.

### Tier 3 — Orchestration

7. **`transfer.py`** — The actual upload flow. Calls into `payloads.py`,
   `sysex.py`, `transport.py`, `audio.py`. Handles chunking, request ID
   allocation, response acknowledgement (if the device ACKs), retry. Port
   phones24's `uploadSample` or equivalent — they've already solved the control
   flow.
8. **`client.py`** — Top-level public API. One class: `EP133Client`. Methods:
   `upload_sample(path, slot, name=None)`, `delete_sample(slot)`,
   `assign_pad(pad, slot)`, `switch_project(n)`. This is what stemforge imports.

### Tier 4 — Integration

9. **Wire into `EP133Mapping`** — existing class, reuse.
10. **CLI entry point** — `stemforge ep133 upload <wav> --slot N`.
11. **Delete old broken code** — `ep133_upload.py` (wrong encoding),
    `ep133_playwright*.py` (Playwright approach abandoned).

---

## Package structure

```
stemforge/exporters/ep133/
├── __init__.py              # re-exports EP133Client
├── PORT_MAP.md              # the spreadsheet from step 0
├── packing.py               # 7-bit pack/unpack (Tier 1)
├── commands.py              # constants (Tier 1)
├── sysex.py                 # message framing (Tier 1)
├── payloads.py              # payload builders (Tier 1)
├── transport.py             # mido wrapper (Tier 2)
├── audio.py                 # WAV → PCM (Tier 2)
├── transfer.py              # upload orchestration (Tier 3)
├── client.py                # EP133Client (Tier 3)
└── tests/
    ├── fixtures/
    │   ├── garrett_kick.syx         # Garrett's working kick upload
    │   ├── garrett_snare.syx
    │   ├── garrett_delete.syx
    │   └── garrett_assign_pad.syx
    ├── test_packing.py      # round-trip vs. phones24 behavior
    ├── test_payloads.py     # generated bytes match Garrett's fixtures
    ├── test_sysex.py        # frame/unframe round-trip
    └── test_integration.py  # real device tests (marked @slow)
```

Existing code that stays:
- `ep133_mapping.py` — reused as-is
- `ep133.py` — WAV formatting/export helpers, pull the audio prep bits into
  `ep133/audio.py`

---

## Porting rules

### Rule 1: Match phones24's structure, not Garrett's captures

If phones24 has a function called `nextRequestId()`, port that. If it has a
state machine for upload phases, port that. Don't recreate the behavior from
observed bytes — observed bytes are the test fixtures, not the source of truth.

### Rule 2: Test each tier against fixtures before moving up

After porting Tier 1, these tests must pass:

- `pack(unpack(garrett_kick_bytes)) == garrett_kick_bytes` (already passing)
- `build_file_init_payload(...) == extract_payload(garrett_kick.syx, msg=3)`
- `frame_sysex(command=5, payload=P, request_id=1555) == garrett_kick_msg_4`

If building a specific payload produces different bytes than Garrett's fixture,
**the port is wrong**. Don't ship. Go read phones24's code for that payload
type again.

### Rule 3: Preserve phones24's naming

If their function is `packToBuffer`, name yours `pack_to_buffer` (snake_case
translation, same semantic name). If their constants are `BIT_IS_REQUEST`,
keep that spelling. Future debugging will benefit from grep-ability across both
codebases.

### Rule 4: No magic numbers in business logic

Every hex constant, every bit position, every flag value must be a named
constant in `commands.py`. If you write `0x61` anywhere other than that file,
you've skipped a step.

### Rule 5: Port the request ID logic, don't hardcode the 152→1555 jump

The previous session's spec says "match this exact sequence (151, 152, then
1555+) for the first working version." This is the wrong instinct. The jump is
not magic — it's whatever phones24's library does for request ID allocation.
Port that logic. If it happens to produce 151, 152, 1555+ for your first
transfer, great; if it produces 151, 152, 153+ and the device accepts both,
even better. Either way, you will understand what's happening instead of
cargo-culting a byte sequence.

If genuinely stuck on request ID behavior, the investigation order is:
1. Read phones24's `sysex.ts` or equivalent for the request ID function
2. Look for a session/connection state variable that increments differently
   post-greet
3. Check whether the flag bits (`0x61` vs `0x6C`) encode something other than
   "high bits of request ID" — likely yes, e.g. a message class

---

## Test strategy

### Offline tests (Tier 1 + 2)

Use Garrett's captured `.syx` files as golden fixtures. For each captured
upload, we should be able to:

1. Parse the `.syx` file into individual messages
2. Unpack each message's payload (7-bit → raw bytes)
3. Identify the message type from the command byte + sub-command
4. Re-generate the same message using our payload builder
5. Re-frame into SysEx
6. Compare byte-for-byte to the original

A single pytest runs all of this. If Garrett's kick upload → 43 messages → 43
byte-identical regeneration, we're done with offline work.

```python
def test_kick_upload_reproduction():
    original_messages = parse_syx_file('fixtures/garrett_kick.syx')
    pcm = load_pcm_fixture('fixtures/kick_pcm_46875.bin')
    generated = generate_upload_messages(pcm, slot=1, name='KICK_01')
    assert len(generated) == len(original_messages)
    for i, (orig, gen) in enumerate(zip(original_messages, generated)):
        assert gen == orig, f"Message {i} mismatch"
```

### Online tests (Tier 3)

Gated behind a `--device` pytest marker. Not run in CI.

- Upload Garrett's kick PCM to slot 1, verify device shows `1_KICK_01`
- Upload a 10s drum loop, verify it plays when pad is pressed
- Upload to slot 700 (USER 1 bank), verify slot encoding for >127 works
- Delete slot 1, verify it's gone
- Round-trip: upload 8 samples in sequence, no errors

---

## Edge cases flagged for investigation (during porting, not after)

These were called out in the previous spec as "test empirically" or "needs
investigation." Most are answered by reading phones24's source rather than
empirical testing.

- **Slots >127**: phones24's library uploads to any slot. Read how they encode
  the slot byte for slot 700. Almost certainly a 2-byte encoding or an offset
  into a different field. Don't test empirically until you've read the code.
- **Chunk size (433 PCM bytes)**: phones24 almost certainly has this as a
  constant. Pull it from there. The fact that it packs to exactly 500 bytes
  → 510-byte SysEx suggests the chunk size was chosen to hit that boundary,
  which phones24 will have documented or at least made legible.
- **Inter-message delay (20ms)**: phones24's transport layer sets this. Match
  their value, not a guess.
- **File metadata unknowns** (`05 00`, `03`, `0xE8`): phones24 names these.
  They're not actually unknown — the previous session just didn't look.

---

## Non-goals for v1

- Receiving/parsing device responses beyond "did the transfer succeed"
- Reading samples *off* the device (phones24's whole app does this; we just
  need the write side)
- Project export/import
- MIDI note data
- UI of any kind — this is a library + CLI

These can come later by porting more of phones24's library. The structure
above makes that additive, not a rewrite.

---

## Dependencies

Current, no new additions needed:
- `mido`, `python-rtmidi` — MIDI I/O
- `soundfile`, `librosa`, `numpy` — audio prep

Remove:
- `playwright` from optional deps in `pyproject.toml`

---

## Definition of done

1. `stemforge ep133 upload kick.wav --slot 1` produces `1_KICK_01` on the
   device
2. Uploading to slot 700+ works
3. `stemforge ep133 delete --slot 1` works
4. `stemforge ep133 assign-pad --pad A1 --slot 1` works
5. All offline fixture tests pass (byte-identical reproduction of Garrett's
   `.syx` files)
6. `ep133_upload.py`, `ep133_playwright.py`, `ep133_playwright_driver.py` are
   deleted
7. `PORT_MAP.md` exists and is accurate (can be a living document; doesn't need
   to be complete, but every ported module needs its row)

---

## Time estimate

With a clean slate and the phones24 library as the reference:

- Step 0 (port map): 30 min
- Tier 1: 3–4 hours (mostly mechanical translation)
- Tier 2: 1–2 hours
- Tier 3: 2–3 hours (the interesting part — orchestration + real device)
- Tier 4: 1 hour

Total: about one focused day. If it takes longer, the signal is almost always
"I'm guessing at phones24's intent instead of reading their code" — back up and
read.

---

## What went wrong last time, and why this spec is different

Last session's spec treated the protocol as a reverse-engineering problem. It
captured Garrett's bytes, decoded the structure, and asked the agent to rebuild
from observations. That works for the easy parts (packing, basic framing) but
fails on anything stateful — request ID allocation, session setup, error
handling — because state is in the library, not the wire.

This spec treats the protocol as a port. phones24's library is the source of
truth. Garrett's `.syx` files are test fixtures. The difference is:

| Reverse-engineer approach | Port approach |
|---------------------------|---------------|
| "What bytes does the device expect?" | "What does phones24's code do?" |
| Guess from captures | Read the implementation |
| Observations become code | Code becomes observations (via tests) |
| Stuck → experiment | Stuck → read source more carefully |
| Hardcodes like "reqID 1555" appear | Named functions like `next_request_id()` |

Same outcome, half the time, ten times the robustness.
