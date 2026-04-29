# EP-133 Song-Mode Export — Fresh-Eyes Summary (2026-04-27)

We're trying to get an EP-133 K.O. II `.ppak` exporter to produce song-mode files
that the device can play across multiple scenes. Loading works. Manual pad
triggering works. **Scene-to-scene switching throws `ERR PATTERN 189` on the
device screen.** That's the gating bug.

This doc is meant to brief a new agent (or a human reviewer) cold. Everything
below has been verified empirically against on-device captures unless flagged
otherwise.

---

## 1. Goal & pipeline

Build a `.ppak` (Teenage Engineering's project file format for the EP-133 K.O. II)
from an Ableton Live arrangement, so the device plays the arrangement's sections
as a sequence of scenes (and optionally chains them in song mode).

```
Live arrangement (with locator markers)
     │
     ▼ M4L "EXPORT" button (snapshot reader)
snapshot.json + manifest.json
     │
     ▼ resolve_scenes() — locator → scene mapping
scene snapshots
     │
     ▼ synthesize() — pads/patterns/scenes/sounds spec
PpakSpec
     │
     ▼ build_ppak() — byte writer
.ppak (ZIP)
     │
     ▼ user drag-drops to device via Sample Tool (Chrome WebMIDI)
EP-133 plays scenes
```

Branch: `feat/ep133-song-export` in `/tmp/sf-song-export` (worktree of
`/Users/zak/zacharysbrown/stemforge`).

Tests: 234/234 EP-133 tests passing.

---

## 2. `.ppak` file format (decoded)

ZIP entries (top-level, slash-prefixed):

```
/meta.json                                   ~300-byte JSON
/projects/P{NN}.tar                          POSIX TAR (uncompressed)
/sounds/{slot:03d} {slot:03d}_{stem}.wav     literal SPACE between slot and name
```

Inner project TAR contents:

```
pads/{a|b|c|d}/p{NN}      — 27-byte fixed records (NN = 01..12, 1-indexed)
                             (4 groups × 12 pads = 48 mandatory entries)
patterns/{group}{NN}      — variable length (NN = 01..99, NO slash before NN)
scenes                    — fixed 712 bytes
settings                  — fixed 222 bytes (DANGEROUS — see §6)
```

### 2.1 Pad record (27 bytes)

Authoritative byte map from `ZacharySBrown/ep133-ppak/PROTOCOL.md §7`,
diff-verified against device backups:

| Bytes | Field | Default | Notes |
|------|------|------|------|
| 0 | (zero) | `0x00` | |
| 1-2 | `sample_slot` (uint16 LE) | 0 | sample-library slot |
| 3-7 | (zero/padding) | zeros | |
| 8-11 | `length_frames` (uint32 LE) | 0 | **WAV frame count, REQUIRED for transitions** |
| 12-15 | `time_stretch_bpm` (float32 LE) | `00 00 f0 42` = **120.0** | default even for one-shot pads |
| 16 | `amplitude` | `0x64` = 100 | |
| 17-19 | (zero/padding) | zeros | |
| 20 | `envelope.release` | `0xff` | |
| 21 | `time.mode` | `0x00` = NONE | (1 = BPM, 2 = BARS) |
| 22-23 | (byte 23 = playmode) | `0x00` = oneshot | |
| 24 | `root_note` | `0x3c` = 60 | |
| 25-26 | (zero/padding) | zeros | byte 25 = bars encoding when BARS mode |

A blank-default 27-byte pad on a fresh device project:

```
00 00 00 00 00 00 00 00  00 00 00 00 00 00 f0 42  64 00 00 00 ff 00 00 00 3c 00 00
```

### 2.2 Pattern file (variable length)

```
header: 00 [bars uint8] [event_count uint8] 00     (4 bytes)
event:  [pos_lo, pos_hi, (pad-1)*8, note, velocity, dur_lo, dur_hi, flag]   (8 bytes each)
        - position_ticks, duration_ticks: uint16 LE (96 ticks/beat, 384 ticks/bar)
        - pad encoding: (pad_index_1_based - 1) * 8  — so pad 1→0, pad 2→8, pad 5→32 (0x20)
        - note: usually 0x3c (60); velocity: usually 0x64 (100)
        - flag: 0x00, 0x08, 0x10 observed in references — purpose unknown
```

### 2.3 Scenes file (fixed 712 bytes)

```
bytes 0-6     : header (4 zero + numerator + denominator + 0)
bytes 7-600   : 99 × 6-byte scene chunks [pat_a, pat_b, pat_c, pat_d, num, denom]
                  pat_X = pattern index 1..99, or 0 = silent in that group
bytes 601-711 : 111-byte trailer
                  trailer[0..3]:  scene_count (uint32 BE; effectively single byte at trailer[3] since count < 256)
                  trailer[11]:    song length (count of song-position bytes, 0..99)
                  trailer[12..]:  song-position bytes — one per position, value = scene index (1..99)
                  rest: zero
```

### 2.4 Settings file (fixed 222 bytes — DO NOT POPULATE)

Reference content (from real device backup):
- bytes 0-23: zeros, with project BPM as float32 LE at bytes 4-7
- bytes 24-215: 48 × float32 LE = -1.0 (`00 00 80 bf` repeated)
- bytes 216-219: zero
- bytes 220-221: `00 02` trailer

**`ZacharySBrown/ep133-ppak/PROTOCOL.md §8` warns this file should NOT be in
the TAR at all** — populating it has caused `ERROR CLOCK 43` and `ERROR 8200`
incidents that wedge the device. Re-confirmed by us on 2026-04-27 (see §6).
Currently we ship 222 zero bytes, which the device tolerates.

---

## 3. Reference captures we have

In `docs/ep133-song-triage/` (in the worktree):

| File | Project | Pads | Scenes | Song mode? |
|------|---------|------|--------|-----------|
| `reference_minimal.ppak` | P01 | 4 drums @ slots 700-703 | 3 simple recorded | no |
| `song-mode-captures/00_baseline_no_song.ppak` | same | same | same | no |
| `song-mode-captures/01_song_5_positions_all_scene1.ppak` | same | same | same | yes — 5 positions all → scene 1 |

The captures #00 vs #01 diff was the key to decoding the song-position trailer:
**5 bytes change in scenes trailer + 1 new empty 4-byte pattern file
(`patterns/d05`)**.

---

## 4. Repo layout

```
/Users/zak/zacharysbrown/stemforge      — main checkout (parallel branches active; do not switch)
/tmp/sf-song-export                     — git worktree on feat/ep133-song-export (active surface)
/Users/zak/stemforge                    — data working dir (inbox/, processed/, exports/, etc.)
```

Key files in `/tmp/sf-song-export`:

```
stemforge/exporters/ep133/song_format.py        — byte builders (build_pad, build_pattern, build_scenes, build_settings)
stemforge/exporters/ep133/ppak_writer.py        — assembles ZIP + TAR + sounds; build_synthetic_template_ppak
stemforge/exporters/ep133/song_synthesizer.py   — snapshot + manifest → PpakSpec
stemforge/cli.py                                — `export-song` CLI
tests/ep133/                                    — 234 tests, all passing
docs/ep133-song-triage/                         — triage docs + reference captures
```

---

## 5. The current failure mode

User loads our generated `~/Desktop/smack_song.ppak` onto the device via
Sample Tool. It imports clean ("restore complete", no errors). Pads light up.
Manual pad-tap triggers play correct samples.

Device opens on **scene 5** (the project's last committed scene). The user
presses `-` to go to scene 4. **Device shows `ERR PATTERN 189`.**

Scene chunks ours emits (decoded from our scenes file):

```
scene 1: pat_a=1 pat_b=0 pat_c=0 pat_d=0
scene 2: pat_a=2 pat_b=1 pat_c=0 pat_d=0
scene 3: pat_a=3 pat_b=2 pat_c=0 pat_d=0
scene 4: pat_a=4 pat_b=3 pat_c=1 pat_d=0    ← target of failing transition
scene 5: pat_a=4 pat_b=3 pat_c=1 pat_d=1    ← current scene at error
```

The 5→4 transition only changes group D from pattern d01 → silent (0). All other
groups continue with the same patterns.

We don't know what "189" refers to (offset, pattern index, error code). Searching
upstream RE projects found no hits. The initial trial of `ERR PATTERN 189` came
from a different cause (BARS-mode pad with `length=0`), now fixed.

---

## 6. What we've changed today (2026-04-27) and outcomes

**Starting state** (2026-04-26 EOD): pads loaded, scenes loaded, scene-switching
threw 189. Latest hypotheses were "drop BARS time-stretch" (one-shot mode) and
"add song-position trailer". Both landed in the writer. Tests passed. Awaiting
device test.

### Fix #1 — pad-record device defaults ✓ kept

**Problem found:** synthetic template was 48 zero-filled pad records. `build_pad`
patched slot/play_mode/stretch on top, leaving bytes 14-15 (BPM), 16 (amp), 20
(envrel), 24 (note) as zeros. Reference pads always carry the device defaults.

**Fix:** added `DEVICE_DEFAULT_PAD` constant in `song_format.py`. Updated
`build_synthetic_template_ppak` to write defaults (BPM=120, amp=100,
envrel=0xff, note=60). Updated `_build_inner_tar` unpopulated-pad branch
likewise. Stopped zeroing bytes 12-15 in `stretch_mode="none"` so template's
120.0 propagates.

**Result:** ✓ tests pass, ✓ device imports, ✗ 189 still fires on scene switch.

### Fix #2 — sample length frames at bytes 8-11 ✓ kept

**Problem found:** PROTOCOL.md §7 explicit: bytes 8-11 = sample length in WAV
frames as uint32 LE, **REQUIRED**, "the binding is broken without this." We
were writing zeros.

**Fix:** added `sample_length_frames` kwarg to `build_pad`. Updated
`_build_inner_tar` to compute frame count via `wave.getnframes()` for each
populated pad's WAV and pass through. Tolerant to invalid stub WAVs (used in
test fixtures).

**Result:** ✓ tests pass, ✓ device imports (manual pad triggering still works),
✗ 189 still fires on scene switch.

### Fix #3 — populate settings file with device defaults ✗ REVERTED

**Problem assumed:** our 222-byte zero settings file had 100 bytes of diff vs
reference (mostly the 48 × -1.0 float32 defaults). Hypothesized device validates
these on transitions.

**Fix attempted:** added `DEVICE_DEFAULT_SETTINGS` constant matching reference
byte-for-byte. Wired into `build_synthetic_template_ppak`.

**Result:** ✗ on-device upload threw `ERR 82` followed by a long hex string —
matches the wedge-class error documented in PROTOCOL.md §8 and the EOD handoff
(both warn against populating the settings file). **Reverted to zero-filled.**

This was a known-bad direction we'd been warned about. We should not have tried
it.

---

## 7. Current state of the writer

After fixes #1 + #2 (both kept) + #3 (reverted), the rebuilt `.ppak` matches the
reference song-mode capture on every byte EXCEPT:

```
TAR entries:
  - patterns/d05         (4-byte empty pattern, present in ref, missing in ours)
  - patterns content     (ours: 12-byte single-event; ref: 20-68 byte multi-event)
  - settings (zeros)     (ref has 100 non-zero bytes — we WILL NOT match these,
                            populating is the wedge bug)

Pad records (48):
  - byte 1-2  : sample slot      — naturally different (we use 700+, ref uses 188-191)
  - byte 8-9  : length_frames    — naturally different (we use 466944, ref different)
  - byte 14-15: BPM in 4 ref pads — ref's 4 populated pads have non-default BPMs

Scenes file:
  - 21 byte diff in scene-chunks region — naturally different (different scene → pattern mappings)
  - trailer: matches structurally (scene_count, song_positions)

Settings:
  - 3 bytes diff at offsets 4-6 — project BPM (90.67 vs 120.0)
```

i.e. the only structural / unexpected differences left are:
- patterns/d05 absent
- pattern content (single-event vs multi-event)
- settings is all zeros (cannot be populated safely)

---

## 8. Open hypotheses for ERR PATTERN 189

In rough priority order:

### H1. `patterns/d05` is required for song mode

The byte-diff between song-mode capture and no-song baseline showed both:
- 5 byte changes in scenes trailer (decoded as song-position list)
- 1 new file: `patterns/d05` (4 bytes, `00 02 00 00` — bars=2, event_count=0)

We took the trailer change but assumed `d05` was an incidental side-effect of
the user opening the song-position editor on the device. **Untested assumption.**
Could it actually be a sentinel/terminator the device requires?

Counterargument: scene chunks reference patterns 1, 2, 3 in the reference;
nothing references d05. So if d05 is a sentinel, it's a side-table the device
checks, not a scene-driven reference.

### H2. Single-event 12-byte patterns fail validation during transitions

Our patterns:
```
00 02 01 00 [pos=0] [pad=N*8] [note=60] [vel=100] [dur=96] [flag=0]   = 12 bytes
```

Reference patterns: 4-byte header + 2-7 events, 20-68 bytes total. Events have
varied flags (0x00, 0x08, 0x10) whose meaning we don't know.

It's plausible the device validates pattern integrity on scene transition
and rejects something specific to our 1-event-per-pattern shape. But the
single events parse correctly and play correctly (manual pad tap works).

### H3. Pattern flag byte encodes a "last event" marker

We always set flag=0x00. References mostly have 0x00 but with mid-event
0x08 / 0x10. If 0x10 is "last event flag" and we're missing it, the device
might overrun the pattern buffer on transition.

Counterargument: reference's last event also has flag=0 in most cases, so
0x10 isn't a last-event marker.

### H4. Pattern bars=2 with single event at position 0 confuses the transition machinery

Our patterns claim 2-bar duration but only fire 1 event at position 0. From
positions 96 to 768, the pattern is silent. Maybe the device, on stopping a
pattern mid-loop during scene-switch, hits a zero region and interprets it as
malformed.

### H5. Settings file should be DROPPED entirely (not zero-filled)

PROTOCOL.md §8 and EOD handoff both recommend not including the settings file
in the TAR. We currently include it as 222 zero bytes. The recommendation is
to omit the entry. Untested.

---

## 9. What we have NOT tried

- **Drop `settings` file from the TAR entirely** (lowest risk, smallest change)
- **Add empty `patterns/d05`** (lowest risk, second smallest change)
- Modify pattern event content (more invasive)
- Capture a *new* on-device reference where the user manually scene-switches
  successfully, to byte-diff against the failing build
- Set `time.mode=BPM` on pad records with per-slot `sound.bpm` JSON metadata
  (per PROTOCOL.md §7.2 — we'd need to figure out where `sound.bpm` lives)
- Use the user's actual `reference_minimal.ppak` as `--reference-template` to
  the CLI (currently we use the synthetic template). The CLI supports this via
  `--reference-template`. Worth one rebuild.

---

## 10. References

Repos (cloned at `/Users/zak/repos/`):

| Repo | Role | Useful for |
|------|------|-----------|
| `ZacharySBrown/ep133-ppak` | Diff-verified `.ppak` writer + per-pad BPM matrix tooling | Authoritative pad byte map (`PROTOCOL.md`); the working `time.mode=bpm` workaround; the no-`settings`-file warning |
| `phones24/ep133-export-to-daw` | Read-side `.ppak` parser (TS) | Cross-check on byte layouts; `collectScenesSettings` confirms phones24 only decodes `timeSignature` from scenes |
| `DannyDesert/EP133-skill` | Claude-Code skill that emits 1-bar drum patterns | Conservative template-based pad writes; doesn't touch stretch metadata |
| `garrettjwilke/ep_133_sysex_thingy` | SysEx capture archive | WAV-header JSON convention (sample-rate 46875, embedded `time.mode`/`sound.bpm`) |

In-repo specs / handoffs:

```
docs/ep133-song-triage/handoff-2026-04-26-eod.md          — yesterday's EOD handoff
docs/ep133-song-triage/triage.md                          — original ERR PATTERN 189 triage
docs/ep133-song-triage/triage-notes-2026-04-26.md         — mobile-session refined diagnosis
docs/ep133-song-triage/test-guide.md                      — on-device sequential test plan
docs/ep133-song-triage/song-mode-captures/                — the two captures that decoded song positions
docs/ep133-song-triage/reference_minimal.ppak             — known-good 4-sample baseline
specs/ep133_song_mode_capture_plan.md                     — original capture plan
specs/ep133-arrangement-song-export.md                    — original feature spec
```

---

## 11. The ask

Given everything above, what's the most likely remaining cause of `ERR PATTERN
189` on scene transition? My (current agent's) best guesses are listed in §8.
The two cheapest tests are:

1. **Drop the `settings` file from the TAR** (single line change in
   `_build_inner_tar`, zero risk based on what we know — protocol doc actively
   recommends this).
2. **Add empty `patterns/d05`** (single line change in `_build_inner_tar`, zero
   risk).

Neither has been tested on-device yet. Both could be done in a single rebuild.

But — am I missing a more obvious explanation, or is there a structural
reason single-event 12-byte patterns would specifically fail transitions
that I'm not seeing?
