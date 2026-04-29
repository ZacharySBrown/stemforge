# EP-133 Protocol — Project-Dump Capture Plan

Handoff document for an asynchronous analysis session. The goal: capture a
series of project-file dumps with known on-device state, so an analyst can
validate/extend the protocol decoder without device access.

Companion to [`ep133_protocol_spec.md`](./ep133_protocol_spec.md) — read that
first for context. Everything below is a concrete *what to do* to produce
high-signal data.

---

## 0. Current device state (before capture session)

As of end of 2026-04-24 session, Project 7 has this known state:

| Location | Sample slot | time.mode | Playmode | Per-pad BPM | Encoding observed |
|----------|-------------|-----------|----------|-------------|-------------------|
| P7 C-1 (pad "7") | 100 (vocal) | bpm | oneshot | default | — |
| P7 C-2 (pad "8") | 100 | bpm | oneshot | default | — |
| P7 C-3 (pad "9") | 100 | bpm | oneshot | default | — |
| P7 C-4 (pad "4") | 100 | off | key | default | — |
| P7 C-5 (pad "5") | 100 | bar | key | default | — |
| P7 C-6 (pad "6") | 100 | bpm | key | **70** | **float32** |
| P7 C-7 (pad "1") | 100 | off | legato | default | — |
| P7 C-8 (pad "2") | 100 | bar | legato | default | — |
| P7 C-9 (pad "3") | 100 | bpm | legato | **60** | **float32** (set via knob, unverified) |
| P7 C-10 (pad ".") | 100 | off | oneshot | default | — |
| P7 C-11 (pad "0") | 100 | off | oneshot | default | — |
| P7 C-12 (pad "E") | 100 | off | oneshot | default | — |

Bonus saved pad:
- **P7 C-? (pad "9" = pad_num 3)**: BPM=100, **override** encoding. This is the
  single data point we have for the override encoding. Byte layout: `80 C8 00`
  at offsets +13..+15 of the pad record.

Saved dump files (on the laptop used for the session):
- `/tmp/ep133_project7_content.bin` — Project 7 after first full read (state: pad C-3=92)
- `/tmp/ep133_project7_after150.bin` — after pad C-3 = 150
- `/tmp/ep133_project7_after100.bin` — after pad C-3 = 100
- `/tmp/ep133_project7_3pads_set.bin` — latest: pad-"9"=100, pad-"6"=70, pad-"3"=60
- `/tmp/ep133_project7_after_pad6_70.bin` — after pad-"6" = 70

Firmware version: **TODO — check device → Settings → System Info before capture.**
(All findings so far are against whatever firmware was running 2026-04-24.
Format may have shifted on 2.0.5+.)

---

## 1. Goal of this capture session

Resolve two specific questions and validate the rest of the pad-record
byte map:

1. **Which pad state triggers float32 vs override BPM encoding?** The
   leading hypothesis is "BAR-mode history in current session" — pads that
   have ever been in BAR mode during the current session use float32; pads
   that stayed in BPM mode use override. Only two data points so far.
2. **Does the float32 at +12..+15 hold BPM or BPM/2?** phones24 says BPM;
   we've observed 35.001 for a pad at BPM=70 (matches BPM/2). Could be
   wrong on either side.
3. **Extend the byte-map validation** for fields we currently only have
   from phones24 (volume, pitch, pan, playmode byte, time-stretch mode,
   loop points in pad record) by diffing dumps with known state deltas.

---

## 2. Two capture paths

### 2a. Live SysEx read (fast, what we already have)

```bash
uv run --with python-rtmidi --with mido python -c "
from stemforge.exporters.ep133.project_reader import read_project_file
from pathlib import Path
import datetime

content = read_project_file(project_num=7)
stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
Path(f'/tmp/ep133_p7_{stamp}.bin').write_bytes(content)
print(f'wrote {len(content)} bytes → /tmp/ep133_p7_{stamp}.bin')
"
```

Pros: under 2 seconds per dump, no UI interaction.
Cons: returns just the project TAR — no meta.json / ZIP wrapping.

### 2b. EP Sample Tool → .ppak backup (slower, full container)

Open [teenageengineering.com/apps/ep-sample-tool](https://teenageengineering.com/apps/ep-sample-tool)
→ connect EP-133 → "Backup" (or equivalent) → save the `.ppak` file.

Pros: full container — includes `meta.json`, other project sub-files, device
settings, patterns. Lets the analyst cross-reference phones24 and Danny's
container docs.
Cons: UI clicks, per-dump overhead.

**Do BOTH paths for at least one dump** so the analyst can validate that the
live-read TAR == `/projects/P07.tar` inside the ppak. After that, the live
path alone is fine for bulk captures.

---

## 3. Capture matrix

Each row is one save + dump. Use pad labels (the numbers printed on the pad);
mapping to pad_num is in [`ep133_protocol_spec.md §2`](./ep133_protocol_spec.md).

### BPM encoding (highest priority)

Do these one at a time, saving after each, and taking a dump immediately:

| # | Target pad | Action | Why |
|---|------------|--------|-----|
| 1 | any untouched pad | no changes, just dump | default-state baseline |
| 2 | pad "4" | knobY → 120, `SHIFT+SOUND` 2s save | BPM set via knob, BPM mode only (no BAR history) |
| 3 | pad "5" | currently BAR mode → knobX to BPM → knobY → 120 → save | Test: does BAR→BPM transition force float32? |
| 4 | pad "7" | knobX BPM→BAR→BPM, knobY → 120, save | BAR history then set — should reproduce pad-6 float32 |
| 5 | pad "8" | BPM→BAR→BPM→BAR→BPM, set 120, save | Deeper BAR history, same hypothesis test |
| 6 | pad "." | set BPM=60, save | Low-range value — expect override 0x78 |
| 7 | pad "0" | set BPM=90, save | Low-range value — expect override 0xB4 |
| 8 | pad "E" | set BPM=127, save | **Right at the ×2/×1 boundary** — expect override 0xFE |
| 9 | pad "1" | set BPM=128, save | **Just over the boundary** — expect override 0x80 with +15=0x80 |
| 10 | pad "2" | set BPM=180, save | High-range value — expect 0xB4 with +15=0x80 |

Between each save, **take one dump and record it** (see §5).

### Other pad-record field validation

If time permits, one save per row, each to a distinct previously-default pad:

| # | Action | Why |
|---|--------|-----|
| 11 | set playmode via `SHIFT+SOUND → SND` to each of oneshot/key/legato | decode byte 22 of pad record |
| 12 | set volume to 50 via VOLUME fader/knob | decode byte 15 (phones24 says volume) |
| 13 | set pitch to +7 semitones | decode byte 16 (phones24 says pitch) |
| 14 | set pan to -8 | decode byte 17 (phones24 says pan ÷16) |
| 15 | set loop start=1000, loop end=50000 via TRIM menu | decode loop-point fields (phones24 doesn't map these in the pad record — might be at sample-slot level only) |
| 16 | set envelope.attack=128, release=128 | decode bytes 18, 19 |
| 17 | assign mute group 1 | decode byte 21 `inChokeGroup` |

---

## 4. Manifest format (one per dump)

Save alongside each binary. Markdown is ideal. Template:

```markdown
# Dump: ep133_p7_20260425_143022.bin

- Firmware: 2.0.5 (or whatever `SETTINGS → SYSTEM → VERSION` reads)
- Capture method: live SysEx (project_reader.read_project_file)
- Device reset/power-cycle since start of session? yes/no
- Size: 53248 bytes (if unusual, note)

## What changed from the previous dump

Previous: ep133_p7_20260425_142850.bin (pad-"5" still default)

This dump: pad "5" → BPM=120 via knob+save. Pad-"5" history:
  - Session start: BAR mode (default state per our earlier matrix)
  - Just now: knobX from BAR to BPM, knobY to 120, SHIFT+SOUND 2s save
  - Observation during save: <any screen flicker, error, or oddity>

## Full current device state

(Carry this forward from the prior manifest, updating only what changed.)

| Location | sample | time.mode | playmode | BPM (as displayed) | notes |
|----------|--------|-----------|----------|---------------------|-------|
| P7 C-1 "7" | 100 | bpm | oneshot | default (120?) | never knob-set |
| P7 C-2 "8" | 100 | bpm | oneshot | default | |
| ...
| P7 C-5 "5" | 100 | bpm | key | **120** | **just set via knobY+save** |
| ...
```

**Why the manifest matters:** the analyst can't ask you questions
asynchronously — the "what I set and in what order" trail IS the
experiment. Be specific about history, especially for BAR↔BPM toggles —
our leading hypothesis is that this history is what controls encoding.

---

## 5. Naming conventions

- Binaries: `ep133_p{N}_{YYYYMMDD}_{HHMMSS}.bin` (live) or `.ppak` (tool)
  - Optionally add a distinguishing suffix: `..._post-pad5-bpm120.bin`
- Manifests: same stem, `.md` extension

One-liner for timestamped filename:

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
echo "ep133_p7_${STAMP}"
```

---

## 6. Pre-capture checklist

Before the session:

- [ ] **Firmware version** from `SETTINGS → SYSTEM → VERSION` — record it
- [ ] **Baseline dump first** (no changes) — gives the analyst a starting
      point for diffs
- [ ] **Power cycle before starting** if any speculative probes have been
      run earlier in the day (ERROR 8200 can accumulate quietly)
- [ ] **Save** (`SHIFT+SOUND` 2s) after every on-device change. Knob-only
      changes are RAM-only and get lost on reboot — we need the persisted
      state captured in the project TAR
- [ ] **Update manifest before moving to the next change** — state history
      is the data; don't try to reconstruct it from memory later
- [ ] **Don't ALSO edit via live SysEx during the capture session** — any
      `FILE_METADATA_SET` writes from our code will mix with the knobY
      changes and confuse the BAR-history analysis. Stay on-device only.

---

## 7. What the analyst will do with the dumps

With 3–5 well-varied dumps + manifests, a session has enough signal to:

1. **Diff dumps against each other.** Each save-and-dump gives a clean
   "these bytes changed for this one change" delta. That's the cleanest
   way to verify the pad-record byte map without device access.
2. **Test the BAR-history hypothesis.** Compare dumps 2 (pure BPM-mode
   set) and 4 (BPM→BAR→BPM then set) against each other at the pad
   record. If the encoding differs, hypothesis confirmed. If identical,
   the float32-vs-override difference must come from somewhere else.
3. **Resolve BPM vs BPM/2 debate.** The BPM=120 dumps (items 2, 3, 4, 5)
   all have the same target BPM but potentially different storage. Float32
   interpretation should read as 60.0 (if BPM/2) or 120.0 (if BPM).
4. **Extend the byte map** for volume, pitch, pan, playmode, etc. — all
   items 11-17 contribute here.
5. **Validate Danny's 27-byte record format** against what the device
   actually produces.

What the analyst **can't** do:

- Probe new SysEx commands (no device access)
- Confirm anything write-side (can't test whether a hand-edited .ppak
  re-loads correctly)
- Execute the capture protocol itself (needs hands on the device)

So the handoff loop is: **you capture → analyst analyzes → you run the
next round based on their findings.**

---

## 8. Practical tips

- **Attach files, don't paste hex.** 50KB of hex wastes the context window.
  A file attachment preserves the bytes exactly.
- **One project per session.** Better to fully explore one project than
  shallowly sample four. If you only have time for one good multi-pad
  dump, do the BPM encoding matrix (items 1-10) — highest value.
- **Write manifests as you go.** Every 10 minutes after the fact makes it
  exponentially harder to remember what pad B-7's history was.
- **Include the "weird stuff" notes.** If the screen flickers on a save,
  if knobY feels sticky at certain values, if BPM "jumps" when you turn
  it fast — all signal. Weirdness is where our hypotheses are weakest.
- **Firmware first.** If you've updated since 2026-04-24, flag it
  prominently in the very first manifest — our protocol spec may no
  longer apply.

---

## 9. What to attach to the analysis session

Minimum useful bundle:

1. This spec ([`ep133_protocol_capture_plan.md`](./ep133_protocol_capture_plan.md))
2. The protocol reference ([`ep133_protocol_spec.md`](./ep133_protocol_spec.md))
3. One or more `ep133_p7_*.bin` dumps
4. A manifest per dump
5. The `decode_bpm()` source for reference
   ([`stemforge/exporters/ep133/pad_record.py`](../stemforge/exporters/ep133/pad_record.py))

Optional but valuable:

- One `.ppak` from EP Sample Tool for the same project state
- Link to phones24: `github.com/phones24/ep133-export-to-daw` (`src/lib/parsers.ts`)
- Link to Danny's format notes: `github.com/DannyDesert/EP133-skill`
   (`references/format-details.md`)
