// test_arrangement_reader.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Offline regression tests for v0/src/m4l-js/sf_arrangement_reader.js
// (Track B of the EP-133 song-export pipeline).
//
// Run:   node tests/js_mocks/test_arrangement_reader.test.js
//
// Uses node:test, the local Max-API mock (`./max_api`), and the sandbox
// loader (`./sandbox`). The default LiveAPI mock returns empty results so we
// install a richer per-test stub that models tempo / time-sig / cue_points /
// arrangement_clips on tracks named A/B/C/D.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule } = require('./sandbox');

// Cross-vm-context normaliser. Sandbox-created arrays/objects use a different
// `Array.prototype`, which trips deepStrictEqual's reference-prototype check.
// JSON-roundtrip normalises everything to the host realm's prototypes — and
// matches what the snapshot looks like once it's been serialised to disk.
function plain(v) {
    return JSON.parse(JSON.stringify(v));
}
const maxApi = require('./max_api');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const JS_DIR = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js');
const SF_ARRANGEMENT_READER = path.join(JS_DIR, 'sf_arrangement_reader.js');

// ── LiveAPI stub builder ─────────────────────────────────────────────────────
//
// Models a Live set as a small dict tree:
//   {
//     tempo: 120, signature_numerator: 4, signature_denominator: 4,
//     cue_points: [{name: "Verse", time: 0}, ...],
//     tracks: [
//       {name: "A", arrangement_clips: [{file_path, start_time, length, warping}]},
//       ...
//     ]
//   }
//
// Builds a LiveAPI factory that responds to `live_set`,
// `live_set tracks N`, `live_set tracks N arrangement_clips M`,
// `live_set cue_points M` exactly the way the real Max LOM does (each
// scalar property returns a 1-element array, getcount returns child counts).

function buildLiveSet(model) {
    // Returns a constructor that the sandbox can assign to its LiveAPI global.
    function LiveAPI(p) {
        this._path = String(p || '');
        this.id = '1';   // non-zero so loader treats it as live
    }
    LiveAPI.prototype._segments = function () {
        return this._path.split(' ').filter(function (s) { return s.length; });
    };
    LiveAPI.prototype._resolveTarget = function () {
        var segs = this._segments();
        // segs example: ['live_set'], ['live_set', 'tracks', '0'],
        // ['live_set', 'cue_points', '2'],
        // ['live_set', 'tracks', '0', 'arrangement_clips', '3']
        if (segs.length === 0) return null;
        if (segs[0] !== 'live_set') return null;
        if (segs.length === 1) return { kind: 'set', target: model };

        if (segs[1] === 'tracks' && segs.length >= 3) {
            var ti = parseInt(segs[2], 10);
            var track = model.tracks[ti];
            if (!track) return null;
            if (segs.length === 3) return { kind: 'track', target: track };
            if (segs[3] === 'arrangement_clips' && segs.length >= 5) {
                var ci = parseInt(segs[4], 10);
                var clip = track.arrangement_clips[ci];
                if (!clip) return null;
                return { kind: 'clip', target: clip };
            }
        }
        if (segs[1] === 'cue_points' && segs.length >= 3) {
            var qi = parseInt(segs[2], 10);
            var cue = model.cue_points[qi];
            if (!cue) return null;
            return { kind: 'cue', target: cue };
        }
        return null;
    };
    LiveAPI.prototype.getcount = function (childName) {
        var hit = this._resolveTarget();
        if (!hit) return 0;
        if (childName === 'tracks' && hit.kind === 'set') {
            return model.tracks.length;
        }
        if (childName === 'cue_points' && hit.kind === 'set') {
            return model.cue_points.length;
        }
        if (childName === 'arrangement_clips' && hit.kind === 'track') {
            return hit.target.arrangement_clips.length;
        }
        return 0;
    };
    LiveAPI.prototype.get = function (prop) {
        var hit = this._resolveTarget();
        if (!hit) return [];
        var val = hit.target[prop];
        // Real LOM returns a 1-element array for scalar properties.
        if (val === undefined || val === null) return [];
        return [val];
    };
    LiveAPI.prototype.set = function () { /* no-op */ };
    LiveAPI.prototype.call = function () { return 0; };
    return LiveAPI;
}

// ── Sandbox helpers ──────────────────────────────────────────────────────────

// Write-capable File mock for tests that exercise the disk-write path. The
// shared max_api.js File is read-only (its `write` is a no-op) — we wrap it
// here so this test can verify runArrangementExport's full success path
// without modifying the shared mock.
function makeWritableFileCtor() {
    var sink = Object.create(null);   // hfs path → buffered string
    function WFile(hfsPath, mode) {
        this._mode = String(mode || 'read');
        var posix = String(hfsPath);
        if (posix.indexOf('Macintosh HD:') === 0) {
            posix = posix.slice('Macintosh HD:'.length);
        }
        this._path = posix;
        this.isopen = 1;
        this.position = 0;
        this.eof = (sink[this._path] || '').length;
        if (this._mode === 'write') {
            sink[this._path] = '';   // truncate
            this.eof = 0;
        }
    }
    WFile.prototype.readstring = function (n) {
        var buf = sink[this._path] || '';
        var take = Math.min(Number(n) || 0, buf.length - this.position);
        var out = buf.substr(this.position, take);
        this.position += take;
        return out;
    };
    WFile.prototype.writestring = function (s) {
        var buf = sink[this._path] || '';
        var head = buf.substring(0, this.position);
        var tail = buf.substring(this.position + s.length);
        sink[this._path] = head + s + tail;
        this.position += s.length;
        if (this.position > this.eof) this.eof = this.position;
    };
    WFile.prototype.close = function () { this.isopen = 0; };
    WFile.sink = sink;   // expose buffered writes for test assertions
    return WFile;
}

function freshSandbox(model, opts) {
    opts = opts || {};
    maxApi.resetState();
    var ctx = createSandbox();
    ctx.LiveAPI = buildLiveSet(model);
    if (opts.writableFiles) {
        ctx.File = makeWritableFileCtor();
    }
    loadModule(ctx, SF_ARRANGEMENT_READER);
    return ctx;
}

function buildSnap(ctx) {
    return ctx.buildArrangementSnapshot();
}

// Convenience: 4 beats @ 120 BPM = 2 sec.
function beatsToSec(beats, tempo) { return beats * 60.0 / tempo; }

// ── Tests ────────────────────────────────────────────────────────────────────

test('happy_path — A clip + locator + tempo round-trip', () => {
    var model = {
        tempo: 120.0,
        signature_numerator: 4,
        signature_denominator: 4,
        cue_points: [
            { name: 'Verse', time: 0 },
            { name: 'Chorus', time: 16 }    // beat 16 @ 120 = 8 sec
        ],
        tracks: [
            {
                name: 'A',
                arrangement_clips: [{
                    file_path: 'Macintosh HD:/tmp/kick.wav',
                    start_time: 0,
                    length: 8,                  // 8 beats = 4 sec
                    warping: 1
                }]
            },
            { name: 'B', arrangement_clips: [] },
            { name: 'C', arrangement_clips: [] },
            { name: 'D', arrangement_clips: [] }
        ]
    };
    var ctx = freshSandbox(model);
    var snap = buildSnap(ctx);

    assert.equal(snap.tempo, 120.0);
    assert.deepEqual(plain(snap.time_sig), [4, 4]);
    assert.equal(snap.locators.length, 2);
    assert.equal(snap.locators[0].name, 'Verse');
    assert.equal(snap.locators[0].time_sec, 0.0);
    assert.equal(snap.locators[1].name, 'Chorus');
    assert.equal(snap.locators[1].time_sec, beatsToSec(16, 120));   // 8.0

    assert.equal(snap.tracks.A.length, 1);
    assert.equal(snap.tracks.A[0].file_path, '/tmp/kick.wav');     // hfs stripped
    assert.equal(snap.tracks.A[0].start_time_sec, 0.0);
    assert.equal(snap.tracks.A[0].length_sec, beatsToSec(8, 120)); // 4.0
    assert.equal(snap.tracks.A[0].warping, 1);

    assert.deepEqual(plain(snap.tracks.B), []);
    assert.deepEqual(plain(snap.tracks.C), []);
    assert.deepEqual(plain(snap.tracks.D), []);
});

test('arrangement_length_sec — max(clip-end, locator-time, 0)', () => {
    var model = {
        tempo: 120.0,
        signature_numerator: 4,
        signature_denominator: 4,
        cue_points: [{ name: 'Bridge', time: 64 }],     // 32 sec
        tracks: [
            {
                name: 'A',
                arrangement_clips: [{
                    file_path: '/foo/a.wav',
                    start_time: 0, length: 8, warping: 1
                }]
            },
            {
                name: 'B', arrangement_clips: [{
                    file_path: '/foo/b.wav',
                    start_time: 32,            // 16 sec start
                    length: 16,                // 8 sec long → ends at 24 sec
                    warping: 1
                }]
            },
            { name: 'C', arrangement_clips: [] },
            { name: 'D', arrangement_clips: [] }
        ]
    };
    var snap = buildSnap(freshSandbox(model));
    // locator @ 32 sec dominates (track B ends at 24 sec).
    assert.equal(snap.arrangement_length_sec, 32.0);
});

test('track_A_missing — letter not in live set returns []', () => {
    var model = {
        tempo: 120.0, signature_numerator: 4, signature_denominator: 4,
        cue_points: [],
        tracks: [
            // No track named A.
            { name: 'B', arrangement_clips: [] },
            { name: 'C', arrangement_clips: [] },
            { name: 'D', arrangement_clips: [] }
        ]
    };
    var snap = buildSnap(freshSandbox(model));
    assert.deepEqual(plain(snap.tracks.A), []);
    assert.deepEqual(plain(snap.tracks.B), []);
});

test('track_exists_no_clips — returns []', () => {
    var model = {
        tempo: 100.0, signature_numerator: 4, signature_denominator: 4,
        cue_points: [],
        tracks: [
            { name: 'A', arrangement_clips: [] },
            { name: 'B', arrangement_clips: [] },
            { name: 'C', arrangement_clips: [] },
            { name: 'D', arrangement_clips: [] }
        ]
    };
    var snap = buildSnap(freshSandbox(model));
    assert.deepEqual(plain(snap.tracks), { A: [], B: [], C: [], D: [] });
    assert.equal(snap.tempo, 100.0);
});

test('no_locators — empty locators array', () => {
    var model = {
        tempo: 120.0, signature_numerator: 4, signature_denominator: 4,
        cue_points: [],
        tracks: [{ name: 'A', arrangement_clips: [] }]
    };
    var snap = buildSnap(freshSandbox(model));
    assert.deepEqual(plain(snap.locators), []);
});

test('locator_at_time_zero — boundary case kept (not filtered)', () => {
    var model = {
        tempo: 120.0, signature_numerator: 4, signature_denominator: 4,
        cue_points: [{ name: 'Start', time: 0 }],
        tracks: [{ name: 'A', arrangement_clips: [] }]
    };
    var snap = buildSnap(freshSandbox(model));
    assert.equal(snap.locators.length, 1);
    assert.equal(snap.locators[0].time_sec, 0.0);
    assert.equal(snap.locators[0].name, 'Start');
});

test('overlapping_clips — both included, sorted by start_time', () => {
    // Track C has two arrangement clips that overlap; the resolver (Track C
    // Python) decides who wins — the reader just emits both faithfully.
    var model = {
        tempo: 120.0, signature_numerator: 4, signature_denominator: 4,
        cue_points: [],
        tracks: [
            { name: 'A', arrangement_clips: [] },
            { name: 'B', arrangement_clips: [] },
            {
                name: 'C', arrangement_clips: [
                    {
                        file_path: '/loops/late.wav',
                        start_time: 8,    // starts later
                        length: 16,
                        warping: 1
                    },
                    {
                        file_path: '/loops/early.wav',
                        start_time: 0,    // starts earlier
                        length: 16,       // overlaps with the late one [8..16]
                        warping: 1
                    }
                ]
            },
            { name: 'D', arrangement_clips: [] }
        ]
    };
    var snap = buildSnap(freshSandbox(model));
    assert.equal(snap.tracks.C.length, 2);
    // Sorted by start_time_sec ascending.
    assert.equal(snap.tracks.C[0].file_path, '/loops/early.wav');
    assert.equal(snap.tracks.C[1].file_path, '/loops/late.wav');
});

test('non_letter_tracks_ignored — Master/Returns/Drums skipped', () => {
    var model = {
        tempo: 120.0, signature_numerator: 4, signature_denominator: 4,
        cue_points: [],
        tracks: [
            {
                name: 'Drums',                  // not a letter
                arrangement_clips: [{
                    file_path: '/should/not/appear.wav',
                    start_time: 0, length: 4, warping: 1
                }]
            },
            { name: 'A', arrangement_clips: [] }
        ]
    };
    var snap = buildSnap(freshSandbox(model));
    assert.deepEqual(plain(snap.tracks.A), []);
    // Drums clip must NOT leak into any letter group.
    var letters = ['A', 'B', 'C', 'D'];
    for (var i = 0; i < letters.length; i++) {
        for (var j = 0; j < snap.tracks[letters[i]].length; j++) {
            assert.notEqual(
                snap.tracks[letters[i]][j].file_path,
                '/should/not/appear.wav'
            );
        }
    }
});

test('time_sig — non-default numerator/denominator', () => {
    var model = {
        tempo: 90.0, signature_numerator: 7, signature_denominator: 8,
        cue_points: [],
        tracks: []
    };
    var snap = buildSnap(freshSandbox(model));
    assert.deepEqual(plain(snap.time_sig), [7, 8]);
    assert.equal(snap.tempo, 90.0);
});

test('runArrangementExport — writes JSON to disk and returns true', () => {
    var model = {
        tempo: 128.0, signature_numerator: 4, signature_denominator: 4,
        cue_points: [{ name: 'Drop', time: 32 }],
        tracks: [
            {
                name: 'A', arrangement_clips: [{
                    file_path: '/x/y.wav',
                    start_time: 0, length: 16, warping: 0
                }]
            },
            { name: 'B', arrangement_clips: [] },
            { name: 'C', arrangement_clips: [] },
            { name: 'D', arrangement_clips: [] }
        ]
    };
    var ctx = freshSandbox(model, { writableFiles: true });

    var tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sf_arr_test_'));
    var outPath = path.join(tmpDir, 'snapshot.json');

    var ok = ctx.runArrangementExport(outPath);
    assert.equal(ok, true,
        'runArrangementExport should return true on success');

    // Verify the buffered write contains a JSON snapshot with the right
    // shape. The mock's `sink` retains every writestring call.
    var written = ctx.File.sink[outPath];
    assert.ok(written && written.length > 0,
        'expected snapshot bytes in mock sink for ' + outPath);

    var parsed;
    try { parsed = JSON.parse(written); }
    catch (e) { assert.fail('snapshot is not valid JSON: ' + e
        + '\n--- bytes ---\n' + written); }

    assert.equal(parsed.tempo, 128.0);
    assert.deepEqual(parsed.time_sig, [4, 4]);
    assert.equal(parsed.locators.length, 1);
    assert.equal(parsed.locators[0].name, 'Drop');
    assert.equal(parsed.tracks.A.length, 1);
    assert.equal(parsed.tracks.A[0].file_path, '/x/y.wav');
    assert.equal(parsed.tracks.A[0].warping, 0);

    // Cleanup.
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
});

test('runArrangementExport — empty path returns false without throwing', () => {
    var ctx = freshSandbox({
        tempo: 120, signature_numerator: 4, signature_denominator: 4,
        cue_points: [], tracks: []
    });
    assert.equal(ctx.runArrangementExport(''), false);
    assert.equal(ctx.runArrangementExport(null), false);
});

test('loader_wrapper_present — stemforge_loader.v0.js wires exportArrangementSnapshot', () => {
    // Static check (mirrors the priority_chain_fixture pattern in the sister
    // suite) — guards against a future edit accidentally removing the wire-in.
    var loaderSrc = fs.readFileSync(
        path.join(JS_DIR, 'stemforge_loader.v0.js'), 'utf8'
    );
    assert.ok(
        loaderSrc.indexOf('function exportArrangementSnapshot') !== -1,
        'loader must define exportArrangementSnapshot top-level function'
    );
    assert.ok(
        loaderSrc.indexOf('include("sf_arrangement_reader.js")') !== -1,
        'loader must include sf_arrangement_reader.js for delegation'
    );
    assert.ok(
        loaderSrc.indexOf('runArrangementExport') !== -1,
        'loader must call into runArrangementExport (not the loader-local '
            + 'wrapper, which would recurse)'
    );
});

test('package_sync — m4l-package copy matches m4l-js source of truth', () => {
    // Per memory/feedback_js_source_of_truth.md: both copies must stay in
    // sync or the installer will deploy a stale build.
    var src = fs.readFileSync(SF_ARRANGEMENT_READER, 'utf8');
    var pkg = fs.readFileSync(
        path.join(REPO_ROOT, 'v0', 'src', 'm4l-package', 'StemForge',
            'javascript', 'sf_arrangement_reader.js'),
        'utf8'
    );
    assert.equal(src, pkg, 'sf_arrangement_reader.js out of sync between '
        + 'v0/src/m4l-js/ and v0/src/m4l-package/StemForge/javascript/');

    var loaderSrc = fs.readFileSync(
        path.join(JS_DIR, 'stemforge_loader.v0.js'), 'utf8'
    );
    var loaderPkg = fs.readFileSync(
        path.join(REPO_ROOT, 'v0', 'src', 'm4l-package', 'StemForge',
            'javascript', 'stemforge_loader.v0.js'),
        'utf8'
    );
    assert.equal(loaderSrc, loaderPkg,
        'stemforge_loader.v0.js out of sync between m4l-js and m4l-package');
});
