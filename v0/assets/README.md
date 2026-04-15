# v0/assets/

Committed build-time assets. Do not regenerate automatically — each file
here has a manual provenance step documented below.

## `skeleton.als` — Empty Ableton Live 12 Set

**Status:** NOT YET COMMITTED (see `v0/state/D/blocker.md`).

**Purpose.** The StemForge Ableton template generator (Track D) does not
synthesize an `.als` from scratch. Instead it reads a one-time-saved
"empty Live 12 set" and clones it into the shape described by
`v0/interfaces/tracks.yaml`. Without `skeleton.als` the builder has no
Live-native schema to clone from.

### Provenance (how to produce it — one-time human step)

Do this once on a Mac that has Ableton Live 12 installed. The file is
then committed and re-used forever.

1. Launch **Ableton Live 12.1.x** (any 12.1 point release; pin the exact
   version you used in `SKELETON_LIVE_VERSION` below).
2. File → **New Live Set** (this gives the stock 2-audio-track + 2-midi-track
   + 2-return default).
3. **Do not modify anything.** Don't rename tracks, add devices, change
   tempo, etc. We want Live's exact default shape.
4. File → **Save Live Set As…** → save as `skeleton.als` at the repo path
   `v0/assets/skeleton.als`.
5. Quit Live without reopening the set.
6. `git add v0/assets/skeleton.als` and commit with the version tag in
   the message (e.g., `assets: skeleton.als from Live 12.1.5`).

### Pinned version

    SKELETON_LIVE_VERSION = 12.1.x   # update here when re-saving

If Live writes a set from a newer major version (13+), the builder may
break silently. The acceptance test opens `StemForge.als` in Live and
verifies no warnings — if that test fails after a Live upgrade, re-save
`skeleton.als` from the current version.

### Why not commit a hand-written XML?

Live's XML schema is undocumented and evolves across point releases.
Even subtle omissions (missing `<LomId>` children, missing `<Annotation>`
nodes, wrong attribute order in some versions) cause Live to either
drop the track silently or refuse to open the set. A real Live-saved
set is the only way to guarantee schema fidelity.

## Extending the VST3 lookup table

`v0/src/als-builder/vst3_lookup.yaml` lists VST3 plugin UIDs + parameter
IDs for SoundToys and XLN plugins. UIDs are per-vendor and change only
when a plugin's Processor class ID is bumped — rare but it happens.

**To verify / capture a UID:**

1. Create a new Live 12 set.
2. Drop the plugin onto a track at default settings.
3. Save the set, e.g. as `probe.als`, to a scratch location.
4. Gunzip it:
       `gunzip -c probe.als > probe.xml`
5. Open `probe.xml` and find the `<Vst3PluginDevice>` node matching the
   plugin. Copy the `Uid Value="…"` (32 lowercase hex chars).
6. For parameter IDs: change one parameter in Live (e.g., Decapitator's
   Drive knob) by a visible amount, save, diff the new `.xml` against
   the prior one. The child `<Parameter><Id Value="N"/>` whose `<Value>`
   changed is the param ID for that knob.
7. Update `vst3_lookup.yaml` accordingly; re-run the builder tests.

Missing plugins (not in the lookup table, or user didn't install them)
render as Live "Plugin missing" placeholders — this is the accepted
v0 behavior, documented in `v0/tracks/D-als-template.md §D6`.
