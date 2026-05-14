# Configurator Smoke Test Guide (Phase 5)

This is the L4 (Live-in-the-loop) validation gate for the StemForge
configurator v1 rebuild. Phases 0–4 produce code; Phase 5 produces
the runner that exercises it against a real Ableton Live process to
make sure the whole stack actually works end-to-end.

## What it does

The runner opens fixture `.als` files via `osascript`, waits for the
StemForge M4L device's `[udpreceive]` socket to come up, fires
`sf-remote` intents, captures server state via `GET /state`, and
asserts on the captured state. One smoke per workflow checkpoint:

| # | Smoke | Checkpoint |
|---|---|---|
| 1 | `smoke_1_empty_boot` | Device boots, server has no active curation. |
| 2 | `smoke_2_load_forge` | `LOAD forge` creates 4 `FORGE/*` tracks. |
| 3 | `smoke_3_create_curation` | `New curation` creates 4 `STG-*` tracks + sets active. |
| 4 | `smoke_4_commit` | `COMMIT` writes the curation YAML/JSON file. |
| 5 | `smoke_5_load_curation` | `LOAD curation` re-populates staging from disk. |
| 6 | `smoke_6_switch_curation` | Switching active curation repopulates staging. |
| 7 | `smoke_7_reanchor` | `RE-ANCHOR` updates forge manifests, reloads tracks. |
| 8 | `smoke_8_bounce` | `BOUNCE` populates `~/stemforge/bounced/<curation>/`. |
| 9 | `smoke_9_export` | `EXPORT` produces a `.ppak`. |
| 10 | `smoke_10_stale` | Mutating a forge surfaces a stale flag in state. |

## How to run locally

Prereqs:

1. Ableton Live installed (11 or 12, Suite or Standard or Beta).
2. StemForge Max package installed:
   ```bash
   uv run python tools/sf_deploy.py
   ```
3. Fixture `.als` files recorded (see
   [`tests/fixtures/als/README.md`](../../tests/fixtures/als/README.md)).
   Only `empty-staging.als` ships with the repo — the other two are
   `.gitkeep` placeholders you must record once.
4. Configurator server can autostart from the device, **or** you can
   start it manually first:
   ```bash
   uv run python tools/m4l_configurator_server.py
   ```

Then:

```bash
# See what's available
tools/test-harness/live-runner.sh --list

# Run everything (skipped tests will report cleanly)
tools/test-harness/live-runner.sh --all

# Run one smoke
tools/test-harness/live-runner.sh --test smoke_1_empty_boot
```

The runner emits one NDJSON line per test on stdout, then prints a
summary to stderr. Exit code 0 iff every non-skipped test passed.

```
{"test": "smoke_1_empty_boot", "status": "pass", "duration_sec": 8.2}
{"test": "smoke_2_load_forge", "status": "skip", "reason": "fixture missing: loaded-forge-stg-empty.als (record it per tests/fixtures/als/README.md)"}
...
=== smoke summary ===
  pass:  1
  fail:  0
  error: 0
  skip:  9
  total: 10
```

## Assertion model per smoke

### Smoke 1 — empty boot

Opens `empty-staging.als`. Polls `GET /healthz` until 200 (or 30 s
timeout). Then `GET /state` and asserts `state.active_curation is
None`.

Why this matters: if the device's `[udpreceive]` doesn't come up or
the server's port file is missing, every later smoke fails. Smoke 1
is the canary.

### Smoke 2 — load forge

Opens `loaded-forge-stg-empty.als`. Fires `sf-remote fire forge load
breaks-n-beats-1`. Waits 2.5 s. Asserts `state.tracks` contains 4
entries whose names start with `FORGE/breaks-n-beats-1`.

### Smoke 3 — create curation

Opens `loaded-forge-stg-empty.als`. Fires `sf-remote fire forge
create-curation smoke_test_curation_3 ep133`. Asserts 4 `STG-*` tracks
and `state.active_curation == "smoke_test_curation_3"`.

### Smoke 4 — commit

Like smoke 3, then fires `sf-remote fire state commit`. Waits longer
(COMMIT walks LOM + writes file). Asserts
`~/stemforge/curations/smoke_test_curation_4.{yaml,json}` exists and
contains `curation_version`, `target`, `groups` keys.

### Smoke 5 — load curation

Opens `curation-active-stg-populated.als`. Fires `sf-remote fire forge
open-curation verse_swap_v1`. Asserts active curation and 4 `STG-*`
tracks.

### Smoke 6 — switch curation

Opens `curation-active-stg-populated.als`. Opens `verse_swap_v1`, then
opens `live_set_oct_2026`. Asserts the active curation switches.

### Smoke 7 — re-anchor

Fires `sf-remote fire forge re-anchor breaks-n-beats-1 0.247`. Waits
for CLI to rewrite manifests + device to reload tracks. Asserts the
forge is still present in `state.forges`.

### Smoke 8 — bounce

Opens `curation-active-stg-populated.als`. Triggers BOUNCE. Waits
generously (Live actually renders audio). Asserts
`~/stemforge/bounced/verse_swap_v1/` contains exactly 4 `.wav` files
(matching the 4 pads on `STG-A` per the fixture).

### Smoke 9 — export

Like smoke 8 but fires `sf-remote fire forge export verse_swap_v1
<out>.ppak`. Asserts the `.ppak` exists and is ≥ 1024 bytes.

### Smoke 10 — stale detection

Opens `verse_swap_v1`. Re-curates `breaks-n-beats-1`. Asserts a stale
flag appears in `state.stale` / `state.active_curation_stale` /
`state.curation.stale` (whichever the server uses).

## Troubleshooting

### "Ableton Live not installed on this host"

The runner searches the standard paths (`/Applications/Ableton Live 12
Beta.app`, `/Applications/Ableton Live 12 Suite.app`, etc.). Override:

```bash
SF_LIVE_APP="/Applications/My Custom Live.app" \
  tools/test-harness/live-runner.sh --all
```

### "configurator server not responding on port 7430"

Either start it manually first (`uv run python
tools/m4l_configurator_server.py`), or open Live with the device
loaded so it autostarts. The server writes
`~/stemforge/.configurator_port` once it binds; the runner reads that
file before falling back to 7430.

### "fixture missing"

The smoke skips cleanly. Record the fixture per the procedure in
[`tests/fixtures/als/README.md`](../../tests/fixtures/als/README.md).

### "configurator /healthz on port X did not come up within 30s"

The device opened the `.als` but the server didn't bind in 30 s.
Causes:
- Live crashed on open (check Live's console).
- The Max device errored on `loadbang`. Check `~/stemforge/logs/sf_debug.log`.
- The configurator server is bound to a different port. Run
  `cat ~/stemforge/.configurator_port` and pass `--port <N>`.

### "fixture corrupt"

The `.als` file exists but isn't a gzipped XML. Probably someone
committed a binary that isn't a real Live set. Re-record the fixture.

### Tests pass locally but fail in CI

The CI workflow runs on a **self-hosted runner** with the labels
`[self-hosted, macos, ableton-live]`. If no such runner is registered,
the workflow queues indefinitely. Check:

1. `gh workflow list` — `smoke-live` is in the list.
2. `gh run list --workflow smoke-live` — recent run statuses.
3. Self-hosted runner is online and has labels matching the workflow.

## CI integration

The workflow at [`.github/workflows/ci-smoke-live.yml`](../../.github/workflows/ci-smoke-live.yml)
is `workflow_dispatch` only — it does not run on PRs or pushes.
Trigger it manually from the Actions tab, optionally passing a
comma-separated list of test names as input. Without a self-hosted
runner registered with the matching labels it stays inert; that's
fine — it's a documented gate, not a blocker.

The workflow:
1. Checks out the branch.
2. Installs `uv`, syncs Python deps with `dev` + `configurator` extras.
3. Installs frontend deps (`npm ci` in `web/configurator`).
4. Installs StemForge.amxd via `tools/sf_deploy.py`.
5. Starts the configurator server in the background.
6. Runs `tools/test-harness/live-runner.sh` with the selected tests.
7. Uploads the server log on failure.

## Self-tests (no Live required)

The runner infrastructure itself is unit-tested. See
[`tests/test_live_runner.py`](../../tests/test_live_runner.py):

- `parse_fixture_status` returns MISSING/PRESENT/CORRUPT correctly.
- `skip_if_no_fixture` behaves as expected.
- `assert_state` does partial-match correctly.
- `build_open_als_command` constructs the right `osascript` argv.
- `live-runner.sh --help` exits 0.
- `live-runner.sh --list` lists 10 smoke tests.
- `live-runner.sh --skip-fixture-check` emits 10 skip reports.
- The plan-vs-impl drift test parses `EXECUTION_PLAN_v1.md` and
  asserts a `smoke_N_*` function exists for each plan entry.

Run with:

```bash
uv run pytest tests/test_live_runner.py -v
```

This suite runs on every PR in regular CI (no Live needed).
