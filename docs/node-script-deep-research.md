# node.script in M4L: Deep Research Brief

**Date:** 2026-04-17
**Goal:** Figure out why `node.script` never initializes in our programmatically-built `.amxd`, and find the correct way to build a working M4L device with `node.script` from CI (no Max GUI interaction required).

---

## The Problem

We have a programmatically-generated `.amxd` (Max for Live audio effect device) that contains a `node.script` object referencing `stemforge_bridge.v0.js`. The patcher JSON is valid — all other objects instantiate correctly (confirmed via `loadbang → print` diagnostic). But `node.script` never transitions to "ready" state. Every message sent to it returns:

```
node.script: Node script not ready can't handle message <whatever>
```

No error about the JS file not being found. No crash. No output from the JS at all. The Node.js process simply never starts.

**Critical finding:** An older `.amxd` device on the same machine (`StemForgeDevice.amxd`, created manually in Max months ago) ALSO shows "Node script not ready" now. This means node.script may be broken system-wide, OR the old device's cached/stale state is causing it to fail too.

**However:** When we create a bare `node.script` object in Max's editor (by opening an empty Max Audio Effect and typing `node.script`), it instantiates without errors in the Max Console. We haven't yet confirmed whether it actually RUNS JS — just that it doesn't show errors on creation.

---

## Environment

- macOS Darwin 25.4.0 (Apple Silicon)
- Ableton Live 12.2.7 (Suite)
- Max 9.0.8 (bundled inside Ableton)
- Node.js v20.6.1 (bundled inside Max at `.../Node for Max/source/bin/osx/node/node`)
- Node binary runs fine from Terminal: `node --version` → `v20.6.1`
- Node binary has `com.apple.provenance` xattr (NOT `com.apple.quarantine`)
- `max-api` module exists at `.../Node for Max/source/lib/exposed/max-api.js`

---

## What We've Tried (Exhaustive)

### Container format variations

| # | Sentinel | meta_val | mx@c header | Result |
|---|----------|----------|-------------|--------|
| 1 | `iiii` | 1 | No | Device loaded but was categorized as instrument (wrong sentinel). node.script "not ready". |
| 2 | `aaaa` | 1 | No | Device loaded as audio effect. UI rendered correctly. plugin~/plugout~ passthrough works. node.script "not ready". |
| 3 | `aaaa` | 7 | Yes (our construction) | "error -1 making directory" — Max couldn't unpack project resources. |
| 4 | `aaaa` | 7 | Yes (surgically copied from old working .amxd, only JSON replaced) | "CreateDevice returned error 6: Device file broken." |
| 5 | `aaaa` | 1 | No, with `project` field in JSON | "project without a name" error gone. UI works. node.script still "not ready". |

### JS file resolution attempts

| # | Approach | Result |
|---|----------|--------|
| 1 | JS files next to .amxd in User Library (`~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/`) | "not ready" — M4L likely sandboxes .amxd to temp dir |
| 2 | JS in Max Package (`~/Documents/Max 9/Packages/StemForge/javascript/`) | "not ready" — node.script may not search package `javascript/` dirs |
| 3 | JS at absolute path with no spaces (`/Users/zak/stemforge/m4l-js/stemforge_bridge.v0.js`) in the object text | "not ready" |
| 4 | JS in Max User Library (`~/Documents/Max 9/Library/`) | "not ready" |
| 5 | `@embed 1` attribute on node.script (Max 9 feature per release notes) with JS source inline in patcher JSON | `"embed" is not a valid attribute argument` — @embed not supported on node.script in Max 9.0.8 |

### node.script object configuration variations

| # | Object text | Extra attributes | Result |
|---|-------------|-----------------|--------|
| 1 | `node.script stemforge_bridge.v0.js` | None | "not ready" |
| 2 | `node.script stemforge_bridge.v0.js @autostart 1` | None | "not ready" |
| 3 | `node.script @autostart 1 stemforge_bridge.v0.js` | None | "not ready" |
| 4 | `node.script @autostart 1 @file stemforge_bridge.v0.js` | None | "not ready" |
| 5 | `node.script /Users/zak/stemforge/m4l-js/stemforge_bridge.v0.js @autostart 1` | None | "not ready" |
| 6 | `node.script stemforge_bridge.v0.js @autostart 1` | `saved_object_attributes: {autostart:1, defer:0, watch:0}`, `textfile: {filename, flags:0, embed:0, autowatch:1}` (matching old working device) | "not ready" |
| 7 | `node.script @autostart 1 @embed 1` | `textfile: {embed:1, text: <entire JS source>}` | `"embed" is not a valid attribute argument` |

### Other diagnostics

- **loadbang → print** fires correctly: `[StemForge-v0-loaded]: bang` ✓
- **loadbang → node.script** (bang as startup nudge): `Node script not ready can't handle message bang`
- **Old StemForgeDevice.amxd** (manually created in Max months ago, 37KB with embedded JS): ALSO shows "not ready" now. Previously worked.
- **Bare `node.script` in Max editor**: creates without console errors, but we haven't tested if it actually executes JS.
- **Node binary from Terminal**: runs fine, `v20.6.1`.

### Ownership/permissions

- All JS files verified `zak:staff`, mode `-rw-r--r--`
- .amxd file verified `zak:staff`
- Package dir verified `zak:staff`
- Node binary is `zak:staff`, mode `-rwxr-xr-x`, has `com.apple.provenance` xattr

---

## Questions for Research

### 1. How does node.script actually find and load its JS file?

- What is the exact file resolution order? Does it search:
  - The device's project bundle (for frozen devices)?
  - The .amxd's containing directory?
  - Max's search path?
  - Max Package `javascript/` folders?
  - Something else entirely?
- Is there a difference in resolution between:
  - Standalone Max vs. Max inside Ableton Live (M4L context)?
  - Frozen vs. unfrozen .amxd?
  - Project devices (meta_val=7) vs. plain devices (meta_val=1)?
- Does `node.script` use Max's `search_path` or does it use Node.js's own `require()` resolution?

### 2. How does node.script start its Node.js process?

- What triggers the transition from "not ready" to "ready"?
- Does `@autostart 1` actually auto-start the script, or does it need a `script start` message?
- In the Max editor, when you create `node.script @autostart 1`, does it auto-start? Or do you need to explicitly start it?
- Is there a way to see verbose startup logs from node.script? (e.g., `@verbose 1`?)
- What are ALL the valid attributes for `node.script` in Max 9?

### 3. What is the correct way to create a working node.script device from script/CI?

- Cycling '74's "m4l-production-guidelines" says unfrozen devices with dependencies need those dependencies resolvable. What is the exact resolution mechanism for node.script?
- Is there a way to use `@embed` with node.script in any Max 9.x version? The release notes mention it for `v8, node.script, js` but Max 9.0.8 rejects it.
- Does `node.codebox` (the inline-code variant of node.script) work differently? Can it be used programmatically?
- Has anyone successfully built a working M4L device with node.script via scripting (not the Max GUI)?

### 4. Is `@embed` really not supported on node.script?

- Max 9.0 release notes say: "Save the text of v8, node.script, jit.gl.slab, jit.gl.shader and jit.gl.pass objects right in the patcher with the embed attribute."
- But Max 9.0.8 says `"embed" is not a valid attribute argument` when used on node.script.
- Was @embed removed? Never implemented for node.script? Only for v8?
- Is there a different attribute name or syntax?
- Is there a `node.codebox` object that supports inline code?

### 5. Why is node.script broken system-wide on this machine?

- The old manually-created device used to work (we saw `python_path missing` output from it earlier in the session) but now shows "not ready".
- Did a macOS update (Darwin 25.4.0) break Node for Max?
- Does the `com.apple.provenance` xattr on the node binary cause issues when launched FROM Max (vs. from Terminal)?
- Is there a TCC (Transparency, Consent, Control) permission that Max needs to spawn child processes?
- Does `xattr -dr com.apple.quarantine "/Applications/Ableton Live 12 Suite.app"` fix it?
- Is there a known Max 9.0.8 bug with node.script?

### 6. What does the manual "create in Max editor" workflow actually produce?

- When you create `node.script @autostart 1` in Max's editor, paste JS, and Cmd+S the device:
  - What does the resulting .amxd binary look like?
  - Is the JS embedded? In what format?
  - What container format is used (sentinel, meta_val)?
  - What extra JSON fields are added that our builder misses?
- Can we diff a manually-saved device against our programmatic one to find the gap?

### 7. Alternative architectures that avoid node.script entirely

- Can `[v8]` spawn child processes in Max 9? (Research doc says no, but verify.)
- Can `[v8 @embed 1]` + `[shell]` (Jeremy Bernstein's external) work as a combo? v8 handles JS/LOM, shell spawns the binary.
- Is there a way to use Max's `[mxj]` (Java) to spawn processes?
- Could we use a Unix domain socket or HTTP server architecture instead? `stemforge-native` runs as a daemon, M4L device connects to it via `[v8]` + WebSocket/HTTP.

---

## Key Files for Reference

| File | What it is |
|------|-----------|
| `v0/src/maxpat-builder/builder.py` | Generates patcher JSON from device.yaml |
| `v0/src/maxpat-builder/amxd_pack.py` | Wraps patcher JSON into .amxd binary container |
| `v0/src/m4l-js/stemforge_bridge.v0.js` | The node.script JS bridge (spawns stemforge-native, parses NDJSON) |
| `v0/src/m4l-js/stemforge_loader.v0.js` | LOM track builder (creates Ableton tracks with stems) |
| `v0/interfaces/device.yaml` | UI layout spec |
| `v0/interfaces/ndjson.schema.json` | Binary ↔ bridge event protocol |
| `~/Music/Ableton/User Library/Presets/Audio Effects/StemForgeDevice.amxd` | Old working device (37KB, mx@c format, NOW also broken) |
| `docs/device_packaging_research.md` | Prior research on .amxd packaging approaches |
| `docs/m4l-device-status.md` | Status doc with container format details |

---

## What a Successful Answer Looks Like

1. A concrete explanation of WHY node.script shows "not ready" in our device (and ideally why the old device also broke).
2. A working recipe for producing a `.amxd` with functional `node.script` from a script — no Max GUI required. Either:
   - The correct JSON fields/container format that makes node.script find external JS
   - A working `@embed` or `node.codebox` approach for inlining JS
   - A Max Package layout that node.script actually searches
3. If fully programmatic is impossible: the minimal one-time manual step (and whether it can be scripted via `osascript` or Max's scripting interface).
