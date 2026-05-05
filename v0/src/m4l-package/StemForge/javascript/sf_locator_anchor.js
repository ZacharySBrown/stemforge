// sf_locator_anchor.js
// ─────────────────────────────────────────────────────────────────────────────
// In-Ableton workflow for re-anchoring a forged track's bar 1 to a user-placed
// locator. User drops a locator at what they hear as bar 1 in arrangement
// view, presses the device button, and we:
//
//   1. read live_set.tempo + the chosen cue_point's time (in beats)
//   2. read the currently-loaded prechop_manifest.json from the track dir
//   3. back-compute the source-time at that timeline beat by walking the
//      manifest's chunks (each chunk[i] is placed at startBeat = i × bars ×
//      beats_per_bar; loop region of chunk[i] in source-time runs from
//      source_offset_sec for chunk_frames seconds)
//   4. shell out to `stemforge re-anchor <track_dir> --bpm <T> --first-downbeat <S>`
//      via [shell] outlet (~2 second roundtrip, no Demucs)
//   5. on success, call sf_arrangement_loader.runArrangementLoad(<manifest>)
//      to refresh the clips with the corrected positioning
//
// Locator selection strategy (v1): use the FIRST cue_point in the song. If
// the user wants a specific one, name it "anchor" and we'll pick it
// preferentially. Otherwise the first locator wins.
//
// Outputs:
//   outlet 0  status messages → status display in patcher
//   outlet 1  shell command atoms (PYTHON_BIN, args...) → [shell]
//
// Inputs:
//   "anchor"            run reAnchorFromLocator on the current track dir
//   "anchor <dir>"      run on an explicit track dir (overrides settings)
//   "trackDir <dir>"    set the cached track dir (sf_settings should also
//                        store this; we mirror it for direct use)
// ─────────────────────────────────────────────────────────────────────────────

/* global autowatch, inlets, outlets, outlet, post, LiveAPI, File, Folder,
          arrayfromargs, messagename, max */

autowatch = 1;
inlets = 1;
outlets = 3;  // 0: status, 1: shell command, 2: reload (manifest_path) → sf_lom_loader

// Default helper paths — same convention sf_clip_export uses; the patcher
// can override via setHelperPath / setPythonBin / setStemforgeRepo.
var PYTHON_BIN = "/Users/zak/zacharysbrown/stemforge/.venv/bin/python";
var STEMFORGE_REPO = "/Users/zak/zacharysbrown/stemforge";
var TRACK_DIR = "";  // last known current track dir (set via inlet)

// Where we write a tiny json blob the helper reads (bpm + first_downbeat),
// since calling `stemforge` directly would require shell expansion. The
// helper reads the json file and shells `stemforge re-anchor` itself.
var HELPER_PATH = "/Users/zak/zacharysbrown/stemforge/tools/m4l_locator_anchor.py";

// ── status / log ─────────────────────────────────────────────────────────────

function _status(msg) {
    var s = "[sf_locator_anchor] " + String(msg);
    try { post(s + "\n"); } catch (_) {}
    try { outlet(0, "status", s); } catch (_) {}
    _appendLog(s);
}

function _appendLog(msg) {
    try {
        var f = new File("~/stemforge/logs/sf_debug.log", "write");
        if (!f.isopen) {
            new Folder("~/stemforge/logs").createFolder();
            f = new File("~/stemforge/logs/sf_debug.log", "write");
        }
        if (f.isopen) {
            f.position = f.eof;
            f.writestring(new Date().toISOString() + " " + msg + "\n");
            f.close();
        }
    } catch (_) {}
}

// ── path helpers ─────────────────────────────────────────────────────────────

function _expandTilde(p) {
    if (typeof p !== "string") return p;
    if (p.charAt(0) === "~") {
        var home = "";
        try { home = max.getenv ? (max.getenv("HOME") || "") : ""; } catch (_) {}
        if (!home) home = "/Users/" + (max.getenv ? max.getenv("USER") : "");
        return home + p.slice(1);
    }
    return p;
}

function _join(dir, child) {
    if (!dir) return child;
    if (dir.charAt(dir.length - 1) === "/") return dir + child;
    return dir + "/" + child;
}

// ── manifest read ────────────────────────────────────────────────────────────

function _readJsonFile(absPath) {
    try {
        var f = new File(absPath, "read");
        if (!f.isopen) return null;
        try { f.position = 0; } catch (_) {}
        var MAX_CHUNK = 32767;
        var raw = "";
        var prev = -1;
        while (f.position < f.eof && f.position !== prev) {
            prev = f.position;
            var chunk = f.readstring(MAX_CHUNK) || "";
            if (!chunk.length) break;
            raw += chunk;
        }
        f.close();
        return JSON.parse(raw);
    } catch (e) {
        _status("readJson: " + absPath + " — " + e);
        return null;
    }
}

// ── locator selection ────────────────────────────────────────────────────────

function _readLocators() {
    // Returns array of {name, time_beats}. Empty if none placed.
    var out = [];
    try {
        var liveSet = new LiveAPI("live_set");
        var n = liveSet.getcount("cue_points");
        for (var i = 0; i < n; i++) {
            var cp = new LiveAPI("live_set cue_points " + i);
            var name = "";
            var t = 0;
            try { name = String(cp.get("name") || ""); } catch (_) {}
            try { t = Number(cp.get("time")); } catch (_) {}
            if (!isFinite(t)) t = 0;
            out.push({name: name, time_beats: t});
        }
    } catch (e) {
        _status("readLocators: " + e);
    }
    return out;
}

function _pickLocator(locators) {
    // Prefer a locator named "anchor" or "downbeat"; else first one.
    if (!locators || !locators.length) return null;
    for (var i = 0; i < locators.length; i++) {
        var n = String(locators[i].name || "").toLowerCase();
        if (n === "anchor" || n === "downbeat" || n === "bar 1") {
            return locators[i];
        }
    }
    return locators[0];
}

// Parse first integer from locator name. Defaults to 1 (= "this is bar 1").
//   "1" → 1, "bar 4" → 4, "Bar 4" → 4, "m4" → 4,
//   "" → 1, null → 1, "downbeat 1" → 1, "verse" → 1
function _parseBarFromLocatorName(name) {
    if (!name) return 1;
    var match = String(name).match(/(\d+)/);
    if (!match) return 1;
    var n = parseInt(match[1], 10);
    return (isFinite(n) && n >= 1) ? n : 1;
}

// ── back-compute source time at a given timeline beat ────────────────────────

function _sourceTimeAtTimelineBeat(manifest, timelineBeat) {
    // The arrangement loader places chunk[i] (0-indexed) at startBeat =
    // i × bars × beats_per_bar. Loop region in source-time runs from
    // source_offset_sec for chunk_frames seconds.
    //
    // For locator at timelineBeat T:
    //   chunk_index_0  = floor(T / chunkBeats)
    //   beat_within    = T - chunk_index_0 × chunkBeats
    //   source_time    = chunk[chunk_index_0].source_offset_sec
    //                  + beat_within × (60 / bpm)
    //
    // Returns null if T falls outside the chunk grid.
    var bpm = Number(manifest.bpm) || 120;
    var bars = Number(manifest.bars) || 4;
    var beatsPerBar = Number(manifest.beats_per_bar) || 4;
    var chunkBeats = bars * beatsPerBar;

    // Pick any stem's chunk array — they share the same source_offset_sec by
    // construction (one bar grid feeds all stems). Drums first, fall back.
    var stems = manifest.stems || {};
    var chunks = null;
    for (var key in stems) {
        if (!Object.prototype.hasOwnProperty.call(stems, key)) continue;
        if (stems[key] && stems[key].chunks && stems[key].chunks.length) {
            chunks = stems[key].chunks;
            if (key === "drums") break;
        }
    }
    if (!chunks || !chunks.length) return null;

    var idx0 = Math.floor(timelineBeat / chunkBeats);
    if (idx0 < 0 || idx0 >= chunks.length) return null;

    var chunk = chunks[idx0];
    var beatWithin = timelineBeat - idx0 * chunkBeats;
    var secPerBeat = 60.0 / bpm;
    return Number(chunk.source_offset_sec) + beatWithin * secPerBeat;
}

// ── public entry point ───────────────────────────────────────────────────────

function setHelperPath(p) { HELPER_PATH = String(p || HELPER_PATH); }
function setPythonBin(p)  { PYTHON_BIN  = String(p || PYTHON_BIN);  }
function setStemforgeRepo(p) { STEMFORGE_REPO = String(p || STEMFORGE_REPO); }
function trackDir(p) { TRACK_DIR = String(p || ""); _status("trackDir set: " + TRACK_DIR); }

// Idempotency threshold (seconds). If the locator-derived first_downbeat
// is within this distance of the manifest's existing first_downbeat, ANCH
// no-ops with a status log instead of triggering a ~2s re-cut.
var IDEMPOTENCY_THRESHOLD_SEC = 0.005;

// PENDING_LOCATOR_BEAT: stashed by anchor() for onAnchorComplete to compute
// the timeline shift that places the new bar-1 chunk at the locator's
// timeline position. Without it, the loader tiles from timeline 0 and the
// locator no longer marks bar 1 in the arrangement view.
var PENDING_LOCATOR_BEAT = null;

function anchor() {
    // Bar-grid re-anchor: derive a small `first_downbeat_sec` correction
    // from where the user's locator falls inside its containing chunk under
    // the CURRENT grid, then shell to `stemforge re-anchor` to re-cut.
    // Live's tempo wins (so the user can fix BPM in Ableton before pressing
    // ANCH). Named-locator parsing lets the user mark "bar 4" if the
    // detected grid is off by whole-chunk multiples.
    var argv = arrayfromargs(arguments);
    var dir = argv.length ? String(argv[0]) : TRACK_DIR;
    if (!dir) {
        _status("anchor: no track dir set (call trackDir <path> first or pass as arg)");
        return false;
    }
    dir = _expandTilde(dir);

    var manifestPath = _join(dir, "prechop_manifest.json");
    var manifest = _readJsonFile(manifestPath);
    if (!manifest) {
        _status("anchor: cannot read " + manifestPath);
        return false;
    }

    var locators = _readLocators();
    if (!locators.length) {
        _status("anchor: no locators placed in arrangement view (drop one at bar 1 first)");
        return false;
    }
    var picked = _pickLocator(locators);

    var locatorSourceSec = _sourceTimeAtTimelineBeat(manifest, picked.time_beats);
    if (locatorSourceSec == null) {
        _status("anchor: locator '" + picked.name + "' at beat " +
                Number(picked.time_beats).toFixed(2) + " falls outside the chunk grid");
        return false;
    }

    // Live's tempo wins. Lets the user nudge tempo before ANCH and have it
    // adopted automatically. Falls back to manifest BPM if LOM read fails.
    var tempo = 120;
    try { tempo = Number(new LiveAPI("live_set").get("tempo")); } catch (_) {}
    if (!isFinite(tempo) || tempo <= 0) tempo = Number(manifest.bpm) || 120;

    // Geometry — note the manifest field is `bars` (chunk width in bars).
    var beatsPerBar = Number(manifest.beats_per_bar) || 4;
    var barsPerChunk = Number(manifest.bars) || 1;
    var barSeconds = beatsPerBar * 60 / tempo;
    var chunkPeriodSec = barsPerChunk * barSeconds;

    // If the user named the locator with a bar number (e.g. "4", "bar 4"),
    // shift the source time back so bar 1 is (N-1) bars earlier.
    var locatorBarNumber = _parseBarFromLocatorName(picked.name);
    var adjustedSourceSec = locatorSourceSec - (locatorBarNumber - 1) * barSeconds;
    if (adjustedSourceSec < 0) {
        _status("anchor: locator '" + picked.name + "' = bar " + locatorBarNumber +
                " puts bar 1 at " + adjustedSourceSec.toFixed(3) +
                "s (negative). Check locator name.");
        return false;
    }

    // Direct: bar 1 is AT the user's locator (after named-locator adjustment).
    // No snap-to-nearest math — the prior design's `mod chunkPeriodSec` snap
    // collapsed multi-chunk-period corrections (a locator several bars deep
    // gets "rounded" back to within half a chunk, mislabeling bar 1).
    var newFirstDownbeat = adjustedSourceSec;
    var oldFirstDownbeat = Number(manifest.first_downbeat_sec) || 0;
    var deltaFD = newFirstDownbeat - oldFirstDownbeat;
    // Suppress unused-var lint on chunkPeriodSec (kept for clarity in logs).
    void chunkPeriodSec;

    if (Math.abs(deltaFD) < IDEMPOTENCY_THRESHOLD_SEC) {
        _status("anchor: locator '" + picked.name + "' (bar " + locatorBarNumber +
                ") already on bar grid (Δ first_downbeat " +
                (deltaFD * 1000).toFixed(1) + "ms < threshold), no-op");
        return false;
    }

    // Stash the locator's timeline beat so onAnchorComplete can compute a
    // shift = locatorBeat - bar1Idx*chunkBeats, placing the new bar-1 chunk
    // AT the locator's timeline position rather than at the chunk-grid
    // origin (timeline 0).
    PENDING_LOCATOR_BEAT = Number(picked.time_beats) || 0;

    _status("anchor: locator '" + (picked.name || "(unnamed)") +
            "' = bar " + locatorBarNumber +
            " at source " + locatorSourceSec.toFixed(3) +
            "s, adjusted bar 1 → " + adjustedSourceSec.toFixed(3) +
            "s, Δ first_downbeat " + deltaFD.toFixed(3) +
            "s, newFirstDownbeat " + newFirstDownbeat.toFixed(4) +
            "s, bpm=" + tempo);

    // Outlet 1 → [shell] → tools/m4l_locator_anchor.py → stemforge re-anchor.
    // On completion, the helper emits NDJSON `anchor_complete <manifest>`,
    // which the patcher routes to onAnchorComplete() → outlet 2 → loader.
    try {
        outlet(1, PYTHON_BIN, HELPER_PATH,
               "--track-dir", dir,
               "--bpm", String(tempo),
               "--first-downbeat", newFirstDownbeat.toFixed(6),
               "--manifest-out", manifestPath);
    } catch (e) {
        _status("anchor: spawn outlet error: " + e);
        return false;
    }
    return true;
}

// ── ndjson event handlers (called from patcher [route] after parser) ─────────

function onAnchorStarted() {
    _status("re-anchor started");
}

function onAnchorComplete() {
    var argv = arrayfromargs(arguments);
    var manifestPath = argv[0] || "";
    _status("re-anchor done; reloading from " + manifestPath);
    if (!manifestPath) return;

    // Compute timeline shift so the new bar-1 chunk lands at the locator's
    // timeline position (where the user dropped it). Without shift, the
    // loader tiles chunks from timeline 0 and the locator no longer marks
    // bar 1 in arrangement view.
    //
    // shift = locatorBeat - bar1Idx * chunkBeats
    //
    // If the result would be negative (= the new bar1Idx demands more
    // pre-roll timeline space than exists between timeline 0 and the
    // locator), clamp to 0 with a status warning. The user should re-drop
    // the locator further right OR force --pre-bars 0 in re-anchor.
    var shift = 0;
    if (PENDING_LOCATOR_BEAT != null) {
        var newManifest = _readJsonFile(manifestPath);
        if (newManifest) {
            var bar1Idx = Number(newManifest.musical_bar_1_chunk_index) || 0;
            var bars = Number(newManifest.bars) || 1;
            var beatsPerBar = Number(newManifest.beats_per_bar) || 4;
            var chunkBeats = bars * beatsPerBar;
            var rawShift = PENDING_LOCATOR_BEAT - bar1Idx * chunkBeats;
            if (rawShift < 0) {
                _status("anchor: locator at beat " +
                        PENDING_LOCATOR_BEAT.toFixed(2) +
                        " is too early for " + bar1Idx +
                        "-chunk pre-roll (would require shift " +
                        rawShift.toFixed(2) +
                        " beats); clamping shift to 0. Drop locator at beat ≥ " +
                        (bar1Idx * chunkBeats) + " for exact alignment.");
                shift = 0;
            } else {
                shift = rawShift;
            }
        }
        PENDING_LOCATOR_BEAT = null;
    }

    // Each [js] box runs in its own classic-Max JS context, so we cannot
    // call runArrangementLoad directly. Emit on outlet 2 — the patcher
    // routes this back to sf_lom_loader as a `loadArrangementFromManifest`
    // message, which include()s sf_arrangement_loader.js and refreshes.
    try { outlet(2, manifestPath, shift); }
    catch (e) { _status("reload outlet failed: " + e); }
}

function onAnchorError() {
    var argv = arrayfromargs(arguments);
    _status("re-anchor failed: " + argv.join(" "));
}

// ── CommonJS shim — for tests/js_mocks/ Node-vm sandbox ──────────────────────

if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        anchor: anchor,
        trackDir: trackDir,
        _readLocators: _readLocators,
        _pickLocator: _pickLocator,
        _parseBarFromLocatorName: _parseBarFromLocatorName,
        _sourceTimeAtTimelineBeat: _sourceTimeAtTimelineBeat,
        _join: _join,
        _expandTilde: _expandTilde
    };
}
