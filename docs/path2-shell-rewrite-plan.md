# Path 2: Replace node.script with [shell] + Max-native NDJSON parsing

**Date:** 2026-04-17
**Why:** node.script is broken on macOS 26 (Darwin 25.4.0) with ALL available Max versions (9.0.8, 9.0.10). The Node.js child process interface never initializes — NULL pointer dereference crash confirmed. No Ableton/Max update fixes it. This is a Max bug that Cycling '74 hasn't patched yet.

**What we're keeping (everything except the bridge layer):**
- `stemforge-native` binary (working, 4.54s warm inference)
- `.pkg` installer (409 MB, deploys everything correctly)
- Patcher UI (all boxes, wiring, plugin~/plugout~ passthrough, project field)
- `.amxd` container format (aaaa sentinel, meta_val=1, plain unfrozen)
- Max Package at `~/Documents/Max 9/Packages/StemForge/` (confirmed detected by Max)
- `stemforge_loader.v0.js` for LOM track creation (uses classic `[js]`, not node.script — should work)
- ONNX model, postinstall warmup, .als template — all unchanged

**What we're replacing:**
- `node.script stemforge_bridge.v0.js` → `[shell]` external (Jeremy Bernstein, MIT)
- JS-based NDJSON parsing → Max-native parsing via `[regexp]` or `[dict.deserialize]`
- JS-based Max.outlet routing → Max `[route]` objects (already partially wired)

---

## Architecture

```
User drops wav → [dropfile] → file path
                                  ↓
[shell] spawns: stemforge-native forge <path> --json-events
                                  ↓
              stdout lines arrive at [shell] outlet
                                  ↓
              [route progress stem bpm complete error]
                                  ↓
         (each branch) → [dict.deserialize] or [regexp] → parse fields
                                  ↓
         progress → [live.slider] + [comment] (status text)
         stem → [js stemforge_loader.v0.js] (LOM track creation)
         bpm → [js stemforge_loader.v0.js]
         complete → [js stemforge_loader.v0.js]
         error → [comment] (error display)
```

Key difference: `[shell]` gives us stdout line-by-line just like node.script's readline, but it's a native Max external — no Node.js process manager involved.

---

## Implementation Steps

### 1. Download + install [shell] external (~5 min)

- GitHub: https://github.com/jeremybernstein/shell
- Download latest release (1.0b3 has arm64 universal binary)
- Install to `~/Documents/Max 9/Packages/StemForge/externals/shell.mxo`
  (or `~/Documents/Max 9/Library/shell.mxo`)
- Verify: create `[shell]` object in Max editor — no error

### 2. Update builder.py — replace node.script with [shell] (~30 min)

Replace the node.script box with:

```python
# [shell] object — spawns stemforge-native, stdout arrives at outlet 0
boxes.append(_box(
    OBJ_BRIDGE, "newobj",
    (16.0, y, 280.0, 22.0),
    numinlets=1, numoutlets=2,
    outlettype=["", ""],
    extras={"text": "shell"},
))
```

Wire the split-command assembly to format a shell command string:
```
[sprintf symout stemforge-native forge %s --json-events --variant ft-fused]
    → [shell]
```

The `[shell]` object:
- Receives a command string at inlet → spawns process
- Outputs stdout line-by-line at outlet 0
- Outputs stderr at outlet 1 (or status messages)

### 3. NDJSON parsing in Max (~45 min)

Each stdout line from [shell] is a JSON string like:
```json
{"event":"progress","pct":50,"phase":"separating"}
{"event":"stem","name":"drums","path":"/tmp/stems/drums.wav"}
{"event":"complete","manifest":"/tmp/stems/stems.json","bpm":120}
```

Two approaches to parse:

**Approach A — [dict.deserialize] (preferred):**
```
[shell] stdout → [dict.deserialize] → [dict] → [dict.unpack event: pct: phase: name: path: ...]
                                                    ↓
                                            [route progress stem bpm complete error]
```

**Approach B — [regexp] (fallback if dict.deserialize chokes on NDJSON):**
```
[shell] stdout → [regexp "event":"(\w+)"] → event type
                 [regexp "pct":(\d+)] → pct value
                 etc.
```

Approach A is cleaner. `[dict.deserialize]` parses JSON strings into Max dicts natively.

### 4. LOM integration via [js] (~15 min)

`stemforge_loader.v0.js` uses classic `[js]` (not node.script) for LOM/LiveAPI access. This should already work since `[js]` doesn't have the same process-spawning bug. The loader receives stem paths + BPM and creates Ableton tracks.

Wire: `complete` route → `[js stemforge_loader.v0.js]`

### 5. Rebuild .amxd + test (~30 min)

- Rebuild with `build_amxd.py`
- Deploy to Ableton User Library
- Test: drop wav, verify stems appear
- Verify [shell] doesn't have the same macOS 26 issues (it shouldn't — it's a simple posix_spawn, not a full Node.js runtime)

### 6. Update installer (~15 min)

- Add `shell.mxo` to the Max Package or bundle it in the .pkg
- The external needs to be in Max's search path (package `externals/` folder)

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| [shell] external also broken on macOS 26 | Low — it's simple posix_spawn, not a managed runtime | Test immediately after download, before building anything |
| [shell] arm64 binary missing from latest release | Low — 1.0b3 ships universal | Verify with `file shell.mxo/Contents/MacOS/shell` |
| [dict.deserialize] can't parse NDJSON lines | Medium — may need preprocessing | Fall back to [regexp] or [js]-based parsing |
| [js] (classic, for loader) also broken on macOS 26 | Low — [js] uses SpiderMonkey, not Node | The old StemForgeDevice.amxd's [js] errors were "no function" (file not found), not crashes |
| [shell] not freezable into .amxd | N/A — we're unfrozen, shell.mxo lives in the Max Package | Already solved by package approach |

---

## Estimated time

| Step | Time |
|------|------|
| Download + verify [shell] | 5 min |
| Update builder.py | 30 min |
| NDJSON parsing in Max | 45 min |
| LOM wiring | 15 min |
| Rebuild + test | 30 min |
| Installer update | 15 min |
| **Total** | **~2.5 hours** |

---

## Files to modify

- `v0/src/maxpat-builder/builder.py` — replace node.script box with [shell] + parsing chain
- `v0/src/m4l-package/StemForge/externals/shell.mxo` — new dependency
- `v0/build/build-pkg.sh` — bundle shell.mxo in installer
- `v0/src/installer/scripts/postinstall` — deploy shell.mxo (may already work via package)

## Files unchanged

- `v0/src/m4l-js/stemforge_loader.v0.js` — LOM loader stays as [js]
- `v0/src/m4l-js/stemforge_bridge.v0.js` — no longer needed (remove or archive)
- `v0/src/maxpat-builder/amxd_pack.py` — container format unchanged
- `v0/interfaces/device.yaml` — UI spec unchanged
- `v0/interfaces/ndjson.schema.json` — event protocol unchanged
- Everything under `v0/src/A/` — binary unchanged
