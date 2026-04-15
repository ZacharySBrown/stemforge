# Track C — M4L Device Generation

## Goal

Produce `StemForge.amxd` programmatically from the specs in `v0/interfaces/`. No opening the Max editor. No hand-wiring UI objects. No "save as device" step.

## Approach

`.maxpat` files are JSON. `.amxd` files are a Max-specific container: roughly `{magic header}{chunk table}{patch JSON}{assets}`. The format is semi-proprietary. Two paths exist, ordered by preference:

### Path 1 (preferred): Fully programmatic
Generate the `.maxpat` JSON from `v0/interfaces/device.yaml`. Wrap it into an `.amxd` using one of:
- Cycling74's `max -cli` headless build (if available on CI)
- Community reverse-engineered container writer (Python implementation exists; test viability)

### Path 2 (fallback): Template + injection
1. A human commits a minimal pre-built `v0/assets/StemForge.template.amxd` (empty patch with one `node.script` and one `inlet/outlet`) **one time**. This is a build-time asset, not a user-time step — per PLAN.md this is the only acknowledged exception.
2. Build tool extracts the `.maxpat` JSON, regenerates UI + wiring from `device.yaml`, re-bundles.

Decision point: spend max 2 agent-hours on Path 1. If not working, fall back to Path 2 without further debate. Document the decision in `v0/state/C/path-chosen.md`.

## Inputs

- `v0/interfaces/device.yaml` — UI + binary resolution
- `v0/interfaces/ndjson.schema.json` — events the bridge JS must handle
- `v0/interfaces/tracks.yaml` — what tracks to duplicate post-complete
- `m4l/*.js` — existing bridge/loader JS, use as reference (do not reuse as-is)
- `v0/build/stemforge-native` — must exist, for end-to-end integration test
- (Path 2 only) `v0/assets/StemForge.template.amxd`

## Outputs

- `v0/build/StemForge.amxd` — drop-in M4L device
- `v0/src/maxpat-builder/` — Python tooling:
  - `builder.py` — `device.yaml` → `.maxpat` JSON
  - `amxd_pack.py` — `.maxpat` → `.amxd`
  - `tests/` — unit tests for the builder
- `v0/src/m4l-js/stemforge_bridge.v0.js` — node.script child: spawn binary, parse NDJSON, drive Max
- `v0/src/m4l-js/stemforge_loader.v0.js` — post-complete: LOM track duplication per `tracks.yaml`
- `v0/state/C/path-chosen.md` — Path 1 or Path 2
- `v0/state/C/done.flag`

## Bridge JS Behavior (critical detail)

The `node.script` child process (inside the .amxd):

```javascript
// stemforge_bridge.v0.js
const { spawn } = require('child_process');
const readline = require('readline');
const Max = require('max-api');

Max.addHandler('split', (filePath, pipeline, backend) => {
    const binary = resolveBinary();  // per device.yaml search_paths
    const child = spawn(binary, ['forge', filePath,
        '--json-events', '--pipeline', pipeline, '--backend', backend]);

    const rl = readline.createInterface({ input: child.stdout });
    rl.on('line', (line) => {
        let evt;
        try { evt = JSON.parse(line); } catch { return; }
        switch (evt.event) {
            case 'progress':  Max.outlet('progress', evt.pct, evt.phase); break;
            case 'stem':      Max.outlet('stem', evt.name, evt.path); break;
            case 'bpm':       Max.outlet('bpm', evt.bpm); break;
            case 'complete':  Max.outlet('complete', evt.manifest); break;
            case 'error':     Max.outlet('error', evt.phase, evt.message); break;
        }
    });
});
```

## Loader JS Behavior

Triggered by `complete` outlet. Reads `stems.json` via Max's `LiveAPI`, then:
1. Set song tempo from manifest BPM.
2. For each stem with a `stem_target` match in `tracks.yaml`: duplicate the template track, rename, load the stem WAV into slot 0.
3. For `drums_beats` target: duplicate the Simpler template, configure slice mode, load every `drums_beats/*.wav`.
4. Unmatched stems (e.g., `guitar`, `piano` from 6-stem model): duplicate fallback template.

## Acceptance

- Opening `v0/build/StemForge.amxd` in Ableton Live 12 succeeds with no errors in the Max console.
- Dropping a file onto the device invokes the native binary and events flow back.
- Post-complete, the Live set has new tracks populated with audio clips at positions matching the templates.
- No editing of the device in Max is required after install.

## Risk / Unknowns

- `.amxd` container format: if Path 1 blocks, Path 2 is acceptable.
- node.script availability: Ableton Live 11.3+ ships with Node for Max. Lock minimum Live version in device.yaml.
- LiveAPI track duplication: existing `stemforge_template_builder.js` proves it works; port carefully.
- `max-api` module: part of Node for Max, not standard npm. Bundle appropriately.

## Subagent Brief

You are implementing Track C of StemForge v0.

**This track has a hard dependency on Track A.** Before starting, block on:
```bash
while [ ! -f v0/state/A/done.flag ]; do sleep 10; done
[ -f v0/state/A/blocker.md ] && exit 1
```

**Read:**
- All of `v0/PLAN.md`, `v0/SHARED.md`, `v0/DAG.md`
- All of `v0/interfaces/*` (device, tracks, ndjson.schema)
- `m4l/stemforge_bridge.js`, `m4l/stemforge_loader.js`, `m4l/stemforge_template_builder.js` (reference)

**Produce:**
- Everything under Outputs above

**Boundaries:**
- You may read `v0/build/stemforge-native` to test integration; do not modify it.
- You may commit `v0/assets/StemForge.template.amxd` only if Path 1 blocks.
- Do not modify `stemforge/` package (that's Track A/B territory).

**On Path 1 blocker within 2h:** switch to Path 2. Record in `v0/state/C/path-chosen.md`.
**On Path 2 blocker:** write `v0/state/C/blocker.md`, do not partially commit.

Write `v0/state/C/done.flag` when the `.amxd` opens cleanly and the spawn pipeline works against a test WAV.
