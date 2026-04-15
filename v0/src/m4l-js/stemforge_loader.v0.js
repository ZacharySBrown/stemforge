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

function loadClip(trackIdx, slotIdx, wavPath, clipName) {
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

// ── Entry points from Max ─────────────────────────────────────────────────────
// These aren't stored on `globalThis`; Max's classic [js] object scans for
// top-level functions automatically. Keep names exactly as handlers used in
// builder.py (`setBpm`, `loadManifest`).

// Eslint-friendly re-exports — tests import the file as CommonJS via a shim.
if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        STEM_TARGETS: STEM_TARGETS,
        SIMPLER_TEMPLATE: SIMPLER_TEMPLATE
    };
}
