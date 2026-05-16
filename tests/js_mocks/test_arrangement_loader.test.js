// test_arrangement_loader.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Offline regression tests for v0/src/m4l-js/sf_arrangement_loader.js.
//
// Run:   node tests/js_mocks/test_arrangement_loader.test.js
//
// We can't unit-test the LOM-touching code path (clip creation, track
// resolution) without a deeper Live mock — those are exercised in Ableton.
// What we CAN test offline are the pure helpers (path resolution, beats
// math). That catches the most common regression surfaces (path-join
// off-by-one, beat-math BPM swap) without standing up a full LiveAPI stub.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, maxApi } = require('./sandbox');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const JS_DIR = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js');
const SF_ARRANGEMENT_LOADER = path.join(JS_DIR, 'sf_arrangement_loader.js');

function freshSandbox() {
    maxApi.resetState();
    const ctx = createSandbox();
    loadModule(ctx, SF_ARRANGEMENT_LOADER);
    return ctx;
}

function getTestExports(ctx) {
    return ctx.module.exports.__test__;
}

test('module loads and exposes test helpers', () => {
    const ctx = freshSandbox();
    const t = getTestExports(ctx);
    assert.ok(t);
    assert.equal(typeof t.runArrangementLoad, 'function');
    assert.equal(typeof t._alJoin, 'function');
    assert.equal(typeof t._alDirname, 'function');
    assert.equal(typeof t._alSecToBeats, 'function');
    assert.equal(typeof t._alExpandTilde, 'function');
});

test('_alJoin: relative path resolves against directory', () => {
    const ctx = freshSandbox();
    const { _alJoin } = getTestExports(ctx);
    assert.equal(
        _alJoin('/Users/zak/song', 'drums_prechop/drums_chunk_001.wav'),
        '/Users/zak/song/drums_prechop/drums_chunk_001.wav'
    );
    assert.equal(
        _alJoin('/Users/zak/song/', 'drums_prechop/drums_chunk_001.wav'),
        '/Users/zak/song/drums_prechop/drums_chunk_001.wav'
    );
});

test('_alJoin: absolute path wins', () => {
    const ctx = freshSandbox();
    const { _alJoin } = getTestExports(ctx);
    assert.equal(
        _alJoin('/Users/zak/song', '/abs/elsewhere.wav'),
        '/abs/elsewhere.wav'
    );
});

test('_alDirname: parent of an absolute path', () => {
    const ctx = freshSandbox();
    const { _alDirname } = getTestExports(ctx);
    assert.equal(
        _alDirname('/Users/zak/song/prechop_manifest.json'),
        '/Users/zak/song'
    );
    assert.equal(_alDirname('/file.json'), '/');
});

test('_alSecToBeats: converts seconds to beats given BPM', () => {
    const ctx = freshSandbox();
    const { _alSecToBeats } = getTestExports(ctx);
    // 120 BPM → 2 beats/sec → 8 sec = 16 beats.
    assert.equal(_alSecToBeats(8, 120), 16);
    // 0 sec → 0 beats.
    assert.equal(_alSecToBeats(0, 120), 0);
    // Negative or NaN → 0 (defensive clamp).
    assert.equal(_alSecToBeats(-1, 120), 0);
    assert.equal(_alSecToBeats(NaN, 120), 0);
});

test('_alExpandTilde: ~ expands to home; absolute paths pass through', () => {
    const ctx = freshSandbox();
    const { _alExpandTilde } = getTestExports(ctx);
    const expanded = _alExpandTilde('~/foo/bar.json');
    // The mock max.getsystemvariable returns "/Users/<x>" — we only assert
    // the prefix replacement happened (no leading ~) and the suffix is intact.
    assert.ok(
        expanded.indexOf('~') === -1 && expanded.endsWith('/foo/bar.json'),
        `expected expanded path, got ${expanded}`
    );
    // Already absolute — unchanged.
    assert.equal(_alExpandTilde('/already/abs.json'), '/already/abs.json');
});

test('runArrangementLoad rejects empty manifest path', () => {
    const ctx = freshSandbox();
    const { runArrangementLoad } = getTestExports(ctx);
    assert.equal(runArrangementLoad(''), false);
    assert.equal(runArrangementLoad(null), false);
    assert.equal(runArrangementLoad(undefined), false);
});

// Regression: real forges + the sample-forge fixture write arrangement
// manifests as a flat chunks[] array (no nested stems{}). The adapter
// fans them out per-stem; without it, runArrangementLoad emitted
// "Arrangement load failed" with zero diagnostics. Caught 2026-05-15
// driving Live via Computer Use against
// /Users/zak/stemforge/processed/breaks-n-beats-deck/arrangement_manifest.json.
test('_alAdaptChunksToStems: groups by stem, maps field names, preserves bar_position', () => {
    const ctx = freshSandbox();
    const { _alAdaptChunksToStems } = getTestExports(ctx);
    const adapted = _alAdaptChunksToStems([
        { stem: 'drum', audio_path: 'arrangement_chunks/drum-intro.wav',
          bar_position: 0, duration_bars: 8, duration_sec: 14.2,
          chunk_id: 'drum-intro' },
        { stem: 'drum', audio_path: '/abs/drum-verse.wav',
          bar_position: 8, duration_bars: 16, duration_sec: 28.4,
          chunk_id: 'drum-verse' },
        { stem: 'bass', audio_path: 'arrangement_chunks/bass-intro.wav',
          bar_position: 0, duration_bars: 8, duration_sec: 14.2,
          chunk_id: 'bass-intro' },
    ]);
    assert.deepEqual(Object.keys(adapted).sort(), ['bass', 'drum']);
    assert.equal(adapted.drum.chunks.length, 2);
    assert.equal(adapted.bass.chunks.length, 1);
    // Field-name mapping intact.
    assert.equal(adapted.drum.chunks[0].file, 'arrangement_chunks/drum-intro.wav');
    assert.equal(adapted.drum.chunks[0].bars, 8);
    assert.equal(adapted.drum.chunks[0].total_sec, 14.2);
    assert.equal(adapted.drum.chunks[0].start_bar, 0);
    // Absolute audio_path preserved (matches _alJoin's absolute-path behavior).
    assert.equal(adapted.drum.chunks[1].file, '/abs/drum-verse.wav');
    assert.equal(adapted.drum.chunks[1].start_bar, 8);
});

test('_alAdaptChunksToStems: handles missing/malformed entries gracefully', () => {
    const ctx = freshSandbox();
    const { _alAdaptChunksToStems } = getTestExports(ctx);
    // Cross-realm deepEqual against literal {} is finicky (different
    // prototypes). Assert key count instead.
    assert.equal(Object.keys(_alAdaptChunksToStems(null)).length, 0);
    assert.equal(Object.keys(_alAdaptChunksToStems(undefined)).length, 0);
    assert.equal(Object.keys(_alAdaptChunksToStems('not-an-array')).length, 0);
    // Entries without stem or audio_path are dropped (not crash).
    const adapted = _alAdaptChunksToStems([
        null,
        { stem: 'drum' }, // no audio_path
        { audio_path: 'x.wav' }, // no stem
        { stem: 'vocal', audio_path: 'v.wav' }, // valid
    ]);
    assert.deepEqual(Object.keys(adapted), ['vocal']);
    assert.equal(adapted.vocal.chunks.length, 1);
});

test('_alAdaptChunksToStems: bar_position is nullable (legacy chunks without positional info)', () => {
    const ctx = freshSandbox();
    const { _alAdaptChunksToStems } = getTestExports(ctx);
    const adapted = _alAdaptChunksToStems([
        { stem: 'drum', audio_path: 'a.wav', duration_bars: 4 },
        { stem: 'drum', audio_path: 'b.wav', duration_bars: 4 },
    ]);
    // When bar_position is absent, start_bar is null → _alLoadStem falls
    // back to sequential `i * bars` positioning (preserving legacy behavior).
    assert.equal(adapted.drum.chunks[0].start_bar, null);
    assert.equal(adapted.drum.chunks[1].start_bar, null);
});

// ── Stem-name aliasing (plural ↔ singular) ─────────────────────────────────
// Regression for ANCH → reload creating duplicate "drums"/"vocals" tracks:
// LOAD FORGE writes singular-named tracks ("definition | drum"), the
// prechop manifest emits plural stem keys, and the loader's substring
// match failed → fell through to _alCreateAudioTrack with the plural
// name. Caught 2026-05-15 after PR #125's ANCH button shipped.

test('_AL_STEM_ALIASES round-trips drum/drums and vocal/vocals', () => {
    const ctx = freshSandbox();
    const { _AL_STEM_ALIASES } = getTestExports(ctx);
    // JSON-roundtrip the vm-realm arrays into local-realm ones — Node's
    // strict deepEqual treats cross-realm Array instances as unequal.
    const aliases = JSON.parse(JSON.stringify(_AL_STEM_ALIASES));
    assert.deepEqual(aliases.drum, ['drum', 'drums']);
    assert.deepEqual(aliases.drums, ['drums', 'drum']);
    assert.deepEqual(aliases.vocal, ['vocal', 'vocals']);
    assert.deepEqual(aliases.vocals, ['vocals', 'vocal']);
    assert.deepEqual(aliases.bass, ['bass']);
    assert.deepEqual(aliases.other, ['other']);
});

test('_alFindTrackForStem("drums") matches a "definition | drum" track', () => {
    const ctx = freshSandbox();
    maxApi.seedLiveTree({
        tracks: [
            { _properties: { name: 'definition | drum',  has_audio_input: 1 } },
            { _properties: { name: 'definition | bass',  has_audio_input: 1 } },
            { _properties: { name: 'definition | other', has_audio_input: 1 } },
            { _properties: { name: 'definition | vocal', has_audio_input: 1 } },
        ],
    });
    const { _alFindTrackForStem } = getTestExports(ctx);

    // Prechop emits plural keys; the singular tracks must still resolve.
    assert.equal(_alFindTrackForStem('drums'), 0, "'drums' should find 'definition | drum'");
    assert.equal(_alFindTrackForStem('vocals'), 3, "'vocals' should find 'definition | vocal'");
});

test('_alFindTrackForStem("drum") matches a "definition | drums" track', () => {
    const ctx = freshSandbox();
    maxApi.seedLiveTree({
        tracks: [
            { _properties: { name: 'definition | drums',  has_audio_input: 1 } },
            { _properties: { name: 'definition | vocals', has_audio_input: 1 } },
        ],
    });
    const { _alFindTrackForStem } = getTestExports(ctx);

    // And the reverse — singular schema stems against pre-existing plural
    // tracks must also resolve (the LOAD FORGE side may rename in the future).
    assert.equal(_alFindTrackForStem('drum'), 0);
    assert.equal(_alFindTrackForStem('vocal'), 1);
});

test('_alFindTrackForStem returns -1 when no track matches either alias', () => {
    const ctx = freshSandbox();
    maxApi.seedLiveTree({
        tracks: [
            { _properties: { name: 'Main',  has_audio_input: 1 } },
            { _properties: { name: 'FORGE', has_audio_input: 1 } },
        ],
    });
    const { _alFindTrackForStem } = getTestExports(ctx);
    assert.equal(_alFindTrackForStem('drum'), -1);
    assert.equal(_alFindTrackForStem('vocals'), -1);
});
