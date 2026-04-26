# Song-Form Templates

Five Ableton Live `.als` templates for guided song-idea sketching. Each
defines: target tempo, total length, locator placements (Ableton arrangement
markers), recommended sample-set inputs, and a starter processing chain.

The templates themselves are `.als` files the user builds in Ableton; this
directory holds the **specs** — bar-counts, locator labels, instrument and
chain recommendations — so the templates can be rebuilt or migrated
deterministically.

| Form | Genre | BPM | Bars |
|---|---|---|---|
| [`ambient_long_form`](ambient_long_form.md) | Ambient | 60–80 | 128 |
| [`lofi_aaba`](lofi_aaba.md) | Lo-fi hip hop | 80–95 | 84 |
| [`idm_squarepusher`](idm_squarepusher.md) | Glitch IDM | 140–170 | 80 |
| [`idm_fourtet_evolve`](idm_fourtet_evolve.md) | Slow-burn IDM | 110–130 | 96 |
| [`big_beat_drop`](big_beat_drop.md) | Big Beat | 120–140 | 128 |

## Workflow these templates support

1. **Pick the form** that matches the mood/energy you want.
2. **Open the template** — `.als` already has tempo, locators, track lanes,
   and processing chains laid out.
3. **Drop in 4–5 sample sets** — typically curated runs from the StemForge
   library at `~/mus/Samples/`, dragged into the designated palette tracks.
4. **Sketch by section** — the locators force you to make A different from B
   different from BREAK before you've over-committed to a single loop.
5. **Bounce / commit** when a section feels right.

The intent: escape "one-loop mentality" by surfacing structural variety up
front. Empty named sections in the timeline are a stronger arrangement
prompt than a blank canvas.

## Conventions used in the per-form specs

- **Locator names** become arrangement-view markers in Live (set via the
  Insert Locator menu, or the `+` icon in the arrangement toolbar)
- **Tempo range** is the genre's typical span; pick one and commit
- **Track recommendations** name the *role* (e.g. "drum loops", "bass mono")
  not specific Live devices — see `chains.md` per form for actual devices
- **Sample-set slots** name how many palette tracks to dedicate to dragged-in
  curation outputs

## Related

- `~/mus/Samples/` — StemForge library where curated palettes live
- `~/mus/Templates/` — where the actual `.als` files should live, named to
  match the slugs above (e.g. `ambient_long_form Project/`)
- `stemforge/router.py` — the curation router that distributes outputs
  into the library these templates pull from
