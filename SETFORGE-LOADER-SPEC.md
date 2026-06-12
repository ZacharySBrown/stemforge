# setforge — 4-Deck Performance Loader: Claude Code Handoff Spec

**Target repo:** `stemforge` (extends the existing M4L loader; does not replace it)
**Audience:** Claude Code, working locally against the real source.
**Status of this doc:** grounded in a read of `m4l/stemforge_loader.js`,
`m4l/stemforge_lom.js`, `specs/stemforge_song_loader.md`,
`specs/stemforge_song_loader_UPDATE.md`, and `specs/manifest-spec.md` as of the
current `main`. Where this doc and the live code disagree, **the code wins** —
reconcile and tell me.

---

## 0. What we're building and why

A performance layout for live stem-DJing: **4 song "decks" (A/B/C/D)** playable
simultaneously, two decks per Launchpad (8 columns = 2 decks × 4 stems). Each
deck is **4 flat audio tracks** — one per stem — named so the loader addresses
them by name, never by index. taste (the recommender, separate project) picks
the next song and emits a load request; setforge (this loader + the Ableton set)
loads that song's stems into a chosen deck, leaving the other three untouched
and still playing.

This is a NEW load mode alongside the existing song-loader, not a rewrite. The
existing loader appends a fresh 5-track set per song and the user deletes old
ones manually. The performance loader instead **reuses four fixed, persistent
deck lanes and reloads clips into them in place.**

---

## 1. What already exists (reuse, do not reinvent)

From `m4l/stemforge_loader.js` — these work and are the building blocks:

- `loadManifest(manifestPath)` — reads a manifest, walks tracks/slots.
- **`create_audio_clip` by path works**: line ~203 does
  `csAPI.call("create_audio_clip", String(stemInfo.wav_path))` on a
  `live_set tracks T clip_slots S` LiveAPI. **This is the load primitive.**
  (Note: this contradicts old community lore that the LOM can't load audio —
  in this Live version it can. Keep using it.)
- `findTrackByName(name)` — linear scan, returns index. **This is how we honor
  the "address by name, not index" rule** and sidesteps the group/index-shift
  problem entirely.
- `findTrackBySuffix(stemName)`, `findEmptyClipSlot(trackIndex)`.
- `setBPM(bpm)`, `setTrackName`, `setTrackColor(trackIndex, color)`.
- `getTrackCount()`, `duplicateTemplate()`, `applyEffects(trackIndex, effects)`.

**Known constraint (README limitation #1, confirmed):** the M4L device **cannot
create tracks inside a group** — `create_*_track` inserts adjacent to the
selected track, not into a group. **Therefore the performance layout is FLAT —
no Session groups.** See §3 for how we get per-deck processing without groups.

---

## 2. The deck/stem/scene addressing model

**Track naming (exact, the loader matches on these):**

```
A-d  A-b  A-v  A-o    B-d  B-b  B-v  B-o    C-d C-b C-v C-o   D-d D-b D-v D-o
└──── DECK A ────┘    └──── DECK B ────┘    └─ DECK C ─┘      └─ DECK D ─┘
 drums bass vox other  (same pattern)        (grid 2)          (grid 2)
```

- Deck ∈ {A,B,C,D}. Stem ∈ {d,b,v,o} = {drums,bass,vocals,other}.
- Track name = `"<DECK>-<stem>"` e.g. `"A-d"`. Loader resolves via
  `findTrackByName` every call (never caches indices — indices shift).
- **Grid mapping:** Launchpad 1 window = tracks for decks A+B (8 columns),
  Launchpad 2 window = decks C+D. Pin each controller's 8×8 window; do not
  scroll mid-set. (Controller config, not code — out of scope for this spec,
  noted for completeness.)

**Scene depth (the 1×4 / 2×4 / 4×4 generalization):**
- A deck occupies `rows` scenes (1, 2, or 4). For `rows=1`, each stem has one
  clip in scene 0. For `rows=2`, two variations per stem in scenes 0–1, etc.
- **Build for `rows=1` first.** Write every loop over scenes as
  `for (s = 0; s < rows; s++)` so 2 and 4 are config, not new code.
- The manifest provides `rows` and a clip list per stem of length `rows`.

---

## 3. Session layout (CONFIG — user builds once, loader assumes it)

16 flat audio tracks, named per §2, plus the persistent source track:

```
0:  SF | Source            (hosts the loader device; never touched)
1:  A-d   2: A-b   3: A-v   4: A-o
5:  B-d   6: B-b   7: B-v   8: B-o
9:  C-d  10: C-b  11: C-v  12: C-o
13: D-d  14: D-b  15: D-v  16: D-o
```

**Per-deck processing without groups** (since we can't group): each deck's 4
stem tracks route to a dedicated **return track** (or an audio bus track) that
carries the deck's EQ Three + Auto Filter + cue. Four returns: `RET-A`..`RET-D`.
Set each stem track's output to its deck return. The return is what you
EQ/filter/cue as a unit — same function as a group, no group container.
Alternatively (simpler, more CPU): put a macro-mapped EQ+Filter rack on each of
the 16 tracks and group the macros via a control surface. **Recommend the
return-track approach.** Either way: **CONFIG, not loader code.** The loader
only touches the 16 named stem tracks' clip slots.

**Cue/preview:** Master out = 1/2, Cue out = 3/4 → master "Cue" switch active →
per-return headphone button auditions a deck pre-fader. Native, no code.

---

## 4. The load operation (the BUILD)

New function, e.g. `loadDeck(manifest)`. Pseudocode, reusing existing helpers:

```javascript
function loadDeck(manifest) {
    var deck = manifest.deck;            // "A".."D"
    var rows = manifest.rows;            // 1 | 2 | 4
    var color = hueToLiveColor(manifest.color_hue);
    var stems = ["d","b","v","o"];
    var stemKey = {d:"drums", b:"bass", v:"vocals", o:"other"};

    // validate all paths exist BEFORE touching the session (existing pattern)
    if (!validatePaths(manifest)) { status("missing files, aborted"); return; }

    for (var i = 0; i < stems.length; i++) {
        var trackName = deck + "-" + stems[i];           // e.g. "A-d"
        var trackIndex = findTrackByName(trackName);     // name -> index, fresh
        if (trackIndex < 0) { status("no track " + trackName); return; }

        var clips = manifest.stems[stemKey[stems[i]]].clips; // length == rows
        ensureScenes(rows);                              // create scenes if <rows

        for (var s = 0; s < rows; s++) {
            var csPath = "live_set tracks " + trackIndex + " clip_slots " + s;
            var cs = new LiveAPI(csPath);
            if (cs.get("has_clip") == 1) {               // reload-in-place
                cs.call("delete_clip");
            }
            cs.call("create_audio_clip", String(clips[s].wav_path));  // PROVEN primitive
            var clip = new LiveAPI(csPath + " clip");
            clip.set("warping", 1);
            clip.set("looping", 1);
            clip.set("name", manifest.song.name + " " + stems[i] + " v" + s);
            // color the CLIP so the Launchpad pad shows the deck color
            clip.set("color", color);
        }
    }
    status("Deck " + deck + " <- " + manifest.song.name);
}
```

Key points for Claude Code:
- **Reload-in-place**: delete existing clip before create (decks are reused, not
  appended). This is the difference from the existing append-style loader.
- **Color the clip, not the track** — the Launchpad mirrors *clip* color on the
  pads, which is the per-song color coding the user wants.
- **Warp markers**: stemforge already pre-warps/exports; the manifest's BPM and
  the clip's `warping=1` should be enough. If clips drift at non-native global
  tempo, that's the warp-marker fidelity risk — verify, see §6.
- `ensureScenes(rows)` — adapt from the existing "create scenes if needed" note
  in the song-loader spec (session must have ≥`rows` scenes).
- Do NOT touch track 0 / `SF | Source`. Do NOT create or delete tracks — the 16
  deck tracks are persistent; only clips change.

---

## 5. The manifest contract (taste → setforge)

taste emits this; the loader consumes it. Mirror the existing manifest style
(`specs/manifest-spec.md`) but add `deck` and `rows`. Proposed schema — reconcile
field names with the real `stemforge/manifest_schema.py` (e.g. it uses
`wav_path`; keep that):

```json
{
  "version": 1,
  "deck": "A",
  "rows": 1,
  "song": { "name": "Squarepusher - Beep Street", "color_hue": 0.62 },
  "bpm": 137.0,
  "stems": {
    "drums":  { "clips": [ { "slot": 0, "wav_path": "/.../A_drums_v0.wav" } ] },
    "bass":   { "clips": [ { "slot": 0, "wav_path": "/.../A_bass_v0.wav"  } ] },
    "vocals": { "clips": [ { "slot": 0, "wav_path": "/.../A_vocals_v0.wav"} ] },
    "other":  { "clips": [ { "slot": 0, "wav_path": "/.../A_other_v0.wav" } ] }
  }
}
```

- `stems.<name>.clips` length MUST equal `rows`; slot index = scene index.
- `bpm` is informational for the loader (global tempo is rider-controlled);
  used to validate/repair warp if needed.
- taste already has `wav_path`s in its DB (the local-analysis paths). A new
  taste command `taste export-load --track <id> --deck A --rows 1` writes this
  JSON. (taste side is a separate task; this spec only defines the contract.)

---

## 6. Build order & acceptance

**Build in this order; each step independently testable:**

1. **`loadDeck` for `rows=1`, one hardcoded manifest, deck A.** Confirm 4 clips
   land in A-d/A-b/A-v/A-o scene 0, warped, looped, colored. Use the existing
   JS mock test harness (`tests/js_mocks/`) — there's already
   `test_arrangement_loader.test.js` and `test_loader_dispatch.test.js` to model
   on. Add `test_deck_loader.test.js`.
2. **Reload-in-place**: load deck A twice with different songs; confirm no
   duplicate clips, old clips replaced cleanly.
3. **All four decks**: load A, B, C, D independently; confirm each is isolated
   (loading C doesn't disturb A playing).
4. **Generalize `rows` → 2, then 4.** Manifest carries 2/4 clips per stem; loop
   already handles it. Confirm scenes auto-created.
5. **Wire taste `export-load`** to emit the §5 manifest from its DB.

**Acceptance:** With A, B playing simultaneously through their return-track
processing and cued independently, load a new song into deck C from a taste
manifest, preview C on the cue mix, then bring it in — without interrupting A/B.
Round-trip reload of any deck leaves no stale clips.

**Risks to validate early (don't discover these at step 5):**
- **a. Return-track routing for 16 stems → 4 deck buses** behaves as a clean
  per-deck EQ/filter/cue. If returns fight you, fall back to per-track racks.
- **b. Warp-marker fidelity** when riding global tempo ±6–8% off a clip's native
  BPM (the breakbeat-smear risk). Spot-check two decks at offset tempo.
- **c. `create_audio_clip` + immediate `clip.set("warping",1)`** timing — LOM
  calls can race; the existing loader may already handle this, check before
  adding defensive delays.
- **d. CPU**: 16 warped stereo stems + 4 return chains playing at once on the
  real machine.

---

## 7. Explicit non-goals / out of scope

- Controller mapping / window-pinning (Launchpad config, done in Live UI).
- taste's recommender internals (separate project; only the manifest contract
  is shared).
- Group containers (impossible per the create-in-group constraint; returns
  replace them).
- Tempo automation / auto-sync — the human rides global tempo manually.
- Anything touching `SF | Source` or the existing append-style song loader’s
  behavior — this is additive.
