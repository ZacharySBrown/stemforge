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

/* global Max, outlet, post, LiveAPI, File, Task, messagename, arrayfromargs */

autowatch = 1;
inlets = 1;
outlets = 2;   // 0: status text, 1: bang on completion

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

function status(msg) {
    try { outlet(0, "set", String(msg)); } catch (_) {}
    try { post(String(msg) + "\n"); } catch (_) {}
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
        var raw = "";
        while (f.position < f.eof) { raw += f.readstring(65536); }
        f.close();
        return raw;
    } catch (e) {
        status("readFile error: " + e);
        return null;
    }
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
                        clipApi.set("warp_mode", warpMode);
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
    try { mf = JSON.parse(d.stringify()); }
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
        status("detected production manifest → 5-track group loader");
        _loadProductionMode(mf);
    } else if (isV2) {
        status("detected v2 manifest (loops+oneshots) → Drum Rack loader");
        _loadCuratedV2(mf);
    } else {
        status("detected v1 manifest (flat bars) → clip slot loader");
        _loadCuratedManifest(mf);
    }
}

// ── Production Mode Loader ───────────────────────────────────────────────────
// Creates a 5-track group per song:
//   1. Drums Loops   — audio track, 16 clip slots
//   2. Drums Rack    — MIDI track, Drum Rack with classified one-shots
//   3. Bass Loops    — audio track, 16 clip slots
//   4. Vocals Loops  — audio track, 16 clip slots
//   5. Other Loops   — audio track, 16 clip slots

var PRODUCTION_STEM_ORDER = ["drums", "bass", "vocals", "other"];

function _loadProductionMode(mf) {
    if (mf.bpm) {
        try { new LiveAPI("live_set").set("tempo", Number(mf.bpm)); } catch (_) {}
        status("tempo → " + mf.bpm + " BPM");
    }

    var stemData = mf.stems;
    if (!stemData) { status("production manifest has no stems"); return; }

    var songName = mf.track || "stemforge";
    var loaded = 0;

    // Try to duplicate the SF | Templates group for organization
    var templateGroupIdx = findTrackByName("SF | Templates");
    var groupCreated = false;

    if (templateGroupIdx >= 0) {
        var countBefore = trackCount();
        var newGroupIdx = duplicateTrack(templateGroupIdx);
        var countAfter = trackCount();

        // Rename group to song name
        renameTrack(newGroupIdx, songName, null);

        // Delete all duplicated child tracks (we'll create our own)
        // Children are the tracks between newGroupIdx+1 and newGroupIdx+(countAfter-countBefore)-1
        var childCount = countAfter - countBefore - 1;
        for (var d = 0; d < childCount; d++) {
            try {
                new LiveAPI("live_set").call("delete_track", newGroupIdx + 1);
            } catch (e) {
                status("  could not delete child track: " + e);
            }
        }
        groupCreated = true;
        status("created song group: " + songName);
    }

    // Track 1: Drums Loops (audio track with clip slots)
    var drumsData = stemData["drums"];
    if (drumsData) {
        var drumsLoops = Array.isArray(drumsData) ? drumsData : (drumsData.loops || []);
        var drumsTrackIdx = trackCount();
        createAudioTrack(drumsTrackIdx);
        renameTrack(drumsTrackIdx, "Drums Loops | " + songName, BAR_TRACK_COLORS["drums"]);

        for (var i = 0; i < drumsLoops.length && i < 16; i++) {
            var loop = drumsLoops[i];
            if (loop && loop.file) {
                var clipName = "drums bar " + (loop.position || (i + 1));
                var startBeat = loop.first_transient_beats || 0;
                if (loadClip(drumsTrackIdx, i, loop.file, clipName, startBeat)) loaded++;
            }
        }
        status("  Drums Loops: " + Math.min(drumsLoops.length, 16) + " clips");
    }

    // Track 2: Drums Rack (MIDI track with one-shots in Drum Rack)
    var drumsOneshots = [];
    if (drumsData && typeof drumsData === "object" && !Array.isArray(drumsData)) {
        drumsOneshots = drumsData.oneshots || [];
    }

    if (drumsOneshots.length > 0) {
        // Find Drum Rack template and duplicate
        var drumRackTemplate = findTrackByName("SF | Drums Rack");
        var drumRackIdx;
        if (drumRackTemplate >= 0) {
            drumRackIdx = duplicateTrack(drumRackTemplate);
            renameTrack(drumRackIdx, "Drums Rack | " + songName, BAR_TRACK_COLORS["drums"]);

            // Load one-shots into Simpler pads
            for (var oi = 0; oi < drumsOneshots.length && oi < 16; oi++) {
                var os = drumsOneshots[oi];
                if (os && os.file) {
                    if (loadSimplerSample(drumRackIdx, oi, os.file, false)) loaded++;
                }
            }
            status("  Drums Rack: " + Math.min(drumsOneshots.length, 16) + " one-shots");
        } else {
            // No template — create bare MIDI track
            drumRackIdx = trackCount();
            createMidiTrack(drumRackIdx);
            renameTrack(drumRackIdx, "Drums Rack | " + songName + " (no template)", BAR_TRACK_COLORS["drums"]);
            status("  Drums Rack: no SF | Drums Rack template found");
        }
    }

    // Tracks 3-5: Bass, Vocals, Other loops (audio tracks with clip slots)
    var loopStems = ["bass", "vocals", "other"];
    for (var si = 0; si < loopStems.length; si++) {
        var stemName = loopStems[si];
        var data = stemData[stemName];
        if (!data) continue;

        var loops = Array.isArray(data) ? data : (data.loops || []);
        var stemTrackIdx = trackCount();
        createAudioTrack(stemTrackIdx);

        var stemCap = stemName.charAt(0).toUpperCase() + stemName.slice(1);
        renameTrack(stemTrackIdx, stemCap + " Loops | " + songName, BAR_TRACK_COLORS[stemName]);

        var warpMode = BAR_WARP_MODES[stemName] || 0;
        for (var li = 0; li < loops.length && li < 16; li++) {
            var item = loops[li];
            if (item && item.file) {
                var name = stemName + " bar " + (item.position || (li + 1));
                var startBeat = item.first_transient_beats || 0;
                if (loadClip(stemTrackIdx, li, item.file, name, startBeat)) {
                    // Set warp mode
                    try {
                        var clipApi = new LiveAPI(
                            "live_set tracks " + stemTrackIdx + " clip_slots " + li + " clip"
                        );
                        if (clipApi.id !== "0") {
                            clipApi.set("warp_mode", warpMode);
                        }
                    } catch (_) {}
                    loaded++;
                }
            }
        }
        status("  " + stemCap + " Loops: " + Math.min(loops.length, 16) + " clips");
    }

    status("production loader: " + loaded + " items loaded (5 tracks)");
    outlet(1, "bang");
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
    try { mf = JSON.parse(d.stringify()); }
    catch (e) { status("loadV2FromDict: parse error: " + e); return; }

    status("loaded v2 manifest from dict: " + dictName);
    _loadCuratedV2(mf);
}

// ── Entry points from Max ─────────────────────────────────────────────────────
// These aren't stored on `globalThis`; Max's classic [js] object scans for
// top-level functions automatically. Keep names exactly as handlers used in
// builder.py (`setBpm`, `loadManifest`, `loadCuratedBars`, `loadCuratedV2`).

// Eslint-friendly re-exports — tests import the file as CommonJS via a shim.
if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        STEM_TARGETS: STEM_TARGETS,
        SIMPLER_TEMPLATE: SIMPLER_TEMPLATE,
        BAR_TRACK_ORDER: BAR_TRACK_ORDER,
        BAR_TRACK_COLORS: BAR_TRACK_COLORS,
        RACK_TEMPLATES: RACK_TEMPLATES
    };
}
