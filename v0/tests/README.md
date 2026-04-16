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
| `test_pkg_install.py` | `v0/build/StemForge-0.0.0.pkg` | Tier 1 auto-skips if pkg absent; tier 2 gated on `STEMFORGE_INSTALL_E2E=1` |

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

## `test_pkg_install.py` — fresh-install validation harness (W4)

Validates that the W2-built `v0/build/StemForge-0.0.0.pkg` contains
everything a fresh Mac needs. Two tiers:

### Tier 1 (default, fast, no sudo)

`pkgutil --expand-full` the pkg into a session-scoped `tmp_path` and
assert on the extracted layout. No real install side-effects.

12 assertions, one per test function:

1. `test_pkg_exists` — pkg file exists under `v0/build/` and is >100 MB.
2. `test_pkg_expands_cleanly` — `pkgutil --expand-full` succeeds,
   produces `system.pkg/`, `user.pkg/`, and `Distribution`.
3. `test_system_payload_has_binary` — `usr/local/bin/stemforge-native`
   present + executable.
4. `test_system_payload_has_dylib` — `usr/local/lib/libonnxruntime.*.dylib`
   glob-match.
5. `test_system_payload_has_uninstaller` — `usr/local/bin/stemforge-uninstall`
   present + executable.
6. `test_user_staging_has_amxd` — `tmp/stemforge-staging/StemForge.amxd`
   present, >1 KB, starts with Max magic bytes `b"ampf"`.
7. `test_user_staging_has_bridge_js` — `stemforge_bridge.v0.js`
   references `spawn` (sanity that it's the real bridge, not a shim).
8. `test_user_staging_has_loader_js` — `stemforge_loader.v0.js`
   present + non-empty.
9. `test_user_staging_has_manifest` — `models/manifest.json` parses
   and has a top-level `models` key.
10. `test_user_staging_has_fused_onnx` — **sha256 of
    `models/htdemucs_ft/htdemucs_ft_fused.onnx` equals
    `71828190…9ce9`.** This is the critical fusion-contract check.
11. `test_user_staging_has_no_data_sidecar` — no `*.data` external-weight
    sidecars anywhere under `models/` (CoreML EP silently falls back to
    CPU with sidecars; see `v0/state/A/fusion_succeeded.md`).
12. `test_postinstall_present_and_executable` — `user.pkg/Scripts/postinstall`
    exists, +x, and contains `stemforge_bridge.v0.js`, `$MODELS_DEST`,
    and `sudo -u` (so the CoreML warmup cache lands in the user's
    Library, not `/var/root`).

Tier-1 is fast: a 409 MB pkg extracts in ~2 s and the sha256 read of the
697 MB fused ONNX dominates the runtime (~1 s on M-series). Expand dir
is a session-scoped fixture so one extract serves all 12 tests.

### Tier 2 (opt-in, gated, slow)

`test_pkg_installs_end_to_end` actually runs
`sudo installer -pkg ... -target $TMPROOT` against a throwaway root, then
exec's the installed binary's `--version` and asserts the output contains
`0.0.0`. Requires sudo (may prompt for a password depending on local
sudoers config) and takes ~30-60 s. Gated on `STEMFORGE_INSTALL_E2E=1`.

### Running

```bash
# Tier 1 only (default).
uv run pytest v0/tests/test_pkg_install.py -v

# Tier 1 + tier 2 (requires sudo).
STEMFORGE_INSTALL_E2E=1 uv run pytest v0/tests/test_pkg_install.py -v
```

If the pkg isn't built yet, tier-1 tests skip cleanly with a message
telling you to run `bash v0/build/build-pkg.sh`.
