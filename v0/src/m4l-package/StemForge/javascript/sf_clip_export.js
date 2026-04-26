// sf_clip_export.js
// ─────────────────────────────────────────────────────────────────────────────
// StemForge M4L — Bounce-Selected-Clips → Sidecars
//
// Reads clip metadata from a configurable set of source tracks in the open
// Live set, builds an export spec, and spawns a Python helper via [shell] to
// slice the source audio and write per-clip `.manifest_<hash>.json` sidecars
// + a directory-level `.manifest.json` BatchManifest.
//
// Producer-handles-rotation: for each track, slot-0 clip → suggested_pad
// `BAR_INDEX_TO_LABEL[0]` (".") through slot-11 clip → "9". One group letter
// per source track (caller passes A/B/C/D).
//
// V1 SCOPE (no Live freeze yet):
//   - Reads `clip.file_path` (the SOURCE sample file).
//   - Reads `loop_start` / `loop_end` (in beats when warped, seconds otherwise)
//     and `signature_numerator` / project tempo to compute trim bounds.
//   - The Python helper reads the source WAV and slices [start..end] out.
//   - Warped clips with non-trivial warp markers WILL bounce un-warped audio
//     in v1 — true freeze-and-export is V2.
//
// Outlets:
//   0 → status messages (logged + can drive UI status-text)
//   1 → [shell] command strings (spawn / kill)
//
// Inlet messages:
//   exportClips                       — entry point (uses defaults from script)
//   exportClips <trackName,...>       — comma-separated list of source track names
//   exportClipsByIndex <i,...>        — alt: zero-based track indices
//   onClipExportStarted <n> <dir>     — NDJSON event from Python helper
//   onClipExportProgress <i> <of>     — NDJSON event from Python helper
//   onClipExportClipDone <i> <of>     — NDJSON event from Python helper
//   onClipExportComplete <batchPath>  — NDJSON event from Python helper
//   onClipExportClipError <i> <msg>   — NDJSON event from Python helper
//   onClipExportError <message…>      — NDJSON event from Python helper
// ─────────────────────────────────────────────────────────────────────────────

/* global outlet, post, LiveAPI, Dict, arrayfromargs, inlet, Folder, File, max */

autowatch = 1;
inlets = 1;
outlets = 2;

// ── Config ───────────────────────────────────────────────────────────────────

// Where the Python helper writes the bounced WAVs + sidecars + batch manifest.
// Each call gets its own timestamped subdir.
var EXPORT_ROOT = "~/stemforge/exports";

// Path to the Python helper. Override via setHelperPath if needed.
var HELPER_PATH = "/Users/zak/zacharysbrown/stemforge/tools/m4l_export_clips.py";
// Use the repo's uv-managed venv python — Max's [shell] PATH doesn't include
// per-project venvs, and /usr/bin/python3 (Apple's) lacks soundfile/pydantic.
// Override via setPythonBin if you've installed deps system-wide.
var PYTHON_BIN  = "/Users/zak/zacharysbrown/stemforge/.venv/bin/python3";

// Default source tracks if `exportClips` is called with no args. Order matters:
// first → group A, second → group B, etc.
var DEFAULT_SOURCE_TRACKS = ["A", "B", "C", "D"];
var GROUP_LETTERS = ["A", "B", "C", "D"];

// Bottom-up EP-133 pad rotation, mirroring stemforge.manifest_schema.
var BAR_INDEX_TO_LABEL = [".", "0", "ENTER", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

// Pads per group cap (EP-133 has exactly 12 user pads per group).
var MAX_SLOTS_PER_TRACK = 12;

// "Very short" threshold (in bars) below which a clip is treated as a one-shot.
// Anything ≥ this becomes playmode "key" with time_mode "bpm".
var ONESHOT_BARS_THRESHOLD = 0.5;

// ── Logging ──────────────────────────────────────────────────────────────────

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
    try { post("[sf_clip_export] " + String(s) + "\n"); } catch (_) {}
    _sfFileLog("sf_clip_export", s);
}

function _statusOut(msg) {
    try { outlet(0, "status", String(msg)); } catch (_) {}
    log(msg);
}

// ── LiveAPI helpers ──────────────────────────────────────────────────────────

function _liveSet() { return new LiveAPI("live_set"); }

function _projectTempo() {
    try { return Number(_liveSet().get("tempo")); } catch (_) { return 120.0; }
}

function _findTrackByName(name) {
    try {
        var ls = _liveSet();
        var n = ls.getcount("tracks");
        for (var i = 0; i < n; i++) {
            var t = new LiveAPI("live_set tracks " + i);
            var tn = String(t.get("name"));
            // LiveAPI returns the name as a quoted-stringified value sometimes;
            // strip surrounding quotes if present.
            tn = tn.replace(/^"+|"+$/g, "");
            if (tn === name) return i;
        }
    } catch (e) { log("_findTrackByName error: " + e); }
    return -1;
}

// Build a per-clip spec object. Returns null when the slot has no clip.
function _readClipSpec(trackIdx, slotIdx) {
    var csPath = "live_set tracks " + trackIdx + " clip_slots " + slotIdx;
    var cs;
    try { cs = new LiveAPI(csPath); } catch (_) { return null; }

    var hasClip;
    try { hasClip = Number(cs.get("has_clip")); } catch (_) { hasClip = 0; }
    if (!hasClip) return null;

    var clip;
    try { clip = new LiveAPI(csPath + " clip"); } catch (_) { return null; }

    function _g(prop, dflt) {
        try {
            var v = clip.get(prop);
            if (v === undefined || v === null) return dflt;
            // LiveAPI returns arrays for many getters; unwrap one level.
            if (Object.prototype.toString.call(v) === "[object Array]" && v.length === 1) {
                v = v[0];
            }
            return v;
        } catch (_) { return dflt; }
    }

    var name = String(_g("name", "")).replace(/^"+|"+$/g, "");
    var lengthBeats = Number(_g("length", 0));
    var loopStart = Number(_g("loop_start", 0));
    var loopEnd = Number(_g("loop_end", lengthBeats));
    // start_marker is where Live BEGINS playback when the clip is launched.
    // It can be offset INSIDE the [loop_start, loop_end] region — when the
    // user drags the play-triangle in the clip view to a different bar.
    // The bounce must start here so the EP-133 plays the rotated phrase
    // the user dialed in.
    var startMarker = Number(_g("start_marker", loopStart));
    var warping = Number(_g("warping", 0));
    var sigNum = Number(_g("signature_numerator", 4));
    var filePath = String(_g("file_path", "")).replace(/^"+|"+$/g, "");
    var gain = Number(_g("gain", 0.0));
    var clipBpm = warping ? Number(_g("warp_marker_bpm", 0.0)) : 0.0;

    if (!filePath || lengthBeats <= 0) return null;

    return {
        track_idx: trackIdx,
        slot_idx: slotIdx,
        name: name,
        file_path: filePath,
        warping: !!warping,
        length_beats: lengthBeats,
        loop_start_beats: loopStart,
        loop_end_beats: loopEnd,
        start_marker_beats: startMarker,
        signature_numerator: sigNum,
        clip_warp_bpm: clipBpm > 0 ? clipBpm : null,
        gain: gain,
    };
}

// ── Spec assembly ────────────────────────────────────────────────────────────

// Compute the EVENTUAL export dir for this bounce. Does NOT create it on
// disk — Max's File()/Folder() can't reliably mkdir intermediate parents
// (e.g. ~/stemforge/exports/ when /stemforge/ is missing) and silently
// fails. Instead, the Python helper takes responsibility for `mkdir -p`-ing
// the export_dir from inside the spec (export_dir.mkdir(parents=True,
// exist_ok=True)). This avoids a fragile JS-side mkdir entirely.
function _planExportDir() {
    var ts = String(new Date().getTime());
    var rootExpanded = EXPORT_ROOT.replace(/^~/, _homePath());
    return rootExpanded + "/" + ts;
}

function _homePath() {
    try {
        if (typeof max !== "undefined" && max && typeof max.getsystemvariable === "function") {
            var h = String(max.getsystemvariable("HOME") || "");
            if (h) return h;
        }
    } catch (_) {}
    return "/Users/zak";
}

// Write the spec to /tmp (always exists, no mkdir needed). The spec contains
// the EVENTUAL export_dir path; the Python helper will mkdir -p that dir
// before writing any outputs into it. This decouples spec write from output
// dir creation — neither needs the other to exist first.
function _writeSpecFile(spec) {
    var ts = String(new Date().getTime());
    var path = "/tmp/sf_clip_export_" + ts + ".json";
    var maxPath = "Macintosh HD:" + path;
    var f = new File(maxPath, "write", "TEXT", "TEXT");
    if (!f.isopen) {
        log("_writeSpecFile: cannot open " + path);
        return null;
    }
    try { f.eof = 0; } catch (_) {}
    f.writestring(JSON.stringify(spec, null, 2));
    f.close();
    return path;
}

function _escapeForShell(p) {
    var s = String(p || "");
    s = s.replace(/"/g, '\\"');
    return '"' + s + '"';
}

// ── Public message handlers ──────────────────────────────────────────────────

function exportClips() {
    var argv = arrayfromargs(arguments);
    var sourceTracks = DEFAULT_SOURCE_TRACKS;
    if (argv.length > 0) {
        // Comma-joined or space-separated list of track names.
        var joined = argv.join(" ");
        sourceTracks = joined.split(/[,\s]+/).filter(function (s) { return s.length > 0; });
    }
    _doExport(sourceTracks, /* byIndex */ false);
}

function exportClipsByIndex() {
    var argv = arrayfromargs(arguments);
    var indices = argv.map(function (a) { return Number(a); })
                      .filter(function (n) { return isFinite(n) && n >= 0; });
    _doExport(indices, /* byIndex */ true);
}

function _doExport(sources, byIndex) {
    if (!sources || sources.length === 0) {
        _statusOut("export: no source tracks specified");
        return;
    }
    if (sources.length > GROUP_LETTERS.length) {
        _statusOut("export: at most " + GROUP_LETTERS.length + " source tracks (one per A/B/C/D)");
        return;
    }

    var tempo = _projectTempo();
    var clipSpecs = [];

    for (var ti = 0; ti < sources.length; ti++) {
        var trackIdx;
        var groupLetter = GROUP_LETTERS[ti];

        if (byIndex) {
            trackIdx = Number(sources[ti]);
        } else {
            trackIdx = _findTrackByName(String(sources[ti]));
            if (trackIdx < 0) {
                _statusOut("export: track not found: " + sources[ti] + " (skipping group " + groupLetter + ")");
                continue;
            }
        }

        var slotCount = MAX_SLOTS_PER_TRACK;
        try {
            var t = new LiveAPI("live_set tracks " + trackIdx);
            var live_n = Number(t.getcount("clip_slots"));
            if (isFinite(live_n) && live_n > 0) slotCount = Math.min(live_n, MAX_SLOTS_PER_TRACK);
        } catch (_) {}

        for (var si = 0; si < slotCount; si++) {
            var spec = _readClipSpec(trackIdx, si);
            if (!spec) continue;
            spec.suggested_group = groupLetter;
            spec.suggested_pad = BAR_INDEX_TO_LABEL[si] || null;
            clipSpecs.push(spec);
        }
    }

    if (clipSpecs.length === 0) {
        _statusOut("export: no clips found in source tracks");
        return;
    }

    var dir = _planExportDir();
    var spec = {
        version: 1,
        project_tempo: tempo,
        oneshot_bars_threshold: ONESHOT_BARS_THRESHOLD,
        export_dir: dir,
        clips: clipSpecs,
    };

    var specPath = _writeSpecFile(spec);
    if (!specPath) {
        _statusOut("export: could not write spec to /tmp");
        return;
    }

    _statusOut("export: " + clipSpecs.length + " clips → " + dir);

    log("spawn: " + PYTHON_BIN + " " + HELPER_PATH + " " + specPath + " --json-events");
    // shell.mxo (Bill Orcutt / Jeremy Bernstein v8.0.0) routes via its
    // `anything` handler: selector becomes argv[0], remaining atoms become
    // argv[1..n]. So send the binary as the SELECTOR and each arg as a
    // separate atom — shell then does the equivalent of execvp(PYTHON_BIN,
    // [HELPER, SPEC, "--json-events"]). No shell escaping needed; spaces
    // in paths are safe because each atom is independent.
    try {
        outlet(1, PYTHON_BIN, HELPER_PATH, specPath, "--json-events");
    } catch (e) {
        _statusOut("export: spawn outlet error: " + e);
    }
}

function setHelperPath(p) { HELPER_PATH = String(p || HELPER_PATH); }
function setPythonBin(p)  { PYTHON_BIN  = String(p || PYTHON_BIN);  }
function setExportRoot(p) { EXPORT_ROOT = String(p || EXPORT_ROOT); }

// ── NDJSON event handlers (called from patcher [route] after parser) ─────────
// Names are intentionally distinct from sf_forge's onProgress/onComplete/etc
// so the shared NDJSON parser can route export_* events to THIS box only.

function onClipExportStarted() {
    var argv = arrayfromargs(arguments);
    _statusOut("export: " + argv[0] + " clips → " + (argv.slice(1).join(" ") || "?"));
}

function onClipExportProgress() {
    var argv = arrayfromargs(arguments);
    var i = Number(argv[0] || 0);
    var of = Number(argv[1] || 0);
    _statusOut("export: clip " + i + "/" + of);
}

function onClipExportClipDone() {
    var argv = arrayfromargs(arguments);
    _statusOut("export: clip done " + argv[0] + "/" + argv[1]);
}

function onClipExportClipError() {
    var argv = arrayfromargs(arguments);
    _statusOut("export: clip " + argv[0] + " FAILED: " + argv.slice(2).join(" "));
}

function onClipExportComplete() {
    var batch = arrayfromargs(arguments).join(" ");
    _statusOut("export complete → " + batch);
}

function onClipExportError() {
    var msg = arrayfromargs(arguments).join(" ");
    _statusOut("export ERROR: " + (msg || "unknown"));
}

// ── CommonJS hook for tests ──────────────────────────────────────────────────

if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        BAR_INDEX_TO_LABEL: BAR_INDEX_TO_LABEL,
        GROUP_LETTERS: GROUP_LETTERS,
        ONESHOT_BARS_THRESHOLD: ONESHOT_BARS_THRESHOLD,
        _escapeForShell: _escapeForShell,
    };
}
