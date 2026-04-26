// sf_preset_loader.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] — scans the StemForge preset directory, populates a
// [umenu] via outlet 0, and on `select <index>` loads the chosen preset JSON
// into the `sf_preset` dict and emits a compact PresetRef to outlet 1
// (destined for sf_state_mgr setPreset).
//
// Protocol (see specs/stemforge_device_ui_contract.md §3, §6, §8):
//   in:   scan               — rescan preset dir, repopulate umenu
//         select <index>     — user picked umenu item N; load the preset
//
//   out0: clear                            (umenu reset)
//         append <displayName>             (one per preset)
//   out1: setPreset <presetRefJsonString>  (routed to sf_state_mgr)
//
// Preset dir resolution order:
//   1. ~/Documents/Max 9/Packages/StemForge/presets
//   2. ~/stemforge/presets
//   3. fallback: first candidate that exists — error if none.
// ─────────────────────────────────────────────────────────────────────────────

/* global autowatch, inlets, outlets, outlet, post, Folder, File, Dict,
   arrayfromargs, messagename */

autowatch = 1;
inlets = 1;
outlets = 2;   // 0: umenu population, 1: setPreset <json> to state manager

var PRESET_DIR = null;            // resolved POSIX path (e.g. /Users/zak/.../presets)
var PRESET_ENTRIES = [];          // [{ filename, displayName, name, ... }] — index-aligned with umenu

// Inline file-log helper (see sf_logger.js). Mirrored across every module.
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
    try { post("[sf_preset_loader] " + String(msg) + "\n"); } catch (_) {}
    _sfFileLog("sf_preset_loader", msg);
}

function toMaxPath(p) {
    var s = String(p);
    if (s.length > 0 && s.charAt(0) === "/") return "Macintosh HD:" + s;
    return s;
}

function _getHomePath() {
    // Mirrors stemforge_loader.v0.js approach — enumerate /Users/ and pick the
    // one that has a Max 9 Packages directory. Avoids relying on env vars that
    // classic [js] doesn't reliably expose.
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

function _resolvePresetDir() {
    var home = _getHomePath();
    var candidates = [
        home + "/Documents/Max 9/Packages/StemForge/presets",
        home + "/stemforge/presets",
        home + "/Documents/Max 8/Packages/StemForge/presets"
    ];
    for (var i = 0; i < candidates.length; i++) {
        if (_folderExistsAndHasAny(toMaxPath(candidates[i]))) return candidates[i];
    }
    log("preset dir not found — tried: " + candidates.join(", "));
    return null;
}

function _readFileContents(posixPath) {
    try {
        var f = new File(toMaxPath(posixPath), "read");
        if (!f.isopen) return null;
        // See sf_manifest_loader for why chunk size is 32767 (signed-short cap).
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
        return raw;
    } catch (e) {
        log("read error (" + posixPath + "): " + e);
        return null;
    }
}

function _listPresetFilenames(posixDir) {
    var names = [];
    try {
        var folder = new Folder(toMaxPath(posixDir));
        while (!folder.end) {
            var fn = String(folder.filename);
            // case-insensitive .json suffix check (old SpiderMonkey — no endsWith)
            if (fn.length > 5) {
                var tail = fn.substring(fn.length - 5).toLowerCase();
                if (tail === ".json" && fn.charAt(0) !== ".") {
                    names.push(fn);
                }
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

function _parsePresetFile(posixDir, filename) {
    var raw = _readFileContents(posixDir + "/" + filename);
    if (!raw) return null;
    var obj;
    try { obj = JSON.parse(raw); }
    catch (e) { log("parse error " + filename + ": " + e); return null; }
    return obj;
}

function _buildPresetRef(filename, obj) {
    // Preset JSON has evolved. Prefer the spec-compliant top-level fields but
    // fall back to the legacy nested `preset.{name,version}` shape used by
    // existing files like idm_production.json.
    var nested = (obj && obj.preset) ? obj.preset : {};

    var nameKey = (obj && obj.name) || nested.name || filename.replace(/\.json$/i, "");
    var displayName = (obj && obj.displayName) || nested.displayName || nested.name || nameKey;
    var version = (obj && obj.version) || nested.version || "";
    var paletteName = (obj && obj.palette) || null;

    var palettePreview = [];
    var targetCount = 0;
    var stems = (obj && obj.stems) ? obj.stems : {};

    for (var stemName in stems) {
        var stem = stems[stemName];
        if (!stem || !stem.targets || !stem.targets.length) continue;
        targetCount += stem.targets.length;

        var firstTarget = stem.targets[0];
        if (!firstTarget || !firstTarget.color) continue;
        var hex = null;
        if (typeof firstTarget.color === "string") {
            hex = firstTarget.color;
        } else if (typeof firstTarget.color === "object" && firstTarget.color.hex) {
            hex = String(firstTarget.color.hex);
        }
        if (hex && palettePreview.length < 6) palettePreview.push(hex);
    }

    return {
        filename: filename,
        name: String(nameKey),
        displayName: String(displayName),
        version: String(version),
        paletteName: paletteName,
        palettePreview: palettePreview,
        targetCount: targetCount
    };
}

// ── Public messages ─────────────────────────────────────────────────────────

function scan() {
    PRESET_DIR = _resolvePresetDir();
    PRESET_ENTRIES = [];

    outlet(0, "clear");

    if (!PRESET_DIR) {
        log("scan: no preset dir resolved");
        return;
    }

    var filenames = _listPresetFilenames(PRESET_DIR);
    for (var i = 0; i < filenames.length; i++) {
        var obj = _parsePresetFile(PRESET_DIR, filenames[i]);
        if (!obj) continue;
        var ref = _buildPresetRef(filenames[i], obj);
        PRESET_ENTRIES.push(ref);
        outlet(0, "append", ref.displayName);
    }

    log("scan: " + PRESET_ENTRIES.length + " presets from " + PRESET_DIR);
}

function select(idx) {
    var i = Number(idx);
    if (isNaN(i) || i < 0 || i >= PRESET_ENTRIES.length) {
        log("select: bad index " + idx);
        return;
    }
    var ref = PRESET_ENTRIES[i];
    if (!PRESET_DIR) {
        log("select: no PRESET_DIR — run scan first");
        return;
    }

    var raw = _readFileContents(PRESET_DIR + "/" + ref.filename);
    if (!raw) {
        log("select: cannot read " + ref.filename);
        return;
    }

    // Sanity-parse: if the JSON is malformed, don't mutate sf_preset.
    try { JSON.parse(raw); }
    catch (e) { log("select: JSON parse failed: " + e); return; }

    // Write full preset body into sf_preset dict. Two writes for robustness:
    // 1. Under "root" as a stringified blob — matches state-mgr convention,
    //    tolerated by readDictJson (unwraps root or returns outer).
    // 2. Top-level keys — so legacy stemforge_loader.v0.js's
    //    `presetData.stems` path works without unwrapping.
    try {
        var d = new Dict("sf_preset");
        d.clear();
        d.replace("root", raw);
        // Also write top-level keys for legacy reader.
        var parsed;
        try { parsed = JSON.parse(raw); } catch (_) { parsed = null; }
        if (parsed && typeof parsed === "object") {
            for (var k in parsed) {
                if (parsed.hasOwnProperty(k) && k !== "root") {
                    try { d.replace(k, parsed[k]); } catch (_) {}
                }
            }
        }
    } catch (e) {
        log("select: dict write error: " + e);
        return;
    }

    // Emit PresetRef (metadata only — full body lives in the dict).
    var refJson;
    try { refJson = JSON.stringify(ref); }
    catch (e) { log("select: stringify error: " + e); return; }

    outlet(1, "setPreset", refJson);
    log("selected preset [" + i + "] " + ref.displayName);
}

// classic [js] exposes top-level functions automatically; no exports needed.
