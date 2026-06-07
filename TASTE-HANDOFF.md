# taste → setforge handoff

What the **taste** project (the recommender/curator, at `/Users/zak/zacharysbrown/taste`)
has produced for the **setforge** 4-deck performance loader, where it lives, the
manifest contract, and — most importantly — the **BPM/downbeat accuracy caveat**
the loader/warp work needs to handle. Pairs with `SETFORGE-LOADER-SPEC.md` (that
doc is the loader spec; this doc is "what taste emits to feed it").

_As of 2026-05-24. Reconstructed from the build; verify paths before depending on them._

---

## 1. TL;DR for the loader workstream

- taste emits **deck manifests** (one JSON per deck per set) in the format the
  loader already reads (`audio_path`, `song.color_hue` — confirmed against
  `v0/src/m4l-package/StemForge/javascript/stemforge_loader.v0.js`).
- **Two loadable setlists exist right now**: a generic 5×4, and a themed
  hip-hop 5×4. IDM + ambient crates are **stemmed but manifests not emitted yet**.
- Stems are **demucs 4-stem** (drums/bass/vocals/other), **44.1 kHz stereo WAV**,
  produced by `stemforge split --no-slice`.
- ⚠️ **The auto-detected downbeat is only ±40–105 ms accurate** (≈10% of a beat).
  Tempo-matching locks; downbeat does **not** lock tightly — a beat-match test
  flammed by ~65 ms. The loader/warp side must not assume sample-accurate
  downbeats from these manifests. See §5.

---

## 2. What's ready right now

| Setlist | Manifests | Stems root | Status |
|---|---|---|---|
| **Generic 5×4** | `taste/setlist_out/manifests/` — `set1_A.json … set5_D.json` (20) | `taste/setlist_out/stems/<track_id>/` | ✅ all 20 valid, all stems present |
| **Hip-hop** | `taste/setlist_out/hiphop/manifests/` — `hiphop_set1_A.json … hiphop_set5_D.json` (20) | `~/.cache/setforge/stems/<track_id>/` | ✅ all 20 valid; tempo per-set loose on Set 3 |
| **IDM / score / vocals** | — | `~/.cache/setforge/stems/` | stemmed (19), manifests **not emitted** |
| **Ambient** | — | `~/.cache/setforge/stems/` | stemmed (17), manifests **not emitted** |

Note the **two different stem roots** (the 5×4 predates the persistent cache).
Every manifest references its stems by **absolute `audio_path`**, so the loader
doesn't need to know which root — just read the path.

`tracklist.md` sits one level above each themed `manifests/` dir (human-readable
deck order + transitions).

---

## 3. The manifest contract (what taste writes, loader reads)

One file = one deck load. `rows: 1` (one clip per stem, scene 0).

```json
{
  "version": 1,
  "deck": "A",                       // A|B|C|D
  "rows": 1,
  "song": { "name": "Dr. Dre, Snoop Dogg - Still D.R.E.", "color_hue": 0.417 },
  "bpm": 93.5,
  "stems": {
    "drums":  { "clips": [ { "slot": 0, "audio_path": "/abs/.../drums.wav"  } ] },
    "bass":   { "clips": [ { "slot": 0, "audio_path": "/abs/.../bass.wav"   } ] },
    "vocals": { "clips": [ { "slot": 0, "audio_path": "/abs/.../vocals.wav" } ] },
    "other":  { "clips": [ { "slot": 0, "audio_path": "/abs/.../other.wav"  } ] }
  }
}
```

- Field names match the live loader: **`audio_path`** (not `wav_path`),
  **`song.color_hue`** (0–1, key-coded: Camelot number → hue). The older
  `SETFORGE-LOADER-SPEC.md` §5 said `wav_path` — **superseded; use `audio_path`.**
- A full set = the 4 manifests sharing a set number (e.g. `*_set1_{A,B,C,D}.json`)
  → decks A/B/C/D.
- `bpm` is per-clip native tempo (informational per the spec, but warp uses it —
  see §5). **There is no downbeat field in the manifest** (the loader relies on
  clip warp markers + global tempo). taste stores downbeat separately (§5).

To load Set 1 of hip-hop: feed `loadDeck()` the four
`taste/setlist_out/hiphop/manifests/hiphop_set1_{A,B,C,D}.json`.

---

## 4. Stems

- Produced by `stemforge split --no-slice` (this repo's `.venv`), htdemucs,
  4 stems: `drums.wav bass.wav vocals.wav other.wav`.
- **44100 Hz, stereo, 24-bit PCM WAV**, full-length (not sliced/looped).
- Layout: `<stem_root>/<track_id>/{drums,bass,vocals,other}.wav` (flat).
- `stems.json` sits beside them with stemforge's `bpm`, `beat_count`, and
  per-stem `first_downbeat_sec`.

---

## 5. ⚠️ BPM + downbeat accuracy — read this

taste stores stemforge's tempo + downbeat per track (`stem_bpm`,
`stem_downbeat` columns in `taste/setforge.db`; 59 tracks so far). Findings from
real audio:

**Tempo (BPM):** mostly good, but **octave errors persist** on some tracks
(e.g. Notorious B.I.G. *Big Poppa* read 169 ≈ true ~84; *Black Beatles* read 73
≈ true ~145). stemforge's detector beats librosa but is not octave-reliable.
Consequence: a manifest `bpm` may be 2× or ½× the musical tempo. The loader's
warp uses bpm, so an octave-wrong bpm warps the clip to double/half speed at a
given global tempo. **Recommend: validate/repair bpm octave on load** (fold to a
sane band, or trust the user's global tempo + half/double matching).

**Downbeat:** auto `first_downbeat_sec` is only **±40–105 ms accurate**. A
controlled beat-match test (Still D.R.E. × The Next Episode, both stretched to
94 BPM, aligned on detected downbeats) **locked on tempo** (dominant pulse 640 ms
vs 638 ms expected) but the two kicks were **~65 ms apart (≈10% of a beat)** — an
audible flam, not a tight unison. Files: `taste/setlist_out/hiphop/beatmatch/`.

**Implication for the loader:** do not assume these manifests give
sample-accurate bar-1 alignment. For tight simultaneous-deck play you need
better downbeats. Two fixes identified (not yet applied):
1. **Kick-snap (cheap, automatic):** align each clip to the first strong
   transient in its `drums.wav` — sample-accurate for drum stems, pulls the
   error under ~20 ms. taste can fold this into stem emission and could add a
   `downbeat`/offset to the manifest if the loader wants it.
2. **stemforge `re-anchor`** per track (`probe_loop.py` + `--first-downbeat`) —
   manual, precise.

Decide on the taste side vs loader side who owns downbeat correction; right now
**neither does** — that's the main open gap.

---

## 6. How taste regenerates these (so the workstream can re-emit)

From `/Users/zak/zacharysbrown` (taste runs as the `taste` package):

```bash
# build/stem a generic N×4 set (select → stemforge split → manifests)
python -m taste.cli setlist --out setlist_out --sets 5

# stem a backlog of specific tracks (stores stem_bpm + stem_downbeat in the DB)
python -m taste.cli stem --ids-file taste/crates/stem_backlog.txt

# themed manifests are emitted by taste.setlist.emit_theme(conn, theme, ids, out_root)
#   (hip-hop done; IDM + ambient pending)
```

Curated theme backlogs (the source lists): `taste/crates/{1_hiphop,2_idm_score_vocals,3_ambient}.md`.

---

## 7. Open items / asks for the setforge workstream

1. **Downbeat correction** — agree on owner (§5). Without it, decks beat-match on
   tempo but flam by ~65 ms.
2. **BPM octave repair** on load (§5) — some manifest `bpm`s are half/double.
3. **`audio_path` is absolute** and points at a user-local cache
   (`~/.cache/setforge/stems`, `taste/setlist_out/stems`). If the loader runs on
   a different machine/path, these need rewriting — flag if so.
4. **IDM + ambient manifests** aren't emitted yet (stems exist). Say the word and
   taste emits them like hip-hop.
5. Confirm the loader is happy with **full-length stems** (not pre-looped) +
   `warping: 1` riding the global tempo, given the loose downbeats.
