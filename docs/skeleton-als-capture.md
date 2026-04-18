# Capturing `skeleton.als` — one-time human step

**Purpose.** Save an empty Ableton Live 12.1.x set to
`v0/assets/skeleton.als` so the `.als` builder can clone Live-native XML
nodes into `v0/build/StemForge.als`. This is the only manual step in the
StemForge v0 pipeline, and it runs once.

This doc is the handoff surface for GitHub issue
[#12](https://github.com/ZacharySBrown/stemforge/issues/12).

---

## Why this is a manual step

`.als` is a gzipped XML file, but Ableton Live is the only tool that
writes the XML correctly. The schema is undocumented and drifts across
Live point releases; even subtle omissions (missing `<LomId>` children,
wrong attribute order, unused `<Annotation>` nodes) cause Live to either
drop tracks silently or refuse to open the set entirely.

We cannot synthesize `skeleton.als` from scratch without reverse-engineering
every format quirk in Live's current output, and we will not ship a
hand-written XML — see
[`v0/assets/README.md` §"Why not commit a hand-written XML?"](../v0/assets/README.md).

The builder at `v0/src/als-builder/builder.py` works by parsing a
real-Live-saved empty set and cloning its `<AudioTrack>` / `<MidiTrack>`
nodes into the 7-track shape described by
`v0/interfaces/tracks.yaml`. Without a real `skeleton.als` to clone
from, the builder has no schema-faithful source and `v0/build/StemForge.als`
cannot be produced.

---

## Prerequisites

- **macOS** with **Ableton Live 12.1.x** installed (any 12.1 point
  release; 12.1.5 is the current reference).
- StemForge repo cloned locally (you already have this).
- ~5 minutes.

Live versions older than 12.1.x may emit a different XML namespace that
the builder tests do not cover — see Troubleshooting.

---

## Steps

> Screenshots welcome as PR amendments — drop PNGs in `docs/img/skeleton-als/`
> and link them inline.

1. Launch **Ableton Live 12.1.x**.

2. **File → New Live Set.** This gives Live's stock default: 2 audio
   tracks + 2 MIDI tracks + 2 return tracks + master. That default shape
   is exactly what the builder wants — it needs at least one `<AudioTrack>`
   and one `<MidiTrack>` node it can clone from, and Live's default set
   already supplies both. (See `v0/tracks/D-als-template.md` §"Approach"
   and `v0/interfaces/tracks.yaml` — the builder clones the default MIDI
   track to emit the `SF | Beat Chop Simpler` track with Simpler in
   slice mode.)

   _Screenshot placeholder: `docs/img/skeleton-als/01-new-live-set.png`._

3. **Do not modify anything.** Don't rename tracks, don't add devices,
   don't change the tempo, don't insert a Simpler by hand. The builder
   is responsible for all mutations. We only want Live's unmodified
   default shape.

4. **File → Save Live Set As…** Navigate to your local StemForge repo
   and save at:

   ```
   <repo>/v0/assets/skeleton.als
   ```

   If Live prompts for a project folder, allow it to create one and
   then move only the `.als` file to `v0/assets/` — the builder does
   not need the project sidecar folders. (Or, simpler: point Save As
   at an empty temporary folder, then `mv <tmp>/skeleton.als
   <repo>/v0/assets/skeleton.als` in a terminal.)

   _Screenshot placeholder: `docs/img/skeleton-als/02-save-as.png`._

5. **Quit Live.** Do not reopen the set — if Live autosaves a tweak,
   the diff will show up and we will have drifted from "pure Live
   default."

---

## After you save

Pick up where the agents stopped. From the repo root:

```bash
# 1. Stage and commit the skeleton.
git add v0/assets/skeleton.als
git commit -m "assets: skeleton.als from Live 12.1.x"

# 2. Rebuild StemForge.als (fast — gzip parse + clone + gzip write).
#    NOTE: the entry point is v0/src/als-builder/builder.py, not build_als.py.
uv run python v0/src/als-builder/builder.py

# 3. Re-run the Track D test suite.
uv run pytest v0/src/als-builder/tests/ -q

# 4. (Optional — required before v0.1 ships) rebuild the installer pkg
#    so StemForge.als is bundled under the User component.
v0/build/build-pkg.sh
```

The pkg rebuild step is **not** required for the v0 ship — `build-pkg.sh`
skips `.als` gracefully when the asset is absent, and the v0 pkg ships
without a project template. Landing `skeleton.als` → `StemForge.als` is a
v0.1 (or fast-follow) deliverable. See
[`docs/v0-ship-spec.md`](./v0-ship-spec.md) §§1, 5, 7.

---

## Verification

Run these against the freshly saved `v0/assets/skeleton.als`. All should
succeed before you consider the capture step done.

```bash
# (a) File exists and is gzip — Live writes .als as gzipped XML.
file v0/assets/skeleton.als
# Expected: "... : gzip compressed data, ..."

# (b) Ungzipped head shows the Ableton root element.
gunzip -c v0/assets/skeleton.als | head -5
# Expected first non-XML-decl line:
#   <Ableton MajorVersion="..." MinorVersion="12..." ... >

# (c) Python stdlib parses it as XML (builder does the same).
python3 -c "import gzip, xml.etree.ElementTree as ET; ET.parse(gzip.open('v0/assets/skeleton.als'))"
# Expected: silent exit 0.

# (d) Builder produces StemForge.als.
uv run python v0/src/als-builder/builder.py
ls -la v0/build/StemForge.als
# Expected: file present, non-zero size.

# (e) Builder tests pass.
uv run pytest v0/src/als-builder/tests/ -q
# Expected: all green.
```

Optional but recommended: open `v0/build/StemForge.als` in Live 12 and
confirm the 7 SF tracks appear with no error dialogs. "Plugin missing"
warnings for SoundToys / XLN are expected if those are not installed —
see `v0/tracks/D-als-template.md` §D6.

---

## Troubleshooting

**`file` reports something other than "gzip compressed data".**
Live didn't save it as a normal `.als`. Most commonly this happens if
Save As… wrote a Live **Project** folder containing an `.als` file
rather than a bare `.als`. Re-do step 4 and make sure the committed
artifact is just the `.als` file, not a containing folder.

**`gunzip -c … | head -5` shows a tag other than `<Ableton … >`.**
Likely Live corrupted the write (rare) or a different tool re-saved
the file (e.g. a text editor opened + saved it, destroying the gzip).
Delete the file and re-capture from Live.

**Builder raises `FileNotFoundError` pointing at `skeleton.als`.**
The asset isn't on the expected path. Confirm it lives at exactly
`v0/assets/skeleton.als` relative to the repo root, not inside a Live
Project subfolder.

**Live version < 12.1.x.**
Older Live versions may emit a different XML namespace / root-attribute
shape than the builder's test fixtures cover. Two options:
1. Upgrade Live to 12.1.x and re-save.
2. Capture anyway, run `uv run pytest v0/src/als-builder/tests/`, and
   file any failures — we'll extend the builder if the delta is small.

**Live version ≥ 13.x.**
Not tested. The set may open in Live 12 with a "set was saved in a newer
version" warning and load-degrade paths. Prefer to capture on 12.1.x so
the committed asset matches the v0 pin (`SKELETON_LIVE_VERSION = 12.1.x`
in `v0/assets/README.md`).

**Live wrote `.als.bak` alongside `.als`.**
That's a backup from a prior save in the same folder. Ignore or delete
the `.bak` — commit only `skeleton.als`.

---

## See also

- [`v0/assets/README.md`](../v0/assets/README.md) — provenance + pinned
  Live version.
- [`v0/tracks/D-als-template.md`](../v0/tracks/D-als-template.md) —
  Track D builder spec.
- [`v0/state/D/blocker.md`](../v0/state/D/blocker.md) — current blocker
  state pointing at this doc.
- [`docs/v0-ship-spec.md`](./v0-ship-spec.md) §W3 — canonical workstream
  brief.
