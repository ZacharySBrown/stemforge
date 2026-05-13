// test_bounce.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tests for _bounceCropTrack — specifically the loop-region collapse behavior
// added 2026-05-11. When a clip is looping, the bounce should write the loop
// bounds onto start_marker/end_marker BEFORE calling crop, so that the
// resulting cropped WAV contains exactly the loop region. When a clip is not
// looping, the markers must be left alone.
//
// Mirrors the harness style from test_commit.test.js (sandbox + seeded
// liveTree + assertion against state.liveApiCalls / node._properties).
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, maxApi } = require('./sandbox');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SF_LOADER = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js', 'stemforge_loader.v0.js');

function makeTrack(name, clipSlots) {
    return { _properties: { name }, clip_slots: clipSlots || [] };
}

function makeClipSlot(clipProps) {
    if (clipProps === null || clipProps === undefined) return { _properties: {} };
    return { _properties: {}, clip: { _properties: clipProps } };
}

function loadBounce() {
    maxApi.resetState();
    const ctx = createSandbox();
    loadModule(ctx, SF_LOADER);
    return {
        ctx,
        bounceCropTrack: ctx._bounceCropTrack,
        collapseToLoopRegion: ctx._collapseToLoopRegion,
    };
}

// Convenience to walk the seeded tree and read a clip's _properties.
// The seeded tree's root has `tracks` directly (no `live_set` wrapper);
// _resolveNode in max_api.js just uses the first path seg as a sentinel
// and walks from the tree root for the rest.
function getClipProps(trackIdx, slotIdx) {
    const tree = maxApi.getLiveTree();
    if (!tree) return null;
    const tracks = tree.tracks;
    if (!tracks || !tracks[trackIdx]) return null;
    const slot = tracks[trackIdx].clip_slots && tracks[trackIdx].clip_slots[slotIdx];
    return slot && slot.clip && slot.clip._properties;
}

// ── 1. looping=1 + loop region differs from play region ─────────────────────

test('_bounceCropTrack: looping=1 + divergent loop bounds → markers rewritten before crop', () => {
    const { bounceCropTrack } = loadBounce();

    // Build a tree with one track "A" containing one clip:
    //   play region 0..8, loop region 2..6, warping=1 (so units are beats).
    const clip = {
        file_path: '/abs/clip.wav',
        warping: 1,
        start_marker: 0, end_marker: 8, length: 8,
        looping: 1, loop_start: 2, loop_end: 6,
    };
    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot(clip)])],
    });

    // Snapshot crop firings — record marker state at each call.
    const cropFires = [];
    maxApi.setLiveCallHandler('crop', function (lomPath) {
        // Pull the live state at the moment crop fires.
        const props = getClipProps(0, 0);
        cropFires.push({
            path: lomPath,
            start_marker: props.start_marker,
            end_marker: props.end_marker,
        });
        return 0;
    });

    let onDoneCalled = false;
    bounceCropTrack('A', function (ok /* , msg */) { onDoneCalled = ok; });

    assert.equal(onDoneCalled, true, 'onDone should be called with ok=true');
    assert.equal(cropFires.length, 1, 'crop should fire exactly once');
    assert.equal(cropFires[0].start_marker, 2,
        'start_marker should be loop_start (2) when crop fires');
    assert.equal(cropFires[0].end_marker, 6,
        'end_marker should be loop_end (6) when crop fires');
});

// ── 2. looping=0 → markers untouched (current behavior preserved) ────────────

test('_bounceCropTrack: looping=0 → markers untouched, crop sees play region', () => {
    const { bounceCropTrack } = loadBounce();

    const clip = {
        file_path: '/abs/clip.wav',
        warping: 1,
        start_marker: 0, end_marker: 8, length: 8,
        looping: 0, loop_start: 2, loop_end: 6,  // loop bounds present but ignored
    };
    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot(clip)])],
    });

    const cropFires = [];
    maxApi.setLiveCallHandler('crop', function (lomPath) {
        const props = getClipProps(0, 0);
        cropFires.push({
            start_marker: props.start_marker,
            end_marker: props.end_marker,
        });
        return 0;
    });

    bounceCropTrack('A', function () {});

    assert.equal(cropFires.length, 1, 'crop should fire once');
    assert.equal(cropFires[0].start_marker, 0,
        'start_marker untouched at 0 when looping=0');
    assert.equal(cropFires[0].end_marker, 8,
        'end_marker untouched at 8 when looping=0');
});

// ── 3. looping=1 but loop bounds == play bounds → no-op write, safe ──────────

test('_bounceCropTrack: looping=1 + loop bounds == play bounds → idempotent', () => {
    const { bounceCropTrack } = loadBounce();

    const clip = {
        file_path: '/abs/clip.wav',
        warping: 1,
        start_marker: 0, end_marker: 4, length: 4,
        looping: 1, loop_start: 0, loop_end: 4,
    };
    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot(clip)])],
    });

    const cropFires = [];
    maxApi.setLiveCallHandler('crop', function () {
        const props = getClipProps(0, 0);
        cropFires.push({ start_marker: props.start_marker, end_marker: props.end_marker });
    });

    bounceCropTrack('A', function () {});

    assert.equal(cropFires.length, 1);
    assert.equal(cropFires[0].start_marker, 0);
    assert.equal(cropFires[0].end_marker, 4);
});

// ── 4. Invalid loop bounds (le ≤ ls) → skip rewrite (safety) ─────────────────

test('_bounceCropTrack: looping=1 with le<=ls → skip rewrite (safety guard)', () => {
    const { bounceCropTrack } = loadBounce();

    const clip = {
        file_path: '/abs/clip.wav',
        warping: 1,
        start_marker: 0, end_marker: 4, length: 4,
        looping: 1, loop_start: 5, loop_end: 5,  // degenerate: le == ls
    };
    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot(clip)])],
    });

    const cropFires = [];
    maxApi.setLiveCallHandler('crop', function () {
        const props = getClipProps(0, 0);
        cropFires.push({ start_marker: props.start_marker, end_marker: props.end_marker });
    });

    bounceCropTrack('A', function () {});

    assert.equal(cropFires.length, 1);
    assert.equal(cropFires[0].start_marker, 0,
        'degenerate loop bounds must NOT overwrite markers');
    assert.equal(cropFires[0].end_marker, 4,
        'degenerate loop bounds must NOT overwrite markers');
});

// ── 5. _collapseToLoopRegion direct unit test ────────────────────────────────

test('_collapseToLoopRegion: unit — looping=1 writes loop bounds to markers', () => {
    const { ctx, collapseToLoopRegion } = loadBounce();

    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot({
            warping: 1,
            start_marker: 1, end_marker: 9,
            looping: 1, loop_start: 3, loop_end: 7,
        })])],
    });
    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    collapseToLoopRegion(clipApi);

    const props = getClipProps(0, 0);
    assert.equal(props.start_marker, 3);
    assert.equal(props.end_marker, 7);
});

test('_collapseToLoopRegion: unit — looping=0 leaves markers alone', () => {
    const { ctx, collapseToLoopRegion } = loadBounce();

    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot({
            warping: 1,
            start_marker: 1, end_marker: 9,
            looping: 0, loop_start: 3, loop_end: 7,
        })])],
    });
    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    collapseToLoopRegion(clipApi);

    const props = getClipProps(0, 0);
    assert.equal(props.start_marker, 1, 'untouched when looping=0');
    assert.equal(props.end_marker, 9, 'untouched when looping=0');
});

// ── 6. 2nd-bounce defensive guards on _collapseToLoopRegion ─────────────────
//
// docs/issues/loop-region-collapse-second-bounce.md: when a clip is bounced a
// 2nd time without reloading, Live's loop_start/loop_end behavior is unverified.
// The guards in _collapseToLoopRegion make the helper safe-by-construction:
//
//   (a) skip when loop bounds == play bounds (Mode 2 no-op — avoids any LOM
//       side effect from a same-value write).
//   (b) skip when loop bounds fall outside the play region (Mode 3 stale-
//       coordinate garbage), and emit a `post()` warning.
//   (c) skip when loop_start < 0 (defensive — impossible in practice).
//
// These tests assert each guard fires by verifying the markers are not
// rewritten when the guard should apply.
//
// Strategy: wrap LiveAPI.prototype.set to count set() calls against the clip
// path, so we can assert "no write happened" rather than just "value
// happened to equal the pre-state".

function instrumentSetSpy(ctx) {
    var spy = { calls: [] };
    var origSet = ctx.LiveAPI.prototype.set;
    ctx.LiveAPI.prototype.set = function (prop, value) {
        spy.calls.push({ path: this._path, prop: prop, value: value });
        return origSet.call(this, prop, value);
    };
    spy.restore = function () { ctx.LiveAPI.prototype.set = origSet; };
    return spy;
}

test('_collapseToLoopRegion: skips when already collapsed (loop bounds == play bounds)', () => {
    const { ctx, collapseToLoopRegion } = loadBounce();

    // Non-trivial bounds — loop region exactly matches play region.
    // Simulates Mode 1 after one crop (or Mode 2 reset).
    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot({
            warping: 1,
            start_marker: 2, end_marker: 6,
            looping: 1, loop_start: 2, loop_end: 6,
        })])],
    });

    const spy = instrumentSetSpy(ctx);
    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    collapseToLoopRegion(clipApi);
    spy.restore();

    // The guard must skip ENTIRELY — no set() against start_marker or
    // end_marker, not even a same-value no-op write.
    const markerWrites = spy.calls.filter(c =>
        c.prop === 'start_marker' || c.prop === 'end_marker'
    );
    assert.equal(markerWrites.length, 0,
        'no marker writes when loop bounds already match play bounds; ' +
        'got ' + JSON.stringify(markerWrites));

    // And of course the seeded values stay put.
    const props = getClipProps(0, 0);
    assert.equal(props.start_marker, 2);
    assert.equal(props.end_marker, 6);
});

test('_collapseToLoopRegion: skips + warns when loop_end > end_marker (stale Mode 3)', () => {
    const { ctx, collapseToLoopRegion } = loadBounce();

    // Simulates Mode 3: clip was cropped once (extent now 0..4) but Live
    // preserved the pre-crop loop region at OLD coordinates (2..6). Writing
    // loop_end=6 to end_marker would corrupt the 2nd bounce.
    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot({
            warping: 1,
            start_marker: 0, end_marker: 4,
            looping: 1, loop_start: 2, loop_end: 6,
        })])],
    });

    const spy = instrumentSetSpy(ctx);
    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    collapseToLoopRegion(clipApi);
    spy.restore();

    const markerWrites = spy.calls.filter(c =>
        c.prop === 'start_marker' || c.prop === 'end_marker'
    );
    assert.equal(markerWrites.length, 0,
        'markers must NOT be touched when loop bounds exceed play region');

    // Markers must still be at the seeded values.
    const props = getClipProps(0, 0);
    assert.equal(props.start_marker, 0);
    assert.equal(props.end_marker, 4);

    // Warning must appear on the Max console (state.logs is the post()
    // capture buffer).
    const warning = maxApi.state.logs.find(s =>
        s.indexOf('outside play region') >= 0
    );
    assert.ok(warning,
        'expected a post() warning about loop bounds outside play region; ' +
        'logs were: ' + JSON.stringify(maxApi.state.logs));
});

test('_collapseToLoopRegion: skips when loop_start < 0 (defensive)', () => {
    const { ctx, collapseToLoopRegion } = loadBounce();

    // loop_start < 0 is impossible in real Live usage but the guard exists
    // to make the function safe-by-construction against any corrupted state.
    maxApi.seedLiveTree({
        tracks: [makeTrack('A', [makeClipSlot({
            warping: 1,
            start_marker: 0, end_marker: 8,
            looping: 1, loop_start: -1, loop_end: 4,
        })])],
    });

    const spy = instrumentSetSpy(ctx);
    const clipApi = new ctx.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    collapseToLoopRegion(clipApi);
    spy.restore();

    const markerWrites = spy.calls.filter(c =>
        c.prop === 'start_marker' || c.prop === 'end_marker'
    );
    assert.equal(markerWrites.length, 0,
        'markers must NOT be touched when loop_start is negative');

    const props = getClipProps(0, 0);
    assert.equal(props.start_marker, 0);
    assert.equal(props.end_marker, 8);
});

// ── 7. Atomic-rename stub flow ──────────────────────────────────────────────
// docs/issues/bounce-stub-race.md: _ensureDeckManifestStub writes to
// ``<path>.tmp`` (NOT the final path), and commitOffsets renames .tmp →
// final via an outlet-3 shell ``mv`` once _commitSessionTracks has filled
// in the manifest. Readers polling on the final path never see partial
// state.

test('_ensureDeckManifestStub: writes stub to <path>.tmp, not final path', () => {
    const { ctx } = loadBounce();
    const FINAL = '/tmp/atomic_rename_test/curated/manifest.json';

    // Pre-state: neither path exists.
    assert.equal(maxApi.state.fs[FINAL], undefined,
        'final path must not exist before stub write');
    assert.equal(maxApi.state.fs[FINAL + '.tmp'], undefined,
        '.tmp path must not exist before stub write');

    ctx._ensureDeckManifestStub(FINAL);

    // Post-state: .tmp populated, final still missing.
    const tmpEntry = maxApi.state.fs[FINAL + '.tmp'];
    assert.ok(tmpEntry, '.tmp must be written by _ensureDeckManifestStub');
    assert.ok(tmpEntry.contents.includes('"session_tracks"'),
        '.tmp must contain the stub structure');
    assert.equal(maxApi.state.fs[FINAL], undefined,
        'final path MUST stay unwritten so external pollers never race');
});

test('_tmpManifestPath: appends .tmp suffix', () => {
    const { ctx } = loadBounce();
    assert.equal(ctx._tmpManifestPath('/foo/bar/manifest.json'),
        '/foo/bar/manifest.json.tmp');
    assert.equal(ctx._tmpManifestPath('/x.json'), '/x.json.tmp');
});

// commitOffsets / _commitOffsetsWithPath were removed in Phase 3B (BOUNCE
// refactor). The disk-backed deck-manifest path they implemented belonged
// to the legacy A/B/C/D bounceTracks pipeline, which Phase 3B's
// bounceCuration() supersedes. The atomic-rename tests that used to live
// here are now covered by the curation-write path in
// stemforge/configurator/curation_io.py (write_curation_atomic +
// lock_curation), tested in tests/test_configurator_curation_crud.py.
