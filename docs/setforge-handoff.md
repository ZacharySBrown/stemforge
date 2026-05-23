# setforge — Session Handoff

**Date:** 2026-05-23
**Working dir:** `/Users/zak/zacharysbrown/setforge` (a fresh clone, separate from `~/zacharysbrown/stemforge`)
**Branch:** `feat/setforge` (2 commits ahead of `main` @ 8a1f6e7)
**Working tree:** clean

---

## What setforge is

A live stem-DJing loader: **4 song "decks" A/B/C/D playable at once**, each deck =
**4 flat audio tracks** named `<DECK>-<stem>` (`A-d` `A-b` `A-v` `A-o` = drums/
bass/vocals/other). `loadDeck` reloads a song's four stems into one deck **in
place**, leaving the other three decks untouched and still playing. Two decks per
Launchpad (8 columns).

Built in the **v0 loader** (`v0/src/m4l-js/stemforge_loader.v0.js`), NOT the
legacy `m4l/stemforge_loader.js`.

Key reference docs in this repo:
- `docs/design-docs/setforge-loader.md` — full design, alternatives, open questions
- `SETFORGE-LOADER-SPEC.md` — the original feature spec (track naming, layout, build order, risks)

---

## What's DONE (committed on `feat/setforge`)

**Commit e4adfb5** — `loadDeck` core:
- `loadDeck(mf)` — validate-all-paths-first, then reuse `loadClip`
  (delete→`create_audio_clip`→probe→warp/loop/name) + layer per-clip color.
  Loops `for (s=0; s<rows; s++)` so rows 1/2/4 are config, not new code.
- `hueToLiveColor(hue)` — 0..1 hue → `0xRRGGBB` at full S/V.
- `validateDeckPaths(mf)` — a missing file aborts BEFORE touching a live deck.
- `loadDeckFromDict()` — production `[dict]` entry (mirrors `loadFromDict`).

**Commit 533b72c** — trigger path (so it's runnable today, no taste needed):
- `loadDeckPath()` in the loader — reads a deck manifest JSON from disk → `loadDeck`.
- `loadDeck()` forwarder in `sf_forge.js` — fires `loadDeckPath <path>` at the
  loader's inlet via outlet 2 (same pattern as the `reload` forwarder). UDP route
  `/forge` already reaches `sf_forge`.

**Tests:** `tests/js_mocks/test_deck_loader.test.js` — 11 cases (hue conversion,
rows=1 place w/ warp+loop+name+color, reload-in-place, deck isolation, rows=2 +
scene auto-create, validate-before-mutate abort, missing-track bail, both dispatch
entries, disk read happy + unreadable, src/pkg byte-identity). Covers spec §6
build-order steps 1–4. Full `js_mocks` suite green.

Both JS files are mirrored to `v0/src/m4l-package/StemForge/javascript/`. `.amxd`
rebuilt (byte-identical — JS ships via the Max Package, NOT embedded in the .amxd).

**Design defaults locked (Zak approved):**
- Manifest audio field = **`audio_path`** (not `wav_path`).
- Deck layout is **SEPARATE** from the existing COMMIT `session_tracks` A/B/C/D
  model (that one = 1 track/deck with mixed stems in slots; see
  `_restoreSessionTracks`). Don't conflate them.
- Warp-marker reuse **deferred** — plain `warping=1` for now.

---

## Manifest contract (taste → setforge)

```json
{
  "version": 1,
  "deck": "A",
  "rows": 1,
  "song": { "name": "Squarepusher - Beep Street", "color_hue": 0.62 },
  "bpm": 137.0,
  "stems": {
    "drums":  { "clips": [ { "slot": 0, "audio_path": "/abs/A_drums.wav" } ] },
    "bass":   { "clips": [ { "slot": 0, "audio_path": "/abs/A_bass.wav"  } ] },
    "vocals": { "clips": [ { "slot": 0, "audio_path": "/abs/A_vocals.wav"} ] },
    "other":  { "clips": [ { "slot": 0, "audio_path": "/abs/A_other.wav" } ] }
  }
}
```
`stems.<name>.clips` length MUST == `rows`; `clips[s].slot == s`.

---

## DEPLOY / RUN — the immediate next step

**You do NOT rebuild the device. Load the same `.amxd`.** It references JS by
name; the running device reads JS from the live Max Package at
`~/Documents/Max 9/Packages/StemForge/javascript/`. Only the JS changed, so it
just needs to be re-deployed there.

**Sequence to make `loadDeck` live:**

1. **Deploy JS** from THIS clone → live package + rebuild .amxd:
   ```bash
   uv run python tools/sf_deploy.py
   ```
   `tools/sf_deploy.py` copies `v0/src/m4l-js/*.js` → the m4l-package mirror AND →
   `~/Documents/Max 9/Packages/StemForge/javascript/`, then rebuilds the .amxd.
   ⚠️ That live package dir is SHARED — deploying from the setforge clone overwrites
   whatever the `~/zacharysbrown/stemforge` repo last pushed there. That's fine for
   testing setforge; just know the two clones share one live install.
   (When I checked, `~/Documents/Max 9/Packages/StemForge` didn't show from my
   sandboxed shell — may just be blocked. Verify the copy actually landed; if the
   dir doesn't exist, the package was never installed and needs a first install.)

2. **Reload the device's JS** so it picks up the new functions:
   `uv run sf-remote fire forge reload`  (or Cmd+S in the `[js]` editor, or
   close/reopen the device).

3. **Build the Live set layout (CONFIG, once):** 16 flat audio tracks named
   `A-d A-b A-v A-o  B-d…  C-d…  D-d…D-o` + a source track. (Optional per-deck
   processing: route each deck's 4 stems to a return `RET-A..D` — groups are
   impossible in M4L. CONFIG, not code.)

4. **Fire it:**
   ```bash
   uv run sf-remote fire forge loadDeck /path/to/deck.json
   ```

---

## What's NOT done (next decisions)

1. **Production trigger** (Open Question 2 in the design doc) — how decks actually
   get loaded in performance: **taste** (recommender, separate project), a **popup
   button**, or **Launchpad**. The `sf-remote` disk path above is trigger-agnostic
   and works regardless. Needs Zak's call before wiring.
2. **Hardware/empirical risks (spec §6, validate on a real set):**
   - (a) return-track routing for 16 stems → 4 deck buses behaving as clean
     per-deck EQ/filter/cue;
   - (b) warp-marker fidelity at global tempo ±6–8% off a clip's native BPM
     (breakbeat smear) — may revisit the deferred `applyCurationV2Clip` warp markers;
   - (d) CPU with 16 warped stereo stems + 4 return chains.
3. **taste `export-load`** emitter (writes the §5 manifest) — separate project.

---

## Environment notes / gotchas

- The harness shell cwd resets to `~/zacharysbrown/stemforge` between commands —
  use absolute paths or `cd` at the start of each command for the setforge clone.
- Always use `uv run --extra all` / `uv sync --extra all` to avoid venv drift
  (narrow extras prune fastapi/beat-this).
- JS dual-location sync is enforced by a test: edits to `v0/src/m4l-js/*.js` MUST
  be mirrored to `v0/src/m4l-package/StemForge/javascript/`. `sf_deploy.py` does this.
- Rebuild `.amxd` before any PR (project rule), even though JS-only changes leave it
  byte-identical.
- Run JS tests with `node tests/js_mocks/test_<name>.test.js`.

---

## Quick verification

```bash
cd /Users/zak/zacharysbrown/setforge
git log --oneline -2                                   # e4adfb5, 533b72c
node tests/js_mocks/test_deck_loader.test.js           # 11 pass
for f in tests/js_mocks/test_*.test.js; do node "$f" >/dev/null 2>&1 \
  && echo "PASS $(basename $f)" || echo "FAIL $(basename $f)"; done
```
