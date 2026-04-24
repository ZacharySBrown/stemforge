// max_api.js
// ─────────────────────────────────────────────────────────────────────────────
// Mock implementations of the Max [js] (classic SpiderMonkey) runtime globals
// used by StemForge JS modules. Lives entirely in Node; no Max install needed.
//
// Scope: just enough surface to execute sf_preset_loader.js, sf_state.js,
// sf_forge.js, and the priority-chain section of stemforge_loader.v0.js for
// offline regression tests.
//
// Module state is intentionally global-on-this-module so multiple modules
// loaded in the same sandbox share Dict state (mirroring the real Max runtime
// where `new Dict("sf_preset")` returns a handle to a single process-wide
// dict).
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs = require('fs');
const path = require('path');

// Shared global state per harness session.
const state = {
    dicts: Object.create(null),        // name -> plain object (the dict tree)
    fs: Object.create(null),           // hfs path -> { contents, isDir, entries? }
    logs: [],                          // post() captures
    outlets: Object.create(null),      // outletNum (number) -> list of arg-arrays
    liveApiCalls: [],                  // for optional inspection
};

function resetState() {
    state.dicts = Object.create(null);
    state.fs = Object.create(null);
    state.logs.length = 0;
    state.outlets = Object.create(null);
    state.liveApiCalls.length = 0;
}

// ── Path helpers ─────────────────────────────────────────────────────────────
// Max hfs paths look like "Macintosh HD:/Users/zak/..." — normalise to POSIX.
function _hfsToPosix(p) {
    let s = String(p);
    if (s.indexOf('Macintosh HD:') === 0) s = s.slice('Macintosh HD:'.length);
    // Normalize trailing slashes (Max callers sometimes send "/Users/", our
    // seed keys never have a trailing slash unless path === '/').
    if (s.length > 1 && s.charAt(s.length - 1) === '/') s = s.slice(0, -1);
    return s;
}

// Seed the mock filesystem from real files/directories on disk. Call this
// before loading any module that reads files via `new File(...)` / `new Folder(...)`.
// `realPath` must exist. `hfsMountPoint` is the path the JS code will ask for
// (e.g. "/Users/zak/Documents/Max 9/Packages/StemForge/presets").
function seedFilesystem(realPath, hfsMountPoint) {
    const abs = path.resolve(realPath);
    if (!fs.existsSync(abs)) {
        throw new Error('seedFilesystem: source does not exist: ' + abs);
    }
    const stat = fs.statSync(abs);
    if (stat.isDirectory()) {
        const entries = fs.readdirSync(abs);
        state.fs[hfsMountPoint] = { isDir: true, entries };
        for (const e of entries) {
            seedFilesystem(path.join(abs, e), hfsMountPoint + '/' + e);
        }
    } else if (stat.isFile()) {
        state.fs[hfsMountPoint] = { isDir: false, contents: fs.readFileSync(abs, 'utf8') };
    }
}

// Manually seed a directory listing (so the loader's preset-dir probe finds it
// even if you don't seed real files).
function seedDir(hfsMountPoint, entries) {
    state.fs[hfsMountPoint] = { isDir: true, entries: entries.slice() };
}

// Seed a single file's contents.
function seedFile(hfsMountPoint, contents) {
    state.fs[hfsMountPoint] = { isDir: false, contents: String(contents) };
}

// ── Mock Dict ────────────────────────────────────────────────────────────────
// `new Dict(name)` in Max returns a handle to a global (per-patch) named dict.
// We mirror that: all `new Dict("sf_preset")` share one backing object.
function Dict(name) {
    if (!state.dicts[name]) state.dicts[name] = Object.create(null);
    this._name = String(name);
}

Dict.prototype._tree = function () {
    return state.dicts[this._name];
};

Dict.prototype._setTree = function (obj) {
    state.dicts[this._name] = obj || Object.create(null);
};

Dict.prototype.parse = function (jsonString) {
    try {
        const parsed = JSON.parse(String(jsonString));
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            this._setTree(parsed);
        } else {
            // Max's real behavior wraps primitives under a generic root; we
            // just overwrite the whole tree with the parsed value.
            this._setTree({ __raw: parsed });
        }
    } catch (e) {
        // Mimic Max: log, leave dict unchanged.
        post('[Dict.parse] error: ' + e + '\n');
    }
};

Dict.prototype.stringify = function () {
    try {
        return JSON.stringify(this._tree());
    } catch (e) {
        return '{}';
    }
};

Dict.prototype.replace = function (key, value) {
    const tree = this._tree();
    // Max accepts either a string (which it tries to parse as JSON for object
    // values) or a primitive / object. We mirror: if `value` is a string that
    // begins with { or [, parse it; otherwise store as-is.
    if (typeof value === 'string') {
        const trimmed = value.replace(/^\s+/, '');
        if (trimmed.length && (trimmed.charAt(0) === '{' || trimmed.charAt(0) === '[')) {
            try {
                tree[key] = JSON.parse(value);
                return;
            } catch (_) {
                // fall through: store the raw string
            }
        }
        tree[key] = value;
        return;
    }
    // Object / array / number / bool — just store.
    tree[key] = value;
};

Dict.prototype.get = function (key) {
    const tree = this._tree();
    return tree[key];
};

Dict.prototype.clear = function () {
    this._setTree(Object.create(null));
};

// ── Mock File ────────────────────────────────────────────────────────────────
function File(hfsPath, mode) {
    this._path = _hfsToPosix(hfsPath);
    this._mode = String(mode || 'read');
    const entry = state.fs[this._path];
    if (entry && !entry.isDir) {
        this._contents = String(entry.contents);
        this.isopen = 1;
        this.position = 0;
        this.eof = this._contents.length;
    } else {
        this._contents = '';
        this.isopen = 0;
        this.position = 0;
        this.eof = 0;
    }
}

File.prototype.readstring = function (n) {
    const take = Math.min(Number(n) || 0, this._contents.length - this.position);
    const out = this._contents.substr(this.position, take);
    this.position += take;
    return out;
};

File.prototype.close = function () {
    this.isopen = 0;
};

File.prototype.write = function (/* data */) {
    // Unused by the code we test, but keep the shape.
};

// ── Mock Folder ──────────────────────────────────────────────────────────────
function Folder(hfsPath) {
    this._path = _hfsToPosix(hfsPath);
    const entry = state.fs[this._path];
    if (entry && entry.isDir) {
        this._entries = entry.entries.slice();
        this._i = 0;
    } else {
        this._entries = [];
        this._i = 0;
    }
    this._updateView();
}

Folder.prototype._updateView = function () {
    if (this._i >= this._entries.length) {
        this.end = 1;
        this.filename = '';
        this.filetype = '';
        return;
    }
    this.end = 0;
    this.filename = this._entries[this._i];
    const childPath = this._path + '/' + this._entries[this._i];
    const child = state.fs[childPath];
    this.filetype = (child && child.isDir) ? 'fold' : 'file';
};

Folder.prototype.next = function () {
    this._i += 1;
    this._updateView();
};

Folder.prototype.close = function () {
    // no-op
};

// ── Mock post / outlet / arrayfromargs ───────────────────────────────────────
function post(/* ...args */) {
    const parts = [];
    for (let i = 0; i < arguments.length; i++) parts.push(String(arguments[i]));
    state.logs.push(parts.join(''));
}

function outlet(n /* , ...args */) {
    const args = Array.prototype.slice.call(arguments, 1);
    if (!state.outlets[n]) state.outlets[n] = [];
    state.outlets[n].push(args);
}

function arrayfromargs(/* ...args */) {
    // Classic Max signature: `arrayfromargs(messagename, arguments)` returns
    // [messagename, ...arguments]. BUT most usages in StemForge call it as
    // `arrayfromargs(arguments)` to convert the `arguments` object into a real
    // array WITHOUT prepending the messagename. We honor both.
    if (arguments.length === 1 &&
        typeof arguments[0] === 'object' && arguments[0] !== null &&
        typeof arguments[0].length === 'number') {
        // Treat the single arguments-like as the list.
        const arr = [];
        for (let i = 0; i < arguments[0].length; i++) arr.push(arguments[0][i]);
        return arr;
    }
    // Multi-arg form — just concatenate everything that was passed in.
    const out = [];
    for (let i = 0; i < arguments.length; i++) {
        const a = arguments[i];
        if (a && typeof a === 'object' && typeof a.length === 'number') {
            for (let j = 0; j < a.length; j++) out.push(a[j]);
        } else {
            out.push(a);
        }
    }
    return out;
}

// ── Mock LiveAPI ─────────────────────────────────────────────────────────────
function LiveAPI(pathOrCb, maybePath) {
    // Minimal — don't throw on construction. Track calls for optional assertions.
    this._path = typeof pathOrCb === 'string' ? pathOrCb : maybePath || '';
    state.liveApiCalls.push({ ctor: this._path });
}
LiveAPI.prototype.getcount = function () { return 0; };
LiveAPI.prototype.get = function () { return []; };
LiveAPI.prototype.set = function () { /* no-op */ };
LiveAPI.prototype.call = function () { return 0; };
LiveAPI.prototype.goto = function () { /* no-op */ };
LiveAPI.prototype.property = '';

// ── Exports ──────────────────────────────────────────────────────────────────
module.exports = {
    Dict,
    File,
    Folder,
    LiveAPI,
    post,
    outlet,
    arrayfromargs,
    state,
    resetState,
    seedFilesystem,
    seedDir,
    seedFile,
};
