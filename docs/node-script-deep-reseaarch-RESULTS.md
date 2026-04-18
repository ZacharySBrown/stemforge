# Why node.script is broken and what to do about it

**The failure is almost certainly a macOS 15 code-signing enforcement issue, not a packaging or provenance-xattr problem.** The symptom pattern — bundled `node` binary runs fine from Terminal, but fails only when spawned as a child of the signed `Ableton Live.app` — is the exact fingerprint of hardened-runtime / library-validation policy tightening that Apple rolled out in macOS 15.6.x security updates in late 2025. A recent Cycling '74 forum thread ("Max 8 and 9 hang on macOS 15.6.1 (Sequoia, M4 Max), full diagnostics done", Oct 2025) confirms a related process-spawning regression on the same OS line. `com.apple.provenance` is a red herring: Howard Oakley's detailed analyses (May 2023, Dec 2025) establish that provenance is a tracking xattr, not an enforcement mechanism. The strategic implication: **stop trying to fix the .amxd JSON; the JSON is fine. Fix the signing/entitlements situation, or design around node.script entirely.**

## macOS 15 is the culprit, and Max 9.0.8 is frozen in place

Multiple independent pieces of evidence converge on a **parent-process launch-policy failure**:

- **Provenance is benign.** `com.apple.provenance` is an 11-byte xattr Apple writes after first successful Gatekeeper clearance, keyed into `/var/db/SystemPolicyConfiguration/ExecPolicy`. Its presence without `com.apple.quarantine` is the *expected* state for a binary that's been vetted once. It has no documented `execve`-blocking behavior. Known side-effects are limited to cosmetic issues (Docker cache invalidation, Syncthing sync, Zed file ops).
- **Hardened runtime + library validation is the real enforcement layer.** When a signed parent app (Live, with hardened runtime) spawns a bundled helper, macOS validates the helper against the parent's signature policy. If the helper lacks required entitlements — **`com.apple.security.cs.allow-jit`, `com.apple.security.cs.allow-unsigned-executable-memory`, `com.apple.security.cs.disable-library-validation`, `com.apple.security.cs.allow-dyld-environment-variables`** — the child is SIGKILLed before execution reaches your code. The exact fingerprint appears in LM Studio issue #1494 (Feb 2026, native Node addons dying with `ERR_DLOPEN_FAILED` across Team IDs) and opencode #18503 (macOS 26 SIGKILL, resolved by `codesign --force --sign -`). These are the same class of bug.
- **The node.script symptom precisely matches a parent-spawned child that never reaches the handshake.** Cycling '74's own lifecycle docs list seven states (`start`, `loadstart`, `loadend`, `stop`, `terminated`, `restarting`, `restarted`). "Node script not ready, can't handle message X" means the child process has not reached `loadend` — either the Node process manager never started, or it started but immediately died. C74's Jeremy Bernstein has acknowledged on the forums that node.script in Max 9 M4L/standalone contexts has an open bug with crash stacks showing `maxnode_protocol_connection_connect` → `node_child_process_interface_new`, which is consistent with a code-signing kill rather than a logic bug.
- **Max 9.0.8 shipped Aug 19, 2025 with zero node.script fixes.** The changelog trail is unambiguous: 9.0.3 fixed `.mjs` resolution, 9.0.5 fixed an npm install crash, 9.0.8/9.0.9/9.0.10 changed nothing for node.script. **Max 9.1.0 bundles Node v22.18** (up from your v20.6.1) and ships inside Ableton Live 12.4 beta — this is the first version where the node binary may have been re-signed with entitlements that satisfy macOS 15.6's tightened enforcement.

## Ordered diagnostic and fix path

Do these in order until the symptom clears. The first three are non-destructive; the last two modify signed bundles.

1. **Enable the Node for Max debug log**: Max → Preferences → "Node for Max" → tick *Enable debug log*, set a path like `~/Documents/n4m.log`, restart Live, reopen the device. This is the single most informative step and is C74's standard opening diagnostic.
2. **Launch Live from Terminal and watch security daemons live.** Run `/Applications/Ableton\ Live\ 12\ Suite.app/Contents/MacOS/Live 2>&1 | tee ~/live.log` in one terminal, and `log stream --predicate 'process == "amfid" OR process == "syspolicyd" OR eventMessage CONTAINS "node"' --info` in another. Reproduce the failure. If you see `CODESIGNING` or `AMFI` messages referencing the bundled node path, you've confirmed the hypothesis.
3. **Verify the bundled node binary's signature and entitlements**: `codesign -dvvv --entitlements - /path/to/Node\ for\ Max/source/bin/osx/node/node`. If entitlements are missing or Team ID differs from Live's, that's the smoking gun. Check Live's own: `codesign -dvvv --entitlements - /Applications/Ableton\ Live\ 12\ Suite.app`.
4. **Upgrade the stack.** Install **Ableton Live 12.4 beta**, which bundles **Max 9.1.4 with Node v22.18**. If C74 re-signed the new node binary, this fixes the problem outright with no patching. This is the cleanest path.
5. **Ad-hoc re-sign the bundled node binary with the four critical entitlements** (as a last resort; breaks Live's outer signature and requires re-signing Live too):
   ```bash
   codesign --force --sign - --options runtime \
     --entitlements /tmp/node.entitlements.plist \
     "/path/to/Node for Max/source/bin/osx/node/node"
   codesign --force --deep --sign - "/Applications/Ableton Live 12 Suite.app"
   ```
   where the plist grants `allow-jit`, `allow-unsigned-executable-memory`, `disable-library-validation`, and `allow-dyld-environment-variables`. Also run `sudo xattr -cr "/Applications/Ableton Live 12 Suite.app"` and `sudo xattr -cr "$HOME/Library/Application Support/Cycling '74/Max 9"` for a clean slate.

**Xattr-only fixes (`xattr -cr`, `xattr -dr com.apple.provenance`) almost certainly will not work by themselves**, because provenance isn't the gate. They're worth including in step 5 only as cleanup.

## The .amxd JSON is not your problem — but this is what a correct one looks like

All real-world node.script devices — from the Vimeo n4m-vimeo player to delucis/n4m-socket-demo to caenopy/lab (a real .amxd) — use **an identical, trivial box structure**. The node.script object is a plain `newobj`, the filename is the first token of the `text` field, and there are exactly five `saved_object_attributes`:

```json
{
  "box": {
    "id": "obj-1",
    "maxclass": "newobj",
    "numinlets": 1,
    "numoutlets": 2,
    "outlettype": ["", ""],
    "patching_rect": [0, 0, 115, 22],
    "saved_object_attributes": {
      "autostart": 0,
      "defer": 0,
      "node_bin_path": "",
      "npm_bin_path": "",
      "watch": 0
    },
    "text": "node.script myscript.js"
  }
}
```

Older Max used `"node"` and `"npm"` as the attribute keys; Max 8.5+ writes `"node_bin_path"` and `"npm_bin_path"`. Both forms are accepted.

Where programmatic builders typically go wrong is **outside the box**, at the patcher-level dependency declaration. Manually-saved devices include a `dependency_cache` array listing the script file with a `bootpath`, `patcherrelativepath`, and `type: "TEXT"`. More importantly, node.script inside an .amxd is resolved against a runtime-expanded temp directory (`~/Library/Application Support/Cycling '74/Max 9/Settings/temp64-live/mxt/{deviceName}_coll_{uid}/`), not against the `.amxd` file's on-disk location. The **officially sanctioned layout** is a Max Project (`meta_val=7` in the amxd header) with a `node_content/` subfolder added to the project's Search Path and the **"Embedded" flag enabled** — this is what the Cycling '74 `03_n4m_projects_devices` vignette specifies, and it's what Florian Demmer prescribes on the forums. Ableton's own `amxd_textconv.py` parser in `github.com/Ableton/maxdevtools/maxdiff/` is the authoritative reference for the binary header (28-byte `ampf`/`meta` chunk, 4-byte LE length, JSON payload, binary footer, 4CC device type codes like `aeff`, `mdev`, `inst`, `ptch`).

## node.script attributes, the @embed mystery, and node.codebox

The complete, documented attribute list in Max 9.0.8 is **`args`, `autostart`, `defer`, `log_path`, `node_bin_path`, `npm_bin_path`, `pm_path`, `restart`, `running` (read-only), `watch`**. There is **no `@verbose`, no `@debug`, no `@script`, and no `@embed`**. For verbose diagnostics, set `@log_path ~/Documents/debug.txt` — this is the closest thing to verbose logging node.script offers.

The **`@embed` attribute is a documentation error in the Max 9.0.0 release notes.** Those notes explicitly named node.script in the "Embedded Textfile Support" section, but the feature was only ever implemented on the codebox variants (`v8.codebox`, `text.codebox`, `osc.codebox`, `dict.codebox`, `gen.codebox`). The current ref page for `node.script` lists no `embed` attribute — and Max 9.0.8 correctly rejects `@embed` as invalid. `node.codebox` is a real object (pairs a text-editor UI with the same Node engine, same attributes otherwise, same "not ready" states and lifecycle), but even its current reference page does not document an `embed` attribute despite analogy with its siblings. Treat the release-notes claim as aspirational and move on.

For startup mechanics: **`@autostart 1` spawns the child process when the object is created**, no explicit `script start` needed; otherwise you must send `script start [optional args]` to the inlet. The `@args` attribute supplies CLI arguments to an autostarted script. After five unhandled crashes in a row, node.script stops auto-restarting until it gets a fresh `script start`. Use `script processStatus` or `script running` to probe the state, and `script reboot` to force-reset a wedged process manager.

## If you can't fix the signing problem, these are your fallbacks

Given the node.script fragility pattern across Max versions (the forum archive is littered with "node process manager not running" threads going back to 2022), designing around node.script is a defensible strategy even if you fix the immediate issue. The comparison landscape looks like this:

| Architecture | Can spawn processes? | Freezes into .amxd? | Apple Silicon / macOS 15 | Maintenance |
|---|---|---|---|---|
| **[v8] + XMLHttpRequest → localhost HTTP** | No (HTTP only) | Yes, native | Fully native | First-party, actively developed |
| **[maxurl] → localhost HTTP** | No (HTTP only) | Yes, native | Fully native | First-party, stable |
| **[shell] external (Jeremy Bernstein)** | Yes | Yes, cross-platform | arm64 fat binary in 1.0b3 | Stable, unmaintained since July 2021 |
| **[jweb] + local HTTP/WS** | No (but does WebSocket) | Partial (HTML-load workaround needed) | Yes (CEF v135) | First-party, inconsistent in M4L |
| **[mxj] + Java ProcessBuilder** | Yes | External freezes, JRE does not | Yes if user installs JRE | Dealbreaker UX |

**The strongest recommendation for a stem-separation M4L device:** make `stemforge-native` a local HTTP server (FastAPI or an equivalent Rust HTTP framework), use **`[shell]` (frozen into the .amxd) to launch it on device load**, and communicate via **`[v8]` with XMLHttpRequest** (new in Max 9.1) or **`[maxurl]`**. This is entirely self-contained in a single `.amxd`, works on Apple Silicon and macOS 15, and sidesteps the node.script spawn problem completely. The `[shell]` external is MIT-licensed and ships an arm64 universal binary. The one caveat: `[v8]`'s XMLHttpRequest currently only supports `responseType: "text"` — for binary audio returns you'll need base64 framing or the Max-specific `_setRequestKey("filename_out", path)` extension to stream directly to a file on disk.

Avoid `[mxj]`: M4L does not bundle a JRE, and requiring end users to install Java is a UX death knell (the RhythmVAE_M4L and deeploops M4L devices documented this pain clearly). Avoid a custom C external just for process-spawning: you'd be reinventing `[shell]` at high engineering cost. `[jweb]` is only worth it if you genuinely need long-lived bidirectional WebSocket streaming, and even then you'll fight its known frozen-amxd HTML-loading bug.

## The short version

**The device JSON is fine; macOS 15.6.x + hardened runtime enforcement is killing the child Node process before it can handshake.** Enable the Node for Max debug log, watch `amfid`/`syspolicyd` via `log stream`, and try Live 12.4 beta (which bundles Max 9.1.4 with a freshly-signed Node v22.18) before you touch any signatures yourself. If upgrading isn't an option, ad-hoc re-sign the bundled node with the four standard JIT/library-validation entitlements. And regardless of whether you fix this, seriously consider moving to a **`[shell]` launches a local HTTP server + `[v8]` talks to it** architecture — that's the pattern the stem-separation M4L ecosystem (spleeter4max, demucs4max) has converged on for good reason, and it removes node.script from your critical path permanently.