// stemforge_bridge.js
// ─────────────────────────────────────────────────────────────────────────────
// Node for Max script — bridges the StemForge Python backend to a Max for Live
// device. Spawns `stemforge forge` as a subprocess, streams newline-delimited
// JSON progress events to the patch, and emits one `load <wav_path> <pad_idx>`
// message per curated bar on completion.
//
// Division of responsibility with stemforge_lom.js:
//   - stemforge_lom.js (classic Max [js], same patch) reads the clip via LOM,
//     writes an analysis JSON to a temp file, and sends a `run <audio> <json>
//     <nbars> <strategy>` message into this node.script's inlet. This split
//     is deliberate: node.script cannot reach the Live Object Model, only
//     classic-JS [js] objects can. Keeping the LOM read out of this file lets
//     the bridge focus on subprocess orchestration.
//
// Python discovery:
//   Reads ~/.stemforge/python_path (written by install.sh) — a single line
//   pointing at the absolute path of the venv's python executable. The
//   subprocess is spawned with -m stemforge.cli so there's no need for a
//   separate `stemforge` entrypoint on PATH (gotcha 5.2).
//
// Outlets:
//   0 — status/progress messages for the UI:
//         `started`
//         `progress <phase> <pct>`
//         `status <text>`
//         `error <text>`
//         `done`
//   1 — polybuffer~ loader commands:
//         `clear`
//         `load <abs_wav_path> <pad_index>` (one per curated bar)
//         `ready <bars>` after all loads are emitted
//         `manifest <abs_manifest_path>` with the source bar BPM for tempo sync
// ─────────────────────────────────────────────────────────────────────────────

const Max = require("max-api");
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

let child = null;
let focusStem = "drums";
let lastOutputDir = null;
let lastManifestPath = null;

function resolvePython() {
    const p = path.join(os.homedir(), ".stemforge", "python_path");
    try {
        const raw = fs.readFileSync(p, "utf8").trim();
        if (!raw) return null;
        if (!fs.existsSync(raw)) return null;
        return raw;
    } catch (e) {
        return null;
    }
}

function emitStatus(msg) {
    Max.outlet("status", String(msg));
    Max.post(msg);
}

function emitError(msg) {
    Max.outlet("error", String(msg));
    Max.post(msg, Max.POST_LEVELS.ERROR);
}

function emitProgress(phase, pct) {
    Max.outlet("progress", String(phase || ""), Number(pct) || 0);
}

async function run(audioPath, analysisJsonPath, nBars, strategy) {
    if (child) {
        emitStatus("forge already running — send `cancel` first");
        return;
    }

    const python = resolvePython();
    if (!python) {
        emitError("Python backend not found. Run ./install.sh to create ~/.stemforge/python_path");
        return;
    }

    if (!audioPath || !fs.existsSync(String(audioPath))) {
        emitError("audio file not found: " + audioPath);
        return;
    }

    const args = ["-m", "stemforge.cli", "forge", String(audioPath)];
    if (analysisJsonPath && fs.existsSync(String(analysisJsonPath))) {
        args.push("--analysis", String(analysisJsonPath));
    }
    args.push("--n-bars", String(nBars || 14));
    args.push("--strategy", String(strategy || "max-diversity"));

    emitStatus("spawning: " + python + " " + args.join(" "));
    Max.outlet("started");

    try {
        child = spawn(python, args, { stdio: ["ignore", "pipe", "pipe"] });
    } catch (e) {
        emitError("spawn failed: " + e.message);
        child = null;
        return;
    }

    let stdoutBuf = "";
    child.stdout.on("data", (chunk) => {
        stdoutBuf += chunk.toString("utf8");
        let nl;
        while ((nl = stdoutBuf.indexOf("\n")) !== -1) {
            const line = stdoutBuf.slice(0, nl).trim();
            stdoutBuf = stdoutBuf.slice(nl + 1);
            if (!line) continue;
            handleLine(line);
        }
    });

    child.stderr.on("data", (chunk) => {
        const text = chunk.toString("utf8");
        if (/download/i.test(text)) {
            emitStatus("downloading model...");
        }
        Max.post("[forge stderr] " + text.trim(), Max.POST_LEVELS.WARN);
    });

    child.on("error", (err) => {
        emitError("child error: " + err.message);
        child = null;
    });

    child.on("close", (code) => {
        const finished = child;
        child = null;
        if (code === 0) {
            emitStatus("forge finished");
            Max.outlet("done");
        } else if (finished === null) {
            // cancelled path already emitted status
        } else {
            emitError("forge exited with code " + code);
        }
    });
}

function handleLine(line) {
    let msg;
    try {
        msg = JSON.parse(line);
    } catch (e) {
        Max.post("[forge stdout non-json] " + line);
        return;
    }

    switch (msg.event) {
        case "started":
            emitStatus("started");
            break;
        case "progress":
            emitProgress(msg.phase, msg.pct);
            break;
        case "complete":
            lastOutputDir = msg.output_dir;
            lastManifestPath = msg.manifest;
            loadCurated(msg.output_dir, msg.manifest, msg.bars);
            break;
        case "error":
            emitError(msg.message || "unknown error");
            break;
        default:
            if (msg.message) emitStatus(msg.message);
    }
}

function loadCurated(outputDir, manifestPath, nBars) {
    if (!outputDir) {
        emitError("complete event missing output_dir");
        return;
    }

    const stemDir = path.join(outputDir, "curated", focusStem);
    if (!fs.existsSync(stemDir)) {
        emitError("curated stem dir not found: " + stemDir);
        return;
    }

    Max.outlet("load_cmd", "clear");

    let entries;
    try {
        entries = fs.readdirSync(stemDir)
            .filter((f) => /\.wav$/i.test(f))
            .sort();
    } catch (e) {
        emitError("read curated dir failed: " + e.message);
        return;
    }

    const max = Math.min(entries.length, 16);
    for (let i = 0; i < max; i++) {
        const full = path.join(stemDir, entries[i]);
        Max.outlet("load_cmd", "load", full, i);
    }

    if (manifestPath && fs.existsSync(manifestPath)) {
        Max.outlet("load_cmd", "manifest", manifestPath);
    }
    Max.outlet("load_cmd", "ready", max);
    emitStatus("loaded " + max + " bars from " + focusStem);
}

Max.addHandler("run", (audioPath, analysisJsonPath, nBars, strategy) => {
    run(audioPath, analysisJsonPath, nBars, strategy);
});

Max.addHandler("cancel", () => {
    if (!child) {
        emitStatus("no active forge to cancel");
        return;
    }
    const c = child;
    child = null;
    try { c.kill("SIGTERM"); } catch (e) {}
    emitStatus("cancelled");
    Max.outlet("status", "cancelled");
});

Max.addHandler("setFocusStem", (name) => {
    focusStem = String(name || "drums");
    emitStatus("focus stem: " + focusStem);
});

Max.addHandler("reloadLast", () => {
    if (!lastOutputDir) {
        emitStatus("no previous forge output to reload");
        return;
    }
    loadCurated(lastOutputDir, lastManifestPath, null);
});

Max.addHandler("checkPython", () => {
    const p = resolvePython();
    if (p) {
        emitStatus("python: " + p);
        Max.outlet("python_ok", 1);
    } else {
        emitError("python_path missing — run install.sh");
        Max.outlet("python_ok", 0);
    }
});
