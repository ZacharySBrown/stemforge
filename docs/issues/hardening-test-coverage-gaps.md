# Hardening: JS mock test coverage gaps + CLI integration gaps

**Status:** Closed 2026-05-12 — all sub-tasks done. See per-section markers.

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

But NOT covered (status as of 2026-05-12):
- ✅ DONE — `deck-from-manifest` end-to-end CLI test against a session-mode fixture manifest. Landed via `test/deck-from-manifest-e2e`: `tests/ep133/test_deck_from_manifest_e2e.py` (5 cases) + `tests/ep133/fixtures/session_mode_manifest.json` (mirrors `_commitSessionTracks` output). Uses subprocess pattern matching `tests/test_canonical_tempos.py::_run_split`.
- ✅ DONE (prior commit, Phase 1) — The format_profile patch step is now a first-class flag (`--profile`, `--all-drum`, `--play-mode`) on `deck-from-manifest`. Library-level coverage in `tests/ep133/test_deck_autogen.py`; end-to-end CLI coverage in `tests/ep133/test_deck_from_manifest_e2e.py`. No more regex sed step needed.

## Done when

- ✅ Every `js_mocks/*.test.js` is exercised by pytest.
- ✅ `STACKED_PR_PENDING` is empty.
- ✅ `deck-from-manifest --profile drum` (or equivalent) is a first-class option, not an inline sed.
- ✅ `deck-from-manifest` end-to-end CLI test landed against a session-mode fixture.
