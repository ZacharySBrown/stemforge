# EP-133 Song-Mode Export — Handoff (2026-04-26 EOD)

**Branch:** `feat/ep133-song-export`
**Worktree:** `/tmp/sf-song-export`
**Pushed to:** `origin/feat/ep133-song-export` at commit `20b05d5` (mobile triage bundle); local has +2 uncommitted commits' worth of work in progress
**Tests:** 234/234 ep133 pass

---

## Where we are right now

Built a Live arrangement → EP-133 song-mode `.ppak` exporter end-to-end. Validated through six sequential failure modes on real hardware, fixing each in turn:

1. ✅ Sound entry naming (`/sounds/{slot} {name}.wav`)
2. ✅ Slot remap to 700+ (avoid clobbering user samples)
3. ✅ Pattern filename (`patterns/{group}{NN}` — no slash)
4. ✅ Pattern event encoding (0-indexed pad in event byte, vel=100, dur=96)
5. ✅ Scenes file fixed-size 712 bytes (was 37; truncation caused ERR SCENE 146)
6. ✅ Scenes trailer scene-count + (initially-incorrect) flag bytes
7. **In flight:** Drop BARS time-stretch + write song-mode positions in trailer
   to clear ERR PATTERN 189 and enable chained song playback

The latest `~/Desktop/smack_song.ppak` has both #7 fixes applied. **Awaiting on-device test** to confirm:
- ERR PATTERN 189 goes away (drop BARS mode hypothesis)
- Song mode plays scenes 1→2→3→4→5 in order (song positions in trailer)

---

## What unblocked the path forward

A user-captured **minimal reference** (`reference_minimal.ppak` — project 1, 4 drum samples on slots 700-703, 3 simple recorded scenes) gave us a known-good byte-level baseline. Every subsequent format bug was diagnosed by `xxd`-style diff against this reference rather than guessing from spec docs.

The single most useful diff was today's song-mode capture diff:
- `00_baseline_no_song.ppak` vs `01_song_5_positions_all_scene1.ppak`
- Diff = 5 bytes in the scenes trailer + 1 new empty pattern file
- Decoded the song-position list format in 30 seconds

Both captures are saved in `docs/ep133-song-triage/song-mode-captures/`.

---

## Decoded format spec (verified against captures)

### `.ppak` ZIP entries

```
/meta.json                                 — fixed JSON, only generated_at varies
/projects/P{NN}.tar                        — uncompressed POSIX TAR
/sounds/{slot:03d} {display_name}.wav      — note literal SPACE + display
```

### Project TAR contents

```
pads/{a|b|c|d}/p{NN}     — 27-byte fixed records (NN = 01..12, 1-indexed)
patterns/{group}{NN}      — variable size (NN = 01..99, NO slash)
scenes                    — fixed 712 bytes
                            (no `settings` file — see triage notes)
```

### Pad record (27 bytes)

```
byte 0       : 0x00
bytes 1-2    : sample_slot (uint16 LE)
bytes 3-7    : zero
bytes 8-11   : length (uint32 LE) — 0 acceptable in NONE mode
bytes 12-15  : time-stretch BPM (float32 LE) — 0 in NONE mode
byte 16      : 0x64 (amplitude=100 default)
bytes 17-19  : zero
byte 20      : 0xff (envelope.release for default playmode)
byte 21      : stretch mode — 0=NONE, 1=BPM, 2=BARS
bytes 22-23  : zero
byte 24      : 0x3c (note=60 default)
byte 25      : bars encoding — 0→1, 1→2, 2→4, 254→0.25, 255→0.5
byte 26      : zero
```

### Pattern file (4-byte header + 8N event bytes)

```
header: 00 [bars uint8] [event_count uint8] 00
event:  [pos_lo, pos_hi, (pad-1)*8, note, velocity, dur_lo, dur_hi, flag]
        - position_ticks: uint16 LE (96 ticks/beat, 384 ticks/bar)
        - pad encoding is 0-INDEXED in event byte (file paths are 1-indexed)
        - note: usually 0x3c (60); velocity: usually 0x64 (100)
        - flag: usually 0x00; sometimes 0x08 / 0x10 (purpose TBD)
```

### Scenes file (fixed 712 bytes)

```
bytes 0-6     : header (4 zero + numerator + denominator + ???=0)
bytes 7-600   : 99 × 6-byte scene slots [pat_a, pat_b, pat_c, pat_d, num, denom]
bytes 601-711 : 111-byte trailer
                - trailer[0..3]:   scene_count (BE uint32; in practice byte 604 only, since count < 256)
                - trailer[11]:     song length (count of song-position bytes, 0..99)
                - trailer[12..110]: song positions — one byte per position, value = scene index (1..99)
                - rest: zero
```

Default device state has `trailer[11]=1, trailer[12]=1` (a 1-position song pointing at scene 1). Our writer now emits a song-position list `[1..N]` so loaded `.ppak`s play scenes 1→N in song mode.

---

## Files touched (uncommitted, in worktree)

```
stemforge/exporters/ep133/song_format.py     — build_pad stretch_mode arg, build_scenes song_positions arg, PpakSpec.song_positions
stemforge/exporters/ep133/ppak_writer.py     — pass stretch_mode="none" + spec.song_positions through
stemforge/exporters/ep133/song_synthesizer.py — emit song_positions=[1..N] by default
tests/ep133/test_song_format.py              — updated assertions for stretch_mode
tests/ep133/test_ppak_writer.py              — updated assertions for one-shot pad bytes
docs/ep133-song-triage/song-mode-captures/   — 00_baseline_no_song.ppak + 01_song_5_positions_all_scene1.ppak
docs/ep133-song-triage/handoff-2026-04-26-eod.md  — this file
```

---

## Next steps

In order, smallest first:

### 1. On-device test of the latest `~/Desktop/smack_song.ppak`

Two outcomes to watch:
- **No ERR PATTERN 189** when switching scenes → confirms BARS-mode-with-zero-length was the cause
- **SHIFT+PLAY → scene 1→2→3→4→5 chain plays** → confirms song-position trailer format

If both pass → we have full song-mode export end-to-end. Commit + push.

If either fails → byte-diff the failing artifact against `reference_minimal.ppak` again; the format gap will surface.

### 2. Commit the two-fix checkpoint

```
git -C /tmp/sf-song-export commit -F <message>
git -C /tmp/sf-song-export push
```

Suggested message:
> fix(ep133-song): one-shot pad mode + song-position list — clears ERR PATTERN 189, enables chained scene playback
>
> - build_pad: new stretch_mode kwarg ("none" default, "bars" opt-in). One-shot mode zeros bytes 12-15 (BPM) and bytes 21/25 (mode/bars). Captured reference confirms one-shots have these zero; BARS mode + length=0 was producing ERR PATTERN 189 on scene switch.
> - build_scenes: optional song_positions kwarg. Writes count at trailer[11], each position byte at trailer[12+]. Default falls back to a 1-position song pointing at scene 1 (matches device's no-song default).
> - synthesizer: emits song_positions=[1..N] so loaded .ppak plays all scenes in order via SHIFT+PLAY.
>
> Decoded from byte-diff of two captures: docs/ep133-song-triage/song-mode-captures/{00_baseline_no_song,01_song_5_positions_all_scene1}.ppak.

### 3. (Future) Switch to `time.mode=BPM` for proper time-stretching

Per `docs/ep133-song-triage/triage-notes-2026-04-26.md` (mobile session) and `ZacharySBrown/ep133-ppak/PROTOCOL.md §7`:

- Set byte 21 = 1 (BPM mode)
- Set per-loop `sound.bpm` on the slot's JSON metadata (NOT in the pad record bytes 12-15)
- Device computes `playback_speed = project_bpm / sound.bpm` automatically
- Device infers bars from `bars = audio_seconds × sound.bpm / 240`

This would let song-export clips auto-fit the project tempo. Right now (one-shot mode) clips play at whatever BPM they were rendered at. For the "song built from forge-curated 2-bar loops" use case, this means the user must keep the project tempo at the source tempo — fine for testing, but limiting.

The blocker for step 3 is figuring out where `sound.bpm` lives. Two candidates:
- A separate JSON file inside the project TAR (none seen in any capture so far)
- WAV header metadata (cue points, LIST/INFO chunks, etc.) — referenced by `garrettjwilke/ep_133_sysex_thingy`

Easiest path: capture a `.ppak` from a device where the user has set per-pad BPM via the device UI, then byte-diff against a no-BPM baseline.

### 4. (Future) `stretch_mode="bpm"` writer support

Once #3 is decoded, add `stretch_mode="bpm"` to `build_pad` (write byte 21 = 1, populate `sound.bpm` source). Synthesizer can detect 2-bar loops from manifest metadata and emit BPM-mode pads with `sound.bpm` = source BPM.

### 5. (Future) Patcher button real estate

The EXPORT button is wired and works. The only on-device feedback when EXPORT runs is via the M4L status bar / debug log. Future polish: emit a short "snapshot saved" toast to a Live-visible UI.

### 6. (Future) UAT polish

- Locator names from Live should appear as scene labels on the device (currently scene names default to `<scene-N>`)
- A way to specify the EP-133 project slot from the M4L UI (currently CLI-only via `--project`)

---

## Active todos (this conversation)

```
✅ Cherry-pick misplaced clip-export commits onto curation-engine-v2
✅ Fix integration test (path API + WAV stubs)
✅ Add EXPORT button to M4L patcher
✅ Build new .pkg with EXPORT button + relocate
✅ EXPORT button writes snapshot.json
✅ Fix sound entry naming + slot 700+ remap
✅ Fix pattern filename (patterns/{group}{NN}, no slash)
✅ Fix pattern event format (vel=100, dur=96, pad-1 0-indexed)
✅ Fix scenes file format (fixed 712 bytes + trailer)
✅ Captured minimal reference (4 samples/scenes) — byte-diff revealed all format bugs
✅ Device boots clean: "restore complete" no errors
✅ Write test guide for on-device validation
✅ Wire song-mode positions in scenes trailer
✅ Drop BARS time-stretch (one-shot mode to clear ERR PATTERN 189)
🔄 On-device test of latest .ppak (in progress when handoff written)
⏳ Commit two-fix checkpoint + push
⏳ Walk through full test guide once errors clear
```

---

## Key references for the next agent

| Path | What's there |
|------|--------------|
| `docs/ep133-song-triage/triage.md` | Original triage doc (2026-04-26 morning) — full format spec we'd verified pre-song-mode-decode |
| `docs/ep133-song-triage/triage-notes-2026-04-26.md` | Mobile session triage notes — cross-references 4 upstream RE projects |
| `docs/ep133-song-triage/song-mode-captures/` | The two on-device captures that decoded song-mode format |
| `docs/ep133-song-triage/reference_minimal.ppak` | Known-good byte-diff baseline (no copyright concern, 180 KB) |
| `docs/ep133-song-triage/test-guide.md` | On-device test plan (5 sequential tests) |
| `specs/ep133_song_mode_capture_plan.md` | The capture plan from the mobile session (now executed) |
| `specs/ep133-arrangement-song-export.md` | Original spec for the whole feature |
| `stemforge/exporters/ep133/song_format.py` | Byte builders for pads/patterns/scenes/settings |
| `stemforge/exporters/ep133/ppak_writer.py` | Assembles ZIP + TAR + sounds |
| `stemforge/exporters/ep133/song_synthesizer.py` | Snapshot → PpakSpec |

---

## Repo state warning (parallel work in progress)

User has a **second concurrent stream of work** on `feat/curation-library-v2` in their main checkout (`/Users/zak/zacharysbrown/stemforge`). DO NOT switch the main checkout's branch — operate via `/tmp/sf-song-export` worktree only.

The user's main checkout has substantial untracked files (`TOP3_TUNING_*.md`, `DUMP`, `backups/`, `export/`, etc.) — these are NOT mine and NOT to be committed.
