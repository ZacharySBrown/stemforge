// test_reload.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Tests for the loader-side `reload()` handler added 2026-05-12 to fix the
// `sf-remote fire forge reload` no-op (docs/issues/js-reload-forwarder-broken.md).
//
// Coverage:
//   1. Static sentinel — `function reload()` exists at the top level so Max [js]
//      can dispatch the symbol to it.
//   2. Static sentinel — both source-of-truth files contain the handler (the
//      `test_loader_dispatch.test.js` byte-equality test catches drift, but
//      keep an explicit assertion here so a regression in either file fails
//      loudly).
//   3. Sandbox — calling `reload()` toggles `autowatch` 0 → 1, posts the
//      diagnostic line, and never throws. The 0 → 1 transition is the
//      mechanism Max uses to re-arm the script file-watcher; whether it
//      actually causes Max to re-eval is an on-device question this suite
//      cannot answer, but the JS-side dispatch contract is locked here.
//   4. Sandbox — `reload` is reachable via the same dispatch convention Max
//      [js] uses (top-level fn named after the inbound symbol), mirroring the
//      `sf_forge.js:reload()` → outlet 2 → loader inlet wire.
//
// Run:   node tests/js_mocks/test_reload.test.js
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs = require('fs');
const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, maxApi } = require('./sandbox');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SF_LOADER = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js', 'stemforge_loader.v0.js');
const SF_LOADER_PKG = path.join(
    REPO_ROOT, 'v0', 'src', 'm4l-package', 'StemForge', 'javascript', 'stemforge_loader.v0.js'
);


// ── 1. Static sentinel: function reload() exists in both copies ──────────────

test('reload() handler exists in stemforge_loader.v0.js (source)', () => {
    const src = fs.readFileSync(SF_LOADER, 'utf8');
    assert.match(src, /function reload\(\)/,
        'stemforge_loader.v0.js must define top-level `function reload()` for Max [js] inlet dispatch');
});

test('reload() handler exists in m4l-package copy (deploy)', () => {
    // Per memory: feedback_js_source_of_truth.md. Both copies must carry the
    // handler — the pkg copy is what ships in the .amxd.
    const src = fs.readFileSync(SF_LOADER_PKG, 'utf8');
    assert.match(src, /function reload\(\)/,
        'm4l-package stemforge_loader.v0.js must define `function reload()`');
});

test('reload() body re-arms autowatch via 0 → 1 toggle', () => {
    // Mechanism check — the fix relies on the specific autowatch 0 → 1
    // sequence. If a future change drops the toggle, this fails loudly so
    // we don't ship a silent no-op again.
    const src = fs.readFileSync(SF_LOADER, 'utf8');
    const reloadFn = src.match(/function reload\(\)\s*\{[\s\S]*?\n\}/);
    assert.ok(reloadFn, 'must be able to extract reload() function body');
    const body = reloadFn[0];
    assert.match(body, /this\.autowatch\s*=\s*0/,
        'reload() must zero autowatch before re-arming');
    assert.match(body, /this\.autowatch\s*=\s*1/,
        'reload() must set autowatch to 1 to trigger Max re-eval');
});


// ── 2. Sandbox behavior — reload() toggles autowatch end-to-end ──────────────

function loadLoader() {
    maxApi.resetState();
    const ctx = createSandbox();
    loadModule(ctx, SF_LOADER);
    return ctx;
}

test('reload(): typeof reload === "function" after loader is evaluated', () => {
    const ctx = loadLoader();
    assert.equal(typeof ctx.reload, 'function',
        'Max [js] dispatches inlet symbols to top-level functions — reload must be one');
});

test('reload(): autowatch ends at 1 after invocation', () => {
    const ctx = loadLoader();
    // Loader sets autowatch = 1 at top of file; baseline confirms our mock
    // mirrors that surface.
    assert.equal(ctx.autowatch, 1,
        'loader source sets autowatch=1 on load; sandbox should reflect that');

    ctx.reload.call(ctx);

    assert.equal(ctx.autowatch, 1,
        'reload() must leave autowatch at 1 so the file-watcher stays armed');
});

test('reload(): observes the 0 → 1 transition (the re-arm mechanism)', () => {
    // Wrap `autowatch` on the sandbox as a tracked property so we can see each
    // write. Max's [js] re-evaluates the script on the 0 → 1 transition, so
    // the test asserts the writes land in that exact order.
    const ctx = loadLoader();
    const writes = [];
    let backing = ctx.autowatch;
    Object.defineProperty(ctx, 'autowatch', {
        configurable: true,
        get: function () { return backing; },
        set: function (v) { writes.push(v); backing = v; },
    });

    ctx.reload.call(ctx);

    // We expect at least [0, 1] in order. Allow trailing writes in case the
    // implementation grows additional bookkeeping; the prefix is the contract.
    assert.ok(writes.length >= 2,
        'reload() must perform at least two autowatch writes (got: ' + writes.length + ')');
    assert.equal(writes[0], 0, 'first autowatch write must be 0 (disarm)');
    assert.equal(writes[1], 1, 'second autowatch write must be 1 (re-arm → re-eval)');
    assert.equal(backing, 1, 'final autowatch value must be 1');
});

test('reload(): posts a diagnostic line to the Max console', () => {
    const ctx = loadLoader();
    const logsBefore = maxApi.state.logs.length;

    ctx.reload.call(ctx);

    const newLogs = maxApi.state.logs.slice(logsBefore);
    const joined = newLogs.join('|');
    assert.match(joined, /reload requested via sf-remote/,
        'reload() must post a diagnostic so on-device debugging can confirm dispatch');
});

test('reload(): does not throw when autowatch writes fail', () => {
    // Defensive — wrap autowatch in a throwing setter and confirm the try/catch
    // path swallows it without taking the loader down. If reload() ever blows
    // up an inlet, every subsequent message into [js] gets dropped, so the
    // guard is load-bearing.
    const ctx = loadLoader();
    Object.defineProperty(ctx, 'autowatch', {
        configurable: true,
        get: function () { return 1; },
        set: function () { throw new Error('simulated set failure'); },
    });

    assert.doesNotThrow(function () { ctx.reload.call(ctx); },
        'reload() must catch internal errors so a failing toggle does not wedge the inlet');
});


// ── 3. Dispatch parity — sf_forge.js outlets "reload", loader handles it ─────

test('reload(): dispatchable via the Max-style symbol-to-function convention', () => {
    // Mirror how Max [js] dispatches: inlet message arrives as a symbol; the
    // [js] object looks up a top-level function with the same name and
    // invokes it with `arguments` set to the message tail. sf_forge.js sends
    // bare "reload" with no payload, so we invoke with no args.
    const ctx = loadLoader();
    const symbol = 'reload';
    const handler = ctx[symbol];
    assert.equal(typeof handler, 'function',
        'inlet dispatch requires a top-level function named "' + symbol + '"');

    ctx.messagename = symbol;
    handler.call(ctx);   // no payload — matches sf_forge.js:reload() outlet

    assert.equal(ctx.autowatch, 1,
        'autowatch must end at 1 after dispatch via the symbol-name convention');
});
