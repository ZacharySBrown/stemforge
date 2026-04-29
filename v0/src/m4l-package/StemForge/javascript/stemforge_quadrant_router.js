// stemforge_quadrant_router.js
// ─────────────────────────────────────────────────────────────────────────────
// M4L MIDI Effect: routes an 8×8 controller grid into four 4×4 quadrants,
// each on a different MIDI channel, so four Drum Rack tracks can be played
// simultaneously from one controller.
//
// Place this on a MIDI track. Set each Drum Rack track's "MIDI From" to
// this track, filtered to its channel (1=drums, 2=bass, 3=vocals, 4=other).
//
// Supports:
//   - Launchpad Pro (original) Programmer mode: notes 11-88 (row*10 + col)
//   - Launchpad Pro MK2 Programmer mode: same note layout
//   - Launchpad Pro MK3 Programmer mode: same note layout
//   - Generic 8×8 grid: configurable note mapping
//
// Messages:
//   Raw MIDI note on/off → parsed → quadrant detected → remapped → output
// ─────────────────────────────────────────────────────────────────────────────

autowatch = 1;
inlets = 1;
outlets = 1;  // single outlet — all quadrants, differentiated by note range

// ── Quadrant configuration ──────────────────────────────────────────────────
// Which stem maps to which quadrant position
// Note range offsets per quadrant.
// Each quadrant's 16 pads map to a unique 16-note range:
//   Drums:  36-51 (C1-D#2)  — offset 0
//   Bass:   52-67 (E2-G3)   — offset 16
//   Vocals: 68-83 (G#3-B4)  — offset 32
//   Other:  84-99 (C5-D#6)  — offset 48
var QUADRANT_OFFSETS = {
    "top_left":     0,    // Drums:  36-51
    "top_right":    16,   // Bass:   52-67
    "bottom_left":  32,   // Vocals: 68-83
    "bottom_right": 48    // Other:  84-99
};

// Drum Rack note range: C1(36) through D#2(51) = 16 pads
var DRUM_RACK_BASE = 36;

// Launchpad Pro Programmer mode:
// Note numbers are row*10 + col, where row=1-8 (bottom to top), col=1-8
// Example: bottom-left pad = 11, top-right pad = 88
var LP_MODE = "programmer";  // "programmer" or "sequential"

// ── Color definitions (Launchpad velocity-based colors) ─────────────────────
// Launchpad Pro uses velocity value as color index (0-127)
// These are approximate matches to stem colors in the standard palette
var QUADRANT_COLORS = {
    "top_left":     5,    // Red (drums)
    "top_right":    45,   // Blue (bass)
    "bottom_left":  9,    // Orange (vocals)
    "bottom_right": 21    // Green (other)
};

// Dim versions for "off" state
var QUADRANT_COLORS_DIM = {
    "top_left":     7,    // Dim red
    "top_right":    47,   // Dim blue
    "bottom_left":  11,   // Dim orange
    "bottom_right": 23    // Dim green
};

// ── Core routing logic ──────────────────────────────────────────────────────

// Launchpad Pro MK2 Programmer mode (Standalone Port):
// Each pad sends a unique note: row*10 + col
// Row 1 (bottom): 11-18, Row 8 (top): 81-88
// No overlapping notes — clean 1:1 pad-to-note mapping.

function _parseGridPosition(noteNum) {
    var row = Math.floor(noteNum / 10);  // 1-8
    var col = noteNum % 10;               // 1-8

    if (row < 1 || row > 8 || col < 1 || col > 8) {
        return null;  // side button or out of range
    }

    return { row: row, col: col };
}

function _getQuadrant(row, col) {
    // Top half: rows 5-8, Bottom half: rows 1-4
    // Left half: cols 1-4, Right half: cols 5-8
    var isTop = row >= 5;
    var isLeft = col <= 4;

    if (isTop && isLeft) return "top_left";
    if (isTop && !isLeft) return "top_right";
    if (!isTop && isLeft) return "bottom_left";
    return "bottom_right";
}

function _remapToDrumRack(row, col) {
    // Convert grid position to local 4×4 position within the quadrant,
    // then map to Drum Rack note (36-51)
    //
    // Local row/col are 0-3 within the quadrant
    var localRow, localCol;

    if (row >= 5) {
        localRow = row - 5;  // 0-3 (5→0, 6→1, 7→2, 8→3)
    } else {
        localRow = row - 1;  // 0-3 (1→0, 2→1, 3→2, 4→3)
    }

    if (col <= 4) {
        localCol = col - 1;  // 0-3 (1→0, 2→1, 3→2, 4→3)
    } else {
        localCol = col - 5;  // 0-3 (5→0, 6→1, 7→2, 8→3)
    }

    // Drum Rack pad mapping: row 0 = pads 0-3, row 1 = pads 4-7, etc.
    var padIndex = localRow * 4 + localCol;
    return DRUM_RACK_BASE + padIndex;
}

// ── MIDI handling ───────────────────────────────────────────────────────────
// midiin sends raw MIDI bytes one integer at a time.
// We collect 3 bytes for note on/off, remap, and output to midiout.

var _midiBytes = [];

function msg_int(val) {
    val = val & 0xFF;
    // Status byte (high bit set)
    if (val & 0x80) {
        _midiBytes = [val];
        return;
    }

    // Data byte — add to current message
    _midiBytes.push(val);

    // Note messages are 3 bytes: status, note, velocity
    if (_midiBytes.length < 3) return;

    var status = _midiBytes[0];
    var noteNum = _midiBytes[1];
    var velocity = _midiBytes[2];
    _midiBytes = [];

    var msgType = status & 0xF0;
    var isNoteOn = (msgType === 0x90);
    var isNoteOff = (msgType === 0x80);

    if (!isNoteOn && !isNoteOff) {
        // Pass through non-note messages (CC, pitchbend, etc.)
        outlet(0, status);
        outlet(0, noteNum);
        outlet(0, velocity);
        return;
    }

    // Parse grid position from Launchpad Programmer mode note
    var pos = _parseGridPosition(noteNum);
    if (!pos) {
        // Not a grid pad (side buttons etc.) — pass through unchanged
        outlet(0, status);
        outlet(0, noteNum);
        outlet(0, velocity);
        return;
    }

    // Determine quadrant and remap note to offset range
    var quadrant = _getQuadrant(pos.row, pos.col);
    var offset = QUADRANT_OFFSETS[quadrant];
    var drumNote = _remapToDrumRack(pos.row, pos.col) + offset;

    // Output as raw MIDI bytes on channel 1 — single outlet, single track.
    // The Instrument Rack on this track splits by key zone (36-51, 52-67, etc.)
    // Each chain has a Pitch device to transpose back to C1-D#2 range.
    var newStatus = (status & 0xF0);  // note on/off on channel 0

    outlet(0, newStatus);
    outlet(0, drumNote);
    outlet(0, velocity);
}

// ── LED color initialization ────────────────────────────────────────────────
// Send SysEx to color all pads by quadrant on device load

function colorize() {
    // Launchpad Pro SysEx for setting pad LED:
    // F0 00 20 29 02 10 0A <pad_note> <color_velocity> F7
    //
    // We set each pad to its quadrant's dim color
    for (var row = 1; row <= 8; row++) {
        for (var col = 1; col <= 8; col++) {
            var noteNum = row * 10 + col;
            var quadrant = _getQuadrant(row, col);
            var color = QUADRANT_COLORS_DIM[quadrant];

            // Send as SysEx via outlet
            outlet(0, [0xF0, 0x00, 0x20, 0x29, 0x02, 0x10, 0x0A,
                       noteNum, color, 0xF7]);
        }
    }
    post("Quadrant colors set\n");
}

function bang() {
    // Skip auto-colorize on load — SysEx to Launchpad needs direct port output,
    // not midiout (which goes to the MIDI chain). Will implement via midiinfo later.
    post("QuadrantRouter ready — colorize disabled (use direct SysEx for LED control)\n");
}

// ── Debug ───────────────────────────────────────────────────────────────────

function test() {
    // Test mapping for a few pads
    var testPads = [11, 14, 15, 18, 51, 54, 55, 58, 81, 84, 85, 88];
    for (var i = 0; i < testPads.length; i++) {
        var n = testPads[i];
        var pos = _parseGridPosition(n);
        if (!pos) continue;
        var q = _getQuadrant(pos.row, pos.col);
        var dn = _remapToDrumRack(pos.row, pos.col);
        var ch = QUADRANT_CHANNELS[q];
        post("pad " + n + " (r" + pos.row + "c" + pos.col + ") → "
             + q + " ch" + ch + " note" + dn + "\n");
    }
}

// ── Entry points ────────────────────────────────────────────────────────────

if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        _parseGridPosition: _parseGridPosition,
        _getQuadrant: _getQuadrant,
        _remapToDrumRack: _remapToDrumRack,
        QUADRANT_CHANNELS: QUADRANT_CHANNELS,
    };
}
