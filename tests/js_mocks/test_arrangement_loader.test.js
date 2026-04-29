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
