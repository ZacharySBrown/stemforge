// test_session_bpm_override.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tier-3 tests for the session-BPM override added 2026-05-06 to
// applyCurationV2Clip. Believer regression: clip's effective tempo was being
// set to 120 BPM (Ableton auto-warp default) or 126 BPM (curate-time drift)
// instead of session BPM (125 = stems.json truth). The fix passes mf.bpm
// through every loadClipsToTrack / applyCurationV2Clip call and recomputes
// warp marker beat positions from session BPM at load time, ignoring the
// manifest's potentially-stale beat_pos values.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, maxApi } = require('./sandbox');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SF_LOADER = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js', 'stemforge_loader.v0.js');


function loadLoader() {
    maxApi.resetState();
    const ctx = createSandbox();
    loadModule(ctx, SF_LOADER);
    return ctx;
}

function makeClipNode(propsOnly = false) {
    return propsOnly
        ? { _properties: {} }
        : {
              _properties: { warping: 1 },
              warp_markers: [],  // we DON'T model marker reads here; the test asserts
                                  // that applyCurationV2Clip computes the right beat_pos
                                  // for its move/add calls, which the mock captures via
                                  // setLiveCallHandler.
          };
}


// ── 1. With sessionBpm provided, beat_pos is recomputed from time_sec * sessionBpm/60 ──

test('applyCurationV2Clip: sessionBpm overrides manifest beat_pos values', () => {
    const ctx = loadLoader();

    // Capture move_warp_marker / add_warp_marker calls — that's where the
    // beat positions our function computes actually land.
    const calls = [];
    maxApi.setLiveCallHandler('move_warp_marker', (lomPath, args) => {
        calls.push({ verb: 'move', currentBeat: args[0], delta: args[1] });
        return 1;
    });
    maxApi.setLiveCallHandler('add_warp_marker', (lomPath, args) => {
        // args[0] is a Dict mock; pull the values back out.
        const dict = args[0];
        let beat, sample;
        try {
            beat = dict.get('beat_time');
            sample = dict.get('sample_time');
        } catch (_) {}
        calls.push({ verb: 'add', beat_time: beat, sample_time: sample });
        return 1;
    });

    // Seed a minimal liveTree so a clip lookup at "live_set tracks 0
    // clip_slots 0 clip" returns a valid LOM-node mock.
    maxApi.seedLiveTree({
        tracks: [{
            clip_slots: [{
                clip: makeClipNode()
            }]
        }]
    });

    // Believer-shape loop entry: warp_markers encode 126 BPM (drift).
    // Each marker pair (time_sec=3.808, beat_pos=8) implies 126 BPM.
    const loopEntry = {
        position: 1,
        clip: {
            raw_start_sec: 0.0,
            raw_end_sec: 3.808,
            padded_start_sec: 0.0,
            padded_end_sec: 3.808,
            pad_bars: 0,
        },
        warp_markers: [
            { time_sec: 0.0, beat_pos: 0.0, type: 'start' },
            { time_sec: 3.808, beat_pos: 8.0, type: 'end' },
        ],
    };

    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    // Pass session BPM = 125. Function should recompute beat_pos from
    // time_sec * 125/60 instead of using manifest's 8.0 (which encodes 126).
    ctx.applyCurationV2Clip(clipApi, loopEntry, 'drums', 125);

    // Expected end-beat at 125 BPM, time_sec=3.808: 3.808 * 125/60 = 7.9333
    // (NOT 8.0 from the manifest)
    const adds = calls.filter((c) => c.verb === 'add');
    const lastAdd = adds[adds.length - 1];
    assert.ok(lastAdd, 'expected at least one add_warp_marker call');
    const expectedBeat = 3.808 * 125 / 60;
    assert.ok(
        Math.abs(lastAdd.beat_time - expectedBeat) < 0.001,
        `last warp marker should be at beat ${expectedBeat.toFixed(4)} (session BPM 125),
         got ${lastAdd.beat_time}`
    );
});


// ── 2. Without sessionBpm, falls back to manifest beat_pos values (back-compat) ──

test('applyCurationV2Clip: no sessionBpm → uses manifest beat_pos values', () => {
    const ctx = loadLoader();

    const calls = [];
    maxApi.setLiveCallHandler('add_warp_marker', (lomPath, args) => {
        const dict = args[0];
        let beat;
        try { beat = dict.get('beat_time'); } catch (_) {}
        calls.push({ verb: 'add', beat_time: beat });
        return 1;
    });

    maxApi.seedLiveTree({
        tracks: [{ clip_slots: [{ clip: makeClipNode() }] }]
    });

    const loopEntry = {
        position: 1,
        clip: {
            raw_start_sec: 0.0,
            raw_end_sec: 3.808,
            padded_start_sec: 0.0,
            padded_end_sec: 3.808,
            pad_bars: 0,
        },
        warp_markers: [
            { time_sec: 0.0, beat_pos: 0.0, type: 'start' },
            { time_sec: 3.808, beat_pos: 8.0, type: 'end' },
        ],
    };

    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    // No sessionBpm passed → fallback to manifest's 8.0.
    ctx.applyCurationV2Clip(clipApi, loopEntry, 'drums');

    const adds = calls.filter((c) => c.verb === 'add');
    const lastAdd = adds[adds.length - 1];
    assert.ok(lastAdd, 'expected at least one add_warp_marker call');
    assert.ok(
        Math.abs(lastAdd.beat_time - 8.0) < 0.001,
        `back-compat: last warp marker should be at manifest beat 8.0, got ${lastAdd.beat_time}`
    );
});


// ── 3. Zero / undefined sessionBpm should also fall back ──

test('applyCurationV2Clip: sessionBpm=0 → fallback to manifest', () => {
    const ctx = loadLoader();
    const calls = [];
    maxApi.setLiveCallHandler('add_warp_marker', (lomPath, args) => {
        const dict = args[0];
        let beat;
        try { beat = dict.get('beat_time'); } catch (_) {}
        calls.push({ beat_time: beat });
        return 1;
    });
    maxApi.seedLiveTree({
        tracks: [{ clip_slots: [{ clip: makeClipNode() }] }]
    });
    const loopEntry = {
        position: 1,
        clip: { raw_start_sec: 0.0, raw_end_sec: 3.808, padded_start_sec: 0.0, padded_end_sec: 3.808 },
        warp_markers: [
            { time_sec: 0.0, beat_pos: 0.0, type: 'start' },
            { time_sec: 3.808, beat_pos: 8.0, type: 'end' },
        ],
    };
    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    ctx.applyCurationV2Clip(clipApi, loopEntry, 'drums', 0);

    const last = calls[calls.length - 1];
    assert.ok(last, 'expected at least one add call');
    assert.ok(
        Math.abs(last.beat_time - 8.0) < 0.001,
        `sessionBpm=0 should fall back to manifest 8.0, got ${last.beat_time}`
    );
});


// ── 4. Acceptance gate sentinel ──────────────────────────────────────────────

test('clip-tempo session-BPM override sentinel: contract is wired', () => {
    const fs = require('fs');
    const src = fs.readFileSync(SF_LOADER, 'utf8');
    // applyCurationV2Clip signature includes sessionBpm
    assert.ok(
        /function applyCurationV2Clip\([^)]*\bsessionBpm\b[^)]*\)/.test(src),
        'applyCurationV2Clip must accept sessionBpm parameter'
    );
    // loadClipsToTrack signature includes sessionBpm
    assert.ok(
        /function loadClipsToTrack\([^)]*\bsessionBpm\b[^)]*\)/.test(src),
        'loadClipsToTrack must accept sessionBpm parameter'
    );
    // All three callers of applyCurationV2Clip pass mf.bpm or sessionBpm
    const callsToApply = src.match(/applyCurationV2Clip\([^)]*\)/g) || [];
    assert.ok(callsToApply.length >= 3, `expected ≥3 call sites, got ${callsToApply.length}`);
    const callsWithBpm = callsToApply.filter(
        (c) => /\bmf\.bpm\b|\bsessionBpm\b/.test(c)
    );
    assert.equal(
        callsWithBpm.length, callsToApply.length,
        `every applyCurationV2Clip call must pass mf.bpm or sessionBpm; non-passers: ${
            callsToApply.filter((c) => !/\bmf\.bpm\b|\bsessionBpm\b/.test(c)).join(', ')
        }`
    );
});
