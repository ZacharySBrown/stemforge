// test_deck_loader.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tests for setforge's loadDeck — the 4-deck live performance loader added to
// stemforge_loader.v0.js. See docs/design-docs/setforge-loader.md.
//
// loadDeck reuses loadClip (delete->create_audio_clip->probe->warp/loop/name)
// and layers a per-clip color on top. The LiveAPI mock's `call()` is a no-op
// unless a handler is registered, so we register handlers for
// create_audio_clip / delete_clip / create_scene that mutate the seeded tree
// the way Live would — only then does loadClip's clip-handle probe see a clip
// land, and only then is the behavior exercised end-to-end.
//
// Mirrors the harness style of test_bounce.test.js / test_commit.test.js.
//
// Run:   node tests/js_mocks/test_deck_loader.test.js
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs = require('fs');
const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, maxApi } = require('./sandbox');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SF_LOADER = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js', 'stemforge_loader.v0.js');

// ── tree builders ───────────────────────────────────────────────────────────

function emptySlots(n) {
    const slots = [];
    for (let i = 0; i < n; i++) slots.push({ _properties: { has_clip: 0 } });
    return slots;
}

function makeTrack(name, slotCount) {
    return { _properties: { name }, clip_slots: emptySlots(slotCount) };
}

// Source track at index 0, then A/B/C/D × {d,b,v,o} with `slotsPerTrack` slots.
function seedDeckLayout(slotsPerTrack, sceneCount) {
    const tracks = [makeTrack('SF | Source', 0)];
    ['A', 'B', 'C', 'D'].forEach((deck) => {
        ['d', 'b', 'v', 'o'].forEach((stem) => {
            tracks.push(makeTrack(deck + '-' + stem, slotsPerTrack));
        });
    });
    const scenes = [];
    for (let i = 0; i < sceneCount; i++) scenes.push({ _properties: {} });
    maxApi.seedLiveTree({ _properties: { tempo: 120 }, tracks, scenes });
}

// Resolve a clip_slot node from a LOM path like "live_set tracks 5 clip_slots 0".
function resolveSlot(lomPath) {
    const segs = String(lomPath).trim().split(/\s+/);
    const tree = maxApi.getLiveTree();
    const t = Number(segs[segs.indexOf('tracks') + 1]);
    const s = Number(segs[segs.indexOf('clip_slots') + 1]);
    const track = tree.tracks[t];
    if (!track || !track.clip_slots) return null;
    return track.clip_slots[s] || null;
}

// Register the Live-side clip lifecycle so loadClip's probe sees clips land.
function installClipHandlers() {
    maxApi.setLiveCallHandler('create_audio_clip', (lomPath, args) => {
        const slot = resolveSlot(lomPath);
        if (!slot) return 0;
        slot.clip = { _properties: { file_path: String(args[0]) } };
        slot._properties.has_clip = 1;
        return 0;
    });
    maxApi.setLiveCallHandler('delete_clip', (lomPath) => {
        const slot = resolveSlot(lomPath);
        if (!slot) return 0;
        delete slot.clip;
        slot._properties.has_clip = 0;
        return 0;
    });
    maxApi.setLiveCallHandler('create_scene', () => {
        maxApi.getLiveTree().scenes.push({ _properties: {} });
        return 0;
    });
}

// Seed the mock filesystem with the wav files a manifest references.
function seedDeckFiles(mf) {
    Object.keys(mf.stems).forEach((k) => {
        mf.stems[k].clips.forEach((c) => maxApi.seedFile(c.audio_path, 'RIFF'));
    });
}

function deckManifest(deck, rows, dir) {
    dir = dir || '/forge/' + deck;
    const stems = {};
    [['drums', 'd'], ['bass', 'b'], ['vocals', 'v'], ['other', 'o']].forEach(([name, s]) => {
        const clips = [];
        for (let r = 0; r < rows; r++) {
            clips.push({ slot: r, audio_path: dir + '/' + s + '_v' + r + '.wav' });
        }
        stems[name] = { clips };
    });
    return {
        version: 1, deck, rows,
        song: { name: deck + ' Song', color_hue: 0.5 },
        bpm: 137.0, stems,
    };
}

function loadLoader() {
    maxApi.resetState();
    const ctx = createSandbox();
    loadModule(ctx, SF_LOADER);
    return ctx;
}

function clipProps(trackIdx, slotIdx) {
    const tree = maxApi.getLiveTree();
    const slot = tree.tracks[trackIdx] && tree.tracks[trackIdx].clip_slots[slotIdx];
    return slot && slot.clip && slot.clip._properties;
}

const STEM_KEYS = ['drums', 'bass', 'vocals', 'other'];

// Track-name → index in the seeded layout (source=0, then A-d=1...).
const IDX = {};
(() => {
    let n = 1;
    ['A', 'B', 'C', 'D'].forEach((deck) => {
        ['d', 'b', 'v', 'o'].forEach((stem) => { IDX[deck + '-' + stem] = n++; });
    });
})();

// ── 0. hueToLiveColor unit ──────────────────────────────────────────────────

test('hueToLiveColor: 0..1 hue → 0xRRGGBB int; non-finite → null', () => {
    const ctx = loadLoader();
    assert.equal(ctx.hueToLiveColor(0), 0xFF0000);       // red
    assert.equal(ctx.hueToLiveColor(1 / 3), 0x00FF00);   // green
    assert.equal(ctx.hueToLiveColor(2 / 3), 0x0000FF);   // blue
    assert.equal(ctx.hueToLiveColor(1), 0xFF0000);       // wraps to red
    assert.equal(ctx.hueToLiveColor(NaN), null);
    assert.equal(ctx.hueToLiveColor(undefined), null);
});

// ── 1. loadDeck rows=1, deck A: 4 clips land warped/looped/named/colored ─────

test('loadDeck rows=1 deck A: places 4 clips, warped+looped+named+colored', () => {
    const ctx = loadLoader();
    installClipHandlers();
    seedDeckLayout(4, 4);
    const mf = deckManifest('A', 1);
    seedDeckFiles(mf);

    ctx.loadDeck(mf);

    ['A-d', 'A-b', 'A-v', 'A-o'].forEach((tn) => {
        const p = clipProps(IDX[tn], 0);
        assert.ok(p, tn + ' scene 0 should have a clip');
        assert.equal(p.warping, 1, tn + ' clip must be warped');
        assert.equal(p.looping, 1, tn + ' clip must be looped');
        assert.equal(p.color, ctx.hueToLiveColor(0.5), tn + ' clip must be colored from hue');
        assert.ok(String(p.name).indexOf('A Song') === 0, tn + ' clip name from song');
    });
    // No clips on other decks' tracks.
    assert.equal(clipProps(IDX['B-d'], 0), undefined, 'deck B untouched');
});

// ── 2. reload-in-place: second load replaces, no duplicate/stale ────────────

test('loadDeck twice with different songs: clips replaced in place', () => {
    const ctx = loadLoader();
    installClipHandlers();
    seedDeckLayout(4, 4);

    const first = deckManifest('A', 1, '/forge/first');
    seedDeckFiles(first);
    ctx.loadDeck(first);
    assert.ok(clipProps(IDX['A-d'], 0).file_path.indexOf('/forge/first') === 0);

    const second = deckManifest('A', 1, '/forge/second');
    seedDeckFiles(second);
    ctx.loadDeck(second);

    // Same slot now holds the second song's file — replaced, not appended.
    assert.ok(clipProps(IDX['A-d'], 0).file_path.indexOf('/forge/second') === 0,
        'reload must replace the clip in place');
    // Slot 1 stays empty (rows=1 → only scene 0 used both times).
    assert.equal(clipProps(IDX['A-d'], 1), undefined, 'no stray clip in scene 1');
});

// ── 3. deck isolation: loading C leaves A intact ─────────────────────────────

test('loadDeck C does not disturb a previously-loaded deck A', () => {
    const ctx = loadLoader();
    installClipHandlers();
    seedDeckLayout(4, 4);

    const a = deckManifest('A', 1, '/forge/a');
    seedDeckFiles(a);
    ctx.loadDeck(a);

    const c = deckManifest('C', 1, '/forge/c');
    seedDeckFiles(c);
    ctx.loadDeck(c);

    assert.ok(clipProps(IDX['A-d'], 0).file_path.indexOf('/forge/a') === 0,
        'deck A clip must survive a deck C load');
    assert.ok(clipProps(IDX['C-d'], 0).file_path.indexOf('/forge/c') === 0,
        'deck C clip placed');
});

// ── 4. rows generalization: rows=2 places 2 per stem + auto-creates scenes ──

test('loadDeck rows=2: 2 clips per stem, scenes auto-created', () => {
    const ctx = loadLoader();
    installClipHandlers();
    // Tracks have 2 slots, but session starts with only 1 scene → ensureScenes
    // must create the 2nd.
    seedDeckLayout(2, 1);
    const mf = deckManifest('B', 2);
    seedDeckFiles(mf);

    ctx.loadDeck(mf);

    assert.equal(maxApi.getLiveTree().scenes.length, 2, 'ensureScenes created scene 2');
    ['B-d', 'B-b', 'B-v', 'B-o'].forEach((tn) => {
        assert.ok(clipProps(IDX[tn], 0), tn + ' scene 0 clip');
        assert.ok(clipProps(IDX[tn], 1), tn + ' scene 1 clip');
    });
});

// ── 4b. per-scene song identity: each row's clip carries its own name+color ──

test('loadDeck per-clip name+color_hue: each scene gets its own song identity', () => {
    const ctx = loadLoader();
    installClipHandlers();
    seedDeckLayout(2, 1); // 2 slots/track, 1 scene → ensureScenes adds the 2nd
    // A merged setlist: deck A holds two DIFFERENT songs down its two scenes.
    const songs = [
        { name: 'Sigur Ros', hue: 0.10 },
        { name: 'Drake', hue: 0.80 },
    ];
    const stems = {};
    [['drums', 'd'], ['bass', 'b'], ['vocals', 'v'], ['other', 'o']].forEach(([k, s]) => {
        stems[k] = {
            clips: songs.map((song, r) => ({
                slot: r,
                audio_path: '/forge/' + s + '_v' + r + '.wav',
                name: song.name,
                color_hue: song.hue,
            })),
        };
    });
    const mf = {
        version: 1, deck: 'A', rows: 2,
        song: { name: 'A deck', color_hue: 0.5 }, bpm: 120, stems,
    };
    seedDeckFiles(mf);

    ctx.loadDeck(mf);

    ['A-d', 'A-b', 'A-v', 'A-o'].forEach((tn) => {
        const p0 = clipProps(IDX[tn], 0);
        const p1 = clipProps(IDX[tn], 1);
        assert.equal(p0.color, ctx.hueToLiveColor(0.10), tn + ' scene0 color from song0');
        assert.equal(p1.color, ctx.hueToLiveColor(0.80), tn + ' scene1 color from song1');
        assert.ok(String(p0.name).indexOf('Sigur Ros') === 0, tn + ' scene0 name from song0');
        assert.ok(String(p1.name).indexOf('Drake') === 0, tn + ' scene1 name from song1');
        // The deck-level song.* must NOT win when a clip carries its own identity.
        assert.notEqual(p0.color, ctx.hueToLiveColor(0.5), tn + ' deck hue must not override');
        // A per-clip name drops the "vN" variation suffix.
        assert.equal(String(p0.name).indexOf(' v0'), -1, 'no vN suffix with per-clip name');
    });
});

// ── 4c. beat-matching: applyDeckWarp imposes a clean 2-marker native warp ────

// Clip node from a "...clip_slots S clip" path.
function clipNode(lomPath) {
    const slot = resolveSlot(lomPath);
    return slot ? slot.clip || null : null;
}

// Warp-aware clip lifecycle: create seeds Live-style auto-warp markers (bogus)
// so we can prove applyDeckWarp REPLACES them with its own linear pair.
function installWarpHandlers() {
    const sync = (clip) => {
        clip._properties.warp_markers = JSON.stringify({ warp_markers: clip._wm });
    };
    maxApi.setLiveCallHandler('create_audio_clip', (lomPath, args) => {
        const slot = resolveSlot(lomPath);
        if (!slot) return 0;
        const clip = { _properties: { file_path: String(args[0]) } };
        clip._wm = [{ beat_time: 0, sample_time: 0 }, { beat_time: 4, sample_time: 2.0 }];
        sync(clip);
        slot.clip = clip;
        slot._properties.has_clip = 1;
        return 0;
    });
    maxApi.setLiveCallHandler('delete_clip', (lomPath) => {
        const slot = resolveSlot(lomPath);
        if (!slot) return 0;
        delete slot.clip;
        slot._properties.has_clip = 0;
        return 0;
    });
    maxApi.setLiveCallHandler('create_scene', () => {
        maxApi.getLiveTree().scenes.push({ _properties: {} });
        return 0;
    });
    maxApi.setLiveCallHandler('add_warp_marker', (lomPath, args) => {
        const clip = clipNode(lomPath);
        if (!clip) return 0;
        const d = args[0];
        const beat = Number(d.get('beat_time'));
        const sample = Number(d.get('sample_time'));
        // Live silently rejects a second marker at an occupied sample_time.
        if (clip._wm.some((m) => Math.abs(m.sample_time - sample) < 0.0005)) return 0;
        clip._wm.push({ beat_time: beat, sample_time: sample });
        sync(clip);
        return 0;
    });
    maxApi.setLiveCallHandler('move_warp_marker', (lomPath, args) => {
        const clip = clipNode(lomPath);
        if (!clip) return 0;
        const m = clip._wm.find((x) => Math.abs(x.beat_time - Number(args[0])) < 1e-6);
        if (m) { m.beat_time += Number(args[1]); sync(clip); }
        return 0;
    });
    maxApi.setLiveCallHandler('remove_warp_marker', (lomPath, args) => {
        const clip = clipNode(lomPath);
        if (!clip) return 0;
        const i = clip._wm.findIndex((x) => Math.abs(x.beat_time - Number(args[0])) < 1e-6);
        if (i >= 0) { clip._wm.splice(i, 1); sync(clip); }
        return 0;
    });
}

test('applyDeckWarp: native bpm+downbeat → clean 2-marker warp, extras removed', () => {
    const ctx = loadLoader();
    installWarpHandlers();
    seedDeckLayout(4, 4);
    const mf = deckManifest('A', 1);
    const bpm = 120;
    const db = 0.5;
    STEM_KEYS.forEach((k) => {
        mf.stems[k].clips[0].bpm = bpm;
        mf.stems[k].clips[0].downbeat_sec = db;
    });
    seedDeckFiles(mf);

    ctx.loadDeck(mf);

    const tree = maxApi.getLiveTree();
    ['A-d', 'A-b', 'A-v', 'A-o'].forEach((tn) => {
        const clip = tree.tracks[IDX[tn]].clip_slots[0].clip;
        assert.equal(clip._properties.warping, 1, tn + ' warping on');
        const wm = JSON.parse(clip._properties.warp_markers).warp_markers;
        assert.equal(wm.length, 2, tn + ' must end with exactly 2 markers (extras removed)');
        const byBeat = {};
        wm.forEach((m) => { byBeat[m.beat_time] = m.sample_time; });
        assert.ok(Math.abs(byBeat[0] - db) < 1e-6, tn + ' beat 0 pinned to the downbeat');
        assert.ok(Math.abs(byBeat[1] - (db + 60 / bpm)) < 1e-6, tn + ' beat 1 one native beat later');
    });
    // Per-stem warp mode: drums/bass = Beats(0), vocals/other = Complex(4).
    assert.equal(tree.tracks[IDX['A-d']].clip_slots[0].clip._properties.warp_mode, 0, 'drums = Beats');
    assert.equal(tree.tracks[IDX['A-b']].clip_slots[0].clip._properties.warp_mode, 0, 'bass = Beats');
    assert.equal(tree.tracks[IDX['A-v']].clip_slots[0].clip._properties.warp_mode, 4, 'vocals = Complex');
    assert.equal(tree.tracks[IDX['A-o']].clip_slots[0].clip._properties.warp_mode, 4, 'other = Complex');
});

test('loadDeck without bpm leaves Live auto-warp (no marker surgery)', () => {
    const ctx = loadLoader();
    installWarpHandlers();
    seedDeckLayout(4, 4);
    const mf = deckManifest('A', 1); // no bpm/downbeat fields
    seedDeckFiles(mf);

    ctx.loadDeck(mf);

    // The seeded auto-warp markers stay untouched when no bpm is supplied.
    const clip = maxApi.getLiveTree().tracks[IDX['A-d']].clip_slots[0].clip;
    const wm = JSON.parse(clip._properties.warp_markers).warp_markers;
    assert.equal(wm.length, 2, 'auto-warp markers untouched');
    assert.ok(wm.some((m) => m.sample_time === 2.0), 'original auto marker still present');
});

// ── 5. validate-before-mutate: a missing file aborts with NO clips placed ────

test('loadDeck aborts cleanly when any audio file is missing (no partial load)', () => {
    const ctx = loadLoader();
    installClipHandlers();
    seedDeckLayout(4, 4);
    const mf = deckManifest('A', 1);
    seedDeckFiles(mf);
    // Remove one file so validation fails.
    delete maxApi.state.fs[mf.stems.vocals.clips[0].audio_path];

    ctx.loadDeck(mf);

    ['A-d', 'A-b', 'A-v', 'A-o'].forEach((tn) => {
        assert.equal(clipProps(IDX[tn], 0), undefined,
            tn + ' must stay empty — validation aborts before mutating a live deck');
    });
});

// ── 6. missing track: bail without crashing ─────────────────────────────────

test('loadDeck reports a missing deck track without throwing', () => {
    const ctx = loadLoader();
    installClipHandlers();
    // Only the source track exists — no A-d etc.
    maxApi.seedLiveTree({ _properties: {}, tracks: [makeTrack('SF | Source', 0)], scenes: [{}] });
    const mf = deckManifest('A', 1);
    seedDeckFiles(mf);

    assert.doesNotThrow(() => ctx.loadDeck(mf));
    const status = maxApi.state.outlets[0] || [];
    const sawNoTrack = status.some((a) => String(a[1] || '').indexOf('no track A-d') >= 0);
    assert.ok(sawNoTrack, 'should surface a "no track A-d" status');
});

// ── 7. loadDeckFromDict dispatch + dual-location sync ────────────────────────

test('loadDeckFromDict reads a [dict] manifest and loads it', () => {
    const ctx = loadLoader();
    installClipHandlers();
    seedDeckLayout(4, 4);
    const mf = deckManifest('D', 1);
    seedDeckFiles(mf);
    // Populate the named dict the way the device would.
    new ctx.Dict('sf_deck').parse(JSON.stringify(mf));

    ctx.messagename = 'loadDeckFromDict';
    ctx.loadDeckFromDict.call(ctx, 'sf_deck');

    assert.ok(clipProps(IDX['D-d'], 0), 'loadDeckFromDict placed deck D clips');
});

test('loadDeckPath reads a deck manifest JSON from disk and loads it', () => {
    const ctx = loadLoader();
    installClipHandlers();
    seedDeckLayout(4, 4);
    const mf = deckManifest('C', 1);
    seedDeckFiles(mf);
    const manifestPath = '/forge/C/deck.json';
    maxApi.seedFile(manifestPath, JSON.stringify(mf));

    ctx.messagename = 'loadDeckPath';
    ctx.loadDeckPath.call(ctx, manifestPath);

    assert.ok(clipProps(IDX['C-d'], 0), 'loadDeckPath placed deck C clips from disk');
    assert.ok(clipProps(IDX['C-d'], 0).file_path.indexOf('/forge/C') === 0);
});

test('loadDeckPath surfaces a clear status when the file is unreadable', () => {
    const ctx = loadLoader();
    seedDeckLayout(4, 4);
    ctx.messagename = 'loadDeckPath';
    assert.doesNotThrow(() => ctx.loadDeckPath.call(ctx, '/nope/missing.json'));
    const status = maxApi.state.outlets[0] || [];
    assert.ok(status.some((a) => String(a[1] || '').indexOf('cannot read') >= 0),
        'should report it cannot read the missing manifest');
});

test('source and package copies of stemforge_loader.v0.js stay byte-identical', () => {
    const src = fs.readFileSync(SF_LOADER, 'utf8');
    const pkg = fs.readFileSync(path.join(
        REPO_ROOT, 'v0', 'src', 'm4l-package', 'StemForge', 'javascript',
        'stemforge_loader.v0.js'), 'utf8');
    assert.equal(src, pkg, 'm4l-js and m4l-package loader copies diverged');
});
