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

test('commitOffsets (disk-backed): reads from .tmp, writes to .tmp, schedules mv', () => {
    const { ctx } = loadBounce();
    const FINAL = '/tmp/atomic_rename_test2/curated/manifest.json';
    const TMP = FINAL + '.tmp';

    // Seed an existing stub at the .tmp path (no clips, just structure).
    maxApi.seedFile(TMP, JSON.stringify({
        bpm: 120,
        source_dir: '/tmp/atomic_rename_test2',
        session_tracks: { A: [], B: [], C: [], D: [] },
        clips: [],
    }));
    // Seed an empty live tree so _commitAllOffsets / _commitSessionTracks
    // have somewhere to traverse without crashing.
    maxApi.seedLiveTree({ tracks: [] });

    // Drive the disk-backed branch: commitOffsets reads `messagename` +
    // arguments via arrayfromargs(messagename, arguments). The sandbox's
    // arrayfromargs honors the multi-arg form, so setting messagename
    // and calling commitOffsets.call(ctx, FINAL) gets us through.
    ctx.messagename = 'commitOffsets';
    ctx.commitOffsets.call(ctx, FINAL);

    // After commit: .tmp has the populated manifest, final path is still
    // untouched (the mv goes via outlet 3 → [shell], which the mock just
    // records as outlet args, not as an actual rename).
    assert.ok(maxApi.state.fs[TMP], '.tmp must contain the committed manifest');
    assert.equal(maxApi.state.fs[FINAL], undefined,
        'final path stays unwritten in JS; mv runs via outlet-3 shell');

    // The mv call must appear on outlet 3 — that's the [shell] wire.
    const outlet3 = maxApi.state.outlets[3] || [];
    const mvCalls = outlet3.filter(args =>
        args[0] === '/bin/mv' && args.indexOf(TMP) >= 0 && args.indexOf(FINAL) >= 0
    );
    assert.equal(mvCalls.length, 1,
        'commitOffsets must emit exactly one /bin/mv outlet call for .tmp → final');
});

test('commitOffsets (disk-backed): falls back to final path if .tmp absent', () => {
    const { ctx } = loadBounce();
    const FINAL = '/tmp/atomic_rename_test3/curated/manifest.json';

    // Only the final path is seeded (legacy / external callers that
    // bypassed _ensureDeckManifestStub).
    maxApi.seedFile(FINAL, JSON.stringify({
        bpm: 120,
        source_dir: '/tmp/atomic_rename_test3',
        session_tracks: { A: [], B: [], C: [], D: [] },
        clips: [],
    }));
    maxApi.seedLiveTree({ tracks: [] });

    ctx.messagename = 'commitOffsets';
    // Shouldn't throw / shouldn't surface "cannot read" status — the
    // fallback read path must pick up the final-path content.
    ctx.commitOffsets.call(ctx, FINAL);

    // The .tmp gets the post-commit write since we always promote via mv.
    const TMP = FINAL + '.tmp';
    assert.ok(maxApi.state.fs[TMP],
        'commitOffsets must still write to .tmp even when seeded from final');
});
