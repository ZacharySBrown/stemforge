// test_locator_anchor.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Offline regression tests for v0/src/m4l-js/sf_locator_anchor.js.
//
// Run:   node tests/js_mocks/test_locator_anchor.test.js
//
// What we cover:
//   - _join / _expandTilde — path helpers
//   - _pickLocator — preferred-name selection (anchor / downbeat / bar 1)
//   - _sourceTimeAtTimelineBeat — back-compute math against a synthetic manifest
//   - anchor() end-to-end: picks locator, computes source time, fires shell
//     atoms on outlet 1
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, maxApi } = require('./sandbox');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const JS_DIR = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js');
const SF_LOCATOR_ANCHOR = path.join(JS_DIR, 'sf_locator_anchor.js');

// Build a synthetic prechop_manifest with 3 chunks of 4 bars at 90 BPM.
//   bars=4, beats_per_bar=4 → chunkBeats=16
//   secPerBeat = 60/90 = 0.6667
//   chunk[0] @ source_offset_sec=0.5 (intro padding)
//   chunk[1] @ source_offset_sec=11.1667 (= 0.5 + 16 * 0.6667)
//   chunk[2] @ source_offset_sec=21.8333
function buildManifest() {
    return {
        bpm: 90.0,
        bars: 4,
        beats_per_bar: 4,
        stems: {
            drums: {
                chunks: [
                    { source_offset_sec: 0.5,     chunk_frames: 470400 },
                    { source_offset_sec: 11.1667, chunk_frames: 470400 },
                    { source_offset_sec: 21.8333, chunk_frames: 470400 }
                ]
            },
            bass: {
                chunks: [
                    { source_offset_sec: 0.5 },
                    { source_offset_sec: 11.1667 },
                    { source_offset_sec: 21.8333 }
                ]
            }
        }
    };
}

// Patch LiveAPI so `live_set` reports a tempo and `live_set cue_points N`
// reports name+time. Uses a per-test config rather than baking it into
// max_api.js, since cue_points behavior is specific to this module.
function installLiveAPIMock(ctx, opts) {
    const tempo = opts.tempo != null ? opts.tempo : 120;
    const cuePoints = opts.cuePoints || []; // [{name, time}]
    function MockLiveAPI(p) { this._path = String(p || ''); }
    MockLiveAPI.prototype.getcount = function (prop) {
        if (this._path === 'live_set' && prop === 'cue_points') return cuePoints.length;
        return 0;
    };
    MockLiveAPI.prototype.get = function (prop) {
        if (this._path === 'live_set' && prop === 'tempo') return tempo;
        const m = /^live_set cue_points (\d+)$/.exec(this._path);
        if (m) {
            const cp = cuePoints[Number(m[1])];
            if (!cp) return '';
            if (prop === 'name') return cp.name || '';
            if (prop === 'time') return cp.time;
        }
        return '';
    };
    MockLiveAPI.prototype.set = function () {};
    MockLiveAPI.prototype.call = function () {};
    ctx.LiveAPI = MockLiveAPI;
}

function freshSandbox(opts) {
    maxApi.resetState();
    const ctx = createSandbox();
    installLiveAPIMock(ctx, opts || {});
    loadModule(ctx, SF_LOCATOR_ANCHOR);
    return ctx;
}

function getTestExports(ctx) {
    return ctx.module.exports.__test__;
}

// ── Module loading ──────────────────────────────────────────────────────────

test('module loads and exposes test helpers', () => {
    const ctx = freshSandbox();
    const t = getTestExports(ctx);
    assert.ok(t);
    assert.equal(typeof t.anchor, 'function');
    assert.equal(typeof t.trackDir, 'function');
    assert.equal(typeof t._readLocators, 'function');
    assert.equal(typeof t._pickLocator, 'function');
    assert.equal(typeof t._sourceTimeAtTimelineBeat, 'function');
    assert.equal(typeof t._join, 'function');
});

// ── _join / _expandTilde ────────────────────────────────────────────────────

test('_join: empty dir → child as-is', () => {
    const ctx = freshSandbox();
    const { _join } = getTestExports(ctx);
    assert.equal(_join('', 'prechop_manifest.json'), 'prechop_manifest.json');
});

test('_join: trailing slash on dir', () => {
    const ctx = freshSandbox();
    const { _join } = getTestExports(ctx);
    assert.equal(_join('/a/b/', 'c.json'), '/a/b/c.json');
    assert.equal(_join('/a/b',  'c.json'), '/a/b/c.json');
});

// ── _pickLocator ────────────────────────────────────────────────────────────

test('_pickLocator: empty array returns null', () => {
    const ctx = freshSandbox();
    const { _pickLocator } = getTestExports(ctx);
    assert.equal(_pickLocator([]), null);
    assert.equal(_pickLocator(null), null);
});

test('_pickLocator: first locator wins when none named anchor/downbeat/bar 1', () => {
    const ctx = freshSandbox();
    const { _pickLocator } = getTestExports(ctx);
    const picked = _pickLocator([
        { name: 'verse', time_beats: 32 },
        { name: 'chorus', time_beats: 64 }
    ]);
    assert.equal(picked.name, 'verse');
});

test('_pickLocator: prefers locator named anchor (case-insensitive)', () => {
    const ctx = freshSandbox();
    const { _pickLocator } = getTestExports(ctx);
    const picked = _pickLocator([
        { name: 'verse', time_beats: 32 },
        { name: 'ANCHOR', time_beats: 16 },
        { name: 'chorus', time_beats: 64 }
    ]);
    assert.equal(picked.name, 'ANCHOR');
    assert.equal(picked.time_beats, 16);
});

test('_pickLocator: also accepts "downbeat" or "bar 1"', () => {
    const ctx = freshSandbox();
    const { _pickLocator } = getTestExports(ctx);
    let picked = _pickLocator([
        { name: 'intro', time_beats: 0 },
        { name: 'Downbeat', time_beats: 8 }
    ]);
    assert.equal(picked.name, 'Downbeat');

    picked = _pickLocator([
        { name: 'intro', time_beats: 0 },
        { name: 'Bar 1', time_beats: 8 }
    ]);
    assert.equal(picked.name, 'Bar 1');
});

// ── _sourceTimeAtTimelineBeat ───────────────────────────────────────────────

test('_sourceTimeAtTimelineBeat: locator at beat 0 → first chunk source offset', () => {
    const ctx = freshSandbox();
    const { _sourceTimeAtTimelineBeat } = getTestExports(ctx);
    const m = buildManifest();
    const t = _sourceTimeAtTimelineBeat(m, 0);
    assert.equal(t, 0.5); // chunk[0].source_offset_sec
});

test('_sourceTimeAtTimelineBeat: locator at chunkBeats → second chunk source offset', () => {
    const ctx = freshSandbox();
    const { _sourceTimeAtTimelineBeat } = getTestExports(ctx);
    const m = buildManifest();
    // chunkBeats = 4 bars * 4 beats = 16
    const t = _sourceTimeAtTimelineBeat(m, 16);
    // Should land exactly on chunk[1].source_offset_sec (beatWithin=0)
    assert.ok(Math.abs(t - 11.1667) < 1e-9);
});

test('_sourceTimeAtTimelineBeat: mid-chunk location adds beatWithin × 60/bpm', () => {
    const ctx = freshSandbox();
    const { _sourceTimeAtTimelineBeat } = getTestExports(ctx);
    const m = buildManifest();
    // Locator at beat 4 → still in chunk 0, beatWithin=4, secPerBeat=60/90
    const t = _sourceTimeAtTimelineBeat(m, 4);
    const expected = 0.5 + 4 * (60 / 90);
    assert.ok(Math.abs(t - expected) < 1e-9, 'got ' + t + ' expected ' + expected);
});

test('_sourceTimeAtTimelineBeat: locator past last chunk returns null', () => {
    const ctx = freshSandbox();
    const { _sourceTimeAtTimelineBeat } = getTestExports(ctx);
    const m = buildManifest();
    // 3 chunks * 16 chunkBeats = 48 → beat 48 falls outside (idx=3, len=3)
    assert.equal(_sourceTimeAtTimelineBeat(m, 48), null);
});

test('_sourceTimeAtTimelineBeat: negative beat returns null', () => {
    const ctx = freshSandbox();
    const { _sourceTimeAtTimelineBeat } = getTestExports(ctx);
    const m = buildManifest();
    assert.equal(_sourceTimeAtTimelineBeat(m, -1), null);
});

test('_sourceTimeAtTimelineBeat: handles missing/empty stems gracefully', () => {
    const ctx = freshSandbox();
    const { _sourceTimeAtTimelineBeat } = getTestExports(ctx);
    assert.equal(_sourceTimeAtTimelineBeat({}, 0), null);
    assert.equal(_sourceTimeAtTimelineBeat({ stems: {} }, 0), null);
    assert.equal(
        _sourceTimeAtTimelineBeat({ stems: { drums: { chunks: [] } } }, 0),
        null
    );
});

// ── anchor() end-to-end ─────────────────────────────────────────────────────

// Mock File reads from maxApi.state.fs, not real disk. Seed it (and use a
// stable in-memory path so we don't touch the filesystem at all). The seed
// MUST happen AFTER freshSandbox() — that calls resetState() which wipes
// state.fs.
const SYNTHETIC_DIR = '/Users/zak/stemforge/processed/synthetic_test';
const SYNTHETIC_MANIFEST = SYNTHETIC_DIR + '/prechop_manifest.json';

function seedTrackDir(manifest) {
    maxApi.seedFile(SYNTHETIC_MANIFEST, JSON.stringify(manifest));
    return SYNTHETIC_DIR;
}

test('anchor: bails when no track dir set', () => {
    const ctx = freshSandbox({ tempo: 90, cuePoints: [{ name: '', time: 0 }] });
    const { anchor } = getTestExports(ctx);
    const ok = anchor();
    assert.equal(ok, false);
});

test('anchor: bails when no locators placed', () => {
    const ctx = freshSandbox({ tempo: 90, cuePoints: [] });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), false);
});

test('anchor: emits reload atoms (path + shift) on outlet 2', () => {
    // Manifest has musical_bar_1_chunk_index implicit=0, chunkBeats=16.
    // Locator at beat 16 → shift = 16 - 0 = 16 beats.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: 'anchor', time: 16 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), true);

    const calls = maxApi.state.outlets[2] || [];
    assert.equal(calls.length, 1, 'expected one reload emission on outlet 2');
    const atoms = calls[0];
    assert.equal(atoms.length, 2, 'expected [path, shift] atoms, got ' + atoms.length);
    assert.equal(atoms[0], dir + '/prechop_manifest.json');
    assert.equal(Number(atoms[1]), 16);

    // Outlet 1 (the old shell path) must NOT fire under shift-only semantics.
    const shellCalls = maxApi.state.outlets[1] || [];
    assert.equal(shellCalls.length, 0, 'shell outlet must be silent under shift-only');
});

test('anchor: shift respects musical_bar_1_chunk_index from manifest', () => {
    // pre_bars manifest: bar 1 lives in chunk[1] (idx=1, beat 16).
    // Locator at beat 24 → shift = 24 - 16 = 8.
    const m = buildManifest();
    m.musical_bar_1_chunk_index = 1;
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: 'downbeat', time: 24 }]
    });
    const dir = seedTrackDir(m);
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), true);

    const atoms = (maxApi.state.outlets[2] || [])[0];
    assert.equal(Number(atoms[1]), 8, 'shift should be locator − bar1Idx*chunkBeats');
});

test('anchor: locator beat outside original grid still shifts (no bail)', () => {
    // Pure shift cares nothing about grid extent — locator at beat 100 just
    // produces a large shift. Caller (Live) handles negative-clamp on its end.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: '', time: 100 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), true);
    const atoms = (maxApi.state.outlets[2] || [])[0];
    assert.equal(Number(atoms[1]), 100);
});
