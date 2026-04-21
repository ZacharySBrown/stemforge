// stemforge_param_scraper.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] — enumerates all native Live device parameters.
// Inserts each device, reads parameters (name, min, max, default, quantized,
// value_items), deletes device, moves to next. Outputs JSON reference file.
//
// Setup:
//   1. Create blank Live set with 2 tracks:
//      - Audio track named "SF_Scraper_Audio"
//      - MIDI track named "SF_Scraper_MIDI" (with Simpler or any instrument)
//   2. Insert this device on any track
//   3. Send "scrapeAll", "scrapeAudio", or "scrapeMidi" message
//
// Output: ~/Documents/StemForge/live_devices.json
// ─────────────────────────────────────────────────────────────────────────────

/* global LiveAPI, File, Task, Dict, post, outlet, arrayfromargs, messagename */

autowatch = 1;
inlets = 1;
outlets = 1;  // 0: status text

// ── Device lists ─────────────────────────────────────────────────────────────

var AUDIO_EFFECTS = [
    "Amp",
    "Auto Filter",
    "Auto Pan",
    "Beat Repeat",
    "Cabinet",
    "Channel EQ",
    "Chorus-Ensemble",
    "Compressor",
    "Corpus",
    "Delay",
    "Drum Buss",
    "Dynamic Tube",
    "Echo",
    "EQ Eight",
    "EQ Three",
    "Erosion",
    "External Audio Effect",
    "Filter Delay",
    "Frequency Shifter",
    "Gate",
    "Glue Compressor",
    "Grain Delay",
    "Hybrid Reverb",
    "Limiter",
    "Looper",
    "Multiband Dynamics",
    "Overdrive",
    "Pedal",
    "Phaser-Flanger",
    "Redux",
    "Resonators",
    "Reverb",
    "Roar",
    "Saturator",
    "Shifter",
    "Simple Delay",
    "Spectral Blur",
    "Spectral Resonator",
    "Spectrum",
    "Tuner",
    "Utility",
    "Vinyl Distortion",
    "Vocoder"
];

var MIDI_EFFECTS = [
    "Arpeggiator",
    "Chord",
    "CC Control",
    "Envelope",
    "Envelope Follower",
    "Expression Control",
    "LFO",
    "MIDI Monitor",
    "Note Echo",
    "Note Length",
    "Pitch",
    "Random",
    "Scale",
    "Shaper",
    "Velocity"
];

// ── State ────────────────────────────────────────────────────────────────────

var _result = null;
var _queue = [];
var _currentIdx = 0;
var _totalDevices = 0;
var _task = null;
var _outputPath = "";

// ── Helpers ──────────────────────────────────────────────────────────────────

function status(msg) {
    try { outlet(0, "set", String(msg)); } catch (_) {}
    post("[scraper] " + msg + "\n");
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

function getLiveVersion() {
    var app = new LiveAPI("live_app");
    var major, minor, bugfix;
    try {
        major = app.get("major_version");
        major = (major && typeof major === "object") ? major[0] : major;
        minor = app.get("minor_version");
        minor = (minor && typeof minor === "object") ? minor[0] : minor;
        bugfix = app.get("bugfix_version");
        bugfix = (bugfix && typeof bugfix === "object") ? bugfix[0] : bugfix;
    } catch (e) {
        return "unknown";
    }
    return major + "." + minor + "." + bugfix;
}

function toMaxPath(posixPath) {
    if (posixPath.charAt(0) === "/") return "Macintosh HD:" + posixPath;
    return posixPath;
}

function ensureDirectory(posixPath) {
    // Max File API can't create directories, but we can try opening a file
    // in write mode — it will create the file (not the directory).
    // The user must ensure ~/Documents/StemForge/ exists.
    // We'll try to create it via a workaround.
    var parts = posixPath.split("/");
    parts.pop(); // remove filename
    var dir = parts.join("/");
    // Use Max's Folder object to check/create
    try {
        var folder = new Folder(toMaxPath(dir));
        if (!folder.typelist) {
            // Folder doesn't exist — we can't create it from Max [js]
            // Log a warning; user must create it manually
            post("[scraper] WARNING: directory may not exist: " + dir + "\n");
        }
        folder.close();
    } catch (_) {}
}

function writeJsonFile(posixPath, data) {
    var jsonStr = JSON.stringify(data, null, 2);
    var maxPath = toMaxPath(posixPath);

    var f = new File(maxPath, "write", "TEXT");
    if (!f.isopen) {
        status("ERROR: cannot open file for writing: " + posixPath);
        return false;
    }

    // Max File.writestring has a 32KB buffer limit.
    // Write in chunks to handle large JSON output.
    var CHUNK_SIZE = 16000;
    var offset = 0;
    while (offset < jsonStr.length) {
        var chunk = jsonStr.substring(offset, offset + CHUNK_SIZE);
        f.writestring(chunk);
        offset += CHUNK_SIZE;
    }

    f.close();
    status("Wrote " + jsonStr.length + " bytes to " + posixPath);
    return true;
}

// ── Core scraper ─────────────────────────────────────────────────────────────

function scrapeDevice(trackIdx, deviceName) {
    var track = new LiveAPI("live_set tracks " + trackIdx);

    // Count devices before insertion
    var countBefore = track.getcount("devices");

    // Insert device
    try {
        track.call("insert_device", deviceName, countBefore);
    } catch (e) {
        return { error: "insert_device failed: " + e };
    }

    // Verify insertion
    var countAfter = track.getcount("devices");
    if (countAfter <= countBefore) {
        return { error: "insert_device returned but device count unchanged" };
    }
    var deviceIdx = countAfter - 1;

    // Get device info
    var device = new LiveAPI("live_set tracks " + trackIdx + " devices " + deviceIdx);
    var className = device.get("class_name");
    className = (className && typeof className === "object") ? String(className[0]) : String(className);

    var paramCount = device.getcount("parameters");

    // Enumerate parameters
    var params = [];
    for (var i = 0; i < paramCount; i++) {
        var paramPath = "live_set tracks " + trackIdx + " devices " + deviceIdx + " parameters " + i;
        var p = new LiveAPI(paramPath);

        var pName = p.get("name");
        pName = (pName && typeof pName === "object") ? String(pName[0]) : String(pName);

        var origName = p.get("original_name");
        origName = (origName && typeof origName === "object") ? String(origName[0]) : String(origName);

        var pMin = p.get("min");
        pMin = (pMin && typeof pMin === "object") ? Number(pMin[0]) : Number(pMin);

        var pMax = p.get("max");
        pMax = (pMax && typeof pMax === "object") ? Number(pMax[0]) : Number(pMax);

        var pValue = p.get("value");
        pValue = (pValue && typeof pValue === "object") ? Number(pValue[0]) : Number(pValue);

        var pDefault;
        try {
            pDefault = p.get("default_value");
            pDefault = (pDefault && typeof pDefault === "object") ? Number(pDefault[0]) : Number(pDefault);
            // 5e-324 means "no default available" — use current value instead
            if (pDefault < 1e-300) pDefault = pValue;
        } catch (_) {
            pDefault = pValue;
        }

        var isQuantized = p.get("is_quantized");
        isQuantized = (isQuantized && typeof isQuantized === "object") ? (isQuantized[0] === 1) : (isQuantized === 1);

        // Get value_items for quantized params (enum labels)
        // Use call("str_for_value", val) — it's a method, not a property
        var valueItems = null;
        if (isQuantized) {
            var numItems = Math.round(pMax - pMin) + 1;
            if (numItems > 0 && numItems <= 64) {
                valueItems = [];
                for (var vi = 0; vi < numItems; vi++) {
                    try {
                        var strVal = p.call("str_for_value", pMin + vi);
                        strVal = (strVal && typeof strVal === "object") ? String(strVal[0]) : String(strVal);
                        if (strVal && strVal !== "undefined" && strVal !== "") {
                            valueItems.push(strVal);
                        } else {
                            valueItems.push(String(pMin + vi));
                        }
                    } catch (_) {
                        valueItems.push(String(pMin + vi));
                    }
                }
                if (valueItems.length === 0) valueItems = null;
            }
        }

        params.push({
            index: i,
            name: pName,
            original_name: origName,
            min: pMin,
            max: pMax,
            default_value: pDefault,
            current_value: pValue,
            is_quantized: isQuantized,
            value_items: valueItems
        });
    }

    // Delete the device we inserted
    try {
        track.call("delete_device", deviceIdx);
    } catch (e) {
        post("[scraper] WARNING: could not delete device " + deviceName + ": " + e + "\n");
    }

    return {
        class_name: className,
        parameters: params
    };
}

// ── Queue-based orchestration (using Task for timing) ────────────────────────

function processNext() {
    if (_currentIdx >= _queue.length) {
        // Done — write output
        finishScrape();
        return;
    }

    var item = _queue[_currentIdx];
    var deviceName = item.name;
    var trackIdx = item.trackIdx;
    var category = item.category;

    status("Scraping: " + deviceName + " [" + (_currentIdx + 1) + "/" + _totalDevices + "]");

    var scraped = scrapeDevice(trackIdx, deviceName);

    if (scraped.error) {
        _result.errors[deviceName] = scraped.error;
        post("[scraper] ERROR on " + deviceName + ": " + scraped.error + "\n");
    } else {
        var entry = {
            class_name: scraped.class_name,
            category: category,
            parameters: scraped.parameters
        };
        if (category === "audio_effect") {
            _result.audio_effects[deviceName] = entry;
        } else {
            _result.midi_effects[deviceName] = entry;
        }
    }

    _currentIdx++;

    // Schedule next device with a brief delay for Live to settle
    _task = new Task(processNext, this);
    _task.schedule(100);
}

function finishScrape() {
    // Sort keys alphabetically
    _result.audio_effects = sortKeys(_result.audio_effects);
    _result.midi_effects = sortKeys(_result.midi_effects);
    _result.errors = sortKeys(_result.errors);

    var audioCount = Object.keys(_result.audio_effects).length;
    var midiCount = Object.keys(_result.midi_effects).length;
    var errorCount = Object.keys(_result.errors).length;

    // Clean up scraper tracks
    cleanupScraperTracks();

    // Write JSON
    var success = writeJsonFile(_outputPath, _result);

    if (success) {
        status("Done! " + audioCount + " audio + " + midiCount + " MIDI devices. " + errorCount + " errors. → " + _outputPath);
    } else {
        status("Scrape complete but file write failed. Check console.");
    }
}

function cleanupScraperTracks() {
    // Delete tracks we created (find by name, delete in reverse order)
    var liveSet = new LiveAPI("live_set");
    var n = trackCount();
    for (var i = n - 1; i >= 0; i--) {
        var name = trackName(i);
        if (name === "_SF_Scraper_Audio" || name === "_SF_Scraper_MIDI") {
            try {
                liveSet.call("delete_track", i);
                post("[scraper] Cleaned up track: " + name + "\n");
            } catch (_) {}
        }
    }
}

function sortKeys(obj) {
    var keys = [];
    for (var k in obj) {
        if (obj.hasOwnProperty(k)) keys.push(k);
    }
    keys.sort();
    var sorted = {};
    for (var i = 0; i < keys.length; i++) {
        sorted[keys[i]] = obj[keys[i]];
    }
    return sorted;
}

// ── Entry points ─────────────────────────────────────────────────────────────

function scrapeAll() {
    startScrape("all");
}

function scrapeAudio() {
    startScrape("audio");
}

function scrapeMidi() {
    startScrape("midi");
}

function setOutputPath() {
    var args = arrayfromargs(messagename, arguments);
    if (args.length > 1) {
        _outputPath = args.slice(1).join(" ");
        status("Output path: " + _outputPath);
    }
}

function findOrCreateAudioTrack() {
    // Create a fresh audio track at end of session for scraping
    var n = trackCount();
    var liveSet = new LiveAPI("live_set");
    liveSet.call("create_audio_track", n);
    var idx = trackCount() - 1;
    var t = new LiveAPI("live_set tracks " + idx);
    t.set("name", "_SF_Scraper_Audio");
    post("[scraper] Created audio track at index " + idx + "\n");
    return idx;
}

function findOrCreateMidiTrack() {
    // Create a fresh MIDI track with Simpler for scraping
    var n = trackCount();
    var liveSet = new LiveAPI("live_set");
    liveSet.call("create_midi_track", n);
    var idx = trackCount() - 1;
    var t = new LiveAPI("live_set tracks " + idx);
    t.set("name", "_SF_Scraper_MIDI");
    // Insert Simpler so MIDI effects can be added
    t.call("insert_device", "Simpler", 0);
    post("[scraper] Created MIDI track with Simpler at index " + idx + "\n");
    return idx;
}

function startScrape(mode) {
    // Create dedicated scraper tracks (cleaned up after)
    var audioTrackIdx = -1;
    var midiTrackIdx = -1;

    if (mode !== "midi") {
        audioTrackIdx = findOrCreateAudioTrack();
    }
    if (mode !== "audio") {
        midiTrackIdx = findOrCreateMidiTrack();
    }

    status("Using audio track " + audioTrackIdx + ", MIDI track " + midiTrackIdx);

    // Set default output path — into repo at stemforge/data/
    if (!_outputPath) {
        _outputPath = "/Users/" + getUsername() + "/zacharysbrown/stemforge/stemforge/data/live_devices.json";
    }

    // Initialize result
    _result = {
        live_version: getLiveVersion(),
        scraped_at: new Date().toISOString(),
        audio_effects: {},
        midi_effects: {},
        errors: {}
    };

    // Build work queue
    _queue = [];
    if (mode === "all" || mode === "audio") {
        for (var i = 0; i < AUDIO_EFFECTS.length; i++) {
            _queue.push({
                name: AUDIO_EFFECTS[i],
                trackIdx: audioTrackIdx,
                category: "audio_effect"
            });
        }
    }
    if (mode === "all" || mode === "midi") {
        for (var j = 0; j < MIDI_EFFECTS.length; j++) {
            _queue.push({
                name: MIDI_EFFECTS[j],
                trackIdx: midiTrackIdx,
                category: "midi_effect"
            });
        }
    }

    _totalDevices = _queue.length;
    _currentIdx = 0;

    status("Starting scrape: " + _totalDevices + " devices (" + mode + " mode)");
    post("[scraper] Output path: " + _outputPath + "\n");

    // Start processing
    processNext();
}

function getUsername() {
    // Extract username from home directory path
    // Max's File API doesn't expose env vars directly,
    // but we can look at well-known paths
    try {
        var f = new Folder("Macintosh HD:/Users/");
        var dirs = [];
        while (!f.end) {
            if (f.filetype === "fold" && f.filename !== "Shared" && f.filename.charAt(0) !== ".") {
                dirs.push(f.filename);
            }
            f.next();
        }
        f.close();
        // If only one non-system user, use that
        if (dirs.length === 1) return dirs[0];
        // Otherwise default to common patterns
        for (var i = 0; i < dirs.length; i++) {
            if (dirs[i] !== "Guest" && dirs[i] !== "admin") return dirs[i];
        }
        return dirs[0] || "user";
    } catch (_) {
        return "user";
    }
}

// ── Quick single-device test ─────────────────────────────────────────────────

function scrapeOne() {
    // Quick test: scrape just one device and print to console
    var audioTrackIdx = findOrCreateAudioTrack();

    var deviceName = "Compressor";
    var args = arrayfromargs(messagename, arguments);
    if (args.length > 1) {
        deviceName = args.slice(1).join(" ");
    }

    status("Scraping single device: " + deviceName);
    var scraped = scrapeDevice(audioTrackIdx, deviceName);

    if (scraped.error) {
        status("ERROR: " + scraped.error);
        return;
    }

    post("\n═══ " + deviceName + " (" + scraped.class_name + ") ═══\n");
    for (var i = 0; i < scraped.parameters.length; i++) {
        var p = scraped.parameters[i];
        var line = "  [" + p.index + "] " + p.name;
        line += "  range=[" + p.min + " .. " + p.max + "]";
        line += "  default=" + p.default_value;
        if (p.is_quantized) {
            line += "  QUANTIZED";
            if (p.value_items) {
                line += " {" + p.value_items.join(", ") + "}";
            }
        }
        post(line + "\n");
    }
    post("═══ " + scraped.parameters.length + " parameters ═══\n\n");
    status("Done: " + deviceName + " — " + scraped.parameters.length + " params (see Max console)");
}
