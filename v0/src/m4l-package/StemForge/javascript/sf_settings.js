// sf_settings.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] — reads/writes the StemForge settings.json, mirrors its
// contents into the `sf_settings` dict. Everything else reads the dict; this
// module is the only path to disk for settings.
//
// Protocol (see specs/stemforge_device_ui_contract.md §2):
//   in:   load                   — read settings.json into sf_settings dict;
//                                  create with defaults if missing
//         save                   — persist sf_settings.root back to disk
//         get <dotted.path>      — emit that value out outlet 0 as a list:
//                                      get <dotted.path> <value>
//         set <dotted.path> ...  — update sf_settings, save to disk
//         openFile               — emit shell command out outlet 0 so the
//                                  patch can open settings.json in the
//                                  user's default editor (open <posix>)
//
//   out0: get replies and editor-open commands
//   out1: bang after mutations (so downstream can refresh)
//
// Settings file:
//   ~/Documents/Max 9/Packages/StemForge/settings.json
// ─────────────────────────────────────────────────────────────────────────────

/* global autowatch, inlets, outlets, outlet, post, Folder, File, Dict,
   arrayfromargs, messagename, max */

autowatch = 1;
inlets = 1;
outlets = 2;  // 0: get/openFile replies, 1: bang on mutation

var DICT_NAME = "sf_settings";

var DEFAULTS = {
    splitting: {
        engine: "demucs",
        model: "htdemucs_ft",
        device: "gpu",
        outputSampleRate: 44100,
        outputBitDepth: 16,
        cacheSplits: true
    },
    workflow: {
        trackPrefix: "{source} {target}",
        manifestDir: "~/stemforge/processed",
        presetDir: "~/Documents/Max 9/Packages/StemForge/presets"
    }
};

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
    try { post("[sf_settings] " + String(msg) + "\n"); } catch (_) {}
    _sfFileLog("sf_settings", msg);
}

function toMaxPath(p) {
    var s = String(p);
    if (s.length > 0 && s.charAt(0) === "/") return "Macintosh HD:" + s;
    return s;
}

function _getHomePath() {
    // Prefer Max's getsystemvariable when available (more reliable), then
    // fall back to /Users/ enumeration for consistency with the other
    // StemForge JS modules.
    try {
        if (typeof max !== "undefined" && max && typeof max.getsystemvariable === "function") {
            var h = max.getsystemvariable("HOME");
            if (h) return String(h);
        }
    } catch (_) {}
    try {
        if (typeof File !== "undefined" && typeof File.getenv === "function") {
            var h2 = File.getenv("HOME");
            if (h2) return String(h2);
        }
    } catch (_) {}

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
        log("_getHomePath error: " + e);
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

function expandHome(p) {
    if (!p) return p;
    var s = String(p);
    if (s.charAt(0) !== "~") return s;
    return _getHomePath() + s.substring(1);
}

function _settingsPath() {
    return _getHomePath() + "/Documents/Max 9/Packages/StemForge/settings.json";
}

function _readFile(posixPath) {
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

function _writeFile(posixPath, text) {
    try {
        // Classic [js]: new File(name, mode, type, creator). TEXT/TEXT is safe.
        var f = new File(toMaxPath(posixPath), "write", "TEXT", "TEXT");
        if (!f.isopen) { log("write: not open " + posixPath); return false; }
        // Ensure clean overwrite.
        try { f.eof = 0; } catch (_) {}
        f.position = 0;
        f.writestring(text);
        try { f.eof = f.position; } catch (_) {}
        f.close();
        return true;
    } catch (e) {
        log("write error (" + posixPath + "): " + e);
        return false;
    }
}

function _dictToObject() {
    try {
        var d = new Dict(DICT_NAME);
        var raw = d.stringify();
        if (!raw || raw === "{}") return null;
        var obj = JSON.parse(raw);
        return (obj && obj.root) ? obj.root : obj;
    } catch (e) {
        log("_dictToObject error: " + e);
        return null;
    }
}

function _writeDictFromObject(obj) {
    try {
        var d = new Dict(DICT_NAME);
        d.replace("root", JSON.stringify(obj));
        return true;
    } catch (e) {
        log("_writeDictFromObject error: " + e);
        return false;
    }
}

function _walkPath(obj, dotted) {
    if (!dotted) return undefined;
    var parts = String(dotted).split(".");
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
        if (cur === null || typeof cur !== "object") return undefined;
        cur = cur[parts[i]];
    }
    return cur;
}

function _setPath(obj, dotted, value) {
    var parts = String(dotted).split(".");
    if (!parts.length) return false;
    var cur = obj;
    for (var i = 0; i < parts.length - 1; i++) {
        var key = parts[i];
        if (typeof cur[key] !== "object" || cur[key] === null) {
            cur[key] = {};
        }
        cur = cur[key];
    }
    cur[parts[parts.length - 1]] = value;
    return true;
}

function _coerceValue(raw) {
    // set messages may arrive already-coerced (numbers as JS numbers) or as a
    // list of atoms. Accept common forms.
    if (raw === null || raw === undefined) return raw;
    if (typeof raw === "number" || typeof raw === "boolean") return raw;
    var s = String(raw);
    if (s === "true") return true;
    if (s === "false") return false;
    if (s === "null") return null;
    // Numeric? Only if it looks like a clean number.
    if (s.length > 0 && /^-?\d+(\.\d+)?$/.test(s)) {
        var n = Number(s);
        if (isFinite(n)) return n;
    }
    return s;
}

function _cloneDefaults() {
    // Plain deep clone — defaults are JSON-safe.
    return JSON.parse(JSON.stringify(DEFAULTS));
}

// ── Public messages ─────────────────────────────────────────────────────────

function load() {
    var path = _settingsPath();
    var raw = _readFile(path);

    if (!raw) {
        // First run: seed defaults to disk AND to dict.
        log("load: no settings file, writing defaults to " + path);
        var defaults = _cloneDefaults();
        _writeDictFromObject(defaults);
        _writeFile(path, JSON.stringify(defaults, null, 2));
        outlet(1, "bang");
        return;
    }

    var obj;
    try { obj = JSON.parse(raw); }
    catch (e) {
        log("load: parse error, keeping defaults: " + e);
        obj = _cloneDefaults();
    }

    // Merge defaults underneath what's on disk so upgrades don't lose new keys.
    var merged = _cloneDefaults();
    for (var topKey in obj) {
        if (!obj.hasOwnProperty(topKey)) continue;
        if (typeof obj[topKey] === "object" && obj[topKey] !== null && !Array.isArray(obj[topKey])) {
            if (!merged[topKey] || typeof merged[topKey] !== "object") merged[topKey] = {};
            for (var subKey in obj[topKey]) {
                if (obj[topKey].hasOwnProperty(subKey)) merged[topKey][subKey] = obj[topKey][subKey];
            }
        } else {
            merged[topKey] = obj[topKey];
        }
    }

    _writeDictFromObject(merged);
    log("load: settings loaded from " + path);
    outlet(1, "bang");
}

function save() {
    var obj = _dictToObject();
    if (!obj) {
        log("save: dict empty, seeding defaults");
        obj = _cloneDefaults();
        _writeDictFromObject(obj);
    }
    var path = _settingsPath();
    var ok = _writeFile(path, JSON.stringify(obj, null, 2));
    log("save: " + (ok ? "wrote " : "failed ") + path);
    outlet(1, "bang");
}

function get() {
    var args = arrayfromargs(messagename, arguments).slice(1);
    if (!args.length) { log("get: missing path"); return; }
    var dotted = args.join(".");  // Max splits 'splitting.engine' on '.' sometimes? keep safe.
    // If caller sent a single symbol, args.length===1 and join(".") === that symbol.
    var obj = _dictToObject();
    if (!obj) {
        // Try loading from disk on first access.
        load();
        obj = _dictToObject();
    }
    var val = _walkPath(obj, dotted);
    if (val === undefined) {
        log("get: no value at " + dotted);
        outlet(0, "get", dotted, "");
        return;
    }
    if (typeof val === "object") {
        try { outlet(0, "get", dotted, JSON.stringify(val)); }
        catch (e) { log("get: stringify error: " + e); }
    } else {
        outlet(0, "get", dotted, val);
    }
}

function set() {
    var args = arrayfromargs(messagename, arguments).slice(1);
    if (args.length < 2) { log("set: expected <path> <value>"); return; }
    var dotted = String(args[0]);
    var rawValue;
    if (args.length === 2) {
        rawValue = args[1];
    } else {
        // Multiple trailing atoms → join with spaces (handles "{source} {target}")
        rawValue = args.slice(1).join(" ");
    }
    var value = _coerceValue(rawValue);

    var obj = _dictToObject();
    if (!obj) obj = _cloneDefaults();

    _setPath(obj, dotted, value);
    _writeDictFromObject(obj);

    var path = _settingsPath();
    _writeFile(path, JSON.stringify(obj, null, 2));
    log("set " + dotted + " = " + (typeof value === "object" ? JSON.stringify(value) : value));
    outlet(1, "bang");
}

function openFile() {
    var path = _settingsPath();
    // Emit in shell form — patch can feed this into [shell] directly.
    // Also include the raw path as a secondary atom in case the patch wires
    // openFile through [prepend shell] + [prepend open] etc.
    outlet(0, "shell", "open", path);
    log("openFile: " + path);
}
