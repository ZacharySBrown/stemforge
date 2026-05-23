# setforge — 4-Deck Performance Loader

## Status
Draft — awaiting review

## Problem

We want a **live stem-DJing layout**: four song "decks" (A/B/C/D) playable
simultaneously, two decks per Launchpad (8 columns = 2 decks × 4 stems). A
recommender (taste, a separate project) picks the next song and emits a load
request; setforge loads that song's four stems into one chosen deck **without
disturbing the other three decks that are still playing**.

This is a **new load mode**, additive to the existing loader. The existing
production/curation loaders *append* fresh tracks per song and the user prunes
old ones by hand. A performance set can't tolerate that — it needs **four fixed,
persistent deck lanes whose clips are reloaded in place.**

## Context

### What exists today (v0 loader — `v0/src/m4l-js/stemforge_loader.v0.js`)

The build target is the **v0 loader** (the live device), not the legacy
`m4l/stemforge_loader.js` the original spec was grounded against. Reusable
primitives already present:

- `loadClip(trackIdx, slotIdx, wavPath, clipName, startMarkerBeats)`
  ([loader:258](../../v0/src/m4l-js/stemforge_loader.v0.js#L258)) — **already
  does reload-in-place**: deletes any clip in the slot, calls
  `create_audio_clip`, *probes the clip handle to confirm it landed* (guards the
  silent-failure mode where `create_audio_clip` doesn't throw on a bad path),
  then sets `warping=1`, `looping=1`, `name`. This is almost exactly the spec's
  §4 pseudocode body — setforge does **not** need to reimplement it.
- `findTrackByName(name)` ([loader:224](../../v0/src/m4l-js/stemforge_loader.v0.js#L224))
  — linear scan, name→index, recomputed every call. Honors the spec's
  "address by name, never by cached index" rule.
- `ensureScenes(n)` ([loader:815](../../v0/src/m4l-js/stemforge_loader.v0.js#L815))
  — creates scenes until `>= n` exist. Reusable as-is for `rows`.
- `parseColor(c)` ([loader:1099](../../v0/src/m4l-js/stemforge_loader.v0.js#L1099))
  — int / `#hex` / `{hex}` → Live color int. Does **not** handle a `0..1` hue.
- `loadFromDict()` ([loader:745](../../v0/src/m4l-js/stemforge_loader.v0.js#L745))
  — the Dict-based entry the device actually uses (manifest passed via a Max
  `[dict]`, not a path). `loadManifest()` is the path-based sibling.
- `applyCurationV2Clip(clipApi, loopEntry, stemName)`
  ([loader:314](../../v0/src/m4l-js/stemforge_loader.v0.js#L314)) — applies warp
  markers + bar offsets so a clip plays correctly at session BPM.

### The collision worth knowing about: there is *already* an A/B/C/D deck model

`_restoreSessionTracks(mf, stemData)`
([loader:1510](../../v0/src/m4l-js/stemforge_loader.v0.js#L1510)) restores a
`session_tracks = {A:[...], B:[...], C:[...], D:[...]}` block written by COMMIT.
That model is **structurally different** from the setforge spec:

| | existing `session_tracks` | setforge spec |
|---|---|---|
| Tracks per deck | **1** track named `"A"` | **4** tracks named `"A-d" "A-b" "A-v" "A-o"` |
| What a slot holds | any stem's bar (mixed) | one stem, one variation |
| Track lookup | `findTrackByName("A")` | `findTrackByName("A-d")` |
| Purpose | save/restore session for edit + export | live performance reload |

These don't collide at the string level (`"A"` ≠ `"A-d"`), so they can coexist
in one set. But two "A/B/C/D" concepts in one file is a real comprehension
hazard — the design must name setforge's pieces unambiguously and document the
distinction so a future reader doesn't wire COMMIT into the performance lanes.

### Manifest field-name reality

The spec proposes `stems.<name>.clips[].wav_path`. In the v0 world:

- Curation manifests (the most likely producer) use a **flat `clips[]`** array
  with `stem`, **`audio_path`**, `source_bar_range`, `clip_id`
  ([loader:565](../../v0/src/m4l-js/stemforge_loader.v0.js#L565)).
- Production manifests use `stems[].wav_path`
  ([loader:699](../../v0/src/m4l-js/stemforge_loader.v0.js#L699)).
- EP-133 `SampleMeta` uses `file` (`stemforge/manifest_schema.py`).

So "the code wins, reconcile" cuts toward **`audio_path`** if taste mirrors the
curation shape, or `wav_path` if it mirrors production. This is a contract
decision (Open Question 1).

### Zones

- **M4L (primary):** new `loadDeck` + a `hueToLiveColor` helper in
  `stemforge_loader.v0.js` (and the byte-identical package mirror at
  `v0/src/m4l-package/StemForge/javascript/stemforge_loader.v0.js`).
- **Core (contract only):** the deck-manifest schema. taste produces it; taste
  internals are out of scope (separate project). No Core code change is required
  to *consume* it in M4L.
- **Tools:** none.

This respects the zone model: Core/taste → M4L is one-way via a manifest.

## Proposed Approach

### 1. Layout (CONFIG, user builds once)

16 flat audio tracks + the source track, per spec §3:

```
0:  SF | Source     (hosts the loader; never touched)
1-4:   A-d A-b A-v A-o
5-8:   B-d B-b B-v B-o
9-12:  C-d C-b C-v C-o
13-16: D-d D-b D-v D-o
```

Per-deck processing (EQ/filter/cue) via four **return tracks** `RET-A..RET-D`
the stem tracks route to — groups are impossible (M4L can't create a track
inside a group). All CONFIG, not loader code. The loader only writes the 16
named stem tracks' clip slots; it never creates/deletes tracks and never touches
track 0.

### 2. `loadDeck` — thin orchestration over `loadClip`

Because `loadClip` already does delete→create→probe→warp/loop/name, `loadDeck`
is small:

```javascript
function loadDeck(manifest) {
    var deck  = manifest.deck;                 // "A".."D"
    var rows  = manifest.rows;                 // 1 | 2 | 4
    var color = hueToLiveColor(manifest.song.color_hue);
    var stems = ["d", "b", "v", "o"];
    var key   = { d:"drums", b:"bass", v:"vocals", o:"other" };

    if (!validateDeckPaths(manifest)) { status("missing files, aborted"); return; }
    ensureScenes(rows);

    for (var i = 0; i < stems.length; i++) {
        var trackName = deck + "-" + stems[i];          // "A-d"
        var t = findTrackByName(trackName);
        if (t < 0) { status("no track " + trackName); return; }
        var clips = manifest.stems[key[stems[i]]].clips; // length == rows

        for (var s = 0; s < rows; s++) {
            var name = manifest.song.name + " " + stems[i] + " v" + s;
            if (!loadClip(t, s, clips[s].audio_path, name)) continue;  // reload-in-place built in
            try {
                var clip = new LiveAPI(
                    "live_set tracks " + t + " clip_slots " + s + " clip");
                clip.set("color", color);   // color the CLIP → Launchpad mirrors it
            } catch (_) {}
        }
    }
    status("Deck " + deck + " <- " + manifest.song.name);
}
```

Decisions baked in:
- **Validate-all-before-mutate.** `validateDeckPaths` checks every
  `audio_path` exists before any slot is touched, so a bad manifest can't
  half-load a live deck.
- **Reuse `loadClip`, don't fork it.** Reload-in-place, the silent-failure probe,
  and warp/loop/name are already battle-tested there. setforge only adds clip
  color afterward.
- **Color the clip, not the track** (spec §4) — the Launchpad mirrors clip color.
- **`for (s = 0; s < rows; s++)`** from day one, so rows 2/4 are config, not new
  code (spec §2).

### 3. Dispatch & data source

Mirror the existing pair:
- **`loadDeckFromDict()`** — production entry; manifest arrives in a Max `[dict]`
  (same plumbing as `loadFromDict`). This is what the device/taste wires.
- **`loadDeck` core** takes the parsed object so tests call it directly.

A `hueToLiveColor(hue)` helper converts the spec's `color_hue` (0..1) to a Live
color int (HSV→RGB at full S/V), sitting beside `parseColor`.

### 4. Manifest contract (taste → setforge)

Per spec §5, reconciled to v0 field names (pending Open Question 1):

```json
{
  "version": 1,
  "deck": "A",
  "rows": 1,
  "song": { "name": "Squarepusher - Beep Street", "color_hue": 0.62 },
  "bpm": 137.0,
  "stems": {
    "drums":  { "clips": [ { "slot": 0, "audio_path": "/.../A_drums_v0.wav" } ] },
    "bass":   { "clips": [ { "slot": 0, "audio_path": "/.../A_bass_v0.wav"  } ] },
    "vocals": { "clips": [ { "slot": 0, "audio_path": "/.../A_vocals_v0.wav"} ] },
    "other":  { "clips": [ { "slot": 0, "audio_path": "/.../A_other_v0.wav" } ] }
  }
}
```

- `stems.<name>.clips` length MUST equal `rows`; `clips[s].slot == s`.
- `bpm` informational (global tempo is rider-controlled); `warping=1` rides it.
- This is a **new, separate** schema from `session_tracks` and from the
  production manifest. It does **not** modify `stems.json` / the existing
  manifest contract — it's a parallel performance-load contract.

### 5. Build order (spec §6, each step independently testable)

1. `loadDeck` for `rows=1`, deck A, one fixture manifest. Add
   `tests/js_mocks/test_deck_loader.test.js`.
2. Reload-in-place: load A twice, assert no duplicate clips.
3. All four decks isolated: load C, assert A still playing/intact.
4. Generalize `rows` → 2 then 4 (manifest carries 2/4 clips; loop already
   handles it; assert scenes auto-created).
5. Wire taste `export-load` to emit the §4 manifest (separate task/project).

### 6. Test strategy

Two existing patterns to model on:
- **`test_loader_dispatch.test.js`** — static source assertions (function exists,
  routes correctly, src ≡ package mirror). Cheap; use for dispatch + dual-location
  sync.
- **`test_arrangement_loader.test.js`** — loads the loader into the LiveAPI
  sandbox (`tests/js_mocks/sandbox.js` + `max_api.js`) and exercises real clip
  placement. Use for the behavioral tests (4 clips land, reload replaces,
  isolation, scene count).

Hard requirement (CLAUDE.md "JS Dual Location Sync"): after every edit, mirror
`v0/src/m4l-js/...` → `v0/src/m4l-package/StemForge/javascript/...` byte-for-byte
and rebuild the `.amxd` before any PR.

## Alternatives Considered

### Alt A — Extend the existing `session_tracks` model instead of a new 16-track layout
Reuse `_restoreSessionTracks`' 4-track A/B/C/D lanes for performance.
- **Pro:** one deck concept in the file; reuses warp/offset restore directly.
- **Con:** the 4-track model mixes all stems into one track's slots — you can't
  fade/EQ/cue *drums of deck A* independently, which is the whole point of
  per-stem decks for stem-DJing. It also entangles performance loading with the
  COMMIT/export round-trip (different lifecycle, different writer). **Rejected**
  — the layouts serve genuinely different goals; conflating them couples two
  unrelated flows.

### Alt B — Fork a dedicated `loadDeckClip` instead of reusing `loadClip`
Write a performance-specific clip loader.
- **Pro:** total control; no risk of a `loadClip` change leaking into perf mode.
- **Con:** duplicates the hard-won silent-failure probe and reload-in-place
  logic; two code paths drift. **Rejected** — `loadClip` is already the right
  shape; setforge layers color on top.

### Alt C — Generalize `loadClip` to take an optional `color` argument
Add `color` as a 6th param to `loadClip` so `loadDeck` is a one-liner.
- **Pro:** marginally less code in `loadDeck`.
- **Con:** widens a function shared by the production/curation paths for a
  perf-only need; risks behavior change in those callers. **Deferred** — set
  color in `loadDeck` after `loadClip` returns; revisit only if a second caller
  wants per-clip color.

## Acceptance Criteria

- [ ] `loadDeck(manifest)` with `rows=1`, deck A places 4 clips in A-d/A-b/A-v/A-o
      scene 0, each warped, looped, named, and colored from `song.color_hue`.
- [ ] `loadDeckFromDict()` exists and routes a `[dict]` manifest to `loadDeck`.
- [ ] Reloading a deck replaces clips in place — no duplicates, no stale clips.
- [ ] Loading one deck leaves the other three decks' clips untouched.
- [ ] `rows` 2 and 4 work with no loop changes; scenes auto-created via `ensureScenes`.
- [ ] A manifest with any missing `audio_path` aborts before mutating the session
      and surfaces a clear status.
- [ ] Track 0 / `SF | Source` is never read or written; no track is created/deleted.
- [ ] `test_deck_loader.test.js` passes; src and package copies stay byte-identical;
      `.amxd` rebuilt.

## Open Questions

- [ ] **1 — Manifest audio-path field name: `audio_path` vs `wav_path`.** taste
      hasn't been written yet, so we choose the contract. `audio_path` matches the
      curation `clips[]` shape (the closest existing producer); `wav_path` matches
      production stems and the original spec. **Recommend `audio_path`.** Needs a
      human call — it's the cross-project contract with taste.
- [ ] **2 — Coexistence with `session_tracks`.** Do we leave both A/B/C/D models
      in place indefinitely, or is the performance layout meant to eventually
      supersede the COMMIT lanes? Affects naming and how loudly we document the
      distinction. Needs human intent.
- [ ] **3 — Warp fidelity at off-tempo (spec §6b).** Deck clips ride global tempo
      ±6–8% off native BPM. Do we reuse `applyCurationV2Clip`'s warp markers when
      the manifest carries them, or trust `warping=1` alone? Recommend: optional —
      apply markers if present, else plain warp. Verify on hardware before step 5.
- [ ] **4 — Return-track routing (spec §6a) and CPU (§6d)** are CONFIG/empirical,
      not code, but should be validated by step 3, not discovered at step 5.
