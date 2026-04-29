// priority_chain_fixture.js
// ─────────────────────────────────────────────────────────────────────────────
// TRANSCRIPTION of the pipelineConfig priority chain from
// stemforge_loader.v0.js lines ~991–1036. Kept in lockstep with that code.
//
// If the real chain is edited and this fixture diverges, the
// `test_priority_chain_matches_source` test should be updated to catch it.
//
// Returns: { pipelineConfig, pipelineSource, pipelineName }
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

function resolvePipelineConfig(opts) {
    // opts: { Dict, manifest, fallbackConfig }
    //   Dict             — Dict constructor (real or mock)
    //   manifest         — the parsed sf_manifest object (may be null)
    //   fallbackConfig   — the PROCESSING_CONFIG fallback (stand-in for the
    //                      hardcoded IDM default)
    const Dict = opts.Dict;
    const mf = opts.manifest || {};
    const fallback = opts.fallbackConfig || { __hardcoded: true };

    let pipelineConfig = null;
    let pipelineSource = 'hardcoded';
    let pipelineName = null;

    // 1. sf_preset dict (user selected preset in dropdown).
    //    Tolerate three possible shapes:
    //      a) Top-level `stems` (direct parse-tree write)
    //      b) `root` key holds a stringified JSON blob
    //      c) `root` key holds a parsed-tree object
    try {
        const presetDict = new Dict('sf_preset');
        const presetRaw = presetDict.stringify();
        if (presetRaw && presetRaw !== '{}') {
            const outer = JSON.parse(presetRaw);
            let unwrapped = outer;
            if (outer && outer.root !== undefined) {
                if (typeof outer.root === 'string') {
                    try { unwrapped = JSON.parse(outer.root); } catch (_) { unwrapped = outer; }
                } else if (typeof outer.root === 'object') {
                    unwrapped = outer.root;
                }
            }
            if (unwrapped && unwrapped.stems) {
                pipelineConfig = unwrapped.stems;
                pipelineSource = 'sf_preset';
                pipelineName = (unwrapped.displayName
                    || unwrapped.name
                    || (unwrapped.preset && unwrapped.preset.name)
                    || '(unnamed)');
            }
        }
    } catch (_) {
        /* preset read error — fall through */
    }

    // 2. manifest-embedded processing_config (backward compat)
    if (!pipelineConfig && mf.processing_config) {
        pipelineConfig = mf.processing_config;
        pipelineSource = 'manifest-embedded';
    }

    // 3. hardcoded fallback (IDM)
    if (!pipelineConfig) {
        pipelineConfig = fallback;
        pipelineSource = 'hardcoded-IDM';
    }

    return { pipelineConfig, pipelineSource, pipelineName };
}

module.exports = { resolvePipelineConfig };
