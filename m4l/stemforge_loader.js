// stemforge_loader.js
// ─────────────────────────────────────────────────────────────────────────────
// Max for Live JavaScript device — StemForge Loader
// Watches ~/stemforge/processed/ for new stems.json files.
// When found:
//   - Sets BPM
//   - Duplicates template tracks for each stem
//   - Renames and recolors the new tracks
//   - Sets device parameters from pipeline config
//   - Loads stem audio into clip slots via create_audio_clip (Live 12+)
//
// Live API path references (all 0-indexed):
//   Song:          live_set
//   Track N:       live_set tracks N
//   ClipSlot N:    live_set tracks T clip_slots S
//   Device on trk: live_set tracks T devices D
//   Device param:  live_set tracks T devices D parameters P
// ─────────────────────────────────────────────────────────────────────────────

inlets = 1;
outlets = 2;   // outlet 0: status text (textedit), outlet 1: bang on load complete

// ── Configuration ─────────────────────────────────────────────────────────────
var PROCESSED_DIR = "";   // set from Max patch via setProcessedDir message
var PIPELINES_DIR = "";   // set from Max patch via setPipelinesDir message
var POLL_INTERVAL = 3000; // ms between folder checks in watch mode
var WARP_MODES    = {
    beats: 0, tones: 1, texture: 2,
    "re-pitch": 3, complex: 4, "complex-pro": 5
};

// State
var lastLoadedManifest = "";
var watchTimer = null;
var isWatching = false;
var pipelineConfig = {};

// ── Entry points called from Max patch ────────────────────────────────────────

function bang() {
    loadLatest();
}

// Load by name: send "load hey_mami" from Max
function load() {
    var args = arrayfromargs(messagename, arguments);
    var name = args.length > 1 ? String(args[1]) : "";
    if (!name) {
        status("Usage: load track_name (e.g. load hey_mami)");
        return;
    }
    if (!PROCESSED_DIR) {
        status("Set processed dir first");
        return;
    }
    var path = PROCESSED_DIR + "/" + String(name) + "/stems.json";
    status("Loading by name: " + name);
    lastLoadedManifest = "";  // reset so it doesn't skip
    loadManifest(path);
}

// Direct load: send "loadFrom /full/path/to/stems.json" from Max
function loadFrom() {
    var path = arrayfromargs(messagename, arguments).slice(1).join(" ");
    if (!path || path === "loadFrom") {
        status("Usage: loadFrom /path/to/stems.json");
        return;
    }
    lastLoadedManifest = "";
    loadManifest(String(path));
}

function reset() {
    lastLoadedManifest = "";
    status("Reset — ready to reload");
}

function loadLatest() {
    if (!PROCESSED_DIR) {
        status("No processed dir set — send setProcessedDir message first");
        return;
    }
    var manifest = findLatestManifest(PROCESSED_DIR);
    if (!manifest) {
        status("No stems.json found in " + PROCESSED_DIR);
        return;
    }
    loadManifest(manifest);
}

function startWatch() {
    if (isWatching) return;
    if (!PROCESSED_DIR) {
        status("Set processed dir first");
        return;
    }
    isWatching = true;
    status("Watching " + PROCESSED_DIR);
    scheduleWatch();
}

function stopWatch() {
    isWatching = false;
    if (watchTimer) { watchTimer.cancel(); watchTimer = null; }
    status("Watch stopped");
}

function setProcessedDir(dir) {
    PROCESSED_DIR = String(dir);
    status("Processed dir: " + PROCESSED_DIR);
}

function setPipelinesDir(dir) {
    PIPELINES_DIR = String(dir);
    status("Pipelines dir: " + PIPELINES_DIR);
}

function loadPipeline(name) {
    var pName = String(name || "default");
    var jsonPath = PIPELINES_DIR + "/" + pName + ".json";
    var raw = readFileContents(jsonPath);
    if (raw === null) {
        status("Pipeline not found: " + jsonPath);
        return;
    }
    try {
        pipelineConfig[pName] = JSON.parse(raw);
        status("Loaded pipeline: " + pName);
    } catch (e) {
        status("Pipeline JSON parse error: " + e);
    }
}

// ── Core: load a stems.json manifest ─────────────────────────────────────────

function loadManifest(manifestPath) {
    status("Loading: " + manifestPath);

    var raw = readFileContents(manifestPath);
    if (raw === null) {
        status("Cannot open: " + manifestPath);
        return;
    }

    var manifest;
    try {
        manifest = JSON.parse(raw);
    } catch (e) {
        status("JSON parse error: " + e);
        return;
    }

    // Set tempo
    setBPM(manifest.bpm);

    // Load pipeline config
    var pName = manifest.pipeline || "default";
    if (!pipelineConfig[pName] && PIPELINES_DIR) {
        loadPipeline(pName);
    }
    var stemConfigs = getPipelineStemConfigs(pName);

    // Process each stem — find existing tracks by matching suffix
    var stemsLoaded = 0;
    var failedLoads = [];

    for (var i = 0; i < manifest.stems.length; i++) {
        var stemInfo = manifest.stems[i];
        if (stemInfo.name === "residual") continue;

        // Find an existing track whose name ends with the stem name
        // e.g., stem "drums" matches "SF | Drums Raw", "My Track | drums", etc.
        var trackIndex = findTrackBySuffix(stemInfo.name);
        if (trackIndex < 0) {
            status("  No track found ending with '" + stemInfo.name + "' — skipping");
            failedLoads.push(stemInfo.name + " (no matching track)");
            continue;
        }

        var trackAPI = new LiveAPI("live_set tracks " + trackIndex);
        var trackName = trackAPI.get("name");
        trackName = (trackName && typeof trackName === "object")
                    ? trackName[0] : String(trackName);

        status("Stem: " + stemInfo.name + " → " + trackName);

        // Apply effect parameters from pipeline config
        var stemConfig = stemConfigs ? stemConfigs[stemInfo.name] : null;
        if (stemConfig && stemConfig.effects) {
            applyEffects(trackIndex, stemConfig.effects);
        }

        // Load audio into first empty clip slot via create_audio_clip
        if (stemInfo.wav_path) {
            var slotIndex = findEmptyClipSlot(trackIndex);
            if (slotIndex < 0) {
                status("  No empty clip slot on " + trackName);
                failedLoads.push(stemInfo.name + " → " + trackName + " (no empty slot)");
            } else {
                try {
                    var csPath = "live_set tracks " + trackIndex + " clip_slots " + slotIndex;
                    var csAPI = new LiveAPI(csPath);
                    csAPI.call("create_audio_clip", String(stemInfo.wav_path));

                    // Name the clip: song_name-stem_part
                    var clipPath = csPath + " clip";
                    var clipAPI = new LiveAPI(clipPath);
                    if (clipAPI.id !== "0") {
                        var clipName = manifest.track_name + "-" + stemInfo.name;
                        clipAPI.set("name", clipName);

                        // Enable warping and set warp mode from pipeline
                        clipAPI.set("warping", 1);
                        var stemConfig2 = stemConfigs ? stemConfigs[stemInfo.name] : null;
                        if (stemConfig2 && stemConfig2.warp_mode !== undefined) {
                            var wm = WARP_MODES[stemConfig2.warp_mode];
                            if (wm !== undefined) {
                                clipAPI.set("warp_mode", wm);
                            }
                        }
                        clipAPI.set("looping", 1);
                    }

                    status("  Loaded: " + clipName + " → slot " + slotIndex);
                } catch (e) {
                    status("  Auto-load failed: " + e);
                    failedLoads.push(stemInfo.name + " → " + trackName);
                }
            }
        }

        stemsLoaded++;
    }

    status("──────────────────────────────────");
    status("Loaded " + stemsLoaded + " stems — " +
           manifest.track_name + " @ " + manifest.bpm + " BPM");

    if (failedLoads.length > 0) {
        status("──────────────────────────────────");
        status("These stems need manual drag from Browser:");
        for (var d = 0; d < failedLoads.length; d++) {
            status("  " + failedLoads[d]);
        }
    }

    outlet(1, "bang");
}

// ── Live API helpers ──────────────────────────────────────────────────────────

function setBPM(bpm) {
    var api = new LiveAPI("live_set");
    api.set("tempo", bpm);
    status("Tempo → " + bpm + " BPM");
}

function getTrackCount() {
    var api = new LiveAPI("live_set");
    return api.getcount("tracks");
}

function findTrackByName(name) {
    var count = getTrackCount();
    for (var i = 0; i < count; i++) {
        var api = new LiveAPI("live_set tracks " + i);
        var trackName = api.get("name");
        var tName = (trackName && typeof trackName === "object")
                    ? trackName[0] : String(trackName);
        if (tName === name) {
            return i;
        }
    }
    return -1;
}

function findTrackBySuffix(stemName) {
    // Find a track whose name ends with the stem name (case-insensitive)
    // e.g., stemName "drums" matches "SF | Drums Raw" won't work directly,
    // so we also check common patterns:
    //   - track name ends with stemName
    //   - track name contains stemName as a word (after | or space)
    var target = stemName.toLowerCase();
    var count = getTrackCount();
    for (var i = 0; i < count; i++) {
        var api = new LiveAPI("live_set tracks " + i);
        var raw = api.get("name");
        var tName = (raw && typeof raw === "object") ? raw[0] : String(raw);
        var lower = tName.toLowerCase();

        // Check: name ends with stem name
        if (lower.lastIndexOf(target) === lower.length - target.length && lower.length >= target.length) {
            return i;
        }
        // Check: "| drums" or "| drum" pattern
        if (lower.indexOf("| " + target) >= 0) {
            return i;
        }
        // Check: stem name appears after last space or pipe
        var parts = lower.split(/[\|\s]+/);
        var lastWord = parts[parts.length - 1];
        if (lastWord === target) {
            return i;
        }
    }

    // Second pass: looser match — stem name anywhere in track name
    // Handles "SF | Drums Raw" matching "drums"
    var STEM_TRACK_MAP = {
        "drums": ["drums", "drum"],
        "drum":  ["drums", "drum"],
        "bass":  ["bass"],
        "vocals": ["vocals", "vocal"],
        "other": ["texture", "other"],
        "guitar": ["guitar"],
        "electricguitar": ["guitar"],
        "piano": ["piano"],
        "synthesizer": ["synth", "texture"]
    };
    var candidates = STEM_TRACK_MAP[target] || [target];

    for (var i = 0; i < count; i++) {
        var api2 = new LiveAPI("live_set tracks " + i);
        var raw2 = api2.get("name");
        var tName2 = (raw2 && typeof raw2 === "object") ? raw2[0] : String(raw2);
        var lower2 = tName2.toLowerCase();

        for (var c = 0; c < candidates.length; c++) {
            if (lower2.indexOf(candidates[c]) >= 0) {
                return i;
            }
        }
    }

    return -1;
}

function findEmptyClipSlot(trackIndex) {
    var track = new LiveAPI("live_set tracks " + trackIndex);
    var slotCount;
    try {
        slotCount = track.getcount("clip_slots");
    } catch (e) {
        return 0;  // fallback to slot 0
    }
    for (var s = 0; s < slotCount; s++) {
        var cs = new LiveAPI("live_set tracks " + trackIndex + " clip_slots " + s);
        var hasClip = cs.get("has_clip");
        var occupied = (hasClip && (hasClip[0] === 1 || hasClip[0] === true));
        if (!occupied) return s;
    }
    return -1;  // all slots full
}

function duplicateTemplate(templateName) {
    var templateIndex = findTrackByName(templateName);
    if (templateIndex < 0) return -1;

    var songAPI = new LiveAPI("live_set");
    songAPI.call("duplicate_track", templateIndex);

    // duplicate_track inserts the new track at templateIndex + 1
    return templateIndex + 1;
}

function setTrackName(trackIndex, name) {
    var api = new LiveAPI("live_set tracks " + trackIndex);
    api.set("name", name);
}

function setTrackColor(trackIndex, color) {
    var api = new LiveAPI("live_set tracks " + trackIndex);
    api.set("color", color);
}

function applyEffects(trackIndex, effects) {
    for (var d = 0; d < effects.length; d++) {
        var effect = effects[d];
        var deviceIndex = effect.device;
        var params = effect.params;
        if (!params) continue;

        var devicePath = "live_set tracks " + trackIndex +
                         " devices " + deviceIndex;
        var deviceAPI;
        try {
            deviceAPI = new LiveAPI(devicePath);
        } catch (e) {
            continue;
        }
        if (!deviceAPI || deviceAPI.id === "0") continue;

        var paramCount;
        try {
            paramCount = deviceAPI.getcount("parameters");
        } catch (e) {
            continue;
        }

        // Match parameters by name
        var paramKeys = Object.keys(params);
        for (var p = 0; p < paramCount; p++) {
            var paramPath = devicePath + " parameters " + p;
            var paramAPI;
            try {
                paramAPI = new LiveAPI(paramPath);
            } catch (e) {
                continue;
            }
            var rawName = paramAPI.get("name");
            var pName = (rawName && typeof rawName === "object")
                        ? rawName[0] : String(rawName);

            for (var k = 0; k < paramKeys.length; k++) {
                if (pName === paramKeys[k]) {
                    try {
                        paramAPI.set("value", params[paramKeys[k]]);
                    } catch (e) {
                        status("  Param error: " + pName + " — " + e);
                    }
                    break;
                }
            }
        }
    }
}

function loadBestBeatSlice(manifest) {
    // Find the drums stem
    var drumsStem = null;
    for (var i = 0; i < manifest.stems.length; i++) {
        if (manifest.stems[i].name === "drums" ||
            manifest.stems[i].name === "drum") {
            drumsStem = manifest.stems[i];
            break;
        }
    }
    if (!drumsStem || !drumsStem.beats_dir) return;

    var simplerIndex = findTrackByName("SF | Beat Chop Simpler");
    if (simplerIndex < 0) return;

    var newIndex = duplicateTemplate("SF | Beat Chop Simpler");
    if (newIndex < 0) return;

    setTrackName(newIndex, manifest.track_name + " | chop");
    setTrackColor(newIndex, 0xFF2400);

    var beatFile = drumsStem.name + "_beat_001.wav";
    status("  Drag " + beatFile + " into Simpler on: " +
           manifest.track_name + " | chop");
}

// ── File watching ─────────────────────────────────────────────────────────────

function findLatestManifest(baseDir) {
    // Try reading a manifest index written by the CLI.
    // The CLI writes processed/{track}/stems.json — we read processed/index.json
    // which lists all track names. If that doesn't exist, try the Folder API
    // as a fallback, then give up with a helpful message.

    var newest = null;
    var newestTime = 0;

    // Strategy 1: read index.json (written by CLI)
    var indexPath = baseDir + "/index.json";
    var indexContent = readFileContents(indexPath);
    if (indexContent) {
        try {
            var trackNames = JSON.parse(indexContent);
            for (var i = 0; i < trackNames.length; i++) {
                var mp = baseDir + "/" + trackNames[i] + "/stems.json";
                var found = tryManifest(mp);
                if (found && found.time > newestTime) {
                    newestTime = found.time;
                    newest = mp;
                }
            }
            if (newest) return newest;
        } catch (e) {}
    }

    // Strategy 2: Folder API (needs Max path format)
    try {
        var folder = new Folder(toMaxPath(baseDir));
        folder.reset();
        while (!folder.end) {
            var entry = folder.filename;
            if (entry && entry !== "." && entry !== "..") {
                var mp2 = baseDir + "/" + entry + "/stems.json";
                var found2 = tryManifest(mp2);
                if (found2 && found2.time > newestTime) {
                    newestTime = found2.time;
                    newest = mp2;
                }
            }
            folder.next();
        }
        folder.close();
        if (newest) return newest;
    } catch (e) {
        status("  Folder scan failed: " + e);
    }

    // Strategy 3: give up with instructions
    status("  Auto-scan could not find manifests.");
    status("  Use loadFrom: send 'loadFrom " + baseDir + "/TRACKNAME/stems.json' to [js]");
    return null;
}

function tryManifest(path) {
    var content = readFileContents(path);
    if (!content) return null;
    try {
        var parsed = JSON.parse(content);
        if (parsed.processed_at) {
            return { time: new Date(parsed.processed_at).getTime() };
        }
        // No processed_at — still valid, use time 1
        return { time: 1 };
    } catch (e) {
        return null;
    }
}

function scheduleWatch() {
    if (!isWatching) return;
    watchTimer = new Task(function () {
        var manifest = findLatestManifest(PROCESSED_DIR);
        if (manifest && manifest !== lastLoadedManifest) {
            status("New stems detected!");
            loadManifest(manifest);
        }
        scheduleWatch();
    }, this);
    watchTimer.schedule(POLL_INTERVAL);
}

// ── Utility ───────────────────────────────────────────────────────────────────

function toMaxPath(posixPath) {
    // Max on macOS needs "Macintosh HD:/Users/..." not "/Users/..."
    var p = String(posixPath);
    if (p.indexOf("/") === 0) {
        return "Macintosh HD:" + p;
    }
    return p;
}

function readFileContents(path) {
    var maxPath = toMaxPath(path);
    var f = new File(maxPath, "read");
    if (!f.isopen) return null;
    var raw = "";
    while (f.position < f.eof) {
        raw += f.readstring(65536);
    }
    f.close();
    return raw;
}

function getPipelineStemConfigs(pName) {
    var config = pipelineConfig[pName];
    if (!config) return null;
    if (config.pipelines && config.pipelines[pName]) {
        return config.pipelines[pName].stems || null;
    }
    // Try top-level stems key
    return config.stems || null;
}

function status(msg) {
    outlet(0, "set", msg);
    post(msg + "\n");
}
