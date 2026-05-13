/**
 * max-stub.js — Node-side stub for the Max/M4L JS environment.
 *
 * Provides Max-API-shaped globals so device JS (the .js files in
 * v0/src/m4l-js/) can be `require()`'d into Node tests without the Max
 * runtime present. Pre-seed LOM state from a `tests/fixtures/lom_snapshots/`
 * JSON file, drive the device JS under test, assert on the recorded
 * `outlet()` / `messnamed()` emissions.
 *
 * Required reading: specs/CONSOLIDATED_DESIGN.md §7.5
 * Companion: tests/fixtures/lom_snapshots/README.md
 *
 * Surface covered:
 *   - Dict (named, parse/replace/get/set/getkeys)
 *   - LiveAPI (path walking against a seeded snapshot, get/set/getcount/call)
 *   - outlet(idx, ...args) → outletEmissions
 *   - messnamed(name, ...args) → messnamedCalls
 *   - post(...args) → postLog
 *   - arrayfromargs(args) → Array.from(args)
 *   - Folder, File (Node fs-backed for `[opendialog]`-style code)
 *
 * Programmable hooks (also installed as globals):
 *   - loadLomSnapshot(jsonPath: string): void
 *   - loadLomSnapshotObject(obj: object): void
 *   - resetMaxStub(): void
 *
 * Usage from a test::
 *
 *     require('../../tools/test-harness/max-stub.js');
 *     loadLomSnapshot('tests/fixtures/lom_snapshots/empty-set.json');
 *     // …drive device code…
 *     expect(outletEmissions).toEqual([…]);
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

// ---------------------------------------------------------------------------
// Mutable state — reset by resetMaxStub()
// ---------------------------------------------------------------------------

/** @type {object} Pre-seeded LOM tree. */
let _lomSnapshot = { live_set: { tracks: [] } };

/** Named Dict registry shared across `new Dict(name)` calls with the same name. */
let _dictRegistry = new Map();

/** @type {{ idx: number, args: any[] }[]} */
let _outletEmissions = [];

/** @type {{ name: string, args: any[] }[]} */
let _messnamedCalls = [];

/** @type {string[]} */
let _postLog = [];

// ---------------------------------------------------------------------------
// Dict
// ---------------------------------------------------------------------------

class Dict {
  /**
   * @param {string} name
   */
  constructor(name) {
    this.name = name || "";
    if (!_dictRegistry.has(this.name)) {
      _dictRegistry.set(this.name, {});
    }
    this._store = _dictRegistry.get(this.name);
  }

  get(key) {
    if (this._store == null) return null;
    return _cloneDeep(this._store[key]);
  }

  set(key, value) {
    this._store[key] = _cloneDeep(value);
  }

  replace(jsonString) {
    const parsed = JSON.parse(jsonString);
    // Clear in-place so all aliases stay in sync.
    for (const k of Object.keys(this._store)) delete this._store[k];
    for (const [k, v] of Object.entries(parsed)) this._store[k] = v;
  }

  parse(jsonString) {
    // Alias for replace in Max's API.
    return this.replace(jsonString);
  }

  getkeys() {
    return Object.keys(this._store);
  }

  /** Drop the entire backing store. */
  clear() {
    for (const k of Object.keys(this._store)) delete this._store[k];
  }

  /** JSON snapshot of the dict's contents (test-only helper). */
  toJSON() {
    return _cloneDeep(this._store);
  }
}

// ---------------------------------------------------------------------------
// LiveAPI
// ---------------------------------------------------------------------------

/**
 * Walks a snapshot path like
 *   ["live_set", "tracks", 0, "clip_slots", 5, "clip"]
 * and returns the targeted node (or null if absent).
 */
function _walkSnapshot(parts) {
  let node = _lomSnapshot;
  for (const part of parts) {
    if (node == null) return null;
    if (typeof part === "number") {
      if (!Array.isArray(node)) return null;
      node = node[part];
    } else {
      node = node[part];
    }
  }
  return node === undefined ? null : node;
}

/**
 * Parse a Max LiveAPI path string into structured parts.
 *
 * "live_set tracks 2 clip_slots 5 clip" →
 *   ["live_set", "tracks", 2, "clip_slots", 5, "clip"]
 */
function _parseLomPath(pathStr) {
  if (!pathStr) return [];
  const tokens = String(pathStr).trim().split(/\s+/);
  return tokens.map((t) => {
    const n = Number(t);
    return Number.isInteger(n) && /^-?\d+$/.test(t) ? n : t;
  });
}

class LiveAPI {
  /**
   * @overload
   * @param {string} pathStr
   *
   * @overload
   * @param {Function} cb
   * @param {string} pathStr
   */
  constructor(arg0, arg1) {
    let pathStr;
    if (typeof arg0 === "function") {
      // (callback, path) form — callback is for property observation; tests
      // can fire it manually if needed.
      this._callback = arg0;
      pathStr = arg1 || "";
    } else {
      this._callback = null;
      pathStr = arg0 || "";
    }
    this.path = pathStr;
    this.unquotedpath = pathStr;
    this._parts = _parseLomPath(pathStr);
    this._node = _walkSnapshot(this._parts);
    // Synthetic LOM id — stable per path string for the lifetime of the
    // snapshot. 0 means "no object" in Max's API; we mirror that.
    this.id = this._node == null ? 0 : _hashString(pathStr) || 1;
  }

  /** Get a property of the current LOM node. Returns an array, mirroring Max. */
  get(prop) {
    if (this._node == null) return [];
    const value = this._node[prop];
    if (value === undefined || value === null) return [];
    return Array.isArray(value) ? _cloneDeep(value) : [_cloneDeep(value)];
  }

  /** Set a property of the current LOM node. */
  set(prop, ...values) {
    if (this._node == null) return;
    this._node[prop] = values.length === 1 ? values[0] : values;
  }

  /**
   * Number of children at a named sub-collection. Mirrors Max's getcount.
   */
  getcount(child) {
    if (this._node == null) return 0;
    const arr = this._node[child];
    return Array.isArray(arr) ? arr.length : 0;
  }

  /** Names of children at a named sub-collection (returns ids in Max; we return names). */
  getchildren(child) {
    if (this._node == null) return [];
    const arr = this._node[child];
    if (!Array.isArray(arr)) return [];
    return arr.map((_, i) => i);
  }

  /**
   * Generic LOM verb. Records to a per-instance log AND to a global so tests
   * can assert without an instance ref. A small set of well-understood verbs
   * also mutate the snapshot so device code that reads back state (e.g.
   * trackCount() after create_audio_track) behaves like in Live.
   */
  call(verb, ...args) {
    _liveApiCalls.push({ path: this.path, verb, args });
    _maybeMutateForVerb(this, verb, args);
    return null;
  }

  /** Reposition this LiveAPI to a new path. */
  goto(newPath) {
    this.path = newPath;
    this.unquotedpath = newPath;
    this._parts = _parseLomPath(newPath);
    this._node = _walkSnapshot(this._parts);
    this.id = this._node == null ? 0 : _hashString(newPath) || 1;
  }
}

/** @type {{path: string, verb: string, args: any[]}[]} */
let _liveApiCalls = [];

/**
 * Mutator dispatch for the well-understood Live LOM verbs. The set is small
 * and intentional: device code that reads back LOM state (e.g.
 * `trackCount()` after `create_audio_track`) needs the snapshot to update.
 * Verbs that don't mutate state in a way device JS depends on (e.g.
 * `duplicate_track` modulo template-track tests) are left for later.
 */
function _maybeMutateForVerb(apiInstance, verb, args) {
  if (verb === "create_audio_track") {
    if (!_lomSnapshot.live_set) _lomSnapshot.live_set = { tracks: [] };
    const tracks = _lomSnapshot.live_set.tracks || (_lomSnapshot.live_set.tracks = []);
    const insertIdx = typeof args[0] === "number" ? args[0] : -1;
    const newTrack = {
      name: `Audio ${tracks.length + 1}`,
      clip_slots: Array.from({ length: 12 }, () => ({ clip: null })),
    };
    if (insertIdx < 0 || insertIdx >= tracks.length) {
      tracks.push(newTrack);
    } else {
      tracks.splice(insertIdx, 0, newTrack);
    }
    return;
  }
  if (verb === "delete_track") {
    if (!_lomSnapshot.live_set || !Array.isArray(_lomSnapshot.live_set.tracks)) return;
    const idx = typeof args[0] === "number" ? args[0] : -1;
    if (idx >= 0 && idx < _lomSnapshot.live_set.tracks.length) {
      _lomSnapshot.live_set.tracks.splice(idx, 1);
    }
    return;
  }
  if (verb === "create_clip") {
    // Path is the clip slot ("live_set tracks N clip_slots M"). Install a
    // minimal clip object so subsequent `new LiveAPI(... clip)` can address
    // it. The device JS sets file_path, name, warp_bpm, loop_*, looping via
    // set() — those land directly on this object.
    const parts = _parseLomPath(apiInstance.path);
    const slot = _walkSnapshot(parts);
    if (slot && typeof slot === "object") {
      slot.clip = {
        name: "",
        file_path: "",
        warp_bpm: 120,
        loop_start: 0,
        loop_end: typeof args[0] === "number" ? args[0] : 4,
        looping: 1,
      };
    }
    return;
  }
  if (verb === "create_audio_clip") {
    // Legacy verb used by `loadClip()`. Same shape as create_clip.
    const parts = _parseLomPath(apiInstance.path);
    const slot = _walkSnapshot(parts);
    if (slot && typeof slot === "object") {
      slot.clip = {
        name: "",
        file_path: typeof args[0] === "string" ? args[0] : "",
        warp_bpm: 120,
        loop_start: 0,
        loop_end: 4,
        looping: 1,
      };
    }
    return;
  }
  if (verb === "duplicate_track") {
    // Cheap clone — used by the legacy loader path. Not required by Phase 1C
    // tests but handy if other tests start using the stub.
    if (!_lomSnapshot.live_set || !Array.isArray(_lomSnapshot.live_set.tracks)) return;
    const idx = typeof args[0] === "number" ? args[0] : -1;
    if (idx >= 0 && idx < _lomSnapshot.live_set.tracks.length) {
      const src = _lomSnapshot.live_set.tracks[idx];
      const clone = _cloneDeep(src);
      _lomSnapshot.live_set.tracks.splice(idx + 1, 0, clone);
    }
  }
}

// ---------------------------------------------------------------------------
// outlet / messnamed / post / arrayfromargs
// ---------------------------------------------------------------------------

function outlet(idx, ...args) {
  _outletEmissions.push({ idx, args });
}

function messnamed(name, ...args) {
  _messnamedCalls.push({ name, args });
}

function post(...args) {
  _postLog.push(args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" "));
}

/**
 * Max's `arrayfromargs` is a magic vararg flattener used inside [js] message
 * handlers: callers typically write `arrayfromargs(messagename, arguments)`,
 * producing `[messagename, ...arguments]`. We mirror that behaviour so the
 * device JS can be required unmodified in Node.
 *
 * Each argument is either appended as-is (scalar) or spread (arguments object
 * / array). Strings are treated as scalars (NOT spread character-by-character),
 * matching Max's behaviour where the message name lands as a single token.
 */
function arrayfromargs(...inputs) {
  const out = [];
  for (const arg of inputs) {
    if (arg == null) continue;
    if (typeof arg === "string") {
      out.push(arg);
    } else if (typeof arg.length === "number" && typeof arg !== "function") {
      // arguments object or array.
      for (let i = 0; i < arg.length; i += 1) out.push(arg[i]);
    } else {
      out.push(arg);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Folder, File (minimal fs-backed)
// ---------------------------------------------------------------------------

class Folder {
  constructor(p) {
    this.pathname = p;
    try {
      this._entries = fs.readdirSync(p);
      this._index = 0;
    } catch {
      this._entries = [];
      this._index = 0;
    }
  }

  get end() {
    return this._index >= this._entries.length;
  }

  get filename() {
    return this._entries[this._index] || "";
  }

  next() {
    this._index += 1;
  }

  close() {
    /* noop */
  }
}

/**
 * Minimal `File` shim. Max addresses files with the HFS-style
 * "Macintosh HD:/Users/foo/bar.txt" prefix; Node sees POSIX paths. Strip the
 * prefix before going to disk so device code can construct paths exactly as
 * it would in Max and still hit real fixtures.
 *
 * Implements the subset the loader actually uses:
 *   - `isopen` (truthy after a successful open).
 *   - `position`, `eof` (numeric byte offsets).
 *   - `readstring(maxChars)` (returns up to N chars; advances position).
 *   - `writestring(str)` (appends in write mode; advances position).
 *   - `close()` (no-op for reads; flushes pending writes).
 */
function _stripHfsPrefix(p) {
  const s = String(p == null ? "" : p);
  if (s.indexOf("Macintosh HD:") === 0) return s.substring("Macintosh HD:".length);
  return s;
}

class MaxFile {
  constructor(p, mode, _typeCode, _creator) {
    this.filename = p;
    this._posixPath = _stripHfsPrefix(p);
    this._mode = mode || "read";
    this._isOpen = false;
    this._contents = "";
    this._writeBuf = "";
    this.position = 0;
    if (this._mode === "read") {
      try {
        this._contents = fs.readFileSync(this._posixPath, "utf-8");
        this._isOpen = true;
        this.eof = this._contents.length;
      } catch {
        this._isOpen = false;
        this.eof = 0;
      }
    } else {
      // write / append modes — the device code does
      //   new File(path, "write", "TEXT", "TEXT")
      // and then f.writestring(...). Don't read existing contents; the
      // device truncates explicitly via `f.eof = 0` before writing.
      this._isOpen = true;
      this.eof = 0;
    }
  }

  get isopen() {
    return this._isOpen;
  }

  open() {
    this._isOpen = true;
  }

  close() {
    if (this._mode !== "read" && this._isOpen) {
      try {
        fs.mkdirSync(path.dirname(this._posixPath), { recursive: true });
        fs.writeFileSync(this._posixPath, this._writeBuf, "utf-8");
      } catch {
        /* ignore — tests rarely care about disk state */
      }
    }
    this._isOpen = false;
  }

  read() {
    return this._contents;
  }

  readstring(maxChars) {
    if (!this._isOpen) return "";
    const remaining = this._contents.length - this.position;
    const n = Math.min(maxChars == null ? remaining : maxChars, remaining);
    if (n <= 0) return "";
    const chunk = this._contents.substring(this.position, this.position + n);
    this.position += n;
    return chunk;
  }

  writestring(s) {
    if (!this._isOpen) return 0;
    const str = String(s == null ? "" : s);
    this._writeBuf += str;
    this.position += str.length;
    this.eof = this.position;
    return str.length;
  }
}

// ---------------------------------------------------------------------------
// Programmable APIs
// ---------------------------------------------------------------------------

function loadLomSnapshot(jsonPath) {
  const resolved = path.resolve(jsonPath);
  const text = fs.readFileSync(resolved, "utf-8");
  loadLomSnapshotObject(JSON.parse(text));
}

function loadLomSnapshotObject(obj) {
  _lomSnapshot = _cloneDeep(obj || { live_set: { tracks: [] } });
}

function resetMaxStub() {
  _lomSnapshot = { live_set: { tracks: [] } };
  _dictRegistry = new Map();
  _outletEmissions.length = 0;
  _messnamedCalls.length = 0;
  _postLog.length = 0;
  _liveApiCalls.length = 0;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _cloneDeep(v) {
  if (v == null || typeof v !== "object") return v;
  if (Array.isArray(v)) return v.map(_cloneDeep);
  const out = {};
  for (const [k, val] of Object.entries(v)) out[k] = _cloneDeep(val);
  return out;
}

function _hashString(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

// ---------------------------------------------------------------------------
// Install globals
// ---------------------------------------------------------------------------

global.Dict = Dict;
global.LiveAPI = LiveAPI;
global.outlet = outlet;
global.messnamed = messnamed;
global.post = post;
global.arrayfromargs = arrayfromargs;
global.Folder = Folder;
// Max calls it File; alias to MaxFile internally so we don't collide with a
// future named import in test code.
global.File = MaxFile;

// Inspection / control globals.
Object.defineProperty(global, "outletEmissions", {
  get() {
    return _outletEmissions;
  },
});
Object.defineProperty(global, "messnamedCalls", {
  get() {
    return _messnamedCalls;
  },
});
Object.defineProperty(global, "postLog", {
  get() {
    return _postLog;
  },
});
Object.defineProperty(global, "liveApiCalls", {
  get() {
    return _liveApiCalls;
  },
});

global.loadLomSnapshot = loadLomSnapshot;
global.loadLomSnapshotObject = loadLomSnapshotObject;
global.resetMaxStub = resetMaxStub;

// `messagename` is Max's per-message magic variable set automatically by the
// runtime to the message that triggered the current handler. Device code
// uses it inside `arrayfromargs(messagename, arguments)` to recover a full
// argument list. Default to empty string; tests that need a specific value
// can `global.messagename = "loadCuration"` before invoking the function.
if (typeof global.messagename === "undefined") global.messagename = "";

// `include(path)` is Max's mechanism to pull other [js] files into the
// current scope. Device JS uses it for sf_arrangement_reader / loader.
// We stub it to a no-op so calls don't crash; tests that depend on those
// loaders' contents have to inject their globals separately.
if (typeof global.include === "undefined") global.include = function () { /* noop */ };

module.exports = {
  Dict,
  LiveAPI,
  outlet,
  messnamed,
  post,
  arrayfromargs,
  Folder,
  File: MaxFile,
  loadLomSnapshot,
  loadLomSnapshotObject,
  resetMaxStub,
};
