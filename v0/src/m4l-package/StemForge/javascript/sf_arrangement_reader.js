// sf_arrangement_reader.js
// ─────────────────────────────────────────────────────────────────────────────
// Track B of the EP-133 song-mode export pipeline.
//
// Reads Ableton Live's arrangement view via LOM and writes a JSON snapshot
// describing tempo, time signature, locator placements, and per-track A/B/C/D
// arrangement clips. The Python `stemforge export-song` CLI consumes this
// snapshot together with the Session-view manifest (stems.json) to author a
// .ppak project for the EP-133.
//
// Public entry point (called from stemforge_loader.v0.js via classic [js]
// include(); intentionally NOT named the same as the loader's Max-facing
// handler to avoid clobbering the wrapper after include() rebinds globals):
//
//     runArrangementExport(outputPath: string) -> bool
//
// Output shape (snapshot.json):
//
//     {
//       "tempo": 120.0,
//       "time_sig": [4, 4],
//       "arrangement_length_sec": 64.0,
//       "locators": [
//         {"time_sec": 0.0, "name": "Verse"},
//         {"time_sec": 16.0, "name": "Chorus"}
//       ],
//       "tracks": {
//         "A": [
//           {"file_path": "/abs/path.wav", "start_time_sec": 0.0,
//            "length_sec": 4.0, "warping": 1}
//         ],
//         "B": [], "C": [...], "D": [...]
//       }
//     }
//
// Conventions adopted from v0/src/m4l-js/stemforge_loader.v0.js:
//   - Top-level functions are auto-exposed to Max's classic [js] object.
//   - LOM scalar properties come back as 1-element arrays; unwrap via the
//     _getLomNumber / _getLomString helpers (mirrored here to keep this
//     module self-contained and testable in isolation).
//   - File paths from LOM start with "Macintosh HD:" — strip via _stripHfsPrefix.
//   - Beats → seconds: `seconds = beats * 60 / tempo`.
// ─────────────────────────────────────────────────────────────────────────────

/* global LiveAPI, File, Folder, post, outlet, max */

// ── Logging (mirrors loader's _sfFileLog so failures land in the same log) ──

function _arrFileLog(msg) {
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
        var line = "[" + ts + "] [sf_arrangement_reader] " + String(msg) + "\n";
        var f = new File(maxPath, "write", "TEXT", "TEXT");
        if (!f.isopen) return;
        try { f.position = f.eof; } catch (_) {}
        f.writestring(line);
        try { f.eof = f.position; } catch (_) {}
        f.close();
    } catch (_) {}
}

function _arrStatus(msg) {
    try { post("[sf_arrangement_reader] " + String(msg) + "\n"); } catch (_) {}
    _arrFileLog(msg);
}

// ── LOM helpers (intentional duplicates of loader helpers — keeps this
// module loadable without sourcing the 1900-line loader) ───────────────────

function _arrHomeDir() {
    // Mirror _arrFileLog: try max.getsystemvariable("HOME") first, fall back
    // to File.getenv("HOME"), then a hardcoded /Users/zak. Returns POSIX, no
    // trailing slash.
    var h = "";
    try {
        if (typeof max !== "undefined" && max && typeof max.getsystemvariable === "function") {
            h = String(max.getsystemvariable("HOME") || "");
        }
    } catch (_) {}
    if (!h) {
        try {
            if (typeof File !== "undefined" && typeof File.getenv === "function") {
                h = String(File.getenv("HOME") || "");
            }
        } catch (_) {}
    }
    if (!h) h = "/Users/zak";
    if (h.charAt(h.length - 1) === "/") h = h.substring(0, h.length - 1);
    return h;
}

function _arrToMaxPath(p) {
    var s = String(p);
    // Expand ~ and ~/foo so the patcher's [exportArrangementSnapshot ~/Desktop/...]
    // message stays portable across users without baking absolute paths into
    // the .amxd.
    if (s === "~") {
        s = _arrHomeDir();
    } else if (s.length >= 2 && s.charAt(0) === "~" && s.charAt(1) === "/") {
        s = _arrHomeDir() + s.substring(1);
    }
    if (s.length > 0 && s.charAt(0) === "/") return "Macintosh HD:" + s;
    return s;
}

function _arrStripHfsPrefix(s) {
    if (!s) return "";
    var str = String(s);
    if (str.indexOf("Macintosh HD:") === 0) {
        return str.substring("Macintosh HD:".length);
    }
    return str;
}

function _arrGetLomNumber(api, prop) {
    try {
        var v = api.get(prop);
        if (v && typeof v === "object") return Number(v[0]);
        return Number(v);
    } catch (_) {
        return NaN;
    }
}

function _arrGetLomString(api, prop) {
    try {
        var v = api.get(prop);
        if (v && typeof v === "object") return String(v[0]);
        return String(v);
    } catch (_) {
        return "";
    }
}

function _arrTrackCount() {
    return new LiveAPI("live_set").getcount("tracks");
}

function _arrTrackName(i) {
    var raw = new LiveAPI("live_set tracks " + i).get("name");
    return (raw && typeof raw === "object") ? String(raw[0]) : String(raw);
}

function _arrFindTrackByName(name) {
    var n = _arrTrackCount();
    for (var i = 0; i < n; i++) {
        if (_arrTrackName(i) === name) return i;
    }
    return -1;
}

// ── Snapshot builder ────────────────────────────────────────────────────────

function _arrReadLocators(beatToSec) {
    // live_set has a `cue_points` collection. Each cue_point has `name` and
    // `time` (in beats). Returns locators sorted by time_sec ascending.
    var liveSet = new LiveAPI("live_set");
    var count = 0;
    try { count = liveSet.getcount("cue_points") | 0; }
    catch (_) { count = 0; }
    var out = [];
    for (var i = 0; i < count; i++) {
        var cp;
        try { cp = new LiveAPI("live_set cue_points " + i); }
        catch (_) { continue; }
        if (!cp || cp.id === "0") continue;
        var name = _arrGetLomString(cp, "name");
        var beats = _arrGetLomNumber(cp, "time");
        if (!isFinite(beats)) continue;
        out.push({
            time_sec: beats * beatToSec,
            name: String(name || "")
        });
    }
    out.sort(function (a, b) { return a.time_sec - b.time_sec; });
    return out;
}

function _arrReadTrackClips(letter, beatToSec) {
    // Returns the array of clip dicts for the named track, or [] if the track
    // doesn't exist or has no arrangement clips. Never throws.
    var trackIdx = _arrFindTrackByName(letter);
    if (trackIdx < 0) return [];

    var trackApi = new LiveAPI("live_set tracks " + trackIdx);
    var count = 0;
    try { count = trackApi.getcount("arrangement_clips") | 0; }
    catch (_) { count = 0; }

    var clips = [];
    for (var i = 0; i < count; i++) {
        var clip;
        try {
            clip = new LiveAPI(
                "live_set tracks " + trackIdx + " arrangement_clips " + i
            );
        } catch (_) { continue; }
        if (!clip || clip.id === "0") continue;

        var fp = _arrGetLomString(clip, "file_path");
        var startBeats = _arrGetLomNumber(clip, "start_time");
        var lengthBeats = _arrGetLomNumber(clip, "length");
        var warping = _arrGetLomNumber(clip, "warping");

        // Skip MIDI / empty clips — file_path will be missing or empty.
        if (!fp) continue;

        clips.push({
            file_path: _arrStripHfsPrefix(fp),
            start_time_sec: isFinite(startBeats) ? startBeats * beatToSec : 0.0,
            length_sec: isFinite(lengthBeats) ? lengthBeats * beatToSec : 0.0,
            warping: (isFinite(warping) ? warping : 0) | 0
        });
    }
    // Stable order: by start time, then file_path.
    clips.sort(function (a, b) {
        if (a.start_time_sec !== b.start_time_sec) {
            return a.start_time_sec - b.start_time_sec;
        }
        if (a.file_path < b.file_path) return -1;
        if (a.file_path > b.file_path) return 1;
        return 0;
    });
    return clips;
}

function _arrComputeArrangementLengthSec(snapshot) {
    // Live exposes `live_set last_event_time` (beats) but not all hosts honor
    // it consistently. Compute from the snapshot itself: max(clip end across
    // all tracks, last locator time, 0). The Python side uses this to bound
    // the final scene's duration.
    var maxEnd = 0.0;
    var letters = ["A", "B", "C", "D"];
    for (var li = 0; li < letters.length; li++) {
        var clips = snapshot.tracks[letters[li]];
        for (var ci = 0; ci < clips.length; ci++) {
            var end = clips[ci].start_time_sec + clips[ci].length_sec;
            if (end > maxEnd) maxEnd = end;
        }
    }
    for (var li2 = 0; li2 < snapshot.locators.length; li2++) {
        if (snapshot.locators[li2].time_sec > maxEnd) {
            maxEnd = snapshot.locators[li2].time_sec;
        }
    }
    return maxEnd;
}

function buildArrangementSnapshot() {
    // Pure builder — returns the snapshot dict. No I/O. Exposed for tests.
    var liveSet = new LiveAPI("live_set");
    var tempoRaw = _arrGetLomNumber(liveSet, "tempo");
    var tempo = isFinite(tempoRaw) && tempoRaw > 0 ? tempoRaw : 120.0;

    var sigNumRaw = _arrGetLomNumber(liveSet, "signature_numerator");
    var sigDenRaw = _arrGetLomNumber(liveSet, "signature_denominator");
    var sigNum = isFinite(sigNumRaw) && sigNumRaw > 0 ? (sigNumRaw | 0) : 4;
    var sigDen = isFinite(sigDenRaw) && sigDenRaw > 0 ? (sigDenRaw | 0) : 4;

    var beatToSec = 60.0 / tempo;

    var locators = _arrReadLocators(beatToSec);
    var tracks = {
        A: _arrReadTrackClips("A", beatToSec),
        B: _arrReadTrackClips("B", beatToSec),
        C: _arrReadTrackClips("C", beatToSec),
        D: _arrReadTrackClips("D", beatToSec)
    };

    var snapshot = {
        tempo: tempo,
        time_sig: [sigNum, sigDen],
        arrangement_length_sec: 0.0,
        locators: locators,
        tracks: tracks
    };
    snapshot.arrangement_length_sec = _arrComputeArrangementLengthSec(snapshot);
    return snapshot;
}

function _arrWriteJson(outputPath, snapshot) {
    // Mirrors writeFileContents() in stemforge_loader.v0.js — chunked writes
    // to dodge Max File.writestring's 32767-char cap. Snapshots are small
    // (<10KB typically) so a single write almost always suffices, but we
    // keep the loop for safety.
    var contents;
    try { contents = JSON.stringify(snapshot, null, 2); }
    catch (e) {
        _arrStatus("snapshot stringify error: " + e);
        return false;
    }
    try {
        var maxPath = _arrToMaxPath(outputPath);
        var f = new File(maxPath, "write", "TEXT", "TEXT");
        if (!f.isopen) {
            _arrStatus("write: could not open " + outputPath);
            return false;
        }
        try { f.position = 0; } catch (_) {}
        try { f.eof = 0; } catch (_) {}

        var MAX_CHUNK = 32767;
        var written = 0;
        var prev = -1;
        while (written < contents.length && f.position !== prev) {
            prev = f.position;
            var end = written + MAX_CHUNK;
            if (end > contents.length) end = contents.length;
            f.writestring(contents.substring(written, end));
            written = end;
        }
        try { f.eof = f.position; } catch (_) {}
        f.close();
        if (written < contents.length) {
            _arrStatus("write: short write " + written + "/" + contents.length
                + " bytes to " + outputPath);
            return false;
        }
        return true;
    } catch (e2) {
        _arrStatus("write error: " + e2);
        return false;
    }
}

function runArrangementExport(outputPath) {
    // Public entry point. Builds the snapshot from current LOM state and
    // writes it to outputPath as JSON. Returns true on success, false on
    // failure. Named to avoid clobbering stemforge_loader.v0.js's
    // `exportArrangementSnapshot` Max-facing wrapper after include().
    if (!outputPath || String(outputPath).length === 0) {
        _arrStatus("runArrangementExport: missing outputPath");
        return false;
    }
    var path = String(outputPath);
    var snapshot;
    try { snapshot = buildArrangementSnapshot(); }
    catch (e) {
        _arrStatus("buildArrangementSnapshot threw: " + e);
        return false;
    }
    var ok = _arrWriteJson(path, snapshot);
    if (ok) {
        var letters = ["A", "B", "C", "D"];
        var summary = letters.map(function (l) {
            return l + "=" + snapshot.tracks[l].length;
        }).join(" ");
        _arrStatus("snapshot written: " + path + " | locators="
            + snapshot.locators.length + " | clips: " + summary);
    }
    return ok;
}

// ── CommonJS shim — mirrors the loader's test export so the Node-vm sandbox
// in tests/js_mocks/ can drive these functions directly. Max's classic [js]
// ignores `module` so this is a no-op at runtime in the device. ───────────

if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        buildArrangementSnapshot: buildArrangementSnapshot,
        runArrangementExport: runArrangementExport,
        _stripHfsPrefix: _arrStripHfsPrefix,
        _findTrackByName: _arrFindTrackByName
    };
}
