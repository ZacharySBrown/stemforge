# EP-133 Song Export — ERR PATTERN 189 Triage

**Branch:** `feat/ep133-song-export`
**As of commit:** `1f469a7` (four format fixes — device now restores .ppak cleanly)
**Status:** Restore loads with no error. Switching to a populated scene fails with **ERR PATTERN 189**. Error doesn't require device restart.

## Files in this directory (NO sanitization — raw artifacts)

| File | Purpose |
|------|---------|
| `smack_song.ppak` | The failing artifact (22 MB, includes audio from *Smack My Bitch Up* — leave for triage only) |
| `reference_minimal.ppak` | Working minimal reference: project 1 with 4 drum-hit samples on slots 700-703 + 3 simple recorded scenes. Use this for byte-diffs. |
| `snapshot.json` | Input from M4L EXPORT button — 5 locators, A=5 / B=4 / C=2 / D=1 clips |
| `test-guide.md` | The on-device test plan |

## What we know works

- **Restore loads cleanly** ("Restore complete", no error message)
- Sample library shows 9 samples in slot range 700+ (704-707, 720-722, 740, 760)
- Pad layout looks correct on group views (per visual inspection during prior tests)

## What fails

- **Switching to a populated scene** → `ERR PATTERN 189` on device screen
- Doesn't require device restart (good — soft error)
- We don't yet know what "189" refers to (offset? pattern index? error code?)

## Likely-suspect areas (in priority order)

### 1. Pad record `length=0` field with `stretch_mode=BARS` set

Our pad records claim BARS time-stretch mode but byte 8-11 (length) is 0 because the minimal reference template (which we use as the byte template) didn't have populated pads on the slots we write. Captured working pads ALWAYS have a non-zero length.

Hex side-by-side (snippet from prior debugging):

```
REF pads/a/p10 (one-shot, working):
  00 bc 02 00 00 00 00 00 ae 33 00 00 00 00 00 00 64 00 00 00 ff 00 00 00 3c 00 00
  ^slot=700^  zeros           ^^len=13230^  ^^bpm=0^^         ^vel ^^^      ^stretch=0/bars=0
                                              (no stretch)              flag

OUR pads/a/p05 (BARS-mode, length=0, FAILING):
  00 c0 02 00 00 00 00 00 00 00 00 00 ca ff 07 43 64 00 00 00 ff 02 00 00 3c 01 00
  ^slot=704^  zeros           ^^len=0^^   ^^bpm=135.998^      ^vel ^^^      ^stretch=2(BARS)/bars=2
```

**Most-likely fix paths:**
- (a) Compute actual sample length from the WAV header and write it to bytes 8-11
- (b) Drop BARS-mode entirely → write as one-shot (mode=0, bpm=0, bars=0). Samples play at original tempo, no auto-stretch.

(b) is faster to validate. (a) is the right long-term answer.

### 2. Pattern format edge case

Pattern bytes look correct per the byte-diff (post commit `1f469a7`):
- `pad*8` is now 0-indexed (verified against minimal reference's pad 10 → byte `0x48`)
- `note=0x3c`, `vel=0x64`, `dur=0x60` (96 ticks) match captured one-shots

But the device may still object to our 1-event-at-pos-0 patterns if it expects events to fire on grid beats. The minimal reference's recorded patterns had 4 events at positions 0, 192, 384, 576 (beats 1+3 of bars 1+2).

### 3. Scenes file trailer

We write `scene_count` (BE u32) at trailer offset 0 + `01 01` at offset 11. The reference had this exact layout. But there could be other non-zero trailer bytes we're missing.

## Format spec — what we've verified

All of these are verified against `reference_minimal.ppak` (byte-diffed):

### `.ppak` ZIP entries

```
/meta.json                          — fixed-template JSON, only generated_at varies
/projects/P{NN}.tar                 — uncompressed POSIX TAR
/sounds/{slot:03d} {display_name}.wav  — note literal SPACE + display name
```

### Project TAR contents

```
pads/{a|b|c|d}/p{NN}                — 27-byte fixed records, NN = 01..12 (1-indexed)
patterns/{a|b|c|d}{NN}              — variable size, NN = 01..99 (NO slash between group and number!)
scenes                              — fixed 712 bytes
settings                            — fixed 222 bytes (only BPM at bytes 4-7 patched)
```

### Pad record (27 bytes) — `pads/{group}/p{NN}`

```
byte 0       : 0x00
bytes 1-2    : sample_slot (uint16 LE)
bytes 3-7    : zero-fill
bytes 8-11   : length (uint32 LE) — sample length, units TBD (probably samples)
bytes 12-15  : time-stretch BPM (float32 LE), 0 for one-shots
byte 16      : 0x64 (amplitude=100 default)
bytes 17-19  : zero
byte 20      : 0xff (envelope.release for default playmode)
byte 21      : stretch mode — 0=NONE, 2=BARS
bytes 22-23  : zero
byte 24      : 0x3c (note=60 default)
byte 25      : bars encoding — 0→1, 1→2, 2→4, 254→0.25, 255→0.5 (per phones24)
byte 26      : zero
```

### Pattern file — `patterns/{group}{NN}`

```
byte 0     : 0x00
byte 1     : bars (uint8)
byte 2     : event_count (uint8, max 255)
byte 3     : 0x00
bytes 4..  : event_count × 8-byte event records:
               [pos_lo, pos_hi, (pad-1)*8, note, velocity, dur_lo, dur_hi, flag]
             - position_ticks: uint16 LE (384 PPQN, so 96 ticks/beat)
             - pad encoding is 0-INDEXED in event byte (file paths are 1-indexed)
             - note: usually 0x3c (60 = C4)
             - velocity: usually 0x64 (100)
             - duration_ticks: uint16 LE (short trigger, ~24-100 typical)
             - flag: usually 0x00; occasionally 0x08 or 0x10 (purpose TBD)
```

### Scenes file (FIXED 712 bytes)

```
bytes 0-6     : header (4 zero + numerator + denominator + ???=0)
bytes 7-600   : 99 × 6-byte scene slots [pat_a, pat_b, pat_c, pat_d, num, denom]
                (zero-fill unused slots, but keep num/denom)
bytes 601-711 : 111-byte trailer
                - trailer[0..3]: scene_count (BIG-endian uint32!)
                - trailer[11..12]: 0x01 0x01 (purpose TBD)
                - rest: zero-fill
```

### Settings file (FIXED 222 bytes)

Preserved from template. Only patch BPM at bytes 4-7 (float32 LE).

## How to reproduce locally

The code that built `smack_song.ppak`:

```bash
# From repo root, on branch feat/ep133-song-export
uv run stemforge export-song \
  --arrangement <path-to-snapshot.json> \
  --manifest <path-to-stemforge-curated-manifest.json> \
  --reference-template docs/ep133-song-triage/reference_minimal.ppak \
  --project 3 \
  --out smack_song.ppak
```

If you're remote and don't have the original WAVs, you can still:
- Inspect `smack_song.ppak` byte-by-byte (it's right here in the dir)
- Compare with `reference_minimal.ppak`
- Modify the writer code in `stemforge/exporters/ep133/` (song_format.py, ppak_writer.py, song_synthesizer.py)
- Use `tests/ep133/` (234 passing tests — run with `uv run pytest tests/ep133/`)

## Key source files

| File | Purpose |
|------|---------|
| `stemforge/exporters/ep133/song_format.py` | Byte builders for pads/patterns/scenes/settings |
| `stemforge/exporters/ep133/ppak_writer.py` | Assembles ZIP + TAR + sounds |
| `stemforge/exporters/ep133/song_synthesizer.py` | Snapshot → PpakSpec (slot 700+ remap, vel=100, dur=96) |
| `stemforge/exporters/ep133/song_resolver.py` | snapshot.json + manifest → list of Snapshots (one per locator) |
| `stemforge/cli.py` | `stemforge export-song` subcommand |

## Recent commits on this branch

```
1f469a7 fix(ep133-song): four format fixes — device now restores .ppak cleanly
e658b68 feat(m4l): EXPORT button → exportArrangementSnapshot wired in patcher
54ed32a fix(ep133-song): integration test materialises stub WAVs + uses path API
2e5237d fix(m4l): chunk readstring/writestring at signed-short cap (32767)
732d858 fix(clip-export): wrap modulo loop region + bpm-derived seconds_per_beat
693dc53 fix(ep133-song): post-merge integration of tracks A+C
01371d4 Merge Track B: arrangement-view snapshot reader (M4L)
cc33a01 Merge Track D: reference-ppak capture + integration test + workflow doc
f8b3b21 Merge Track C: snapshot resolver + song synthesizer + export-song CLI
5cd8cab feat(ep133): song-mode binary format + .ppak writer
```

## Quickstart for the remote agent

```bash
# 1. Inspect the failing pads + patterns
uv run python -c "
import zipfile, tarfile, io
from pathlib import Path
p = Path('docs/ep133-song-triage/smack_song.ppak')
with zipfile.ZipFile(p) as zf:
    tar_b = zf.read(next(n for n in zf.namelist() if n.endswith('.tar')))
with tarfile.open(fileobj=io.BytesIO(tar_b), mode='r') as tf:
    for n in sorted(tf.getnames()):
        if n.startswith('pads/') or n.startswith('patterns/') or n in ('scenes',):
            f = tf.extractfile(n)
            if f:
                d = f.read()
                if any(d[1:3]) or n.startswith('pattern') or n == 'scenes':
                    print(f'{n}: {d.hex()[:120]}')
"

# 2. Same for the reference (working baseline)
# (replace path; same script)

# 3. If hypothesis is "drop BARS mode" — patch song_synthesizer.py:
#    play_mode='oneshot', time_stretch_bars=1, project_bpm=None
#    Then re-run pytest tests/ep133/ to confirm + regenerate.
```

## What to avoid

- Don't push the user's audio (`smack_song.ppak` already on this branch is acceptable for triage — clean up before any release)
- Don't amend `1f469a7` — it's a clean checkpoint
- Don't switch the local main checkout's branch (user has parallel work on `feat/curation-library-v2`)
