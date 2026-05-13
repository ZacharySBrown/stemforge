// test_sf_configurator.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tier-3 tests for the Configurator Strip's JS operations dispatcher
// (Phase 3). Module under test: v0/src/m4l-devices/configurator-strip/js/
// sf_configurator.js.
//
// The script:
//   - On loadbang, reads ~/stemforge/.configurator_port and caches the port.
//   - When the port file is present, sets the status dot to green (DOT_OK)
//     and emits the server URL into the footer.
//   - When the port file is missing, sets DOT_ERROR and a "click Start
//     Server" footer.
//   - Each operation handler emits a curl POST to /intent/<verb> via
//     outlet 4 (which the patcher pipes through [shell]).
//   - openEditor emits `openurl <serverBase>/` on outlet 3 (the [jweb]).
//   - startServer emits `exec stemforge-configurator &` on outlet 4.
//   - commit walks session + arrangement view (mirrors
//     _commitSessionTracks) and POSTs the result.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, maxApi } = require('./sandbox');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SF_CONF = path.join(
    REPO_ROOT, 'v0', 'src', 'm4l-devices', 'configurator-strip',
    'js', 'sf_configurator.js',
);

// Path the script will read at boot. The script now passes `~` through
// to Max's File API (which expands it against the running user's home
// on macOS); the broken `$HOME`-substitution that motivated the original
// seed has been removed. Mock has no expansion logic, so we seed the
// literal `~`-prefixed key the script will look up.
const PORT_FILE_KEY = '~/stemforge/.configurator_port';

function loadConf() {
    maxApi.resetState();
    const ctx = createSandbox();
    loadModule(ctx, SF_CONF);
    return ctx;
}

function outlets() {
    return maxApi.state.outlets;
}

function outletOn(n) {
    return outlets()[n] || [];
}

function normalize(x) {
    return JSON.parse(JSON.stringify(x));
}

// ── Port discovery ───────────────────────────────────────────────────────────

test('discoverPort: missing port file → DOT_ERROR + server-down status', () => {
    const ctx = loadConf();
    // No seed for the port file at all.
    const port = ctx._discoverPort();
    assert.equal(port, null);

    // outlet 0 = status text. Last emission should be "server down".
    const statusEmits = outletOn(0).map(a => a[0]);
    assert.ok(statusEmits.includes('server down'),
              `expected "server down" in ${JSON.stringify(statusEmits)}`);

    // outlet 2 = dot color. Look for the error rgba (red).
    const dotEmits = outletOn(2);
    const lastDot = dotEmits[dotEmits.length - 1];
    assert.equal(lastDot[0], 'bgcolor');
    // DOT_ERROR red ~ 0.871.
    assert.ok(lastDot[1] > 0.8, `expected red dot, got ${JSON.stringify(lastDot)}`);
});

test('discoverPort: present port file → DOT_OK + serverBase resolved', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421\n');

    const port = ctx._discoverPort();
    assert.equal(port, 7421);

    const statusEmits = outletOn(0).map(a => a[0]);
    assert.ok(statusEmits.includes('connected'),
              `expected "connected" in ${JSON.stringify(statusEmits)}`);

    // Footer last emission should be the serverBase URL.
    const footerEmits = outletOn(1).map(a => a[0]);
    const lastFooter = footerEmits[footerEmits.length - 1];
    assert.equal(lastFooter, 'http://127.0.0.1:7421');

    // Dot is green (DOT_OK ~ 0.220, 0.780, 0.376).
    const dotEmits = outletOn(2);
    const lastDot = dotEmits[dotEmits.length - 1];
    assert.equal(lastDot[0], 'bgcolor');
    assert.ok(Math.abs(lastDot[2] - 0.780) < 0.01,
              `expected green-channel ~0.78, got ${lastDot[2]}`);
});

// ── HTTP intent emission ─────────────────────────────────────────────────────

test('loadManifest: POSTs /intent/load-manifest via curl on outlet 4', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    ctx._discoverPort();

    ctx.loadManifest('/Users/zak/song/stems.json');

    const shellEmits = outletOn(4);
    // Find the curl call.
    const curl = shellEmits.find(a => a[0] === 'exec' && /curl/.test(a[1]));
    assert.ok(curl, 'expected a curl exec emission');
    const cmd = curl[1];
    assert.match(cmd, /POST/);
    assert.match(cmd, /http:\/\/127\.0\.0\.1:7421\/intent\/load-manifest/);
    assert.match(cmd, /stems\.json/, `body should include manifest path; got: ${cmd}`);
});

test('exportPpak: POSTs /intent/export with target=ep133', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    ctx._discoverPort();

    ctx.exportPpak('/tmp/out.ppak');

    const shellEmits = outletOn(4);
    const curl = shellEmits.find(a => a[0] === 'exec' && /intent\/export/.test(a[1]));
    assert.ok(curl, 'expected export curl emission');
    assert.match(curl[1], /target.*ep133/);
    assert.match(curl[1], /out\.ppak/);
});

test('recompute / slice / curate / reAnchor each fire their verb', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    ctx._discoverPort();

    ctx.recompute();
    ctx.slice();
    ctx.curate();
    ctx.reAnchor();

    const shellEmits = outletOn(4);
    const cmds = shellEmits.filter(a => a[0] === 'exec').map(a => a[1]);
    assert.ok(cmds.some(c => /intent\/recompute/.test(c)), 'recompute missing');
    assert.ok(cmds.some(c => /intent\/slice/.test(c)),     'slice missing');
    assert.ok(cmds.some(c => /intent\/curate/.test(c)),    'curate missing');
    assert.ok(cmds.some(c => /intent\/re-anchor/.test(c)), 're-anchor missing');
});

// ── openEditor → launchbrowser via messnamed (default browser, new tab) ─────
//
// Tried in Phase 3:
//   1. outlet(3, "openurl", url) → [jweb]      — [jweb] doesn't recognize
//                                                "openurl"; verb is "url".
//      Plus [jweb] in M4L is embedded in the device UI area (too small).
//   2. shell `open -na "Google Chrome" --args --new-window --app=<url>`
//      — macOS + Chrome silently drops -n when Chrome is already running,
//      and --app= from a re-launch attempt is ignored. Tested on-device.
//   3. AppleScript `tell app "Chrome" to make new window` — AppleEvent
//      timeout (Chrome's automation permissions). Tested on-device.
//   4. Direct binary `/Applications/Google Chrome.app/.../Google Chrome
//      --app=<url> --new-window` — focuses existing instance, no window.
//
// Reliable cross-permission path: launchbrowser → tab in default browser.
// Phase 4 adds an in-popup "Pop out" button that uses window.open() to
// spawn a proper popup window (works from inside the browser without OS
// automation grants).

test('openEditor: emits messnamed launchbrowser with serverBase', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    ctx._discoverPort();

    maxApi.state.messnamed = [];
    ctx.openEditor();

    const calls = maxApi.state.messnamed;
    assert.equal(calls.length, 1, 'exactly one messnamed call');
    assert.deepEqual(calls[0], ['max', 'launchbrowser', 'http://127.0.0.1:7421/']);

    // Legacy outlet-3 path emits `url <addr>` for custom-patched routes.
    const j = outletOn(3);
    const last = j[j.length - 1];
    assert.deepEqual(last, ['url', 'http://127.0.0.1:7421/']);
});

test('openEditor: with no server, fires neither launchbrowser nor outlet-3', () => {
    const ctx = loadConf();
    maxApi.state.messnamed = [];

    ctx.openEditor();

    assert.equal((maxApi.state.messnamed || []).length, 0,
        'no launchbrowser without a server');

    const j = outletOn(3);
    const urls = j.filter(a => a[0] === 'url' || a[0] === 'openurl');
    assert.equal(urls.length, 0, 'no url emission without a server');
});

// ── startServer → shell exec ─────────────────────────────────────────────────

test('startServer: emits exec stemforge-configurator on outlet 4', () => {
    const ctx = loadConf();
    ctx.startServer();

    const shellEmits = outletOn(4);
    const start = shellEmits.find(a => a[0] === 'exec' && /stemforge-configurator/.test(a[1]));
    assert.ok(start, 'expected stemforge-configurator start command');
});

// ── COMMIT walker — exact mirror of _commitSessionTracks contract ────────────

function makeTrack(name, clipSlots, arrClips) {
    const t = { _properties: { name }, clip_slots: clipSlots || [] };
    if (arrClips) t.arrangement_clips = arrClips;
    return t;
}

function makeClipSlot(clipProps) {
    if (clipProps == null) return { _properties: {} };
    return { _properties: {}, clip: { _properties: clipProps } };
}

function makeArrClip(clipProps) {
    return { _properties: clipProps };
}

test('commit walker: empty live set → all four letters empty', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    maxApi.seedLiveTree({ _properties: { tempo: 120 }, tracks: [] });

    const result = ctx._walkSessionAndArrangement();
    assert.deepEqual(normalize(result), { A: [], B: [], C: [], D: [] });
});

test('commit walker: session-view clip on track A registers at clip-slot index', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    maxApi.seedLiveTree({
        _properties: { tempo: 120 },
        tracks: [
            makeTrack('A', [
                makeClipSlot(null),  // slot 0 empty
                makeClipSlot({
                    file_path: 'Macintosh HD:/abs/a.wav',
                    start_marker: 0, end_marker: 4, length: 4, warping: 1,
                }),
            ]),
        ],
    });

    const result = ctx._walkSessionAndArrangement();
    assert.equal(result.A.length, 1);
    assert.equal(result.A[0].slot, 1);   // claim by clip-slot index
    assert.equal(result.A[0].file, '/abs/a.wav');  // HFS prefix stripped
    // 4 beats @ 120 bpm = 2 sec.
    assert.ok(Math.abs(result.A[0].end_sec - 2.0) < 0.001);
});

test('commit walker: arrangement-only file claims next free slot in 0..19', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    maxApi.seedLiveTree({
        _properties: { tempo: 120 },
        tracks: [
            makeTrack('B',
                [makeClipSlot({
                    file_path: 'Macintosh HD:/abs/session.wav',
                    start_marker: 0, end_marker: 4, length: 4, warping: 1,
                })],
                [makeArrClip({
                    file_path: 'Macintosh HD:/abs/arr_only.wav',
                    start_marker: 0, end_marker: 4, length: 4, warping: 1,
                })],
            ),
        ],
    });

    const result = ctx._walkSessionAndArrangement();
    assert.equal(result.B.length, 2);
    // Session entry first (claimed slot 0 by clip-slot index).
    assert.equal(result.B[0].slot, 0);
    assert.equal(result.B[0].file, '/abs/session.wav');
    // Arrangement entry claims the next free slot (1, since 0 is taken).
    assert.equal(result.B[1].slot, 1);
    assert.equal(result.B[1].file, '/abs/arr_only.wav');
});

test('commit walker: dedup by file_path — same path in both views = one entry', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    maxApi.seedLiveTree({
        _properties: { tempo: 120 },
        tracks: [
            makeTrack('C',
                [makeClipSlot({
                    file_path: 'Macintosh HD:/abs/shared.wav',
                    start_marker: 0, end_marker: 4, length: 4, warping: 1,
                })],
                [makeArrClip({
                    file_path: 'Macintosh HD:/abs/shared.wav',
                    start_marker: 0, end_marker: 4, length: 4, warping: 1,
                })],
            ),
        ],
    });

    const result = ctx._walkSessionAndArrangement();
    assert.equal(result.C.length, 1, 'duplicate path should dedup');
    assert.equal(result.C[0].file, '/abs/shared.wav');
});

test('commit: full path — walk + POST /intent/commit with session_tracks body', () => {
    const ctx = loadConf();
    maxApi.seedFile(PORT_FILE_KEY, '7421');
    maxApi.seedLiveTree({
        _properties: { tempo: 120 },
        tracks: [
            makeTrack('A', [makeClipSlot({
                file_path: 'Macintosh HD:/abs/a.wav',
                start_marker: 0, end_marker: 4, length: 4, warping: 1,
            })]),
        ],
    });

    ctx.commit();

    const shellEmits = outletOn(4);
    const curl = shellEmits.find(a => a[0] === 'exec' && /intent\/commit/.test(a[1]));
    assert.ok(curl, 'expected commit curl emission');
    assert.match(curl[1], /session_tracks/);
    assert.match(curl[1], /\/abs\/a\.wav/);
});

// ── Verb→handler integrity: every device.yaml verb has a JS handler ─────────

test('every device.yaml verb has a callable handler on the sandbox', () => {
    const fs = require('fs');
    const yaml = require('./_yaml_lite');   // no jsdep — use a tiny parser
    const DEVICE_YAML = path.join(
        REPO_ROOT, 'v0', 'src', 'm4l-devices', 'configurator-strip', 'device.yaml',
    );
    const items = yaml.extractButtonItems(fs.readFileSync(DEVICE_YAML, 'utf8'));

    const ctx = loadConf();
    const verbToHandler = {
        'load-manifest': 'loadManifest',
        'slice':         'slice',
        'recompute':     'recompute',
        're-anchor':     'reAnchor',
        'curate':        'curate',
        'export':        'exportPpak',
        'open-editor':   'openEditor',
    };
    for (const it of items) {
        const h = verbToHandler[it.verb];
        assert.ok(h, `device.yaml verb missing in test map: ${it.verb}`);
        assert.equal(typeof ctx[h], 'function',
                     `handler ${h} (verb ${it.verb}) not exposed on sandbox`);
    }
});
