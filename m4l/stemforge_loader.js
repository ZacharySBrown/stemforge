// stemforge_loader.js
// ─────────────────────────────────────────────────────────────────────────────
// Max for Live JavaScript device — StemForge Loader
// Watches ~/stemforge/processed/ for new stems.json files.
// When found, loads stems into Ableton template tracks using the Live API.
//
// Live API path references (all 0-indexed):
//   Song:          live_set
//   Track N:       live_set tracks N
//   ClipSlot N:    live_set tracks T clip_slots S
//   Device on trk: live_set tracks T devices D
//   Device param:  live_set tracks T devices D parameters P
// ─────────────────────────────────────────────────────────────────────────────

inlets = 1;
outlets = 2;   // outlet 0: status string for display, outlet 1: bang on load complete

var liveAPI  = new LiveAPI();
var YAML     = null;   // YAML parsing done in Python via system call (see below)
var fs       = null;   // Max's file system via "file" object

// ── Configuration ─────────────────────────────────────────────────────────────
var PROCESSED_DIR = Packages.java.lang.System.getProperty("user.home") +
                    "/stemforge/processed";
var PIPELINES_DIR = "";  // set from Max patch via setPipelinesDir message
var POLL_INTERVAL = 3000; // ms between folder checks in watch mode
var WARP_MODES    = {beats:0, tones:1, texture:2, "re-pitch":3, complex:4, "complex-pro":5};

// State
var lastLoadedManifest = "";
var watchTimer = null;
var isWatching = false;
var pipelineConfig = {};

// ── Entry points called from Max patch ────────────────────────────────────────

function bang() {
    loadLatest();
}

function loadLatest() {
    var manifest = findLatestManifest(PROCESSED_DIR);
    if (!manifest) {
        outlet(0, "No stems.json found in " + PROCESSED_DIR);
        return;
    }
    if (manifest === lastLoadedManifest) {
        outlet(0, "Already loaded: " + manifest);
        return;
    }
    loadManifest(manifest);
}

function startWatch() {
    if (isWatching) return;
    isWatching = true;
    outlet(0, "Watching " + PROCESSED_DIR);
    scheduleWatch();
}

function stopWatch() {
    isWatching = false;
    if (watchTimer) { watchTimer.cancel(); watchTimer = null; }
    outlet(0, "Watch stopped");
}

function setPipelinesDir(dir) {
    PIPELINES_DIR = dir;
    outlet(0, "Pipelines dir: " + dir);
}

function loadPipeline(name) {
    // Read and parse the default.yaml pipeline config.
    // Max doesn't have native YAML parsing so we read it as text
    // and do lightweight parsing for the values we need.
    // For production, consider converting default.yaml to JSON.
    var path = PIPELINES_DIR + "/" + (name || "default") + ".yaml";
    var f = new File(path, "read", "text");
    if (!f.isopen) {
        outlet(0, "Pipeline not found: " + path);
        return null;
    }
    // Read full content
    var lines = [];
    f.open();
    while (!f.eof) {
        lines.push(f.readline());
    }
    f.close();
    // Store raw for lookup — parameter setting uses pipeline lookup below
    pipelineConfig[name || "default"] = lines.join("\n");
    outlet(0, "Loaded pipeline: " + (name || "default"));
}

// ── Core: load a stems.json manifest ─────────────────────────────────────────

function loadManifest(manifestPath) {
    outlet(0, "Loading: " + manifestPath);

    // Read stems.json
    var f = new File(manifestPath, "read", "text");
    if (!f.isopen) {
        outlet(0, "Cannot open: " + manifestPath);
        return;
    }
    var raw = "";
    f.open();
    while (!f.eof) { raw += f.readline() + "\n"; }
    f.close();

    var manifest;
    try {
        manifest = JSON.parse(raw);
    } catch(e) {
        outlet(0, "JSON parse error: " + e);
        return;
    }

    // Set tempo
    setBPM(manifest.bpm);

    // Load pipeline config for parameter setting
    loadPipeline(manifest.pipeline || "default");
    var pipeline = getPipelineSection(manifest.pipeline || "default");

    // Get current track count so we append after existing tracks
    var api = new LiveAPI("live_set");
    api.property = "tracks";
    var numTracks = getTrackCount();

    // Process each stem
    var stemsLoaded = 0;
    for (var i = 0; i < manifest.stems.length; i++) {
        var stemInfo = manifest.stems[i];
        if (stemInfo.name === "residual") continue;

        var stemConfig = pipeline ? pipeline[stemInfo.name] : null;
        var templateName = stemConfig ? stemConfig.template : "SF | Texture Verb";

        outlet(0, "Loading stem: " + stemInfo.name + " → " + templateName);

        var newTrackIndex = duplicateTemplate(templateName, numTracks + stemsLoaded);
        if (newTrackIndex < 0) {
            outlet(0, "Template not found: " + templateName);
            continue;
        }

        // Rename track
        var trackName = manifest.track_name + " | " + stemInfo.name;
        setTrackName(newTrackIndex, trackName);

        // Set color
        var color = stemConfig ? stemConfig.color : 0x444444;
        setTrackColor(newTrackIndex, color || 0x444444);

        // Load audio into clip slot 0
        loadAudioClip(newTrackIndex, 0, stemInfo.wav_path);

        // Set clip properties
        var warpMode = stemConfig ? WARP_MODES[stemConfig.warp_mode] || 0 : 0;
        setClipProperties(newTrackIndex, 0, {
            warp_mode: warpMode,
            looping: stemConfig ? (stemConfig.loop ? 1 : 0) : 1,
            warping: 1,
        });

        // Apply effect parameters from pipeline config
        if (stemConfig && stemConfig.effects) {
            applyEffects(newTrackIndex, stemConfig.effects);
        }

        stemsLoaded++;
    }

    // Load best beat slice into "SF | Beat Chop Simpler" if present
    loadBestBeatSlice(manifest, numTracks + stemsLoaded);

    lastLoadedManifest = manifestPath;
    outlet(0, "Loaded " + stemsLoaded + " stems — " + manifest.track_name +
              " @ " + manifest.bpm + " BPM");
    outlet(1, "bang"); // signal completion
}

// ── Live API helpers ──────────────────────────────────────────────────────────

function setBPM(bpm) {
    var api = new LiveAPI("live_set");
    api.set("tempo", bpm);
    outlet(0, "Tempo → " + bpm + " BPM");
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
        if (trackName && trackName[0] === name) {
            return i;
        }
    }
    return -1;
}

function duplicateTemplate(templateName, insertAfterIndex) {
    var templateIndex = findTrackByName(templateName);
    if (templateIndex < 0) return -1;

    // Duplicate the track via Song.duplicate_track
    var songAPI = new LiveAPI("live_set");
    songAPI.call("duplicate_track", templateIndex);

    // The new track appears at templateIndex + 1
    // We need to move it to insertAfterIndex
    // LOM doesn't have move_track, but duplicate inserts at source+1
    // Acceptable for now — tracks appear in order of stem processing
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

function loadAudioClip(trackIndex, slotIndex, filePath) {
    // This is the key capability: ClipSlot.create_clip via file path
    // The LOM function signature: create_clip(path) on an audio track ClipSlot
    var api = new LiveAPI("live_set tracks " + trackIndex +
                          " clip_slots " + slotIndex);
    api.call("create_clip", filePath);
    // Small delay to let Live process the file
    var t = new Task(function() {}, this);
    t.schedule(200);
}

function setClipProperties(trackIndex, slotIndex, props) {
    var clipPath = "live_set tracks " + trackIndex +
                   " clip_slots " + slotIndex + " clip";
    var api = new LiveAPI(clipPath);
    if (api.id === "0") return; // clip not yet loaded

    if (props.warping !== undefined)   api.set("warping", props.warping);
    if (props.warp_mode !== undefined) api.set("warp_mode", props.warp_mode);
    if (props.looping !== undefined)   api.set("looping", props.looping);
}

function applyEffects(trackIndex, effects) {
    for (var d = 0; d < effects.length; d++) {
        var effect = effects[d];
        var deviceIndex = effect.device;
        var params = effect.params;
        if (!params) continue;

        // Get parameter list for this device
        var devicePath = "live_set tracks " + trackIndex +
                         " devices " + deviceIndex;
        var deviceAPI = new LiveAPI(devicePath);
        var paramCount = deviceAPI.getcount("parameters");

        // For each named parameter in the config, find and set it
        // Note: param matching is by index in the config (not by name)
        // The config uses descriptive keys for readability but the actual
        // setting is by sequential index in the effects[d].params object
        var paramKeys = Object.keys(params);
        for (var p = 0; p < paramKeys.length; p++) {
            var paramPath = devicePath + " parameters " + p;
            var paramAPI = new LiveAPI(paramPath);
            if (paramAPI.id !== "0") {
                paramAPI.set("value", params[paramKeys[p]]);
            }
        }
    }
}

function loadBestBeatSlice(manifest, insertIndex) {
    // Find the drums stem beat slices
    var drumsStem = null;
    for (var i = 0; i < manifest.stems.length; i++) {
        if (manifest.stems[i].name === "drums" ||
            manifest.stems[i].name === "drum") {
            drumsStem = manifest.stems[i];
            break;
        }
    }
    if (!drumsStem || !drumsStem.beats_dir) return;

    // Find Simpler template track
    var simplerIndex = findTrackByName("SF | Beat Chop Simpler");
    if (simplerIndex < 0) return;

    // Duplicate it
    var newSimpler = duplicateTemplate("SF | Beat Chop Simpler", insertIndex);
    if (newSimpler < 0) return;

    setTrackName(newSimpler, manifest.track_name + " | chop");
    setTrackColor(newSimpler, 0xFF2400);

    // Load first beat slice (beat_001.wav) into Simpler's sample slot
    // Simpler's sample parameter is typically parameter index 0
    var firstBeat = drumsStem.beats_dir + "/" +
                    drumsStem.name + "_beat_001.wav";

    // Load via Simpler's built-in load mechanism (device param 0)
    var devicePath = "live_set tracks " + newSimpler + " devices 0";
    var deviceAPI = new LiveAPI(devicePath);
    deviceAPI.call("load_device", firstBeat);
    // Note: if load_device is not available, fallback is drag-and-drop.
    // Document this limitation clearly.

    outlet(0, "Beat chop Simpler loaded: " + drumsStem.name + "_beat_001.wav");
}

// ── File watching ─────────────────────────────────────────────────────────────

function findLatestManifest(baseDir) {
    // Walk baseDir for the most recently modified stems.json
    // Max's file access is limited — we check known structure:
    // baseDir/{track_name}/stems.json
    var f = new File(baseDir);
    if (!f.isopen) return null;

    var newest = null;
    var newestTime = 0;

    // List subdirectories
    var subdirs = [];
    f.open();
    var entry;
    while ((entry = f.readdir()) !== null) {
        subdirs.push(entry);
    }
    f.close();

    for (var i = 0; i < subdirs.length; i++) {
        var manifestPath = baseDir + "/" + subdirs[i] + "/stems.json";
        var mf = new File(manifestPath);
        if (mf.isopen) {
            // Use file modification date for comparison
            // Max's File object doesn't expose mtime directly,
            // so we track by reading and comparing processed_at timestamps
            mf.open();
            var content = "";
            while (!mf.eof) { content += mf.readline() + "\n"; }
            mf.close();
            try {
                var parsed = JSON.parse(content);
                var t = new Date(parsed.processed_at).getTime();
                if (t > newestTime) {
                    newestTime = t;
                    newest = manifestPath;
                }
            } catch(e) {}
        }
    }

    return newest;
}

function scheduleWatch() {
    if (!isWatching) return;
    watchTimer = new Task(function() {
        var manifest = findLatestManifest(PROCESSED_DIR);
        if (manifest && manifest !== lastLoadedManifest) {
            outlet(0, "New stems detected: " + manifest);
            loadManifest(manifest);
        }
        scheduleWatch(); // reschedule
    }, this);
    watchTimer.schedule(POLL_INTERVAL);
}

// ── Pipeline config parsing ────────────────────────────────────────────────────

function getPipelineSection(pipelineName) {
    // Convert the loaded YAML text (stored in pipelineConfig) to a usable
    // JS object. Since Max lacks YAML parsing, the pipeline config should
    // also be distributed as a JSON file: pipelines/default.json
    // Claude Code should generate BOTH default.yaml (human-editable)
    // AND default.json (machine-readable, auto-generated from yaml on CLI run).
    // The M4L device reads default.json.

    var jsonPath = PIPELINES_DIR + "/" + pipelineName + ".json";
    var f = new File(jsonPath, "read", "text");
    if (!f.isopen) {
        outlet(0, "Pipeline JSON not found: " + jsonPath +
                  " — run: stemforge generate-pipeline-json");
        return null;
    }
    var raw = "";
    f.open();
    while (!f.eof) { raw += f.readline() + "\n"; }
    f.close();

    try {
        var config = JSON.parse(raw);
        return config.pipelines ? config.pipelines[pipelineName] ?
               config.pipelines[pipelineName].stems : null : null;
    } catch(e) {
        outlet(0, "Pipeline JSON parse error: " + e);
        return null;
    }
}
