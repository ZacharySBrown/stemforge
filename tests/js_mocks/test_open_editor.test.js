// test_open_editor.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Phase 4B — openEditor() on stemforge_loader.v0.js.
//
// The footer's [ Open Editor ] button fires `messnamed("max",
// "launchbrowser", <url>)` after resolving the server's port from
// ~/stemforge/.configurator_port. This test captures the messnamed
// emissions so we can assert against the URL the loader would have
// opened in production.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, invoke } = require('./sandbox');
const maxApi = require('./max_api');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const LOADER = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js', 'stemforge_loader.v0.js');

function makeSandbox() {
    const captured = { messnamed: [] };
    const ctx = createSandbox({
        extras: {
            messnamed: function () {
                // Capture every (recv, ...args) tuple.
                captured.messnamed.push(Array.prototype.slice.call(arguments));
            },
            max: { getsystemvariable: () => '/Users/test' },
        },
    });
    loadModule(ctx, LOADER);
    return { ctx, captured };
}

test('openEditor falls back to default port 7430 when no port file is present', () => {
    maxApi.resetState();
    const { ctx, captured } = makeSandbox();

    const url = invoke(ctx, 'openEditor');

    assert.equal(url, 'http://127.0.0.1:7430/');
    assert.ok(captured.messnamed.length >= 1, 'messnamed should fire once');
    const [recv, verb, payload] = captured.messnamed[0];
    assert.equal(recv, 'max');
    assert.equal(verb, 'launchbrowser');
    assert.equal(payload, 'http://127.0.0.1:7430/');
});

test('openEditor reads the resolved port from ~/stemforge/.configurator_port', () => {
    maxApi.resetState();
    // Seed the mock filesystem with the port file at HFS path the loader looks
    // for: "Macintosh HD:/Users/test/stemforge/.configurator_port".
    // The mock File constructor converts "Macintosh HD:" → POSIX, then
    // looks up state.fs[posixPath]. Seed at the POSIX key so the open
    // succeeds.
    const hfsPath = '/Users/test/stemforge/.configurator_port';
    maxApi.seedFile(hfsPath, '7438');

    const { ctx, captured } = makeSandbox();
    const url = invoke(ctx, 'openEditor');

    assert.equal(url, 'http://127.0.0.1:7438/');
    assert.equal(captured.messnamed[0][2], 'http://127.0.0.1:7438/');
});

test('openEditor falls back when port file contains garbage', () => {
    maxApi.resetState();
    // The mock File constructor converts "Macintosh HD:" → POSIX, then
    // looks up state.fs[posixPath]. Seed at the POSIX key so the open
    // succeeds.
    const hfsPath = '/Users/test/stemforge/.configurator_port';
    maxApi.seedFile(hfsPath, 'not-a-number\n');

    const { ctx, captured } = makeSandbox();
    const url = invoke(ctx, 'openEditor');

    // parseInt would yield NaN; we fall back to the default.
    assert.equal(url, 'http://127.0.0.1:7430/');
    assert.equal(captured.messnamed[0][2], 'http://127.0.0.1:7430/');
});

test('_readConfiguratorPort returns null when HOME is unresolvable', () => {
    maxApi.resetState();
    // No `max` global → File.getenv also returns no HOME → null.
    const ctx = createSandbox({ extras: { messnamed: () => {} } });
    loadModule(ctx, LOADER);

    const port = invoke(ctx, '_readConfiguratorPort');
    assert.equal(port, null);
});
