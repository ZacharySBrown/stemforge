// test_loader_dispatch.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Stream E #6 (added 2026-05-07): static sentinels for the loader dispatcher.
//
// 2026-05-06 we deleted the v1 (`_loadCuratedManifest`) and v2
// (`_loadCuratedV2`) loader paths from `stemforge_loader.v0.js`. Production-
// mode `loadSong()` is the only supported layout. Non-production manifests
// must surface a clear error rather than silently falling through.
//
// This file does NOT load the loader into a sandbox — it would require the
// full LiveAPI mock surface (~1000 LOC of state + clip APIs) to exercise
// loadFromDict end-to-end. Instead we read the source and assert the right
// dispatcher shape: production routes to loadSong, anything else surfaces
// an error, and the legacy entry points are gone.
//
// Run:   node tests/js_mocks/test_loader_dispatch.test.js
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs = require('fs');
const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const LOADER_SOURCE = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js', 'stemforge_loader.v0.js');
const LOADER_PKG_COPY = path.join(
    REPO_ROOT, 'v0', 'src', 'm4l-package', 'StemForge', 'javascript', 'stemforge_loader.v0.js'
);

const src = fs.readFileSync(LOADER_SOURCE, 'utf8');
const pkgSrc = fs.readFileSync(LOADER_PKG_COPY, 'utf8');


// ── Production-mode is the supported path ───────────────────────────────────

test('loadFromDict() exists and dispatches to loadSong on production manifests', () => {
    // The dispatcher entry point.
    assert.match(src, /function loadFromDict\(\)/,
        'loadFromDict must exist as the dict-based entry point');
    // Routes to loadSong when layout_mode === "production".
    assert.match(src, /mf\.layout_mode === "production"/,
        'dispatcher must check layout_mode === "production"');
    assert.match(src, /detected production manifest/,
        'dispatcher must log when it detects production layout');
    assert.match(src, /loadSong\(\)/,
        'dispatcher must call loadSong() for production manifests');
});

test('loadFromDict() rejects non-production manifests with a clear error', () => {
    // The fail-fast branch surfaces a status message that points the user
    // at the curate command they need to run. We grep for the actionable
    // hint text that landed 2026-05-06.
    assert.match(src, /Re-curate with/,
        'rejection branch must tell the user how to recover');
    assert.match(src, /production_idm\.yaml/,
        'rejection branch must name the pipeline that fixes it');
});


// ── Legacy paths are gone ────────────────────────────────────────────────────

test('legacy v1 loader (_loadCuratedManifest) is removed', () => {
    // The v1 flat-bars loader and its public path-based entry are deleted.
    // We allow the IDENTIFIER to appear in *comments* (the loadFromDict
    // header documents the removal), but no function definition or call.
    const codeOnly = src
        .split('\n')
        .filter(line => !line.trim().startsWith('//'))
        .join('\n');
    assert.doesNotMatch(codeOnly, /function _loadCuratedManifest/,
        '_loadCuratedManifest function must be removed');
    assert.doesNotMatch(codeOnly, /function loadCuratedBars/,
        'loadCuratedBars public entry must be removed');
});

test('legacy v2 loader (_loadCuratedV2) is removed', () => {
    const codeOnly = src
        .split('\n')
        .filter(line => !line.trim().startsWith('//'))
        .join('\n');
    assert.doesNotMatch(codeOnly, /function _loadCuratedV2/,
        '_loadCuratedV2 function must be removed');
    assert.doesNotMatch(codeOnly, /function loadCuratedV2/,
        'loadCuratedV2 public entry must be removed');
    assert.doesNotMatch(codeOnly, /function loadV2FromDict/,
        'loadV2FromDict public entry must be removed');
});

test('v2-only helpers are removed (RACK_TEMPLATES, createMidiTrack, loadSimplerSample)', () => {
    const codeOnly = src
        .split('\n')
        .filter(line => !line.trim().startsWith('//'))
        .join('\n');
    assert.doesNotMatch(codeOnly, /var RACK_TEMPLATES =/,
        'RACK_TEMPLATES constant should be removed (only used by _loadCuratedV2)');
    assert.doesNotMatch(codeOnly, /function createMidiTrack/,
        'createMidiTrack should be removed (only used by _loadCuratedV2)');
    assert.doesNotMatch(codeOnly, /function loadSimplerSample/,
        'loadSimplerSample should be removed (only used by _loadCuratedV2)');
});


// ── JS-dual-location sync (per the project's "JS Dual Location Sync" rule) ──

test('source and package copies of stemforge_loader.v0.js are byte-identical', () => {
    // Per CLAUDE.md memory: edits to v0/src/m4l-js/ must be mirrored to
    // v0/src/m4l-package/StemForge/javascript/. Drift here is a deploy
    // failure mode (the installed pkg ships stale JS).
    assert.equal(src, pkgSrc,
        'v0/src/m4l-js/stemforge_loader.v0.js and the m4l-package copy diverged');
});
