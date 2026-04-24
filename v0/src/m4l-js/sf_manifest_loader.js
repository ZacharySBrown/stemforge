// sf_manifest_loader.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] — scans the curated manifest directory, populates the
// source [umenu], and emits SourceRef JSON to the state manager on select.
// Also accepts an `audioPath` message (POSIX path, from [opendialog sound] →
// regexp) and builds an audio-type SourceRef.
//
// Protocol (see specs/stemforge_device_ui_contract.md §3, §8):
//   in:   scanManifests              — rescan manifest dir, repopulate umenu
//         select <index>             — user picked item N in source umenu
//         audioPath <posixPath...>   — after [opendialog sound] completes
//
//   out0: clear                                  (umenu reset)
//         append <manifestName>                  (one per manifest)
//         append ----                            (divider)
//         append Browse audio...                 (dialog entry)
//   out1: setSource <sourceRefJson>              (manifest or audio source)
//         browseAudio                            (patch opens [opendialog sound])
//
// Manifest dir resolution order (when no override from sf_settings):
//   1. ~/stemforge/curated
//   2. ~/stemforge/processed
//   3. ~/Documents/Max 9/Packages/StemForge/manifests
// ─────────────────────────────────────────────────────────────────────────────

/* global autowatch, inlets, outlets, outlet, post, Folder, File, SoundFile,
   Dict, arrayfromargs, messagename */

autowatch = 1;
inlets = 1;
outlets = 2;   // 0: umenu population, 1: setSource / browseAudio to state mgr

var MANIFEST_DIR = null;
var MANIFEST_ENTRIES = [];        // [{ filename, displayName, path, bpm, bars, stemCount }]
var BROWSE_INDEX = -1;            // index of the "Browse audio..." entry
var BROWSE_MANIFEST_INDEX = -1;   // index of the "Browse manifest..." entry
var DIVIDER_INDEX = -1;           // index of the "----" divider (non-selectable)

// Inline file-log helper (see sf_logger.js).
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

function log(msg) {
    try { post("[sf_manifest_loader] " + String(msg) + "\n"); } catch (_) {}
    _sfFileLog("sf_manifest_loader", msg);
}

function toMaxPath(p) {
    var s = String(p);
    if (s.length > 0 && s.charAt(0) === "/") return "Macintosh HD:" + s;
    return s;
}

function _expandHome(p) {
    if (!p) return p;
    var s = String(p);
    if (s.charAt(0) !== "~") return s;
    var home = _getHomePath();
    return home + s.substring(1);
}

function _getHomePath() {
    var skip = { Shared: 1, Library: 1, Guest: 1, admin: 1 };
    var dirs = [];
    try {
        var f = new Folder("Macintosh HD:/Users/");
        while (!f.end) {
            var fn = String(f.filename);
            if (f.filetype === "fold" && !skip[fn] && fn.charAt(0) !== ".") {
                dirs.push(fn);
            }
            f.next();
        }
        f.close();
    } catch (e) {
        log("getHomePath error: " + e);
    }
    if (dirs.length === 1) return "/Users/" + dirs[0];
    for (var i = 0; i < dirs.length; i++) {
        try {
            var testPath = "Macintosh HD:/Users/" + dirs[i] + "/Documents/Max 9/Packages";
            var tf = new Folder(testPath);
            var hasEntries = !tf.end;
            tf.close();
            if (hasEntries) return "/Users/" + dirs[i];
        } catch (_) {}
    }
    return "/Users/" + (dirs[0] || "unknown");
}

function _folderExistsAndHasAny(maxPath) {
    try {
        var f = new Folder(maxPath);
        var ok = !f.end || !!f.filename;
        f.close();
        return ok;
    } catch (_) {
        return false;
    }
}

function _readFileContents(posixPath) {
    try {
        var f = new File(toMaxPath(posixPath), "read");
        if (!f.isopen) return null;
        var raw = "";
        while (f.position < f.eof) { raw += f.readstring(65536); }
        f.close();
        return raw;
    } catch (e) {
        log("read error (" + posixPath + "): " + e);
        return null;
    }
}

function _settingsManifestDir() {
    // Check sf_settings dict for an override at workflow.manifestDir.
    try {
        var d = new Dict("sf_settings");
        var raw = d.stringify();
        if (!raw || raw === "{}") return null;
        var obj = JSON.parse(raw);
        // Dicts are wrapped with root key per project convention.
        var workflow = (obj.root && obj.root.workflow) || obj.workflow;
        if (workflow && workflow.manifestDir) {
            return _expandHome(workflow.manifestDir);
        }
    } catch (_) {}
    return null;
}

function _resolveManifestDir() {
    // Prefer `processed` because that's where actual split output lands;
    // `curated` on its own is legacy and usually empty.
    var override = _settingsManifestDir();
    var home = _getHomePath();
    var candidates = [];
    if (override) candidates.push(override);
    candidates.push(home + "/stemforge/processed");
    candidates.push(home + "/stemforge/curated");
    candidates.push(home + "/Documents/Max 9/Packages/StemForge/manifests");

    for (var i = 0; i < candidates.length; i++) {
        if (_folderExistsAndHasAny(toMaxPath(candidates[i]))) return candidates[i];
    }
    log("manifest dir not found — tried: " + candidates.join(", "));
    return null;
}

// Flat directory: any `.json` in this folder counts.
function _listManifestFilenames(posixDir) {
    var names = [];
    try {
        var folder = new Folder(toMaxPath(posixDir));
        while (!folder.end) {
            var fn = String(folder.filename);
            if (fn.length > 5 && fn.charAt(0) !== ".") {
                var tail = fn.substring(fn.length - 5).toLowerCase();
                if (tail === ".json") names.push(fn);
            }
            folder.next();
        }
        folder.close();
    } catch (e) {
        log("list error (" + posixDir + "): " + e);
    }
    names.sort();
    return names;
}

// Nested layout: each subdirectory is a track; look for
//   <track>/curated/manifest.json (preferred)  → label "<track>"
//   <track>/stems.json             (fallback)  → label "<track> (raw)"
function _listNestedTracks(posixDir) {
    var tracks = [];
    try {
        var folder = new Folder(toMaxPath(posixDir));
        while (!folder.end) {
            var fn = String(folder.filename);
            if (folder.filetype === "fold" && fn.charAt(0) !== ".") {
                var subdir = posixDir + "/" + fn;
                var curated = subdir + "/curated/manifest.json";
                var raw = subdir + "/stems.json";
                var curatedFile = null;
                var rawFile = null;
                try {
                    var tf = new File(toMaxPath(curated), "read");
                    if (tf.isopen) { curatedFile = curated; tf.close(); }
                } catch (_) {}
                try {
                    var tf2 = new File(toMaxPath(raw), "read");
                    if (tf2.isopen) { rawFile = raw; tf2.close(); }
                } catch (_) {}
                if (curatedFile) {
                    tracks.push({ track: fn, label: fn, path: curatedFile });
                } else if (rawFile) {
                    tracks.push({ track: fn, label: fn + " (raw)", path: rawFile });
                }
            }
            folder.next();
        }
        folder.close();
    } catch (e) {
        log("nested list error (" + posixDir + "): " + e);
    }
    tracks.sort(function (a, b) { return a.label < b.label ? -1 : 1; });
    return tracks;
}

function _inspectManifest(posixPath) {
    var raw = _readFileContents(posixPath);
    if (!raw) return { bpm: null, bars: null, stemCount: 0 };
    var obj;
    try { obj = JSON.parse(raw); }
    catch (e) { log("parse error " + posixPath + ": " + e); return { bpm: null, bars: null, stemCount: 0 }; }

    var bpm = (obj && typeof obj.bpm === "number") ? obj.bpm : null;
    var bars = (obj && typeof obj.bars === "number") ? obj.bars : null;
    var stemCount = 0;
    if (obj && obj.stems) {
        if (obj.stems.length !== undefined && obj.stems.length !== null) {
            // Array form (legacy).
            stemCount = obj.stems.length;
        } else {
            for (var k in obj.stems) {
                if (obj.stems.hasOwnProperty(k)) stemCount++;
            }
        }
    }
    return { bpm: bpm, bars: bars, stemCount: stemCount };
}

function _baseName(posixPath) {
    if (!posixPath) return "";
    var s = String(posixPath);
    var slash = s.lastIndexOf("/");
    return (slash >= 0) ? s.substring(slash + 1) : s;
}

function _stripJsonExt(fn) {
    if (!fn) return "";
    var s = String(fn);
    if (s.length > 5 && s.substring(s.length - 5).toLowerCase() === ".json") {
        return s.substring(0, s.length - 5);
    }
    return s;
}

// ── Public messages ─────────────────────────────────────────────────────────

function scanManifests() {
    MANIFEST_DIR = _resolveManifestDir();
    MANIFEST_ENTRIES = [];
    BROWSE_INDEX = -1;
    BROWSE_MANIFEST_INDEX = -1;
    DIVIDER_INDEX = -1;

    outlet(0, "clear");

    // Try nested layout first (stemforge/processed style).
    // Fall back to flat .json-in-dir layout.
    var nested = MANIFEST_DIR ? _listNestedTracks(MANIFEST_DIR) : [];
    var uiIdx = 0;

    if (nested.length > 0) {
        for (var i = 0; i < nested.length; i++) {
            var t = nested[i];
            var info = _inspectManifest(t.path);
            MANIFEST_ENTRIES.push({
                filename: t.track,
                displayName: t.label,
                path: t.path,
                bpm: info.bpm,
                bars: info.bars,
                stemCount: info.stemCount
            });
            outlet(0, "append", t.label);
            uiIdx++;
        }
    } else if (MANIFEST_DIR) {
        var filenames = _listManifestFilenames(MANIFEST_DIR);
        for (var j = 0; j < filenames.length; j++) {
            var filename = filenames[j];
            var posixPath = MANIFEST_DIR + "/" + filename;
            var info2 = _inspectManifest(posixPath);
            var displayName = _stripJsonExt(filename);
            MANIFEST_ENTRIES.push({
                filename: filename,
                displayName: displayName,
                path: posixPath,
                bpm: info2.bpm,
                bars: info2.bars,
                stemCount: info2.stemCount
            });
            outlet(0, "append", displayName);
            uiIdx++;
        }
    }

    DIVIDER_INDEX = uiIdx++;
    outlet(0, "append", "----");
    BROWSE_MANIFEST_INDEX = uiIdx++;
    outlet(0, "append", "Browse manifest...");
    BROWSE_INDEX = uiIdx;
    outlet(0, "append", "Browse audio...");

    log("scanManifests: " + MANIFEST_ENTRIES.length
        + " manifests from " + (MANIFEST_DIR || "(no dir)"));
}

function select(idx) {
    var i = Number(idx);
    if (isNaN(i) || i < 0) { log("select: bad index " + idx); return; }

    if (i === DIVIDER_INDEX) {
        log("select: divider chosen — ignoring");
        return;
    }

    if (i === BROWSE_MANIFEST_INDEX) {
        outlet(1, "browseManifest");
        log("select: browseManifest requested");
        return;
    }

    if (i === BROWSE_INDEX) {
        outlet(1, "browseAudio");
        log("select: browseAudio requested");
        return;
    }

    if (i >= MANIFEST_ENTRIES.length) {
        log("select: index " + i + " out of range");
        return;
    }

    var m = MANIFEST_ENTRIES[i];
    _writeManifestDict(m.path);

    var sourceRef = {
        filename: m.displayName,
        type: "manifest",
        path: m.path,
        bpm: m.bpm,
        bars: m.bars,
        stemCount: m.stemCount
    };

    var json;
    try { json = JSON.stringify(sourceRef); }
    catch (e) { log("select: stringify error: " + e); return; }

    outlet(1, "setSource", json);
    log("selected manifest [" + i + "] " + m.displayName);
}

// Copy the manifest JSON on disk into the [dict sf_manifest] object, which
// the legacy stemforge_loader.v0.js:loadFromDict reads. Without this the
// loader can't find stems/quadrants/etc. (see the "manifest has no stems
// object" error in early dev).
function _writeManifestDict(posixPath) {
    var raw = _readFileContents(posixPath);
    if (!raw) { log("_writeManifestDict: could not read " + posixPath); return; }
    try {
        var d = new Dict("sf_manifest");
        d.clear();
        d.parse(raw);
        log("wrote manifest JSON into sf_manifest dict (" + raw.length + " bytes)");
    } catch (e) {
        log("_writeManifestDict error: " + e);
    }
}

function manifestPath() {
    // A POSIX path to a .json manifest, selected via the [opendialog] that
    // the patch wires to `browseManifest`. Build a manifest-type SourceRef.
    var args = arrayfromargs(messagename, arguments).slice(1);
    if (!args.length) { log("manifestPath: empty"); return; }
    var posix = args.join(" ");

    var info = _inspectManifest(posix);
    var fn = _baseName(posix);
    var label = _stripJsonExt(fn);

    _writeManifestDict(posix);

    var sourceRef = {
        filename: label,
        type: "manifest",
        path: posix,
        bpm: info.bpm,
        bars: info.bars,
        stemCount: info.stemCount
    };

    var json;
    try { json = JSON.stringify(sourceRef); }
    catch (e) { log("manifestPath: stringify error: " + e); return; }

    outlet(1, "setSource", json);
    log("manifestPath: " + label
        + (info.bpm !== null ? " · " + info.bpm + " BPM" : "")
        + " · " + info.stemCount + " stems");
}

function audioPath() {
    // Joining with a space reassembles paths that Max may have split on spaces.
    var args = arrayfromargs(messagename, arguments).slice(1);
    if (!args.length) { log("audioPath: empty"); return; }
    var posix = args.join(" ");

    var filename = _baseName(posix);

    var durationSec = null;
    var sampleRate = null;
    try {
        if (typeof SoundFile !== "undefined") {
            var sf = new SoundFile(toMaxPath(posix));
            // SoundFile in classic Max exposes duration (ms) and samplerate.
            try {
                var durMs = sf.duration;
                if (typeof durMs === "number" && isFinite(durMs) && durMs > 0) {
                    durationSec = durMs / 1000.0;
                }
            } catch (_) {}
            try {
                var sr = sf.samplerate;
                if (typeof sr === "number" && isFinite(sr) && sr > 0) {
                    sampleRate = sr;
                }
            } catch (_) {}
            try { sf.close(); } catch (_) {}
        }
    } catch (e) {
        log("SoundFile probe failed (non-fatal): " + e);
    }

    var sourceRef = {
        filename: filename,
        type: "audio",
        path: posix,
        durationSec: durationSec,
        sampleRate: sampleRate
    };

    var json;
    try { json = JSON.stringify(sourceRef); }
    catch (e) { log("audioPath: stringify error: " + e); return; }

    outlet(1, "setSource", json);
    log("audioPath: " + filename
        + (durationSec !== null ? " · " + durationSec.toFixed(1) + "s" : "")
        + (sampleRate !== null ? " · " + sampleRate + "Hz" : ""));
}
