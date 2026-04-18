# Track D — Ableton .als Template Generation

## Goal

Produce `StemForge.als` (Ableton Live Set) with the 7 template tracks from `v0/interfaces/tracks.yaml` pre-built. User opens File → New from Template → "StemForge" and the set is ready.

## Approach

`.als` format: gzip-compressed XML. The XML is undocumented but stable within a major Live version. We target **Live 12 only** for v0.

Strategy:
1. Commit `v0/assets/skeleton.als` — an empty Live 12 set saved by a human one time. This is a build-time asset, documented as the only acknowledged manual step in the v0 pipeline. It is re-used across all builds; the user never touches it.
2. Python tool at `v0/src/als-builder/` parses skeleton, mutates, writes new .als.

## Inputs

- `v0/interfaces/tracks.yaml`
- `v0/assets/skeleton.als` (one-time committed asset — see note below)
- Live 12 XML schema knowledge (reverse-engineered incrementally by the tool)

## Outputs

- `v0/build/StemForge.als`
- `v0/src/als-builder/builder.py` — reads tracks.yaml + skeleton, writes .als
- `v0/src/als-builder/devices/` — per-device XML fragment templates (Compressor, EQ Eight, Reverb, Utility, Simpler — stock devices only)
- `v0/src/als-builder/vst3_lookup.yaml` — VST3 name → plugin UID + param index map (for SoundToys, XLN)
- `v0/src/als-builder/tests/` — pytest suite validating output against fixtures
- `v0/state/D/done.flag`

## One-Time Asset Note

`v0/assets/skeleton.als` is the only file in the repo that was created by a human opening Ableton once. It represents "empty set saved by Live 12, no tracks, no devices." It is not user-facing. It exists because reverse-engineering a complete .als from zero is out of scope for v0. Track D **must** document this in `v0/assets/README.md`.

## Subtasks

### D1 — Parse + serialize
```python
import gzip, lxml.etree as ET
with gzip.open('skeleton.als', 'rb') as f:
    tree = ET.parse(f)
# mutate ...
with gzip.open('StemForge.als', 'wb') as f:
    tree.write(f, xml_declaration=True, encoding='UTF-8')
```

### D2 — Track creation
For each track in `tracks.yaml`:
- Clone `<AudioTrack>` or `<MidiTrack>` node from skeleton
- Set `Name/EffectiveName/Value` = track.name
- Set `ColorIndex/Value` = color → Live's palette index (build a map)
- Insert into `<LiveSet><Tracks>`

### D3 — Device chain
For each device in track.chain:
- Stock devices (Compressor, EQ Eight, Reverb, Utility, Simpler): use `v0/src/als-builder/devices/<device>.xml` template, substitute params
- VST3 (XLN.LO-FI-AF, SoundToys.*): emit `<PluginDevice>` node with UID from `vst3_lookup.yaml`. Parameters by **index**, not name — use the lookup table.

### D4 — ID uniqueness
Every Live element has an `Id` attribute in a set-wide namespace. Track the counter as the builder walks the tree.

### D5 — Time signature + tempo
Master track tempo is left at 120 (M4L device overrides at runtime from manifest).

### D6 — Graceful missing-plugin behavior
If the user doesn't own SoundToys / XLN, Live loads the set with placeholder "Plugin missing" nodes. This is acceptable for v0 — document in README. Do not try to omit devices the user might lack; Live handles it.

## Acceptance

- Live 12 opens `StemForge.als` without error dialogs (plugin-missing warnings OK).
- All 7 tracks present with correct names and colors.
- Stock device params match `tracks.yaml` (verified by saving the opened set and diffing).
- `.als` is gzipped valid XML (parseable with stdlib).

## Risk / Unknowns

- Live XML schema drift between Live 12 point releases: pin target to 12.1.x for v0, document.
- VST3 UIDs are per-vendor and per-plugin; the lookup table is hand-curated. Start with SoundToys + XLN.LO-FI-AF; document how to extend.
- Color palette indices: Live uses a fixed 70-color palette. Map hex → nearest index.

## Subagent Brief

You are implementing Track D of StemForge v0. Can run in parallel with A, B, F.

**Read:**
- `v0/PLAN.md`, `v0/SHARED.md`
- `v0/interfaces/tracks.yaml`
- Any Live 12 .als reverse-engineering notes online (no specific URL required; this is exploratory)

**Produce:**
- `v0/src/als-builder/` with builder.py, devices/, vst3_lookup.yaml, tests/
- `v0/build/StemForge.als`
- `v0/assets/skeleton.als` — IF not already committed. If you need to create it and you don't have Ableton available, write `v0/state/D/blocker.md` noting the need and stop.
- `v0/assets/README.md` documenting skeleton.als provenance

**Do not touch:**
- `stemforge/` package
- `v0/build/stemforge-native`, `v0/build/StemForge.amxd`
- Other tracks' state directories

**Test strategy:**
- Unit: builder output parses as XML, has correct track count.
- Integration: commit a known-good `v0/tests/fixtures/expected.als` for one tracks.yaml config; diff builder output.
- Manual (out of agent scope): open in Live 12, verify visually. Note in done artifacts.

Write `v0/state/D/done.flag` on success.
