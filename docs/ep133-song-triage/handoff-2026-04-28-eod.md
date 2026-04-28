# EP-133 Song-Mode Export — Handoff (2026-04-28 EOD)

**Branch:** `feat/ep133-song-export`
**Worktree:** `/tmp/sf-song-export`
**Tip commit:** `d9d00d3` (3 commits ahead of `origin/feat/ep133-song-export`, not yet pushed)
**Tests:** 233/233 ep133 pass
**Status:** Scene-mode export works end-to-end on factory-reset hardware. **Next ticket: time.mode=BPM for tempo-aware playback.**

---

## Where we are

Scene-mode export through StemForge's `export-song` CLI is working. Verified on a factory-reset EP-133 K.O. II:

- 5-scene smack arrangement (`/Users/zak/Desktop/snapshot.json` + `/Users/zak/stemforge/processed/smack_my_bitch_up/curated/manifest.json`) builds via `stemforge export-song --reference-template docs/ep133-song-triage/reference_minimal.ppak --project 9` to a 6.8 MB `.ppak`.
- Sample Tool transfers the `.ppak` cleanly (no hangs, no `ERR 82`).
- Project loads cleanly (no `ERR SCENE 146/154`).
- All 9 pads trigger their assigned smack samples.
- Scene-stepping through scenes 1 → 2 → 3 → 4 → 5 fires the right groups in each.
- Scene 5 → 4 transition (the original `ERR PATTERN 189` failure) works cleanly.

**Open issue:** clips play at their native render tempo, not the project tempo. The pad record `time.mode` is currently `NONE` (one-shot mode); switching to `BPM` mode is the next ticket.

---

## What changed today (3 commits, on top of `20b05d5`)

### `0865298 fix(ep133-song): full byte-level rewrite — scenes work end-to-end`

The big writer corrections, all rooted in capturing a factory-reset device backup (`docs/ep133-song-triage/factory_default.pak`) and using its bytes as ground truth — vs. the user-saved Sample Tool roundtrip captures we'd been chasing.

1. **WAV format conversion** (new module `stemforge/exporters/ep133/wav_format.py`). Sample Tool transfers hung on any WAV that wasn't mono 16-bit 46875Hz with `smpl` + `LIST/INFO/TNGE` metadata chunks. `convert_wav_to_ep133()` does the conversion + chunk authoring. Wired into `build_ppak()` so every bundled WAV is converted on the way through.
2. **Pad records are 26 bytes, not 27** (`PAD_RECORD_SIZE = 26`, `DEVICE_DEFAULT_PAD` rebuilt). Upstream `ZacharySBrown/ep133-ppak/PROTOCOL.md` says 27 — that's a Sample Tool roundtrip artifact. Factory P01-P05 records are 26 bytes with BPM=0 default at bytes 12-15 (not 120.0 as the protocol doc claims). The `_ReferenceTemplate.load` path transparently truncates 27-byte legacy templates.
3. **Sample length frames at bytes 8-11** (uint32 LE). PROTOCOL.md §7 marks REQUIRED; we'd been zeroing it. Computed from the post-conversion WAV via `wave.getnframes()`.
4. **Settings file omitted from the TAR**. Populating it (even byte-for-byte from a working reference) wedged the device with `ERR 82`. Per PROTOCOL.md §8 the entry should not be present at all.
5. **Minimal TAR layout** — emit only the 6 directory entries + only the pad files for assigned pads. Factory P06 (truly empty project) emits zero pad files.
6. **`patterns/d05`** empty-pattern marker added when song positions are set. Decoded from the byte-diff of the two on-device song-mode captures.

### `acb9354 docs(ep133-triage): saga artifacts`

`factory_default.pak` (26 MB, the gold reference), the EOD handoff from yesterday, the song-mode captures, and the cold-brief summary. Plus yesterday's M4L EXPORT-button build (`v0/build/StemForge.amxd`).

### `d9d00d3 fix(ep133-song): silent groups reference empty pattern, not 0`

The bug that was hiding behind every "ERR PATTERN 189" all along. The synthesizer used to emit `pat_x=0` in scene chunks where a group had no clip in a snapshot. The device errors with `err pattern 189` on scene transition when a group transitions from a real pattern to 0 — verified on factory-reset hardware with the smack arrangement (scene 5 → 4 fired 189 because group D went from d01 → 0).

Reference song-mode captures NEVER use 0 in scene chunks; every scene fires every group. "Silent" is encoded by referencing an empty pattern (`patterns/{group}99` = `00 02 00 00`).

Synthesizer now emits `EMPTY_PATTERN_INDEX = 99` in scene chunks for silent groups, and adds one empty `Pattern` per group that needs it.

---

## The path you can replay

```bash
# In /tmp/sf-song-export (the worktree).
python -m stemforge.cli export-song \
  --arrangement /Users/zak/Desktop/snapshot.json \
  --manifest /Users/zak/stemforge/processed/smack_my_bitch_up/curated/manifest.json \
  --reference-template docs/ep133-song-triage/reference_minimal.ppak \
  --project 9 \
  --out /Users/zak/Desktop/smack_song.ppak
```

Inspect the output:

```python
import zipfile, tarfile, io
with zipfile.ZipFile('/Users/zak/Desktop/smack_song.ppak') as zf:
    tar_b = zf.read(next(n for n in zf.namelist() if n.endswith('.tar')))
with tarfile.open(fileobj=io.BytesIO(tar_b)) as tf:
    sc = tf.extractfile('scenes').read()
    for i in range(5):
        off = 7 + i*6
        print(f"scene {i+1}: {list(sc[off:off+6])}")
# scene 1: [1, 99, 99, 99, 4, 4]   ← drums + 3 empties
# scene 5: [4, 3, 1, 1, 4, 4]      ← all 4 groups firing
```

To test on hardware:

1. Factory-reset the device (NOT just format — see `MEMORY.md` standing rules).
2. Open MIDI Monitor, start recording.
3. Drag `~/Desktop/smack_song.ppak` to Sample Tool, upload to project 9.
4. Switch to project 9, step through scenes with `+`/`-`, then `SHIFT+PLAY` for song-mode chain.

---

## Next ticket: `time.mode=BPM` for tempo-aware playback

Right now clips play at their native render tempo, not the project tempo. Pad records ship with `time.mode = NONE` (byte 21 = 0). To make clips stretch to project tempo:

### What needs to change

Per `ZacharySBrown/ep133-ppak/PROTOCOL.md §7.2`:

- **Pad record byte 21 = 1** (BPM mode, not 0/NONE or 2/BARS).
- **`sound.bpm` populated in the WAV's `LIST/INFO/TNGE` JSON metadata** for each sample. The device computes `playback_speed = project_bpm / sound.bpm` on every pad trigger.
- **Bytes 12-15 (BPM float32 in pad record)** likely irrelevant in BPM mode (the device reads `sound.bpm` from the WAV metadata, not the pad record). Verify by capture.

### Where each lives in StemForge

| Change | File | Notes |
|---|---|---|
| `time.mode` field in JSON metadata | `stemforge/exporters/ep133/wav_format.py:DEFAULT_SOUND_METADATA_JSON` | currently `"time.mode":"off"` — change to `"bpm"` |
| `sound.bpm` field in JSON metadata | same | currently absent — add as a runtime-set field |
| `convert_wav_to_ep133` signature | same | needs a `sound_bpm` kwarg threaded through |
| Pad record byte 21 | `stemforge/exporters/ep133/song_format.py:build_pad` | add a `stretch_mode="bpm"` branch (we already have `"none"` and `"bars"`) |
| Source BPM determination | `stemforge/exporters/ep133/song_synthesizer.py` | derive per-clip BPM from manifest metadata (the curated/ stems should have known BPMs from forge processing) |
| Wiring through `build_ppak` | `stemforge/exporters/ep133/ppak_writer.py` | pass per-slot `sound_bpm` from spec/synthesizer through to the WAV converter |

### How to determine `sound.bpm` per clip

Best-case: the manifest's `session_tracks` entries already carry BPM info from the forge curation pipeline. Check with:

```python
import json
m = json.load(open("/Users/zak/stemforge/processed/smack_my_bitch_up/curated/manifest.json"))
for grp, entries in (m.get("session_tracks") or {}).items():
    for e in entries[:1]:
        print(grp, list(e.keys()))
```

If BPM isn't in the manifest, the source-of-truth is the project tempo at render time (90.67 BPM for the smack arrangement). Forge-curated 2-bar loops at project BPM mean `sound.bpm = project_bpm`.

### How to verify on-device

Easiest: capture a `.ppak` from a device where the user has set per-pad BPM via the device UI (Sample Tool's "edit sample" or the device's per-pad settings menu), then byte-diff against a no-BPM baseline. The diff will land in:
- WAV metadata JSON (the `sound.bpm` value)
- Pad record byte 21 (mode flag)

`ZacharySBrown/ep133-ppak/tools/bpm_matrix.py` is a working SysEx-based example of this — read it for the exact shape of the metadata and pad-record write.

### Test plan

Reuse the rebuild + factory-reset cycle. Build a single-sample test like `test_smack_no_zero_refs.ppak` but with `time.mode=BPM` set + a known `sound.bpm` (e.g. 90.67). On device, change the project tempo to 120 BPM and confirm the sample plays back at `120/90.67 = 1.32×` speed. Then bake the changes into the writer and rebuild the full smack with the right BPMs.

---

## Standing rules (from `MEMORY.md`)

These are durable instructions from the user, applicable across sessions:

- **Operate via `/tmp/sf-song-export` worktree only.** Don't switch the main checkout's branch — there's parallel work on `feat/curation-library-v2`.
- **Factory-reset (not format) before each device test.** Format alone leaves the device under-initialized; Sample Tool can't read project metadata.
- **Don't populate the `settings` file in the TAR.** Triggers `ERR 82`/`ERR 8200` (wedge-class). Currently omitted.
- **Pad records are 26 bytes, not 27.** Upstream PROTOCOL.md is wrong about this.
- **WebMIDI traffic is captureable via MIDI Monitor on macOS.** The `33 33` manufacturer route carries firmware debug logs as ASCII — every device error appears here with source-file/line context.

---

## Reference points

```
docs/ep133-song-triage/factory_default.pak                     — gold byte reference
docs/ep133-song-triage/reference_minimal.ppak                  — known-good 4-sample baseline
docs/ep133-song-triage/song-mode-captures/                     — the captures that decoded song positions
docs/ep133-song-triage/handoff-2026-04-26-eod.md               — yesterday's handoff
docs/ep133-song-triage/handoff-2026-04-28-eod.md               — this doc
docs/ep133-song-triage/summary-for-fresh-eyes-2026-04-27.md    — mid-saga cold-brief

stemforge/exporters/ep133/song_format.py                       — byte builders
stemforge/exporters/ep133/wav_format.py                        — WAV converter + metadata chunks
stemforge/exporters/ep133/ppak_writer.py                       — assembles ZIP + TAR + sounds
stemforge/exporters/ep133/song_synthesizer.py                  — snapshot + manifest → PpakSpec
stemforge/cli.py                                               — `export-song` CLI

/Users/zak/stemforge/exports/sysex_capture[1-7].txt            — captured device traffic
```

Upstream RE projects (cloned at `/Users/zak/repos/`):

- `ZacharySBrown/ep133-ppak` — `PROTOCOL.md` (mostly correct, wrong on pad-record size); `tools/bpm_matrix.py` is the BPM-mode reference.
- `phones24/ep133-export-to-daw` — TS read-side parser.
- `garrettjwilke/ep_133_sysex_thingy` — SysEx capture archive; per-WAV metadata convention.
