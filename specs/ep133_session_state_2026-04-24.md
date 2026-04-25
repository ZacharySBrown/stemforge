# EP-133 Session State — 2026-04-24

## What We Just Fixed

`sound.playmode` was written as a string (`"key"`) but the device expects an integer:

| String | Wire value |
|--------|-----------|
| `oneshot` | `0` |
| `key` | `1` |
| `legato` | `2` |

**File changed:** `stemforge/exporters/ep133/payloads.py`  
**Commit:** `9cc93ca` — "fix: sound.playmode uses integer wire encoding"

Device was silently ignoring the string and falling back to oneshot. This is why `--playmode key` never worked.

---

## How to Test on the EP-133

### Setup
- EP-133 connected via USB-C
- `uv run python tools/ep133_load_project.py` (or the CLI command)
- Have a stem WAV ready (any short loop)

### Test 1 — Verify `key` (gated) mode actually sticks

```bash
# Upload a stem to slot 1, assign to project 1 / group A / pad 1, with key mode
uv run python - <<'EOF'
import rtmidi
from stemforge.exporters.ep133 import payloads as P
from stemforge.exporters.ep133.sysex import build_sysex, pack_7bit

# Assign pad with key mode
params = P.PadParams(playmode="key")
payload = P.build_assign_pad(project=1, group="A", pad_num=1, slot=1, params=params)
sysex = build_sysex(payload)

out = rtmidi.MidiOut()
ports = out.get_ports()
print(ports)
ep_port = next(i for i, p in enumerate(ports) if "EP-133" in p or "K.O" in p)
out.open_port(ep_port)
out.send_message(list(sysex))
out.close_port()
print("Sent. Expected: pad 1 plays only while held.")
EOF
```

**Expected behavior:** Pad 1 plays audio only while you hold it. Releases immediately on lift.  
**Prior broken behavior:** Pad played oneshot regardless of mode set.

### Test 2 — Verify `oneshot` (default) still works

Same as above but `playmode="oneshot"`. Pad should fire and play to end regardless of hold duration.

### Test 3 — Verify `legato` mode

`playmode="legato"` — monophonic, holds position on retrigger (doesn't restart).

### Verify via EP Sample Tool (ground truth)

After sending the SysEx:
1. Open EP Sample Tool at `teenageengineering.com/apps/ep-sample-tool`
2. Connect EP-133
3. Load the project
4. Watch MIDI Monitor — device responds with `FILE_METADATA_GET` replies
5. Find the JSON for the pad you just wrote
6. Confirm `"sound.playmode":1` (not `"sound.playmode":"key"`)

---

## What's Still Unconfirmed (do these captures next session)

### 1. `time.mode` — may also be integer-encoded

We have `"time.mode":"bpm"` in our code. Given the playmode finding, it may be `0=off, 1=bpm, 2=bar`.

**Capture:** Set a pad to BPM mode on-device (SHIFT+SOUND → TIM → orange knob), load project in EP Sample Tool, read the JSON.

### 2. `sound.mutegroup` — bool vs integer?

We have `true`/`false`. May need to be `0`/`1`. Capture same way.

### 3. BAR mode field name

Is it `"time.mode":"bar"` or `"time.mode":"bars"`? Set a pad to BAR mode, capture.

### 4. BAR count field

Does BAR mode add a `"time.bar":4` or `"time.bars":4` field? Capture above will answer this too.

### 5. Source BPM — lives in WAV, not metadata

`time.bpm` does NOT exist in pad metadata (byte budget confirmed). BPM is stored in the WAV file at upload time, format unknown. To find it: export a WAV from EP Sample Tool with BPM set, run `hexdump -C file.wav | grep -A4 smpl` to inspect RIFF chunks.

### 6. Loop — also in WAV or archive, not metadata

No loop submenu in Sound Edit (submodes are: SND TRI ENV TIM M:I GRP — no loop). Set at upload time. Same WAV inspection will reveal whether `smpl` chunk encodes loop points.

---

## Current State of the Export Pipeline

| Feature | Status |
|---------|--------|
| WAV upload to EP-133 (SysEx) | ✅ Working |
| Pad assignment (slot → group/pad) | ✅ Working, all formulas verified |
| `sound.playmode` write | ✅ Just fixed (integer encoding) |
| `time.mode` write | ⚠️ Implemented, encoding unverified |
| `sound.mutegroup` write | ⚠️ Implemented, encoding unverified |
| Source BPM in WAV | ❌ Unknown — research needed |
| Loop in WAV | ❌ Unknown — research needed |
| `stemforge export ep133` CLI command | ✅ Implemented |
| SETUP.md generation | ✅ Implemented |
| Full `ep133_load_project.py` batch script | ✅ Working |

---

## Relevant Files

```
stemforge/exporters/ep133/
  payloads.py          ← PadParams, _PLAYMODE_WIRE, build_assign_pad
  sysex.py             ← framing, 7-bit pack/unpack
  uploader.py          ← WAV upload sequence
  commands.py          ← constants (file IDs, strides, pad map)
stemforge/exporters/ep133_stem_export.py  ← full pipeline (process WAV + write manifest + SETUP.md)
tools/ep133_load_project.py               ← batch: manifest → upload + assign all stems
tests/ep133/                              ← 89 passing tests
specs/ep133_sysex_upload_plan_v2.md       ← protocol reference
```

## Memory Files to Read

- `memory/project_ep133_protocol_findings.md` — confirmed schema + 5 open research items
- `memory/project_ep133_sysex_upload.md` — upload pipeline state
- `memory/project_ep133_batch_load.md` — batch loader state
