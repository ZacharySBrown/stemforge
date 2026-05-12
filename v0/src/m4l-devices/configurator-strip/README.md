# Configurator Strip — Phase 3 M4L device

A thin, fresh-build M4L audio-effect device that fires the seven canonical
Configurator operations (load, slice, recompute, re-anchor, curate, export,
open editor) at the local HTTP server.

Status: builder + JS + tests landed. `.amxd` packaging and on-device verify
are manual (per `feedback_test_deploy_discipline.md` — never bake .amxd
artefacts in a worktree, the user packs + installs to verify).

## What this is

A SEPARATE device from `StemForge.amxd`. It runs alongside the big device,
on its own M4L track or after the big device on the same track. The strip
has no LOM/forge logic of its own — it's an intent-emitter that:

1. Discovers the local HTTP server's port via `~/stemforge/.configurator_port`.
2. Renders seven labelled buttons (`live.text` widgets, orange-accent).
3. POSTs to `http://127.0.0.1:<port>/intent/<verb>` via curl + `[shell]`.
4. Opens the popup editor via `[jweb]` (float window).
5. Walks session + arrangement view for `commit`, mirroring the algorithm
   in `stemforge_loader.v0.js`'s `_commitSessionTracks`.

## Files

```
v0/src/m4l-devices/configurator-strip/
  device.yaml          # operation table, palette, geometry, server config
  builder.py           # generates the .maxpat (programmatic)
  js/
    sf_configurator.js # operations dispatcher (classic [js])
  tests/
    test_strip_builder.py  # 17 Python tests (static .maxpat asserts)
    conftest.py
    __init__.py
  README.md            # this file
```

The JS-side test is at `tests/js_mocks/test_sf_configurator.test.js` so the
project's existing `tests/test_js_bridge.py` autodiscovers it. The bridge
runs every `tests/js_mocks/*.test.js` as a parametrized pytest case (10
prior + 1 new = 11 cases as of this PR).

## Local development loop

```bash
# Python tests (fast, no Max).
uv run pytest v0/src/m4l-devices/configurator-strip/tests/ -q

# JS tests (also fast, no Max).
node tests/js_mocks/test_sf_configurator.test.js

# Both, via the pytest bridge.
uv run pytest v0/src/m4l-devices/configurator-strip/tests/ tests/test_js_bridge.py -q

# Generate a .maxpat for visual inspection in standalone Max (no Ableton).
python v0/src/m4l-devices/configurator-strip/builder.py \
    --out v0/build/ConfiguratorStrip.maxpat
open v0/build/ConfiguratorStrip.maxpat
```

## Packing the .amxd + installing (deferred to on-device verify)

The strip is NOT packed in CI. Per
`memory/feedback_test_deploy_discipline.md`, the .amxd is built and
installed manually by the user to verify on real hardware. Suggested
recipe once the design is locked:

```bash
# 1. Build the maxpat.
python v0/src/m4l-devices/configurator-strip/builder.py \
    --out v0/build/ConfiguratorStrip.maxpat

# 2. Pack into .amxd using the existing amxd_pack helper.
python - <<'PY'
import sys, json, pathlib
sys.path.insert(0, "v0/src/maxpat-builder")
from amxd_pack import pack_amxd
patcher = json.loads(pathlib.Path("v0/build/ConfiguratorStrip.maxpat").read_text())
pack_amxd(patcher, "v0/build/ConfiguratorStrip.amxd",
          device_type=1, device_class="audio")
PY

# 3. Sync sf_configurator.js into StemForge's Max Package (so [js] finds it).
cp v0/src/m4l-devices/configurator-strip/js/sf_configurator.js \
   "$HOME/Documents/Max 9/Packages/StemForge/javascript/"

# 4. Install the .amxd alongside StemForge.amxd.
cp v0/build/ConfiguratorStrip.amxd \
   "$HOME/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/"
```

A future installer wrapper (`tools/install_configurator_strip.sh`, similar
to `tools/sf_deploy.py`) is the right place to land step 3+4 once the
device design is verified on hardware.

## JS source of truth

`v0/src/m4l-devices/configurator-strip/js/sf_configurator.js` is the
canonical source.

Per `memory/feedback_js_source_of_truth.md`, the big device duplicates JS
across `v0/src/m4l-js/` and `v0/src/m4l-package/StemForge/javascript/`.
The strip device avoids that duplication by:

- Keeping JS only in `v0/src/m4l-devices/configurator-strip/js/`.
- Having the install step (recipe above) copy it into the existing
  `StemForge/javascript/` package directory at install time.

This means the strip and the big device share one Max Package — both end
up looking in `~/Documents/Max 9/Packages/StemForge/javascript/` for any
classic `[js]` filename.

## HTTP transport choice

Max's classic `[js]` (SpiderMonkey) doesn't ship a reliable
`XMLHttpRequest` binding. Per
`memory/m4l_device_development_guide.md` §3 the working pattern for
external I/O is `[shell]` + the JS emitting commands out an outlet. We
follow that: JS builds a `curl --silent --max-time 5 -X POST -d <json>
<url>` command string and emits `exec <cmd>` on outlet 4. The `[shell]`
external (already a project dependency for the big device) runs it.

Trade-offs:

- Pro: works today, no Max 9.x quirks, easy to debug (the curl command is
  copy-pasteable to a terminal).
- Pro: timeouts are explicit (`--max-time 5`) so a missing server doesn't
  hang the M4L thread.
- Con: stdout from curl isn't surfaced — POSTs are fire-and-forget from
  the strip's POV. Lane A's server is expected to use SSE/websocket for
  progress reporting, which the popup (not the strip) listens to.
- Con: no header-level introspection in the strip (HTTP status codes are
  hidden in `[shell]` stdout). Phase 3.1 may parse `curl --write-out` and
  surface non-200s on the footer line.

## [jweb] embedding choice

Phase 3 uses a **float-window** `[jweb]` (separate window, openurl-driven),
not an embedded view inside the M4L strip rect. Rationale:

- The strip's rect is ~820×100 — way too small to embed a 1200×800 popup
  meaningfully.
- Live's M4L device-area rect doesn't grow dynamically; embedding would
  force the strip to claim 800px tall.
- A float window is movable and the user can drag it to a second monitor,
  which is the common workflow for hardware-export prep.

Phase 4 may revisit if a richer in-device popup makes sense (e.g. a
mini-inspector for the currently-selected scene).

## COMMIT walker

The strip implements `_walkSessionAndArrangement()` inline, mirroring
`_commitSessionTracks` in `v0/src/m4l-js/stemforge_loader.v0.js`. The
walker:

- Iterates tracks named A / B / C / D.
- Session view: clip_slots 0..30, claim slot = clip-slot index, dedup by
  posix file_path.
- Arrangement view: walk `arrangement_clips`, dedup against session
  paths, claim next free slot in 0..19.
- Converts markers to seconds via session bpm when warping=1.

TODO: factor a shared walker into `v0/src/m4l-js/sf_commit_walker.js` so
both devices share one implementation. The duplicate is acceptable for
Phase 3 because it keeps the strip independent of the big device's JS
bundle; a follow-up PR can deduplicate.

## References

- `docs/configurator/STEMFORGE_CONFIGURATOR_SPEC_v4.md` — Phase 3 scope.
- `memory/m4l_device_development_guide.md` — 20 pitfalls observed.
- `memory/feedback_test_deploy_discipline.md` — never auto-build .amxd.
- `memory/feedback_js_source_of_truth.md` — JS duplication trap.
- `memory/project_configurator_device_decision.md` — fresh build, not v2
  refactor.
