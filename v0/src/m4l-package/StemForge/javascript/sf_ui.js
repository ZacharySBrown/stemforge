/**
 * sf_ui.js — StemForge device v8ui canvas renderer
 * =================================================
 *
 * Runs in Max's v8 engine (modern JS / ES6). Attach to a [v8ui] object sized
 * 820x149 px. The v8ui area is the top portion of the 820x169 device body —
 * the bottom 20 px are native [live.comment]/[live.text] status objects.
 *
 * Responsibilities
 *   - Read the `sf_state` dict on demand; default to {kind:'empty'} on error.
 *   - Paint all 9 states (empty / idle / forging-phase1 / forging-phase2 /
 *     done / error) onto one canvas using mgraphics.
 *   - Dispatch click events through outlet 0 as lists:
 *       preset_click | source_click | forge_click | cancel_click |
 *       done_click   | retry_click  | settings_click
 *   - Drive a pulsing animation loop ONLY while state is "forging" to avoid
 *     unnecessary redraws.
 *
 * Inlet messages
 *   bang | refresh              — re-read dict, request redraw
 *   setState  <jsonString>      — debug: write raw JSON into sf_state.root
 *   setPhase  <0..1>            — debug: animation phase override
 *
 * Outlet 0 emits events per the device UI contract (spec §4).
 *
 * Layout (contract §1)
 *   Canvas:   820 x 149 px
 *   Left:     x ∈ [0, 212)    preset + source selectors (always visible)
 *   Middle:   x ∈ [212, 716)  matrix / progress / empty-prompt / error card
 *   Right:    x ∈ [716, 820)  action button (FORGE/CANCEL/DONE/RETRY)
 *
 * Dict schema: see specs/stemforge_device_ui_contract.md §3.
 *
 * Colors (contract §12)
 *   canvas bg      #2D2D33
 *   panel bg       #1E1E23
 *   border         #2A2A2A
 *   text primary   #E0E0E0
 *   text dim       #888888
 *   accent violet  #C084FC
 *   green          #4ADE80
 *   amber          #FBBF24
 *   red            #F87171
 */

// ---------------------------------------------------------------------------
// v8ui boilerplate
// ---------------------------------------------------------------------------

inlets = 1;
outlets = 1;

mgraphics.init();
mgraphics.relative_coords = 0;  // absolute pixel coords
mgraphics.autofill = 0;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CANVAS_W = 820;
const CANVAS_H = 149;

const COL_LEFT_END   = 212;
// Right column anchors to the right edge of whatever canvas we're given.
// Patcher may narrow the v8ui presentation_rect (e.g. to 608 wide so native
// umenus in the left column can receive clicks). onresize() keeps this in
// sync so FORGE button + middle-matrix width adapt to the actual canvas.
let COL_RIGHT_START = 716;

// Colors — stored as [r, g, b] 0..1 floats so we don't convert per-paint.
const COL = {
    bg:       [0.176, 0.176, 0.200], // #2D2D33
    panel:    [0.118, 0.118, 0.137], // #1E1E23
    border:   [0.165, 0.165, 0.165], // #2A2A2A
    text:     [0.878, 0.878, 0.878], // #E0E0E0
    textDim:  [0.533, 0.533, 0.533], // #888888
    textMute: [0.380, 0.380, 0.400], // dimmer placeholder grey
    violet:   [0.753, 0.518, 0.988], // #C084FC
    green:    [0.290, 0.871, 0.502], // #4ADE80
    amber:    [0.984, 0.749, 0.141], // #FBBF24
    red:      [0.973, 0.443, 0.443], // #F87171
    buttonDisabled: [0.25, 0.25, 0.28],
    pillBorder: [0.10, 0.10, 0.12],
};

const FONT_FACE = "Arial";
const FONT_SIZE_LABEL = 10;  // small header labels ("PRESET", "SOURCE")
const FONT_SIZE_VALUE = 12;  // selector values
const FONT_SIZE_META  = 10;  // meta lines (bpm/bars)
const FONT_SIZE_BODY  = 11;  // middle column body text
const FONT_SIZE_PILL  = 10;  // pill target labels
const FONT_SIZE_BTN   = 11;  // action button label

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let canvasW = CANVAS_W;
let canvasH = CANVAS_H;
let animPhase = 0;       // 0..1, advances while forging
let animTask = null;     // Task object for pulse animation
let lastKind = "empty";  // to detect state-kind transitions
let cachedFontSet = false;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Inline file-log helper — matches sf_logger.js behavior. Writes one line to
// ~/stemforge/logs/sf_debug.log. v8-engine safe (uses let/try/catch).
function _sfFileLog(module, msg) {
    try {
        let homePath = "";
        try {
            if (typeof max !== "undefined" && max && typeof max.getsystemvariable === "function") {
                homePath = String(max.getsystemvariable("HOME") || "");
            }
        } catch (_) {}
        if (!homePath) {
            try {
                if (typeof File !== "undefined" && typeof File.getenv === "function") {
                    homePath = String(File.getenv("HOME") || "");
                }
            } catch (_) {}
        }
        if (!homePath) homePath = "/Users/zak";
        const dir = homePath + "/stemforge/logs";
        const path = dir + "/sf_debug.log";
        const maxPath = "Macintosh HD:" + path;
        try { new Folder("Macintosh HD:" + dir).close(); }
        catch (_) {
            try {
                const ff = new File("Macintosh HD:" + dir + "/.keep", "write", "TEXT", "TEXT");
                if (ff.isopen) { ff.writestring(""); ff.close(); }
            } catch (_) {}
        }
        let ts;
        try { ts = (new Date()).toISOString(); }
        catch (_) { ts = String(new Date().getTime()); }
        const line = "[" + ts + "] [" + String(module) + "] " + String(msg) + "\n";
        const f = new File(maxPath, "write", "TEXT", "TEXT");
        if (!f.isopen) return;
        try { f.position = f.eof; } catch (_) {}
        f.writestring(line);
        try { f.eof = f.position; } catch (_) {}
        f.close();
    } catch (_) {}
}

function setColor(rgb, alpha) {
    if (alpha === undefined) alpha = 1.0;
    mgraphics.set_source_rgba(rgb[0], rgb[1], rgb[2], alpha);
}

function hexToRgb(hex) {
    if (!hex || typeof hex !== "string") return [0.5, 0.5, 0.5];
    let h = hex.charAt(0) === "#" ? hex.slice(1) : hex;
    if (h.length === 3) {
        h = h.charAt(0) + h.charAt(0) + h.charAt(1) + h.charAt(1) + h.charAt(2) + h.charAt(2);
    }
    if (h.length !== 6) return [0.5, 0.5, 0.5];
    const r = parseInt(h.slice(0, 2), 16) / 255;
    const g = parseInt(h.slice(2, 4), 16) / 255;
    const b = parseInt(h.slice(4, 6), 16) / 255;
    if (isNaN(r) || isNaN(g) || isNaN(b)) return [0.5, 0.5, 0.5];
    return [r, g, b];
}

/** Safe read of sf_state.root as a JS object. Mirrors sf_state.js:readState.
 *  Uses d.stringify() because Dict.get() on a nested object returns a Max
 *  dict-wrapper whose .toString() is "[object Object]", not JSON. */
function readState() {
    try {
        const d = new Dict("sf_state");
        const s = d.stringify();
        if (!s || s === "" || s === "{}") return { kind: "empty" };
        const outer = JSON.parse(s);
        const parsed = outer && outer.root ? outer.root : outer;
        if (!parsed || typeof parsed !== "object" || !parsed.kind) return { kind: "empty" };
        return parsed;
    } catch (e) {
        try { post("[sf_ui] readState error: " + e + "\n"); } catch (_) {}
        _sfFileLog("sf_ui", "readState error: " + e);
        return { kind: "empty" };
    }
}

/** Full preset body from the sf_preset dict. State.preset is a PresetRef
 *  (metadata only) — the stems tree lives in sf_preset.root as a JSON blob
 *  written by sf_preset_loader.js. Mirrors sf_forge.js:_readPresetRoot. */
function readPreset() {
    try {
        const d = new Dict("sf_preset");
        const s = d.stringify();
        if (!s || s === "" || s === "{}") return null;
        const outer = JSON.parse(s);
        // root may be a nested JSON string (loader writes d.replace("root", raw))
        // or a parsed subtree. Handle both shapes.
        let body = outer && outer.root !== undefined ? outer.root : outer;
        if (typeof body === "string") {
            try { body = JSON.parse(body); } catch (_) { return null; }
        }
        return body && typeof body === "object" ? body : null;
    } catch (e) {
        _sfFileLog("sf_ui", "readPreset error: " + e);
        return null;
    }
}

/** Rounded rectangle path. Leaves path unfilled — caller decides fill/stroke. */
function roundedRect(x, y, w, h, r) {
    const rr = Math.min(r, Math.min(w, h) / 2);
    mgraphics.move_to(x + rr, y);
    mgraphics.line_to(x + w - rr, y);
    mgraphics.curve_to(x + w - rr, y, x + w, y, x + w, y + rr);
    mgraphics.line_to(x + w, y + h - rr);
    mgraphics.curve_to(x + w, y + h - rr, x + w, y + h, x + w - rr, y + h);
    mgraphics.line_to(x + rr, y + h);
    mgraphics.curve_to(x + rr, y + h, x, y + h, x, y + h - rr);
    mgraphics.line_to(x, y + rr);
    mgraphics.curve_to(x, y + rr, x, y, x + rr, y);
}

function fillRect(x, y, w, h, rgb, alpha) {
    setColor(rgb, alpha);
    mgraphics.rectangle(x, y, w, h);
    mgraphics.fill();
}

function strokeRoundedRect(x, y, w, h, r, rgb, alpha, lineWidth) {
    setColor(rgb, alpha);
    mgraphics.set_line_width(lineWidth || 1);
    roundedRect(x, y, w, h, r);
    mgraphics.stroke();
}

function fillRoundedRect(x, y, w, h, r, rgb, alpha) {
    setColor(rgb, alpha);
    roundedRect(x, y, w, h, r);
    mgraphics.fill();
}

function ensureFontSet() {
    if (cachedFontSet) return;
    mgraphics.select_font_face(FONT_FACE);
    cachedFontSet = true;
}

function setFontSize(px) {
    ensureFontSet();
    mgraphics.set_font_size(px);
}

function textAt(x, y, str, rgb, size, alpha) {
    setFontSize(size);
    setColor(rgb, alpha === undefined ? 1.0 : alpha);
    mgraphics.move_to(x, y);
    mgraphics.show_text(String(str));
}

/** Rough text-width estimate (avg 0.55em per char for Arial body sizes). */
function textWidth(str, size) {
    if (!str) return 0;
    return Math.ceil(String(str).length * size * 0.55);
}

function clampStr(str, maxChars) {
    if (!str) return "";
    const s = String(str);
    if (s.length <= maxChars) return s;
    if (maxChars <= 1) return s.slice(0, maxChars);
    return s.slice(0, Math.max(1, maxChars - 1)) + "…";
}

// ---------------------------------------------------------------------------
// Paint entry point
// ---------------------------------------------------------------------------

function paint() {
    const state = readState();

    // Detect kind change for animation control.
    if (state.kind !== lastKind) {
        lastKind = state.kind;
        if (state.kind === "forging") {
            startAnim();
        } else {
            stopAnim();
        }
    }

    // Clear canvas background.
    fillRect(0, 0, canvasW, canvasH, COL.bg);

    // Left & middle column divider.
    fillRect(COL_LEFT_END - 1, 8, 1, canvasH - 16, COL.border);
    fillRect(COL_RIGHT_START, 8, 1, canvasH - 16, COL.border);

    drawLeftColumn(state);

    switch (state.kind) {
        case "empty":
            drawMiddleEmpty();
            break;
        case "idle":
            drawMiddleMatrix(state, /*progressMode=*/false, /*doneMode=*/false);
            break;
        case "forging":
            if (state.phase1 && state.phase1.active) {
                drawMiddlePhase1(state);
            } else {
                drawMiddleMatrix(state, /*progressMode=*/true, /*doneMode=*/false);
            }
            break;
        case "done":
            drawMiddleMatrix(state, /*progressMode=*/false, /*doneMode=*/true);
            break;
        case "error":
            drawMiddleError(state);
            break;
        default:
            drawMiddleEmpty();
            break;
    }

    drawRightButton(state);
}

// ---------------------------------------------------------------------------
// Left column — preset + source selectors
// ---------------------------------------------------------------------------

function drawLeftColumn(state) {
    // Preset selector area: y ∈ [8, 64). Header + value + palette preview.
    drawSelectorCard(8, 8, COL_LEFT_END - 16, 56, "PRESET", state.preset, "preset");

    // Small separator.
    fillRect(12, 70, COL_LEFT_END - 24, 1, COL.border);

    // Source selector area: y ∈ [78, 134).
    drawSelectorCard(8, 78, COL_LEFT_END - 16, 56, "SOURCE", state.source, "source");
}

function drawSelectorCard(x, y, w, h, labelText, ref, kind) {
    // Faint panel background so the hit zone is visible.
    fillRoundedRect(x, y, w, h, 4, COL.panel, 0.55);

    // Header label (tiny, dim).
    textAt(x + 8, y + 13, labelText, COL.textDim, FONT_SIZE_LABEL);

    if (!ref) {
        // Placeholder — grey "Pick {kind}"
        textAt(x + 8, y + 32, labelText === "PRESET" ? "Pick preset…" : "Pick source…",
               COL.textMute, FONT_SIZE_VALUE);
        // A subtle dashed bottom indicator.
        setColor(COL.border, 1.0);
        mgraphics.set_line_width(1);
        mgraphics.move_to(x + 8, y + h - 8);
        mgraphics.line_to(x + w - 8, y + h - 8);
        mgraphics.stroke();
        return;
    }

    if (kind === "preset") {
        const name = ref.displayName || ref.name || ref.filename || "(unnamed)";
        textAt(x + 8, y + 32, clampStr(name, 24), COL.text, FONT_SIZE_VALUE);

        // Palette preview strip: up to 6 tiny colored rects.
        const preview = Array.isArray(ref.palettePreview) ? ref.palettePreview.slice(0, 6) : [];
        const swatchW = 12, swatchH = 6, swatchGap = 2;
        let sx = x + 8;
        const sy = y + h - 14;
        for (let i = 0; i < preview.length; i++) {
            const rgb = hexToRgb(preview[i]);
            fillRoundedRect(sx, sy, swatchW, swatchH, 1.5, rgb, 1.0);
            sx += swatchW + swatchGap;
        }
        // Target count annotation on the right of strip.
        if (ref.targetCount) {
            const meta = ref.targetCount + " tgts";
            textAt(x + w - 8 - textWidth(meta, FONT_SIZE_META), y + h - 8,
                   meta, COL.textDim, FONT_SIZE_META);
        }
    } else {
        // Source card.
        const name = ref.filename || "(unnamed)";
        textAt(x + 8, y + 32, clampStr(name, 24), COL.text, FONT_SIZE_VALUE);

        let metaParts = [];
        if (ref.type === "manifest") {
            if (typeof ref.bpm === "number") metaParts.push(ref.bpm.toFixed(1) + " bpm");
            if (typeof ref.bars === "number") metaParts.push(ref.bars + " bars");
        } else if (ref.type === "audio") {
            if (typeof ref.durationSec === "number") {
                const m = Math.floor(ref.durationSec / 60);
                const s = Math.floor(ref.durationSec % 60);
                metaParts.push(m + ":" + (s < 10 ? "0" : "") + s);
            }
            if (ref.sampleRate) metaParts.push(Math.round(ref.sampleRate / 1000) + "k");
            metaParts.push("audio");
        }
        if (metaParts.length) {
            textAt(x + 8, y + h - 8, metaParts.join(" · "), COL.textDim, FONT_SIZE_META);
        }
    }
}

// ---------------------------------------------------------------------------
// Middle column — empty state
// ---------------------------------------------------------------------------

function drawMiddleEmpty() {
    const cx = (COL_LEFT_END + COL_RIGHT_START) / 2;
    const cy = canvasH / 2;
    const msg = "Pick a preset and source to begin";
    setFontSize(FONT_SIZE_BODY + 1);
    const w = textWidth(msg, FONT_SIZE_BODY + 1);
    textAt(cx - w / 2, cy, msg, COL.textDim, FONT_SIZE_BODY + 1);

    // Subtle dashed box to hint "drop zone" feel.
    const boxW = 260, boxH = 56;
    strokeRoundedRect(cx - boxW / 2, cy - boxH / 2 - 4, boxW, boxH, 6, COL.border, 1.0, 1);
}

// ---------------------------------------------------------------------------
// Middle column — matrix (idle / phase2 / done)
// ---------------------------------------------------------------------------

function drawMiddleMatrix(state, progressMode, doneMode) {
    // state.preset is a PresetRef (metadata only). Full stems/targets/colors
    // live in the sf_preset dict, which sf_preset_loader populates on select.
    const presetBody = readPreset();
    const stemsObj = (presetBody && presetBody.stems && typeof presetBody.stems === "object")
        ? presetBody.stems : null;

    // Middle area padding.
    const mx = COL_LEFT_END + 8;
    const my = 8;
    const mw = COL_RIGHT_START - COL_LEFT_END - 16;
    const mh = canvasH - 16;

    // If preset not resolved yet, show a soft prompt.
    if (!stemsObj) {
        setFontSize(FONT_SIZE_BODY);
        const msg = "(preset has no stems yet)";
        textAt(mx + 8, my + mh / 2, msg, COL.textDim, FONT_SIZE_BODY);
        return;
    }

    // Counter for phase2: show "N/M targets" top-right.
    if (progressMode && state.phase2) {
        const done = state.phase2.targetsDone || 0;
        const total = state.phase2.targetsTotal || 0;
        const txt = done + "/" + total + " targets";
        const tw = textWidth(txt, FONT_SIZE_META);
        textAt(mx + mw - tw - 4, my + 10, txt, COL.violet, FONT_SIZE_META);
    } else if (doneMode) {
        const tracks = (state.tracksCreated != null) ? state.tracksCreated : "";
        const range = Array.isArray(state.trackRange) ? state.trackRange : null;
        let txt = "";
        if (range && range.length === 2) txt = "tracks " + range[0] + "–" + range[1];
        else if (tracks) txt = tracks + " tracks";
        if (txt) {
            const tw = textWidth(txt, FONT_SIZE_META);
            textAt(mx + mw - tw - 4, my + 10, txt, COL.green, FONT_SIZE_META);
        }
    }

    // Determine the stem order & count.
    const stemNames = Object.keys(stemsObj);
    const stemCount = Math.max(1, stemNames.length);
    const rowH = Math.floor((mh - 4) / stemCount);

    // Phase2 target state lookup.
    const phase2Targets = (progressMode && state.phase2 && state.phase2.targets)
        ? state.phase2.targets : null;

    for (let i = 0; i < stemNames.length; i++) {
        const stemName = stemNames[i];
        const rowY = my + i * rowH + 2;

        // Stem label (left 48px of middle column).
        const stemLabelW = 48;
        textAt(mx + 2, rowY + rowH / 2 + 3, clampStr(stemName, 7),
               COL.textDim, FONT_SIZE_BODY);

        // Pills start after the label.
        const pillStartX = mx + stemLabelW;
        const pillsAreaW = mw - stemLabelW - 8;
        const targets = (stemsObj[stemName] && Array.isArray(stemsObj[stemName].targets))
            ? stemsObj[stemName].targets : [];

        drawPillRow(pillStartX, rowY, pillsAreaW, rowH,
                    targets, stemName, phase2Targets, progressMode, doneMode);
    }
}

function drawPillRow(x, y, w, h, targets, stemName, phase2Targets, progressMode, doneMode) {
    const pillH = 20;
    const pillGap = 6;
    const pillY = y + Math.floor((h - pillH) / 2);

    let cx = x;
    const limitX = x + w;

    for (let i = 0; i < targets.length; i++) {
        const t = targets[i];
        const name = t && t.name ? String(t.name) : "target";
        // Target.color can be either a hex string ("#FF4444" — older presets
        // like idm_production.json) or a descriptor object ({name, index,
        // hex} — the 4 new vibes presets). Support both so every preset
        // renders correctly. Matches stemforge_loader.v0.js:parseColor.
        let color = "#888888";
        if (t && t.color) {
            if (typeof t.color === "string") color = t.color;
            else if (typeof t.color.hex === "string") color = t.color.hex;
        }
        const pillW = Math.max(28, textWidth(name, FONT_SIZE_PILL) + 18);

        // Overflow handling: if this pill won't fit and there are more pills,
        // draw a "+N more" marker and stop.
        if (cx + pillW > limitX) {
            const remaining = targets.length - i;
            const moreTxt = "+" + remaining + " more";
            const moreW = textWidth(moreTxt, FONT_SIZE_PILL) + 10;
            if (cx + moreW <= limitX) {
                fillRoundedRect(cx, pillY, moreW, pillH, 9, COL.panel, 1.0);
                strokeRoundedRect(cx, pillY, moreW, pillH, 9, COL.border, 1.0, 1);
                textAt(cx + 5, pillY + pillH - 6, moreTxt, COL.textDim, FONT_SIZE_PILL);
            }
            break;
        }

        // Determine per-target status for phase2/done rendering.
        let status = "idle";  // idle | pending | creating | done
        if (progressMode && phase2Targets && phase2Targets[stemName]) {
            const s = phase2Targets[stemName][name];
            if (s === "creating") status = "creating";
            else if (s === "done") status = "done";
            else status = "pending";
        } else if (doneMode) {
            status = "done";
        }

        drawPill(cx, pillY, pillW, pillH, name, color, status);
        cx += pillW + pillGap;
    }
}

function drawPill(x, y, w, h, label, hexColor, status) {
    const rgb = hexToRgb(hexColor);

    if (status === "pending") {
        // Hollow outline, faded.
        strokeRoundedRect(x, y, w, h, 9, rgb, 0.55, 1);
        textAt(x + 9, y + h - 6, label, rgb, FONT_SIZE_PILL, 0.75);
        return;
    }

    if (status === "creating") {
        // Pulsing amber-tinted fill at color base.
        const pulse = 0.5 + 0.5 * Math.sin(animPhase * Math.PI * 2);
        fillRoundedRect(x, y, w, h, 9, rgb, 0.35 + 0.45 * pulse);
        strokeRoundedRect(x, y, w, h, 9, COL.amber, 0.85, 1.5);
        textAt(x + 9, y + h - 6, label, [1, 1, 1], FONT_SIZE_PILL);
        // Small amber dot on right edge.
        fillRoundedRect(x + w - 10, y + 4, 4, 4, 2, COL.amber, 0.7 + 0.3 * pulse);
        return;
    }

    if (status === "done") {
        fillRoundedRect(x, y, w, h, 9, rgb, 1.0);
        strokeRoundedRect(x, y, w, h, 9, COL.pillBorder, 0.6, 1);
        textAt(x + 9, y + h - 6, label, [1, 1, 1], FONT_SIZE_PILL);
        return;
    }

    // idle / default
    fillRoundedRect(x, y, w, h, 9, rgb, 0.95);
    strokeRoundedRect(x, y, w, h, 9, COL.pillBorder, 0.55, 1);
    textAt(x + 9, y + h - 6, label, [1, 1, 1], FONT_SIZE_PILL);
}

function drawCheck(x, y, s, rgb, lw) {
    setColor(rgb, 1.0);
    mgraphics.set_line_width(lw || 1.5);
    mgraphics.move_to(x, y);
    mgraphics.line_to(x + s * 0.4, y + s * 0.6);
    mgraphics.line_to(x + s, y - s * 0.4);
    mgraphics.stroke();
}

// ---------------------------------------------------------------------------
// Middle column — phase 1 progress
// ---------------------------------------------------------------------------

function drawMiddlePhase1(state) {
    const mx = COL_LEFT_END + 12;
    const my = 14;
    const mw = COL_RIGHT_START - COL_LEFT_END - 24;

    const p1 = state.phase1 || {};
    const engine = p1.engineLabel || "splitting";
    const currentOp = p1.currentOp || "";
    const progress = Math.max(0, Math.min(1, Number(p1.progress) || 0));

    // Top-row header: "splitting · engineLabel"
    textAt(mx, my + 4, "splitting · " + engine, COL.text, FONT_SIZE_BODY);

    // Current op (small, dim) right-aligned.
    if (currentOp) {
        const opTxt = clampStr(currentOp, 40);
        const tw = textWidth(opTxt, FONT_SIZE_META);
        textAt(mx + mw - tw, my + 4, opTxt, COL.textDim, FONT_SIZE_META);
    }

    // Progress bar.
    const barX = mx;
    const barY = my + 16;
    const barW = mw;
    const barH = 14;
    fillRoundedRect(barX, barY, barW, barH, 4, COL.panel, 1.0);
    strokeRoundedRect(barX, barY, barW, barH, 4, COL.border, 1.0, 1);
    if (progress > 0) {
        const fillW = Math.max(2, Math.floor(barW * progress));
        // Pulse the progress bar fill during activity.
        const pulse = 0.5 + 0.5 * Math.sin(animPhase * Math.PI * 2);
        fillRoundedRect(barX + 1, barY + 1, fillW - 2, barH - 2, 3,
                        COL.violet, 0.75 + 0.25 * pulse);
    }
    // Pct text centered in bar.
    const pctTxt = Math.round(progress * 100) + "%";
    const pctW = textWidth(pctTxt, FONT_SIZE_META);
    textAt(barX + barW / 2 - pctW / 2, barY + barH - 3, pctTxt, COL.text, FONT_SIZE_META);

    // ETA line.
    if (typeof p1.etaSec === "number" && p1.etaSec > 0) {
        const etaTxt = "eta " + Math.round(p1.etaSec) + "s";
        textAt(barX, barY + barH + 12, etaTxt, COL.textDim, FONT_SIZE_META);
    }

    // Per-stem status dots (drums / bass / vocals / other).
    const stems = p1.stems || {};
    const stemOrder = ["drums", "bass", "vocals", "other"];
    const dotsY = barY + barH + 22;
    let dx = barX;
    const dotSlotW = Math.floor(mw / stemOrder.length);
    for (let i = 0; i < stemOrder.length; i++) {
        const s = stemOrder[i];
        const st = stems[s] || "pending";
        drawStemDot(dx + 4, dotsY, s, st);
        dx += dotSlotW;
    }
}

function drawStemDot(x, y, label, status) {
    const r = 5;
    let fill, alpha = 1.0;
    if (status === "done")      { fill = COL.green;  }
    else if (status === "splitting") {
        fill = COL.amber;
        alpha = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(animPhase * Math.PI * 2));
    }
    else                        { fill = COL.textDim; alpha = 0.5; }

    fillRoundedRect(x, y - r, r * 2, r * 2, r, fill, alpha);
    textAt(x + r * 2 + 6, y + 3, label, COL.text, FONT_SIZE_META,
           status === "pending" ? 0.6 : 1.0);
}

// ---------------------------------------------------------------------------
// Middle column — error card
// ---------------------------------------------------------------------------

function drawMiddleError(state) {
    const mx = COL_LEFT_END + 10;
    const my = 10;
    const mw = COL_RIGHT_START - COL_LEFT_END - 20;
    const mh = canvasH - 20;

    // Bordered red card.
    fillRoundedRect(mx, my, mw, mh, 6, COL.panel, 1.0);
    strokeRoundedRect(mx, my, mw, mh, 6, COL.red, 1.0, 1.5);

    const err = state.error || {};
    const phase = err.phase || 1;
    const breadcrumbParts = ["phase " + phase];
    if (err.stem) breadcrumbParts.push(err.stem);
    if (err.target) breadcrumbParts.push(err.target);
    const breadcrumb = breadcrumbParts.join(" · ");

    // Breadcrumb (top, small, dim red).
    textAt(mx + 10, my + 15, breadcrumb, COL.red, FONT_SIZE_META, 0.85);

    // Message (bold-ish via size bump).
    const msg = clampStr(err.message || "Forge failed.", 72);
    textAt(mx + 10, my + 36, msg, COL.text, FONT_SIZE_BODY + 1);

    // Fix hint (italic-ish via dim color).
    if (err.fix) {
        const fix = clampStr(err.fix, 80);
        textAt(mx + 10, my + 56, fix, COL.textDim, FONT_SIZE_BODY);
    }

    // Error kind tag.
    if (err.kind) {
        const kindTxt = String(err.kind);
        const tw = textWidth(kindTxt, FONT_SIZE_META);
        textAt(mx + mw - tw - 10, my + 15, kindTxt, COL.red, FONT_SIZE_META, 0.7);
    }
}

// ---------------------------------------------------------------------------
// Right column — action button
// ---------------------------------------------------------------------------

function drawRightButton(state) {
    // v8ui may be sized smaller than the canonical 820 width when the
    // patcher narrows presentation_rect (e.g. to leave room for native
    // umenus in the left column). Anchor the button to the right edge of
    // whatever canvas width we actually have instead of hardcoded 716.
    const bw = 88;
    const bh = 32;
    const bx = canvasW - bw - 8;
    const by = 75 - 16;     // centered around y=75 per spec

    let label = "FORGE";
    let fillRgb = COL.violet;
    let fillAlpha = 1.0;
    let strokeRgb = null;
    let textRgb = [1, 1, 1];
    let disabled = false;

    switch (state.kind) {
        case "empty":
            label = "FORGE";
            fillRgb = COL.buttonDisabled;
            textRgb = COL.textMute;
            disabled = true;
            break;
        case "idle":
            label = "FORGE";
            fillRgb = COL.violet;
            break;
        case "forging": {
            // Solid gray "pressed" fill so the button clearly looks busy as
            // soon as state flips to forging. Subtle breathing (±6% alpha)
            // signals "alive" without the flashy amber strobe.
            label = "CANCEL";
            const pulse = 0.5 + 0.5 * Math.sin(animPhase * Math.PI * 2);
            fillRgb = COL.buttonDisabled;
            fillAlpha = 0.92 + 0.08 * pulse;
            strokeRgb = COL.border;
            textRgb = COL.amber;
            break;
        }
        case "done":
            label = "DONE";
            fillRgb = COL.green;
            fillAlpha = 0.18;
            strokeRgb = COL.green;
            textRgb = COL.green;
            break;
        case "error":
            label = "RETRY";
            fillRgb = COL.red;
            fillAlpha = 0.18;
            strokeRgb = COL.red;
            textRgb = COL.red;
            break;
    }

    // Button body.
    fillRoundedRect(bx, by, bw, bh, 16, fillRgb, fillAlpha);
    if (strokeRgb) {
        strokeRoundedRect(bx, by, bw, bh, 16, strokeRgb, 1.0, 1.5);
    } else if (disabled) {
        strokeRoundedRect(bx, by, bw, bh, 16, COL.border, 1.0, 1);
    }

    // Label text centered.
    setFontSize(FONT_SIZE_BTN + 1);
    const lw = textWidth(label, FONT_SIZE_BTN + 1);
    textAt(bx + bw / 2 - lw / 2, by + bh / 2 + 4, label, textRgb, FONT_SIZE_BTN + 1);

    // "⌘Z to undo" hint under button when state=done.
    if (state.kind === "done") {
        const hint = "⌘Z to undo";
        const hw = textWidth(hint, FONT_SIZE_META);
        textAt(bx + bw / 2 - hw / 2, by + bh + 14, hint, COL.textDim, FONT_SIZE_META);
    }

    // ETA/current-op hint under button during forging.
    if (state.kind === "forging") {
        let hint = "";
        if (state.phase1 && state.phase1.active && state.phase1.etaSec) {
            hint = "~" + Math.round(state.phase1.etaSec) + "s";
        } else if (state.phase2 && state.phase2.targetsTotal) {
            hint = state.phase2.targetsDone + "/" + state.phase2.targetsTotal;
        }
        if (hint) {
            const hw = textWidth(hint, FONT_SIZE_META);
            textAt(bx + bw / 2 - hw / 2, by + bh + 14, hint, COL.textDim, FONT_SIZE_META);
        }
    }
}

// ---------------------------------------------------------------------------
// Click handling
// ---------------------------------------------------------------------------

function onclick(x, y, button, mod1, shift, ctrl, mod2) {
    // Max passes 7 args to onclick in v8ui; only x/y are required here.
    const state = readState();

    if (x < COL_LEFT_END) {
        // Left column: preset vs source.
        if (y >= 8 && y < 64) {
            outlet(0, "preset_click");
        } else if (y >= 78 && y < 134) {
            outlet(0, "source_click");
        }
        return;
    }

    if (x >= COL_RIGHT_START) {
        // Right column action button. Dispatch per state kind.
        switch (state.kind) {
            case "empty":
                // Disabled — no-op (could outlet a "blocked" toast event later).
                return;
            case "idle":
                outlet(0, "forge_click");
                return;
            case "forging":
                outlet(0, "cancel_click");
                return;
            case "done":
                outlet(0, "done_click");
                return;
            case "error":
                outlet(0, "retry_click");
                return;
        }
        return;
    }

    // Middle column — future: pill clicks. v1: ignored.
}

function onidle() { /* unused */ }
function ondrag() { /* unused */ }
function ondblclick() { /* unused */ }

// ---------------------------------------------------------------------------
// Resize handling
// ---------------------------------------------------------------------------

function onresize(w, h) {
    canvasW = w;
    canvasH = h;
    // Right column hangs off the right edge; keep 104px of space for the
    // FORGE button + padding (was the 820 − 716 convention).
    COL_RIGHT_START = Math.max(COL_LEFT_END + 100, canvasW - 104);
    mgraphics.redraw();
}

// ---------------------------------------------------------------------------
// Inlet message handlers
// ---------------------------------------------------------------------------

function bang() {
    refresh();
}

function refresh() {
    mgraphics.redraw();
}

/**
 * Debug helper: overwrite `sf_state.root` with the given JSON string, then
 * force a redraw. Lets us exercise all 9 render modes from a Max message box:
 *     setState "{\"kind\":\"idle\",\"preset\":{...},\"source\":{...}}"
 */
function setState(jsonStr) {
    try {
        // v8 passes string args; be forgiving if it came in as anything else.
        const s = (jsonStr == null) ? "" : String(jsonStr);
        // Validate it parses before writing.
        JSON.parse(s);
        const d = new Dict("sf_state");
        d.replace("root", s);
        mgraphics.redraw();
    } catch (e) {
        post("sf_ui: setState failed — " + e + "\n");
        _sfFileLog("sf_ui", "setState failed — " + e);
    }
}

/** Debug helper to manually advance the pulse phase. */
function setPhase(p) {
    animPhase = Math.max(0, Math.min(1, Number(p) || 0));
    mgraphics.redraw();
}

// ---------------------------------------------------------------------------
// Pulse animation (runs only while forging)
// ---------------------------------------------------------------------------

function startAnim() {
    if (animTask) return;
    animTask = new Task(function () {
        animPhase = (animPhase + 0.033) % 1.0;  // ~30fps, 1-sec cycle
        mgraphics.redraw();
    }, this);
    animTask.interval = 33;  // ms
    animTask.repeat(-1);
}

function stopAnim() {
    if (!animTask) return;
    try { animTask.cancel(); } catch (e) {}
    animTask = null;
    animPhase = 0;
}

// Public — so Max "autowatch" reloads don't leave a runaway task.
function freebang() {
    stopAnim();
}

// ---------------------------------------------------------------------------
// Assist (tooltip in Max)
// ---------------------------------------------------------------------------

function assist(helpOut, helpIn) {
    if (helpOut == 1) {
        // inlet
        // no-op; Max calls assist with in/out index
    }
}
