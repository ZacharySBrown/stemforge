// test_session_bpm_override.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tier-3 tests for applyCurationV2Clip's tempo handling.
//
// Strategy (2026-05-06, mirrors sf_arrangement_loader.js):
// applyCurationV2Clip disables warping on the clip and writes start_marker,
// end_marker, loop_start, loop_end in SECONDS. Curated bars are pre-rendered
// at manifest BPM, and session tempo is set to manifest BPM at load time
// (in loadSong / _loadCuratedV2 / _loadCuratedManifest), so unwarped
// playback at the native rate stays in sync. Avoids fighting Live's
// auto-warp tempo guess — the prior move_warp_marker / add_warp_marker
// strategy was abandoned because Ableton's auto-warp markers don't
// reliably match by sample_time, leaving clips at 120 BPM default.
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

function makeClipNode() {
    return {
        _properties: { warping: 1 },  // Live default is warping=1; our code flips to 0
    };
}

function readProp(path, prop) {
    return maxApi.getLiveProperty(path, prop);
}


// ── 1. Warping is disabled (the core fix) ───────────────────────────────────

test('applyCurationV2Clip: disables warping on the clip', () => {
    const ctx = loadLoader();
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
    const ok = ctx.applyCurationV2Clip(clipApi, loopEntry, 'drums', 125);
    assert.equal(ok, true);
    assert.equal(readProp('live_set tracks 0 clip_slots 0 clip', 'warping'), 0);
});


// ── 2. Markers are written in SECONDS, not beats ────────────────────────────

test('applyCurationV2Clip: start_marker / end_marker in seconds', () => {
    const ctx = loadLoader();
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
        },
        warp_markers: [],
    };

    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    ctx.applyCurationV2Clip(clipApi, loopEntry, 'drums', 125);

    // Expect raw values in seconds — NOT 0 and 8 (beats at 126 BPM) and
    // NOT 0 and 7.93 (beats at 125 BPM session). Just seconds.
    const sm = readProp('live_set tracks 0 clip_slots 0 clip', 'start_marker');
    const em = readProp('live_set tracks 0 clip_slots 0 clip', 'end_marker');
    assert.ok(Math.abs(sm - 0.0) < 1e-9, `start_marker should be 0.0 seconds, got ${sm}`);
    assert.ok(Math.abs(em - 3.808) < 1e-9, `end_marker should be 3.808 seconds, got ${em}`);
});


// ── 3. Loop region in seconds, looping enabled ──────────────────────────────

test('applyCurationV2Clip: loop_start / loop_end in seconds when loop enabled', () => {
    const ctx = loadLoader();
    maxApi.seedLiveTree({
        tracks: [{ clip_slots: [{ clip: makeClipNode() }] }]
    });

    const loopEntry = {
        position: 1,
        clip: { raw_start_sec: 0.952, raw_end_sec: 2.856, padded_start_sec: 0.0, padded_end_sec: 3.808 },
        loop: {
            enabled: true,
            loop_start_sec: 0.952,
            loop_end_sec: 2.856,
        },
        warp_markers: [],
    };

    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    ctx.applyCurationV2Clip(clipApi, loopEntry, 'drums', 125);

    const ls = readProp('live_set tracks 0 clip_slots 0 clip', 'loop_start');
    const le = readProp('live_set tracks 0 clip_slots 0 clip', 'loop_end');
    const looping = readProp('live_set tracks 0 clip_slots 0 clip', 'looping');
    assert.ok(Math.abs(ls - 0.952) < 1e-9, `loop_start should be 0.952 seconds, got ${ls}`);
    assert.ok(Math.abs(le - 2.856) < 1e-9, `loop_end should be 2.856 seconds, got ${le}`);
    assert.equal(looping, 1);
});


// ── 4. warp_mode still set per-stem (in case user manually re-enables warping) ──

test('applyCurationV2Clip: warp_mode set from BAR_WARP_MODES per stem', () => {
    const ctx = loadLoader();
    maxApi.seedLiveTree({
        tracks: [{ clip_slots: [{ clip: makeClipNode() }] }]
    });
    const loopEntry = {
        position: 1,
        clip: { raw_start_sec: 0.0, raw_end_sec: 3.808, padded_start_sec: 0.0, padded_end_sec: 3.808 },
        warp_markers: [],
    };
    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    ctx.applyCurationV2Clip(clipApi, loopEntry, 'drums', 125);
    // BAR_WARP_MODES.drums = 0 (Beats)
    assert.equal(readProp('live_set tracks 0 clip_slots 0 clip', 'warp_mode'), 0);
});


// ── 5. sessionBpm parameter ignored under arrangement-loader-mirror strategy ──

test('applyCurationV2Clip: behavior unchanged regardless of sessionBpm', () => {
    const ctx = loadLoader();

    function run(sessionBpm) {
        maxApi.seedLiveTree({
            tracks: [{ clip_slots: [{ clip: makeClipNode() }] }]
        });
        const loopEntry = {
            position: 1,
            clip: { raw_start_sec: 0.0, raw_end_sec: 3.808, padded_start_sec: 0.0, padded_end_sec: 3.808 },
            warp_markers: [],
        };
        const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
        ctx.applyCurationV2Clip(clipApi, loopEntry, 'drums', sessionBpm);
        return {
            warping: readProp('live_set tracks 0 clip_slots 0 clip', 'warping'),
            sm: readProp('live_set tracks 0 clip_slots 0 clip', 'start_marker'),
            em: readProp('live_set tracks 0 clip_slots 0 clip', 'end_marker'),
        };
    }

    // sessionBpm=125 vs sessionBpm=undefined vs sessionBpm=0 all yield same.
    const a = run(125);
    const b = run(undefined);
    const c = run(0);
    assert.deepEqual(a, b);
    assert.deepEqual(a, c);
});


// ── 6. Acceptance gate: confirm we mirror the arrangement loader's strategy ─

test('applyCurationV2Clip mirrors sf_arrangement_loader.js strategy', () => {
    const fs = require('fs');
    const src = fs.readFileSync(SF_LOADER, 'utf8');

    // Function disables warping (mirror of arrangement loader line 370)
    const fnMatch = src.match(/function applyCurationV2Clip[\s\S]*?\n}/);
    assert.ok(fnMatch, 'function applyCurationV2Clip not found');
    const fnBody = fnMatch[0];
    assert.ok(
        /clipApi\.set\("warping",\s*0\)/.test(fnBody),
        'applyCurationV2Clip must call clipApi.set("warping", 0) — the arrangement-loader strategy'
    );

    // Markers are NOT multiplied by secToBeat (no beats conversion)
    assert.ok(
        !/start_marker.*\*\s*secToBeat/.test(fnBody),
        'start_marker should not be converted to beats — markers are in SECONDS now'
    );

    // No more move_warp_marker / add_warp_marker CALL invocations (fight
    // abandoned). Mention of the names in comments is fine — that's
    // documenting the strategy change.
    assert.ok(
        !/\.call\(["'](?:move_warp_marker|add_warp_marker)["']/.test(fnBody),
        'applyCurationV2Clip should no longer call move_warp_marker / add_warp_marker'
    );
});
