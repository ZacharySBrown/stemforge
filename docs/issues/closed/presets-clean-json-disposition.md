# `presets/clean.json` color refactor — needs disposition

**Status:** Open — captured 2026-05-12.

## What's there

`presets/clean.json` has an uncommitted change in the working tree (30 line diff) that swaps the `color` field from a 3-key object `{"name": ..., "index": ..., "hex": ...}` to a bare hex string `"#FF4444"`. This was excluded from PR #62 because it's unrelated to the EP-133 deck pipeline.

```diff
- "color": {
-   "name": "red",
-   "index": 14,
-   "hex": "#FF3A34"
- },
+ "color": "#FF4444",
```

## What needs to happen

1. **Decide if the refactor is wanted.** Does it match the schema other presets expect? Does the loader accept both shapes (gracefully degrade)?
2. **If yes**, also update the loader to handle the new shape and migrate all preset files in one go.
3. **If no**, `git checkout presets/clean.json` to discard.
4. **If half-yes** (e.g. accept both for back-compat), commit just the loader change and leave the preset alone for now.

## Where to look

- Loader code paths that read `color` — grep for `\.color`, `preset.color`, `colorIndex` etc.
- `pipelines/default.yaml` / `production_idm.yaml` — how colors are specified elsewhere.
- Memory: [`feedback_preset_authoring_style.md`] — preset conventions.

## Done when

`git status` is clean on `presets/clean.json` (either committed or reverted) and the loader's color-handling is consistent across all presets.
