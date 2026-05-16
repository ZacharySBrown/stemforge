// test_open_editor.test.js
// ─────────────────────────────────────────────────────────────────────────────
// openEditor() on stemforge_loader.v0.js.
//
// The footer's [ Open Editor ] button resolves the configurator server's
// port from ~/stemforge/.configurator_port and opens the popup as a Chrome
// *app window* — `outlet(3, "/usr/bin/open", "-n", "-a", "Google Chrome",
// "--args", "--app=<url>")` → [shell]. (It used to fire `messnamed("max",
// "launchbrowser", url)`, which piled up a tab in the main browser — #129.)
// This test captures the outlet emissions to assert the opened URL.
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
    const captured = { outlet: [], messnamed: [] };
    const ctx = createSandbox({
        extras: {
            outlet: function () {
                captured.outlet.push(Array.prototype.slice.call(arguments));
            },
            messnamed: function () {
                captured.messnamed.push(Array.prototype.slice.call(arguments));
            },
            max: { getsystemvariable: () => '/Users/test' },
        },
    });
    loadModule(ctx, LOADER);
    return { ctx, captured };
}

// Assert openEditor opened `url` as a Chrome app window via outlet 3.
function assertAppWindow(captured, url) {
    assert.ok(captured.outlet.length >= 1, 'openEditor should emit on an outlet');
    const args = captured.outlet[0].map(String);
    assert.equal(args[0], '3', 'must use outlet 3 → [shell]');
    assert.match(args[1], /\/open$/, 'shells `open`');
    assert.ok(args.includes('-n'), '`-n` forces a new instance so --args applies');
    assert.ok(args.includes('--args'));
    assert.ok(args.includes('--app=' + url), 'opens the popup URL as an app window');
    // Must NOT regress to the old launchbrowser-tab behavior.
    const usedLaunchBrowser = captured.messnamed.some(
        (m) => m.indexOf('launchbrowser') !== -1,
    );
    assert.ok(!usedLaunchBrowser, 'openEditor must not use launchbrowser');
}

test('openEditor falls back to default port 7430 when no port file is present', () => {
    maxApi.resetState();
    const { ctx, captured } = makeSandbox();

    const url = invoke(ctx, 'openEditor');

    assert.equal(url, 'http://127.0.0.1:7430/');
    assertAppWindow(captured, 'http://127.0.0.1:7430/');
});

test('openEditor reads the resolved port from ~/stemforge/.configurator_port', () => {
    maxApi.resetState();
    // Seed the mock filesystem with the port file. The mock File constructor
    // converts "Macintosh HD:" → POSIX, then looks up state.fs[posixPath].
    const hfsPath = '/Users/test/stemforge/.configurator_port';
    maxApi.seedFile(hfsPath, '7438');

    const { ctx, captured } = makeSandbox();
    const url = invoke(ctx, 'openEditor');

    assert.equal(url, 'http://127.0.0.1:7438/');
    assertAppWindow(captured, 'http://127.0.0.1:7438/');
});

test('openEditor falls back when port file contains garbage', () => {
    maxApi.resetState();
    const hfsPath = '/Users/test/stemforge/.configurator_port';
    maxApi.seedFile(hfsPath, 'not-a-number\n');

    const { ctx, captured } = makeSandbox();
    const url = invoke(ctx, 'openEditor');

    // parseInt would yield NaN; we fall back to the default.
    assert.equal(url, 'http://127.0.0.1:7430/');
    assertAppWindow(captured, 'http://127.0.0.1:7430/');
});

test('_readConfiguratorPort returns null when HOME is unresolvable', () => {
    maxApi.resetState();
    // No `max` global → File.getenv also returns no HOME → null.
    const ctx = createSandbox({ extras: { messnamed: () => {}, outlet: () => {} } });
    loadModule(ctx, LOADER);

    const port = invoke(ctx, '_readConfiguratorPort');
    assert.equal(port, null);
});
