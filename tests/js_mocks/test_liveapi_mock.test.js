// test_liveapi_mock.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tier-3 tests for the hardened LiveAPI mock (Hardening Stream B.2).
//
// What this proves:
//   1. Default LiveAPI (no liveTree seeded) is back-compat: all reads return
//      empty / no-op, matching the prior mock's behavior. Existing JS tests
//      that build their own LiveAPI continue to override seamlessly.
//   2. With a seeded liveTree, get/set/getcount work on real path traversal.
//   3. LOM read-only properties (warp_bpm, end_time) silently drop writes.
//   4. Marker-unit oracle (liveMarkerUnit) reflects warping flag.
//   5. Path traversal handles collections (arrays) AND singleton children.
//   6. The call() handler table dispatches by verb.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const maxApi = require('./max_api');

function freshState() {
    maxApi.resetState();
}

// ── Default behavior (unseeded tree = back-compat with prior no-op mock) ─────

test('LiveAPI with no liveTree returns empty/no-op for all calls', () => {
    freshState();
    const api = new maxApi.LiveAPI('live_set');
    assert.equal(api.getcount('tracks'), 0);
    assert.deepEqual(api.get('tempo'), []);
    api.set('tempo', 200);  // no-op, doesn't throw
    assert.equal(api.call('some_verb', 1, 2), 0);
});

// ── Property reads / writes ──────────────────────────────────────────────────

test('LiveAPI.get returns scalar wrapped in 1-element array (LOM convention)', () => {
    freshState();
    maxApi.seedLiveTree({
        _properties: { tempo: 120, signature_numerator: 4 },
    });
    const api = new maxApi.LiveAPI('live_set');
    assert.deepEqual(api.get('tempo'), [120]);
    assert.deepEqual(api.get('signature_numerator'), [4]);
});

test('LiveAPI.get on missing property returns empty array', () => {
    freshState();
    maxApi.seedLiveTree({ _properties: { tempo: 120 } });
    const api = new maxApi.LiveAPI('live_set');
    assert.deepEqual(api.get('does_not_exist'), []);
});

test('LiveAPI.set persists on the seeded node', () => {
    freshState();
    maxApi.seedLiveTree({ _properties: { tempo: 120 } });
    const api = new maxApi.LiveAPI('live_set');
    api.set('tempo', 145);
    assert.deepEqual(api.get('tempo'), [145]);
});

test('LiveAPI.set creates _properties bag if missing', () => {
    freshState();
    maxApi.seedLiveTree({ tracks: [{}] });
    const api = new maxApi.LiveAPI('live_set tracks 0');
    api.set('name', 'Drums');
    assert.equal(maxApi.getLiveProperty('live_set tracks 0', 'name'), 'Drums');
});

// ── getcount on collections ──────────────────────────────────────────────────

test('LiveAPI.getcount on a collection returns array length', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [
            { _properties: { name: 'A' } },
            { _properties: { name: 'B' } },
            { _properties: { name: 'C' } },
        ],
        cue_points: [{ _properties: { time: 0, name: 'Verse' } }],
    });
    const api = new maxApi.LiveAPI('live_set');
    assert.equal(api.getcount('tracks'), 3);
    assert.equal(api.getcount('cue_points'), 1);
    assert.equal(api.getcount('does_not_exist'), 0);
});

// ── Path traversal (collections + singletons) ────────────────────────────────

test('LiveAPI traverses collection-by-index paths', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [
            { _properties: { name: 'A' } },
            { _properties: { name: 'B' } },
        ],
    });
    const trackA = new maxApi.LiveAPI('live_set tracks 0');
    const trackB = new maxApi.LiveAPI('live_set tracks 1');
    assert.deepEqual(trackA.get('name'), ['A']);
    assert.deepEqual(trackB.get('name'), ['B']);
});

test('LiveAPI traverses singleton-child paths (clip_slot.clip)', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [
            {
                clip_slots: [
                    {
                        _properties: { has_clip: 1 },
                        clip: {
                            _properties: { file_path: '/abs/foo.wav', warping: 1 },
                        },
                    },
                ],
            },
        ],
    });
    const clipApi = new maxApi.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    assert.deepEqual(clipApi.get('file_path'), ['/abs/foo.wav']);
    assert.deepEqual(clipApi.get('warping'), [1]);
});

test('LiveAPI returns empty for out-of-range collection index', () => {
    freshState();
    maxApi.seedLiveTree({ tracks: [{ _properties: { name: 'A' } }] });
    const api = new maxApi.LiveAPI('live_set tracks 5');
    assert.deepEqual(api.get('name'), []);
    assert.equal(api.getcount('clip_slots'), 0);
});

test('LiveAPI.goto repoints to a new path', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [
            { _properties: { name: 'A' } },
            { _properties: { name: 'B' } },
        ],
    });
    const api = new maxApi.LiveAPI('live_set tracks 0');
    assert.deepEqual(api.get('name'), ['A']);
    api.goto('live_set tracks 1');
    assert.deepEqual(api.get('name'), ['B']);
});

// ── LOM read-only quirks ─────────────────────────────────────────────────────

test('LiveAPI.set on warp_bpm is silently dropped (LOM read-only)', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [
            {
                clip_slots: [
                    {
                        clip: {
                            _properties: { warp_bpm: 120 },
                        },
                    },
                ],
            },
        ],
    });
    const clip = new maxApi.LiveAPI('live_set tracks 0 clip_slots 0 clip');
    clip.set('warp_bpm', 160);
    // Original value preserved.
    assert.deepEqual(clip.get('warp_bpm'), [120]);
    // Drop is logged for assertions.
    assert.equal(maxApi.state.liveReadonlyDrops.length, 1);
    assert.equal(maxApi.state.liveReadonlyDrops[0].prop, 'warp_bpm');
    assert.equal(maxApi.state.liveReadonlyDrops[0].value, 160);
});

test('LiveAPI.set on end_time is silently dropped (LOM read-only)', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [{ arrangement_clips: [{ _properties: { end_time: 4.0 } }] }],
    });
    const clip = new maxApi.LiveAPI('live_set tracks 0 arrangement_clips 0');
    clip.set('end_time', 8.0);
    assert.deepEqual(clip.get('end_time'), [4.0]);
    assert.equal(maxApi.state.liveReadonlyDrops.length, 1);
    assert.equal(maxApi.state.liveReadonlyDrops[0].prop, 'end_time');
});

// ── Marker unit oracle ───────────────────────────────────────────────────────

test('liveMarkerUnit returns "beats" when warping=1 (default)', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [
            {
                clip_slots: [
                    { clip: { _properties: { warping: 1, start_marker: 4 } } },
                ],
            },
        ],
    });
    const unit = maxApi.liveMarkerUnit('live_set tracks 0 clip_slots 0 clip');
    assert.equal(unit, 'beats');
});

test('liveMarkerUnit returns "seconds" when warping=0', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [
            {
                clip_slots: [
                    { clip: { _properties: { warping: 0, start_marker: 1.5 } } },
                ],
            },
        ],
    });
    const unit = maxApi.liveMarkerUnit('live_set tracks 0 clip_slots 0 clip');
    assert.equal(unit, 'seconds');
});

test('liveMarkerUnit defaults to beats when warping unset', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [{ clip_slots: [{ clip: { _properties: {} } }] }],
    });
    const unit = maxApi.liveMarkerUnit('live_set tracks 0 clip_slots 0 clip');
    assert.equal(unit, 'beats');
});

// ── call() handler table ─────────────────────────────────────────────────────

test('LiveAPI.call dispatches to registered handler', () => {
    freshState();
    maxApi.seedLiveTree({});
    const seen = [];
    maxApi.setLiveCallHandler('create_clip', (lomPath, args) => {
        seen.push({ lomPath, args });
        return 42;
    });
    const api = new maxApi.LiveAPI('live_set tracks 0 clip_slots 0');
    const result = api.call('create_clip', '/abs/foo.wav', 4.0);
    assert.equal(result, 42);
    assert.equal(seen.length, 1);
    assert.equal(seen[0].lomPath, 'live_set tracks 0 clip_slots 0');
    assert.deepEqual(seen[0].args, ['/abs/foo.wav', 4.0]);
});

test('LiveAPI.call without handler returns 0 and logs the unhandled verb', () => {
    freshState();
    maxApi.seedLiveTree({});
    const api = new maxApi.LiveAPI('live_set');
    assert.equal(api.call('mystery_verb', 'a', 'b'), 0);
    const unhandled = maxApi.state.liveApiCalls.filter((c) => c.unhandledCall);
    assert.equal(unhandled.length, 1);
    assert.equal(unhandled[0].unhandledCall.verb, 'mystery_verb');
});

// ── Public seeders / getters surface ─────────────────────────────────────────

test('setLiveProperty + getLiveProperty round-trip', () => {
    freshState();
    maxApi.seedLiveTree({
        tracks: [{ _properties: { name: 'A' } }],
    });
    assert.equal(maxApi.getLiveProperty('live_set tracks 0', 'name'), 'A');
    const ok = maxApi.setLiveProperty('live_set tracks 0', 'name', 'Drums');
    assert.equal(ok, true);
    assert.equal(maxApi.getLiveProperty('live_set tracks 0', 'name'), 'Drums');
});

test('setLiveProperty on missing path returns false', () => {
    freshState();
    maxApi.seedLiveTree({ tracks: [] });
    const ok = maxApi.setLiveProperty('live_set tracks 5', 'name', 'X');
    assert.equal(ok, false);
});

test('resetState clears liveTree + handlers + drops', () => {
    freshState();
    maxApi.seedLiveTree({ _properties: { tempo: 120 } });
    maxApi.setLiveCallHandler('foo', () => 1);
    new maxApi.LiveAPI('live_set').set('warp_bpm', 200);
    assert.equal(maxApi.state.liveReadonlyDrops.length, 1);
    maxApi.resetState();
    assert.equal(maxApi.getLiveTree(), null);
    assert.equal(maxApi.state.liveReadonlyDrops.length, 0);
    assert.equal(Object.keys(maxApi.state.liveCallHandlers).length, 0);
});

// ── Hardening Spec acceptance gate TI-2 anchor ───────────────────────────────

test('acceptance gate TI-2: hardened LiveAPI mock with backing liveTree', () => {
    // Hardening Spec acceptance gate TI-2:
    //   "LiveAPI mock has backing liveTree; existing JS tests pass through
    //   the new mock."
    // The static proof:
    //   - liveTree exists in module state
    //   - get/set/getcount route through it
    //   - LOM quirks are encoded
    //   - existing tests in this directory continue to pass (verified at
    //     suite level — see the parallel test files that DON'T import this
    //     gate but still pass).
    freshState();
    assert.equal(typeof maxApi.seedLiveTree, 'function');
    assert.equal(typeof maxApi.getLiveTree, 'function');
    assert.equal(typeof maxApi.liveMarkerUnit, 'function');
    assert.equal(typeof maxApi.setLiveCallHandler, 'function');
    // Quirk constants exposed.
    assert.equal(maxApi.LOM_READONLY_PROPS.warp_bpm, true);
    assert.equal(maxApi.LOM_READONLY_PROPS.end_time, true);
    assert.equal(maxApi.LOM_MARKER_PROPS.start_marker, true);
});
