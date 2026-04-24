// sandbox.js
// ─────────────────────────────────────────────────────────────────────────────
// Load a classic Max [js] source file inside a fresh Node vm context that has
// the mock Max globals pre-injected. Lets us call top-level functions on the
// returned sandbox exactly like Max would.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs = require('fs');
const vm = require('vm');
const maxApi = require('./max_api');

function createSandbox(options) {
    options = options || {};
    const ctx = {
        // Max globals — classic [js] expects these to be set before the script
        // runs. We bind the mock instances.
        Dict:           maxApi.Dict,
        File:           maxApi.File,
        Folder:         maxApi.Folder,
        LiveAPI:        maxApi.LiveAPI,
        post:           maxApi.post,
        outlet:         maxApi.outlet,
        arrayfromargs:  maxApi.arrayfromargs,
        autowatch:      0,
        inlets:         1,
        outlets:        1,
        messagename:    '',

        // Node helpers the harness itself may want (not what the device code
        // uses, but convenient for tests that load modules via require-shim).
        module:         { exports: {} },
        exports:        {},

        // JS stdlib
        JSON, Math, Date, Object, Array, String, Number, Boolean,
        RegExp, Error, parseFloat, parseInt, isFinite, isNaN, undefined,

        // Console/log for debugging tests (not used by device code).
        console,

        // For tests that want to poke sandbox-side functions back into
        // globalThis.
        globalThis: null,
    };
    ctx.globalThis = ctx;

    // Optional extra globals.
    if (options.extras) {
        for (const k in options.extras) ctx[k] = options.extras[k];
    }

    vm.createContext(ctx);
    return ctx;
}

function loadModule(sandboxCtx, srcPath) {
    const src = fs.readFileSync(srcPath, 'utf8');
    const script = new vm.Script(src, { filename: srcPath });
    script.runInContext(sandboxCtx);
    return sandboxCtx;
}

function reset() {
    maxApi.resetState();
}

// Run a message on a sandbox — sets messagename then invokes the named fn.
// `fn` may be a function reference already extracted from the sandbox or a
// string name.
function invoke(sandboxCtx, fnName /* , ...args */) {
    sandboxCtx.messagename = fnName;
    const fn = sandboxCtx[fnName];
    if (typeof fn !== 'function') {
        throw new Error('invoke: ' + fnName + ' is not a function in sandbox');
    }
    const args = Array.prototype.slice.call(arguments, 2);
    return fn.apply(sandboxCtx, args);
}

module.exports = {
    createSandbox,
    loadModule,
    reset,
    invoke,
    maxApi,
};
