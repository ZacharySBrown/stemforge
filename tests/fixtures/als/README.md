# `.als` fixtures for the Live-in-the-loop smoke suite

This directory holds Ableton Live Sets (`.als`) used by the Phase 5
smoke runner (`tools/test-harness/live-runner.sh`). Each fixture pins
a known starting state for one or more smoke tests.

**`.als` files are gzip-compressed XML** (Live's native save format).
They include host-specific paths and Live-version-specific schemas,
so we can't reliably synthesize them programmatically — they must be
recorded once in a real Live, then committed.

## Inventory

| Fixture | Status | Used by | What it contains |
|---|---|---|---|
| `empty-staging.als` | **shipped (minimal skeleton)** | smoke_1 | Bare-minimum gzipped-XML `.als`. Hand-crafted to be openable by Live 12 (will normalize on first save). The smoke just asserts the device boots and reports no active curation. |
| `loaded-forge-stg-empty.als` | **`.gitkeep` placeholder — user must capture** | smoke_2, smoke_3, smoke_4 | One forge (`breaks-n-beats-1`) loaded as `FORGE/*` tracks. No `STG-*` tracks. No active curation. |
| `curation-active-stg-populated.als` | **`.gitkeep` placeholder — user must capture** | smoke_5, smoke_6, smoke_7, smoke_8, smoke_9, smoke_10 | Active curation `verse_swap_v1`. `STG-A`..`STG-D` tracks created. `STG-A` has 4 pads populated from `breaks-n-beats-1`. Also: a second curation `live_set_oct_2026` exists on disk (for smoke_6). |

The smoke runner skips tests cleanly when the required fixture is
missing or corrupt. Run `tools/test-harness/live-runner.sh --list` to
see what each test needs.

## Capture procedure

For each `.gitkeep`-placeholder fixture above, do the following on a
machine with Ableton Live + the StemForge Max package installed.

### Prep (once per session)

```bash
# 1. Make sure StemForge.amxd is installed in your Ableton User Library.
uv run python tools/sf_deploy.py

# 2. Make sure the fixture forge exists on disk. The smoke suite expects
#    a forge at ~/stemforge/processed/breaks-n-beats-1/ with both
#    arrangement_manifest.json and auto_curation_manifest.json.
ls ~/stemforge/processed/breaks-n-beats-1/

# 3. Make sure the fixture curations exist. The smoke suite expects
#    ~/stemforge/curations/verse_swap_v1.yaml and
#    ~/stemforge/curations/live_set_oct_2026.yaml.
ls ~/stemforge/curations/
```

If any of the above is missing, create it first via the normal
`stemforge forge` / `New Curation…` flow.

### `empty-staging.als`

> **Shipped already.** A minimal hand-crafted skeleton is in this
> directory (committed as a real gzipped `.als`). You can re-record
> it if Live's schema bumps and the skeleton stops opening:

1. Open Ableton Live → new empty Live Set.
2. Drag `StemForge.amxd` onto the master/return chain.
3. File → Save Live Set As… → save as `empty-staging.als` in this
   directory.
4. Verify: `python -c "import gzip; print(gzip.open('empty-staging.als').read()[:80])"`
   should start with `<?xml`.

### `loaded-forge-stg-empty.als`

1. Open Ableton Live → new empty Live Set.
2. Drag `StemForge.amxd` onto a return track (or master).
3. In the configurator popup (or via the device's `Pick source…`),
   load forge `breaks-n-beats-1`. Wait for `FORGE/breaks-n-beats-1/drum`,
   `.../bass`, `.../vocal`, `.../other` tracks to appear.
4. **Do not** create a curation. **Do not** drag any clips to staging.
5. File → Save Live Set As… → save as `loaded-forge-stg-empty.als` in
   this directory.
6. Replace the `.gitkeep` placeholder by deleting it (`git rm
   loaded-forge-stg-empty.als.gitkeep`).

### `curation-active-stg-populated.als`

1. Open Ableton Live → new empty Live Set.
2. Drag `StemForge.amxd` on, load forge `breaks-n-beats-1`.
3. In the popup: New curation → name `verse_swap_v1`, target `ep133`.
   Wait for `STG-A`..`STG-D` tracks to appear.
4. From `FORGE/breaks-n-beats-1/drum` slot 5, drag a clip onto
   `STG-A` slot 1. Repeat for slots 2, 3, 4 (any clips — exact source
   doesn't matter; the smoke suite asserts on count, not identity).
5. Click `COMMIT` on the device. Wait for the popup to refresh.
6. Switch popup focus: New curation → name `live_set_oct_2026`,
   target `ep133`. (This populates the second curation file on disk
   so smoke_6 has somewhere to switch *to*.) Don't add pads to it.
7. Switch active curation back to `verse_swap_v1` (Open as active).
8. File → Save Live Set As… → save as
   `curation-active-stg-populated.als` in this directory.
9. Replace the `.gitkeep` placeholder.

## Regenerating

If Live's `.als` schema changes (major Live version bump), the
fixtures may fail to open cleanly. Just re-run the capture procedure
above and overwrite the existing files.

A future enhancement could add `live-runner.sh capture <fixture-name>`
to automate the "open / save / verify" leg, but for now the procedure
is manual.

## Why not synthesize?

We considered hand-crafting all three fixtures programmatically.
Issues:

1. `.als` XML schemas drift between Live versions; Live often refuses
   to open or silently corrupts sets generated outside Live itself.
2. Loading the StemForge Max device requires a path-relative reference
   that Live writes with a host-absolute form.
3. Clips on tracks include sample-path absolute references that are
   user-specific.

So we ship one minimal `empty-staging.als` (which Live is permissive
enough to open even from a bare skeleton) and require the operator to
record the more complex fixtures once. The runner skips cleanly until
they're present.
