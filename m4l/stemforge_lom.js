// stemforge_lom.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] script paired with stemforge_bridge.js (node.script).
// Reads Ableton clip analysis via the Live Object Model, writes a temp JSON
// file, then emits a `run <audio> <tmpJson> <nBars> <strategy>` message for
// the node bridge to consume.
//
// Inlet messages:
//   forge <nBars> <strategy>   — read the first clip on this track, write
//                                analysis JSON, emit run command
//   setFocusSlot <int>         — optionally force a specific clip slot index
//
// Outlets:
//   0: status messages (to UI)
//   1: run command for node.script (as space-separated Max list)
// ─────────────────────────────────────────────────────────────────────────────

inlets  = 1;
outlets = 2;

var focusSlot = -1;  // -1 = auto (first non-empty)

function status(msg) {
    outlet(0, "status", String(msg));
    post(msg + "\n");
}

function setFocusSlot(i) {
    focusSlot = parseInt(i);
    status("focus slot: " + focusSlot);
}

function forge() {
    var args = arrayfromargs(messagename, arguments);
    var nBars = args.length > 1 ? parseInt(args[1]) : 14;
    var strategy = args.length > 2 ? String(args[2]) : "max-diversity";

    try {
        var analysis = extractClipAnalysis();
        if (!analysis) return;

        var audioPath = analysis.file_path;
        if (!audioPath || audioPath === "0" || audioPath === "") {
            status("clip has no file_path — is it an audio clip?");
            return;
        }

        var tmp = writeTempJson(analysis);
        if (!tmp) {
            status("failed to write temp analysis JSON");
            return;
        }

        status("analysis → " + tmp);
        outlet(1, "run", audioPath, tmp, nBars, strategy);
    } catch (e) {
        status("LOM error: " + e);
    }
}

function extractClipAnalysis() {
    var trackPath = "live_set view selected_track";
    var track = new LiveAPI(trackPath);
    if (!track || track.id === "0") {
        status("no selected track");
        return null;
    }

    var slotCount = track.getcount("clip_slots");
    var clip = null;
    var chosen = -1;

    if (focusSlot >= 0) {
        var slot = new LiveAPI(trackPath + " clip_slots " + focusSlot);
        if (getInt(slot, "has_clip") === 1) {
            clip = new LiveAPI(trackPath + " clip_slots " + focusSlot + " clip");
            chosen = focusSlot;
        }
    }

    if (!clip) {
        for (var i = 0; i < slotCount; i++) {
            var s = new LiveAPI(trackPath + " clip_slots " + i);
            if (getInt(s, "has_clip") === 1) {
                clip = new LiveAPI(trackPath + " clip_slots " + i + " clip");
                chosen = i;
                break;
            }
        }
    }

    if (!clip || clip.id === "0") {
        status("no clip found on selected track");
        return null;
    }

    var isAudio = getInt(clip, "is_audio_clip") === 1;
    if (!isAudio) {
        status("slot " + chosen + " clip is not audio");
        return null;
    }

    var warpMarkers = [];
    var fallback = false;
    try {
        var raw = clip.call("get_warp_markers");
        if (raw && raw.length && raw.length >= 2) {
            for (var j = 0; j < raw.length; j += 2) {
                warpMarkers.push({
                    beat_time:   parseFloat(raw[j]),
                    sample_time: parseFloat(raw[j + 1])
                });
            }
        }
    } catch (e) {
        fallback = true;
    }

    var tempo = parseFloat(new LiveAPI("live_set").get("tempo"));
    var sampleRate = getInt(clip, "sample_rate") || 44100;
    var startMarker = parseFloat(clip.get("start_marker"));
    var endMarker   = parseFloat(clip.get("end_marker"));

    if (warpMarkers.length < 2 || fallback) {
        // rigid-grid fallback: derive from clip length + session tempo
        var spb = 60.0 / tempo;
        warpMarkers = [
            { beat_time: startMarker, sample_time: Math.round(startMarker * spb * sampleRate) },
            { beat_time: endMarker,   sample_time: Math.round(endMarker   * spb * sampleRate) }
        ];
        fallback = true;
    }

    var analysis = {
        warp_markers: warpMarkers,
        time_signature: {
            numerator:   getInt(clip, "signature_numerator") || 4,
            denominator: getInt(clip, "signature_denominator") || 4
        },
        tempo: tempo,
        file_path: stringVal(clip.get("file_path")),
        start_marker: startMarker,
        end_marker: endMarker,
        loop_start: parseFloat(clip.get("loop_start")),
        loop_end:   parseFloat(clip.get("loop_end")),
        sample_rate: sampleRate,
        is_warped: getInt(clip, "warping") === 1,
        analysis_fallback: fallback
    };

    status("clip: slot " + chosen + ", " +
           analysis.time_signature.numerator + "/" +
           analysis.time_signature.denominator + " @ " + tempo + " BPM" +
           (fallback ? " [fallback grid]" : ""));
    return analysis;
}

function getInt(api, prop) {
    var v = api.get(prop);
    if (v && typeof v === "object") v = v[0];
    return parseInt(v);
}

function stringVal(v) {
    if (v && typeof v === "object") v = v[0];
    return String(v);
}

function writeTempJson(obj) {
    var tmpDir = toMaxPath("/tmp");
    var name = "stemforge_analysis_" + Date.now() + ".json";
    var posixPath = "/tmp/" + name;
    var maxPath = tmpDir + "/" + name;

    var f = new File(maxPath, "write");
    if (!f.isopen) return null;
    try {
        f.writestring(JSON.stringify(obj));
        f.close();
    } catch (e) {
        try { f.close(); } catch (_e) {}
        return null;
    }
    return posixPath;
}

function toMaxPath(posixPath) {
    var p = String(posixPath);
    if (p.indexOf("/") === 0) return "Macintosh HD:" + p;
    return p;
}
