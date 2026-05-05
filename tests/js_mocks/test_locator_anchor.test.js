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
//   bars=4, beats_per_bar=4 → chunkBeats=16, chunkPeriodSec=10.6667
//   barSeconds = 4 * 60/90 = 2.6667
//   secPerBeat = 60/90 = 0.6667
//   first_downbeat_sec = 0.5 (where the OLD grid puts bar 1)
//   chunk[0] @ source_offset_sec=0.5
//   chunk[1] @ source_offset_sec=11.1667 (= 0.5 + 10.6667)
//   chunk[2] @ source_offset_sec=21.8333
function buildManifest() {
    return {
        bpm: 90.0,
        bars: 4,
        beats_per_bar: 4,
        first_downbeat_sec: 0.5,
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
    assert.equal(typeof t._parseBarFromLocatorName, 'function');
    assert.equal(typeof t._sourceTimeAtTimelineBeat, 'function');
    assert.equal(typeof t._join, 'function');
});

// ── _parseBarFromLocatorName ────────────────────────────────────────────────

test('_parseBarFromLocatorName: empty / null defaults to bar 1', () => {
    const ctx = freshSandbox();
    const { _parseBarFromLocatorName } = getTestExports(ctx);
    assert.equal(_parseBarFromLocatorName(''), 1);
    assert.equal(_parseBarFromLocatorName(null), 1);
    assert.equal(_parseBarFromLocatorName(undefined), 1);
});

test('_parseBarFromLocatorName: bare integer string', () => {
    const ctx = freshSandbox();
    const { _parseBarFromLocatorName } = getTestExports(ctx);
    assert.equal(_parseBarFromLocatorName('1'), 1);
    assert.equal(_parseBarFromLocatorName('4'), 4);
    assert.equal(_parseBarFromLocatorName('17'), 17);
});

test('_parseBarFromLocatorName: extracts first integer from common patterns', () => {
    const ctx = freshSandbox();
    const { _parseBarFromLocatorName } = getTestExports(ctx);
    assert.equal(_parseBarFromLocatorName('bar 4'), 4);
    assert.equal(_parseBarFromLocatorName('Bar 4'), 4);
    assert.equal(_parseBarFromLocatorName('m4'), 4);
    assert.equal(_parseBarFromLocatorName('downbeat 1'), 1);
    assert.equal(_parseBarFromLocatorName('4 bar'), 4); // first integer wins
});

test('_parseBarFromLocatorName: non-numeric names default to bar 1', () => {
    const ctx = freshSandbox();
    const { _parseBarFromLocatorName } = getTestExports(ctx);
    assert.equal(_parseBarFromLocatorName('verse'), 1);
    assert.equal(_parseBarFromLocatorName('chorus'), 1);
    assert.equal(_parseBarFromLocatorName('anchor'), 1);
});

test('_parseBarFromLocatorName: zero or negative integers fall back to 1', () => {
    const ctx = freshSandbox();
    const { _parseBarFromLocatorName } = getTestExports(ctx);
    assert.equal(_parseBarFromLocatorName('0'), 1);
    // Regex `(\d+)` rejects the minus sign — '-3' → matches '3' → 3.
    assert.equal(_parseBarFromLocatorName('-3'), 3);
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

// Helpers for outlet-1 inspection (the shell-call path).
function shellAtomsOf(call) {
    // outlet(1, PYTHON_BIN, HELPER_PATH, "--track-dir", dir, "--bpm", tempo,
    //        "--first-downbeat", newDB, "--manifest-out", manifestPath)
    // Returns a flat parsed object for assertions.
    const flat = {
        python: call[0],
        helper: call[1],
        argv: call.slice(2),
    };
    flat.flags = {};
    for (let i = 0; i < flat.argv.length; i += 2) {
        flat.flags[flat.argv[i]] = flat.argv[i + 1];
    }
    return flat;
}

test('anchor: idempotent no-op when locator marks the existing bar 1', () => {
    // Locator at beat 0 → source = chunk[0].source_offset_sec = 0.5
    //                  = manifest.first_downbeat_sec.
    // adjustedSourceSec = 0.5 (default bar 1, no name digit).
    // newFirstDownbeat = 0.5. delta = 0 < 5ms → no-op.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: 'anchor', time: 0 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), false, 'locator on existing bar 1 should no-op');

    // Neither outlet should fire when no work to do.
    assert.equal((maxApi.state.outlets[1] || []).length, 0,
        'idempotent no-op must not spawn the helper');
    assert.equal((maxApi.state.outlets[2] || []).length, 0,
        'idempotent no-op must not emit on outlet 2');
});

test('anchor: emits shell atoms on outlet 1 when locator differs from old bar 1', () => {
    // Locator at beat 18 → source 11.1667 + 2*0.6667 = 12.5s.
    // adjustedSourceSec = 12.5 (default bar 1, no snap math).
    // newFirstDownbeat = 12.5 (direct, no `mod chunkPeriodSec`).
    // Δ = 12.5 - 0.5 = 12.0s, well above 5ms idempotency threshold.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: 'anchor', time: 18 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), true);

    const calls = maxApi.state.outlets[1] || [];
    assert.equal(calls.length, 1, 'expected one shell emission on outlet 1');
    const atoms = shellAtomsOf(calls[0]);
    assert.equal(atoms.flags['--track-dir'], dir);
    assert.equal(Number(atoms.flags['--bpm']), 90);
    assert.ok(Math.abs(Number(atoms.flags['--first-downbeat']) - 12.5) < 1e-3,
        'expected newFirstDownbeat = adjustedSourceSec ≈ 12.5, got ' +
        atoms.flags['--first-downbeat']);
    assert.equal(atoms.flags['--manifest-out'], dir + '/prechop_manifest.json');

    // outlet 2 only fires from onAnchorComplete (after the helper finishes),
    // not from anchor() itself.
    assert.equal((maxApi.state.outlets[2] || []).length, 0,
        'outlet 2 must be silent during anchor() — only fires from onAnchorComplete');
});

test('anchor: Live tempo wins over manifest BPM in --bpm arg', () => {
    // No-snap math: newFirstDownbeat = adjustedSourceSec = 12.5,
    // independent of Live tempo (since no name digit, default bar 1, no
    // (N-1)*barSeconds adjustment that depends on tempo).
    // The test verifies BPM passes through as Live's, not manifest's.
    const ctx = freshSandbox({
        tempo: 120,
        cuePoints: [{ name: 'anchor', time: 18 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), true);

    const atoms = shellAtomsOf((maxApi.state.outlets[1] || [])[0]);
    assert.equal(Number(atoms.flags['--bpm']), 120,
        'Live tempo (120) must override manifest bpm (90) in --bpm arg');
    assert.ok(Math.abs(Number(atoms.flags['--first-downbeat']) - 12.5) < 1e-3,
        'expected newFirstDownbeat ≈ 12.5 (no-snap), got ' +
        atoms.flags['--first-downbeat']);
});

// ── onAnchorComplete: timeline shift to align bar-1 chunk with locator ──────

test('onAnchorComplete: emits manifest path + shift atom on outlet 2', () => {
    // anchor() stashes locator beat. onAnchorComplete reads the (just-rewritten)
    // manifest and computes shift = locatorBeat - bar1Idx * chunkBeats so the
    // new bar-1 chunk lands at the locator's timeline position.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: 'anchor', time: 18 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    anchor();  // stashes PENDING_LOCATOR_BEAT = 18

    // Simulate the helper rewriting the manifest with a leading partial:
    // bar1Idx = 1, bars = 4, beats_per_bar = 4 → chunkBeats = 16.
    const newManifest = buildManifest();
    newManifest.musical_bar_1_chunk_index = 1;
    maxApi.seedFile(SYNTHETIC_MANIFEST, JSON.stringify(newManifest));

    // Helper would emit anchor_complete <manifestPath> via NDJSON; the
    // patcher routes that to onAnchorComplete().
    ctx.onAnchorComplete(SYNTHETIC_MANIFEST);

    const reloadCalls = maxApi.state.outlets[2] || [];
    assert.equal(reloadCalls.length, 1, 'expected one reload on outlet 2');
    const [path, shift] = reloadCalls[0];
    assert.equal(path, SYNTHETIC_MANIFEST);
    // shift = 18 - 1*16 = 2 → bar 1 chunk lands at timeline beat 18 (= locator)
    assert.equal(Number(shift), 2,
        'shift should align bar 1 chunk with locator timeline position');
});

test('onAnchorComplete: clamps negative shift to 0 (when bar1Idx pre-roll exceeds locator beat)', () => {
    // Locator at beat 8 with bar1Idx = 2 (partial + 1 pre-chunk) → shift
    // would be 8 - 2*16 = -24 (negative). Clamp to 0 with status warning.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: 'anchor', time: 8 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    anchor();

    const newManifest = buildManifest();
    newManifest.musical_bar_1_chunk_index = 2;  // partial + 1 pre-chunk
    maxApi.seedFile(SYNTHETIC_MANIFEST, JSON.stringify(newManifest));

    ctx.onAnchorComplete(SYNTHETIC_MANIFEST);

    const reloadCalls = maxApi.state.outlets[2] || [];
    assert.equal(reloadCalls.length, 1);
    assert.equal(Number(reloadCalls[0][1]), 0, 'negative shift must clamp to 0');
});

test('anchor: named locator subtracts (N-1)*barSeconds from adjustedSourceSec', () => {
    // Locator at beat 16 named "2" (= "this is bar 2 of the song").
    // locatorSourceSec = 11.1667. barSeconds @ 90 BPM = 2.6667.
    // adjustedSourceSec = 11.1667 - 1 * 2.6667 = 8.5.
    // relSec = 8.5 - 0.5 = 8.0.
    // chunkPeriodSec = 10.6667. offsetWithinChunk = 8.0 % 10.6667 = 8.0.
    // 8.0 > 5.333 → snap back: signedOffset = 8.0 - 10.6667 = -2.6667.
    // newFirstDownbeat = 0.5 - 2.6667 → NEGATIVE → wrap: -2.1667 + 10.6667 = 8.5.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: '2', time: 16 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), true);

    const atoms = shellAtomsOf((maxApi.state.outlets[1] || [])[0]);
    assert.ok(Math.abs(Number(atoms.flags['--first-downbeat']) - 8.5) < 1e-3,
        'expected newFirstDownbeat ≈ 8.5 with named locator "2", got '
        + atoms.flags['--first-downbeat']);
});

test('anchor: bails when named locator pushes adjusted bar 1 negative', () => {
    // Locator at beat 0 (source 0.5s) named "5". adjustedSourceSec =
    // 0.5 - 4 * 2.6667 = -10.1667 → negative → bail with status, no shell.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: '5', time: 0 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), false);

    assert.equal((maxApi.state.outlets[1] || []).length, 0);
});

test('anchor: locator beat outside original grid bails (no shell)', () => {
    // 3 chunks * 16 chunkBeats = 48; beat 100 falls outside the grid.
    // _sourceTimeAtTimelineBeat returns null → anchor() bails.
    const ctx = freshSandbox({
        tempo: 90,
        cuePoints: [{ name: '', time: 100 }]
    });
    const dir = seedTrackDir(buildManifest());
    const { anchor, trackDir } = getTestExports(ctx);
    trackDir(dir);
    assert.equal(anchor(), false);
    assert.equal((maxApi.state.outlets[1] || []).length, 0);
});
