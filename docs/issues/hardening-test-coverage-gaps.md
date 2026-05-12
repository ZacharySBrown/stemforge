# Hardening: JS mock test coverage gaps + CLI integration gaps

**Status:** Open — captured 2026-05-12.

## JS mock suites NOT run by pytest

`tests/test_js_bridge.py` runs only three JS mock test files as of 2026-05-12:

1. `test_preset_resolution.test.js`
2. `test_arrangement_loader.test.js`
3. `test_bounce.test.js` ← just added

But the directory has more:

```
tests/js_mocks/
  test_arrangement_loader.test.js       ✓ wired
  test_arrangement_reader.test.js       ✗ NOT wired
  test_bounce.test.js                    ✓ wired (new)
  test_commit.test.js                    ✗ NOT wired (only listed in path_coverage)
  test_liveapi_mock.test.js             ✗ NOT wired
  test_loader_dispatch.test.js          ✗ NOT wired
  test_locator_anchor.test.js           ✗ NOT wired
  test_preset_resolution.test.js         ✓ wired
```

`test_commit.test.js` has 27 cases covering the COMMIT button flow — it's not run on every pytest. Currently exists in `tests/test_path_coverage.py:STACKED_PR_PENDING` (line 95) suggesting it was supposed to land via a PR that never finished merging.

## What to fix

1. **Add bridge tests for every js_mocks/*.test.js** — each becomes a `test_js_<name>_suite` Pytest function in `tests/test_js_bridge.py`.
2. **Or refactor** — write one bridge test that iterates over all `tests/js_mocks/*.test.js` and runs each. Saves boilerplate, fewer pytest names but parametrized.
3. **Resolve `STACKED_PR_PENDING`** — `test_commit.test.js` is in the tree and passing locally. The entry in `tests/test_path_coverage.py:97` should be removed.

## CLI integration gaps

`stemforge deck-from-manifest` and `stemforge build-deck` are covered by:
- `tests/test_build_deck_cli.py` (8 cases) — argument parsing + smoke run.

But NOT covered:
- `deck-from-manifest` end-to-end CLI test against a fixture manifest. Currently the production-mode manifests from `curate-bars` produce empty `session_tracks`, so the only deck-from-manifest test inputs are hand-rolled fixtures. We need a session-mode fixture (the COMMIT-flow output shape).
- The format_profile patch step (regex swap of vocal/texture/preserve_source → drum) we did inline at the CLI — that's not in code, it's an ad-hoc step in the breaks-n-beats1 build. Should be a flag on deck-from-manifest (`--all-drum`, `--profile <preset>`, etc).

## Done when

- Every `js_mocks/*.test.js` is exercised by pytest.
- `STACKED_PR_PENDING` is empty.
- `deck-from-manifest --profile drum` (or equivalent) is a first-class option, not an inline sed.
