// sf_forge.js
// ─────────────────────────────────────────────────────────────────────────────
// StemForge M4L — Forge Orchestrator
//
// Classic Max [js] object. Drives the FORGE operation in two phases:
//
//   Phase 1 (only when source.type === 'audio'):
//     Emits a `spawn <cmd>` on outlet 1 so the patcher can route it to
//     [shell]. Progress/complete/error events come BACK IN as inlet messages
//     (routed via the NDJSON parser → [route] tree in the patcher).
//
//   Phase 2 (always):
//     Delegates LiveAPI track-creation to the existing stemforge_loader.v0.js
//     via an outlet-2 message pointing it at the sf_manifest dict:
//       outlet 2 → "loadFromDict sf_manifest"
//     The loader reads both `sf_manifest` and `sf_preset` on its own.
//
// State mutation is delegated to sf_state.js (outlet 0). This module never
// writes to `sf_state` / `sf_preset` / `sf_manifest` dicts directly.
//
// Outlets:
//   0 → sf_state_mgr messages (markPhase1Progress, markStemDone, markDone …)
//   1 → [shell] command strings (spawn / kill)
//   2 → stemforge_loader bridge (loadFromDict …)
//
// Inlet messages:
//   startForge                           — entry point
//   cancelForge                          — user pressed cancel
//   retry                                — user pressed retry after error
//   rollback <offsetStart> <offsetEnd>   — delete tracks in range (infra hook)
//   onProgress <pct>                     — NDJSON progress event (0-1)
//   onStem <stemName>                    — NDJSON stem completion
//   onBpm <bpm>                          — NDJSON bpm detection
//   onComplete <manifestPath>            — NDJSON split complete
//   onCurated <manifestPath> <bars> <bpm> — curation step complete
//   onError <message …>                  — NDJSON error event
// ─────────────────────────────────────────────────────────────────────────────

/* global outlet, post, LiveAPI, Dict, messagename, arrayfromargs, inlet, Folder, File, max */

autowatch = 1;
inlets = 1;
outlets = 3;

// ── Config ───────────────────────────────────────────────────────────────────

var NATIVE_BIN   = "/usr/local/bin/stemforge-native";
var NATIVE_VARIANT = "ft-fused";
var STATE_DICT   = "sf_state";

// ── Internal orchestrator state ──────────────────────────────────────────────
// None of this is in sf_state; it's purely local bookkeeping for phase-1
// plumbing (manifest path, timing, track range) that shouldn't leak into the
// canonical state dict.

var _phase            = "idle";  // "idle" | "phase1" | "curating" | "phase2" | "done" | "error"
var _startEpoch       = 0;
var _trackOffsetStart = -1;
var _trackOffsetEnd   = -1;
var _detectedBpm      = 0;
var _splitManifest    = "";
var _curatedManifest  = "";
var _cancelRequested  = false;

// ── Utilities ────────────────────────────────────────────────────────────────

// Inline file-log helper. Mirrors sf_logger.js behavior so every module
// writes into ~/stemforge/logs/sf_debug.log without needing require().
function _sfFileLog(module, msg) {
    try {
        var homePath;
        try {
            if (typeof max !== "undefined" && max && typeof max.getsystemvariable === "function") {
                homePath = String(max.getsystemvariable("HOME") || "");
            }
        } catch (_) {}
        if (!homePath) {
            try {
                if (typeof File !== "undefined" && typeof File.getenv === "function") {
                    homePath = String(File.getenv("HOME") || "");
                }
            } catch (_) {}
        }
        if (!homePath) homePath = "/Users/zak";
        var dir = homePath + "/stemforge/logs";
        var path = dir + "/sf_debug.log";
        var maxPath = "Macintosh HD:" + path;
        try { new Folder("Macintosh HD:" + dir).close(); }
        catch (_) {
            try {
                var ff = new File("Macintosh HD:" + dir + "/.keep", "write", "TEXT", "TEXT");
                if (ff.isopen) { ff.writestring(""); ff.close(); }
            } catch (_) {}
        }
        var ts;
        try { ts = (new Date()).toISOString(); }
        catch (_) { ts = String(new Date().getTime()); }
        var line = "[" + ts + "] [" + String(module) + "] " + String(msg) + "\n";
        var f = new File(maxPath, "write", "TEXT", "TEXT");
        if (!f.isopen) return;
        try { f.position = f.eof; } catch (_) {}
        f.writestring(line);
        try { f.eof = f.position; } catch (_) {}
        f.close();
    } catch (_) {}
}

function log(s) {
    try { post("[sf_forge] " + String(s) + "\n"); } catch (_) {}
    _sfFileLog("sf_forge", s);
}

function nowEpochSec() {
    return Math.floor(new Date().getTime() / 1000);
}

function _readStateKind() {
    try {
        var d  = new Dict(STATE_DICT);
        var js = d.get("root");
        if (!js) return "empty";
        // Dict.get returns string for string vals; parse if needed.
        var obj;
        if (typeof js === "string") {
            obj = JSON.parse(js);
        } else {
            obj = JSON.parse(d.stringify()).root;
        }
        return (obj && obj.kind) ? String(obj.kind) : "empty";
    } catch (e) {
        log("_readStateKind error: " + e);
        return "empty";
    }
}

function _readStateRoot() {
    try {
        var d   = new Dict(STATE_DICT);
        var raw = d.stringify();
        if (!raw) return null;
        var parsed = JSON.parse(raw);
        return parsed.root || null;
    } catch (e) {
        log("_readStateRoot error: " + e);
        return null;
    }
}

function _readPresetRoot() {
    try {
        var d   = new Dict("sf_preset");
        var raw = d.stringify();
        if (!raw || raw === "{}") return null;
        var parsed = JSON.parse(raw);
        return parsed.root || parsed; // legacy presets may omit root wrapper
    } catch (e) {
        log("_readPresetRoot error: " + e);
        return null;
    }
}

function _escapeForShell(path) {
    // Quote the path for a shell command. We don't do full POSIX escaping;
    // just wrap in double quotes and escape embedded quotes.
    var s = String(path || "");
    s = s.replace(/"/g, '\\"');
    return '"' + s + '"';
}

function _buildSplitCommand(audioPath) {
    return NATIVE_BIN + ' split ' + _escapeForShell(audioPath) +
           ' --json-events --variant ' + NATIVE_VARIANT;
}

// ── LiveAPI helpers ──────────────────────────────────────────────────────────

function getCurrentTrackCount() {
    try {
        return new LiveAPI("live_set").getcount("tracks");
    } catch (e) {
        log("getCurrentTrackCount error: " + e);
        return -1;
    }
}

function rollback(offsetStart, offsetEnd) {
    // Delete tracks in reverse order so indices remain valid mid-loop.
    var start = Number(offsetStart);
    var end   = Number(offsetEnd);
    if (!isFinite(start) || !isFinite(end) || end <= start) {
        log("rollback: nothing to do (" + start + ".." + end + ")");
        return;
    }
    log("rollback: deleting tracks [" + start + ".." + (end - 1) + "]");
    try {
        var live = new LiveAPI("live_set");
        for (var i = end - 1; i >= start; i--) {
            try {
                live.call("delete_track", i);
            } catch (inner) {
                log("rollback: delete_track " + i + " failed: " + inner);
            }
        }
    } catch (e) {
        log("rollback: fatal " + e);
    }
}

// ── State-mgr message helpers (outlet 0) ─────────────────────────────────────
// All outbound state mutations funnel through these so the message names stay
// in sync with the contract (§5 of the UI contract doc).

function _smPhase1Start()                            { outlet(0, "markPhase1Start"); }
function _smPhase1Progress(pct, currentOp)           { outlet(0, "markPhase1Progress", Number(pct || 0), String(currentOp || "")); }
function _smStemStart(stem)                          { outlet(0, "markStemStart", String(stem)); }
function _smStemDone(stem)                           { outlet(0, "markStemDone", String(stem)); }
function _smPhase1Done()                             { outlet(0, "markPhase1Done"); }
function _smTargetStart(stem, target)                { outlet(0, "markTargetStart", String(stem), String(target)); }
function _smTargetDone(stem, target)                 { outlet(0, "markTargetDone", String(stem), String(target)); }
function _smDone(count, start, end, elapsed)        { outlet(0, "markDone", Number(count), Number(start), Number(end), Number(elapsed)); }
function _smError(phase, kind, message, fix) {
    outlet(0, "markError", Number(phase), String(kind || "unknown"),
        String(message || ""), String(fix || ""));
}

// ── Phase 1: native split ────────────────────────────────────────────────────

function _startPhase1(audioPath) {
    _phase            = "phase1";
    _splitManifest    = "";
    _curatedManifest  = "";
    _detectedBpm      = 0;
    _cancelRequested  = false;

    _smPhase1Start();

    var cmd = _buildSplitCommand(audioPath);
    log("spawn: " + cmd);
    try {
        outlet(1, "spawn", cmd);
    } catch (e) {
        log("spawn outlet error: " + e);
        _phase = "error";
        _smError(1, "split_failed", "failed to emit spawn command: " + e,
            "check [shell] wiring in the patcher");
    }
}

// ── Phase 2: LOM track creation (delegated to stemforge_loader.v0.js) ───────

function _walkPresetTargets(preset, cb) {
    // Iterate every (stemName, targetName) pair in the preset, in stem order.
    // Mirrors sf_state.js STEM_ORDER for consistency.
    if (!preset || !preset.stems) return 0;
    var order = ["drums", "bass", "vocals", "other"];
    var count = 0;
    for (var i = 0; i < order.length; i++) {
        var sn = order[i];
        var stemEntry = preset.stems[sn];
        if (!stemEntry || !stemEntry.targets) continue;
        for (var ti = 0; ti < stemEntry.targets.length; ti++) {
            var tgt = stemEntry.targets[ti];
            if (!tgt || !tgt.name) continue;
            try { cb(sn, tgt.name); } catch (_) {}
            count++;
        }
    }
    return count;
}

function _startPhase2() {
    _phase = "phase2";

    var preset = _readPresetRoot();
    if (!preset) {
        _phase = "error";
        _smError(2, "missing_preset",
            "no preset loaded", "pick a preset from the dropdown");
        return;
    }

    // Flip phase1.active → false, phase2.active → true in sf_state.
    _smPhase1Done();

    // Snapshot the current track count so we can rollback on failure. If the
    // Live API isn't available (rare, but possible during startup), we still
    // proceed — rollback just becomes a no-op.
    _trackOffsetStart = getCurrentTrackCount();
    if (_trackOffsetStart < 0) _trackOffsetStart = 0;
    log("phase 2 start: trackOffsetStart=" + _trackOffsetStart);

    // Defer the (synchronous, ~7s) loader call by one frame so Max's event
    // loop can paint the "forging" state — gray CANCEL button, pending pills —
    // before we block. Without this yield the redraws queue up during the
    // loader and flush all at once at the end, so the user sees idle → done
    // with nothing in between. Per-target progress is now driven by the loader
    // itself via _notifyStateMgr (see stemforge_loader.v0.js).
    var task = new Task(_runLoaderAndComplete, this);
    task.schedule(40);
}

function _runLoaderAndComplete() {
    try {
        outlet(2, "loadFromDict", "sf_manifest");
    } catch (e) {
        log("phase 2 outlet error: " + e);
        _phase = "error";
        _smError(2, "device_not_found",
            "failed to invoke loader: " + e,
            "check patcher wiring between sf_forge and stemforge_loader");
        return;
    }

    // Loader is synchronous from our POV; compute final track range & mark done.
    _trackOffsetEnd = getCurrentTrackCount();
    if (_trackOffsetEnd < _trackOffsetStart) _trackOffsetEnd = _trackOffsetStart;

    var tracksCreated = _trackOffsetEnd - _trackOffsetStart;
    var elapsed = nowEpochSec() - _startEpoch;

    _phase = "done";
    _smDone(tracksCreated, _trackOffsetStart, _trackOffsetEnd, elapsed);
    log("forge complete: " + tracksCreated + " tracks [" +
        _trackOffsetStart + ".." + _trackOffsetEnd + "] in " + elapsed + "s");
}

// ── Public message handlers ──────────────────────────────────────────────────

function startForge() {
    var root = _readStateRoot();
    if (!root) {
        log("startForge: no sf_state");
        _smError(1, "invalid_state", "no state loaded",
            "pick a preset and a source first");
        return;
    }

    // The state manager should have already validated that we're in idle and
    // transitioned to forging. We read source.type from the current state.
    var source = root.source;
    if (!source || !source.type) {
        _smError(1, "invalid_state", "no source configured",
            "pick a source (manifest or audio) first");
        return;
    }

    _startEpoch       = nowEpochSec();
    _cancelRequested  = false;
    _trackOffsetStart = -1;
    _trackOffsetEnd   = -1;

    // Transition state-mgr idle → forging BEFORE emitting phase marks.
    // State-mgr's validator rejects markPhase* while kind=idle.
    outlet(0, "startForge");

    if (source.type === "audio") {
        log("startForge: audio source → phase 1 (" + source.path + ")");
        _startPhase1(source.path || source.filename || "");
    } else if (source.type === "manifest") {
        log("startForge: manifest source → phase 2 directly");
        // For manifest sources, phase 1 is effectively skipped. Fake-flash it
        // so the state machine's phase-1 flags get cleared cleanly.
        _smPhase1Start();
        _smPhase1Progress(1.0, "manifest loaded");
        _startPhase2();
    } else {
        _smError(1, "invalid_state",
            "unknown source.type: " + source.type,
            "source must be 'audio' or 'manifest'");
    }
}

function cancelForge() {
    _cancelRequested = true;
    log("cancelForge: current phase=" + _phase);
    if (_phase === "phase1" || _phase === "curating") {
        try { outlet(1, "kill"); } catch (e) { log("kill outlet error: " + e); }
        _phase = "error";
        _smError(1, "cancelled", "user cancelled split",
            "press retry to re-run");
    } else if (_phase === "phase2") {
        // Mid-LOM-call — too late to cleanly stop. Flag it for the record.
        log("cancelForge: phase 2 already running, can't safely abort");
        _smError(2, "cancelled", "cancel during phase 2 is not supported",
            "let the forge finish then undo (⌘Z) in Live");
    } else {
        log("cancelForge: nothing to cancel (phase=" + _phase + ")");
    }
}

function retry() {
    log("retry: clearing error and re-starting forge");
    _phase            = "idle";
    _cancelRequested  = false;
    _trackOffsetStart = -1;
    _trackOffsetEnd   = -1;
    _splitManifest    = "";
    _curatedManifest  = "";
    _detectedBpm      = 0;

    // Re-emit startForge so the state machine can legitimately transition
    // idle → forging. The UI should have already reset via retry_click →
    // state-mgr's "reset"-esque path; we then re-kick the forge.
    startForge();
}

// Dispatcher for the single physical action button. The button always fires
// `actionClick`; we pick the right handler based on current sf_state.kind.
function actionClick() {
    var kind = _readStateKind();
    log("actionClick in kind=" + kind);
    if (kind === "empty") {
        log("  no preset+source yet — ignoring");
        return;
    }
    if (kind === "idle") { startForge(); return; }
    if (kind === "forging") { cancelForge(); return; }
    if (kind === "done") {
        // Tell state-mgr to reset so UI returns to idle (or empty if no
        // preset/source). outlet 0 = state-mgr channel.
        outlet(0, "reset");
        return;
    }
    if (kind === "error") { retry(); return; }
    log("  unknown kind — no action");
}

// Forwarder so sf-remote can trigger the loader's commitOffsets handler
// without a dedicated UDP endpoint. Accepts optional manifest path argument;
// forwards to the loader via outlet 2 (same channel as loadFromDict).
function commitOffsets() {
    var argv = arrayfromargs(arguments);
    try {
        if (argv.length > 0) outlet(2, "commitOffsets", String(argv[0]));
        else                 outlet(2, "commitOffsets");
        log("commitOffsets forwarded to loader" + (argv.length ? " with path " + argv[0] : ""));
    } catch (e) {
        log("commitOffsets outlet error: " + e);
    }
}

// ── NDJSON event handlers (called from patcher [route] after parser) ─────────

function onProgress() {
    // args: <pct 0-1> [currentOp…]
    if (_phase !== "phase1") return;
    var argv = arrayfromargs(arguments);
    var pct = Number(argv[0] || 0);
    if (!isFinite(pct)) pct = 0;
    // Clamp to [0, 1] — native emits 0..100 sometimes; normalize.
    if (pct > 1.0) pct = pct / 100.0;
    if (pct < 0)   pct = 0;
    if (pct > 1)   pct = 1;

    var op = argv.length > 1 ? argv.slice(1).join(" ") : "";
    _smPhase1Progress(pct, op);
}

function onStem() {
    // args: <stemName>
    if (_phase !== "phase1") return;
    var stem = String(arguments[0] || "").toLowerCase();
    if (!stem) return;
    // Native emits stem events as "done" signals; flip to splitting then done
    // so the UI briefly shows the "just finished" beat. For v1 we just mark
    // done.
    _smStemDone(stem);
}

function onBpm() {
    var bpm = Number(arguments[0] || 0);
    if (!isFinite(bpm) || bpm <= 0) return;
    _detectedBpm = bpm;
    log("detected bpm: " + bpm);
}

function onComplete() {
    // args: <manifestPath>
    if (_phase !== "phase1") {
        log("onComplete ignored (phase=" + _phase + ")");
        return;
    }
    var path = arrayfromargs(arguments).join(" ");
    _splitManifest = path;
    log("split complete → " + path);

    // Between split and phase 2 sits the curation step. The patcher/binary
    // handles the actual curate work (see builder.py OBJ_CURATE_CMD). From
    // our POV we just wait for the subsequent `onCurated` event.
    _phase = "curating";
    _smPhase1Progress(1.0, "curating bars");
}

function onCurated() {
    // args: <manifestPath> [<bars>] [<bpm>]
    var argv = arrayfromargs(arguments);
    var curatedPath = String(argv[0] || "");
    var bars        = argv.length > 1 ? Number(argv[1]) : 0;
    var bpm         = argv.length > 2 ? Number(argv[2]) : _detectedBpm;

    _curatedManifest = curatedPath;
    if (bpm && bpm > 0) _detectedBpm = bpm;
    log("curated → " + curatedPath + " (" + bars + " bars, " + bpm + " bpm)");

    // Hand off to phase 2 — loader will read sf_manifest which is expected
    // to have been populated by the manifest-loader / patcher wiring.
    if (_cancelRequested) {
        log("onCurated: cancel was requested, not advancing to phase 2");
        return;
    }
    _startPhase2();
}

function onError() {
    var msg = arrayfromargs(arguments).join(" ");
    if (!msg) msg = "unknown error";
    log("onError: " + msg);
    _phase = "error";
    _smError(1, "split_failed", msg,
        "check the stemforge-native logs and retry");
}

// ── CommonJS hook (for tests, mirrors stemforge_loader.v0.js) ────────────────

if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        NATIVE_BIN: NATIVE_BIN,
        NATIVE_VARIANT: NATIVE_VARIANT,
        _buildSplitCommand: _buildSplitCommand,
        _escapeForShell: _escapeForShell
    };
}
