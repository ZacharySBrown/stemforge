# UDP / OSC bus — outstanding cleanup

**Status:** Open — captured 2026-05-12. User-flagged ("any outstanding work with the UDP stuff").

## Background

The harness uses Max's `udpreceive` (port 7420 bus, 7421 dump) in OSC mode to drive forge actions from `sf-remote` CLI. PR #62 landed the slash-prefixed OSC route fix and `sf_remote._osc_encode` for the wire format.

## Loose ends to chase

1. **`reload` forwarder is broken** — `sf_forge.js:reload()` outlets `"reload"` to the loader, but `stemforge_loader.v0.js` has no `reload` handler. Right-click → Edit Script → save is the workaround. **See [`js-reload-forwarder-broken.md`](js-reload-forwarder-broken.md).**

2. **Bounce stub race** — `bounceTracks` writes a 217-byte stub manifest *before* the crop loop runs; the real session_tracks gets written later. Anyone polling for the manifest's existence (vs size > N) gets the wrong file. **See [`bounce-stub-race.md`](bounce-stub-race.md).**

3. **`sf-remote dump` times out when Max isn't running the debug patch** — the 3s timeout is reasonable but the error message could be more diagnostic. Also: when the dump patch IS running but `sf_state` is empty, output is misleading.

4. **OSC route documentation drift** — `tools/sf_remote.py` references "verified empirically 2026-05-09 via /tmp/udp_probe.maxpat" but the probe patcher isn't versioned. If anyone needs to reproduce the route shape later, the probe is lost. **TODO:** check `/tmp/udp_probe.maxpat` in or write a one-paragraph note explaining what to do if the OSC behavior ever changes.

5. **No round-trip test for sf-remote → patcher** — we have unit tests for OSC encoding but no integration test that fires a message and verifies the patcher dispatches it correctly. Could use a mock Max harness or a probe `[print]` in the patcher.

6. **`bus_port` 7420 / `dump_port` 7421 are hardcoded** in `sf_remote.py`. Fine for single-Max-instance dev, breaks for parallel Max sessions. Lowest-effort fix: env vars `SF_BUS_PORT` / `SF_DUMP_PORT`.

7. **Settings target (`settings`) might not have all the routes the dispatcher claims** — the patcher's `route` text was updated to `route /state /forge /preset-loader /manifest-loader /settings /ui /logger` but I haven't verified every target accepts the message types sf-remote claims it supports.

## Done when

Each item above is either fixed or has its own dedicated issue file. The CLI usage stays the same (so we're not breaking the contract — these are internals).
