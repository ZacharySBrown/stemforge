// stemforge_loader.v0.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] object (NOT node.script). This file runs inside Max and
// has access to LiveAPI, File, Folder, post() etc. — Node-for-Max does not.
//
// Messages accepted from the bridge (via patchlines in StemForge.amxd):
//   setBpm <bpm:float>           — set song tempo from NDJSON bpm event
//   loadManifest <path:symbol>   — fired on NDJSON complete event
//
// Behavior of loadManifest:
//   1. Read stems.json via File API.
//   2. Set master tempo.
//   3. For each stem: find a matching template track (stem_target in
//      tracks.yaml — we use the same heuristics as the legacy loader).
//      - If match: duplicate the track, rename with the source track name,
//        load the WAV into clip slot 0.
//      - If the stem has a beats_dir + target is drums: duplicate the
//        Simpler template and load *every* *_beats/*.wav into polybuffer~.
//      - Else: duplicate the fallback generic audio template.
//
// Kept intentionally compatible with v0 manifests (stems.json) emitted by
// stemforge-native. Schema fields consumed:
//   manifest.bpm, manifest.track_name, manifest.stems[].name,
//   manifest.stems[].wav_path, manifest.stems[].beats_dir (optional).
// ─────────────────────────────────────────────────────────────────────────────

/* global Max, outlet, post, LiveAPI, File, Folder, Task, messagename, arrayfromargs, max */

autowatch = 1;
inlets = 1;
outlets = 3;   // 0: status text, 1: bang on completion, 2: preset umenu control

var STEM_TARGETS = {
    // From v0/interfaces/tracks.yaml — mirrored in JS because the template
    // tracks are the user-installed ones; we need to recognise them in the
    // Live set. Keys are stem names produced by stemforge-native.
    drums:  { track: "SF | Drums Raw",         color: 0xFF4444 },
    bass:   { track: "SF | Bass",              color: 0x4477FF },
    vocals: { track: "SF | Vocals",            color: 0xFFAA44 },
    other:  { track: "SF | Texture Verb",      color: 0x44DD77 },
    guitar: { track: null,                     color: 0x888888 },  // fallback
    piano:  { track: null,                     color: 0x888888 }
};

var SIMPLER_TEMPLATE = "SF | Beat Chop Simpler";
var FALLBACK_TEMPLATE = null;   // null triggers `generic audio track` path

// Inline file-log helper (see sf_logger.js). Keeps the loader self-contained
// so a broken require() never takes track creation down.
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

function status(msg) {
    try { outlet(0, "set", String(msg)); } catch (_) {}
    try { post(String(msg) + "\n"); } catch (_) {}
    _sfFileLog("sf_loader", msg);
}

function toMaxPath(p) {
    var s = String(p);
    if (s.length > 0 && s.charAt(0) === "/") return "Macintosh HD:" + s;
    return s;
}

function readFileContents(p) {
    try {
        var f = new File(toMaxPath(p), "read");
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
        status("readFile error: " + e);
        return null;
    }
}

function writeFileContents(p, contents) {
    // Overwrites the file at `p` with `contents`. Truncates before writing.
    // Modeled on _sfFileLog's file-write pattern — used by commitOffsets to
    // persist manifest changes back to disk.
    //
    // CRITICAL: Max File.writestring caps at 32767 chars per call (signed-short,
    // same as readstring). Writing an 84K manifest in one call silently
    // truncates to exactly 32767 bytes. Loop with safe chunks.
    try {
        var maxPath = toMaxPath(p);
        var f = new File(maxPath, "write", "TEXT", "TEXT");
        if (!f.isopen) {
            status("writeFile error: could not open " + p);
            return false;
        }
        try { f.position = 0; } catch (_) {}
        try { f.eof = 0; } catch (_) {}

        var MAX_CHUNK = 32767;
        var total = String(contents);
        var written = 0;
        var prev = -1;
        while (written < total.length && f.position !== prev) {
            prev = f.position;
            var end = written + MAX_CHUNK;
            if (end > total.length) end = total.length;
            f.writestring(total.substring(written, end));
            written = end;
        }
        try { f.eof = f.position; } catch (_) {}
        f.close();
        if (written < total.length) {
            status("writeFile: short write " + written + "/" + total.length
                + " bytes to " + p);
            return false;
        }
        return true;
    } catch (e) {
        status("writeFile error: " + e);
        return false;
    }
}

// Max named dicts have an asymmetric API: `parse(jsonStr)` stores jsonStr's
// content at the dict root (no auto-wrap), but `stringify()` emits
// `{"root": <content>}` on read. So every read needs to unwrap `.root`
// and every write should NOT re-wrap (passing a {root:...} string to
// parse() produces `.root.root` nesting on the next read).
// root may also be a stringified blob in some older dicts; handle defensively.
function _unwrapDictContent(parsed) {
    if (parsed && parsed.root !== undefined) {
        if (typeof parsed.root === "object") return parsed.root;
        if (typeof parsed.root === "string") {
            try { return JSON.parse(parsed.root); } catch (_) {}
        }
    }
    return parsed;
}

function trackCount() {
    return new LiveAPI("live_set").getcount("tracks");
}

function trackName(i) {
    var raw = new LiveAPI("live_set tracks " + i).get("name");
    return (raw && typeof raw === "object") ? String(raw[0]) : String(raw);
}

function findTrackByName(name) {
    var n = trackCount();
    for (var i = 0; i < n; i++) {
        if (trackName(i) === name) return i;
    }
    return -1;
}

function findTrackBySuffix(stem) {
    // Match any existing track whose name ends with or contains the stem
    // name. This picks up both template tracks ("SF | Drums Raw") and
    // user-renamed duplicates ("Song | drums").
    var target = String(stem).toLowerCase();
    var n = trackCount();
    for (var i = 0; i < n; i++) {
        var lower = trackName(i).toLowerCase();
        if (lower.indexOf(target) >= 0) return i;
    }
    return -1;
}

function duplicateTrack(srcIdx) {
    new LiveAPI("live_set").call("duplicate_track", srcIdx);
    return srcIdx + 1;   // Live inserts the clone immediately after.
}

function renameTrack(idx, name, color) {
    var api = new LiveAPI("live_set tracks " + idx);
    api.set("name", String(name));
    if (color !== undefined && color !== null) {
        try { api.set("color", color); } catch (_) {}
    }
}

function loadClip(trackIdx, slotIdx, wavPath, clipName, startMarkerBeats) {
    var csPath = "live_set tracks " + trackIdx + " clip_slots " + slotIdx;
    var cs = new LiveAPI(csPath);
    try {
        cs.call("create_audio_clip", String(wavPath));
    } catch (e) {
        status("create_audio_clip failed: " + e);
        return false;
    }
    try {
        var clip = new LiveAPI(csPath + " clip");
        if (clip.id !== "0" && clipName) {
            clip.set("name", String(clipName));
            clip.set("warping", 1);
            clip.set("looping", 1);
            // Note: start_marker adjustment removed — shifting clip start
            // breaks sync. Instead, the curator now boosts bars with early
            // transients during selection (prefer bars that start with a hit).
        }
    } catch (_) {}
    return true;
}

// Apply Curation v2 clip/warp-marker/offset data to an already-loaded clip.
// Feature-detects the v2 schema by checking loopEntry.clip.padded_start_sec.
// Returns true if v2 data was applied, false if the entry is legacy (caller
// should fall back to its existing warp_mode behavior). See spec sections
// 4 (warp marker types), 6 (offset flow), 9 (export formula), 10 (M4L app).
//
// `stemName` (optional) selects warp_mode from BAR_WARP_MODES. Drums/bass
// default to 0 (Beats) — far cleaner stretching of transient-heavy bar-
// aligned material than the generic 4 (Complex). Vocals/other stay at 4.
function applyCurationV2Clip(clipApi, loopEntry, stemName) {
    if (!loopEntry || !loopEntry.clip) return false;
    var clipBlock = loopEntry.clip;
    if (clipBlock.padded_start_sec === undefined) return false;
    if (!clipApi || clipApi.id === "0") return false;

    var offsets = loopEntry.offsets || {};
    var startOffset = Number(offsets.start_offset_sec) || 0.0;
    var endOffset = Number(offsets.end_offset_sec) || 0.0;

    // Default start/end = musical bar boundaries (raw_*), not padded_*.
    // Padding exists so the user can trim backward into it by committing a
    // negative start_offset (reveal an early transient they want back), or
    // forward past the bar end by committing a positive end_offset.
    // Playback on first trigger should start at the musical content.
    //
    // CRITICAL: when `warping` is on, Ableton interprets start_marker,
    // end_marker, loop_start, loop_end as BEATS (not seconds). Convert
    // using the slope implied by our intended warp markers — this is the
    // same slope we encode via move_warp_marker / add_warp_marker below,
    // so the bar boundaries and loop region stay aligned with the
    // musical content in beat-time.
    var rawStart = Number(clipBlock.raw_start_sec) || 0.0;
    var rawEnd = Number(clipBlock.raw_end_sec) || 0.0;
    var secToBeat = 1.0;
    if (loopEntry.warp_markers && loopEntry.warp_markers.length >= 2) {
        var wmFirst = loopEntry.warp_markers[0];
        var wmLast = loopEntry.warp_markers[loopEntry.warp_markers.length - 1];
        var ds = Number(wmLast.time_sec) - Number(wmFirst.time_sec);
        var db = Number(wmLast.beat_pos) - Number(wmFirst.beat_pos);
        if (isFinite(ds) && isFinite(db) && ds > 0) {
            secToBeat = db / ds;
        }
    }
    var startMarker = (rawStart + startOffset) * secToBeat;
    var endMarker = (rawEnd + endOffset) * secToBeat;

    // Set clip boundaries (spec §9)
    try { clipApi.set("start_marker", startMarker); } catch (e) {
        status("      start_marker set failed: " + e);
    }
    try { clipApi.set("end_marker", endMarker); } catch (e) {
        status("      end_marker set failed: " + e);
    }

    // Loop block (spec §5). Also in beats for warped clips.
    var loopBlock = loopEntry.loop;
    if (loopBlock && loopBlock.enabled) {
        var ls = Number(loopBlock.loop_start_sec);
        var le = Number(loopBlock.loop_end_sec);
        if (isFinite(ls)) {
            try { clipApi.set("loop_start", ls * secToBeat); } catch (_) {}
        }
        if (isFinite(le)) {
            try { clipApi.set("loop_end", le * secToBeat); } catch (_) {}
        }
        try { clipApi.set("looping", 1); } catch (_) {}
    }

    // Per-stem warp mode from BAR_WARP_MODES (drums/bass = 0 Beats,
    // vocals/other = 4 Complex). Falls back to 4 if stem is unknown.
    var wmode = 4;
    if (stemName && BAR_WARP_MODES[stemName] !== undefined) {
        wmode = BAR_WARP_MODES[stemName];
    }
    try { clipApi.set("warp_mode", wmode); } catch (_) {}

    // Warp markers — Live 12 LOM (hard-won findings):
    //   - `create_warp_marker` / `clear_all_warp_markers` are GHOST methods:
    //     LiveAPI.call returns truthy for unknown names, so these appeared
    //     to succeed but did nothing.
    //   - `add_warp_marker` takes a Dict `{beat_time, sample_time}` — NOT
    //     two floats, NOT flat key/value args. It also SILENTLY REJECTS
    //     any attempt to add at a sample_time already occupied by a marker.
    //   - `remove_warp_marker(beat_time)` takes a float beat_time, not an
    //     index. Often rejects the shadow (last) marker.
    //   - `move_warp_marker(beat_time, beat_delta)` shifts an existing
    //     marker's beat_time by delta. Identify by CURRENT beat_time.
    //   - `get("warp_markers")` returns a ONE-element array whose element
    //     is a JSON string: `["{\"warp_markers\":[...]}"]`.
    //
    // Strategy: for each target anchor, match an existing marker by
    // sample_time and MOVE its beat_time; add_warp_marker only if no
    // marker exists at that sample. The shadow marker auto-repositions
    // when we move the last visible marker.
    var wmList = loopEntry.warp_markers;
    if (wmList && wmList.length) {
        var existing = [];
        try {
            var rawVal = clipApi.get("warp_markers");
            if (rawVal && rawVal.length > 0) {
                var rawStr = (typeof rawVal[0] === "string") ? rawVal[0] : String(rawVal[0]);
                var parsed = JSON.parse(rawStr);
                if (parsed && parsed.warp_markers && parsed.warp_markers.length) {
                    existing = parsed.warp_markers;
                }
            }
        } catch (_) {}

        var moved = 0, addedNew = 0, noop = 0, failed = 0;
        for (var wi = 0; wi < wmList.length; wi++) {
            var wm = wmList[wi];
            if (!wm) continue;
            var targetTime = Number(wm.time_sec);
            var targetBeat = Number(wm.beat_pos);
            if (!isFinite(targetTime) || !isFinite(targetBeat)) continue;

            var match = null;
            for (var ei = 0; ei < existing.length; ei++) {
                if (Math.abs(existing[ei].sample_time - targetTime) < 0.001) {
                    match = existing[ei];
                    break;
                }
            }

            if (match) {
                var delta = targetBeat - match.beat_time;
                if (Math.abs(delta) < 0.0001) {
                    noop++;
                } else {
                    try {
                        clipApi.call("move_warp_marker", match.beat_time, delta);
                        moved++;
                    } catch (eMv) {
                        status("      move_warp_marker(" + match.beat_time.toFixed(4)
                            + ", " + delta.toFixed(4) + ") failed: " + eMv);
                        failed++;
                    }
                }
            } else {
                try {
                    var scratch = new Dict();
                    scratch.set("beat_time", targetBeat);
                    scratch.set("sample_time", targetTime);
                    clipApi.call("add_warp_marker", scratch);
                    addedNew++;
                } catch (eAdd) {
                    status("      add_warp_marker(beat=" + targetBeat.toFixed(3)
                        + ", sample=" + targetTime.toFixed(3) + ") failed: " + eAdd);
                    failed++;
                }
            }
        }
        status("      warp_markers: " + moved + " moved, " + addedNew + " added, "
            + noop + " no-op, " + failed + " failed");
    }

    return true;
}

function setBpm() {
    var bpm = Number(arguments[0]);
    if (!bpm || !isFinite(bpm)) { status("setBpm: invalid"); return; }
    try {
        new LiveAPI("live_set").set("tempo", bpm);
        status("tempo → " + bpm + " BPM");
    } catch (e) {
        status("setBpm error: " + e);
    }
}

function loadManifest() {
    var manifestPath = arrayfromargs(messagename, arguments).slice(1).join(" ");
    if (!manifestPath) { status("loadManifest: missing path"); return; }

    var raw = readFileContents(manifestPath);
    if (!raw) { status("cannot read manifest: " + manifestPath); return; }
    var mf;
    try { mf = JSON.parse(raw); }
    catch (e) { status("manifest JSON parse: " + e); return; }

    if (mf.bpm) {
        try { new LiveAPI("live_set").set("tempo", Number(mf.bpm)); } catch (_) {}
    }

    if (!mf.stems || !mf.stems.length) { status("manifest has no stems"); return; }

    var loaded = 0;
    for (var i = 0; i < mf.stems.length; i++) {
        var s = mf.stems[i];
        if (!s || !s.name) continue;
        if (s.name === "residual") continue;

        // Decide source template to duplicate from.
        var cfg = STEM_TARGETS[s.name];
        var templateName = cfg && cfg.track ? cfg.track : null;
        var templateIdx = templateName ? findTrackByName(templateName) : -1;

        if (templateIdx < 0) {
            // No template for this stem. Try to at least find a matching
            // existing track by suffix (user's custom template) or create a
            // fresh audio track at the end of the set.
            templateIdx = findTrackBySuffix(s.name);
        }
        if (templateIdx < 0) {
            status("  " + s.name + ": no target track — dragging required");
            continue;
        }

        var newIdx = duplicateTrack(templateIdx);
        var clipName = (mf.track_name || "stemforge") + " | " + s.name;
        renameTrack(newIdx, clipName, cfg ? cfg.color : null);

        if (s.wav_path) {
            if (loadClip(newIdx, 0, s.wav_path, clipName)) loaded++;
        }

        // If there's a beats_dir and this stem is drums, also duplicate the
        // Simpler slice template. The actual beat sample is dragged in Live
        // 12 or loaded by a second LiveAPI call (out of v0 scope for
        // non-drums stems).
        if (s.name === "drums" && s.beats_dir) {
            var simplerIdx = findTrackByName(SIMPLER_TEMPLATE);
            if (simplerIdx >= 0) {
                var simNew = duplicateTrack(simplerIdx);
                renameTrack(simNew, (mf.track_name || "stemforge") + " | chop",
                    0xFF2400);
                status("  duplicated Simpler track for beat slices @ "
                    + s.beats_dir);
            }
        }
    }
    status("loader: " + loaded + "/" + mf.stems.length + " stems placed");
    outlet(1, "bang");
}

// ── Curated bars loader (Launchpad MVP) ──────────────────────────────────────
// Creates 4 audio tracks × 16 clip slots from a curated manifest.
// Each track maps to a Launchpad column in session clip launch mode.

var BAR_TRACK_ORDER = ["drums", "bass", "vocals", "other"];
var BAR_TRACK_COLORS = {
    drums:  0xFF4444,   // red
    bass:   0x4477FF,   // blue
    vocals: 0xFFAA44,   // orange
    other:  0x44DD77    // green
};
var BAR_WARP_MODES = {
    drums:  0,  // Beats
    bass:   0,  // Beats
    vocals: 4,  // Complex
    other:  4   // Complex
};

function createAudioTrack(insertIdx) {
    new LiveAPI("live_set").call("create_audio_track", insertIdx);
    return insertIdx;
}

function _loadCuratedManifest(mf) {
    if (mf.bpm) {
        try { new LiveAPI("live_set").set("tempo", Number(mf.bpm)); } catch (_) {}
        status("tempo → " + mf.bpm + " BPM");
    }

    if (!mf.stems) { status("manifest has no stems object"); return; }

    var loaded = 0;
    for (var si = 0; si < BAR_TRACK_ORDER.length; si++) {
        var stemName = BAR_TRACK_ORDER[si];
        var bars = mf.stems[stemName];
        if (!bars || !bars.length) {
            status("  " + stemName + ": no bars in manifest, skipping");
            continue;
        }

        var insertIdx = trackCount();
        createAudioTrack(insertIdx);

        var trackLabel = "[SF] " + stemName.charAt(0).toUpperCase() + stemName.slice(1) + " Bars";
        renameTrack(insertIdx, trackLabel, BAR_TRACK_COLORS[stemName]);

        var warpMode = BAR_WARP_MODES[stemName] || 0;

        for (var bi = 0; bi < bars.length; bi++) {
            var bar = bars[bi];
            if (!bar.file) continue;
            var clipName = stemName + " bar " + (bar.position || (bi + 1));
            if (loadClip(insertIdx, bi, bar.file, clipName)) {
                try {
                    var clipApi = new LiveAPI(
                        "live_set tracks " + insertIdx + " clip_slots " + bi + " clip"
                    );
                    if (clipApi.id !== "0") {
                        // Curation v2: apply padded markers + warp markers
                        // + offsets when present; fall back to legacy warp
                        // mode when the entry has no clip block.
                        if (!applyCurationV2Clip(clipApi, bar, stemName)) {
                            clipApi.set("warp_mode", warpMode);
                        }
                    }
                } catch (_) {}
                loaded++;
            }
        }
        status("  " + trackLabel + ": " + bars.length + " bars loaded");
    }
    status("loader: " + loaded + " curated bars across " + BAR_TRACK_ORDER.length + " tracks");
    outlet(1, "bang");
}

function loadCuratedBars() {
    var manifestPath = arrayfromargs(messagename, arguments).slice(1).join(" ");
    if (!manifestPath) { status("loadCuratedBars: missing path"); return; }

    var raw = readFileContents(manifestPath);
    if (!raw) { status("cannot read manifest: " + manifestPath); return; }
    var mf;
    try { mf = JSON.parse(raw); }
    catch (e) { status("manifest JSON parse: " + e); return; }

    _loadCuratedManifest(mf);
}

function loadFromDict() {
    var dictName = arrayfromargs(messagename, arguments).slice(1).join(" ") || "sf_manifest";
    var d;
    try { d = new Dict(dictName); }
    catch (e) { status("loadFromDict: cannot open dict " + dictName + ": " + e); return; }

    var mf;
    try { mf = _unwrapDictContent(JSON.parse(d.stringify())); }
    catch (e) { status("loadFromDict: parse error: " + e); return; }

    status("loaded manifest from dict: " + dictName);

    // Dispatch to v2 loader if manifest has v2 markers (oneshots, quadrants, or version=2)
    // Detect v2 format by stem DATA shape, not version number.
    // v1: stems are flat arrays of {file, position, ...}
    // v2: stems are dicts with {loops: [...], oneshots: [...]}
    // quadrants field = always v2
    var isV2 = false;
    if (mf.quadrants) {
        isV2 = true;
    } else if (mf.stems) {
        for (var key in mf.stems) {
            var val = mf.stems[key];
            if (val && typeof val === "object" && !Array.isArray(val) && (val.loops || val.oneshots)) {
                isV2 = true;
                break;
            }
        }
    }

    // Check for production mode (has layout_mode field)
    if (mf.layout_mode === "production") {
        status("detected production manifest → song loader");
        loadSong();
    } else if (isV2) {
        status("detected v2 manifest (loops+oneshots) → Drum Rack loader");
        _loadCuratedV2(mf);
    } else {
        status("detected v1 manifest (flat bars) → clip slot loader");
        _loadCuratedManifest(mf);
    }
}

// ── v2 Quadrant Loader (Drum Rack mode) ──────────────────────────────────────
// Creates 4 MIDI tracks with Drum Racks, loads samples into Simpler pads.
// Each stem gets a 4×4 quadrant: loops on pads 8-15, one-shots on pads 0-7.

var RACK_TEMPLATES = {
    drums:  "SF | Drums Rack",
    bass:   "SF | Bass Rack",
    vocals: "SF | Vocals Rack",
    other:  "SF | Other Rack"
};

function createMidiTrack(insertIdx) {
    new LiveAPI("live_set").call("create_midi_track", insertIdx);
    return insertIdx;
}

function loadSimplerSample(trackIdx, padIdx, wavPath, loopEnabled) {
    // Navigate: track → Drum Rack (device 0) → chain (pad) → Simpler (device 0)
    var chainPath = "live_set tracks " + trackIdx + " devices 0 chains " + padIdx + " devices 0";
    try {
        var simpler = new LiveAPI(chainPath);
        if (simpler.id === "0") {
            status("  pad " + padIdx + ": no Simpler found at " + chainPath);
            return false;
        }
        // Load sample — Live 12 API: SimplerDevice.replace_sample(absolute_path)
        // Uses POSIX path (NOT HFS/Max path)
        simpler.call("replace_sample", String(wavPath));
        // Set playback mode: 0=classic (loops), 1=one-shot (no loop)
        try {
            simpler.set("playback_mode", loopEnabled ? 0 : 1);
        } catch (_) {}
        return true;
    } catch (e) {
        status("  loadSimpler error pad " + padIdx + ": " + e);
        return false;
    }
}

function _loadCuratedV2(mf) {
    if (mf.bpm) {
        try { new LiveAPI("live_set").set("tempo", Number(mf.bpm)); } catch (_) {}
        status("tempo → " + mf.bpm + " BPM");
    }

    // Check for quadrants (v2 layout manifest) or stems (v2 curated manifest)
    var stemData = mf.quadrants || mf.stems;
    if (!stemData) { status("v2 manifest has no stems or quadrants"); return; }

    var songName = mf.track || "stemforge";
    var loaded = 0;

    // Strategy: duplicate the "SF | Templates" group (creates a new group with
    // all children), rename it to the song name, delete the duplicated Source
    // track, then rename the rack tracks.
    var templateGroupIdx = findTrackByName("SF | Templates");
    var songTrackMap = {};  // stemName → trackIdx

    if (templateGroupIdx >= 0) {
        var countBefore = trackCount();
        var newGroupIdx = duplicateTrack(templateGroupIdx);
        var countAfter = trackCount();
        var addedTracks = countAfter - countBefore;

        // Rename the new group to the song name
        renameTrack(newGroupIdx, songName, null);
        status("  created song group: " + songName + " (" + addedTracks + " tracks)");

        // Scan the new tracks (newGroupIdx+1 through newGroupIdx+addedTracks-1)
        // and map them by matching template names
        for (var ti = newGroupIdx + 1; ti < newGroupIdx + addedTracks; ti++) {
            var tn = String(trackName(ti));

            // Delete duplicated Source track (audio track with the device)
            if (tn === "SF | Source") {
                try {
                    new LiveAPI("live_set").call("delete_track", ti);
                    addedTracks--;
                    // Indices shift after deletion, re-scan
                    ti--;
                } catch (e) {
                    status("  could not delete duplicated Source: " + e);
                }
                continue;
            }

            // Match rack template names
            for (var si2 = 0; si2 < BAR_TRACK_ORDER.length; si2++) {
                var sn = BAR_TRACK_ORDER[si2];
                if (tn === RACK_TEMPLATES[sn] && !(sn in songTrackMap)) {
                    var cap = sn.charAt(0).toUpperCase() + sn.slice(1);
                    renameTrack(ti, cap + " | " + songName, BAR_TRACK_COLORS[sn]);
                    songTrackMap[sn] = ti;
                    break;
                }
            }
        }
    }

    // Fallback for any stems not found via group duplication
    for (var si = 0; si < BAR_TRACK_ORDER.length; si++) {
        var stemName = BAR_TRACK_ORDER[si];
        if (stemName in songTrackMap) continue;

        var data = stemData[stemName];
        if (!data) continue;

        var stemCapitalized = stemName.charAt(0).toUpperCase() + stemName.slice(1);
        var templateName = RACK_TEMPLATES[stemName];
        var templateIdx = templateName ? findTrackByName(templateName) : -1;

        var trackIdx;
        if (templateIdx >= 0) {
            trackIdx = duplicateTrack(templateIdx);
            renameTrack(trackIdx, stemCapitalized + " | " + songName, BAR_TRACK_COLORS[stemName]);
        } else {
            trackIdx = trackCount();
            createMidiTrack(trackIdx);
            renameTrack(trackIdx, "[SF] " + stemCapitalized + " Rack", BAR_TRACK_COLORS[stemName]);
            status("  " + stemName + ": no template — created bare MIDI track");
        }
        songTrackMap[stemName] = trackIdx;
    }

    // Load samples into each stem's track
    for (var si = 0; si < BAR_TRACK_ORDER.length; si++) {
        var stemName = BAR_TRACK_ORDER[si];
        var data = stemData[stemName];
        if (!data || !(stemName in songTrackMap)) continue;
        var trackIdx = songTrackMap[stemName];

        // Load pads from quadrant data (layout manifest format)
        if (data.pads) {
            for (var pi = 0; pi < data.pads.length; pi++) {
                var pad = data.pads[pi];
                if (!pad.file || pad.type === "empty") continue;
                if (loadSimplerSample(trackIdx, pad.pad_index, pad.file, pad.loop)) {
                    loaded++;
                }
            }
        }
        // Load from v2 curated manifest format (loops + oneshots)
        else {
            var loops = data.loops || data;
            var oneshots = data.oneshots || [];

            if (Array.isArray(loops) && oneshots.length === 0 && loops.length > 8) {
                // Loops-only mode: spread all loops across all 16 pads
                // Pad order: 0-3 (row 1), 4-7 (row 2), 8-11 (row 3), 12-15 (row 4)
                for (var li = 0; li < loops.length && li < 16; li++) {
                    var loop = loops[li];
                    if (loop && loop.file) {
                        if (loadSimplerSample(trackIdx, li, loop.file, true)) {
                            loaded++;
                        }
                    }
                }
            } else if (Array.isArray(loops)) {
                // Mixed mode: loops → pads 8-15 (top 2 rows)
                for (var li = 0; li < loops.length && li < 8; li++) {
                    var loop = loops[li];
                    if (loop && loop.file) {
                        var loopPad = 8 + li;
                        if (loadSimplerSample(trackIdx, loopPad, loop.file, true)) {
                            loaded++;
                        }
                    }
                }
            }

            // One-shots → pads 0-7 (bottom 2 rows) — only when present
            for (var oi = 0; oi < oneshots.length && oi < 8; oi++) {
                var os = oneshots[oi];
                if (os && os.file) {
                    if (loadSimplerSample(trackIdx, oi, os.file, false)) {
                        loaded++;
                    }
                }
            }
        }

        status("  " + stemName + " rack: pads loaded");
    }

    status("v2 loader: " + loaded + " pads loaded across " + BAR_TRACK_ORDER.length + " racks");
    outlet(1, "bang");
}

function loadCuratedV2() {
    var manifestPath = arrayfromargs(messagename, arguments).slice(1).join(" ");
    if (!manifestPath) { status("loadCuratedV2: missing path"); return; }

    var raw = readFileContents(manifestPath);
    if (!raw) { status("cannot read v2 manifest: " + manifestPath); return; }
    var mf;
    try { mf = JSON.parse(raw); }
    catch (e) { status("v2 manifest JSON parse: " + e); return; }

    _loadCuratedV2(mf);
}

function loadV2FromDict() {
    var dictName = arrayfromargs(messagename, arguments).slice(1).join(" ") || "sf_manifest";
    var d;
    try { d = new Dict(dictName); }
    catch (e) { status("loadV2FromDict: cannot open dict " + dictName + ": " + e); return; }

    var mf;
    try { mf = _unwrapDictContent(JSON.parse(d.stringify())); }
    catch (e) { status("loadV2FromDict: parse error: " + e); return; }

    status("loaded v2 manifest from dict: " + dictName);
    _loadCuratedV2(mf);
}

function ensureScenes(n) {
    // Ensure at least N scenes exist (for clip slots 0..N-1)
    var song = new LiveAPI("live_set");
    var current = song.getcount("scenes");
    while (current < n) {
        song.call("create_scene", current);
        current++;
    }
}

// ── Config-driven song loader (Live 12.3+) ──────────────────────────────────
// Per specs/processing_config_spec.md: each stem has N targets, each target
// creates one track with a type (clips/rack) and an optional effect chain.
// Chains are either all native `insert` devices or a single `template` track.

// Default processing config — embedded for immediate testability.
// Future: loaded from pipelines/production_idm.json via a [dict].
var PROCESSING_CONFIG = {
    drums: {
        targets: [
            {
                name: "loops", type: "clips", color: 0xFF4444,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: []
            },
            {
                name: "rack", type: "rack", color: 0xFF4444,
                params: { oneshot_count: 16, oneshot_mode: "classify" },
                chain: [
                    { insert: "Compressor", params: { Threshold: 0.55, Ratio: 0.75 } }
                ]
            },
            {
                name: "crushed", type: "clips", color: 0x882222,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: [
                    { template: "decapitator_drums", macros: { Drive: 0.7, Punish: 0.5, Style: 0, OutputTrim: 0.5 } }
                ]
            },
            {
                name: "repeat", type: "clips", color: 0xCC3333,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: [
                    { insert: "Beat Repeat", params: { Chance: 0.7, Grid: 7, Variation: 5, "Variation Type": 4, "Pitch Decay": 0.4, Decay: 0.3, "Mix Type": 2, Gate: 8 } },
                    { insert: "Compressor", params: { Threshold: 0.5, Ratio: 0.8 } }
                ]
            },
            {
                name: "echo", type: "clips", color: 0xAA4444,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: [
                    { insert: "Echo", params: { "L Synced": -4, "R Synced": -3, "L Sync Mode": 2, Feedback: 0.45, "Noise On": 1, "Noise Amt": 0.3, "Wobble On": 1, "Wobble Amt": 0.25, "Reverb Level": 0.2, "Reverb Loc": 2, "Dry Wet": 0.5 } }
                ]
            },
            {
                name: "grain", type: "clips", color: 0x993333,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: [
                    { insert: "Grain Delay", params: { Pitch: -7, Spray: 0.4, Frequency: 0.6, Random: 0.3, Feedback: 0.35, DryWet: 0.6 } },
                    { insert: "Reverb", params: { "Dry/Wet": 0.3 } }
                ]
            }
        ]
    },
    bass: {
        targets: [
            {
                name: "loops", type: "clips", color: 0x4477FF,
                params: { phrase_bars: 2, loop_count: 16 },
                chain: [
                    { insert: "EQ Eight", params: {} },
                    { insert: "Compressor", params: { Threshold: 0.6, Ratio: 0.65 } }
                ]
            }
        ]
    },
    vocals: {
        targets: [
            {
                name: "phrases", type: "clips", color: 0xFFAA44,
                params: { phrase_bars: 4, loop_count: 16 },
                chain: [
                    { insert: "EQ Eight", params: {} },
                    { insert: "Compressor", params: { Threshold: 0.65, Ratio: 0.6 } }
                ]
            }
        ]
    },
    other: {
        targets: [
            {
                name: "loops", type: "clips", color: 0x44DD77,
                params: { phrase_bars: 2, loop_count: 16 },
                chain: []
            },
            {
                name: "grain", type: "clips", color: 0x338855,
                params: { phrase_bars: 2, loop_count: 16 },
                chain: [
                    { insert: "Grain Delay", params: { Pitch: -5, Spray: 0.5, Frequency: 0.5, Random: 0.4, Feedback: 0.4, DryWet: 0.7 } },
                    { insert: "Reverb", params: { "Dry/Wet": 0.4 } }
                ]
            },
            {
                name: "echo", type: "clips", color: 0x2D7744,
                params: { phrase_bars: 2, loop_count: 16 },
                chain: [
                    { insert: "Echo", params: { "L Synced": -3, "R Synced": -2, "L Sync Mode": 2, Feedback: 0.5, "Noise On": 1, "Noise Amt": 0.25, "Wobble On": 1, "Wobble Amt": 0.2, "Reverb Level": 0.35, "Reverb Decay": 0.7, "Reverb Loc": 2, "Dry Wet": 0.55 } }
                ]
            }
        ]
    }
};

function applyParams(trackIdx, deviceIdx, params) {
    if (!params) return;
    var device = new LiveAPI("live_set tracks " + trackIdx + " devices " + deviceIdx);
    // Force LOM to settle after insert_device
    device.get("name");
    var paramCount = device.getcount("parameters");

    for (var paramName in params) {
        var value = params[paramName];
        var found = false;
        for (var i = 0; i < paramCount; i++) {
            var param = new LiveAPI("live_set tracks " + trackIdx + " devices " + deviceIdx + " parameters " + i);
            var pName = param.get("name");
            pName = (pName && typeof pName === "object") ? String(pName[0]) : String(pName);
            if (pName === paramName) {
                param.set("value", value);
                found = true;
                break;
            }
        }
        if (!found) {
            status("    WARN: param \"" + paramName + "\" not found on device " + deviceIdx);
        }
    }
}

function applyInsertChain(trackIdx, chain) {
    if (!chain || !chain.length) return;
    var track = new LiveAPI("live_set tracks " + trackIdx);

    for (var ci = 0; ci < chain.length; ci++) {
        var effect = chain[ci];
        if (!effect.insert) continue;

        try {
            var deviceCount = track.getcount("devices");
            track.call("insert_device", effect.insert, deviceCount);
            status("    + " + effect.insert);

            if (effect.params && Object.keys(effect.params).length > 0) {
                applyParams(trackIdx, deviceCount, effect.params);
            }
        } catch (e) {
            status("    WARN: insert failed: " + effect.insert + " — " + e);
        }
    }
}

function applyTemplateChain(chain, songName, targetName, color) {
    // Template chains create the track via duplication (no pre-created track).
    // Returns the track index of the duplicated template.
    if (!chain || !chain.length) return -1;
    var effect = chain[0];  // v1: single template per chain
    if (!effect.template) return -1;

    var templateTrackName = "[TEMPLATE] " + effect.template;
    var templateIdx = findTrackByName(templateTrackName);
    if (templateIdx < 0) {
        status("    WARN: template not found: " + templateTrackName);
        return -1;
    }

    // Duplicate template track — all devices come along
    var dupIdx = duplicateTrack(templateIdx);
    renameTrack(dupIdx, targetName + " | " + songName, color);
    status("    duplicated template: " + effect.template);

    // Apply macros if specified — scale 0-1 config values to actual param range
    if (effect.macros) {
        var rackDevice = new LiveAPI("live_set tracks " + dupIdx + " devices 0");
        var className = rackDevice.get("class_name");
        className = (className && typeof className === "object") ? String(className[0]) : String(className);

        if (className.indexOf("Rack") >= 0 || className.indexOf("Group") >= 0) {
            var paramCount = rackDevice.getcount("parameters");
            for (var macroName in effect.macros) {
                var macroVal = effect.macros[macroName];
                var found = false;
                for (var mi = 0; mi < paramCount; mi++) {
                    var mp = new LiveAPI("live_set tracks " + dupIdx + " devices 0 parameters " + mi);
                    var mn = mp.get("name");
                    mn = (mn && typeof mn === "object") ? String(mn[0]) : String(mn);
                    if (mn === macroName) {
                        var pMin = mp.get("min");
                        pMin = (pMin && typeof pMin === "object") ? Number(pMin[0]) : Number(pMin);
                        var pMax = mp.get("max");
                        pMax = (pMax && typeof pMax === "object") ? Number(pMax[0]) : Number(pMax);
                        var scaled = pMin + macroVal * (pMax - pMin);
                        mp.set("value", scaled);
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    status("    WARN: macro \"" + macroName + "\" not found");
                }
            }
        } else {
            status("    WARN: first device is not a rack (" + className + "), macros skipped");
        }
    }

    return dupIdx;
}

function buildDrumRack(trackIdx, oneshots) {
    // Live 12.3+: insert Drum Rack from scratch, add chains with Simplers.
    var track = new LiveAPI("live_set tracks " + trackIdx);
    try {
        track.call("insert_device", "Drum Rack", 0);
    } catch (e) {
        status("    ERROR inserting Drum Rack: " + e);
        return 0;
    }

    var drumRack = new LiveAPI("live_set tracks " + trackIdx + " devices 0");
    var loaded = 0;

    for (var oi = 0; oi < oneshots.length && oi < 16; oi++) {
        var os = oneshots[oi];
        if (!os || !os.file) continue;

        try {
            drumRack.call("insert_chain", oi);
            var chainPath = "live_set tracks " + trackIdx + " devices 0 chains " + oi;
            var chain = new LiveAPI(chainPath);
            chain.set("in_note", 36 + oi);
            chain.set("name", os.classification || ("pad " + oi));
            chain.call("insert_device", "Simpler", 0);

            var simpler = new LiveAPI(chainPath + " devices 0");
            simpler.call("replace_sample", String(os.file));
            try { simpler.set("playback_mode", 1); } catch (_) {}
            loaded++;
        } catch (e) {
            status("    pad " + oi + " error: " + e);
        }
    }
    return loaded;
}

function loadClipsToTrack(trackIdx, loops, stemName) {
    var warpMode = BAR_WARP_MODES[stemName] || 0;
    var loaded = 0;

    for (var li = 0; li < loops.length && li < 16; li++) {
        var item = loops[li];
        if (item && item.file) {
            var clipName = stemName + " bar " + (item.position || (li + 1));
            if (loadClip(trackIdx, li, item.file, clipName, 0)) {
                try {
                    var clipApi = new LiveAPI(
                        "live_set tracks " + trackIdx + " clip_slots " + li + " clip"
                    );
                    if (clipApi.id !== "0") {
                        // Curation v2: if entry has a clip block, apply
                        // padded markers + warp markers + offsets. Otherwise
                        // fall back to legacy per-stem warp_mode.
                        if (!applyCurationV2Clip(clipApi, item, stemName)) {
                            clipApi.set("warp_mode", warpMode);
                        }
                    }
                } catch (_) {}
                loaded++;
            }
        }
    }
    return loaded;
}

function parseColor(c) {
    // Accept integer (0xFF4444), hex string ("#FF4444"), or color-descriptor
    // object ({name, index, hex}) → integer for Live API. Object form is what
    // the preset JSON now ships (see presets/idm_production.json). We extract
    // the hex rather than the index so each target keeps its authored shade —
    // color_index would collapse shade variants that share a palette slot.
    if (typeof c === "number") return c;
    if (typeof c === "string" && c.charAt(0) === "#") {
        return parseInt(c.substring(1), 16);
    }
    if (c && typeof c === "object") {
        if (typeof c.hex === "string" && c.hex.charAt(0) === "#") {
            return parseInt(c.hex.substring(1), 16);
        }
        if (typeof c.hex === "number") return c.hex;
    }
    return null;
}

function isTemplateChain(chain) {
    // v1 constraint: chains are homogeneous — all insert OR single template.
    return chain && chain.length > 0 && chain[0].template;
}

// ── Preset system ────────────────────────────────────────────────────────────

var PRESETS_DIR = null;

function _getHomePath() {
    var skip = { Shared: 1, Library: 1, Guest: 1, admin: 1 };
    var f = new Folder("Macintosh HD:/Users/");
    var dirs = [];
    while (!f.end) {
        var fn = String(f.filename);
        if (f.filetype === "fold" && !skip[fn] && fn.charAt(0) !== ".") {
            dirs.push(fn);
        }
        f.next();
    }
    f.close();
    if (dirs.length === 1) return "/Users/" + dirs[0];
    // Check which user has the Max 9 Packages directory
    for (var i = 0; i < dirs.length; i++) {
        var testPath = "Macintosh HD:/Users/" + dirs[i] + "/Documents/Max 9/Packages";
        var tf = new Folder(testPath);
        var hasEntries = !tf.end;
        tf.close();
        if (hasEntries) return "/Users/" + dirs[i];
    }
    return "/Users/" + (dirs[0] || "unknown");
}

function scanPresets() {
    var home = _getHomePath();
    // Try multiple possible locations for the presets directory
    var candidates = [
        home + "/Documents/Max 9/Packages/StemForge/presets",
        home + "/Documents/Max 8/Packages/StemForge/presets"
    ];

    var presetsPath = null;
    var folder = null;
    for (var ci = 0; ci < candidates.length; ci++) {
        var maxPath = toMaxPath(candidates[ci]);
        try {
            var f = new Folder(maxPath);
            if (!f.end || f.filename) {
                presetsPath = candidates[ci];
                folder = f;
                break;
            }
            f.close();
        } catch (_) {}
    }

    if (!folder) {
        status("presets dir not found");
        return;
    }

    var presetNames = [];
    while (!folder.end) {
        var fn = String(folder.filename);
        if (fn.length > 5 && fn.substring(fn.length - 5) === ".json") {
            presetNames.push(fn.substring(0, fn.length - 5));
        }
        folder.next();
    }
    folder.close();

    PRESETS_DIR = presetsPath;

    // Populate umenu via outlet 2
    outlet(2, "clear");
    for (var i = 0; i < presetNames.length; i++) {
        outlet(2, "append", presetNames[i]);
    }

    // Auto-select default preset
    var defaultIdx = 0;
    for (var i = 0; i < presetNames.length; i++) {
        if (presetNames[i] === "idm_production") { defaultIdx = i; break; }
    }
    if (presetNames.length > 0) {
        outlet(2, defaultIdx);
    }

    status("found " + presetNames.length + " presets");
}

function loadPreset() {
    var name = arrayfromargs(messagename, arguments).slice(1).join(" ");
    // Strip umenu prefix if present
    name = name.replace(/^Preset:\s*/, "");
    if (!name || !PRESETS_DIR) {
        status("loadPreset: no name or presets dir");
        return;
    }

    var jsonPath = PRESETS_DIR + "/" + name + ".json";
    var raw = readFileContents(jsonPath);
    if (!raw) {
        status("cannot read preset: " + name);
        return;
    }

    var preset;
    try { preset = JSON.parse(raw); }
    catch (e) { status("preset parse error: " + e); return; }

    // Load into sf_preset dict
    var d = new Dict("sf_preset");
    d.parse(raw);

    var meta = preset.preset || {};
    status("preset: " + (meta.name || name) + " v" + (meta.version || "?"));
}

function loadSong() {
    // Config-driven song loader (Live 12.3+).
    // Reads manifest content + processing config targets.
    // For each stem: iterates targets, creates appropriate track, loads content,
    // applies effect chain (native insert or template duplication).
    var dictName = "sf_manifest";
    var d;
    try { d = new Dict(dictName); }
    catch (e) { status("loadSong: cannot open dict " + dictName + ": " + e); return; }

    var mf;
    try { mf = _unwrapDictContent(JSON.parse(d.stringify())); }
    catch (e) { status("loadSong: parse error: " + e); return; }

    var stemData = mf.stems;
    if (!stemData) { status("manifest has no stems"); return; }

    var songName = mf.track || "stemforge";
    var loaded = 0;

    if (mf.bpm) {
        try { new LiveAPI("live_set").set("tempo", Number(mf.bpm)); } catch (_) {}
        status("tempo → " + mf.bpm + " BPM");
    }

    ensureScenes(16);

    // Priority chain: sf_preset dict → manifest embedding → hardcoded fallback
    var pipelineConfig = null;
    var pipelineSource = "hardcoded";
    var pipelineName = null;

    // 1. sf_preset dict (user selected preset in dropdown).
    //    Tolerate three possible shapes:
    //      a) Top-level `stems` (direct parse-tree write)
    //      b) `root` key holds a stringified JSON blob
    //      c) `root` key holds a parsed-tree object
    try {
        var presetDict = new Dict("sf_preset");
        var presetRaw = presetDict.stringify();
        if (presetRaw && presetRaw !== "{}") {
            var outer = JSON.parse(presetRaw);
            var unwrapped = outer;
            if (outer && outer.root !== undefined) {
                if (typeof outer.root === "string") {
                    try { unwrapped = JSON.parse(outer.root); } catch (_) { unwrapped = outer; }
                } else if (typeof outer.root === "object") {
                    unwrapped = outer.root;
                }
            }
            if (unwrapped && unwrapped.stems) {
                pipelineConfig = unwrapped.stems;
                pipelineSource = "sf_preset";
                pipelineName = (unwrapped.displayName
                    || unwrapped.name
                    || (unwrapped.preset && unwrapped.preset.name)
                    || "(unnamed)");
            }
        }
    } catch (e) {
        status("sf_preset read error: " + e);
    }

    // 2. manifest-embedded processing_config (backward compat)
    if (!pipelineConfig && mf.processing_config) {
        pipelineConfig = mf.processing_config;
        pipelineSource = "manifest-embedded";
    }

    // 3. hardcoded fallback (IDM)
    if (!pipelineConfig) {
        pipelineConfig = PROCESSING_CONFIG;
        pipelineSource = "hardcoded-IDM";
    }
    status("pipelineConfig source: " + pipelineSource
        + (pipelineName ? " (" + pipelineName + ")" : ""));

    var stemOrder = ["drums", "bass", "vocals", "other"];

    for (var si = 0; si < stemOrder.length; si++) {
        var stemName = stemOrder[si];
        var data = stemData[stemName];
        if (!data) continue;

        var stemCap = stemName.charAt(0).toUpperCase() + stemName.slice(1);

        // Get content from manifest
        var loops = Array.isArray(data) ? data : (data.loops || []);
        var oneshots = (typeof data === "object" && !Array.isArray(data)) ? (data.oneshots || []) : [];

        // Get targets from processing config
        var stemConfig = pipelineConfig[stemName];
        if (!stemConfig || !stemConfig.targets) {
            // Fallback: create a simple clips track if we have loops
            if (loops.length > 0) {
                var fallbackIdx = trackCount();
                createAudioTrack(fallbackIdx);
                renameTrack(fallbackIdx, stemCap + " Loops | " + songName, BAR_TRACK_COLORS[stemName]);
                loaded += loadClipsToTrack(fallbackIdx, loops, stemName);
                status("  " + stemCap + " Loops: " + loops.length + " clips (no config)");
            }
            continue;
        }

        // Iterate targets from processing config
        var targets = stemConfig.targets;
        for (var ti = 0; ti < targets.length; ti++) {
            var target = targets[ti];
            var targetName = stemCap + " " + (target.name || "Track");
            var targetColor = parseColor(target.color) || BAR_TRACK_COLORS[stemName];
            var chain = target.chain || [];

            status("  " + targetName + " (" + target.type + ")");

            if (target.type === "clips") {
                // ── Clips target: audio track with bar loops ──
                if (loops.length === 0) {
                    status("    skipped (no loops in manifest)");
                    continue;
                }

                var clipsTrackIdx;

                if (isTemplateChain(chain)) {
                    // Template chain: duplicate creates the track
                    clipsTrackIdx = applyTemplateChain(chain, songName, targetName, targetColor);
                    if (clipsTrackIdx < 0) continue;
                } else {
                    // Native chain: create track, then insert devices
                    clipsTrackIdx = trackCount();
                    createAudioTrack(clipsTrackIdx);
                    renameTrack(clipsTrackIdx, targetName + " | " + songName, targetColor);

                    if (chain.length > 0) {
                        applyInsertChain(clipsTrackIdx, chain);
                    }
                }

                var clipsLoaded = loadClipsToTrack(clipsTrackIdx, loops, stemName);
                loaded += clipsLoaded;
                status("    " + clipsLoaded + " clips loaded");

            } else if (target.type === "rack") {
                // ── Rack target: MIDI track with Drum Rack ──
                if (oneshots.length === 0) {
                    status("    skipped (no oneshots in manifest)");
                    continue;
                }

                var rackTrackIdx = trackCount();
                new LiveAPI("live_set").call("create_midi_track", rackTrackIdx);
                renameTrack(rackTrackIdx, targetName + " | " + songName, targetColor);

                var rackLoaded = buildDrumRack(rackTrackIdx, oneshots);
                loaded += rackLoaded;
                status("    " + rackLoaded + " pads loaded");

                // Apply chain AFTER Drum Rack (effects go on the track, after the rack)
                if (chain.length > 0 && !isTemplateChain(chain)) {
                    applyInsertChain(rackTrackIdx, chain);
                }
            }
        }
    }

    status("song loader: " + loaded + " items across " + stemOrder.length + " stems for \"" + songName + "\"");
    outlet(1, "bang");
}

// ── Curation v2: commit offsets (Ableton → manifest) ────────────────────────
// Per spec §6. Walks every track × clip_slot (up to 31), matches loaded clips
// against manifest entries by file_path, reads the current start_marker /
// end_marker from the LOM, computes the offset vs padded_*_sec, and writes
// the result back to the manifest (sf_manifest dict or disk file).
//
// Two call shapes:
//   commitOffsets                    → reads/writes the `sf_manifest` dict
//   commitOffsets <absManifestPath>  → reads/writes the file on disk

function _stripHfsPrefix(s) {
    if (!s) return "";
    var str = String(s);
    // LOM returns paths as "Macintosh HD:/Users/..." — strip the prefix so
    // manifest entries stored as POSIX paths compare cleanly.
    if (str.indexOf("Macintosh HD:") === 0) {
        return str.substring("Macintosh HD:".length);
    }
    return str;
}

function _getLomString(api, prop) {
    try {
        var v = api.get(prop);
        if (v && typeof v === "object") return String(v[0]);
        return String(v);
    } catch (_) {
        return "";
    }
}

function _getLomNumber(api, prop) {
    try {
        var v = api.get(prop);
        if (v && typeof v === "object") return Number(v[0]);
        return Number(v);
    } catch (_) {
        return NaN;
    }
}

function _buildClipIndex() {
    // Returns {posixPath: {trackIdx, slotIdx}} for every loaded audio clip in
    // the live set, covering clip_slots 0..30 on each track.
    var index = {};
    var n = trackCount();
    for (var ti = 0; ti < n; ti++) {
        for (var sj = 0; sj < 31; sj++) {
            var csPath = "live_set tracks " + ti + " clip_slots " + sj;
            var clipApi;
            try {
                clipApi = new LiveAPI(csPath + " clip");
            } catch (_) { continue; }
            if (!clipApi || clipApi.id === "0") continue;
            var fp = _getLomString(clipApi, "file_path");
            if (!fp) continue;
            var posix = _stripHfsPrefix(fp);
            if (!posix) continue;
            if (!index[posix]) {
                index[posix] = { trackIdx: ti, slotIdx: sj };
            }
        }
    }
    return index;
}

function _commitEntryOffsets(entry, clipIndex) {
    // Mutates `entry` in place. Returns true if offsets were committed.
    if (!entry || !entry.clip || !entry.file) return false;
    if (entry.clip.padded_start_sec === undefined) return false;

    var target = String(entry.file);
    var hit = clipIndex[target];
    if (!hit) {
        // Also try stripping HFS from the manifest side, in case it stored a
        // Macintosh HD: path.
        hit = clipIndex[_stripHfsPrefix(target)];
    }
    if (!hit) return false;

    var clipApi = new LiveAPI(
        "live_set tracks " + hit.trackIdx + " clip_slots " + hit.slotIdx + " clip"
    );
    if (!clipApi || clipApi.id === "0") return false;

    // Ableton returns start_marker/end_marker in BEATS for warped clips.
    // Convert back to seconds using the slope derived from the manifest's
    // warp_markers so the computed offsets are in the same units the manifest
    // stores them (seconds, relative to raw_*).
    var startMarkerBeats = _getLomNumber(clipApi, "start_marker");
    var endMarkerBeats = _getLomNumber(clipApi, "end_marker");
    if (!isFinite(startMarkerBeats) || !isFinite(endMarkerBeats)) return false;

    var beatToSec = 1.0;
    if (entry.warp_markers && entry.warp_markers.length >= 2) {
        var wmFirst = entry.warp_markers[0];
        var wmLast = entry.warp_markers[entry.warp_markers.length - 1];
        var ds = Number(wmLast.time_sec) - Number(wmFirst.time_sec);
        var db = Number(wmLast.beat_pos) - Number(wmFirst.beat_pos);
        if (isFinite(ds) && isFinite(db) && db > 0) {
            beatToSec = ds / db;
        }
    }
    var startMarkerSec = startMarkerBeats * beatToSec;
    var endMarkerSec = endMarkerBeats * beatToSec;

    // Offsets are relative to raw_* (the musical bar boundaries), matching
    // applyCurationV2Clip's default start/end = raw_* + offset. A negative
    // start_offset means the user trimmed backward into the left pad to
    // reveal an early transient; positive means they trimmed forward past
    // the bar start. Same symmetry for end_offset with the right pad.
    var rawStart = Number(entry.clip.raw_start_sec) || 0.0;
    var rawEnd = Number(entry.clip.raw_end_sec) || 0.0;

    var offsets = entry.offsets || {};
    offsets.start_offset_sec = startMarkerSec - rawStart;
    offsets.end_offset_sec = endMarkerSec - rawEnd;
    offsets.committed = true;
    if (offsets.note === undefined) offsets.note = "";
    entry.offsets = offsets;
    return true;
}

function _commitAllOffsets(mf, clipIndex) {
    // Walks a manifest's stems, handling both v2 {loops: [...]} and v1 flat-
    // array shapes. Mutates mf in place, returns the count of committed
    // entries.
    if (!mf || !mf.stems) return 0;
    var committed = 0;
    for (var key in mf.stems) {
        var stemBlock = mf.stems[key];
        if (!stemBlock) continue;
        var list = null;
        if (Array.isArray(stemBlock)) {
            // v1 flat-array stem shape.
            list = stemBlock;
        } else if (stemBlock && Array.isArray(stemBlock.loops)) {
            // v2 {loops: [...], oneshots: [...]} shape — only loops have
            // clip markers; oneshots are triggered from Simpler pads.
            list = stemBlock.loops;
        }
        if (!list) continue;
        for (var li = 0; li < list.length; li++) {
            if (_commitEntryOffsets(list[li], clipIndex)) committed++;
        }
    }
    return committed;
}

function commitOffsets() {
    var args = arrayfromargs(messagename, arguments).slice(1);
    var diskPath = args.length ? args.join(" ") : "";

    var clipIndex = _buildClipIndex();

    if (diskPath) {
        // Disk-backed mode: read the JSON file, mutate, write back.
        var raw = readFileContents(diskPath);
        if (!raw) {
            status("commitOffsets: cannot read " + diskPath);
            return;
        }
        var mf;
        try { mf = JSON.parse(raw); }
        catch (e) {
            status("commitOffsets: parse error: " + e);
            return;
        }
        var n = _commitAllOffsets(mf, clipIndex);
        var out;
        try { out = JSON.stringify(mf, null, 2); }
        catch (e2) {
            status("commitOffsets: stringify error: " + e2);
            return;
        }
        if (!writeFileContents(diskPath, out)) {
            status("commitOffsets: write failed for " + diskPath);
            return;
        }
        status("Committed offsets for " + n + " clips");
        outlet(0, "set", "Committed offsets for " + n + " clips");
        outlet(1, "bang");
        return;
    }

    // Dict-backed mode: read sf_manifest, mutate, write back.
    var d;
    try { d = new Dict("sf_manifest"); }
    catch (e) {
        status("commitOffsets: cannot open sf_manifest: " + e);
        return;
    }
    var rawDict;
    try { rawDict = d.stringify(); }
    catch (e3) {
        status("commitOffsets: dict stringify error: " + e3);
        return;
    }
    var mfDict;
    try { mfDict = _unwrapDictContent(JSON.parse(rawDict)); }
    catch (e4) {
        status("commitOffsets: dict parse error: " + e4);
        return;
    }
    var nDict = _commitAllOffsets(mfDict, clipIndex);
    // Dict.parse stores json content directly (no auto-wrap) — pass unwrapped.
    try {
        d.parse(JSON.stringify(mfDict));
    } catch (e5) {
        status("commitOffsets: dict write error: " + e5);
        return;
    }

    // Also persist to disk so the manifest file reflects the committed
    // offsets across sessions. Derive the path from `source_dir` in the
    // manifest — that's where `curated/manifest.json` lives.
    var wroteDisk = false;
    var srcDir = mfDict && mfDict.source_dir;
    if (srcDir) {
        var diskPathDerived = String(srcDir).replace(/\/+$/, "")
            + "/curated/manifest.json";
        var mfOut;
        try { mfOut = JSON.stringify(mfDict, null, 2); }
        catch (eS) { status("commitOffsets: disk stringify error: " + eS); }
        if (mfOut && writeFileContents(diskPathDerived, mfOut)) {
            wroteDisk = true;
        } else if (mfOut) {
            status("commitOffsets: disk write failed for " + diskPathDerived);
        }
    }

    var msg = "Committed offsets for " + nDict + " clips"
        + (wroteDisk ? " (dict + disk)" : " (dict only)");
    status(msg);
    outlet(0, "set", msg);
    outlet(1, "bang");
}

// ── Entry points from Max ─────────────────────────────────────────────────────
// These aren't stored on `globalThis`; Max's classic [js] object scans for
// top-level functions automatically.

// Eslint-friendly re-exports — tests import the file as CommonJS via a shim.
if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        STEM_TARGETS: STEM_TARGETS,
        SIMPLER_TEMPLATE: SIMPLER_TEMPLATE,
        BAR_TRACK_ORDER: BAR_TRACK_ORDER,
        BAR_TRACK_COLORS: BAR_TRACK_COLORS,
        RACK_TEMPLATES: RACK_TEMPLATES,
        PROCESSING_CONFIG: PROCESSING_CONFIG,
    };
}
