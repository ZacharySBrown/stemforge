// stemforge_bridge.v0.js
// ─────────────────────────────────────────────────────────────────────────────
// Node-for-Max child script. Loaded inside StemForge.amxd by a [node.script]
// object. Owns the subprocess lifecycle for `stemforge-native` and translates
// its NDJSON event stream (v0/interfaces/ndjson.schema.json) into Max outlets.
//
// Events emitted on the single node.script outlet (first element = event type):
//   progress  <pct:float>  <phase:symbol>
//   stem      <name:symbol>  <path:symbol>  [size_bytes:int]
//   bpm       <bpm:float>  [beat_count:int]
//   slice_dir <stem:symbol> <dir:symbol> <count:int>
//   complete  <manifest:symbol> [bpm:float] [stem_count:int]
//   error     <phase:symbol> <message:symbol>
//
// Handlers accepted on the inlet:
//   split <audioPath> <pipeline> <backend> <slice01>
//   cancel
//   ping
//
// Binary resolution: search_paths from device.yaml (in priority order):
//   $AMXD_DIR/../bin/stemforge-native
//   ~/Library/Application Support/StemForge/bin/stemforge-native
//   /usr/local/bin/stemforge-native
//   /opt/homebrew/bin/stemforge-native
//
// max-api is an npm module shipped with Ableton's Node for Max runtime;
// reference it here as `max-api`. The export surface we rely on is small
// enough that the tests stub a fake one (see tests/fake_max_api.js).
// ─────────────────────────────────────────────────────────────────────────────

"use strict";

const Max = require("max-api");
const { spawn } = require("child_process");
const readline = require("readline");
const path = require("path");
const fs = require("fs");
const os = require("os");

const BINARY_NAME = "stemforge-native";

// Search paths from v0/interfaces/device.yaml. Kept in sync manually; a
// device-regen step will refresh this list as part of the build.
const SEARCH_PATHS = [
    // Relative to .amxd location — resolved at call time using __dirname.
    (amxdDir) => path.join(amxdDir, "..", "bin", BINARY_NAME),
    () => path.join(os.homedir(), "Library", "Application Support", "StemForge", "bin", BINARY_NAME),
    () => path.join("/usr/local/bin", BINARY_NAME),
    () => path.join("/opt/homebrew/bin", BINARY_NAME),
];

let child = null;

function logInfo(msg) {
    try { Max.post(String(msg)); } catch (_) {}
}

function logError(msg) {
    try {
        const lvl = (Max.POST_LEVELS && Max.POST_LEVELS.ERROR) || undefined;
        if (lvl !== undefined) { Max.post(String(msg), lvl); return; }
    } catch (_) {}
    try { Max.post("[stemforge error] " + String(msg)); } catch (_) {}
}

function resolveBinary() {
    // __dirname is where node.script copied the .js — typically next to the
    // unpacked .amxd project. That's not guaranteed; we also try the path
    // relative to the user's Ableton install under Application Support.
    const candidates = [];
    for (const fn of SEARCH_PATHS) {
        try {
            candidates.push(fn(__dirname));
        } catch (_) { /* ignore */ }
    }
    for (const p of candidates) {
        if (!p) continue;
        try {
            if (fs.existsSync(p)) {
                // Verify it's executable; fs.accessSync throws otherwise.
                fs.accessSync(p, fs.constants.X_OK);
                return p;
            }
        } catch (_) { /* keep looking */ }
    }
    return null;
}

function emitEvent(evt) {
    // Each branch calls Max.outlet with positional args matching the bridge
    // contract. Downstream [route] object in the .maxpat splits by symbol.
    try {
        switch (evt.event) {
            case "started":
                // Mirror started as a progress(0, starting) — most UIs don't
                // care to distinguish.
                Max.outlet("progress", 0, "starting");
                break;
            case "progress":
                Max.outlet("progress", Number(evt.pct) || 0, String(evt.phase || ""));
                break;
            case "stem":
                Max.outlet("stem", String(evt.name), String(evt.path),
                    evt.size_bytes != null ? Number(evt.size_bytes) : 0);
                break;
            case "bpm":
                Max.outlet("bpm", Number(evt.bpm), Number(evt.beat_count) || 0);
                break;
            case "slice_dir":
                Max.outlet("slice_dir", String(evt.stem), String(evt.dir),
                    Number(evt.count) || 0);
                break;
            case "complete":
                Max.outlet("complete", String(evt.manifest),
                    Number(evt.bpm) || 0, Number(evt.stem_count) || 0);
                break;
            case "error":
                Max.outlet("error", String(evt.phase || ""), String(evt.message || ""));
                break;
            default:
                logInfo("[bridge] unknown event: " + JSON.stringify(evt));
        }
    } catch (e) {
        logError("outlet failed: " + e.message);
    }
}

function parseAndEmit(line) {
    line = String(line).trim();
    if (!line) return;
    let evt;
    try {
        evt = JSON.parse(line);
    } catch (_) {
        // stemforge-native may print non-JSON diagnostic lines; forward as
        // console log so the user can see them, but do not emit.
        logInfo("[stdout] " + line);
        return;
    }
    if (!evt || typeof evt !== "object" || !evt.event) {
        logInfo("[stdout non-event] " + line);
        return;
    }
    emitEvent(evt);
}

function runSplit(audioPath, pipeline, backend, sliceFlag) {
    if (child) {
        Max.outlet("error", "busy", "previous job still running — send cancel first");
        return;
    }
    const binary = resolveBinary();
    if (!binary) {
        Max.outlet(
            "error",
            "binary_missing",
            "stemforge-native not found in any search path; install via .pkg"
        );
        return;
    }
    if (!audioPath || !fs.existsSync(String(audioPath))) {
        Max.outlet("error", "input_missing", "audio file not found: " + audioPath);
        return;
    }

    const args = [
        "forge",
        String(audioPath),
        "--json-events",
        "--pipeline", String(pipeline || "default"),
        "--backend", String(backend || "auto"),
    ];
    if (Number(sliceFlag) === 1 || sliceFlag === true || String(sliceFlag) === "true") {
        args.push("--slice");
    }

    logInfo("[bridge] spawn: " + binary + " " + args.join(" "));

    try {
        child = spawn(binary, args, { stdio: ["ignore", "pipe", "pipe"] });
    } catch (e) {
        Max.outlet("error", "spawn_failed", e.message);
        child = null;
        return;
    }

    const rl = readline.createInterface({ input: child.stdout });
    rl.on("line", parseAndEmit);

    child.stderr.on("data", (chunk) => {
        logInfo("[stemforge-native stderr] " + String(chunk).trim());
    });

    child.on("error", (err) => {
        Max.outlet("error", "child_error", err.message);
    });

    child.on("close", (code, signal) => {
        child = null;
        if (code !== 0 && !signal) {
            Max.outlet("error", "exit_nonzero", "exit code " + code);
        }
    });
}

function cancel() {
    if (!child) {
        logInfo("[bridge] no active job");
        return;
    }
    try { child.kill("SIGTERM"); } catch (_) {}
}

// ── Max handlers ──────────────────────────────────────────────────────────────
Max.addHandler("split", (audioPath, pipeline, backend, sliceFlag) => {
    runSplit(audioPath, pipeline, backend, sliceFlag);
});

Max.addHandler("cancel", () => cancel());

Max.addHandler("ping", () => {
    const bin = resolveBinary();
    if (bin) {
        Max.outlet("progress", 0, "ready");
        logInfo("[bridge] binary: " + bin);
    } else {
        Max.outlet("error", "binary_missing", "run installer");
    }
});

// ── Test hooks — only active when required from tests, not from Max ──────────
// The surface needed for unit testing: parse a line and observe outlets. We
// attach parseAndEmit to module.exports so tests can import without spawning
// a real binary. Guarded by a typeof check so Max never sees it.
if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        parseAndEmit,
        emitEvent,
        resolveBinary,
        SEARCH_PATHS,
    };
}
