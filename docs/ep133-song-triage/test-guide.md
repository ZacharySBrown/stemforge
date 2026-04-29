# Test Guide — `smack_song.ppak`

You should be on **Project 3** with no errors. This guide walks through what to verify, in order from easiest → most demanding.

## What's loaded

- **Project 3** — generated from your 5-locator arrangement of *Smack My Bitch Up*
- **Sample library** — 9 samples in slot range 700+ (USER 1 + USER 2 banks):
  - 704–707: drums (bar_002, bar_004, bar_006, bar_007)
  - 720–722: bass (bar_003, bar_002, bar_007)
  - 740: other (bar_001)
  - 760: other (bar_005)
- **Pads** — 9 populated:
  - **A** pads 5, 6, 7, 8 (drums)
  - **B** pads 1, 2, 3 (bass)
  - **C** pad 1 (other)
  - **D** pad 1 (other)
- **Patterns** — 9, one per (group, pad) combination
- **Scenes** — 5, one per locator from the arrangement
- **Tempo** — 136 BPM, 4/4

## Sequential tests (do in order, stop at first failure)

### 1. Visual sanity
- [ ] Project 3 loads with no error message
- [ ] Pad LEDs: tap **A** group button — pads 5/6/7/8 should look populated (lit/colored)
- [ ] Tap **B**, **C**, **D** group buttons — confirm pads 1–3 (B), 1 (C), 1 (D) look populated

### 2. Manual pad triggering
- [ ] On group **A**, tap pad 5 — should hear a drum loop
- [ ] Tap pad 6, 7, 8 — different drum loops on each
- [ ] Switch to group **B**, tap pad 1 — should hear bass
- [ ] Tap pad 2, 3 — different bass clips
- [ ] Group **C** pad 1 — "other" stem clip
- [ ] Group **D** pad 1 — second "other" stem

If any pad triggers silence: that pad's sample slot may have failed to load. Check the sample library to confirm the slot has audio.

### 3. Scene mode (manual stepping)
- [ ] You should be on **Scene 1** by default. If not, press `-` until the screen shows scene 1.
- [ ] Tap **PLAY** — Scene 1 loops. You should hear ONLY drums on group A (since the first locator only had drums playing on track A).
- [ ] Tap **STOP**.
- [ ] Press **+** to advance to Scene 2 — Tap PLAY — should hear drums + bass (groups A + B).
- [ ] STOP, **+** to Scene 3 — drums + bass continue (different clips).
- [ ] STOP, **+** to Scene 4 — drums + bass + "other" (groups A + B + C).
- [ ] STOP, **+** to Scene 5 — all 4 groups firing.

If a scene plays nothing on a group that should have a clip: pattern → pad binding may be off.
If a scene plays something on a group that shouldn't: extra (zero-fill) scene chunks leaking through.

### 4. Song mode (chained scene playback)
- [ ] Press `-` until back at Scene 1.
- [ ] **Hold SHIFT + tap PLAY** — engages Song mode.
- [ ] **Tap PLAY** — scenes should play in order, 1 → 2 → 3 → 4 → 5, then loop or stop.
- [ ] You should hear the full 5-section progression matching what you arranged in Live.

### 5. Time-stretch sanity
The clips were rendered at original tempo from your forge process; we tagged them as 2-bar loops at 136 BPM. The device should auto-stretch each clip to fit 2 bars at the project tempo.

- [ ] Each clip should sound rhythmically aligned with the project — no drift, no obvious time-stretch artifacts.
- [ ] If clips sound too slow or too fast: time-stretch math may be off (we set `stretch_mode=BARS, bars=2`).

## Things we know are imperfect

- **Pad record `length=0`**: we don't compute the actual sample length and write it to the pad record. The device probably figures this out from the WAV header on load, but if anything plays wrong we'll need to add real lengths.
- **Pad record `stretch_mode=BARS`**: we always set this. If a sample sounds bad, we may need to detect "this is a one-shot" vs "this is a loop" from the manifest and write different stretch settings.
- **Sound entry naming**: we write `/sounds/704 704_bar_002.wav` (slot prefix duplicated in display name). Cosmetic only — works fine, just slightly redundant.

## If something fails

Note exactly what fails and at which step. The most useful info:
- The exact error message on the device screen (if any)
- Which group / pad / scene triggers the failure
- Whether the issue is silence, wrong sound, or visual (lights)

I can rebuild the `.ppak` with adjustments and you can drag-drop again — fast iteration cycle.

## File locations (for reference)

- Generated `.ppak`: `~/Desktop/smack_song.ppak`
- Source arrangement snapshot: `~/Desktop/snapshot.json`
- Manifest: `/Users/zak/stemforge/processed/smack_my_bitch_up/curated/manifest.json`
- Reference template (minimal): `~/Desktop/EP-133_E3PUK243_2026-04-26_P01_backup.ppak`
- Source code (all changes): `feat/ep133-song-export` branch in `/tmp/sf-song-export/` worktree
