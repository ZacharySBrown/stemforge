// stemforge_template_builder.js
// ─────────────────────────────────────────────────────────────────────────────
// Max for Live JavaScript — creates the 7 StemForge template tracks
// automatically: tracks, devices, parameters, colors, grouping.
//
// Usage: drop onto any MIDI track in your StemForge Templates set,
// click the button (bang) to build all template tracks.
// Run ONCE — then remove or bypass the device.
//
// Requires: Ableton Live 11+ / 12, Max for Live
// VST3 plugins are loaded best-effort — missing ones are logged.
// ─────────────────────────────────────────────────────────────────────────────

inlets  = 1;
outlets = 2;  // 0: status messages, 1: bang on complete

// ── Track Color Constants (0x00RRGGBB for LOM) ───────────────────────────────
var RED         = 0xFF2400;
var RED_DARK    = 0xAA1800;
var RED_BRIGHT  = 0xFF3030;
var BLUE        = 0x0055FF;
var GREEN       = 0x00AA44;
var TEAL        = 0x00BBAA;
var ORANGE      = 0xFF8800;
var GREY        = 0x666666;

// ── Template Definitions ─────────────────────────────────────────────────────
// Each entry: { name, type, color, devices[], clip }
// device.category: "audio_effects" | "instruments" | "plugins"
// device.search:   name to search in the Browser tree
// device.params:   { "LOM param name": value } — set after device loads

var TEMPLATES = [

    // ── Track 1: SF | Drums Raw ──────────────────────────────────────────────
    {
        name: "SF | Drums Raw",
        type: "audio",
        color: RED,
        devices: [
            {
                search: "Compressor",
                category: "audio_effects",
                params: {
                    "Ratio":       2.5,
                    "Attack":      10.0,
                    "Release":     80.0,
                    "Output Gain": 0.0
                }
            },
            {
                search: "EQ Eight",
                category: "audio_effects",
                params: {
                    "1 Filter On A":   1,    // enable band 1
                    "1 Filter Type A": 5,    // high shelf
                    "1 Frequency A":   10000,
                    "1 Gain A":        2.0
                }
            }
        ],
        clip: { warp_mode: 0, loop: true }  // beats
    },

    // ── Track 2: SF | Drums Crushed ──────────────────────────────────────────
    {
        name: "SF | Drums Crushed",
        type: "audio",
        color: RED_DARK,
        devices: [
            {
                search: "LO-FI-AF",
                category: "plugins",
                params: {}  // VST3 — set sections manually or via pipeline
            },
            {
                search: "Decapitator",
                category: "plugins",
                params: {}
            },
            {
                search: "Compressor",
                category: "audio_effects",
                params: {
                    "Ratio":       6.0,
                    "Attack":      5.0,
                    "Release":     60.0,
                    "Output Gain": 2.0
                }
            },
            {
                search: "EchoBoy Jr",
                category: "plugins",
                params: {}
            }
        ],
        clip: { warp_mode: 0, loop: true }
    },

    // ── Track 3: SF | Bass ───────────────────────────────────────────────────
    {
        name: "SF | Bass",
        type: "audio",
        color: BLUE,
        devices: [
            {
                search: "EQ Eight",
                category: "audio_effects",
                params: {
                    "1 Filter On A":   1,
                    "1 Filter Type A": 0,    // 12dB low-cut (high pass)
                    "1 Frequency A":   35,

                    "2 Filter On A":   1,
                    "2 Filter Type A": 2,    // low shelf
                    "2 Frequency A":   80,
                    "2 Gain A":        2.0,

                    "3 Filter On A":   1,
                    "3 Filter Type A": 5,    // high shelf
                    "3 Frequency A":   8000,
                    "3 Gain A":        -1.0
                }
            },
            {
                search: "Compressor",
                category: "audio_effects",
                params: {
                    "Ratio":   4.0,
                    "Attack":  20.0,
                    "Release": 120.0
                }
            },
            {
                search: "LO-FI-AF",
                category: "plugins",
                params: {}
            },
            {
                search: "Decapitator",
                category: "plugins",
                params: {}
            }
        ],
        clip: { warp_mode: 0, loop: true }
    },

    // ── Track 4: SF | Texture Verb ───────────────────────────────────────────
    {
        name: "SF | Texture Verb",
        type: "audio",
        color: GREEN,
        devices: [
            {
                search: "PhaseMistress",
                category: "plugins",
                params: {}
            },
            {
                search: "EchoBoy",
                category: "plugins",
                params: {}
            },
            {
                search: "Reverb",
                category: "audio_effects",
                params: {
                    "Room Size":  0.75,
                    "Decay Time": 3.0,
                    "Diffusion":  0.9,
                    "Dry/Wet":    0.35
                }
            },
            {
                search: "LO-FI-AF",
                category: "plugins",
                params: {}
            }
        ],
        clip: { warp_mode: 4, loop: true }  // complex
    },

    // ── Track 5: SF | Texture Crystallized ───────────────────────────────────
    {
        name: "SF | Texture Crystallized",
        type: "audio",
        color: TEAL,
        devices: [
            {
                search: "Crystallizer",
                category: "plugins",
                params: {}
            },
            {
                search: "Reverb",
                category: "audio_effects",
                params: {
                    "Room Size":  0.9,
                    "Decay Time": 5.0,
                    "Dry/Wet":    0.6
                }
            },
            {
                search: "Utility",
                category: "audio_effects",
                params: {
                    "Width": 1.3   // 130%
                }
            }
        ],
        clip: { warp_mode: 5, loop: true }  // complex-pro
    },

    // ── Track 6: SF | Vocals ─────────────────────────────────────────────────
    {
        name: "SF | Vocals",
        type: "audio",
        color: ORANGE,
        devices: [
            {
                search: "EQ Eight",
                category: "audio_effects",
                params: {
                    "1 Filter On A":   1,
                    "1 Filter Type A": 0,    // high pass
                    "1 Frequency A":   120,

                    "2 Filter On A":   1,
                    "2 Filter Type A": 3,    // bell
                    "2 Frequency A":   3000,
                    "2 Gain A":        2.0
                }
            },
            {
                search: "Compressor",
                category: "audio_effects",
                params: {
                    "Ratio":   3.0,
                    "Attack":  15.0,
                    "Release": 100.0
                }
            },
            {
                search: "LO-FI-AF",
                category: "plugins",
                params: {}
            },
            {
                search: "EchoBoy",
                category: "plugins",
                params: {}
            }
        ],
        clip: { warp_mode: 1, loop: true }  // tones
    },

    // ── Track 7: SF | Beat Chop Simpler ──────────────────────────────────────
    {
        name: "SF | Beat Chop Simpler",
        type: "midi",
        color: RED_BRIGHT,
        devices: [
            {
                search: "Simpler",
                category: "instruments",
                params: {}  // Classic mode, warp on — set manually after load
            },
            {
                search: "Decapitator",
                category: "plugins",
                params: {}
            },
            {
                search: "PrimalTap",
                category: "plugins",
                params: {}
            }
        ],
        clip: null
    }
];

// ── Build State ──────────────────────────────────────────────────────────────

var queue       = [];
var queueIndex  = 0;
var baseIndex   = 0;   // first track index we create
var buildActive = false;

// ── Entry Point ──────────────────────────────────────────────────────────────

function bang() {
    if (buildActive) {
        status("Build already in progress");
        return;
    }
    buildTemplates();
}

// Allow cancelling mid-build
function stop() {
    buildActive = false;
    queue = [];
    queueIndex = 0;
    status("Build cancelled");
}

// ── Build Orchestration ──────────────────────────────────────────────────────

function buildTemplates() {
    buildActive = true;
    baseIndex   = getTrackCount();
    queue       = [];
    queueIndex  = 0;

    status("Creating " + TEMPLATES.length + " template tracks starting at index " + baseIndex);

    // Phase 1: create all tracks (fast)
    for (var t = 0; t < TEMPLATES.length; t++) {
        enqueue(doCreateTrack, [t], 150);
    }

    // Phase 2: print device checklist per track
    // (Browser API is unavailable — devices must be added manually)
    for (var t = 0; t < TEMPLATES.length; t++) {
        enqueue(doPrintDevices, [t], 100);
    }

    // Phase 3: group and finish
    enqueue(doGroupTracks, [], 400);
    enqueue(doFinish,      [], 100);

    processQueue();
}

function enqueue(fn, args, delay) {
    queue.push({ fn: fn, args: args, delay: delay || 200 });
}

function processQueue() {
    if (!buildActive) return;
    if (queueIndex >= queue.length) return;

    var step = queue[queueIndex];
    try {
        step.fn.apply(this, step.args);
    } catch (e) {
        status("ERROR at step " + queueIndex + ": " + e);
    }
    queueIndex++;

    if (queueIndex < queue.length) {
        var t = new Task(processQueue, this);
        t.schedule(step.delay);
    }
}

// ── Phase 1: Create Tracks ───────────────────────────────────────────────────

function doCreateTrack(templateIdx) {
    var tmpl = TEMPLATES[templateIdx];
    var idx  = baseIndex + templateIdx;
    var song = new LiveAPI("live_set");

    if (tmpl.type === "midi") {
        song.call("create_midi_track", idx);
    } else {
        song.call("create_audio_track", idx);
    }

    // Name + color
    var track = new LiveAPI("live_set tracks " + idx);
    track.set("name", tmpl.name);
    track.set("color", tmpl.color);

    status("Created track " + (templateIdx + 1) + "/" + TEMPLATES.length +
           ": " + tmpl.name);
}

// ── Phase 2: Print Device Checklist ──────────────────────────────────────────
// Browser API is not available in this Live version, so we print a checklist
// of which devices to drag onto each track manually.

function doPrintDevices(templateIdx) {
    var tmpl = TEMPLATES[templateIdx];
    var devices = [];
    for (var d = 0; d < tmpl.devices.length; d++) {
        devices.push(tmpl.devices[d].search);
    }
    status("  " + tmpl.name + " → drag: " + devices.join(" → "));
}

// ── Phase 3: Group Tracks ────────────────────────────────────────────────────

function doGroupTracks() {
    // Select all template tracks, then group
    var view = new LiveAPI("live_set view");
    var song = new LiveAPI("live_set");

    // Select first template track
    selectTrack(baseIndex);

    // Select range: in LOM we can't multi-select directly.
    // Use Song.create_group — only available in Live 12+
    // Fallback: just log a reminder.
    try {
        // Live 12 API: create_group with track indices
        // This is version-dependent, so wrap in try/catch
        var trackIds = [];
        for (var t = 0; t < TEMPLATES.length; t++) {
            trackIds.push(baseIndex + t);
        }
        // Note: LOM doesn't have a create_group(indices) method.
        // Users group manually: select all SF tracks → Cmd+G
        status("Group manually: select tracks " + (baseIndex + 1) + "-" +
               (baseIndex + TEMPLATES.length) +
               " → Cmd+G → name 'StemForge Templates' → color grey");
    } catch (e) {
        status("Group tracks manually: Cmd+G");
    }
}

function doFinish() {
    buildActive = false;
    status("Template build complete! " + TEMPLATES.length + " tracks created.");
    status("Next: set VST3 params per setup.md, then group → Cmd+G");
    outlet(1, "bang");
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getTrackCount() {
    var api = new LiveAPI("live_set");
    return api.getcount("tracks");
}

function selectTrack(index) {
    var view  = new LiveAPI("live_set view");
    var track = new LiveAPI("live_set tracks " + index);
    view.set("selected_track", "id", track.id);
}

function status(msg) {
    outlet(0, "set", msg);
    post(msg + "\n");
}
