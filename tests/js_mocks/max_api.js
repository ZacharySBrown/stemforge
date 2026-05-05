// max_api.js
// ─────────────────────────────────────────────────────────────────────────────
// Mock implementations of the Max [js] (classic SpiderMonkey) runtime globals
// used by StemForge JS modules. Lives entirely in Node; no Max install needed.
//
// Scope: just enough surface to execute sf_preset_loader.js, sf_state.js,
// sf_forge.js, sf_arrangement_reader.js, sf_arrangement_loader.js,
// stemforge_loader.v0.js's `_commitSessionTracks`, and the priority-chain
// section of stemforge_loader.v0.js for offline regression tests.
//
// Module state is intentionally global-on-this-module so multiple modules
// loaded in the same sandbox share Dict state (mirroring the real Max runtime
// where `new Dict("sf_preset")` returns a handle to a single process-wide
// dict).
//
// LiveAPI hardening (Hardening Stream B.2):
//   The LiveAPI constructor traverses a backing `state.liveTree` — a nested
//   dict where each node has `_properties` (scalar properties accessible via
//   `.get(prop)`) and named children (collections as arrays, singletons as
//   objects). Path syntax mirrors Live's: space-separated tokens like
//   "live_set tracks 0 clip_slots 0 clip". Unseeded paths fall back to the
//   no-op behavior (returning 0 / [] / 'no-op set') so existing tests that
//   don't set up a tree continue to work.
//
//   LOM quirks honored (per `feedback_arrangement_clip_lom`):
//     * `warp_bpm` writes are silently dropped (read-only LOM property)
//     * `end_time` writes are silently dropped (read-only on Clip)
//     * Marker-unit flip with warping is exposed via `liveMarkerUnit(path)`
//       (returns "beats" if warping=1, "seconds" if warping=0). Mock does
//       NOT auto-convert; tests can assert the unit flag and verify caller
//       logic uses the right interpretation.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs = require('fs');
const path = require('path');

// LOM properties that the real Live runtime accepts writes for but silently
// ignores. Documented in `memory/feedback_arrangement_clip_lom.md`.
const LOM_READONLY_PROPS = Object.freeze({
    warp_bpm: true,
    end_time: true,
});

// Properties whose unit (seconds vs beats) flips with the clip's `warping`
// flag. Used by `liveMarkerUnit()` so tests can assert against the right
// numeric basis.
const LOM_MARKER_PROPS = Object.freeze({
    start_marker: true,
    end_marker: true,
    loop_start: true,
    loop_end: true,
});

// Shared global state per harness session.
const state = {
    dicts: Object.create(null),        // name -> plain object (the dict tree)
    fs: Object.create(null),           // hfs path -> { contents, isDir, entries? }
    logs: [],                          // post() captures
    outlets: Object.create(null),      // outletNum (number) -> list of arg-arrays
    liveApiCalls: [],                  // for optional inspection
    liveTree: null,                    // root LOM mock; null = unseeded → no-op
    liveCallHandlers: Object.create(null), // verb -> (lomPath, args) => result
    liveReadonlyDrops: [],             // log of writes silently dropped
};

function resetState() {
    state.dicts = Object.create(null);
    state.fs = Object.create(null);
    state.logs.length = 0;
    state.outlets = Object.create(null);
    state.liveApiCalls.length = 0;
    state.liveTree = null;
    state.liveCallHandlers = Object.create(null);
    state.liveReadonlyDrops.length = 0;
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

// ── liveTree path resolution ─────────────────────────────────────────────────
// Path syntax (LOM):  "live_set" | "live_set tracks 0" |
//   "live_set tracks 0 clip_slots 0 clip" |
//   "live_set cue_points 0".
//
// Tree shape:
//   {
//     _properties: { tempo: 120, signature_numerator: 4, ... },
//     tracks: [                          // collection (array)
//       {
//         _properties: { name: "A", color: 1 },
//         clip_slots: [
//           { _properties: { has_clip: 1 },
//             clip: {                     // scalar child (object, not array)
//               _properties: {
//                 file_path: "...", start_marker: 0, ..., warping: 1,
//               },
//               warp_markers: [ { _properties: {...} }, ... ],
//             },
//           },
//         ],
//         arrangement_clips: [...],
//       },
//     ],
//     cue_points: [
//       { _properties: { time: 0, name: "Verse" } },
//     ],
//   }

function _splitPath(pathStr) {
    return String(pathStr || '')
        .trim()
        .split(/\s+/)
        .filter(function (s) { return s.length; });
}

function _resolveNode(rootKey, segs) {
    if (!state.liveTree) return null;
    if (segs[0] !== rootKey) return null;
    let node = state.liveTree;
    let i = 1;
    while (i < segs.length) {
        const childKey = segs[i];
        const child = node[childKey];
        if (Array.isArray(child)) {
            // Collection — next seg is the index.
            const idxStr = segs[i + 1];
            if (idxStr === undefined) return null;
            const idx = Number(idxStr);
            if (!Number.isFinite(idx) || idx < 0 || idx >= child.length) return null;
            node = child[idx];
            if (!node) return null;
            i += 2;
        } else if (child && typeof child === 'object') {
            // Singleton child (e.g., clip_slot.clip) — no index follows.
            node = child;
            i += 1;
        } else {
            return null;
        }
    }
    return node;
}

// Public seeders for tests. Pass a plain JS object using the tree shape above.
function seedLiveTree(tree) {
    state.liveTree = tree || null;
}

function getLiveTree() {
    return state.liveTree;
}

// Set/get a property at any LOM path. For tests + diagnostics.
function setLiveProperty(lomPath, prop, value) {
    const segs = _splitPath(lomPath);
    if (!segs.length) return false;
    const node = _resolveNode(segs[0], segs);
    if (!node) return false;
    if (!node._properties) node._properties = {};
    node._properties[prop] = value;
    return true;
}

function getLiveProperty(lomPath, prop) {
    const segs = _splitPath(lomPath);
    if (!segs.length) return undefined;
    const node = _resolveNode(segs[0], segs);
    if (!node || !node._properties) return undefined;
    return node._properties[prop];
}

// Marker-unit oracle. Call after seeding a clip's warping flag to know which
// numeric basis loop_start/end + start/end_marker live in.
function liveMarkerUnit(lomPath) {
    const segs = _splitPath(lomPath);
    if (!segs.length) return 'beats';
    const node = _resolveNode(segs[0], segs);
    if (!node || !node._properties) return 'beats';
    const w = node._properties.warping;
    return (w === 0 || w === false) ? 'seconds' : 'beats';
}

// Register a handler for a specific LiveAPI.call() verb. Handler signature:
//   (lomPath, argsArray) -> any
function setLiveCallHandler(verb, handler) {
    state.liveCallHandlers[String(verb)] = handler;
}

// ── Mock LiveAPI ─────────────────────────────────────────────────────────────
function LiveAPI(pathOrCb, maybePath) {
    // Mirror Max LiveAPI: first arg can be a callback fn or a path string.
    this._path = typeof pathOrCb === 'string' ? pathOrCb : (maybePath || '');
    state.liveApiCalls.push({ ctor: this._path });
    // `id` mirrors Live's "0" = no object at this path / non-zero string
    // for a real LOM object. Used by code paths like _commitSessionTracks's
    // empty-slot check (`clipApi.id === "0"`).
    this._refreshId();
}

LiveAPI.prototype._refreshId = function () {
    if (!state.liveTree) {
        // Unseeded: keep id "0" (back-compat with prior no-op mock).
        this.id = '0';
        return;
    }
    const node = this._node();
    this.id = node ? '1' : '0';
};

LiveAPI.prototype._node = function () {
    if (!state.liveTree) return null;
    const segs = _splitPath(this._path);
    if (!segs.length) return null;
    return _resolveNode(segs[0], segs);
};

LiveAPI.prototype.getcount = function (childName) {
    if (!state.liveTree) return 0;
    const node = this._node();
    if (!node) return 0;
    const child = node[childName];
    return Array.isArray(child) ? child.length : 0;
};

LiveAPI.prototype.get = function (prop) {
    if (!state.liveTree) return [];
    const node = this._node();
    if (!node || !node._properties) return [];
    const val = node._properties[prop];
    if (val === undefined) return [];
    // LOM scalar reads return a 1-element array. Lists stay lists.
    return Array.isArray(val) ? val.slice() : [val];
};

LiveAPI.prototype.set = function (prop, value) {
    if (LOM_READONLY_PROPS[prop]) {
        // Mirror Live: silent drop.
        state.liveReadonlyDrops.push({ path: this._path, prop, value });
        return;
    }
    if (!state.liveTree) return;
    const node = this._node();
    if (!node) return;
    if (!node._properties) node._properties = {};
    node._properties[prop] = value;
};

LiveAPI.prototype.call = function (verb /* , ...args */) {
    const args = Array.prototype.slice.call(arguments, 1);
    const handlers = state.liveCallHandlers || {};
    const handler = handlers[verb];
    if (typeof handler === 'function') {
        return handler(this._path, args);
    }
    state.liveApiCalls.push({ unhandledCall: { path: this._path, verb, args } });
    return 0;
};

LiveAPI.prototype.goto = function (p) {
    this._path = String(p || '');
    this._refreshId();
};

// `property` is sometimes assigned on real LiveAPI for observer callbacks.
// Keep as a simple writable string; not load-bearing for our test paths.
LiveAPI.prototype.property = '';

// ── Exports ──────────────────────────────────────────────────────────────────
module.exports = {
    Dict,
    File,
    Folder,
    LiveAPI,
    LOM_READONLY_PROPS,
    LOM_MARKER_PROPS,
    post,
    outlet,
    arrayfromargs,
    state,
    resetState,
    seedFilesystem,
    seedDir,
    seedFile,
    seedLiveTree,
    getLiveTree,
    setLiveProperty,
    getLiveProperty,
    liveMarkerUnit,
    setLiveCallHandler,
};
