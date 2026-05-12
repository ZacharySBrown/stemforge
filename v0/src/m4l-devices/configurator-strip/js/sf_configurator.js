// sf_configurator.js
// ─────────────────────────────────────────────────────────────────────────────
// Configurator Strip — operations dispatcher (Phase 3).
//
// Lives inside the ConfiguratorStrip.amxd device. The strip has seven labelled
// buttons; each button fires a message into this script (see device.yaml for
// the verb→button mapping). The script:
//
//   1. Discovers the local HTTP server's port (Lane A writes it to
//      ~/stemforge/.configurator_port).
//   2. For "http"-kind verbs: POSTs to http://127.0.0.1:<port>/intent/<verb>.
//   3. For "jweb"-kind verb (open-editor): emits an `openurl` message that
//      the patcher routes to a [jweb] float window.
//   4. For commit specifically: walks session+arrangement view first
//      (using the same algorithm as stemforge_loader.v0.js's
//      _commitSessionTracks), then POSTs the resulting session_tracks dict.
//
// HTTP transport choice — `[js]` SpiderMonkey on macOS doesn't ship a
// XMLHttpRequest binding that's reliable in M4L, so we use the shell-via-curl
// fallback documented in `memory/m4l_device_development_guide.md` §3 (the
// [shell] external is already a project dependency for the big device).
// The JS emits curl commands out outlet 4 and the patcher pipes them through
// [shell].
//
// Outlets (matched in device.yaml):
//   0: status text   → live.comment status_text
//   1: footer text   → live.comment footer_text
//   2: dot color     → live.text status_dot   (sent as `bgcolor r g b a`)
//   3: openurl       → [jweb]                 (open the popup)
//   4: shell exec    → [shell]                (curl POST + server-start)
// ─────────────────────────────────────────────────────────────────────────────

inlets  = 1;
outlets = 5;
autowatch = 1;

// ── Configuration ────────────────────────────────────────────────────────────

// Path to the port file. We expand ~ at lookup time.
var PORT_FILE = "~/stemforge/.configurator_port";

// HTTP base + intent endpoint. Templated at runtime once we know the port.
var SERVER_HOST = "127.0.0.1";

// Console-script name fired by the "Start server" CTA.
var START_COMMAND = "stemforge-configurator";

// Cached state. Re-checked on COMMIT (in case the server restarted).
var _port      = null;
var _serverBase = null;
var _connected = false;

// Letters walked by COMMIT — matches stemforge_loader.v0.js convention.
var COMMIT_LETTERS    = ["A", "B", "C", "D"];
var COMMIT_SLOTS_PER  = 20;
var COMMIT_SESSION_MAX = 31;

// ── Status helpers ───────────────────────────────────────────────────────────

function _status(line) {
    outlet(0, line == null ? "" : String(line));
}

function _footer(line) {
    outlet(1, line == null ? "" : String(line));
}

function _setDot(rgba) {
    // rgba is a 4-element array. Emit as a Max message that [live.text]
    // bgcolor recognizes.
    outlet(2, "bgcolor", rgba[0], rgba[1], rgba[2], rgba[3]);
}

var DOT_OK    = [0.220, 0.780, 0.376, 1.0];
var DOT_WARN  = [0.957, 0.741, 0.137, 1.0];
var DOT_ERROR = [0.871, 0.275, 0.275, 1.0];

function _post(msg) {
    if (typeof post === "function") post(String(msg) + "\n");
}

// ── Port discovery ───────────────────────────────────────────────────────────

function _expandTilde(p) {
    // Max [js] File API accepts ~ directly on macOS. An earlier "defensive"
    // substitution to the literal string "$HOME" broke port discovery —
    // Max's File constructor doesn't expand shell variables, so the
    // substituted path was meaningless. Pass through as-is; the File
    // constructor handles ~ resolution.
    return p;
}

function discoverPort() {
    // Read the port file. classic [js] `File` supports this; if it doesn't
    // resolve `~`, we fall back to letting the shell-curl handle expansion.
    _setDot(DOT_WARN);
    _status("checking…");

    var port = _readPortFile(PORT_FILE);
    if (port == null) {
        _port = null;
        _serverBase = null;
        _connected = false;
        _setDot(DOT_ERROR);
        _status("server down");
        _footer("server not running — click Start Server");
        return null;
    }

    _port = port;
    _serverBase = "http://" + SERVER_HOST + ":" + port;
    _setDot(DOT_OK);
    _status("connected");
    _footer(_serverBase);
    _connected = true;
    return port;
}

function _readPortFile(p) {
    // The classic Max [js] `File` object reads file contents via .position +
    // .readstring(). It accepts ~ on macOS — but not always reliably. We
    // try File first, then defer to a shell read if that fails.
    try {
        var f = new File(_expandTilde(p), "read");
        if (f && f.isopen) {
            f.position = 0;
            var raw = f.readstring(64);
            f.close();
            if (raw == null) return null;
            var s = String(raw).replace(/\s+/g, "");
            if (!s.length) return null;
            var n = parseInt(s, 10);
            if (!isFinite(n) || n <= 0) return null;
            return n;
        }
    } catch (e) {
        _post("[sf_configurator] File read failed for " + p + ": " + e);
    }
    return null;
}

// ── HTTP via shell + curl (see header doc for why) ───────────────────────────

function _shellQuote(s) {
    // Single-quote shell wrap; escape embedded single quotes.
    if (s == null) return "''";
    return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

function _postIntent(verb, bodyObj) {
    if (!_serverBase) {
        if (discoverPort() == null) {
            _footer("post " + verb + ": server down");
            return false;
        }
    }
    var url = _serverBase + "/intent/" + verb;
    var bodyJson = "{}";
    try {
        if (bodyObj && typeof bodyObj === "object") {
            bodyJson = JSON.stringify(bodyObj);
        }
    } catch (e) {
        _post("[sf_configurator] JSON.stringify failed: " + e);
        bodyJson = "{}";
    }

    // curl -X POST -H 'Content-Type: application/json' -d '<body>' <url>
    // Use --silent + --max-time so we don't hang the patcher.
    var cmd = "curl --silent --max-time 5 " +
              "-H 'Content-Type: application/json' " +
              "-X POST " +
              "-d " + _shellQuote(bodyJson) + " " +
              _shellQuote(url);

    outlet(4, "exec", cmd);
    _footer("→ " + verb);
    return true;
}

// ── Public message handlers (one per button) ─────────────────────────────────

function loadbang() {
    discoverPort();
}

function bang() {
    // Re-discover port (status indicator clicked or external bang).
    discoverPort();
}

function ping() {
    discoverPort();
}

// btn_load — POST /intent/load-manifest
function loadManifest(path) {
    var body = path ? { manifest_path: String(path) } : {};
    if (_postIntent("load-manifest", body)) {
        _status("load-manifest sent");
    }
}

// btn_slice — POST /intent/slice
function slice() {
    if (_postIntent("slice", {})) _status("slice sent");
}

// btn_recompute — POST /intent/recompute
function recompute() {
    if (_postIntent("recompute", {})) _status("recompute sent");
}

// btn_reanchor — POST /intent/re-anchor
function reAnchor() {
    if (_postIntent("re-anchor", {})) _status("re-anchor sent");
}
// Alias matching device.yaml verb (hyphen → camel handled in the patcher).
function reanchor() { reAnchor(); }

// btn_curate — POST /intent/curate
function curate() {
    if (_postIntent("curate", {})) _status("curate sent");
}

// btn_export — POST /intent/export
function exportPpak(outPath) {
    var body = { target: "ep133" };
    if (outPath != null) body.out_path = String(outPath);
    if (_postIntent("export", body)) _status("export sent");
}
function exportTarget(target, outPath) {
    var body = { target: String(target || "ep133") };
    if (outPath != null) body.out_path = String(outPath);
    if (_postIntent("export", body)) _status("export → " + body.target);
}

// btn_open_editor — open popup via [jweb]
function openEditor() {
    // Re-check port in case the server has restarted since boot.
    if (!_serverBase) discoverPort();
    if (!_serverBase) {
        _footer("open-editor: server down");
        return;
    }
    outlet(3, "openurl", _serverBase + "/");
    _status("editor opened");
    _footer("editor → " + _serverBase + "/");
}

// "Start server" CTA fired when port-file is missing.
function startServer() {
    outlet(4, "exec", START_COMMAND + " &");
    _status("starting…");
    _footer("starting " + START_COMMAND);
}

// ── COMMIT — walk session+arrangement view, POST result ──────────────────────
//
// Mirrors the algorithm in stemforge_loader.v0.js's `_commitSessionTracks`.
// We duplicate the walker here for Phase 3 to keep the strip independent of
// the big device's JS bundle. TODO: factor a shared walker into
// v0/src/m4l-js/sf_commit_walker.js (or similar) and have both devices load
// it; tracking issue to follow this PR.

function _findTrackByName(name) {
    try {
        var ls = new LiveAPI("live_set");
        var cnt = ls.getcount("tracks");
        for (var i = 0; i < cnt; i++) {
            var t = new LiveAPI("live_set tracks " + i);
            var got = t.get("name");
            var s = Array.isArray(got) ? got[0] : got;
            if (String(s) === String(name)) return i;
        }
    } catch (e) {
        _post("[sf_configurator] findTrackByName error: " + e);
    }
    return -1;
}

function _getProp(api, prop) {
    try {
        var v = api.get(prop);
        if (Array.isArray(v) && v.length === 1) return v[0];
        return v;
    } catch (_) { return null; }
}

function _stripHfs(p) {
    if (p == null) return "";
    var s = String(p);
    if (s.indexOf("Macintosh HD:") === 0) s = s.substring("Macintosh HD:".length);
    return s;
}

function _entryFromClip(clipApi, slot, beatToSec) {
    var fpRaw = _getProp(clipApi, "file_path");
    if (fpRaw == null || fpRaw === "") return null;
    var file = _stripHfs(fpRaw);
    var startMarker = Number(_getProp(clipApi, "start_marker")) || 0;
    var endMarker   = Number(_getProp(clipApi, "end_marker"))   || 0;
    var lengthBeats = Number(_getProp(clipApi, "length"))       || 0;
    var warping     = Number(_getProp(clipApi, "warping"))      || 0;
    var startSec, endSec, lengthSec;
    if (warping) {
        startSec  = startMarker * beatToSec;
        endSec    = endMarker   * beatToSec;
        lengthSec = lengthBeats * beatToSec;
    } else {
        startSec  = startMarker;
        endSec    = endMarker;
        lengthSec = lengthBeats;
    }
    var mode = (Math.abs(endSec - lengthSec) < 0.010) ? "rotate" : "trim";
    return {
        file:        file,
        slot:        slot,
        start_sec:   startSec,
        end_sec:     endSec,
        length_sec:  lengthSec,
        warping:     warping ? 1 : 0,
        mode:        mode,
    };
}

function _walkSessionAndArrangement() {
    // Returns { A: [...], B: [...], C: [...], D: [...] } per the same
    // contract as the big device's _commitSessionTracks. BPM falls back to
    // 120 if the LiveAPI isn't seeded.
    var bpm = 120.0;
    try {
        var lsApi = new LiveAPI("live_set");
        var t = Number(_getProp(lsApi, "tempo"));
        if (t > 0) bpm = t;
    } catch (_) {}
    var beatToSec = 60.0 / bpm;
    var result = { A: [], B: [], C: [], D: [] };

    for (var li = 0; li < COMMIT_LETTERS.length; li++) {
        var letter = COMMIT_LETTERS[li];
        var ti = _findTrackByName(letter);
        if (ti < 0) continue;
        var seen = {};
        var used = {};
        var entries = [];

        // Session view — slot = clip_slot index (preserve historical layout).
        for (var sj = 0; sj < COMMIT_SESSION_MAX; sj++) {
            var clipApi;
            try { clipApi = new LiveAPI("live_set tracks " + ti + " clip_slots " + sj + " clip"); }
            catch (_) { continue; }
            if (!clipApi || clipApi.id === "0") continue;
            var entry = _entryFromClip(clipApi, sj, beatToSec);
            if (!entry) continue;
            if (seen.hasOwnProperty(entry.file)) continue;
            entries.push(entry);
            seen[entry.file] = entry.slot;
            used[entry.slot] = true;
        }

        // Arrangement view — claim next free slot in 0..19.
        var trackApi;
        try { trackApi = new LiveAPI("live_set tracks " + ti); } catch (_) { trackApi = null; }
        var arrCount = 0;
        if (trackApi) {
            try { arrCount = trackApi.getcount("arrangement_clips") | 0; } catch (_) {}
        }
        for (var ai = 0; ai < arrCount; ai++) {
            var aClip;
            try { aClip = new LiveAPI("live_set tracks " + ti + " arrangement_clips " + ai); }
            catch (_) { continue; }
            if (!aClip || aClip.id === "0") continue;
            var afpRaw = _getProp(aClip, "file_path");
            if (!afpRaw) continue;
            var afp = _stripHfs(afpRaw);
            if (seen.hasOwnProperty(afp)) continue;
            var nextSlot = -1;
            for (var s = 0; s < COMMIT_SLOTS_PER; s++) {
                if (!used[s]) { nextSlot = s; break; }
            }
            if (nextSlot < 0) continue;
            var aEntry = _entryFromClip(aClip, nextSlot, beatToSec);
            if (!aEntry) continue;
            entries.push(aEntry);
            seen[aEntry.file] = aEntry.slot;
            used[aEntry.slot] = true;
        }

        result[letter] = entries;
    }
    return result;
}

// btn_commit — walk views, POST /intent/commit
function commit() {
    // Re-check port — server may have restarted since boot.
    discoverPort();
    var session_tracks;
    try {
        session_tracks = _walkSessionAndArrangement();
    } catch (e) {
        _post("[sf_configurator] commit walker failed: " + e);
        _footer("commit walker failed: " + e);
        return;
    }
    var summary = COMMIT_LETTERS.map(function (l) {
        return l + "=" + (session_tracks[l] ? session_tracks[l].length : 0);
    }).join(" ");
    _status("commit: " + summary);
    _postIntent("commit", { session_tracks: session_tracks });
}

// Expose the walker for unit tests (sandbox can reach it via the global).
this._walkSessionAndArrangement = _walkSessionAndArrangement;
this._entryFromClip             = _entryFromClip;
this._postIntent                = _postIntent;
this._discoverPort              = discoverPort;
