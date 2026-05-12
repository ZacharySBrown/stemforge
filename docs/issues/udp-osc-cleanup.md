# UDP / OSC bus — outstanding cleanup

**Status:** Mostly resolved — 2026-05-12. Three items closed, two fixed inline, two split into sub-issues.

## Background

The harness uses Max's `udpreceive` (port 7420 bus, 7421 dump) in OSC mode to drive forge actions from `sf-remote` CLI. PR #62 landed the slash-prefixed OSC route fix and `sf_remote._osc_encode` for the wire format.

## Loose ends — status

1. **`reload` forwarder is broken** — ✅ **Resolved by PR #74** (Lane 2B). `stemforge_loader.v0.js` now has a top-level `function reload()` that toggles `this.autowatch` to re-arm Max's file-watcher. On-device validation still pending. Issue file: [`js-reload-forwarder-broken.md`](js-reload-forwarder-broken.md).

2. **Bounce stub race** — ✅ **Resolved by PR #66** (Phase 1). `bounceTracks` now writes the stub to `<manifest>.tmp` and atomically renames to the final path after `_commitSessionTracks` fills it. Issue file: [`bounce-stub-race.md`](bounce-stub-race.md).

3. **`sf-remote dump` error messages** — ✅ **Fixed in this PR.** The timeout and "no relevant lines" messages now include a 3-step checklist (Live loaded? sf_logger running? log live?) and point users at `--timeout` for tight defaults. The empty-dict case is distinguished from the not-initialized case.

4. **OSC route documentation drift** — ✅ **Fixed in this PR.** The `_osc_encode` docstring previously pointed at `/tmp/udp_probe.maxpat` which gets wiped on macOS reboot. Replaced with prose explaining the empirical check, how to reproduce it with `nc -u`, and what would change if a future Max version normalizes OSC addresses. No on-disk probe artifact needed.

5. **No round-trip integration test for sf-remote → patcher** — 🔜 **Split out to its own issue.** Mock Max harness or `[print]` probe needed. See the new sub-issue filed alongside this update.

6. **`bus_port` 7420 / `dump_port` 7421 hardcoded** — ✅ **Already resolved** (in a prior change). `tools/sf_remote.py:51-52` already reads `SF_REMOTE_BUS_PORT` / `SF_REMOTE_DUMP_PORT` env vars with `7420` / `7421` as defaults. Status line on this file was just stale.

7. **Settings target dispatch coverage** — 🔜 **Split out to its own issue.** Need to audit each route in the patcher's `route /state /forge /preset-loader /manifest-loader /settings /ui /logger` chain against the message types `sf-remote fire` claims to send. See the new sub-issue.

## Done when

This umbrella is closed when:

- Items 1–4, 6 are confirmed working in a v0.2.x release cycle.
- Items 5 + 7 have their own filed issues progressing independently.

## Followup work

The two remaining sub-issues track the real work that didn't fit inline. Hardware validation of items 1 (reload) and 6 (port env vars on a parallel-Max setup) can happen opportunistically.
