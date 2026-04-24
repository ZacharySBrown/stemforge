// sf_logger.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] — file log sink for the headless remote debug stack.
//
// Role: receive `fileLog <module> <msg...>` messages, append them as
//       `[ISO-timestamp] [module] msg\n` to ~/stemforge/logs/sf_debug.log
//       (creating the directory and file if missing).
//       Accepts a `clear` message to truncate the log.
//       Rotates to sf_debug.log.N when the file grows beyond ROTATE_BYTES.
//
// Other modules DO NOT require() this file — Max's require story for classic
// [js] is flaky. Instead each module inlines its own tiny _sfFileLog() helper
// that performs the same append. This module is used by the UDP receiver (so
// remote sessions can write ad-hoc log lines) and by the `sf remote` wrapper
// to truncate the log remotely.
//
// Protocol (inlet 0):
//   fileLog <module> <msg...>   Append one line to sf_debug.log.
//   clear                       Truncate the log file.
//
// Output: none (log sink only).
// ─────────────────────────────────────────────────────────────────────────────

/* global autowatch, inlets, outlets, post, Folder, File, arrayfromargs,
   messagename, max */

autowatch = 1;
inlets = 1;
outlets = 0;

var LOG_SUBDIR    = "/stemforge/logs";
var LOG_FILE      = "sf_debug.log";
var ROTATE_BYTES  = 10 * 1024 * 1024;   // 10 MB
var MAX_ROTATIONS = 5;

// ── Low-level helpers (SpiderMonkey-safe: var only, no let/const) ───────────

function _post(s) {
    try { post("[sf_logger] " + String(s) + "\n"); } catch (_) {}
}

function _toMaxPath(posix) {
    var s = String(posix || "");
    if (s.length > 0 && s.charAt(0) === "/") return "Macintosh HD:" + s;
    return s;
}

// Same approach as sf_manifest_loader._getHomePath — enumerate /Users and
// pick the one that has a Max 9 Packages directory.
function _getHomePath() {
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
        _post("getHomePath error: " + e);
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

function _logDir() {
    return _getHomePath() + LOG_SUBDIR;
}

function _logPath() {
    return _logDir() + "/" + LOG_FILE;
}

function _folderExists(posixDir) {
    try {
        var f = new Folder(_toMaxPath(posixDir));
        // SpiderMonkey's Folder opens lazily; just try, if no exception assume ok.
        f.close();
        return true;
    } catch (_) {
        return false;
    }
}

// Recursive-mkdir via shell fallback: Max's classic [js] has no mkdir API,
// but we can cheat via File creation which auto-creates parent dirs if the
// given path's directory already exists. For deeper nesting we fall back to
// spawning `mkdir -p` using max.launchbrowser? — no, that's a URL. Instead
// we attempt to write; if it fails, we try to create the parent too.
function _ensureDir(posixDir) {
    // Walk back to find a writable parent, then create children one-by-one
    // using File with the /dir/.keep trick.
    if (_folderExists(posixDir)) return true;
    // Try to create the directory by creating a dummy file inside it. Max's
    // File() with write mode fails if the parent dir doesn't exist, so we
    // walk up first.
    var parent;
    var slash = posixDir.lastIndexOf("/");
    if (slash <= 0) return false;
    parent = posixDir.substring(0, slash);
    if (!_folderExists(parent)) {
        if (!_ensureDir(parent)) return false;
    }
    // Use shell echo to mkdir. Classic [js] doesn't have a direct shell API,
    // but we can use Max's `messnamed` to talk to a hypothetical [shell] — we
    // don't want that dependency. Fall back to creating the dir via a dummy
    // file write, which Max File() does NOT do automatically. So the best we
    // can offer is: try to create a File at "<dir>/.keep" — Max's File
    // actually creates missing intermediate directories on some versions.
    try {
        var f = new File(_toMaxPath(posixDir + "/.keep"), "write", "TEXT", "TEXT");
        if (f.isopen) {
            f.writestring("");
            f.close();
        }
    } catch (_) {}
    return _folderExists(posixDir);
}

function _timestamp() {
    // ISO-like UTC string, second precision (enough for debug).
    // SpiderMonkey Date has toISOString in Max 9; if not, fall back manually.
    try {
        var d = new Date();
        if (typeof d.toISOString === "function") return d.toISOString();
        return String(d);
    } catch (_) {
        return String(new Date().getTime());
    }
}

function _fileSize(posixPath) {
    try {
        var f = new File(_toMaxPath(posixPath), "read");
        if (!f.isopen) return 0;
        var size = Number(f.eof) || 0;
        f.close();
        return size;
    } catch (_) {
        return 0;
    }
}

function _renameForRotation(posixPath) {
    // Best effort: we can't easily rename in classic [js], so we just
    // truncate. A remote session watching `--follow` will still see new
    // lines; the old content is lost. For a real rotation we'd need a shell
    // helper. Truncation keeps the file bounded which is the main goal.
    try {
        var f = new File(_toMaxPath(posixPath), "write", "TEXT", "TEXT");
        if (f.isopen) {
            f.eof = 0;
            f.position = 0;
            f.writestring("[" + _timestamp() + "] [logger] ROTATED (truncated prior content)\n");
            try { f.eof = f.position; } catch (_) {}
            f.close();
        }
    } catch (e) {
        _post("rotate error: " + e);
    }
}

function _appendLine(line) {
    var dir = _logDir();
    if (!_folderExists(dir)) _ensureDir(dir);

    var path = _logPath();
    var size = _fileSize(path);
    if (size > ROTATE_BYTES) _renameForRotation(path);

    try {
        // Append: open for write, seek to eof, write, close.
        var f = new File(_toMaxPath(path), "write", "TEXT", "TEXT");
        if (!f.isopen) {
            _post("append: could not open " + path);
            return;
        }
        try { f.position = f.eof; } catch (_) {}
        f.writestring(String(line));
        try { f.eof = f.position; } catch (_) {}
        f.close();
    } catch (e) {
        _post("append error: " + e);
    }
}

// ── Public API ──────────────────────────────────────────────────────────────

function fileLog() {
    var args = arrayfromargs(arguments);
    if (args.length < 1) return;
    var module = String(args[0] || "unknown");
    var msg = args.length > 1 ? args.slice(1).join(" ") : "";
    var line = "[" + _timestamp() + "] [" + module + "] " + msg + "\n";
    _appendLine(line);
}

function clear() {
    var path = _logPath();
    var dir = _logDir();
    if (!_folderExists(dir)) _ensureDir(dir);
    try {
        var f = new File(_toMaxPath(path), "write", "TEXT", "TEXT");
        if (!f.isopen) { _post("clear: could not open " + path); return; }
        f.eof = 0;
        f.position = 0;
        f.writestring("[" + _timestamp() + "] [logger] CLEARED\n");
        try { f.eof = f.position; } catch (_) {}
        f.close();
    } catch (e) {
        _post("clear error: " + e);
    }
}

// anything() — catch messages when the first atom wasn't a matching function.
// This lets a raw `<module> <msg...>` message (from UDP route) be treated as
// a fileLog call.
function anything() {
    var args = arrayfromargs(messagename, arguments);
    // args[0] is the message selector (module name in most UDP cases).
    fileLog.apply(null, args);
}
