# EP-133 Song Export — Triage Follow-up (2026-04-26)

Mobile session follow-up to the original triage on `feat/ep133-song-export`
(`docs/ep133-song-triage/triage.md`, commit `20b05d5`). Cross-references
four upstream RE projects against our writer to refine the **ERR PATTERN
189** diagnosis.

## Status

Unchanged since the previous note: `Restore` loads cleanly, switching to
any populated scene fails with **ERR PATTERN 189** on the device screen.

## What we cross-referenced

| Repo | Role | Useful for |
|------|------|------------|
| [`ZacharySBrown/ep133-ppak`](https://github.com/ZacharySBrown/ep133-ppak) | Diff-verified `.ppak` writer + per-pad BPM matrix tooling | Authoritative pad-record byte map; the `time.mode=bpm` workaround for per-pad tempo; the no-`settings`-file warning |
| [`phones24/ep133-export-to-daw`](https://github.com/phones24/ep133-export-to-daw) | Read-side `.ppak` parser (TS) | Cross-check on pad/scenes/settings byte layout; `collectScenesSettings` confirms phones24 only decodes `timeSignature` from the scenes file |
| [`DannyDesert/EP133-skill`](https://github.com/DannyDesert/EP133-skill) | Claude-Code skill that emits 1-bar drum patterns | Conservative template-based pad writes; does NOT touch stretch metadata |
| [`garrettjwilke/ep_133_sysex_thingy`](https://github.com/garrettjwilke/ep_133_sysex_thingy) | SysEx capture archive | WAV-header JSON convention (sample-rate 46875, embedded `time.mode`/`sound.bpm`) |

## Refined diagnosis

### Primary suspect — pad-record stretch metadata is internally inconsistent

Every pad record we emit has:

- `bytes 8-11 (length, u32 LE)` = **0**
- `bytes 12-15 (timeStretchBpm, f32 LE)` = project BPM (e.g. 135.998)
- `byte 21 (time.mode)` = **2 (BARS)**
- `byte 25 (timeStretchBars)` = encoded bar count

`ZacharySBrown/ep133-ppak/PROTOCOL.md §7` (diff-verified 2026-04-25)
recommends a different path entirely:

- Use **`time.mode = bpm`** (byte 21 = 1), **not** `bar`
- Set per-loop **`sound.bpm`** on the **slot's JSON metadata** (not the
  pad-record bytes 12-15)
- Device computes `playback_speed = project_bpm / sound.bpm` automatically
- The `bpm_matrix.py` tool in that repo is a working example of this
  pattern across 12 pads

This sidesteps the bytes 8-11 length question entirely — `bpm` mode
doesn't depend on knowing the source length up front, and the device
infers bars from `bars = audio_seconds × sound.bpm / 240`.

### Secondary suspect — `settings` file inclusion is a flash-format hazard

Our writer emits `settings` (222 bytes patched from a captured template)
inside every project TAR. `ZacharySBrown/ep133-ppak/PROTOCOL.md §8` is
explicit:

> No `settings` file inside the TAR — adding one in our generator
> triggered ERROR CLOCK 43 on import, which persisted across power
> cycles and required flash format to recover.

Today's restore loaded clean, so this is not the immediate cause of ERR
PATTERN 189. But it's a latent device-bricking bug regardless of the
triage outcome and should be removed.

## Coverage tally — what's known vs unknown

| Component | Total bytes | Understood for our use case | Real unknowns |
|-----------|-------------|------------------------------|---------------|
| `meta.json` | ~400 | 100% — 10 named fields | none |
| `pads/{g}/p{NN}` (×9) | 27 each | All bytes that vary in our writes: slot, length, BPM, mode, bars enc, play mode | bytes 2-7, 17-19, 22 zero-fill in every capture |
| `patterns/{g}{NN}` (×9) | variable | Header (4B), 7 of 8 event bytes | last byte of event (flag); zero-fill is safe |
| `scenes` | 712 | Header 7B + 99×6B chunks + byte 604 (count) + bytes 612-613 (`01 01`) | **bytes 601-603** (phones24's example shows `127 2 8` — likely song-mode state) |
| `settings` | 222 | KNOWN: should not be in the TAR at all | n/a |

The only real gap relevant to this triage is **scenes bytes 601-603**.
Resolving it requires capturing a `.ppak` from a device with song mode
configured — see `specs/ep133_song_mode_capture_plan.md`.

## Scenes file diff (smoking-gun confirmation)

Decoded both `reference_minimal.ppak` (3 committed scenes, no song mode)
and our failing `smack_song.ppak` (5 committed scenes). Trailer
byte-wise diff:

```
byte 604:  REF=0x03  OURS=0x05    ← scene_count
(every other byte 0..711 identical)
```

So the scenes file is fully understood and not the cause of ERR PATTERN
189. Our writer's `scene_count = u32 BE at trailer[0..3]` model is
slightly wrong (it's actually a single u8 at trailer[3] = file byte 604),
but produces correct output as long as count < 256.

## Recommended next steps

In order, smallest-effort first:

1. **Capture song-mode reference `.ppak`** per
   `specs/ep133_song_mode_capture_plan.md`. Resolves bytes 601-603 +
   reveals where song-position list is stored.
2. **Switch writer from `time.mode=bar` to `time.mode=bpm`** (slot
   metadata + pad record byte 21 = 1). Mirrors the working pattern in
   `ZacharySBrown/ep133-ppak/tools/bpm_matrix.py`.
3. **Drop the `settings` file** from the TAR. Independent of the ERR
   PATTERN fix; eliminates the ERROR CLOCK 43 hazard.

Steps 2 and 3 land best on `feat/ep133-song-export`, not this debug
branch.

## What this branch (`claude/debug-ep133-export-VlBBM`) contains

This branch carries triage docs only — no code changes. The fix lands
on `feat/ep133-song-export`.
