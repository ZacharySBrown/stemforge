# Verse-Swap Deck — Execution Plan

**Goal.** A hip-hop mixtape deck on the EP-133 with **24 full verse vocal pads**
(2 verses × 12 source songs) on Groups A + B, **drum breaks/oneshots** on
Group C, and **bass/synth/texture samples** on Group D. Memory budget fits
inside the 64 MB device cap.

**Status.** Plan only; not yet implemented. Target the smallest path through
v4 that lets the user perform from this deck.

**Spec anchors.** v4 Decision 16 (per-group format), Decision 12 (Workflow B
single-scene kit), Decision 13 (clip identity by `audio_hash`), Decision 14
(pad canvas as slot table). Phase 3.5/3.6 (Koala/Chompi) and Phase 4.7/4.8
(splice editor + multi-target export) are explicitly out of scope here.

---

## Reality check before we start (read this)

The v4 Decision 16 motivating math is mildly misleading for EP-133
specifically. EP-133 is **always** mono / 16-bit / 46875 Hz on disk —
[stemforge/exporters/ep133/wav_format.py:26-28](stemforge/exporters/ep133/wav_format.py#L26-L28)
hardcodes that, and `convert_wav_to_ep133` always downmixes + resamples
inputs to that format. The "stereo 48 kHz → 94 MB" framing in v4 was
inflated for narrative; the real-world math at EP-133's actual on-disk
format is:

| Profile | Per 42s verse | × 24 verses | Fits in 64 MB? |
|---|---|---|---|
| `preserve_source` (46875 Hz mono 16-bit) | 3.94 MB | 94.5 MB | **No** |
| `vocal` (23437 Hz mono 16-bit, half rate) | 1.97 MB | 47.3 MB | Yes, with ~17 MB of headroom for groups C+D |
| `vocal-tight` (16000 Hz mono 16-bit) | 1.34 MB | 32.3 MB | Yes, with ~32 MB of headroom |

**Conclusion:** the *channel* and *bit-depth* axes of Decision 16 are no-ops
on EP-133 (already locked). The lever that matters here is **sample rate
downsampling**. Plan accordingly: ship sample-rate-per-group as the v1
hardware-constrained surface, treat channels/bit-depth as forward-looking
hooks for Koala / Chompi / future targets.

---

## What ships (two slices)

> **Update 2026-05-08:** the user is hand-curating source material in Live
> (one song broken into two verses + 2-3 chunks per other section,
> scaled across the corpus). **Slice 3 (verse-extraction CLI) drops** —
> the user produces curated WAVs upstream and the deck-builder doesn't
> need a verse-trimmer.

### Slice 1 — Per-group sample rate + memory budget (Decision 16, EP-133-only edition)

**Outcome:** the projector can produce a `.ppak` where Group A and B
samples are downsampled to 24 kHz while Group C and D stay at the device
default. Memory budget is computed pre-export and surfaces as a warning
when the project exceeds 64 MB.

Concrete commits:

1. **Schema add** — extend
   [stemforge/scene_model/schema.py:57-62](stemforge/scene_model/schema.py#L57-L62)
   so `GroupSpec` carries `format_profile: Literal["vocal", "drum",
   "texture", "preserve_source"] = "preserve_source"`. Defaults preserve
   today's behavior. No optional `format` override yet — keep the surface
   tight; add it when a real workflow asks for it.

2. **Profile resolver** — new `stemforge/scene_model/format_profiles.py`
   mapping each profile to a concrete `(target_rate, channels, bit_depth)`.
   For Slice 1 only `target_rate` differs (24 kHz / 23437 Hz for vocal,
   46875 Hz for everything else). Pure function; trivial to test.

3. **WAV writer parameterization** — add `target_sample_rate: int |
   None = None` to
   [convert_wav_to_ep133](stemforge/exporters/ep133/wav_format.py#L43);
   when `None`, default to `EP133_SAMPLE_RATE` (today's behavior). The
   `_build_ep133_wav` and `byte_rate` math need to use the actual rate,
   not the constant — small, surgical edit. Existing byte-identity test
   (`test_song_export_parity`) stays green because the default path is
   unchanged.

4. **Projector wiring** — `synthesize` / `build_ppak` need to thread the
   per-group rate into
   [ppak_writer.py:297](stemforge/exporters/ep133/ppak_writer.py#L297)'s
   `convert_wav_to_ep133` call. Lookup by group letter. The `project_from_spec`
   path already knows the `Project` and can read each `GroupSpec.format_profile`.

5. **Memory budget calculator** — new function
   `Ep133Projector.estimate_memory_bytes(project) -> int`. Sums each pad's
   `(end - start) seconds × group_rate × 2 bytes`. Pure function over
   `Project` + clip durations from `ClipRef` or manifest.

6. **`validate_spec` extension** — append warning when `estimate_memory_bytes
   > 64 * 1024 * 1024`. Hard threshold; no grace.

7. **Tests:**
   - `test_format_profile_preserve_source_byte_identity` — projecting a
     known fixture with all-`preserve_source` groups produces bytes equal
     to today's output. Locks the migration.
   - `test_format_profile_vocal_downsamples_rate` — projecting one group
     as `vocal` produces a `.ppak` whose extracted WAVs report
     `framerate == 23437` (read with `wave.open`).
   - `test_memory_budget_warns_over_cap` — synthetic 70 MB project surfaces
     the warning; 60 MB project doesn't.
   - `test_format_profile_round_trips_in_serialize` — schema field survives
     JSON round-trip.

**Acceptance:** byte-identity gate stays green; one new test demonstrates
mixed-rate output; memory warning fires deterministically.

**Out of scope for Slice 1:** no UI, no `format` override, no per-pad
format, no Koala/Chompi rate handling.

---

### Slice 2 — Multi-source kit assembly (the deck-builder CLI)

**Outcome:** a deck-shaped `Project` can be built by hand-picking clips
across N forge runs, without going through Live's arrangement view. The
CLI emits a `ProjectSpec` JSON; the projector turns it into a `.ppak`.

This is the workflow piece that **doesn't exist anywhere today**. The
existing `Ep133Projector.project_from_spec` requires a single
`manifest` argument because `synthesize` walks `manifest.session_tracks`
to look up sample slots
([stemforge/exporters/ep133/song_synthesizer.py:1-17](stemforge/exporters/ep133/song_synthesizer.py#L1-L17)).
The verse-swap deck has **12 manifests**; the kit projection path needs
to resolve clips from a federated lookup.

Concrete commits:

1. **Federated clip resolver** — new `stemforge/exporters/ep133/clip_index.py`.
   Given a list of forge directories, builds a
   `dict[audio_hash, (path, manifest_entry)]`. Per Decision 13, this is the
   identity layer; per Phase 2 loose-end #1, today's `audio_hash` is empty
   string at COMMIT time, so this slice also wires hash population at
   resolver build time (compute on demand from file bytes — trivial).

2. **Kit-projection synthesizer path** — new
   `stemforge/exporters/ep133/kit_synthesizer.py`. Mirrors `song_synthesizer.py`
   but consumes `(Project, ClipIndex)` instead of `(snapshots, manifest)`.
   Emits a one-scene `PpakSpec` where every pad is its own pattern (one
   trigger at position 0). Re-uses
   [global_sample_slot()](stemforge/exporters/ep133/song_synthesizer.py#L77)
   for slot allocation — Group A → 700-719, B → 720-739, C → 740-759,
   D → 760-779.

3. **Projector method** — `Ep133Projector.project_kit(project, clip_index,
   *, project_slot, reference_template)` — analogue of `project_from_spec`
   but driven by `kit_synthesizer.synthesize_kit(...)`. Bytes path is
   identical from `PpakSpec` onwards.

4. **CLI: `stemforge build-deck`** — new subcommand. Takes a YAML/JSON
   project plan and a list of forge directories; emits the `ProjectSpec`
   plus the `.ppak`. Plan shape (concrete, simple):

   ```yaml
   project: "verse_swap_deck_v1"
   project_slot: 8
   groups:
     A:
       format_profile: vocal
       pads:
         - {pad: 1, source: "01_hey_mami/curated/manifest.json", clip: "vocals_v1"}
         - {pad: 2, source: "02_benjamins/curated/manifest.json", clip: "vocals_v1"}
         - ... (12 pads)
     B:
       format_profile: vocal
       pads: [... 12 alt verses + hooks ...]
     C:
       format_profile: drum
       pads: [... 12 drum picks ...]
     D:
       format_profile: texture
       pads: [... 12 bass/synth/other ...]
   ```

   The `clip:` selector resolves against the manifest's `session_tracks`
   entries. Naming convention: bar-loop chunks are addressable by stem
   plus bar index (`drums_b3` = 3rd bar of drums stem), or by curated
   slot name. Pick whichever's already canonical; that's a 30-min
   research task before this commit.

5. **Live test on the deck** — the user actually performs from it. This
   is acceptance, not "tests passing."

**Acceptance:** user runs `stemforge build-deck deck.yaml --output verse_swap.ppak`,
loads to project slot 8, plays a 15-minute set without laptop, all 24
vocal pads audible and in tempo, drum/synth pads functional.

**Out of scope for Slice 2:** popup UI, drag-import, audio preview,
HTTP server. The CLI YAML is the editor for now.

---

### (Slice 3 dropped — user-side curation handles verse production)

User-side workflow assumed: hand-curate clips in Live (verses, hooks,
drum picks, bass/synth fragments), COMMIT into a manifest per source
song. The deck-builder operates on those manifests + optionally raw
WAV paths for clips that bypass COMMIT.

**deck.yaml supports two clip-resolution shapes** (both, not pick-one):

```yaml
groups:
  A:
    pads:
      - {pad: 1, source: "01_hey_mami/curated/manifest.json", clip: "vocals_verse_1"}
      - {pad: 2, path: "/Users/zak/Music/hand_curated/02_benjamins/verse_1.wav"}
```

`clip:` resolves through the federated `ClipIndex`; `path:` references
a raw WAV directly (hash computed at build-deck time). Both produce a
`ClipRef` with the same downstream behavior. Trivial to support both;
saves the user from forcing every clip through COMMIT if they don't
want to.

---

## Sequence + critical-path dependencies

```
Slice 1 ──→ Slice 2 ──→ Live performance verification on hardware
```

Slice 1 lands first (byte-identity gate, isolated, testable).
Slice 2 builds on it (needs `format_profile` in the schema).

---

## What I'm explicitly NOT doing in this plan

Per the Phase 3 fresh-session handoff:

- No HTTP server (Phase 3.1) — the CLI is the editor for v0 of this deck.
- No M4L strip device for configurator (Phase 3.2) — existing `forge`
  device stays unchanged.
- No popup UI / pad canvas / inspector (Phase 4) — the YAML deck plan
  is the inspector.
- No Koala/Chompi projectors (Phase 3.5/3.6) — EP-133 only.
- No splice editor (Phase 4.7) — single-scene Workflow B.
- No multi-target export (Phase 4.8) — EP-133 only.
- No per-pad format profile — per-group is the whole surface.

The configurator Phase 3 + 4 work in v4's plan is genuinely useful
**after** this deck ships — at that point you have a real workflow to
test the popup against. Building popup-first risks designing for an
imagined workflow.

---

## Risks specific to this path

**RV1 — `audio_hash` empty at COMMIT.** Phase 2 loose-end. Slice 2's
clip resolver computes hash on demand from file bytes, so this isn't
actually blocking — but it does mean two hashes are generated for the
same content (one in resolver, one when COMMIT eventually wires it up)
unless we standardize on the same helper. **Mitigation:** use
[stemforge/manifest_schema.py:66](stemforge/manifest_schema.py#L66)'s
`compute_audio_hash` everywhere. One place; no drift.

**RV2 — verses' BPM may differ from project BPM.** A hip-hop deck
spans 88-100 BPM across sources. EP-133's per-pad `time.mode: bpm` +
`sound.bpm` handles this — it stretches playback to project tempo.
Each `ClipRef` already carries `source_bpm`; `convert_wav_to_ep133`
already takes `sound_bpm`. Slice 2 just needs to wire the bpm through
from `ClipRef.source_bpm` for each pad. **No new code; just plumbing.**

**RV3 — sample-rate downsampling breaks BPM stretching.**
Conjecture: lower-rate vocal samples might stretch differently on
device because the BPM-stretch math depends on the WAV's declared rate.
Probability low but unverified. **Mitigation:** Slice 1 acceptance
includes "load a 23437 Hz WAV with `time.mode: bpm` to a real device,
play at scene tempo, confirm pitch + tempo are correct." Live test, not
unit test.

**RV4 — verse trim points + project-tempo-synced playback.** Decision
14 says pad canvas is the slot table; trim points are in the pad
config (`start_offset_sec` / `end_offset_sec` already on `ClipRef`).
The 16-bar verse may not be a clean 16 bars on the source — pickup
notes, post-verse breath, etc. **Mitigation:** Slice 3's verse
extraction outputs the raw trim; Slice 2's YAML can refine via per-pad
`start_offset_sec` / `end_offset_sec`. Both layers already supported by
the schema.

**RV5 — phasing pressure to skip Slice 1's byte-identity gate.** Easy
trap: "format_profile defaults to preserve_source; nobody changes it;
why do we need a parity test?" Because subtle bugs in the rate
parameterization will only surface when the user actually flips a
group to `vocal` in production, after the test is gone. Hold the
gate.

---

## Definition of done

User is able to:
1. Author a `deck.yaml` listing 4 groups × 12 pads with `format_profile`
   per group, referencing a mix of manifest entries (`clip:`) and raw
   WAV paths (`path:`).
2. Run `stemforge build-deck deck.yaml --output verse_swap.ppak`, see
   the memory-budget validation report ~50 MB used / 64 MB cap, no
   warnings.
3. Load `verse_swap.ppak` to EP-133 project slot 8 via existing
   `tools/ep133_load_project.py` plumbing (or a sysex transfer
   helper if needed).
4. Perform: trigger Group A pad 1 (a verse), swap Group C drum break
   underneath mid-verse, swap to Group B pad 7 (alt hook from a
   different song), Group D pad 4 sub-bass underlay. No laptop,
   no audible drift, vocals stretched to scene tempo correctly.

That's the ship bar.
