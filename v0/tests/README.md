# v0 Integration Tests (Track G)

End-to-end tests that verify the shippable v0 artifacts work without
requiring Ableton Live to be open.

## Running

`jsonschema` is not in the project's `dev` extra yet, so tests are run with
`uv run --with jsonschema`. Use `--active` to layer the extra onto the
project's existing `.venv` (otherwise `uv` creates an ephemeral env that
misses project test dependencies):

```bash
uv run --active --with jsonschema pytest v0/tests/ -v
```

If the dev venv already has `jsonschema` (e.g. because the `onnx` extra has
been installed — `optimum[onnxruntime]` pulls it transitively), plain:

```bash
uv run pytest v0/tests/ -v
```

works too.

## What's tested

| File | Subject | Gates |
|---|---|---|
| `test_binary.py` | `v0/build/stemforge-native` | Skipped if binary absent |
| `test_amxd.py` | `v0/build/StemForge.amxd` | Skipped if amxd absent |
| `test_als.py` | `v0/build/StemForge.als` | Skipped if als absent (currently all-skip; Track D blocked on `v0/assets/skeleton.als`) |

Individual tests within each file also skip fixtures that are missing at
the per-dependency level (e.g. `jsonschema` not installed).

## Binary resolution

`test_binary.py` tries, in order:

1. `v0/build/stemforge-native` (in-tree build)
2. `~/Library/Application Support/StemForge/bin/stemforge-native` (installed)

If neither exists the entire module skips — A gates G at runtime.

## Fixtures

- `fixtures/short_loop.wav` — committed by Track A's validator
  (10s stereo 44.1kHz PCM16, 1.76MB). **Do not regenerate this from
  Track G** — A owns it and downstream tests compare against it.
- `fixtures/generate_loop.py` — reference recipe for producing an
  equivalent signal from scratch. Not called at test time; documented
  for reproducibility.
- `fixtures/expected_stems.json` — structural template (field names +
  type sentinels) for `stems.json`. Derived from
  `v0/src/A/src/sf_manifest.hpp`. `test_binary_manifest_schema_compat`
  asserts the real manifest matches this shape without comparing
  values.

## Als tests are conditional

All tests in `test_als.py` skip cleanly when `v0/build/StemForge.als`
doesn't exist. Track D has a blocker (`v0/state/D/blocker.md` — needs
`v0/assets/skeleton.als` from a human with Ableton). Once that lands
and D regenerates the set, this suite runs without changes.
