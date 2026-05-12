// _yaml_lite.js
// ─────────────────────────────────────────────────────────────────────────────
// Minimal YAML extractor used only by tests that need to read a couple of
// fields out of `v0/src/m4l-devices/configurator-strip/device.yaml`. Avoids
// pulling in a real YAML dep just for tests.
//
// Scope: extract the list of button items under
//   ui:
//     buttons:
//       items:
//         - id: btn_foo
//           verb: load-manifest
//
// Anything more complex than that is out of scope for this helper — the
// Python builder uses pyyaml for the full parse.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

function extractButtonItems(yamlText) {
    const lines = String(yamlText).split(/\r?\n/);
    let inItems = false;
    let itemsIndent = -1;
    const items = [];
    let cur = null;

    for (const raw of lines) {
        if (!inItems) {
            if (/^\s*items:\s*$/.test(raw)) {
                // Only honor this `items:` if it's nested under `buttons:`
                // — we can't track that cheaply without a real parser, but
                // device.yaml has only one `items:` block (the buttons),
                // so it's safe in practice.
                inItems = true;
                itemsIndent = raw.length - raw.replace(/^\s+/, '').length;
            }
            continue;
        }

        // Stop when we hit a less-indented non-blank line.
        if (raw.trim() === '') continue;
        const indent = raw.length - raw.replace(/^\s+/, '').length;
        if (indent <= itemsIndent) {
            inItems = false;
            if (cur) items.push(cur);
            cur = null;
            continue;
        }

        const lineNoIndent = raw.trim();
        if (lineNoIndent.startsWith('- ')) {
            if (cur) items.push(cur);
            cur = {};
            const rest = lineNoIndent.substring(2).trim();
            const m = rest.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
            if (m) cur[m[1]] = unquote(m[2]);
            continue;
        }
        const m = lineNoIndent.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
        if (m && cur) cur[m[1]] = unquote(m[2]);
    }
    if (cur) items.push(cur);
    return items;
}

function unquote(s) {
    if (s == null) return s;
    const t = String(s).trim();
    if ((t.startsWith('"') && t.endsWith('"')) ||
        (t.startsWith("'") && t.endsWith("'"))) {
        return t.substring(1, t.length - 1);
    }
    // Strip trailing comments.
    const hashIdx = t.indexOf('#');
    if (hashIdx > 0) return t.substring(0, hashIdx).trim();
    return t;
}

module.exports = { extractButtonItems };
