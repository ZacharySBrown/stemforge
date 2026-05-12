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
