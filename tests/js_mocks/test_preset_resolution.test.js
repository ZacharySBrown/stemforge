// test_preset_resolution.test.js
// ─────────────────────────────────────────────────────────────────────────────
// Offline regression tests for StemForge's preset / state / forge JS modules.
//
// Run:   node tests/js_mocks/test_preset_resolution.test.js
//
// Uses only Node stdlib: `node:test`, `node:assert`, `vm`, `fs`, `path`.
// No Max, no Ableton, no new npm deps.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const test = require('node:test');
const assert = require('node:assert/strict');

const { createSandbox, loadModule, invoke } = require('./sandbox');
const maxApi = require('./max_api');
const { resolvePipelineConfig } = require('./priority_chain_fixture');

// ── Paths ────────────────────────────────────────────────────────────────────
const REPO_ROOT     = path.resolve(__dirname, '..', '..');
const JS_DIR        = path.join(REPO_ROOT, 'v0', 'src', 'm4l-js');
const SF_PRESET_LOADER = path.join(JS_DIR, 'sf_preset_loader.js');
const SF_STATE     = path.join(JS_DIR, 'sf_state.js');
const SF_FORGE     = path.join(JS_DIR, 'sf_forge.js');
const LEGACY_LOADER = path.join(JS_DIR, 'stemforge_loader.v0.js');

// Source-of-truth preset dir (mock file system is seeded from here).
const REAL_PRESETS_DIR = path.join(
    os.homedir(), 'Documents', 'Max 9', 'Packages', 'StemForge', 'presets'
);

// Pick a real preset to exercise; fall back to generating a synthetic one if
// the user's Max install isn't present so the test is self-contained.
function pickRealPresetOrSynth() {
    if (fs.existsSync(REAL_PRESETS_DIR)) {
        const entries = fs.readdirSync(REAL_PRESETS_DIR)
            .filter(f => f.toLowerCase().endsWith('.json') && !f.startsWith('.'));
        if (entries.length) {
            return { source: 'disk', dir: REAL_PRESETS_DIR, files: entries };
        }
    }
    // Synthesize a minimal preset dir under a tmp hfs path.
    return { source: 'synth', dir: null, files: [] };
}

const SYNTH_PRESET = {
    name: 'test_preset',
    displayName: 'Test Preset',
    version: '9.9.9',
    palette: 'synth_palette',
    stems: {
        drums: {
            targets: [
                { name: 'loops', type: 'clips',
                    color: { name: 'red', index: 14, hex: '#FF3A34' },
                    chain: [] }
            ]
        },
        bass: {
            targets: [
                { name: 'loops', type: 'clips',
                    color: { name: 'orange', index: 1, hex: '#FFA529' },
                    chain: [] }
            ]
        }
    }
};

// ── Harness helpers ──────────────────────────────────────────────────────────

function prepFilesystemFromDisk() {
    // Seed the mock FS with the real Max package layout so sf_preset_loader's
    // _getHomePath/_resolvePresetDir probes succeed.
    const users = fs.readdirSync('/Users', { withFileTypes: true })
        .filter(e => e.isDirectory())
        .map(e => e.name);

    // Seed /Users/ directory listing. We also need each user dir itself to be
    // a seeded directory so the loader's Folder.filetype check reports "fold"
    // (filetype is inferred from whether the child path exists as a dir in
    // state.fs). Empty-seed each; only our home gets the real layout.
    maxApi.seedDir('/Users', users);
    for (const u of users) maxApi.seedDir('/Users/' + u, []);

    const home = os.homedir();          // e.g. /Users/zak
    const homeName = path.basename(home);
    // Seed nothing else for all the other user dirs; only ours needs entries.
    maxApi.seedDir('/Users/' + homeName, ['Documents']);
    maxApi.seedDir('/Users/' + homeName + '/Documents', ['Max 9']);
    maxApi.seedDir('/Users/' + homeName + '/Documents/Max 9', ['Packages']);
    maxApi.seedDir('/Users/' + homeName + '/Documents/Max 9/Packages',
        fs.existsSync(path.join(home, 'Documents/Max 9/Packages'))
            ? fs.readdirSync(path.join(home, 'Documents/Max 9/Packages'))
            : ['StemForge']);

    // Seed the presets dir itself from disk if present, otherwise synthesise.
    const real = pickRealPresetOrSynth();
    const presetDirHfs = '/Users/' + homeName + '/Documents/Max 9/Packages/StemForge/presets';

    if (real.source === 'disk') {
        maxApi.seedFilesystem(real.dir, presetDirHfs);
        return { presetDirHfs, presetFiles: real.files, realHomeName: homeName };
    } else {
        // Synth: manually seed one preset file.
        maxApi.seedDir(presetDirHfs, ['test_preset.json']);
        maxApi.seedFile(presetDirHfs + '/test_preset.json', JSON.stringify(SYNTH_PRESET));
        return {
            presetDirHfs,
            presetFiles: ['test_preset.json'],
            realHomeName: homeName
        };
    }
}

function loadPresetFileContents(presetDirHfs, filename) {
    const entry = maxApi.state.fs[presetDirHfs + '/' + filename];
    if (!entry || entry.isDir) throw new Error('missing preset file ' + filename);
    return entry.contents;
}

// ── Tests ────────────────────────────────────────────────────────────────────

// A reproduction of the PRE-FIX legacy reader. Checks only top-level
// `stems` — doesn't know about `root`. Used by bug_repro to confirm the
// original bug would have manifested.
function preFixLegacyResolve(Dict, manifest, fallback) {
    let pipelineConfig = null;
    let pipelineSource = 'hardcoded-IDM';
    try {
        const d = new Dict('sf_preset');
        const raw = d.stringify();
        if (raw && raw !== '{}') {
            const outer = JSON.parse(raw);
            if (outer && outer.stems) {
                pipelineConfig = outer.stems;
                pipelineSource = 'sf_preset';
            }
        }
    } catch (_) {}
    if (!pipelineConfig && manifest && manifest.processing_config) {
        pipelineConfig = manifest.processing_config;
        pipelineSource = 'manifest-embedded';
    }
    if (!pipelineConfig) {
        pipelineConfig = fallback;
        pipelineSource = 'hardcoded-IDM';
    }
    return { pipelineConfig, pipelineSource };
}

test('bug_repro_d_replace_root_blob — OLD writer + OLD reader falls through to hardcoded IDM', () => {
    // This reproduces the writer pattern that was in sf_preset_loader BEFORE
    // the dual-write fix: `d.replace("root", rawJsonString)`. Paired with the
    // OLD reader (no `root` unwrap), this falls through to the hardcoded IDM
    // fallback — which is the bug the user reported.
    maxApi.resetState();
    const d = new maxApi.Dict('sf_preset');
    d.replace('root', JSON.stringify(SYNTH_PRESET));   // OLD writer shape

    const result = preFixLegacyResolve(
        maxApi.Dict, {}, { __hardcoded_IDM: true }
    );

    assert.equal(result.pipelineSource, 'hardcoded-IDM',
        'BUG CONFIRMED: old writer + old reader → hardcoded fallback');
    assert.ok(result.pipelineConfig.__hardcoded_IDM);
});

test('fix_dual_write_works — current sf_preset_loader.select() makes both shapes available', () => {
    maxApi.resetState();
    const fsInfo = prepFilesystemFromDisk();
    const firstPreset = fsInfo.presetFiles[0];

    // Load sf_preset_loader.js in a sandbox.
    const ctx = createSandbox();
    loadModule(ctx, SF_PRESET_LOADER);

    // scan → populate PRESET_ENTRIES.
    invoke(ctx, 'scan');
    const outletAppends = maxApi.state.outlets[0] || [];
    assert.ok(outletAppends.length >= 2,
        'scan should have emitted clear + >=1 append');

    // Figure out which index maps to our preset filename.
    const targetDisplay = (function () {
        const raw = loadPresetFileContents(fsInfo.presetDirHfs, firstPreset);
        const obj = JSON.parse(raw);
        const nested = (obj && obj.preset) ? obj.preset : {};
        return obj.displayName || nested.displayName || nested.name ||
            (obj.name || firstPreset.replace(/\.json$/i, ''));
    })();

    // Find the append index (skip the leading "clear"). Entries are sorted
    // alphabetically by filename in the loader.
    let idx = -1;
    let appendCount = 0;
    for (const args of outletAppends) {
        if (args[0] === 'append') {
            if (args[1] === targetDisplay) { idx = appendCount; break; }
            appendCount++;
        }
    }
    assert.ok(idx >= 0, 'expected to find display name among umenu appends');

    // select → dual-write to sf_preset.
    invoke(ctx, 'select', idx);

    // Inspect sf_preset dict directly.
    const dictTree = maxApi.state.dicts['sf_preset'];
    assert.ok(dictTree, 'sf_preset dict should exist after select');
    assert.ok('root' in dictTree, 'dual-write must include root key');
    assert.ok('stems' in dictTree, 'dual-write must include top-level stems');

    // And the priority chain must resolve to sf_preset.
    const resolved = resolvePipelineConfig({
        Dict: maxApi.Dict,
        manifest: {},
        fallbackConfig: { __hardcoded: true }
    });
    assert.equal(resolved.pipelineSource, 'sf_preset',
        'current-fix loader path must resolve to sf_preset');
    assert.ok(resolved.pipelineName && resolved.pipelineName !== '(unnamed)',
        'pipelineName should be populated: ' + resolved.pipelineName);

    // setPreset message was emitted on outlet 1.
    const outlet1 = maxApi.state.outlets[1] || [];
    assert.ok(outlet1.length >= 1, 'setPreset should have fired on outlet 1');
    assert.equal(outlet1[0][0], 'setPreset');
});

test('legacy_unwrap_tolerates_all_three_shapes', () => {
    // Shape A: top-level `stems` directly.
    maxApi.resetState();
    let d = new maxApi.Dict('sf_preset');
    for (const k in SYNTH_PRESET) d.replace(k, SYNTH_PRESET[k]);
    let r = resolvePipelineConfig({ Dict: maxApi.Dict, manifest: {} });
    assert.equal(r.pipelineSource, 'sf_preset', 'shape A (top-level stems)');

    // Shape B: `root` holds a stringified JSON blob.
    maxApi.resetState();
    d = new maxApi.Dict('sf_preset');
    d.replace('root', JSON.stringify(SYNTH_PRESET));
    r = resolvePipelineConfig({ Dict: maxApi.Dict, manifest: {} });
    assert.equal(r.pipelineSource, 'sf_preset', 'shape B (root=stringified)');

    // Shape C: `root` holds a parsed object.
    maxApi.resetState();
    d = new maxApi.Dict('sf_preset');
    d.replace('root', SYNTH_PRESET);
    r = resolvePipelineConfig({ Dict: maxApi.Dict, manifest: {} });
    assert.equal(r.pipelineSource, 'sf_preset', 'shape C (root=object)');
});

test('empty_dict_falls_back', () => {
    // Case 1: no sf_preset, no manifest.processing_config → hardcoded.
    maxApi.resetState();
    let r = resolvePipelineConfig({
        Dict: maxApi.Dict,
        manifest: {},
        fallbackConfig: { __hardcoded: true }
    });
    assert.equal(r.pipelineSource, 'hardcoded-IDM');
    assert.ok(r.pipelineConfig.__hardcoded);

    // Case 2: empty sf_preset, manifest has processing_config → manifest.
    maxApi.resetState();
    // Dict exists but empty.
    new maxApi.Dict('sf_preset');
    r = resolvePipelineConfig({
        Dict: maxApi.Dict,
        manifest: { processing_config: { drums: { targets: [] } } },
        fallbackConfig: { __hardcoded: true }
    });
    assert.equal(r.pipelineSource, 'manifest-embedded');
});

test('state_mgr_transitions — setPreset+setSource → idle; setPreset alone → empty with preset', () => {
    maxApi.resetState();
    const ctx = createSandbox();
    loadModule(ctx, SF_STATE);

    // setPreset with full JSON body → empty (source still missing), but dict
    // should carry preset metadata.
    invoke(ctx, 'setPreset', JSON.stringify(SYNTH_PRESET));

    let stateTree = maxApi.state.dicts['sf_state'];
    assert.ok(stateTree && stateTree.root, 'sf_state.root must be written');
    assert.equal(stateTree.root.kind, 'empty',
        'setPreset without source → kind=empty');
    assert.ok(stateTree.root.preset, 'preset field should be surfaced');
    assert.equal(stateTree.root.preset.displayName, 'Test Preset');

    // setSource → should transition to idle now that preset was stashed.
    const source = {
        filename: 'sketch_04',
        type: 'manifest',
        bpm: 112.4,
        bars: 32,
        stemCount: 4,
        path: '/tmp/stems.json'
    };
    invoke(ctx, 'setSource', JSON.stringify(source));

    stateTree = maxApi.state.dicts['sf_state'];
    assert.equal(stateTree.root.kind, 'idle',
        'after setSource with stashed preset, kind=idle');
    assert.ok(stateTree.root.preset && stateTree.root.source);
    assert.equal(stateTree.root.source.filename, 'sketch_04');

    // Outlet 1 should have emitted btnState messages on each commit.
    const out1 = maxApi.state.outlets[1] || [];
    assert.ok(out1.some(a => a[0] === 'btnState' && a[1] === 'empty'),
        'should have broadcast btnState empty');
    assert.ok(out1.some(a => a[0] === 'btnState' && a[1] === 'idle'),
        'should have broadcast btnState idle');
});

test('priority_chain_fixture_matches_source — guard against drift', () => {
    // Read the legacy loader and verify the signature lines of the chain are
    // still present, so a future edit to the real loader triggers a test
    // failure that prompts us to update the fixture.
    const src = fs.readFileSync(LEGACY_LOADER, 'utf8');
    assert.ok(src.indexOf('pipelineSource = "sf_preset"') !== -1,
        'loader still tags pipelineSource=sf_preset');
    assert.ok(src.indexOf('pipelineSource = "manifest-embedded"') !== -1);
    assert.ok(src.indexOf('pipelineSource = "hardcoded-IDM"') !== -1);
    // Three-shape unwrap should still be in place.
    assert.ok(src.indexOf('typeof outer.root === "string"') !== -1,
        'legacy loader must still handle shape B (root=string)');
    assert.ok(src.indexOf('typeof outer.root === "object"') !== -1,
        'legacy loader must still handle shape C (root=object)');
});
