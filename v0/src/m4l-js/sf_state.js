// sf_state.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] object (SpiderMonkey — NOT node.script). Owns the
// `sf_state` dict: every mutation flows through this file, nowhere else
// writes to it.
//
// Other modules (sf_preset_loader, sf_manifest_loader, sf_forge, sf_ui)
// READ sf_state and call into us with the messages below. We validate
// phase transitions, overwrite `sf_state.root`, then bang outlet 0 so the
// v8ui can redraw from the new state.
//
// Dicts we READ (never write): sf_preset, sf_manifest, sf_settings.
// Dict we OWN (read + write):  sf_state.
//
// Messages accepted on inlet 0 (see specs/stemforge_device_ui_contract.md §5):
//
//   setPreset <jsonString | filename>       Load preset into state; if source
//                                           also present, transition → idle.
//   setSource <jsonString>                  Load source into state; if preset
//                                           also present, transition → idle.
//   startForge                              idle → forging. Initializes
//                                           phase1.stems + phase2.targets
//                                           skeleton from current preset.
//   markPhase1Start                         Zero phase1 progress + etaSec.
//   markPhase1Progress <pct 0-1> <op...>    Update progress + currentOp.
//   markStemStart <stemName>                stems[stem] = "splitting".
//   markStemDone  <stemName>                stems[stem] = "done".
//   markPhase1Done                          phase1.active=false,
//                                           phase2.active=true.
//   markTargetStart <stem> <target>         targets[stem][target] = "creating".
//   markTargetDone  <stem> <target>         targets[stem][target] = "done";
//                                           increments targetsDone.
//   markDone <tracks> <trackStart>
//            <trackEnd> <elapsedSec>        forging → done.
//   markError <phase> <kind> <msg> <fix>    * → error. phase is 1|2. msg and
//                                           fix are single atoms (quote them
//                                           patcher-side for multi-word).
//   reset                                   → empty unless preset AND source
//                                           are already set (→ idle in that
//                                           case). Clears phase1/phase2.
//   getStateJson                            Emits "state <jsonstring>" out
//                                           outlet 0 for debug probes.
//
// Every successful mutation emits a bare `bang` out outlet 0 so the v8ui
// can refresh. Invalid transitions (e.g. empty → forging) are logged via
// post() and become no-ops — we do NOT throw.
// ─────────────────────────────────────────────────────────────────────────────

/* global Dict, outlet, post, messagename, arrayfromargs, Folder, File, max */

autowatch = 1;
inlets = 1;
outlets = 2;   // 0: bang for v8ui redraw + state probe; 1: btnState <kind> for action button config

var STATE_DICT    = "sf_state";
var PRESET_DICT   = "sf_preset";
var MANIFEST_DICT = "sf_manifest";

var STEM_ORDER = ["drums", "bass", "vocals", "other"];

// ── Dict helpers ─────────────────────────────────────────────────────────────

// Inline file-log helper (see v0/src/m4l-js/sf_logger.js for the full sink).
// Every StemForge JS module carries its own copy so a malfunctioning require()
// or broken logger doesn't take the module down. Safe to call before Max's
// File/Folder APIs are fully available (caught by try).
function _sfFileLog(module, msg) {
    try {
        var homePath;
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
        var dir = homePath + "/stemforge/logs";
        var path = dir + "/sf_debug.log";
        var maxPath = "Macintosh HD:" + path;
        // Ensure dir (best-effort via dummy file touch).
        try { new Folder("Macintosh HD:" + dir).close(); }
        catch (_) {
            try {
                var ff = new File("Macintosh HD:" + dir + "/.keep", "write", "TEXT", "TEXT");
                if (ff.isopen) { ff.writestring(""); ff.close(); }
            } catch (_) {}
        }
        var ts;
        try { ts = (new Date()).toISOString(); }
        catch (_) { ts = String(new Date().getTime()); }
        var line = "[" + ts + "] [" + String(module) + "] " + String(msg) + "\n";
        var f = new File(maxPath, "write", "TEXT", "TEXT");
        if (!f.isopen) return;
        try { f.position = f.eof; } catch (_) {}
        f.writestring(line);
        try { f.eof = f.position; } catch (_) {}
        f.close();
    } catch (_) {}
}

function logMsg(s) {
    try { post("[sf_state] " + String(s) + "\n"); } catch (_) {}
    _sfFileLog("sf_state", s);
}

function readState() {
    try {
        var d = new Dict(STATE_DICT);
        var raw = d.get("root");
        if (raw === undefined || raw === null) return { kind: "empty" };
        // Dict.get for a stored JSON object returns a dict-like; stringify it.
        var s;
        try {
            s = d.stringify();
        } catch (e) {
            return { kind: "empty" };
        }
        if (!s || s === "" || s === "{}") return { kind: "empty" };
        var parsed;
        try {
            var outer = JSON.parse(s);
            parsed = outer.root ? outer.root : outer;
        } catch (e) {
            return { kind: "empty" };
        }
        if (!parsed || !parsed.kind) return { kind: "empty" };
        return parsed;
    } catch (e) {
        return { kind: "empty" };
    }
}

function writeState(obj) {
    try {
        var d = new Dict(STATE_DICT);
        // Clear then write: dict.replace overwrites the whole tree at key.
        d.clear();
        d.parse(JSON.stringify({ root: obj }));
    } catch (e) {
        logMsg("writeState error: " + e);
        return false;
    }
    return true;
}

function readDictJson(name) {
    // Returns parsed object or null. Tolerant of missing / empty dicts.
    try {
        var d = new Dict(name);
        var s = d.stringify();
        if (!s || s === "" || s === "{}") return null;
        var outer = JSON.parse(s);
        // Dicts in StemForge nest everything under "root"
        if (outer && outer.root !== undefined) return outer.root;
        return outer;
    } catch (e) {
        return null;
    }
}

// ── PresetRef + SourceRef builders ───────────────────────────────────────────

function buildPresetRef(presetJson, filenameHint) {
    // presetJson is the full preset JSON (shape from pipelines/*.json).
    if (!presetJson || typeof presetJson !== "object") return null;

    var targetCount = 0;
    if (presetJson.stems && typeof presetJson.stems === "object") {
        for (var sk in presetJson.stems) {
            var st = presetJson.stems[sk];
            if (st && st.targets && st.targets.length) {
                targetCount += st.targets.length;
            }
        }
    }

    var palettePreview = [];
    if (presetJson.stems) {
        for (var sk2 in presetJson.stems) {
            var st2 = presetJson.stems[sk2];
            if (st2 && st2.targets) {
                for (var ti = 0; ti < st2.targets.length; ti++) {
                    var tg = st2.targets[ti];
                    var hex = null;
                    if (tg && tg.color) {
                        if (typeof tg.color === "string") hex = tg.color;
                        else if (tg.color.hex) hex = tg.color.hex;
                    }
                    if (hex && palettePreview.length < 6) {
                        palettePreview.push(hex);
                    }
                }
            }
        }
    }

    var name = presetJson.name || "";
    var fn = filenameHint ||
        (name ? (name + ".json") : "");

    return {
        filename:        String(fn),
        name:            String(name),
        displayName:     String(presetJson.displayName || presetJson.display_name || name),
        version:         String(presetJson.version || ""),
        paletteName:     String(presetJson.palette || presetJson.paletteName || ""),
        palettePreview:  palettePreview,
        targetCount:     targetCount
    };
}

function buildSourceRef(srcJson) {
    if (!srcJson || typeof srcJson !== "object") return null;
    // Pass through; fields are documented in contract §3.
    // We do NOT reshape — the loader is responsible for emitting a shape
    // that matches the SourceRef contract.
    return srcJson;
}

// ── Skeleton builders from current preset ────────────────────────────────────

function buildPhase1Stems(presetJson) {
    // Stem entries: "pending" for each stem mentioned in the preset; fall
    // back to STEM_ORDER so the UI always has a stable row set.
    var out = {};
    var have = false;
    if (presetJson && presetJson.stems) {
        for (var sk in presetJson.stems) {
            out[sk] = "pending";
            have = true;
        }
    }
    if (!have) {
        for (var i = 0; i < STEM_ORDER.length; i++) {
            out[STEM_ORDER[i]] = "pending";
        }
    }
    return out;
}

function buildPhase2Targets(presetJson) {
    // targets[stem][targetName] = "pending"
    var out = {};
    var total = 0;
    if (presetJson && presetJson.stems) {
        for (var sk in presetJson.stems) {
            var st = presetJson.stems[sk];
            if (!st || !st.targets) continue;
            out[sk] = {};
            for (var ti = 0; ti < st.targets.length; ti++) {
                var tg = st.targets[ti];
                if (tg && tg.name) {
                    out[sk][tg.name] = "pending";
                    total++;
                }
            }
        }
    }
    return { targets: out, total: total };
}

// ── Commit helper ────────────────────────────────────────────────────────────

function commit(newState, reason) {
    if (!writeState(newState)) return false;
    try { outlet(0, "bang"); } catch (_) {}
    // Outlet 1: broadcast the new kind so patcher can reconfigure the
    // action button (label + colors + enabled) without parsing dict.
    try { outlet(1, "btnState", String(newState.kind || "empty")); } catch (_) {}
    if (reason) logMsg(reason + " → " + newState.kind);
    return true;
}

function invalid(msg) {
    logMsg("invalid transition: " + msg + " (no-op)");
}

// ── Message handlers ─────────────────────────────────────────────────────────

function setPreset() {
    var args = arrayfromargs(arguments);
    if (!args.length) { logMsg("setPreset: missing arg"); return; }

    // Args may be split across atoms if patcher sends raw JSON. Rejoin.
    var joined = args.join(" ").replace(/^\s+|\s+$/g, "");
    var presetJson = null;
    var filenameHint = null;

    if (joined.charAt(0) === "{") {
        // Full JSON string
        try {
            presetJson = JSON.parse(joined);
        } catch (e) {
            logMsg("setPreset: JSON parse failed — " + e);
            return;
        }
    } else {
        // Filename form — loader has (or will) populate sf_preset for us.
        filenameHint = joined;
        presetJson = readDictJson(PRESET_DICT);
        if (!presetJson) {
            logMsg("setPreset: sf_preset dict empty; cannot resolve \"" + filenameHint + "\"");
            return;
        }
    }

    var presetRef = buildPresetRef(presetJson, filenameHint);
    if (!presetRef) { logMsg("setPreset: could not build PresetRef"); return; }

    var cur = readState();
    var source = cur.source || _stashedSource || null;
    if (!cur.source && _stashedSource) {
        _stashedSource = null;
    }

    var next;
    if (source) {
        next = { kind: "idle", preset: presetRef, source: source };
    } else {
        // No source yet — stay in empty, but include preset in the dict so
        // v8ui can render the preset card. Also stash on JS side for reset().
        _stashedPreset = presetRef;
        next = { kind: "empty", preset: presetRef };
        logMsg("setPreset: stored PresetRef; waiting for source");
    }
    commit(next, "setPreset");
}

function setSource() {
    var args = arrayfromargs(arguments);
    if (!args.length) { logMsg("setSource: missing arg"); return; }

    var joined = args.join(" ").replace(/^\s+|\s+$/g, "");
    var srcJson;
    try {
        srcJson = JSON.parse(joined);
    } catch (e) {
        logMsg("setSource: JSON parse failed — " + e);
        return;
    }
    var sourceRef = buildSourceRef(srcJson);
    if (!sourceRef) { logMsg("setSource: bad source"); return; }

    var cur = readState();
    var preset = cur.preset || _stashedPreset || null;

    // If current state had no preset but we have a stashed one, consume it.
    if (!cur.preset && _stashedPreset) {
        preset = _stashedPreset;
        _stashedPreset = null;
    }

    var next;
    if (preset) {
        next = { kind: "idle", preset: preset, source: sourceRef };
    } else {
        // No preset yet — keep kind='empty' but surface the source in the
        // dict so v8ui can display the selected card. Still stash in the
        // JS global so a later reset() can promote it to idle without a
        // second setSource call.
        _stashedSource = sourceRef;
        next = { kind: "empty", source: sourceRef };
        logMsg("setSource: stored SourceRef; waiting for preset");
    }
    commit(next, "setSource");
}

// Module-level stash for preset/source set before their counterpart.
// Classic [js] globals persist until reload, which mirrors our dict
// persistence model.
var _stashedPreset = null;
var _stashedSource = null;

function _currentPresetJson() {
    // Used by startForge to derive phase1/phase2 skeletons.
    var p = readDictJson(PRESET_DICT);
    return p;
}

function startForge() {
    var cur = readState();
    if (cur.kind !== "idle") {
        invalid("startForge requires kind=idle, got " + cur.kind);
        return;
    }

    var presetJson = _currentPresetJson();
    if (!presetJson) {
        // Can't build skeleton without the full preset JSON.
        invalid("startForge: sf_preset dict is empty");
        return;
    }

    var stems = buildPhase1Stems(presetJson);
    var phase2 = buildPhase2Targets(presetJson);

    var next = {
        kind:    "forging",
        source:  cur.source,
        preset:  cur.preset,
        phase1:  {
            active:      true,
            progress:    0.0,
            etaSec:      0,
            stems:       stems,
            engineLabel: "",
            currentOp:   ""
        },
        phase2:  {
            active:       false,
            targetsTotal: phase2.total,
            targetsDone:  0,
            targets:      phase2.targets,
            currentOp:    ""
        }
    };
    commit(next, "startForge");
}

function markPhase1Start() {
    var cur = readState();
    if (cur.kind !== "forging") { invalid("markPhase1Start: kind=" + cur.kind); return; }
    cur.phase1.active = true;
    cur.phase1.progress = 0.0;
    cur.phase1.etaSec = 0;
    cur.phase1.currentOp = "";
    commit(cur, "markPhase1Start");
}

function markPhase1Progress() {
    var args = arrayfromargs(arguments);
    if (!args.length) { logMsg("markPhase1Progress: missing pct"); return; }
    var cur = readState();
    if (cur.kind !== "forging") { invalid("markPhase1Progress: kind=" + cur.kind); return; }

    var pct = Number(args[0]);
    if (!isFinite(pct)) pct = 0;
    if (pct < 0) pct = 0;
    if (pct > 1) pct = 1;
    cur.phase1.progress = pct;

    if (args.length > 1) {
        cur.phase1.currentOp = args.slice(1).join(" ");
    }
    commit(cur, "markPhase1Progress");
}

function markStemStart() {
    var args = arrayfromargs(arguments);
    if (!args.length) { logMsg("markStemStart: missing stem"); return; }
    var stem = String(args[0]);
    var cur = readState();
    if (cur.kind !== "forging") { invalid("markStemStart: kind=" + cur.kind); return; }
    if (!cur.phase1 || !cur.phase1.stems) { invalid("markStemStart: no phase1.stems"); return; }
    if (!(stem in cur.phase1.stems)) {
        logMsg("markStemStart: unknown stem \"" + stem + "\" (adding)");
    }
    cur.phase1.stems[stem] = "splitting";
    cur.phase1.currentOp = "separating " + stem;
    commit(cur, "markStemStart(" + stem + ")");
}

function markStemDone() {
    var args = arrayfromargs(arguments);
    if (!args.length) { logMsg("markStemDone: missing stem"); return; }
    var stem = String(args[0]);
    var cur = readState();
    if (cur.kind !== "forging") { invalid("markStemDone: kind=" + cur.kind); return; }
    if (!cur.phase1 || !cur.phase1.stems) { invalid("markStemDone: no phase1.stems"); return; }
    cur.phase1.stems[stem] = "done";
    commit(cur, "markStemDone(" + stem + ")");
}

function markPhase1Done() {
    var cur = readState();
    if (cur.kind !== "forging") { invalid("markPhase1Done: kind=" + cur.kind); return; }
    if (!cur.phase1 || !cur.phase2) { invalid("markPhase1Done: missing phases"); return; }
    cur.phase1.active = false;
    cur.phase1.progress = 1.0;
    cur.phase2.active = true;
    commit(cur, "markPhase1Done");
}

function markTargetStart() {
    var args = arrayfromargs(arguments);
    if (args.length < 2) { logMsg("markTargetStart: need <stem> <target>"); return; }
    var stem = String(args[0]);
    var target = String(args[1]);

    var cur = readState();
    if (cur.kind !== "forging") { invalid("markTargetStart: kind=" + cur.kind); return; }
    if (!cur.phase2 || !cur.phase2.targets) { invalid("markTargetStart: no phase2.targets"); return; }
    if (!cur.phase2.targets[stem]) cur.phase2.targets[stem] = {};
    cur.phase2.targets[stem][target] = "creating";
    cur.phase2.currentOp = stem + "/" + target;
    commit(cur, "markTargetStart(" + stem + "/" + target + ")");
}

function markTargetDone() {
    var args = arrayfromargs(arguments);
    if (args.length < 2) { logMsg("markTargetDone: need <stem> <target>"); return; }
    var stem = String(args[0]);
    var target = String(args[1]);

    var cur = readState();
    if (cur.kind !== "forging") { invalid("markTargetDone: kind=" + cur.kind); return; }
    if (!cur.phase2 || !cur.phase2.targets) { invalid("markTargetDone: no phase2.targets"); return; }
    if (!cur.phase2.targets[stem]) cur.phase2.targets[stem] = {};
    var prev = cur.phase2.targets[stem][target];
    cur.phase2.targets[stem][target] = "done";
    if (prev !== "done") {
        cur.phase2.targetsDone = (cur.phase2.targetsDone || 0) + 1;
    }
    commit(cur, "markTargetDone(" + stem + "/" + target + ")");
}

function markDone() {
    var args = arrayfromargs(arguments);
    if (args.length < 4) { logMsg("markDone: need <tracks> <start> <end> <elapsed>"); return; }
    var cur = readState();
    if (cur.kind !== "forging") { invalid("markDone: kind=" + cur.kind); return; }

    var next = {
        kind:          "done",
        source:        cur.source,
        preset:        cur.preset,
        tracksCreated: Number(args[0]) || 0,
        trackRange:    [Number(args[1]) || 0, Number(args[2]) || 0],
        elapsedSec:    Number(args[3]) || 0
    };
    commit(next, "markDone");
}

function markError() {
    var args = arrayfromargs(arguments);
    if (args.length < 2) { logMsg("markError: need <phase> <kind> [<msg>] [<fix>]"); return; }
    var cur = readState();
    if (cur.kind === "empty") { invalid("markError: kind=empty"); return; }

    var phase = Number(args[0]);
    if (phase !== 1 && phase !== 2) phase = 1;
    var errKind = String(args[1]);
    var message = args.length > 2 ? String(args[2]) : "";
    var fix     = args.length > 3 ? String(args[3]) : "";

    var next = {
        kind:   "error",
        source: cur.source || null,
        preset: cur.preset || null,
        error:  {
            phase:   phase,
            kind:    errKind,
            message: message,
            fix:     fix
        }
    };
    // stem / target are not carried by this message per contract —
    // caller invokes separate messages if needed. For now, preserve any
    // last-known progress info on the error object.
    if (cur.kind === "forging" && cur.phase2 && cur.phase2.currentOp) {
        var parts = cur.phase2.currentOp.split("/");
        if (parts.length === 2) {
            next.error.stem = parts[0];
            next.error.target = parts[1];
        }
    }
    commit(next, "markError(" + errKind + ")");
}

function reset() {
    // reset returns to empty UNLESS preset AND source are both present, in
    // which case we land in idle (so the user can re-forge without reselecting).
    var cur = readState();
    var preset = cur.preset || _stashedPreset || null;
    var source = cur.source || _stashedSource || null;
    _stashedPreset = null;
    _stashedSource = null;

    var next;
    if (preset && source) {
        next = { kind: "idle", preset: preset, source: source };
    } else {
        next = { kind: "empty" };
        // Preserve stashes if only one side is present.
        if (preset && !source) _stashedPreset = preset;
        if (source && !preset) _stashedSource = source;
    }
    commit(next, "reset");
}

function getStateJson() {
    var cur = readState();
    var s;
    try {
        s = JSON.stringify(cur);
    } catch (e) {
        logMsg("getStateJson: stringify failed — " + e);
        s = "{\"kind\":\"empty\"}";
    }
    try { outlet(0, "state", s); } catch (_) {}
}

// ── Remote debug: dumpDict <name> ────────────────────────────────────────────
// Serializes the named dict (sf_preset, sf_manifest, sf_settings, sf_state)
// into the shared log file tagged DUMP:<name>. Lets a remote session
// snapshot any dict via `sf dump sf_preset`.
function dumpDict() {
    var args = arrayfromargs(arguments);
    if (!args.length) { logMsg("dumpDict: missing dict name"); return; }
    var name = String(args[0]);
    var allowed = { sf_state: 1, sf_preset: 1, sf_manifest: 1, sf_settings: 1 };
    if (!allowed[name]) {
        logMsg("dumpDict: unknown dict '" + name + "' (allowed: sf_state, sf_preset, sf_manifest, sf_settings)");
        return;
    }
    var tag = "DUMP:" + name;
    _sfFileLog(tag, "BEGIN");
    try {
        var d = new Dict(name);
        var s;
        try { s = d.stringify(); }
        catch (e) { s = "<stringify failed: " + e + ">"; }
        if (!s) s = "<empty>";
        // Write the full body as a single log line (let tools re-wrap on read).
        _sfFileLog(tag, s);
    } catch (e) {
        _sfFileLog(tag, "<dict read error: " + e + ">");
    }
    _sfFileLog(tag, "DUMP END");
    logMsg("dumpDict " + name + " → log");
}

// ── Test / CommonJS shim ─────────────────────────────────────────────────────
// Allows node-based unit tests to import the module without touching Max
// globals. Max's classic [js] ignores this block.
if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        buildPresetRef:     buildPresetRef,
        buildSourceRef:     buildSourceRef,
        buildPhase1Stems:   buildPhase1Stems,
        buildPhase2Targets: buildPhase2Targets,
        STEM_ORDER:         STEM_ORDER
    };
}
