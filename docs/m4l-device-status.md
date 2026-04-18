# StemForge M4L Device — Status & Current Blockers

**Date:** 2026-04-17
**Branch:** `feat/harness-patterns`
**Purpose:** Handoff doc for debugging the .amxd device build with a fresh Claude session.

---

## What StemForge is

StemForge is an audio stem separation tool. The v0 ship target is a `.pkg` installer for macOS (Apple Silicon) that installs:

1. **`stemforge-native`** — a C++ CLI binary wrapping ONNX Runtime + CoreML EP. Runs the `htdemucs_ft_fused` model (4-stem: drums/bass/vocals/other). 4.54s warm inference per 10s segment.
2. **`StemForge.amxd`** — a Max for Live audio effect device for Ableton Live 12.x. Contains a `node.script` object that spawns `stemforge-native` as a child process, parses its NDJSON event stream, and routes events (progress, stems, BPM, complete, error) to Max outlets. A companion `js` object uses the Live Object Model (LOM) to create new tracks with the separated stems.
3. **Bridge JS files** — `stemforge_bridge.v0.js` (node.script child) and `stemforge_loader.v0.js` (LOM track builder).

The `.pkg` installer + `stemforge-native` binary are fully working. The blocker is the `.amxd` device.

---

## What works

- **Binary:** `stemforge-native` is built, signed (ad-hoc), runs correctly. `--version` prints `0.0.0`. `warmup` triggers CoreML compile. `split` produces stems.
- **ONNX model:** `htdemucs_ft_fused.onnx` (697 MB, inline — no `.data` sidecar). CoreML EP claims 96.4% of nodes. 11× speedup vs unfused.
- **Installer:** `.pkg` (409 MB) bundles binary, dylib, .amxd, both JS files, manifest.json, fused ONNX model, .als template. `postinstall` deploys to correct paths and runs warmup.
- **Tests:** 28 pass / 2 skip / 0 fail across 4 test suites (binary, amxd structure, als structure, pkg layout).
- **Bridge JS:** `stemforge_bridge.v0.js` is well-structured Node.js code using `max-api`, `spawn`, `readline`. Has handlers for `split`, `cancel`, `ping`. Resolves binary via search paths. All unit-testable.

---

## What's broken: the .amxd container

The `.amxd` file is a proprietary binary container format used by Max for Live. We're generating it programmatically (no Max editor involved). The patcher JSON inside is correct — all UI elements, wiring, and objects are valid. **The container wrapping is wrong.**

### Container format (reverse-engineered)

```
Offset  Field          Notes
0       magic          b'ampf' (always)
4       version        u32 LE = 4
8       sentinel       b'aaaa' for audio effect, b'iiii' for instrument
12      b'meta'        chunk tag
16      meta_len       u32 LE = 4
20      meta_val       u32 LE: 1=plain device, 7=project device with embedded resources
24      b'ptch'        chunk tag
28      ptch_len       u32 LE: length of the patch body that follows
32+     ptch_body      Patcher JSON (+ optional embedded resources)
```

### What we've tried and what failed

#### Attempt 1: Simple container (sentinel=`iiii`, meta_val=1)
- Built by Track C agent during the original v0 multi-agent session.
- **Result:** Device loaded in Ableton but was categorized as an **instrument** (couldn't drag onto audio track). Sentinel `iiii` = instrument, not audio effect.

#### Attempt 2: Fixed sentinel to `aaaa`, meta_val=1, no embedded JS
- Device loaded and showed correct UI (title, drop zone, dropdowns, toggle, progress).
- Added `plugin~` / `plugout~` audio passthrough (required for audio effects).
- **Result:** Device could be placed on audio track. UI rendered. But `node.script` permanently showed "Node script not ready" — it couldn't find `stemforge_bridge.v0.js` because M4L copies the .amxd to a temp sandbox dir, and external JS files aren't co-located.

#### Attempt 3: Embedded JS using mx@c header (meta_val=7)
- Reverse-engineered from the old working `StemForgeDevice.amxd` (37 KB), which embeds JS after the patcher JSON.
- Old device structure: `mx@c` header (16 bytes) prefixes the ptch body, then JSON, then `\0`, then JS concatenated.
- Old device's mx@c header: `6d784063 00000010 00000000 00008f29` (big-endian fields).
- Replicated the format with our JSON + JS.
- **Result:** `StemForge.amxd: error -1 making directory` — Max couldn't unpack the project resources.

#### Attempt 4: Surgical replacement (old device container + new JSON)
- Took the old working device byte-for-byte, replaced only the patcher JSON, kept old JS and container structure.
- Updated ptch_len and mx@c total-size field.
- **Result:** Same "error -1 making directory" + "CreateDevice returned error 6: Device file broken."

### Why the old device works but our modifications don't

The old `StemForgeDevice.amxd` (37,017 bytes) loads fine in Ableton. Its structure:
- Sentinel: `aaaa`, meta_val: `7`
- mx@c header at ptch body offset 0
- Patcher JSON: 22,533 bytes
- Separator: `\n}\n\0`
- Embedded JS: 14,432 bytes (stemforge_bridge.js + stemforge_lom.js)

When we modify the JSON (changing its length), the mx@c header's size fields become inconsistent and Max rejects the file. The mx@c header has a field at offset 12 (big-endian u32) that we set to the new total size, but this might not be what that field represents — it could be a checksum, offset table, or something else.

**We don't have documentation for the mx@c container format.** The `.amxd` format is proprietary to Cycling '74 / Ableton.

---

## The core question

**How do we build a valid `.amxd` with embedded JS resources that Max for Live will accept?**

Options to explore:

1. **Use Max's CLI tooling** — `max -cli` or `max --build-collective` might be able to package a `.maxpat` + JS files into a valid `.amxd`. Need to check if Live 12's Max has headless build commands.

2. **Use Max interactively (one-time)** — Open the patcher JSON in Max, add the JS files to the project, then "Save as Device" to produce a valid `.amxd`. This is the fallback approach (Track C "Path 2" in the original spec) — a human step, but only done once.

3. **Deeper reverse engineering of mx@c** — Figure out what the fields at offsets 8 and 12 of the mx@c header actually mean. Maybe they're CRC32, or offsets to a resource table, or something we can compute.

4. **Avoid embedded JS entirely** — Find a way to make `node.script` discover external JS files. Options:
   - Add the JS directory to Max's file search path via `max.searchpath` or `Options → File Preferences`.
   - Use an absolute path in the `node.script` text (tested partially — `~/stemforge/m4l-js/stemforge_bridge.v0.js` — haven't confirmed if Max expands `~`).
   - Ship a Max package (a folder in `~/Documents/Max 8/Packages/` or similar) that puts the JS on the search path automatically.

5. **Use a different M4L object** — Instead of `node.script` (which needs Node.js file resolution), use `[shell]` or `[aka.shell]` to spawn the binary directly and parse stdout. Less elegant but avoids the JS embedding problem entirely.

---

## Key file locations

| File | Path | Notes |
|------|------|-------|
| Patcher builder | `v0/src/maxpat-builder/builder.py` | Generates the patcher JSON from `device.yaml` |
| Container packer | `v0/src/maxpat-builder/amxd_pack.py` | Wraps JSON into `.amxd` binary container |
| Build script | `v0/src/maxpat-builder/build_amxd.py` | CLI that runs builder → packer |
| Bridge JS | `v0/src/m4l-js/stemforge_bridge.v0.js` | Node.js script for node.script |
| Loader JS | `v0/src/m4l-js/stemforge_loader.v0.js` | Classic JS for LOM track creation |
| Device spec | `v0/interfaces/device.yaml` | UI layout + element definitions |
| NDJSON schema | `v0/interfaces/ndjson.schema.json` | Event protocol between binary and bridge |
| Old working device | `~/Music/Ableton/User Library/Presets/Audio Effects/StemForgeDevice.amxd` | 37 KB, loads fine, uses Python backend (not v0) |
| Built device | `v0/build/StemForge.amxd` | Current broken build |
| Installed device | `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/StemForge.amxd` | What Ableton sees |

---

## Environment

- macOS (Apple Silicon, Darwin 25.4.0)
- Ableton Live 12.2.7 (Suite)
- Max 9.0.8 (bundled with Live 12)
- Node for Max: installed at `/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/Max/Max.app/Contents/Resources/C74/packages/Node for Max/`
- Node.js binary: `.../Node for Max/source/bin/osx/node/node`
- `max-api`: `.../Node for Max/source/lib/exposed/max-api.js`

---

## What doesn't need to change

- The patcher JSON is correct (all UI objects, wiring, node.script reference, plugin~/plugout~ passthrough). Only the container wrapping is wrong.
- The bridge JS works (tested via unit tests, correct max-api usage).
- The native binary is fully operational.
- Everything EXCEPT the .amxd device packaging is ship-ready.
