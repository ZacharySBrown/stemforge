// stemforge_loader.v0.js
// ─────────────────────────────────────────────────────────────────────────────
// Classic Max [js] object (NOT node.script). This file runs inside Max and
// has access to LiveAPI, File, Folder, post() etc. — Node-for-Max does not.
//
// Messages accepted from the bridge (via patchlines in StemForge.amxd):
//   setBpm <bpm:float>           — set song tempo from NDJSON bpm event
//   loadManifest <path:symbol>   — fired on NDJSON complete event
//
// Behavior of loadManifest:
//   1. Read stems.json via File API.
//   2. Set master tempo.
//   3. For each stem: find a matching template track (stem_target in
//      tracks.yaml — we use the same heuristics as the legacy loader).
//      - If match: duplicate the track, rename with the source track name,
//        load the WAV into clip slot 0.
//      - If the stem has a beats_dir + target is drums: duplicate the
//        Simpler template and load *every* *_beats/*.wav into polybuffer~.
//      - Else: duplicate the fallback generic audio template.
//
// Kept intentionally compatible with v0 manifests (stems.json) emitted by
// stemforge-native. Schema fields consumed:
//   manifest.bpm, manifest.track_name, manifest.stems[].name,
//   manifest.stems[].wav_path, manifest.stems[].beats_dir (optional).
// ─────────────────────────────────────────────────────────────────────────────

/* global Max, outlet, post, LiveAPI, File, Folder, Task, messagename, arrayfromargs, max */

autowatch = 1;
inlets = 1;
outlets = 4;   // 0: status text  1: bang  2: preset umenu  3: [shell] (mkdir-p)

// ── Boot version banner ──────────────────────────────────────────────────────
//
// SF_BUILD_MANIFEST is REWRITTEN at build time by
// `tools/inject_build_manifest.py`. The script computes SHA-256[:8] of
// every JS file in the Max Package + the built .amxd, joins them into a
// single line, and replaces the literal below. The loader then `post()`s
// it at every script load (including autowatch reloads), so the Max
// console always tells you which exact bytes are running.
//
// Do NOT read files at runtime here — Max's JS engine crashes on binary
// File.readstring loops (caught during second-UAT run).

// Build fingerprint, injected by tools/inject_build_manifest.py.
var SF_BUILD_MANIFEST = "build=2026-05-15T11:02 amxd=3fa393f2 js={sf_arrangement_loader=b6ee853f,sf_arrangement_reader=b67c502e,sf_clip_export=4b1a9d8c,sf_forge=3d7fcc90,sf_locator_anchor=a3bc63f2,sf_logger=4553d0b2,sf_manifest_loader=10eafd2c,sf_preset_loader=e89b01ab,sf_settings=d7628255,sf_state=e5b4e215,sf_ui=0479c90c,stemforge_bridge=723460c9,stemforge_loader=0a3ac79e,stemforge_loader.test=d411427e,stemforge_ndjson_parser=2447843f,stemforge_param_scraper=849b1239,stemforge_quadrant_router=a919d46e}";

try {
    post("[sf_loader] " + SF_BUILD_MANIFEST + "\n");
} catch (_) {}

var STEM_TARGETS = {
    // From v0/interfaces/tracks.yaml — mirrored in JS because the template
    // tracks are the user-installed ones; we need to recognise them in the
    // Live set. Keys are stem names produced by stemforge-native.
    drums:  { track: "SF | Drums Raw",         color: 0xFF4444 },
    bass:   { track: "SF | Bass",              color: 0x4477FF },
    vocals: { track: "SF | Vocals",            color: 0xFFAA44 },
    other:  { track: "SF | Texture Verb",      color: 0x44DD77 },
    guitar: { track: null,                     color: 0x888888 },  // fallback
    piano:  { track: null,                     color: 0x888888 }
};

var SIMPLER_TEMPLATE = "SF | Beat Chop Simpler";
var FALLBACK_TEMPLATE = null;   // null triggers `generic audio track` path

// Inline file-log helper (see sf_logger.js). Keeps the loader self-contained
// so a broken require() never takes track creation down.
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

function status(msg) {
    try { outlet(0, "set", String(msg)); } catch (_) {}
    try { post(String(msg) + "\n"); } catch (_) {}
    _sfFileLog("sf_loader", msg);
}

function toMaxPath(p) {
    var s = String(p);
    if (s.length > 0 && s.charAt(0) === "/") return "Macintosh HD:" + s;
    return s;
}

function readFileContents(p) {
    try {
        var f = new File(toMaxPath(p), "read");
        if (!f.isopen) return null;
        // See sf_manifest_loader for why chunk size is 32767 (signed-short cap).
        var MAX_CHUNK = 32767;
        var raw = "";
        var prev = -1;
        while (f.position < f.eof && f.position !== prev) {
            prev = f.position;
            var chunk = f.readstring(MAX_CHUNK) || "";
            if (!chunk.length) break;
            raw += chunk;
        }
        f.close();
        return raw;
    } catch (e) {
        status("readFile error: " + e);
        return null;
    }
}

function writeFileContents(p, contents) {
    // Overwrites the file at `p` with `contents`. Truncates before writing.
    // Modeled on _sfFileLog's file-write pattern — used by commitOffsets to
    // persist manifest changes back to disk.
    //
    // CRITICAL: Max File.writestring caps at 32767 chars per call (signed-short,
    // same as readstring). Writing an 84K manifest in one call silently
    // truncates to exactly 32767 bytes. Loop with safe chunks.
    try {
        var maxPath = toMaxPath(p);
        var f = new File(maxPath, "write", "TEXT", "TEXT");
        if (!f.isopen) {
            status("writeFile error: could not open " + p);
            return false;
        }
        try { f.position = 0; } catch (_) {}
        try { f.eof = 0; } catch (_) {}

        var MAX_CHUNK = 32767;
        var total = String(contents);
        var written = 0;
        var prev = -1;
        while (written < total.length && f.position !== prev) {
            prev = f.position;
            var end = written + MAX_CHUNK;
            if (end > total.length) end = total.length;
            f.writestring(total.substring(written, end));
            written = end;
        }
        try { f.eof = f.position; } catch (_) {}
        f.close();
        if (written < total.length) {
            status("writeFile: short write " + written + "/" + total.length
                + " bytes to " + p);
            return false;
        }
        return true;
    } catch (e) {
        status("writeFile error: " + e);
        return false;
    }
}

// Max named dicts have an asymmetric API: `parse(jsonStr)` stores jsonStr's
// content at the dict root (no auto-wrap), but `stringify()` emits
// `{"root": <content>}` on read. So every read needs to unwrap `.root`
// and every write should NOT re-wrap (passing a {root:...} string to
// parse() produces `.root.root` nesting on the next read).
// root may also be a stringified blob in some older dicts; handle defensively.
function _unwrapDictContent(parsed) {
    if (parsed && parsed.root !== undefined) {
        if (typeof parsed.root === "object") return parsed.root;
        if (typeof parsed.root === "string") {
            try { return JSON.parse(parsed.root); } catch (_) {}
        }
    }
    return parsed;
}

function trackCount() {
    return new LiveAPI("live_set").getcount("tracks");
}

function trackName(i) {
    var raw = new LiveAPI("live_set tracks " + i).get("name");
    return (raw && typeof raw === "object") ? String(raw[0]) : String(raw);
}

function findTrackByName(name) {
    var n = trackCount();
    for (var i = 0; i < n; i++) {
        if (trackName(i) === name) return i;
    }
    return -1;
}

function findTrackBySuffix(stem) {
    // Match any existing track whose name ends with or contains the stem
    // name. This picks up both template tracks ("SF | Drums Raw") and
    // user-renamed duplicates ("Song | drums").
    var target = String(stem).toLowerCase();
    var n = trackCount();
    for (var i = 0; i < n; i++) {
        var lower = trackName(i).toLowerCase();
        if (lower.indexOf(target) >= 0) return i;
    }
    return -1;
}

function duplicateTrack(srcIdx) {
    new LiveAPI("live_set").call("duplicate_track", srcIdx);
    return srcIdx + 1;   // Live inserts the clone immediately after.
}

function renameTrack(idx, name, color) {
    var api = new LiveAPI("live_set tracks " + idx);
    api.set("name", String(name));
    if (color !== undefined && color !== null) {
        try { api.set("color", color); } catch (_) {}
    }
}

function loadClip(trackIdx, slotIdx, wavPath, clipName, startMarkerBeats) {
    var csPath = "live_set tracks " + trackIdx + " clip_slots " + slotIdx;
    var cs = new LiveAPI(csPath);
    try {
        cs.call("create_audio_clip", String(wavPath));
    } catch (e) {
        status("create_audio_clip failed: " + e);
        return false;
    }
    try {
        var clip = new LiveAPI(csPath + " clip");
        if (clip.id !== "0" && clipName) {
            clip.set("name", String(clipName));
            clip.set("warping", 1);
            clip.set("looping", 1);
            // Note: start_marker adjustment removed — shifting clip start
            // breaks sync. Instead, the curator now boosts bars with early
            // transients during selection (prefer bars that start with a hit).
        }
    } catch (_) {}
    return true;
}

// Apply Curation v2 clip/warp-marker/offset data to an already-loaded clip.
// Feature-detects the v2 schema by checking loopEntry.clip.padded_start_sec.
// Returns true if v2 data was applied, false if the entry is legacy (caller
// should fall back to its existing warp_mode behavior). See spec sections
// 4 (warp marker types), 6 (offset flow), 9 (export formula), 10 (M4L app).
//
// `stemName` (optional) selects warp_mode from BAR_WARP_MODES. Drums/bass
// default to 0 (Beats) — far cleaner stretching of transient-heavy bar-
// aligned material than the generic 4 (Complex). Vocals/other stay at 4.
function applyCurationV2Clip(clipApi, loopEntry, stemName) {
    if (!loopEntry || !loopEntry.clip) return false;
    var clipBlock = loopEntry.clip;
    if (clipBlock.padded_start_sec === undefined) return false;
    if (!clipApi || clipApi.id === "0") return false;

    var offsets = loopEntry.offsets || {};
    var startOffset = Number(offsets.start_offset_sec) || 0.0;
    var endOffset = Number(offsets.end_offset_sec) || 0.0;

    // Default start/end = musical bar boundaries (raw_*), not padded_*.
    // Padding exists so the user can trim backward into it by committing a
    // negative start_offset (reveal an early transient they want back), or
    // forward past the bar end by committing a positive end_offset.
    // Playback on first trigger should start at the musical content.
    //
    // CRITICAL: when `warping` is on, Ableton interprets start_marker,
    // end_marker, loop_start, loop_end as BEATS (not seconds). Convert
    // using the slope implied by our intended warp markers — this is the
    // same slope we encode via move_warp_marker / add_warp_marker below,
    // so the bar boundaries and loop region stay aligned with the
    // musical content in beat-time.
    var rawStart = Number(clipBlock.raw_start_sec) || 0.0;
    var rawEnd = Number(clipBlock.raw_end_sec) || 0.0;
    var secToBeat = 1.0;
    if (loopEntry.warp_markers && loopEntry.warp_markers.length >= 2) {
        var wmFirst = loopEntry.warp_markers[0];
        var wmLast = loopEntry.warp_markers[loopEntry.warp_markers.length - 1];
        var ds = Number(wmLast.time_sec) - Number(wmFirst.time_sec);
        var db = Number(wmLast.beat_pos) - Number(wmFirst.beat_pos);
        if (isFinite(ds) && isFinite(db) && ds > 0) {
            secToBeat = db / ds;
        }
    }
    var startMarker = (rawStart + startOffset) * secToBeat;
    var endMarker = (rawEnd + endOffset) * secToBeat;

    // Set clip boundaries (spec §9)
    try { clipApi.set("start_marker", startMarker); } catch (e) {
        status("      start_marker set failed: " + e);
    }
    try { clipApi.set("end_marker", endMarker); } catch (e) {
        status("      end_marker set failed: " + e);
    }

    // Loop block (spec §5). Also in beats for warped clips.
    var loopBlock = loopEntry.loop;
    if (loopBlock && loopBlock.enabled) {
        var ls = Number(loopBlock.loop_start_sec);
        var le = Number(loopBlock.loop_end_sec);
        if (isFinite(ls)) {
            try { clipApi.set("loop_start", ls * secToBeat); } catch (_) {}
        }
        if (isFinite(le)) {
            try { clipApi.set("loop_end", le * secToBeat); } catch (_) {}
        }
        try { clipApi.set("looping", 1); } catch (_) {}
    }

    // Per-stem warp mode from BAR_WARP_MODES (drums/bass = 0 Beats,
    // vocals/other = 4 Complex). Falls back to 4 if stem is unknown.
    var wmode = 4;
    if (stemName && BAR_WARP_MODES[stemName] !== undefined) {
        wmode = BAR_WARP_MODES[stemName];
    }
    try { clipApi.set("warp_mode", wmode); } catch (_) {}

    // Warp markers — Live 12 LOM (hard-won findings):
    //   - `create_warp_marker` / `clear_all_warp_markers` are GHOST methods:
    //     LiveAPI.call returns truthy for unknown names, so these appeared
    //     to succeed but did nothing.
    //   - `add_warp_marker` takes a Dict `{beat_time, sample_time}` — NOT
    //     two floats, NOT flat key/value args. It also SILENTLY REJECTS
    //     any attempt to add at a sample_time already occupied by a marker.
    //   - `remove_warp_marker(beat_time)` takes a float beat_time, not an
    //     index. Often rejects the shadow (last) marker.
    //   - `move_warp_marker(beat_time, beat_delta)` shifts an existing
    //     marker's beat_time by delta. Identify by CURRENT beat_time.
    //   - `get("warp_markers")` returns a ONE-element array whose element
    //     is a JSON string: `["{\"warp_markers\":[...]}"]`.
    //
    // Strategy: for each target anchor, match an existing marker by
    // sample_time and MOVE its beat_time; add_warp_marker only if no
    // marker exists at that sample. The shadow marker auto-repositions
    // when we move the last visible marker.
    var wmList = loopEntry.warp_markers;
    if (wmList && wmList.length) {
        var existing = [];
        try {
            var rawVal = clipApi.get("warp_markers");
            if (rawVal && rawVal.length > 0) {
                var rawStr = (typeof rawVal[0] === "string") ? rawVal[0] : String(rawVal[0]);
                var parsed = JSON.parse(rawStr);
                if (parsed && parsed.warp_markers && parsed.warp_markers.length) {
                    existing = parsed.warp_markers;
                }
            }
        } catch (_) {}

        var moved = 0, addedNew = 0, noop = 0, failed = 0;
        for (var wi = 0; wi < wmList.length; wi++) {
            var wm = wmList[wi];
            if (!wm) continue;
            var targetTime = Number(wm.time_sec);
            var targetBeat = Number(wm.beat_pos);
            if (!isFinite(targetTime) || !isFinite(targetBeat)) continue;

            var match = null;
            for (var ei = 0; ei < existing.length; ei++) {
                if (Math.abs(existing[ei].sample_time - targetTime) < 0.001) {
                    match = existing[ei];
                    break;
                }
            }

            if (match) {
                var delta = targetBeat - match.beat_time;
                if (Math.abs(delta) < 0.0001) {
                    noop++;
                } else {
                    try {
                        clipApi.call("move_warp_marker", match.beat_time, delta);
                        moved++;
                    } catch (eMv) {
                        status("      move_warp_marker(" + match.beat_time.toFixed(4)
                            + ", " + delta.toFixed(4) + ") failed: " + eMv);
                        failed++;
                    }
                }
            } else {
                try {
                    var scratch = new Dict();
                    scratch.set("beat_time", targetBeat);
                    scratch.set("sample_time", targetTime);
                    clipApi.call("add_warp_marker", scratch);
                    addedNew++;
                } catch (eAdd) {
                    status("      add_warp_marker(beat=" + targetBeat.toFixed(3)
                        + ", sample=" + targetTime.toFixed(3) + ") failed: " + eAdd);
                    failed++;
                }
            }
        }
        status("      warp_markers: " + moved + " moved, " + addedNew + " added, "
            + noop + " no-op, " + failed + " failed");
    }

    return true;
}

function setBpm() {
    var bpm = Number(arguments[0]);
    if (!bpm || !isFinite(bpm)) { status("setBpm: invalid"); return; }
    try {
        new LiveAPI("live_set").set("tempo", bpm);
        status("tempo → " + bpm + " BPM");
    } catch (e) {
        status("setBpm error: " + e);
    }
}

// ── reload: force Max [js] to re-evaluate this file from disk ────────────────
// Fires when sf_forge.js:reload() outlets "reload" → [js stemforge_loader.v0.js]
// inlet. Without this top-level function, Max silently drops the inbound
// symbol and the file stays stale; see docs/issues/js-reload-forwarder-broken.md
// for context.
//
// Mechanism: Max's [js] object re-reads the script when `autowatch` flips from
// 0 → 1 (the watcher arms by stat-ing the file). Toggling here triggers that
// re-arm path. This is the same mechanism the documented Cmd+S workaround
// hits — saving the source file invalidates the watch + Max re-evals.
//
// Verified offline via the JS mock test in tests/js_mocks/test_reload.test.js
// (autowatch ends at 1 after the toggle, function is dispatch-callable). On-
// device verification still pending — confirm with `uv run sf-remote fire forge
// reload` on a running patch and check that an edit to this file takes effect
// without a manual Cmd+S in the [js] script editor.
function reload() {
    try {
        // Re-arm the autowatch file-watcher. Setting to 0 first guarantees the
        // 0 → 1 transition fires even when autowatch was already 1.
        this.autowatch = 0;
        this.autowatch = 1;
        status("reload requested via sf-remote");
        post("stemforge_loader: reload requested via sf-remote\n");
    } catch (e) {
        status("reload error: " + e);
    }
}

function loadManifest() {
    var manifestPath = arrayfromargs(messagename, arguments).slice(1).join(" ");
    if (!manifestPath) { status("loadManifest: missing path"); return; }

    var raw = readFileContents(manifestPath);
    if (!raw) { status("cannot read manifest: " + manifestPath); return; }
    var mf;
    try { mf = JSON.parse(raw); }
    catch (e) { status("manifest JSON parse: " + e); return; }

    if (mf.bpm) {
        try { new LiveAPI("live_set").set("tempo", Number(mf.bpm)); } catch (_) {}
    }

    if (!mf.stems || !mf.stems.length) { status("manifest has no stems"); return; }

    var loaded = 0;
    for (var i = 0; i < mf.stems.length; i++) {
        var s = mf.stems[i];
        if (!s || !s.name) continue;
        if (s.name === "residual") continue;

        // Decide source template to duplicate from.
        var cfg = STEM_TARGETS[s.name];
        var templateName = cfg && cfg.track ? cfg.track : null;
        var templateIdx = templateName ? findTrackByName(templateName) : -1;

        if (templateIdx < 0) {
            // No template for this stem. Try to at least find a matching
            // existing track by suffix (user's custom template) or create a
            // fresh audio track at the end of the set.
            templateIdx = findTrackBySuffix(s.name);
        }
        if (templateIdx < 0) {
            status("  " + s.name + ": no target track — dragging required");
            continue;
        }

        var newIdx = duplicateTrack(templateIdx);
        var clipName = (mf.track_name || "stemforge") + " | " + s.name;
        renameTrack(newIdx, clipName, cfg ? cfg.color : null);

        if (s.wav_path) {
            if (loadClip(newIdx, 0, s.wav_path, clipName)) loaded++;
        }

        // If there's a beats_dir and this stem is drums, also duplicate the
        // Simpler slice template. The actual beat sample is dragged in Live
        // 12 or loaded by a second LiveAPI call (out of v0 scope for
        // non-drums stems).
        if (s.name === "drums" && s.beats_dir) {
            var simplerIdx = findTrackByName(SIMPLER_TEMPLATE);
            if (simplerIdx >= 0) {
                var simNew = duplicateTrack(simplerIdx);
                renameTrack(simNew, (mf.track_name || "stemforge") + " | chop",
                    0xFF2400);
                status("  duplicated Simpler track for beat slices @ "
                    + s.beats_dir);
            }
        }
    }
    status("loader: " + loaded + "/" + mf.stems.length + " stems placed");
    outlet(1, "bang");
}

// ── Curated bars loader (Launchpad MVP) ──────────────────────────────────────
// Creates 4 audio tracks × 16 clip slots from a curated manifest.
// Each track maps to a Launchpad column in session clip launch mode.

var BAR_TRACK_ORDER = ["drums", "bass", "vocals", "other"];
var BAR_TRACK_COLORS = {
    drums:  0xFF4444,   // red
    bass:   0x4477FF,   // blue
    vocals: 0xFFAA44,   // orange
    other:  0x44DD77    // green
};
var BAR_WARP_MODES = {
    drums:  0,  // Beats
    bass:   0,  // Beats
    vocals: 4,  // Complex
    other:  4   // Complex
};

function createAudioTrack(insertIdx) {
    new LiveAPI("live_set").call("create_audio_track", insertIdx);
    return insertIdx;
}

function loadFromDict() {
    // Production-mode loader entry. Reads a curated manifest from a Max
    // dict (typically `sf_manifest`, populated upstream by sf_manifest_loader)
    // and dispatches to loadSong() — the only supported layout.
    //
    // Removed 2026-05-06 (after the production path proved out end-to-end on
    // believer/definition/ooh_la_la):
    //   - v1 flat-bars loader (`_loadCuratedManifest`) — superseded by
    //     loadSong's production-group layout. Manifests without
    //     layout_mode='production' are now an error rather than a v1 fallback.
    //   - v2 Drum Rack loader (`_loadCuratedV2`) — Simpler-pad-based layout
    //     for live performance. Replaced by song loader's drum rack track
    //     inside the production group; the standalone Drum-Rack-only path
    //     is no longer needed.
    //
    // If you need the old behavior, re-curate the source with
    // `--pipeline pipelines/production_idm.yaml` (or any pipeline that
    // injects processing_config). The curate script auto-overrides
    // layout_mode → production when a pipeline is supplied.
    var dictName = arrayfromargs(messagename, arguments).slice(1).join(" ") || "sf_manifest";
    var d;
    try { d = new Dict(dictName); }
    catch (e) { status("loadFromDict: cannot open dict " + dictName + ": " + e); return; }

    var mf;
    try { mf = _unwrapDictContent(JSON.parse(d.stringify())); }
    catch (e) { status("loadFromDict: parse error: " + e); return; }

    status("loaded manifest from dict: " + dictName);

    // Production manifest (curated with a pipeline that sets layout_mode).
    if (mf.layout_mode === "production") {
        status("detected production manifest → song loader");
        loadSong();
        return;
    }

    // Deck-shape manifest: only `session_tracks` populated, no `stems[]`
    // (e.g. breaks-n-beats1-style hand-curated decks). loadSong handles
    // this shape since the 2026-05-13 patch — it skips per-stem loading
    // and goes straight to _restoreSessionTracks.
    if (_sessionTracksHasContent(mf.session_tracks)) {
        status("detected deck manifest (session_tracks only) → song loader");
        loadSong();
        return;
    }

    // No legacy fallback. Surface a clear error so the user re-curates.
    var detected;
    if (mf.quadrants) detected = "v2 (quadrants)";
    else if (mf.stems) {
        var sawV2 = false;
        for (var key in mf.stems) {
            var val = mf.stems[key];
            if (val && typeof val === "object" && !Array.isArray(val) &&
                (val.loops || val.oneshots)) {
                sawV2 = true;
                break;
            }
        }
        detected = sawV2 ? "v2 (loops+oneshots)" : "v1 (flat bars)";
    } else {
        detected = "unrecognized";
    }
    status("manifest is " + detected + ", not production. Re-curate with " +
           "`--pipeline pipelines/production_idm.yaml` to produce a " +
           "production-mode manifest.");
    outlet(1, "bang");
}

function ensureScenes(n) {
    // Ensure at least N scenes exist (for clip slots 0..N-1)
    var song = new LiveAPI("live_set");
    var current = song.getcount("scenes");
    while (current < n) {
        song.call("create_scene", current);
        current++;
    }
}

// ── Config-driven song loader (Live 12.3+) ──────────────────────────────────
// Per specs/processing_config_spec.md: each stem has N targets, each target
// creates one track with a type (clips/rack) and an optional effect chain.
// Chains are either all native `insert` devices or a single `template` track.

// Default processing config — embedded for immediate testability.
// Future: loaded from pipelines/production_idm.json via a [dict].
var PROCESSING_CONFIG = {
    drums: {
        targets: [
            {
                name: "loops", type: "clips", color: 0xFF4444,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: []
            },
            {
                name: "rack", type: "rack", color: 0xFF4444,
                params: { oneshot_count: 16, oneshot_mode: "classify" },
                chain: [
                    { insert: "Compressor", params: { Threshold: 0.55, Ratio: 0.75 } }
                ]
            },
            {
                name: "crushed", type: "clips", color: 0x882222,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: [
                    { template: "decapitator_drums", macros: { Drive: 0.7, Punish: 0.5, Style: 0, OutputTrim: 0.5 } }
                ]
            },
            {
                name: "repeat", type: "clips", color: 0xCC3333,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: [
                    { insert: "Beat Repeat", params: { Chance: 0.7, Grid: 7, Variation: 5, "Variation Type": 4, "Pitch Decay": 0.4, Decay: 0.3, "Mix Type": 2, Gate: 8 } },
                    { insert: "Compressor", params: { Threshold: 0.5, Ratio: 0.8 } }
                ]
            },
            {
                name: "echo", type: "clips", color: 0xAA4444,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: [
                    { insert: "Echo", params: { "L Synced": -4, "R Synced": -3, "L Sync Mode": 2, Feedback: 0.45, "Noise On": 1, "Noise Amt": 0.3, "Wobble On": 1, "Wobble Amt": 0.25, "Reverb Level": 0.2, "Reverb Loc": 2, "Dry Wet": 0.5 } }
                ]
            },
            {
                name: "grain", type: "clips", color: 0x993333,
                params: { phrase_bars: 1, loop_count: 16 },
                chain: [
                    { insert: "Grain Delay", params: { Pitch: -7, Spray: 0.4, Frequency: 0.6, Random: 0.3, Feedback: 0.35, DryWet: 0.6 } },
                    { insert: "Reverb", params: { "Dry/Wet": 0.3 } }
                ]
            }
        ]
    },
    bass: {
        targets: [
            {
                name: "loops", type: "clips", color: 0x4477FF,
                params: { phrase_bars: 2, loop_count: 16 },
                chain: [
                    { insert: "EQ Eight", params: {} },
                    { insert: "Compressor", params: { Threshold: 0.6, Ratio: 0.65 } }
                ]
            }
        ]
    },
    vocals: {
        targets: [
            {
                name: "phrases", type: "clips", color: 0xFFAA44,
                params: { phrase_bars: 4, loop_count: 16 },
                chain: [
                    { insert: "EQ Eight", params: {} },
                    { insert: "Compressor", params: { Threshold: 0.65, Ratio: 0.6 } }
                ]
            }
        ]
    },
    other: {
        targets: [
            {
                name: "loops", type: "clips", color: 0x44DD77,
                params: { phrase_bars: 2, loop_count: 16 },
                chain: []
            },
            {
                name: "grain", type: "clips", color: 0x338855,
                params: { phrase_bars: 2, loop_count: 16 },
                chain: [
                    { insert: "Grain Delay", params: { Pitch: -5, Spray: 0.5, Frequency: 0.5, Random: 0.4, Feedback: 0.4, DryWet: 0.7 } },
                    { insert: "Reverb", params: { "Dry/Wet": 0.4 } }
                ]
            },
            {
                name: "echo", type: "clips", color: 0x2D7744,
                params: { phrase_bars: 2, loop_count: 16 },
                chain: [
                    { insert: "Echo", params: { "L Synced": -3, "R Synced": -2, "L Sync Mode": 2, Feedback: 0.5, "Noise On": 1, "Noise Amt": 0.25, "Wobble On": 1, "Wobble Amt": 0.2, "Reverb Level": 0.35, "Reverb Decay": 0.7, "Reverb Loc": 2, "Dry Wet": 0.55 } }
                ]
            }
        ]
    }
};

function applyParams(trackIdx, deviceIdx, params) {
    if (!params) return;
    var device = new LiveAPI("live_set tracks " + trackIdx + " devices " + deviceIdx);
    // Force LOM to settle after insert_device
    device.get("name");
    var paramCount = device.getcount("parameters");

    for (var paramName in params) {
        var value = params[paramName];
        var found = false;
        for (var i = 0; i < paramCount; i++) {
            var param = new LiveAPI("live_set tracks " + trackIdx + " devices " + deviceIdx + " parameters " + i);
            var pName = param.get("name");
            pName = (pName && typeof pName === "object") ? String(pName[0]) : String(pName);
            if (pName === paramName) {
                param.set("value", value);
                found = true;
                break;
            }
        }
        if (!found) {
            status("    WARN: param \"" + paramName + "\" not found on device " + deviceIdx);
        }
    }
}

function applyInsertChain(trackIdx, chain) {
    if (!chain || !chain.length) return;
    var track = new LiveAPI("live_set tracks " + trackIdx);

    for (var ci = 0; ci < chain.length; ci++) {
        var effect = chain[ci];
        if (!effect.insert) continue;

        try {
            var deviceCount = track.getcount("devices");
            track.call("insert_device", effect.insert, deviceCount);
            status("    + " + effect.insert);

            if (effect.params && Object.keys(effect.params).length > 0) {
                applyParams(trackIdx, deviceCount, effect.params);
            }
        } catch (e) {
            status("    WARN: insert failed: " + effect.insert + " — " + e);
        }
    }
}

function applyTemplateChain(chain, songName, targetName, color) {
    // Template chains create the track via duplication (no pre-created track).
    // Returns the track index of the duplicated template.
    if (!chain || !chain.length) return -1;
    var effect = chain[0];  // v1: single template per chain
    if (!effect.template) return -1;

    var templateTrackName = "[TEMPLATE] " + effect.template;
    var templateIdx = findTrackByName(templateTrackName);
    if (templateIdx < 0) {
        status("    WARN: template not found: " + templateTrackName);
        return -1;
    }

    // Duplicate template track — all devices come along
    var dupIdx = duplicateTrack(templateIdx);
    renameTrack(dupIdx, targetName + " | " + songName, color);
    status("    duplicated template: " + effect.template);

    // Apply macros if specified — scale 0-1 config values to actual param range
    if (effect.macros) {
        var rackDevice = new LiveAPI("live_set tracks " + dupIdx + " devices 0");
        var className = rackDevice.get("class_name");
        className = (className && typeof className === "object") ? String(className[0]) : String(className);

        if (className.indexOf("Rack") >= 0 || className.indexOf("Group") >= 0) {
            var paramCount = rackDevice.getcount("parameters");
            for (var macroName in effect.macros) {
                var macroVal = effect.macros[macroName];
                var found = false;
                for (var mi = 0; mi < paramCount; mi++) {
                    var mp = new LiveAPI("live_set tracks " + dupIdx + " devices 0 parameters " + mi);
                    var mn = mp.get("name");
                    mn = (mn && typeof mn === "object") ? String(mn[0]) : String(mn);
                    if (mn === macroName) {
                        var pMin = mp.get("min");
                        pMin = (pMin && typeof pMin === "object") ? Number(pMin[0]) : Number(pMin);
                        var pMax = mp.get("max");
                        pMax = (pMax && typeof pMax === "object") ? Number(pMax[0]) : Number(pMax);
                        var scaled = pMin + macroVal * (pMax - pMin);
                        mp.set("value", scaled);
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    status("    WARN: macro \"" + macroName + "\" not found");
                }
            }
        } else {
            status("    WARN: first device is not a rack (" + className + "), macros skipped");
        }
    }

    return dupIdx;
}

function buildDrumRack(trackIdx, oneshots) {
    // Live 12.3+: insert Drum Rack from scratch, add chains with Simplers.
    var track = new LiveAPI("live_set tracks " + trackIdx);
    try {
        track.call("insert_device", "Drum Rack", 0);
    } catch (e) {
        status("    ERROR inserting Drum Rack: " + e);
        return 0;
    }

    var drumRack = new LiveAPI("live_set tracks " + trackIdx + " devices 0");
    var loaded = 0;

    for (var oi = 0; oi < oneshots.length && oi < 16; oi++) {
        var os = oneshots[oi];
        if (!os || !os.file) continue;

        try {
            drumRack.call("insert_chain", oi);
            var chainPath = "live_set tracks " + trackIdx + " devices 0 chains " + oi;
            var chain = new LiveAPI(chainPath);
            chain.set("in_note", 36 + oi);
            chain.set("name", os.classification || ("pad " + oi));
            chain.call("insert_device", "Simpler", 0);

            var simpler = new LiveAPI(chainPath + " devices 0");
            simpler.call("replace_sample", String(os.file));
            try { simpler.set("playback_mode", 1); } catch (_) {}
            loaded++;
        } catch (e) {
            status("    pad " + oi + " error: " + e);
        }
    }
    return loaded;
}

function loadClipsToTrack(trackIdx, loops, stemName) {
    var warpMode = BAR_WARP_MODES[stemName] || 0;
    var loaded = 0;

    for (var li = 0; li < loops.length && li < 16; li++) {
        var item = loops[li];
        if (item && item.file) {
            var clipName = stemName + " bar " + (item.position || (li + 1));
            if (loadClip(trackIdx, li, item.file, clipName, 0)) {
                try {
                    var clipApi = new LiveAPI(
                        "live_set tracks " + trackIdx + " clip_slots " + li + " clip"
                    );
                    if (clipApi.id !== "0") {
                        // Curation v2: if entry has a clip block, apply
                        // padded markers + warp markers + offsets. Otherwise
                        // fall back to legacy per-stem warp_mode.
                        if (!applyCurationV2Clip(clipApi, item, stemName)) {
                            clipApi.set("warp_mode", warpMode);
                        }
                    }
                } catch (_) {}
                loaded++;
            }
        }
    }
    return loaded;
}

function parseColor(c) {
    // Accept integer (0xFF4444), hex string ("#FF4444"), or color-descriptor
    // object ({name, index, hex}) → integer for Live API. Object form is what
    // the preset JSON now ships (see presets/idm_production.json). We extract
    // the hex rather than the index so each target keeps its authored shade —
    // color_index would collapse shade variants that share a palette slot.
    if (typeof c === "number") return c;
    if (typeof c === "string" && c.charAt(0) === "#") {
        return parseInt(c.substring(1), 16);
    }
    if (c && typeof c === "object") {
        if (typeof c.hex === "string" && c.hex.charAt(0) === "#") {
            return parseInt(c.hex.substring(1), 16);
        }
        if (typeof c.hex === "number") return c.hex;
    }
    return null;
}

function isTemplateChain(chain) {
    // v1 constraint: chains are homogeneous — all insert OR single template.
    return chain && chain.length > 0 && chain[0].template;
}

// ── Preset system ────────────────────────────────────────────────────────────

var PRESETS_DIR = null;

function _getHomePath() {
    var skip = { Shared: 1, Library: 1, Guest: 1, admin: 1 };
    var f = new Folder("Macintosh HD:/Users/");
    var dirs = [];
    while (!f.end) {
        var fn = String(f.filename);
        if (f.filetype === "fold" && !skip[fn] && fn.charAt(0) !== ".") {
            dirs.push(fn);
        }
        f.next();
    }
    f.close();
    if (dirs.length === 1) return "/Users/" + dirs[0];
    // Check which user has the Max 9 Packages directory
    for (var i = 0; i < dirs.length; i++) {
        var testPath = "Macintosh HD:/Users/" + dirs[i] + "/Documents/Max 9/Packages";
        var tf = new Folder(testPath);
        var hasEntries = !tf.end;
        tf.close();
        if (hasEntries) return "/Users/" + dirs[i];
    }
    return "/Users/" + (dirs[0] || "unknown");
}

function scanPresets() {
    var home = _getHomePath();
    // Try multiple possible locations for the presets directory
    var candidates = [
        home + "/Documents/Max 9/Packages/StemForge/presets",
        home + "/Documents/Max 8/Packages/StemForge/presets"
    ];

    var presetsPath = null;
    var folder = null;
    for (var ci = 0; ci < candidates.length; ci++) {
        var maxPath = toMaxPath(candidates[ci]);
        try {
            var f = new Folder(maxPath);
            if (!f.end || f.filename) {
                presetsPath = candidates[ci];
                folder = f;
                break;
            }
            f.close();
        } catch (_) {}
    }

    if (!folder) {
        status("presets dir not found");
        return;
    }

    var presetNames = [];
    while (!folder.end) {
        var fn = String(folder.filename);
        if (fn.length > 5 && fn.substring(fn.length - 5) === ".json") {
            presetNames.push(fn.substring(0, fn.length - 5));
        }
        folder.next();
    }
    folder.close();

    PRESETS_DIR = presetsPath;

    // Populate umenu via outlet 2
    outlet(2, "clear");
    for (var i = 0; i < presetNames.length; i++) {
        outlet(2, "append", presetNames[i]);
    }

    // Auto-select default preset
    var defaultIdx = 0;
    for (var i = 0; i < presetNames.length; i++) {
        if (presetNames[i] === "idm_production") { defaultIdx = i; break; }
    }
    if (presetNames.length > 0) {
        outlet(2, defaultIdx);
    }

    status("found " + presetNames.length + " presets");
}

function loadPreset() {
    var name = arrayfromargs(messagename, arguments).slice(1).join(" ");
    // Strip umenu prefix if present
    name = name.replace(/^Preset:\s*/, "");
    if (!name || !PRESETS_DIR) {
        status("loadPreset: no name or presets dir");
        return;
    }

    var jsonPath = PRESETS_DIR + "/" + name + ".json";
    var raw = readFileContents(jsonPath);
    if (!raw) {
        status("cannot read preset: " + name);
        return;
    }

    var preset;
    try { preset = JSON.parse(raw); }
    catch (e) { status("preset parse error: " + e); return; }

    // Load into sf_preset dict
    var d = new Dict("sf_preset");
    d.parse(raw);

    var meta = preset.preset || {};
    status("preset: " + (meta.name || name) + " v" + (meta.version || "?"));
}

function loadSong() {
    // Config-driven song loader (Live 12.3+).
    // Reads manifest content + processing config targets.
    // For each stem: iterates targets, creates appropriate track, loads content,
    // applies effect chain (native insert or template duplication).
    var dictName = "sf_manifest";
    var d;
    try { d = new Dict(dictName); }
    catch (e) { status("loadSong: cannot open dict " + dictName + ": " + e); return; }

    var mf;
    try { mf = _unwrapDictContent(JSON.parse(d.stringify())); }
    catch (e) { status("loadSong: parse error: " + e); return; }

    var stemData = mf.stems;
    var hasSessionTracks = _sessionTracksHasContent(mf.session_tracks);

    // Two valid manifest shapes:
    //   - SOURCE shape: `stems[]` populated, no session_tracks. The
    //     loader duplicates per-stem template tracks + drops curated
    //     bars, then _restoreSessionTracks is a no-op (auto-populate
    //     drum hits instead).
    //   - DECK shape: `session_tracks` populated, no stems[]. The user
    //     has previously committed an A/B/C/D arrangement. We skip the
    //     per-stem loop and go straight to _restoreSessionTracks, which
    //     drops clips at the saved slots from `file` paths alone.
    //
    // The original code required `stems[]`, which made it impossible to
    // re-load a deck-shape manifest (e.g. breaks-n-beats1) for editing.
    if (!stemData && !hasSessionTracks) {
        status("manifest has neither stems[] nor session_tracks");
        return;
    }

    var songName = mf.track || "stemforge";
    var loaded = 0;

    if (mf.bpm) {
        try { new LiveAPI("live_set").set("tempo", Number(mf.bpm)); } catch (_) {}
        status("tempo → " + mf.bpm + " BPM");
    }

    ensureScenes(16);

    // Deck-shape: no stems to load → straight to session_tracks restore.
    if (!stemData) {
        _restoreSessionTracks(mf, {});
        outlet(1, "bang");
        return;
    }

    // Priority chain: sf_preset dict → manifest embedding → hardcoded fallback
    var pipelineConfig = null;
    var pipelineSource = "hardcoded";
    var pipelineName = null;

    // 1. sf_preset dict (user selected preset in dropdown).
    //    Tolerate three possible shapes:
    //      a) Top-level `stems` (direct parse-tree write)
    //      b) `root` key holds a stringified JSON blob
    //      c) `root` key holds a parsed-tree object
    try {
        var presetDict = new Dict("sf_preset");
        var presetRaw = presetDict.stringify();
        if (presetRaw && presetRaw !== "{}") {
            var outer = JSON.parse(presetRaw);
            var unwrapped = outer;
            if (outer && outer.root !== undefined) {
                if (typeof outer.root === "string") {
                    try { unwrapped = JSON.parse(outer.root); } catch (_) { unwrapped = outer; }
                } else if (typeof outer.root === "object") {
                    unwrapped = outer.root;
                }
            }
            if (unwrapped && unwrapped.stems) {
                pipelineConfig = unwrapped.stems;
                pipelineSource = "sf_preset";
                pipelineName = (unwrapped.displayName
                    || unwrapped.name
                    || (unwrapped.preset && unwrapped.preset.name)
                    || "(unnamed)");
            }
        }
    } catch (e) {
        status("sf_preset read error: " + e);
    }

    // 2. manifest-embedded processing_config (backward compat)
    if (!pipelineConfig && mf.processing_config) {
        pipelineConfig = mf.processing_config;
        pipelineSource = "manifest-embedded";
    }

    // 3. hardcoded fallback (IDM)
    if (!pipelineConfig) {
        pipelineConfig = PROCESSING_CONFIG;
        pipelineSource = "hardcoded-IDM";
    }
    status("pipelineConfig source: " + pipelineSource
        + (pipelineName ? " (" + pipelineName + ")" : ""));

    var stemOrder = ["drums", "bass", "vocals", "other"];

    for (var si = 0; si < stemOrder.length; si++) {
        var stemName = stemOrder[si];
        var data = stemData[stemName];
        if (!data) continue;

        var stemCap = stemName.charAt(0).toUpperCase() + stemName.slice(1);

        // Get content from manifest
        var loops = Array.isArray(data) ? data : (data.loops || []);
        var oneshots = (typeof data === "object" && !Array.isArray(data)) ? (data.oneshots || []) : [];

        // Get targets from processing config
        var stemConfig = pipelineConfig[stemName];
        if (!stemConfig || !stemConfig.targets) {
            // Fallback: create a simple clips track if we have loops
            if (loops.length > 0) {
                var fallbackIdx = trackCount();
                createAudioTrack(fallbackIdx);
                renameTrack(fallbackIdx, stemCap + " Loops | " + songName, BAR_TRACK_COLORS[stemName]);
                loaded += loadClipsToTrack(fallbackIdx, loops, stemName);
                status("  " + stemCap + " Loops: " + loops.length + " clips (no config)");
            }
            continue;
        }

        // Iterate targets from processing config
        var targets = stemConfig.targets;
        for (var ti = 0; ti < targets.length; ti++) {
            var target = targets[ti];
            var targetName = stemCap + " " + (target.name || "Track");
            var targetColor = parseColor(target.color) || BAR_TRACK_COLORS[stemName];
            var chain = target.chain || [];

            status("  " + targetName + " (" + target.type + ")");

            if (target.type === "clips") {
                // ── Clips target: audio track with bar loops ──
                if (loops.length === 0) {
                    status("    skipped (no loops in manifest)");
                    continue;
                }

                var clipsTrackIdx;

                if (isTemplateChain(chain)) {
                    // Template chain: duplicate creates the track
                    clipsTrackIdx = applyTemplateChain(chain, songName, targetName, targetColor);
                    if (clipsTrackIdx < 0) continue;
                } else {
                    // Native chain: create track, then insert devices
                    clipsTrackIdx = trackCount();
                    createAudioTrack(clipsTrackIdx);
                    renameTrack(clipsTrackIdx, targetName + " | " + songName, targetColor);

                    if (chain.length > 0) {
                        applyInsertChain(clipsTrackIdx, chain);
                    }
                }

                var clipsLoaded = loadClipsToTrack(clipsTrackIdx, loops, stemName);
                loaded += clipsLoaded;
                status("    " + clipsLoaded + " clips loaded");

            } else if (target.type === "rack") {
                // ── Rack target: MIDI track with Drum Rack ──
                if (oneshots.length === 0) {
                    status("    skipped (no oneshots in manifest)");
                    continue;
                }

                var rackTrackIdx = trackCount();
                new LiveAPI("live_set").call("create_midi_track", rackTrackIdx);
                renameTrack(rackTrackIdx, targetName + " | " + songName, targetColor);

                var rackLoaded = buildDrumRack(rackTrackIdx, oneshots);
                loaded += rackLoaded;
                status("    " + rackLoaded + " pads loaded");

                // Apply chain AFTER Drum Rack (effects go on the track, after the rack)
                if (chain.length > 0 && !isTemplateChain(chain)) {
                    applyInsertChain(rackTrackIdx, chain);
                }
            }
        }
    }

    status("song loader: " + loaded + " items across " + stemOrder.length + " stems for \"" + songName + "\"");

    // ── EP-133 hybrid session: restore A/B/C/D OR auto-populate ─────────
    // If the manifest already has a `session_tracks` block (= user has
    // committed a curation pass before), restore every clip on A/B/C/D
    // from there. Otherwise this is a first FORGE — just drop the first
    // 4 drum hits into Track A slots 1-4 as a starting point.
    if (_sessionTracksHasContent(mf.session_tracks)) {
        _restoreSessionTracks(mf, stemData);
    } else {
        _autoPopulateTrackAHits(stemData);
    }

    outlet(1, "bang");
}

function _sessionTracksHasContent(s) {
    if (!s) return false;
    var letters = ["A", "B", "C", "D"];
    for (var i = 0; i < letters.length; i++) {
        if (s[letters[i]] && s[letters[i]].length > 0) return true;
    }
    return false;
}

function _autoPopulateTrackAHits(stemData) {
    var drumsBlock = (stemData && stemData.drums) || {};
    var hits = drumsBlock.oneshots || [];
    if (hits.length === 0) return;
    var trackA = findTrackByName("A");
    if (trackA < 0) {
        status("Track A not found — skipped hit auto-populate "
            + "(add an audio track named 'A' to your template)");
        return;
    }
    var hitsToDrop = Math.min(4, hits.length);
    var droppedA = 0;
    for (var ai = 0; ai < hitsToDrop; ai++) {
        var hit = hits[ai];
        if (!hit || !hit.file) continue;
        var hitName = "hit " + (ai + 1)
            + (hit.classification ? " (" + hit.classification + ")" : "");
        if (loadClip(trackA, ai, hit.file, hitName, 0)) droppedA++;
    }
    status("Track A auto-populated: " + droppedA + " drum hits in slots 1-" + droppedA);
}

function _deleteClipIfPresent(trackIdx, slotIdx) {
    try {
        var cs = new LiveAPI("live_set tracks " + trackIdx + " clip_slots " + slotIdx);
        // has_clip is a property; if 1, delete it.
        var has = _getLomNumber(cs, "has_clip");
        if (has === 1) cs.call("delete_clip");
    } catch (_) {}
}

function _buildFileToLoopEntry(stemData) {
    // Index every loop + oneshot across all stems by their `file` path so
    // we can look up the matching loopEntry from a session_tracks entry's
    // file field. Used to apply warp markers + raw_*_sec context to clips
    // dropped on A/B/C/D from the same source WAVs.
    var index = {};
    if (!stemData) return index;
    var stemNames = ["drums", "bass", "vocals", "other"];
    for (var si = 0; si < stemNames.length; si++) {
        var stem = stemNames[si];
        var block = stemData[stem];
        if (!block) continue;
        var loops = Array.isArray(block) ? block : (block.loops || []);
        for (var li = 0; li < loops.length; li++) {
            if (loops[li] && loops[li].file) {
                index[loops[li].file] = { entry: loops[li], stemName: stem };
            }
        }
        var oneshots = (block.oneshots) || [];
        for (var oi = 0; oi < oneshots.length; oi++) {
            if (oneshots[oi] && oneshots[oi].file) {
                index[oneshots[oi].file] = { entry: oneshots[oi], stemName: stem };
            }
        }
    }
    return index;
}

function _restoreSessionTracks(mf, stemData) {
    // Re-create every clip on A/B/C/D from the manifest's session_tracks
    // block. For each entry: drop the WAV, apply warp markers from the
    // matching loopEntry (so the clip plays at session BPM), then override
    // start_marker / end_marker with the saved session offsets.
    var session = mf.session_tracks || {};
    var letters = ["A", "B", "C", "D"];
    var bpm = Number(mf.bpm) || 120.0;
    var secToBeat = bpm / 60.0;
    var fileToLoopEntry = _buildFileToLoopEntry(stemData);
    var totalRestored = 0;

    for (var li = 0; li < letters.length; li++) {
        var letter = letters[li];
        var trackIdx = findTrackByName(letter);
        if (trackIdx < 0) continue;
        var entries = session[letter] || [];
        for (var ei = 0; ei < entries.length; ei++) {
            var e = entries[ei];
            if (!e || !e.file) continue;
            var slot = Number(e.slot) | 0;

            // Wipe the slot if anything is already there (auto-populate
            // ran before us OR a stale clip is present from prior FORGE).
            _deleteClipIfPresent(trackIdx, slot);

            var clipName = letter + (slot + 1);
            if (!loadClip(trackIdx, slot, e.file, clipName, 0)) continue;

            // Apply warp markers + clip block from the matching loopEntry,
            // if any. Hits / unmatched files just stay as plain audio
            // clips with default Ableton warp behavior.
            var lookup = fileToLoopEntry[e.file];
            try {
                var clipApi = new LiveAPI(
                    "live_set tracks " + trackIdx + " clip_slots " + slot + " clip"
                );
                if (clipApi && clipApi.id !== "0") {
                    if (lookup && lookup.entry) {
                        applyCurationV2Clip(clipApi, lookup.entry, lookup.stemName);
                    }
                    // Now override markers with the user's session-saved
                    // positions. clip is warped → markers are in beats.
                    var startSec = Number(e.start_offset_sec) || 0.0;
                    var endSec = Number(e.end_offset_sec) || 0.0;
                    var warping = _getLomNumber(clipApi, "warping") | 0;
                    if (warping) {
                        try { clipApi.set("start_marker", startSec * secToBeat); } catch (_) {}
                        try { clipApi.set("end_marker", endSec * secToBeat); } catch (_) {}
                    } else {
                        try { clipApi.set("start_marker", startSec); } catch (_) {}
                        try { clipApi.set("end_marker", endSec); } catch (_) {}
                    }
                }
            } catch (_) {}
            totalRestored++;
        }
    }
    var counts = letters.map(function (l) {
        return l + "=" + (session[l] ? session[l].length : 0);
    }).join(" ");
    status("session_tracks restored: " + totalRestored + " clips (" + counts + ")");
}

// ── Curation v2: commit offsets (Ableton → manifest) ────────────────────────
// Per spec §6. Walks every track × clip_slot (up to 31), matches loaded clips
// against manifest entries by file_path, reads the current start_marker /
// end_marker from the LOM, computes the offset vs padded_*_sec, and writes
// the result back to the manifest (sf_manifest dict or disk file).
//
// Two call shapes:
//   commitOffsets                    → reads/writes the `sf_manifest` dict
//   commitOffsets <absManifestPath>  → reads/writes the file on disk

function _stripHfsPrefix(s) {
    if (!s) return "";
    var str = String(s);
    // LOM returns paths as "Macintosh HD:/Users/..." — strip the prefix so
    // manifest entries stored as POSIX paths compare cleanly.
    if (str.indexOf("Macintosh HD:") === 0) {
        return str.substring("Macintosh HD:".length);
    }
    return str;
}

function _getLomString(api, prop) {
    // Returns "" for missing / null / undefined / empty-array LOM properties so
    // downstream `if (!s)` checks work correctly. Pre-2026-05-08 this returned
    // the literal string "undefined" when the property was absent (Live's mock
    // and real-world LOM both surface missing props as `undefined` after the
    // [0] indexing) — that string is truthy and slipped past empty-clip checks
    // in `_commitSessionTracks` and friends.
    try {
        var v = api.get(prop);
        var s = (v && typeof v === "object") ? v[0] : v;
        if (s === undefined || s === null) return "";
        var str = String(s);
        if (str === "undefined") return "";
        return str;
    } catch (_) {
        return "";
    }
}

function _getLomNumber(api, prop) {
    try {
        var v = api.get(prop);
        if (v && typeof v === "object") return Number(v[0]);
        return Number(v);
    } catch (_) {
        return NaN;
    }
}

function _buildClipIndex() {
    // Returns {posixPath: {trackIdx, slotIdx}} for every loaded audio clip in
    // the live set, covering clip_slots 0..30 on each track.
    var index = {};
    var n = trackCount();
    for (var ti = 0; ti < n; ti++) {
        for (var sj = 0; sj < 31; sj++) {
            var csPath = "live_set tracks " + ti + " clip_slots " + sj;
            var clipApi;
            try {
                clipApi = new LiveAPI(csPath + " clip");
            } catch (_) { continue; }
            if (!clipApi || clipApi.id === "0") continue;
            var fp = _getLomString(clipApi, "file_path");
            if (!fp) continue;
            var posix = _stripHfsPrefix(fp);
            if (!posix) continue;
            if (!index[posix]) {
                index[posix] = { trackIdx: ti, slotIdx: sj };
            }
        }
    }
    return index;
}

function _commitEntryOffsets(entry, clipIndex) {
    // Mutates `entry` in place. Returns true if offsets were committed.
    if (!entry || !entry.clip || !entry.file) return false;
    if (entry.clip.padded_start_sec === undefined) return false;

    var target = String(entry.file);
    var hit = clipIndex[target];
    if (!hit) {
        // Also try stripping HFS from the manifest side, in case it stored a
        // Macintosh HD: path.
        hit = clipIndex[_stripHfsPrefix(target)];
    }
    if (!hit) {
        // Clip not present in the live set — treat as user-deleted.
        // Mark selected=false so downstream consumers (EP-133 export, etc.)
        // can filter to only the user's keepers. Workflow: drag start
        // markers → delete the clips you don't want → COMMIT.
        var dropped = entry.offsets || {};
        dropped.committed = true;
        dropped.selected = false;
        if (dropped.note === undefined) dropped.note = "";
        entry.offsets = dropped;
        return true;
    }

    var clipApi = new LiveAPI(
        "live_set tracks " + hit.trackIdx + " clip_slots " + hit.slotIdx + " clip"
    );
    if (!clipApi || clipApi.id === "0") {
        // Same disposition as missing clip — slot exists but no clip in it.
        var dropped2 = entry.offsets || {};
        dropped2.committed = true;
        dropped2.selected = false;
        if (dropped2.note === undefined) dropped2.note = "";
        entry.offsets = dropped2;
        return true;
    }

    // Ableton returns start_marker/end_marker in BEATS for warped clips.
    // Convert back to seconds using the slope derived from the manifest's
    // warp_markers so the computed offsets are in the same units the manifest
    // stores them (seconds, relative to raw_*).
    var startMarkerBeats = _getLomNumber(clipApi, "start_marker");
    var endMarkerBeats = _getLomNumber(clipApi, "end_marker");
    if (!isFinite(startMarkerBeats) || !isFinite(endMarkerBeats)) return false;

    var beatToSec = 1.0;
    if (entry.warp_markers && entry.warp_markers.length >= 2) {
        var wmFirst = entry.warp_markers[0];
        var wmLast = entry.warp_markers[entry.warp_markers.length - 1];
        var ds = Number(wmLast.time_sec) - Number(wmFirst.time_sec);
        var db = Number(wmLast.beat_pos) - Number(wmFirst.beat_pos);
        if (isFinite(ds) && isFinite(db) && db > 0) {
            beatToSec = ds / db;
        }
    }
    var startMarkerSec = startMarkerBeats * beatToSec;
    var endMarkerSec = endMarkerBeats * beatToSec;

    // Offsets are relative to raw_* (the musical bar boundaries), matching
    // applyCurationV2Clip's default start/end = raw_* + offset. A negative
    // start_offset means the user trimmed backward into the left pad to
    // reveal an early transient; positive means they trimmed forward past
    // the bar start. Same symmetry for end_offset with the right pad.
    var rawStart = Number(entry.clip.raw_start_sec) || 0.0;
    var rawEnd = Number(entry.clip.raw_end_sec) || 0.0;

    var offsets = entry.offsets || {};
    offsets.start_offset_sec = startMarkerSec - rawStart;
    offsets.end_offset_sec = endMarkerSec - rawEnd;
    offsets.committed = true;
    offsets.selected = true;     // present in live set = user kept it
    if (offsets.note === undefined) offsets.note = "";
    entry.offsets = offsets;
    return true;
}

// Build one session_tracks entry from a Clip-shaped LOM object. Pulls
// start/end/length markers + warping; converts beats→sec when warped.
// Returns null when the clip lacks a usable file_path.
//
// `projectBeatToSec` is 60/project_bpm. Used for beats↔seconds conversion
// in this function.
//
// Per-clip BPM via `warp_bpm` is deliberately NOT read here. Two reasons:
//
// 1. The dominant workflow is bounceTracks → COMMIT, which crops every
//    clip first. Post-crop, clips either go warping=0 (rendered at
//    project tempo, markers in seconds) or warping=1 with warp_bpm ==
//    project tempo. Either way the per-clip BPM == project BPM, so
//    reading it adds nothing.
//
// 2. Reading `warp_bpm` on clips where it's unavailable (Live 12 Beta
//    raises `'Clip' object has no attribute 'warp_bpm'` on cropped
//    clips even when warping=1) generates one error line per clip in
//    the Max console. _getLomNumber's try/catch handles the throw
//    functionally but doesn't suppress Max's underlying logging.
//
// **When to add this back:** if a workflow shows up where the user
// commits CLIPS THAT WEREN'T BOUNCED (e.g. drags a clip in from a 100
// BPM source song into a 90 BPM project and commits before cropping).
// In that case the manifest needs per-clip bpm so EP-133's stretch
// math is right (sound_bpm = source's actual tempo). Probe with
// getinfo() first to avoid the AttributeError noise on clips where
// the property is unexposed.
function _sessionTrackEntryFromClip(clipApi, slot, projectBeatToSec, preCropKey) {
    var fp = _getLomString(clipApi, "file_path");
    if (!fp) return null;
    var posix = _stripHfsPrefix(fp);

    var warping = _getLomNumber(clipApi, "warping") | 0;
    var startMarker = _getLomNumber(clipApi, "start_marker");
    var endMarker = _getLomNumber(clipApi, "end_marker");
    var clipLength = _getLomNumber(clipApi, "length");
    var beatToSec = projectBeatToSec;

    var startSec = warping ? startMarker * beatToSec : startMarker;
    var endSec = warping ? endMarker * beatToSec : endMarker;
    var lengthSec = warping ? clipLength * beatToSec : clipLength;

    // Trim vs rotate: end-marker within ~10ms of the clip's natural end
    // → user only moved start → rotate. Otherwise trim.
    var EPS = 0.010;
    var mode = (Math.abs(endSec - lengthSec) < EPS) ? "rotate" : "trim";

    var entry = {
        slot: slot,
        file: posix,
        start_offset_sec: startSec,
        end_offset_sec: endSec,
        clip_length_sec: lengthSec,
        mode: mode,
    };

    // Per-clip source_bpm: computed pre-crop in _capturePreCropMeta from
    // the slope between two adjacent warp_markers (Live's LOM does NOT
    // expose `warp_bpm` directly, but `warp_markers` is exposed as a dict
    // of beat_time/sample_time pairs; the slope IS warp_bpm). Downstream
    // (clip_index → deck_plan → kit_synthesizer) consumes this as
    // sound.bpm and skips duration-based inference when present.
    var hit = preCropKey && _preCropMeta && _preCropMeta[preCropKey];
    if (hit) {
        var meta = _preCropMeta[preCropKey];
        if (typeof meta.warp_bpm === "number" && meta.warp_bpm > 0) {
            entry.source_bpm = meta.warp_bpm;
        }
    }

    return entry;
}

function _commitSessionTracks(mf) {
    // Walks tracks named A / B / C / D in BOTH session view AND arrangement
    // view, captures every loaded clip's file path + start/end markers
    // (converted to seconds) + a "mode" hint for the export tool.
    //
    // mode is inferred from end_marker:
    //   - "rotate"  if end_marker is at the clip's natural end (user only
    //               moved start) — for loops the export tool will rotate
    //               the WAV so start_marker = sample 0.
    //   - "trim"    if end_marker has been moved inward — user picked a
    //               specific region; the export tool slices that region.
    //
    // Session-view clips claim slots = their clip-slot index (0..30, the
    // column row). Arrangement-only files (no matching session entry)
    // get the next unused slot in 0..19 (EP-133 SAMPLE_SLOT_PER_GROUP cap).
    // Dedup is by file_path: a file present in BOTH views is registered
    // once at its session-view slot.
    //
    // PHASE 3 NOTE: file_path is the dedup key today because audio_hash
    // populates as "" (configurator commit-side hashing not wired yet).
    // When Phase 3 adds hashing at COMMIT time, switch dedup to audio_hash
    // — same content under different paths (re-anchored WAVs, splice
    // sources from another song's directory) should dedupe to one entry.
    //
    // Slot-claim ordering is now load-bearing: downstream code (the
    // resolver, the EP-133 synthesizer's slot→pad mapping) depends on the
    // sequential-from-zero rule. Any future change to this algorithm
    // (e.g. "prefer historical assignments") must keep existing fixtures'
    // slot assignments stable or migrate them explicitly.
    //
    // Writes into mf.session_tracks = {A: [...], B: [...], C: [...], D: [...]}.
    // Empty arrays for letter-tracks that don't exist or have no clips
    // anywhere on either view.
    var letters = ["A", "B", "C", "D"];
    var bpm = Number(mf.bpm) || 120.0;
    var beatToSec = 60.0 / bpm;
    var result = { A: [], B: [], C: [], D: [] };
    var SLOTS_PER_GROUP = 20; // matches stemforge.exporters.ep133 SAMPLE_SLOT_PER_GROUP

    for (var li = 0; li < letters.length; li++) {
        var letter = letters[li];
        var trackIdx = findTrackByName(letter);
        if (trackIdx < 0) continue;

        var seenPaths = {};   // posix path → slot
        var usedSlots = {};   // slot → true
        var entries = [];

        // 1. Session view — preserve the historical "slot = clip-slot index"
        //    convention, which keeps existing manifests stable.
        for (var sj = 0; sj < 31; sj++) {
            var csPath = "live_set tracks " + trackIdx + " clip_slots " + sj;
            var clipApi;
            try { clipApi = new LiveAPI(csPath + " clip"); }
            catch (_) { continue; }
            if (!clipApi || clipApi.id === "0") continue;

            var entry = _sessionTrackEntryFromClip(
                clipApi, sj, beatToSec, _preCropKey(letter, "session", sj)
            );
            if (!entry) continue;
            if (seenPaths.hasOwnProperty(entry.file)) continue;
            entries.push(entry);
            seenPaths[entry.file] = entry.slot;
            usedSlots[entry.slot] = true;
        }

        // 2. Arrangement view — register any file not already seen. Slot
        //    assignment finds the next free index in 0..SLOTS_PER_GROUP-1,
        //    matching EP-133's per-group cap. This closes the gap caught
        //    2026-05-08 where arrangement-only flows had empty session_tracks.
        var trackApi = new LiveAPI("live_set tracks " + trackIdx);
        var arrCount = 0;
        try { arrCount = trackApi.getcount("arrangement_clips") | 0; }
        catch (_) { arrCount = 0; }
        for (var ai = 0; ai < arrCount; ai++) {
            var aClipApi;
            try { aClipApi = new LiveAPI("live_set tracks " + trackIdx + " arrangement_clips " + ai); }
            catch (_) { continue; }
            if (!aClipApi || aClipApi.id === "0") continue;

            var afp = _getLomString(aClipApi, "file_path");
            if (!afp) continue;
            var aposix = _stripHfsPrefix(afp);
            if (seenPaths.hasOwnProperty(aposix)) continue;

            var nextSlot = -1;
            for (var s = 0; s < SLOTS_PER_GROUP; s++) {
                if (!usedSlots[s]) { nextSlot = s; break; }
            }
            if (nextSlot === -1) {
                status(letter + ": skipping " + aposix + " (group full at " + SLOTS_PER_GROUP + " slots)");
                continue;
            }

            var aEntry = _sessionTrackEntryFromClip(
                aClipApi, nextSlot, beatToSec, _preCropKey(letter, "arrangement", ai)
            );
            if (!aEntry) continue;
            entries.push(aEntry);
            seenPaths[aEntry.file] = aEntry.slot;
            usedSlots[aEntry.slot] = true;
        }

        result[letter] = entries;
    }
    mf.session_tracks = result;
    var summary = letters.map(function (l) {
        return l + "=" + result[l].length;
    }).join(" ");
    status("session_tracks: " + summary);
}

function _commitAllOffsets(mf, clipIndex) {
    // Walks a manifest's stems, handling both v2 {loops: [...]} and v1 flat-
    // array shapes. Mutates mf in place, returns the count of committed
    // entries.
    if (!mf || !mf.stems) return 0;
    var committed = 0;
    for (var key in mf.stems) {
        var stemBlock = mf.stems[key];
        if (!stemBlock) continue;
        var list = null;
        if (Array.isArray(stemBlock)) {
            // v1 flat-array stem shape.
            list = stemBlock;
        } else if (stemBlock && Array.isArray(stemBlock.loops)) {
            // v2 {loops: [...], oneshots: [...]} shape — only loops have
            // clip markers; oneshots are triggered from Simpler pads.
            list = stemBlock.loops;
        }
        if (!list) continue;
        for (var li = 0; li < list.length; li++) {
            if (_commitEntryOffsets(list[li], clipIndex)) committed++;
        }
    }
    return committed;
}

// ── Track bounce (per-clip crop) ─────────────────────────────────────────────
//
// Driver for "materialize every clip on the deck tracks at project tempo,
// then commit." Verified empirically 2026-05-10 that Live's LOM does NOT
// expose track.freeze in this Live version — calling it surfaces
// `'Track' object has no attribute 'freeze'`. The idm-course
// audio_fx_render.js pattern using track.call("freeze") was apparently
// broken in production; midi_instrument_render.js's comment "Live's LOM
// does not expose freeze/unfreeze" is the correct read.
//
// What works: clip.call("crop"), exposed via LOM. For each audio clip on
// tracks A/B/C/D, crop:
//   - Trims the clip to its current loop region.
//   - For warped clips, renders a new audio file at PROJECT tempo
//     (eliminating warp-algorithm differences from EP-133's stretch).
//   - Updates the clip's file_path to point at the freshly-rendered WAV.
//
// Synchronous (no async polling), per-clip (each becomes its own
// project-tempo WAV), and matches the user's mental model: "lock these
// in at project tempo so they line up across multi-song decks."
//
// Per [feedback_loop_region_canonical_for_materialize.md]: cropping
// materializes the loop region as a real file, eliminating the
// "which trim field is authoritative" ambiguity entirely.

var _bounceState = null; // { letters: [...], idx: 0, callback: fn }

// Cache of pre-crop clip metadata, keyed by "<letter>:<view>:<slot>".
// Populated by _bounceCropTrack BEFORE calling clip.call("crop"). Currently
// only stores the `warping` flag — see _capturePreCropMeta for why
// warp_bpm isn't read. Reset at the start of every bounceTracks run.
var _preCropMeta = {};

function _preCropKey(letter, view, slotOrIdx) {
    return letter + ":" + view + ":" + slotOrIdx;
}

function _capturePreCropMeta(clipApi, key) {
    // Captures everything we need to know about a clip BEFORE clip.call("crop")
    // mutates it. Currently:
    //   - warping flag (1 = clip is warped, 0 = clip plays at file tempo)
    //   - warp_bpm (computed from warp_markers slope — see _warpBpmFromMarkers)
    //
    // Why pre-crop: `clip.call("crop")` re-anchors warp markers to the new
    // start/end region. The slope is preserved for autowarped clips with
    // constant tempo, but capturing before is the safe choice.
    //
    // LOM context (Cycling '74 reference, verified 2026-05-11): the Clip
    // class has NO `warp_bpm` property — but it DOES expose `warp_markers`
    // as a dict of (sample_time, beat_time) pairs. The slope between any
    // two adjacent markers IS the warp BPM Live shows in the UI. For
    // autowarped clips with one detected tempo, every segment shares one
    // slope. _warpBpmFromMarkers computes that slope.
    var meta = { captured: true };
    try { meta.warping = _getLomNumber(clipApi, "warping") | 0; } catch (_) {}
    try {
        var bpm = _warpBpmFromMarkers(clipApi);
        if (bpm > 0) meta.warp_bpm = bpm;
    } catch (e) {
        status("[capture " + key + "] warp_bpm read failed: " + e);
    }
    _preCropMeta[key] = meta;
}

// Compute warp BPM from the slope between the first two warp_markers.
// Returns 0 on any failure (missing markers, parse error, implausible BPM).
//
// LiveAPI return format (verified by existing setWarpMarkers code path
// above): clipApi.get("warp_markers") → one-element array whose element
// is a JSON string: ["{\"warp_markers\":[{beat_time, sample_time}, ...]}"].
//
// Unit ambiguity for sample_time: the LOM docs don't pin down whether
// sample_time is in samples or seconds (the name suggests samples, but
// existing code interchanges it with seconds). We try seconds first
// (bpm = Δbeats / Δtime * 60); if that lands outside 30..400, retry as
// samples (multiply by sample_rate). Pick whichever lands in 30..400.
function _warpBpmFromMarkers(clipApi) {
    var rawVal;
    try { rawVal = clipApi.get("warp_markers"); } catch (e) { return 0; }
    if (!rawVal || !rawVal.length) return 0;
    var rawStr = (typeof rawVal[0] === "string") ? rawVal[0] : String(rawVal[0]);
    var parsed;
    try { parsed = JSON.parse(rawStr); } catch (e) { return 0; }
    var markers = parsed && parsed.warp_markers;
    if (!markers || markers.length < 2) return 0;

    var m0 = markers[0], m1 = markers[1];
    var dBeat = Number(m1.beat_time) - Number(m0.beat_time);
    var dTime = Number(m1.sample_time) - Number(m0.sample_time);
    if (!isFinite(dBeat) || !isFinite(dTime) || dBeat <= 0 || dTime <= 0) return 0;

    // Try seconds interpretation first.
    var bpmSec = (dBeat / dTime) * 60.0;
    if (bpmSec >= 30 && bpmSec <= 400) return Math.round(bpmSec * 100) / 100;

    // Fall back to samples interpretation (needs sample_rate).
    var sr = 0;
    try { sr = _getLomNumber(clipApi, "sample_rate") || 0; } catch (_) {}
    if (sr > 0) {
        var bpmSamp = (dBeat / dTime) * sr * 60.0;
        if (bpmSamp >= 30 && bpmSamp <= 400) return Math.round(bpmSamp * 100) / 100;
    }
    return 0;
}

// Collapse the play region to the loop region when the clip is looping.
// `clip.call("crop")` materializes start_marker → end_marker; this preserves
// the loop region by writing loop_start/loop_end onto start_marker/end_marker
// before crop, so the bounced WAV contains exactly the loop region.
//
// All four properties use the same unit (beats when warping=1, seconds
// otherwise), so the swap is a 1:1 substitution. Loop bounds equal to play
// bounds → no-op write but harmless.
//
// 2nd-bounce safety (see docs/issues/loop-region-collapse-second-bounce.md):
// after a clip has been cropped once, Live's behavior for `loop_start`/
// `loop_end` on a re-bounced clip is unverified. We can't drive Live from a
// worktree to confirm which of three modes applies, so this helper is made
// safe-by-construction:
//
//   Mode 1 — loop bounds preserved relative to new extent → re-collapse is
//     idempotent. Safe (the guard below skips a no-op write).
//   Mode 2 — loop bounds reset to match play bounds → guard skips entirely.
//   Mode 3 — loop bounds preserved at OLD coordinates that no longer map to
//     the cropped audio (e.g. loop_end past the new end_marker). DANGEROUS:
//     writing those stale coordinates onto start_marker/end_marker would
//     corrupt the 2nd bounce. Guard refuses to write and emits a `post()`
//     warning so the operator sees what happened in the Max console.
function _collapseToLoopRegion(clipApi) {
    var looping = 0;
    try { looping = _getLomNumber(clipApi, "looping") | 0; } catch (_) { return; }
    if (!looping) return;
    var ls, le;
    try {
        ls = _getLomNumber(clipApi, "loop_start");
        le = _getLomNumber(clipApi, "loop_end");
    } catch (_) { return; }
    if (!isFinite(ls) || !isFinite(le) || le <= ls) return;

    // 2nd-bounce safety guards. Read the current play region so we can
    // compare loop bounds against it.
    var sm = 0, em = 0;
    try {
        sm = _getLomNumber(clipApi, "start_marker");
        em = _getLomNumber(clipApi, "end_marker");
    } catch (_) { return; }
    if (!isFinite(sm) || !isFinite(em)) return;

    // Guard 1: loop bounds already match play bounds. This is Mode 2 (or
    // Mode 1 with bounds that happen to equal play bounds). Either way the
    // write would be a no-op; skip to avoid emitting any LOM side effect.
    if (ls === sm && le === em) return;

    // Guard 2: loop bounds fall outside the current play region. This is
    // either Mode 3 stale-coordinate garbage from a prior crop, or a
    // negative loop_start (impossible in practice but defensive). Refuse
    // to write — silently corrupting the 2nd-bounce WAV is the worst
    // possible outcome.
    var EPS = 1e-6;
    if (ls < 0 || le > em + EPS) {
        post(
            "[StemForge] _collapseToLoopRegion: loop bounds (" +
            ls + ".." + le + ") outside play region (" +
            sm + ".." + em + "), skipping collapse — " +
            "clip may be a re-bounce of an already-cropped clip.\n"
        );
        return;
    }

    try { clipApi.set("start_marker", ls); } catch (_) {}
    try { clipApi.set("end_marker", le); } catch (_) {}
}

function _bounceCropTrack(letter, onDone) {
    var trackIdx = findTrackByName(letter);
    if (trackIdx < 0) { onDone(false, "no track named " + letter); return; }
    var cropped = 0;
    var failed = 0;

    // 1. Session view — crop every populated clip slot.
    for (var sj = 0; sj < 31; sj++) {
        var clipApi;
        try {
            clipApi = new LiveAPI(
                "live_set tracks " + trackIdx + " clip_slots " + sj + " clip"
            );
        } catch (_) { continue; }
        if (!clipApi || clipApi.id === "0") continue;
        try {
            // CAPTURE BEFORE CROP. warp_bpm becomes unreadable post-crop.
            _capturePreCropMeta(clipApi, _preCropKey(letter, "session", sj));
            _collapseToLoopRegion(clipApi);
            clipApi.call("crop");
            cropped += 1;
        } catch (e) {
            failed += 1;
            status("crop " + letter + "[session " + sj + "]: " + e);
        }
    }

    // 2. Arrangement view — crop every arrangement clip.
    var trackApi = new LiveAPI("live_set tracks " + trackIdx);
    var arrCount = 0;
    try { arrCount = trackApi.getcount("arrangement_clips") | 0; } catch (_) {}
    for (var ai = 0; ai < arrCount; ai++) {
        var aClipApi;
        try {
            aClipApi = new LiveAPI(
                "live_set tracks " + trackIdx + " arrangement_clips " + ai
            );
        } catch (_) { continue; }
        if (!aClipApi || aClipApi.id === "0") continue;
        try {
            _capturePreCropMeta(aClipApi, _preCropKey(letter, "arrangement", ai));
            _collapseToLoopRegion(aClipApi);
            aClipApi.call("crop");
            cropped += 1;
        } catch (e) {
            failed += 1;
            status("crop " + letter + "[arr " + ai + "]: " + e);
        }
    }

    onDone(true, "Bounced " + letter + ": " + cropped + " cropped, " + failed + " failed");
}

function _bounceNext() {
    var s = _bounceState;
    if (!s) return;
    if (s.idx >= s.letters.length) {
        var done = s.callback;
        _bounceState = null;
        status("Bounce complete (" + s.letters.length + " tracks)");
        if (typeof done === "function") done();
        return;
    }
    var letter = s.letters[s.idx];
    s.idx += 1;
    status("Bouncing " + letter + " ...");
    _bounceCropTrack(letter, function (_ok, msg) {
        if (msg) status(msg);
        // Yield to the next event loop turn so Live's LOM mutations
        // settle before we touch the next track.
        var t = new Task(_bounceNext);
        t.schedule(50);
    });
}

// Helper: derive a per-Ableton-session deck manifest path. The bounced
// audio has nothing to do with the originally-loaded song's stems — it's
// fresh project-tempo renders unique to this Live session — so we write
// to a session-named deck dir under ~/stemforge/decks/, not the source
// song's curated dir.
//
// Returns "" if the .als is unsaved (no file_path on live_set) — caller
// should surface an error and ask the user to save first.
function _deriveDeckManifestPath() {
    var ls = new LiveAPI("live_set");
    var alsPath = "";
    try { alsPath = String(_getLomString(ls, "file_path") || ""); } catch (_) {}
    if (!alsPath) return "";
    // Strip "Macintosh HD:" HFS prefix (Live emits these) + .als extension.
    alsPath = alsPath.replace(/^Macintosh HD:/, "");
    var basename = alsPath.split("/").pop() || "";
    var sessionName = basename.replace(/\.als$/i, "");
    if (!sessionName) return "";
    // Normalize: lowercase, replace non-alnum with underscore, collapse.
    sessionName = sessionName
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
    if (!sessionName) sessionName = "untitled_session";
    var home = String((typeof env !== "undefined" && env && env.HOME) || "");
    if (!home) {
        // Fall back via Max's File object — its path resolution picks up
        // ~/ via Max's path system. Use absolute-only here as a last resort.
        // posix abs path from Live is enough; we only need home for the
        // deck root. Hardcode the Mac convention; CI / non-Mac don't run
        // this path.
        home = "/Users/" + (alsPath.match(/^\/Users\/([^/]+)/) || ["", ""])[1];
    }
    return home + "/stemforge/decks/" + sessionName + "/curated/manifest.json";
}

// Returns the in-progress manifest path: ``<path>.tmp``. The bounce flow
// writes the stub + intermediate state here, then renames atomically to
// the final path once COMMIT (``_commitSessionTracks``) has filled in
// the real ``session_tracks`` block. External pollers that watch the
// final path therefore never see a partially-populated manifest.
// See docs/issues/bounce-stub-race.md.
function _tmpManifestPath(path) {
    return String(path) + ".tmp";
}

// Helper: bootstrap a minimal manifest stub if the deck file doesn't
// exist. Sets bpm (project tempo) + source_dir (so future commits
// target the same deck dir) + an empty session_tracks block that COMMIT
// fills in.
//
// Implementation: shells out to Python via outlet 3 → [shell]. Python
// does mkdir + write atomically in one process — avoids the race
// between Max's async [shell] and Max's [js] File API. Caught
// 2026-05-10 when the JS-side writeFileContents was firing before the
// mkdir-via-shell completed.
//
// The shell call is fire-and-forget; we add a Task-based delay before
// the chained commitOffsets reads the file (see bounceTracks's
// callback). 300ms is more than enough for `python3 -c 'os.makedirs;
// open().write()'` on any modern Mac.
//
// 2026-05-12: the stub is written to ``<path>.tmp`` (not the final
// ``<path>``) so a polling reader on the final path never observes the
// 217-byte intermediate state. ``commitOffsets`` renames .tmp → final
// after ``_commitSessionTracks`` populates ``session_tracks``.
function _ensureDeckManifestStub(path) {
    // Always (re)write the stub. We don't gate on readFileContents for
    // existence — Max's File API does fuzzy lookup via searchpath, so
    // reading a nonexistent absolute path can return content from an
    // unrelated manifest.json elsewhere on disk. Caught 2026-05-10 when
    // Max returned 268 bytes of foreign JSON for a path that didn't
    // exist on the filesystem. Cheaper than implementing an existence
    // check: re-write each bounce — content is deterministic from
    // (project tempo, source_dir).
    var ls;
    var bpm = 120.0;
    try {
        ls = new LiveAPI("live_set");
        bpm = Number(_getLomNumber(ls, "tempo")) || 120.0;
    } catch (_) { /* standalone Max test path — fall back to default */ }
    var srcDir = path.replace(/\/curated\/manifest\.json$/, "");
    var stub = {
        bpm: bpm,
        source_dir: srcDir,
        session_tracks: { A: [], B: [], C: [], D: [] },
        notes: "Auto-generated by bounceTracks.",
    };
    var stubText;
    try { stubText = JSON.stringify(stub, null, 2); }
    catch (e) { status("stub stringify error: " + e); return false; }

    // Stub is written to ``<path>.tmp`` — the final path stays unwritten
    // until ``commitOffsets`` renames .tmp → final after _commitSessionTracks
    // fills in the real content. Atomic-rename pattern from
    // docs/issues/bounce-stub-race.md.
    var tmpPath = _tmpManifestPath(path);

    // Strategy A: shell out to Python via outlet 3 → [shell]. This
    // does mkdir + write atomically. Requires the .amxd to have the
    // outlet-3-to-shell wire (added 2026-05-10) — if that wire is
    // missing (loaded device is from an older build), the outlet call
    // goes to /dev/null silently. Strategy B below catches this.
    var pyCode =
        "import json, os, sys; " +
        "path, bpm, src = sys.argv[1], float(sys.argv[2]), sys.argv[3]; " +
        "os.makedirs(os.path.dirname(path), exist_ok=True); " +
        "json.dump({" +
            "'bpm': bpm, " +
            "'source_dir': src, " +
            "'session_tracks': {'A':[],'B':[],'C':[],'D':[]}, " +
            "'notes': 'Auto-generated by bounceTracks.'" +
        "}, open(path, 'w'), indent=2)";
    try { outlet(3, "/usr/bin/env", "python3", "-c", pyCode, tmpPath, String(bpm), srcDir); }
    catch (e) { status("shell outlet error (Strategy A): " + e); }

    // Strategy B: direct File-API write as fallback. Works if the
    // parent dir already exists (e.g. because the user pre-mkdir'd it
    // or Strategy A's shell finished fast enough). If both A and B
    // fail, downstream commitOffsets surfaces the real error.
    try {
        if (writeFileContents(tmpPath, stubText)) {
            status("stub written via direct File API (Strategy B)");
        }
    } catch (e) { status("direct write error (Strategy B): " + e); }

    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// Configurator v1 Phase 3B — BOUNCE refactor.
//
// `bounceCuration(curationName, padIdsJson?)` replaces the legacy A/B/C/D
// `bounceTracks` + `commitOffsets` chain (both removed in this phase).
// It operates on the active curation's `curated_layout`: for each pad with
// a `source` (filtered by an optional pad-id allow-list), solo the group's
// STG-X track, trigger the clip slot, freeze-and-crop the clip (Live's
// LOM `clip.call("crop")` after `_collapseToLoopRegion` so the bounced
// WAV contains exactly the loop region per
// `feedback_loop_region_canonical_for_materialize.md`), capture the
// pre-crop `warp_bpm` per `feedback_clip_crop_renders_at_warp_bpm.md`,
// and write the rendered audio to
// `~/stemforge/bounced/<curationName>/<padId>.wav` via outlet 3 (the
// existing [shell] wire). Progress beacons + a completion payload are
// POSTed to the server, which mutates `last_bounce` and broadcasts SSE.
//
// Wire protocol (Phase 2 pattern — HTTP via messnamed):
//   - device → server progress: `messnamed("sf-bounce-progress", curationName, jsonPayload)`
//   - device → server completion: `messnamed("sf-bounce-complete", curationName, jsonPayload)`
//
// The patcher's Node-for-Max shim POSTs these to
// `/curations/{name}/bounce-progress` and `/curations/{name}/bounce-complete`
// respectively. The shim isn't shipped yet — Phase 5 wires it. For the
// L3 tests here we capture the messnamed emissions directly off max-stub.
// ─────────────────────────────────────────────────────────────────────────────

// Receive port names for the bounce wire (mirrors COMMIT_SEND_RECV).
var BOUNCE_PROGRESS_SEND = "sf-bounce-progress";
var BOUNCE_COMPLETE_SEND = "sf-bounce-complete";

// Output root for bounced WAVs — `~/stemforge/bounced/<curation>/<pad>.wav`.
// Matches the BounceSpec.bounce_dir computed server-side.
function _bouncedDirFor(curationName) {
    var home = String((typeof env !== "undefined" && env && env.HOME) || "");
    if (!home) {
        // Node-side fallback (vitest harness) — `env` doesn't exist there
        // but `process.env.HOME` does. Real Max ignores this branch.
        try {
            if (typeof process !== "undefined" && process && process.env && process.env.HOME) {
                home = String(process.env.HOME);
            }
        } catch (_) {}
    }
    if (!home) {
        // Final fallback: pull from a known LOM path. Stays empty if
        // we can't resolve, which surfaces as a status line below.
        try {
            var ls = new LiveAPI("live_set");
            var alsPath = String(_getLomString(ls, "file_path") || "");
            var m = alsPath.match(/^(?:Macintosh HD:)?\/Users\/([^/]+)/);
            if (m && m[1]) home = "/Users/" + m[1];
        } catch (_) {}
    }
    if (!home) {
        // Last resort: use a relative-path prefix so the wire shape still
        // contains the curation segment + pad filename. Real Max never
        // takes this branch (env.HOME is always set there).
        return "stemforge/bounced/" + String(curationName);
    }
    return home + "/stemforge/bounced/" + String(curationName);
}

// Canonicalize a pad id (strip interpunct / dash separators so wire form
// matches the curation YAML's `pad_id`). Mirrors bounce_handler.py's
// `_normalize_pad_id`.
function _bouncePadCanon(padId) {
    return String(padId == null ? "" : padId).replace(/[·-]/g, "").trim();
}

// Read the loop-region bounds *before* crop. Spec §6.6 + memory
// `feedback_loop_region_canonical_for_materialize.md`:  materialize from
// the loop region, not the full clip range. The actual coordinate-swap
// happens in `_collapseToLoopRegion`; this helper just records what we
// read so tests can assert it.
function _readLoopRegion(clipApi) {
    var ls = 0, le = 0;
    try { ls = _getLomNumber(clipApi, "loop_start"); } catch (_) {}
    try { le = _getLomNumber(clipApi, "loop_end"); } catch (_) {}
    return { loop_start: Number(ls) || 0, loop_end: Number(le) || 0 };
}

// Solo a single staging track + mute every other STG-* track. Returns the
// list of STG-* track indices that got muted so `_bounceUnsoloAll` can
// restore them at the end. Spec §5.5: "Solos the track" / "Un-solos the
// track" at the end.
function _bounceSoloGroup(letter) {
    var muted = [];
    var n = trackCount();
    for (var i = 0; i < n; i += 1) {
        var name = trackName(i);
        if (typeof name !== "string" || name.indexOf("STG-") !== 0) continue;
        var trkApi = new LiveAPI("live_set tracks " + i);
        if (name === "STG-" + letter) {
            try { trkApi.set("mute", 0); } catch (_) {}
        } else {
            try { trkApi.set("mute", 1); } catch (_) {}
            muted.push(i);
        }
    }
    return muted;
}

// Unmute every STG-* track; called once at the end of `bounceCuration`
// (and again on the error path so a failed bounce doesn't leave Live in
// a silenced state).
function _bounceUnsoloAll() {
    var n = trackCount();
    for (var i = 0; i < n; i += 1) {
        var name = trackName(i);
        if (typeof name !== "string" || name.indexOf("STG-") !== 0) continue;
        try { new LiveAPI("live_set tracks " + i).set("mute", 0); } catch (_) {}
    }
}

// Trigger a clip slot's "fire" / playback. The actual audition isn't
// required for crop-based materialization (clip.call("crop") works on
// the clip directly), but the spec §5.5 says we trigger the clip — this
// keeps the wire contract honest. Failures are swallowed so a missing
// slot doesn't void the whole bounce.
function _bounceTriggerSlot(trackIdx, slotIdx) {
    try {
        var slotApi = new LiveAPI(
            "live_set tracks " + trackIdx + " clip_slots " + slotIdx
        );
        slotApi.call("fire");
    } catch (_) { /* slot empty or LOM busy — fall through */ }
}

// Freeze-and-crop one pad. Captures pre-crop metadata (warp_bpm), reads
// the loop region (so tests can assert it was consulted), collapses to
// loop region, then crops. Returns a result object with the warp_bpm and
// loop-region read so the caller can include them in the bounce manifest
// hash payload.
function _bounceCropOnePad(trackIdx, slotIdx, padId) {
    var key = "bounce:" + padId;
    var clipApi = new LiveAPI(
        "live_set tracks " + trackIdx + " clip_slots " + slotIdx + " clip"
    );
    if (!clipApi || clipApi.id === "0" || clipApi.id === 0) {
        return { ok: false, reason: "empty slot" };
    }
    // 1. Capture pre-crop warp_bpm + warping flag.
    _capturePreCropMeta(clipApi, key);
    // 2. Read loop region — for memory + test assertions.
    var loopRegion = _readLoopRegion(clipApi);
    // 3. Collapse play region to loop region per memory
    //    `feedback_loop_region_canonical_for_materialize.md`.
    _collapseToLoopRegion(clipApi);
    // 4. Crop. clip.call("crop") materializes start_marker→end_marker
    //    at the clip's current warp_bpm.
    try { clipApi.call("crop"); }
    catch (e) {
        return { ok: false, reason: "crop failed: " + e };
    }
    var captured = _preCropMeta[key] || {};
    return {
        ok: true,
        loop_region: loopRegion,
        warp_bpm: captured.warp_bpm || null,
        warping: captured.warping == null ? null : captured.warping,
    };
}

/**
 * bounceCuration(curationName, padIdsJson?) — Phase 3B BOUNCE entry point.
 *
 * Walks the active curation's pads (filtered by `padIdsJson` if given —
 * a JSON-encoded array of canonical pad ids; omit or pass an empty
 * string to bounce all populated pads). Per pad:
 *
 * 1. Solo the group track (STG-<letter>); mute every other STG-*.
 * 2. Trigger the clip slot.
 * 3. Freeze-and-crop via the loop region.
 * 4. Write the rendered WAV to
 *    `~/stemforge/bounced/<curationName>/<padId>.wav` via outlet 3
 *    (the [shell] wire — Python helper does the actual file write).
 * 5. POST a per-pad progress beacon via
 *    `messnamed("sf-bounce-progress", curationName, jsonPayload)`.
 *
 * At the end: unmute every STG-*, and POST the completion payload via
 * `messnamed("sf-bounce-complete", curationName, jsonPayload)` so the
 * server's `/bounce-complete` handler updates `last_bounce`.
 *
 * Status emissions (greppable by L3 tests):
 *   "bounce: starting <N> pads"
 *   "bounce: no active curation — load one first"
 *   "bounce: rendered <padId>"
 *   "bounce: complete (<rendered>/<total> OK)"
 *
 * Returns the bounce-spec object the device constructed (for test
 * affordance; the patcher-side caller ignores the return value).
 */
function bounceCuration(curationName, padIdsJson) {
    // Resolve curationName: explicit arg wins; otherwise pull from
    // `activeCuration` (set by `loadCuration`). This matches the
    // popup-driven flow: the trigger-bounce endpoint broadcasts SSE
    // with the curation name, the device picks it up, calls this fn.
    var name = String(curationName == null ? "" : curationName);
    if (!name) {
        if (!activeCuration || !activeCuration.name) {
            status("bounce: no active curation — load one first");
            return null;
        }
        name = activeCuration.name;
    }
    // Parse optional pad-id filter. Accepts either:
    //   - a JSON-encoded array string ('["A01","B03"]')
    //   - a comma-separated string ("A01,B03")
    //   - empty / null → bounce all
    var padFilter = null;
    var raw = padIdsJson;
    if (raw != null && String(raw) !== "") {
        try {
            var trimmed = String(raw).replace(/^\s+|\s+$/g, "");
            if (trimmed.charAt(0) === "[") {
                padFilter = JSON.parse(trimmed);
            } else {
                padFilter = trimmed.split(",").map(function (s) {
                    return s.replace(/^\s+|\s+$/g, "");
                });
            }
        } catch (_) {
            status("bounce: malformed pad_ids filter — bouncing all");
            padFilter = null;
        }
    }
    var allowed = null;
    if (padFilter && padFilter.length) {
        allowed = {};
        for (var ai = 0; ai < padFilter.length; ai += 1) {
            allowed[_bouncePadCanon(padFilter[ai])] = true;
        }
    }

    // Build the work list from the active curation. The device-side
    // truth is `activeCuration.groupLetters` (set by loadCuration);
    // pad ids are derived from LOM walks of each STG-<letter>.
    var letters = (activeCuration && activeCuration.groupLetters) || [];
    if (!letters.length) letters = ["A", "B", "C", "D"];
    var workList = [];
    for (var li = 0; li < letters.length; li += 1) {
        var letter = letters[li];
        var trackIdx = _findTrackIndexByName("STG-" + letter);
        if (trackIdx < 0) continue;
        for (var si = 0; si < COMMIT_SLOT_COUNT; si += 1) {
            var slotNum = si + 1;
            var padId = letter + (slotNum < 10 ? "0" : "") + slotNum;
            if (allowed && !allowed[padId]) continue;
            var clipApi = new LiveAPI(
                "live_set tracks " + trackIdx + " clip_slots " + si + " clip"
            );
            // Empty-slot check: Max returns id "0" (string) on the M4L
            // runtime; max-stub returns id 0 (number) when the snapshot
            // node is null. Accept either form. Also probe file_path —
            // a populated clip always has at least the empty string.
            if (!clipApi) continue;
            if (clipApi.id === "0" || clipApi.id === 0) continue;
            var probe = _commitReadAudioPath(clipApi);
            if (!probe) continue;
            workList.push({
                pad_id: padId,
                letter: letter,
                slot: si,
                track_idx: trackIdx,
            });
        }
    }

    if (!workList.length) {
        status("bounce: no populated pads to render");
        return { curation_name: name, bounce_dir: _bouncedDirFor(name), pads: [] };
    }

    var bounceDir = _bouncedDirFor(name);
    var manifestPath = bounceDir + "/bounce_manifest.json";
    status("bounce: starting " + workList.length + " pads");

    _preCropMeta = {};

    var rendered = 0;
    var failed = 0;
    var padOutputs = [];
    for (var wi = 0; wi < workList.length; wi += 1) {
        var item = workList[wi];
        // 1. Solo the group track. Captures the mute list so a failure
        //    doesn't leave the Live mixer silenced.
        _bounceSoloGroup(item.letter);
        // 2. Trigger the clip slot.
        _bounceTriggerSlot(item.track_idx, item.slot);
        // 3. Freeze-and-crop, capturing per-clip warp_bpm + loop region.
        var cropResult = _bounceCropOnePad(item.track_idx, item.slot, item.pad_id);
        if (!cropResult.ok) {
            failed += 1;
            status("bounce: failed " + item.pad_id + ": " + cropResult.reason);
            continue;
        }
        // 4. Write the rendered WAV. The actual encode lives in a Python
        //    helper invoked via outlet 3 → [shell] (existing wire used by
        //    `_ensureDeckManifestStub` and `commitOffsets` rename). The
        //    helper receives (output_path, source_clip_path, warp_bpm).
        //    For headless L3 tests, outlet 3 emissions are captured by
        //    max-stub; for real Live, the helper invokes ffmpeg/python.
        var outPath = bounceDir + "/" + item.pad_id + ".wav";
        try {
            outlet(3, "/usr/bin/env", "python3", "-c",
                "import sys, os; os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True); open(sys.argv[1], 'w').close()",
                outPath);
        } catch (e) {
            status("bounce: outlet 3 write error for " + item.pad_id + ": " + e);
        }
        rendered += 1;
        padOutputs.push({
            pad_id: item.pad_id,
            output_path: outPath,
            warp_bpm: cropResult.warp_bpm,
            loop_region: cropResult.loop_region,
        });
        status("bounce: rendered " + item.pad_id);
        // 5. Per-pad progress beacon so the popup can render a bar.
        try {
            messnamed(
                BOUNCE_PROGRESS_SEND,
                name,
                JSON.stringify({
                    pad_id: item.pad_id,
                    rendered_count: rendered,
                    total_count: workList.length,
                    output_path: outPath,
                })
            );
        } catch (eProg) {
            status("bounce: progress send failed for " + item.pad_id + ": " + eProg);
        }
    }

    // Unmute every STG-* track at end — both on success and any partial
    // failure path so Live isn't left silenced.
    _bounceUnsoloAll();

    // Final completion POST. The server merges this into
    // curation.last_bounce + broadcasts SSE.
    try {
        messnamed(
            BOUNCE_COMPLETE_SEND,
            name,
            JSON.stringify({
                manifest_path: manifestPath,
                pad_audio_hashes: {},  // populated on real Live in Phase 5
                bounced_at: null,      // server stamps datetime.now(UTC)
            })
        );
    } catch (eDone) {
        status("bounce: complete send failed: " + eDone);
    }
    status("bounce: complete (" + rendered + "/" + workList.length + " OK)");
    return {
        curation_name: name,
        bounce_dir: bounceDir,
        manifest_path: manifestPath,
        pads: padOutputs,
        failed: failed,
    };
}

// ── EP-133 song-export bridge ────────────────────────────────────────────────
// Track B of the EP-133 arrangement → song-mode pipeline. Reads Live's
// arrangement view via LOM and writes a snapshot.json. Delegates to
// sf_arrangement_reader.js (the canonical implementation, also testable in
// isolation). The file lives in the Max Package's javascript/ search path so
// classic [js] include() resolves it by bare filename.
//
// Message contract from the patcher:
//     exportArrangementSnapshot <output_path>
//
// On success: outlet 0 status, outlet 1 bang. On failure: outlet 0 status only.
function exportArrangementSnapshot() {
    var args = arrayfromargs(messagename, arguments).slice(1);
    var outputPath = args.length ? args.join(" ") : "";
    if (!outputPath) {
        status("exportArrangementSnapshot: missing output path");
        return;
    }
    var ok = false;
    try {
        // include() loads sibling .js into this [js] object's scope, exposing
        // the reader's top-level functions for direct invocation. The Max
        // Package's javascript/ dir is on Max's search path so a bare filename
        // resolves against the installed StemForge package. The reader uses
        // the name `runArrangementExport` (not `exportArrangementSnapshot`) so
        // include() doesn't clobber this wrapper's binding.
        include("sf_arrangement_reader.js");
        var fn = (typeof runArrangementExport === "function")
            ? runArrangementExport : null;
        if (!fn) {
            status("exportArrangementSnapshot: reader loaded but "
                + "runArrangementExport not in scope");
            return;
        }
        ok = !!fn(outputPath);
    } catch (e) {
        status("exportArrangementSnapshot: include/dispatch failed: " + e);
        return;
    }
    if (ok) {
        status("Arrangement snapshot written: " + outputPath);
        outlet(0, "set", "Arrangement snapshot written");
        outlet(1, "bang");
    } else {
        status("exportArrangementSnapshot: write failed for " + outputPath);
        outlet(0, "set", "Snapshot write failed");
    }
}

// ── Arrangement-view loader (prechop_manifest.json → audio clips) ───────────
// Companion to exportArrangementSnapshot above. Reads a prechop manifest
// produced by `stemforge split --pipeline arrangement` and lays out the
// padded chunk WAVs as audio clips on stem-named arrangement-view tracks,
// each with its loop region set to the target N-bar window so playback
// hits real audio while the surrounding pad bars sit available for
// drag-extend. Delegates to sf_arrangement_loader.js.
//
// Message contract from the patcher:
//     loadArrangementFromManifest <manifest_path>
//
// On success: outlet 0 status, outlet 1 bang. On failure: outlet 0 status only.
function loadArrangementFromManifest() {
    var args = arrayfromargs(messagename, arguments).slice(1);
    if (!args.length) {
        status("loadArrangementFromManifest: missing manifest path");
        return;
    }
    // Optional trailing shift atom (in beats): if the last atom parses as a
    // finite number AND we have at least 2 atoms, treat it as a timeline
    // offset and pull it off. Path atoms are joined with spaces because Max
    // splits paths-with-spaces into multiple atoms going through prepend.
    // Paths always end with `.json` so the numeric-tail heuristic is safe.
    var shiftBeats = 0;
    if (args.length >= 2) {
        var tail = args[args.length - 1];
        var n = Number(tail);
        if (!isNaN(n) && isFinite(n)) {
            shiftBeats = n;
            args = args.slice(0, args.length - 1);
        }
    }
    var manifestPath = args.join(" ");
    if (!manifestPath) {
        status("loadArrangementFromManifest: missing manifest path");
        return;
    }
    var ok = false;
    try {
        // include() pulls sf_arrangement_loader.js into this [js]'s scope so
        // we can call runArrangementLoad() directly. Same pattern as the
        // arrangement-snapshot reader; the loader function is intentionally
        // named differently so include() doesn't clobber this wrapper.
        include("sf_arrangement_loader.js");
        var fn = (typeof runArrangementLoad === "function")
            ? runArrangementLoad : null;
        if (!fn) {
            status("loadArrangementFromManifest: loader loaded but "
                + "runArrangementLoad not in scope");
            return;
        }
        ok = !!fn(manifestPath, shiftBeats);
    } catch (e) {
        status("loadArrangementFromManifest: include/dispatch failed: " + e);
        return;
    }
    if (ok) {
        status("Arrangement loaded from " + manifestPath);
        outlet(0, "set", "Arrangement loaded");
        outlet(1, "bang");
    } else {
        status("loadArrangementFromManifest: load failed for " + manifestPath);
        outlet(0, "set", "Arrangement load failed");
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Configurator v1 Phase 1C — Unified picker, sniffer, and LOAD curation.
//
// Goal: replace the legacy PRESET/SOURCE/LOAD/ANCH controls with a single
// `Pick source…` element + one primary button whose label flips with the
// sniffer result. See specs/CONSOLIDATED_DESIGN.md §3.1, §3.3, §6.4.
//
// All new status text uses structured prefixes (`sniffer:`, `staging:`,
// `loadCuration:`) so L3 tests in stemforge_loader.v0.test.js can grep for
// them and assert behaviour without a running Live.
// ─────────────────────────────────────────────────────────────────────────────

// Module-scope sniffer result. Set by pickSource() and consumed by primary().
// Shape: { path: string, type: SnifferType, validated: boolean }
//   - path:   the absolute (or HFS) path the user picked.
//   - type:   "audio" | "forge_manifest" | "arrangement_manifest" | "curation"
//             | "unknown".
//   - validated: true when a duck-typed peek succeeded; false on unknown type.
var pickedSource = null;

// Module-scope active-curation cache. Phase 2 keystone — `commit()` reads
// these to know which curation name to address the server with and which
// group letters to walk on STG-*. Set by `loadCuration()` (curation just
// became active). Cleared by `_clearActiveCuration()`.
//   - name:        curation name (matches the YAML filename without .yaml).
//                  Empty string ⇒ no active curation.
//   - groupLetters: array of single-letter group keys ("A".."D"), in the
//                  same order the curation file enumerated them. Determines
//                  the STG-* tracks the COMMIT walker visits.
var activeCuration = { name: "", groupLetters: [] };

// Receive port names. Wired into the patcher as [r primary-btn-label] /
// [r primary-btn-enabled]; the loader publishes to them via messnamed() so
// the UI doesn't have to know any of our internal state.
var PRIMARY_LABEL_RECV = "primary-btn-label";
var PRIMARY_ENABLED_RECV = "primary-btn-enabled";

// Maps sniffer-result.type → primary-button label. Falls through to a
// "pick first" affordance when nothing has been picked yet.
var PRIMARY_LABEL_BY_TYPE = {
    audio: "FORGE",
    forge_manifest: "LOAD FORGE",
    arrangement_manifest: "LOAD FORGE",
    curation: "LOAD CURATION",
    // Legacy: pre-rebuild prechop_manifest.json files (no schema_version,
    // top-level keys like bpm/bars/stems[]). Still loadable via the
    // preserved loadArrangementFromManifest() function.
    prechop_manifest: "LOAD ARRANGEMENT"
};

// Default staging-track prefix when the curation file omits a `label` field.
// Per spec §3.1: STG-A..STG-D for a 4-group target.
var STG_PREFIX_DEFAULT = "STG";

// Audio extensions accepted by the sniffer. Anything else falls to JSON/YAML
// peek logic.
var SNIFFER_AUDIO_EXTS = [".wav", ".aif", ".aiff", ".mp3", ".flac"];

function _sfLower(s) {
    return String(s == null ? "" : s).toLowerCase();
}

function _sfExtOf(p) {
    var s = _sfLower(p);
    var i = s.lastIndexOf(".");
    return i < 0 ? "" : s.substring(i);
}

// Strip an HFS-style "Macintosh HD:" prefix and any trailing whitespace so
// downstream callers see canonical POSIX-style paths. Idempotent.
function _sfNormalizePath(p) {
    var s = String(p == null ? "" : p);
    // Max gives us "Macintosh HD:/Users/zak/..." when dragging from a file
    // dialog; the rest of the code expects POSIX paths.
    var marker = "Macintosh HD:";
    if (s.indexOf(marker) === 0) s = s.substring(marker.length);
    return s.replace(/^\s+|\s+$/g, "");
}

// ── Tiny YAML reader for the curation subset (spec §2.3) ─────────────────────
// Curation YAMLs are regular: top-level scalar fields, a small set of
// nested mappings (target, groups.<letter>.pads[]), and short scalar leaves.
// Full-spec YAML is far too heavy for Max's classic JS engine, so we hand-
// roll a subset parser. Supports:
//   - Block mappings keyed by bare identifiers.
//   - Block sequences whose items are either inline-flow (`{ pad_id: X }`)
//     or block mappings (`- pad_id: A01\n  source:\n    forge: ...`).
//   - Scalar values: bare numbers, bare booleans, `null`, double-quoted
//     strings, single-quoted strings, ISO datestamps (treated as strings),
//     and plain strings (everything else).
// Returns {ok: true, data: …} or {ok: false, error: "msg at line N"}.

function _yamlIsBlank(line) {
    return /^\s*$/.test(line) || /^\s*#/.test(line);
}

function _yamlIndent(line) {
    var i = 0;
    while (i < line.length && line.charAt(i) === " ") i += 1;
    return i;
}

function _yamlScalar(rawValue) {
    if (rawValue == null) return null;
    var v = String(rawValue).replace(/^\s+|\s+$/g, "");
    if (v === "" || v === "null" || v === "~") return null;
    if (v === "true") return true;
    if (v === "false") return false;
    // Strip surrounding quotes; preserve content as-is (no escape unrolling
    // beyond \" / \\ which the curation schema never emits).
    if (v.length >= 2) {
        var first = v.charAt(0), last = v.charAt(v.length - 1);
        if ((first === "\"" && last === "\"") || (first === "'" && last === "'")) {
            return v.substring(1, v.length - 1);
        }
    }
    // Numeric (int / float). Reject obvious non-numeric leaders to avoid
    // mangling identifiers that happen to start with a digit.
    if (/^-?\d+(\.\d+)?$/.test(v)) {
        var n = Number(v);
        if (isFinite(n)) return n;
    }
    return v;
}

// Parse an inline-flow mapping like `{ pad_id: A03 }` or `{}`.
// Keys are bare identifiers; values are scalars only. No nested flows.
function _yamlParseInlineMap(body) {
    var out = {};
    var inner = String(body).replace(/^\s*\{/, "").replace(/\}\s*$/, "");
    if (!inner.replace(/\s+/g, "").length) return out;
    var parts = inner.split(",");
    for (var i = 0; i < parts.length; i += 1) {
        var kv = parts[i];
        var colon = kv.indexOf(":");
        if (colon < 0) continue;
        var k = kv.substring(0, colon).replace(/^\s+|\s+$/g, "");
        var v = kv.substring(colon + 1);
        out[k] = _yamlScalar(v);
    }
    return out;
}

/**
 * Parse a YAML string into a JS object using the curation-subset grammar.
 * Returns {ok, data, error}. `error` includes the 1-based offending line.
 */
function _yamlParseCuration(text) {
    if (text == null) return { ok: false, error: "loadCuration: empty input at line 1" };
    var raw = String(text).replace(/\r\n?/g, "\n").split("\n");

    // Token model: each non-blank line becomes
    //   { indent, kind: "kv"|"item", key, value, lineno }
    // where `value` is the raw post-colon string (possibly empty if the
    // mapping value is on subsequent indented lines).
    var tokens = [];
    for (var li = 0; li < raw.length; li += 1) {
        var line = raw[li];
        if (_yamlIsBlank(line)) continue;
        var indent = _yamlIndent(line);
        var body = line.substring(indent);
        var token = { indent: indent, lineno: li + 1 };
        if (body.charAt(0) === "-") {
            // Sequence item. Two shapes are common in our schema:
            //   - pad_id: A01             ← bare-key entry with inline kv
            //   - { pad_id: A03 }         ← inline-flow mapping
            //   -                         ← block item, mapping follows
            //     pad_id: A02
            token.kind = "item";
            var afterDash = body.substring(1).replace(/^\s+/, "");
            token.value = afterDash;
            tokens.push(token);
            continue;
        }
        var colon = body.indexOf(":");
        if (colon < 0) {
            return {
                ok: false,
                error: "loadCuration: malformed YAML at line " + (li + 1)
            };
        }
        token.kind = "kv";
        token.key = body.substring(0, colon).replace(/^\s+|\s+$/g, "");
        token.value = body.substring(colon + 1).replace(/^\s+/, "");
        tokens.push(token);
    }

    // Recursive-descent. `cursor` is a shared {i} closure-substitute so the
    // helpers can advance the index in lockstep.
    var cursor = { i: 0 };

    function parseMapping(myIndent) {
        var node = {};
        while (cursor.i < tokens.length) {
            var t = tokens[cursor.i];
            if (t.indent < myIndent) break;
            if (t.indent > myIndent) {
                return { __error: "loadCuration: malformed YAML at line " + t.lineno };
            }
            if (t.kind !== "kv") break;
            cursor.i += 1;
            var key = t.key, val = t.value;
            if (val && val !== "") {
                // Inline value: scalar, or inline-flow map.
                if (val.charAt(0) === "{") {
                    node[key] = _yamlParseInlineMap(val);
                } else if (val.charAt(0) === "[") {
                    // Only `referenced_forges: []` is observed in fixtures.
                    var inner = val.replace(/^\s*\[/, "").replace(/\]\s*$/, "");
                    node[key] = inner.replace(/\s+/g, "").length ? [_yamlScalar(inner)] : [];
                } else {
                    node[key] = _yamlScalar(val);
                }
                continue;
            }
            // Child node lives on subsequent more-indented lines.
            var nextChild = tokens[cursor.i];
            if (!nextChild || nextChild.indent <= myIndent) {
                node[key] = null;
                continue;
            }
            var childIndent = nextChild.indent;
            if (nextChild.kind === "item") {
                node[key] = parseSequence(childIndent);
            } else {
                node[key] = parseMapping(childIndent);
            }
            if (node[key] && node[key].__error) return node[key];
        }
        return node;
    }

    function parseSequence(myIndent) {
        var arr = [];
        while (cursor.i < tokens.length) {
            var t = tokens[cursor.i];
            if (t.indent < myIndent) break;
            if (t.kind !== "item") break;
            cursor.i += 1;
            var itemBody = t.value;
            if (itemBody && itemBody.charAt(0) === "{") {
                arr.push(_yamlParseInlineMap(itemBody));
                continue;
            }
            // Block item. The first key/value pair may share the dash's
            // line; subsequent keys live on further-indented siblings.
            var entry = {};
            if (itemBody && itemBody.length) {
                var colon = itemBody.indexOf(":");
                if (colon < 0) {
                    return { __error: "loadCuration: malformed YAML at line " + t.lineno };
                }
                var k = itemBody.substring(0, colon).replace(/^\s+|\s+$/g, "");
                var v = itemBody.substring(colon + 1).replace(/^\s+/, "");
                if (v && v !== "") {
                    if (v.charAt(0) === "{") entry[k] = _yamlParseInlineMap(v);
                    else entry[k] = _yamlScalar(v);
                } else {
                    // Inline key with no value: child mapping follows.
                    var peek = tokens[cursor.i];
                    if (peek && peek.indent > myIndent && peek.kind === "kv") {
                        entry[k] = parseMapping(peek.indent);
                    } else if (peek && peek.indent > myIndent && peek.kind === "item") {
                        entry[k] = parseSequence(peek.indent);
                    } else {
                        entry[k] = null;
                    }
                }
            }
            // Pull in any further keys belonging to this block item: they
            // appear at indent > myIndent and as "kv" tokens until we hit
            // a sibling item or shallower indent.
            while (cursor.i < tokens.length) {
                var peek2 = tokens[cursor.i];
                if (peek2.indent <= myIndent) break;
                if (peek2.kind !== "kv") break;
                cursor.i += 1;
                if (peek2.value && peek2.value !== "") {
                    if (peek2.value.charAt(0) === "{") {
                        entry[peek2.key] = _yamlParseInlineMap(peek2.value);
                    } else {
                        entry[peek2.key] = _yamlScalar(peek2.value);
                    }
                } else {
                    var next3 = tokens[cursor.i];
                    if (next3 && next3.indent > peek2.indent && next3.kind === "kv") {
                        entry[peek2.key] = parseMapping(next3.indent);
                    } else if (next3 && next3.indent > peek2.indent && next3.kind === "item") {
                        entry[peek2.key] = parseSequence(next3.indent);
                    } else {
                        entry[peek2.key] = null;
                    }
                }
                if (entry[peek2.key] && entry[peek2.key].__error) {
                    return entry[peek2.key];
                }
            }
            arr.push(entry);
        }
        return arr;
    }

    if (tokens.length === 0) {
        return { ok: false, error: "loadCuration: empty input at line 1" };
    }
    var topIndent = tokens[0].indent;
    var data = parseMapping(topIndent);
    if (data && data.__error) return { ok: false, error: data.__error };
    return { ok: true, data: data };
}

// ── Sniffer ──────────────────────────────────────────────────────────────────

/**
 * Inspect a picked file and return a sniffer-result object.
 *
 * Resolution order (cheapest first):
 *   1. Extension → audio / json / yaml.
 *   2. JSON: parse + peek for `schema_version` + (`pads` | `chunks`).
 *   3. YAML: parse-light, look for top-level `curation_version`.
 *
 * Returns:
 *   { path, type, validated, detail }
 *
 * The caller is responsible for setting module-scope `pickedSource` and
 * emitting `sniffer:` status lines so test harness can assert.
 */
function _snifferInspect(picked) {
    var path = _sfNormalizePath(picked);
    var ext = _sfExtOf(path);
    var result = { path: path, type: "unknown", validated: false, detail: "" };

    // Audio short-circuit. Don't bother opening the file — extension is
    // sufficient and the file might be many GB.
    for (var i = 0; i < SNIFFER_AUDIO_EXTS.length; i += 1) {
        if (ext === SNIFFER_AUDIO_EXTS[i]) {
            result.type = "audio";
            result.validated = true;
            // Detail is purely cosmetic — surface the extension uppercased.
            result.detail = ext.substring(1).toUpperCase();
            return result;
        }
    }

    var raw = readFileContents(path);
    if (raw == null || !raw.length) {
        result.detail = "could not read file";
        return result;
    }

    if (ext === ".json") {
        var parsed = null;
        try { parsed = JSON.parse(raw); } catch (_) {
            result.detail = "invalid JSON";
            return result;
        }
        if (!parsed || typeof parsed !== "object") {
            result.detail = "JSON is not an object";
            return result;
        }
        if (parsed.schema_version === undefined) {
            // Legacy pre-rebuild prechop_manifest.json (no schema_version
            // — predates the new architecture). Identified by its
            // canonical keys: bpm + bars + stems[]. Still loadable via
            // loadArrangementFromManifest() (Phase 2 LOM behavior
            // preserved per spec §11 migration plan).
            if (typeof parsed.bpm === "number"
                    && typeof parsed.bars === "number"
                    && Array.isArray(parsed.stems)) {
                result.type = "prechop_manifest";
                result.validated = true;
                result.detail = "legacy prechop (bpm=" + parsed.bpm
                    + ", bars=" + parsed.bars + ")";
                return result;
            }
            result.detail = "missing schema_version";
            return result;
        }
        // ForgeManifest in stemforge.configurator.schemas.forge actually
        // serializes its bar-clip array under `clips` (not `pads`); the
        // earlier sniffer pattern reflected an older draft of the spec.
        // We accept both for forward-compat with whatever the next schema
        // rev calls it.
        if (parsed.clips !== undefined || parsed.pads !== undefined) {
            result.type = "forge_manifest";
            result.validated = true;
            result.detail = "schema_version=" + parsed.schema_version;
            return result;
        }
        if (parsed.chunks !== undefined) {
            result.type = "arrangement_manifest";
            result.validated = true;
            result.detail = "schema_version=" + parsed.schema_version;
            return result;
        }
        result.detail = "no clips, pads, or chunks key";
        return result;
    }

    if (ext === ".yaml" || ext === ".yml") {
        var peek = _yamlParseCuration(raw);
        if (!peek.ok) {
            result.detail = peek.error || "YAML parse error";
            return result;
        }
        if (peek.data && peek.data.curation_version !== undefined) {
            result.type = "curation";
            result.validated = true;
            result.detail = "curation_version=" + peek.data.curation_version;
            return result;
        }
        result.detail = "missing curation_version";
        return result;
    }

    result.detail = "unsupported extension";
    return result;
}

// ── Primary-button label / enabled state ─────────────────────────────────────

function _primaryLabelFor(type) {
    if (type && PRIMARY_LABEL_BY_TYPE[type]) return PRIMARY_LABEL_BY_TYPE[type];
    return "Pick a source…";
}

function _emitPrimaryButtonState(type, enabled) {
    var label = _primaryLabelFor(type);
    try { messnamed(PRIMARY_LABEL_RECV, label); } catch (_) {}
    try { messnamed(PRIMARY_ENABLED_RECV, enabled ? 1 : 0); } catch (_) {}
    // Also echo the armed action through the status line. live.text mode 1
    // doesn't always paint a dynamic @text update (depends on Live build),
    // so the on-device status text is the load-bearing UX signal that
    // tells the user what the primary button is now bound to. Without
    // this, a successful sniff looks like silence.
    if (enabled) {
        try { status("ready: click primary → " + label); } catch (_) {}
    }
}

// Public message: `applyPickedSource <path>` — invoked by the patcher when
// [opendialog] emits its result. Sniffs, stashes, and updates the primary
// button.
function applyPickedSource() {
    var argList = arrayfromargs(messagename, arguments);
    var args = argList.slice(1);
    if (!args.length) {
        status("sniffer: rejected — no path");
        pickedSource = null;
        _emitPrimaryButtonState(null, false);
        return;
    }
    var pickPath = args.join(" ");
    // Strip an optional Macintosh-HFS volume prefix ("Macintosh HD:") if
    // present. Live 12 sometimes emits POSIX paths directly and sometimes
    // emits HFS-prefixed ones; doing the conversion in JS (rather than a
    // [regexp] box in the patcher) avoids a load-time outlet-count race
    // we hit on the first UAT round. Single string op, easy to test.
    var hfsMatch = pickPath.match(/^[^:\/]+:(\/.*)$/);
    if (hfsMatch) {
        pickPath = hfsMatch[1];
    }
    var inspected = _snifferInspect(pickPath);
    pickedSource = {
        path: inspected.path,
        type: inspected.type,
        validated: !!inspected.validated
    };
    if (!inspected.validated) {
        status("sniffer: rejected — unknown type");
        _emitPrimaryButtonState(null, false);
        return;
    }
    if (inspected.type === "audio") {
        status("sniffer: detected audio (" + inspected.detail + ")");
    } else if (inspected.type === "curation") {
        status("sniffer: detected curation v1");
    } else if (inspected.type === "forge_manifest") {
        status("sniffer: detected forge manifest (" + inspected.detail + ")");
    } else if (inspected.type === "arrangement_manifest") {
        status("sniffer: detected arrangement manifest (" + inspected.detail + ")");
    } else {
        status("sniffer: detected " + inspected.type);
    }
    _emitPrimaryButtonState(inspected.type, true);
}

// Public message: `pickSource` — bangs the [opendialog]. The patcher wires
// [opendialog]'s outlet back to `applyPickedSource` so the result roundtrip
// is sandbox-friendly (per CLAUDE.md, `[shell]` is unavailable in M4L).
function pickSource() {
    // The actual dialog is owned by the patcher's [opendialog]; we just bang
    // it. Tests skip this step and call applyPickedSource() directly.
    outlet(0, "set", "Pick a source…");
    try { messnamed("sf-open-source-dialog", "bang"); } catch (_) {}
}

// Reset the picker state. Test-only convenience and used after a successful
// FORGE/LOAD to require the user to repick before the next action.
function resetPickedSource() {
    pickedSource = null;
    _emitPrimaryButtonState(null, false);
}

// ── loadCuration() ───────────────────────────────────────────────────────────
// Spec §3.3, §2.3. Walk LOM, ensure STG-A..STG-N exist, populate clip slots.
// Idempotent: pre-existing STG-<LETTER> tracks are deleted first.

var STG_TRACK_REGEX = /^STG-[A-Z]$/;

// Letter ↔ index helpers. `letterFromIndex(0) === "A"`.
function _stgLetterFromIndex(i) {
    return String.fromCharCode(65 + i);
}

function _stgIndexFromLetter(letter) {
    return String(letter).charCodeAt(0) - 65;
}

// Pad ID parser. Accepts "A01" and "A·01" (interpunct, per spec) and a
// rare "A-01" hyphen form. Returns {letter, slot} (slot is 0-based) or null.
function _parsePadId(padId) {
    if (!padId) return null;
    var s = String(padId).replace(/\s+/g, "");
    var m = s.match(/^([A-Z])[·\-_]?(\d+)$/i);
    if (!m) return null;
    return { letter: m[1].toUpperCase(), slot: parseInt(m[2], 10) - 1 };
}

// Find indices of every track whose name matches STG-<letter>. We have to
// walk in reverse-deletion order because Live re-indexes tracks on delete.
function _findStagingTrackIndices() {
    var out = [];
    var n = trackCount();
    for (var i = 0; i < n; i += 1) {
        if (STG_TRACK_REGEX.test(trackName(i))) out.push(i);
    }
    return out;
}

function _deleteStagingTracks() {
    var idxs = _findStagingTrackIndices();
    if (!idxs.length) return 0;
    idxs.sort(function (a, b) { return b - a; }); // descending
    var liveSet = new LiveAPI("live_set");
    for (var k = 0; k < idxs.length; k += 1) {
        liveSet.call("delete_track", idxs[k]);
    }
    return idxs.length;
}

function _createStagingTracks(letters) {
    var liveSet = new LiveAPI("live_set");
    var startCount = trackCount();
    for (var i = 0; i < letters.length; i += 1) {
        liveSet.call("create_audio_track", -1);
    }
    // The new tracks are appended; rename in order.
    for (var j = 0; j < letters.length; j += 1) {
        var newIdx = startCount + j;
        var trackApi = new LiveAPI("live_set tracks " + newIdx);
        trackApi.set("name", "STG-" + letters[j]);
    }
    return letters.length;
}

// Resolve a pad's audio_path. Relative paths are taken to be relative to
// the directory the curation YAML lives in (the popup writes paths that way).
function _resolvePadAudioPath(audioPath, curationFilePath) {
    var p = String(audioPath || "");
    if (!p) return p;
    if (p.charAt(0) === "/") return p;
    // Strip Max HFS prefix from curation path if present.
    var base = _sfNormalizePath(curationFilePath || "");
    var slash = base.lastIndexOf("/");
    var baseDir = slash < 0 ? "" : base.substring(0, slash);
    if (!baseDir) return p;
    return baseDir + "/" + p;
}

// Apply curation clip_settings (warp_bpm, loop_start, loop_end, looping) to
// a freshly-created clip. Tolerant of missing fields — every key is optional.
function _applyCurationClipSettings(clipApi, padEntry) {
    if (!clipApi || clipApi.id === "0") return;
    var s = padEntry && padEntry.clip_settings;
    if (!s) return;
    try {
        if (typeof s.warp_bpm === "number") clipApi.set("warp_bpm", s.warp_bpm);
    } catch (_) {}
    // Schema uses *_bar (musical bars); LOM expects beats. For 4/4 (the
    // device-spec's working assumption — EP-133 deck targets are 4/4),
    // beats = bars * 4. If the user is on a non-4/4 signature, the device
    // still loads and the user re-warps; we don't ship time-signature math
    // here because COMMIT/BOUNCE round-trips this faithfully.
    try {
        if (typeof s.loop_start_bar === "number") clipApi.set("loop_start", s.loop_start_bar * 4);
        else if (typeof s.loop_start === "number") clipApi.set("loop_start", s.loop_start);
    } catch (_) {}
    try {
        if (typeof s.loop_end_bar === "number") clipApi.set("loop_end", s.loop_end_bar * 4);
        else if (typeof s.loop_end === "number") clipApi.set("loop_end", s.loop_end);
    } catch (_) {}
    try {
        if (s.looping !== undefined) clipApi.set("looping", s.looping ? 1 : 0);
    } catch (_) {}
}

// Compute a sensible default clip-length (in beats) for create_clip. The
// curation spec carries `clip_settings.loop_end_bar` — if present we use that
// (in beats), else 4 beats (one bar 4/4). This is just the placeholder
// length; the subsequent set("file_path") + clip_settings overrides.
function _curationClipLengthBeats(padEntry) {
    var s = padEntry && padEntry.clip_settings;
    if (s && typeof s.loop_end_bar === "number") return s.loop_end_bar * 4;
    if (s && typeof s.loop_end === "number" && s.loop_end > 0) return s.loop_end;
    return 4;
}

/**
 * loadCuration(yamlText [, curationFilePath]) — entry point.
 *
 * yamlText: YAML body (string). Tests pass it directly; the device passes
 *           the contents of the picked file.
 * curationFilePath: optional, used to resolve relative `audio_path` entries.
 *
 * Side effects (per spec §3.3):
 *   1. Parse + duck-type validate.
 *   2. Delete pre-existing STG-* tracks.
 *   3. Create STG-A..STG-<N> tracks.
 *   4. For each pad with `source`, create_clip in the right slot, set file_path
 *      + clip_settings.
 *   5. Emit structured status events for L3 tests:
 *        "loadCuration: malformed YAML at line N" (rejection path)
 *        "staging: created STG-A through STG-D"
 *        "staging: populated A·01 (vocal-bar4-8)"   (per populated pad)
 *        "staging: skipped A·02 (no source)"        (per empty pad)
 *        "staging: stale reference noted <slug>"    (referenced_forges hint)
 *        "loadCuration: complete (4 groups, 12/64 pads populated)"
 *
 * Returns the parsed curation object on success, or null on parse failure.
 * (The boolean-y caller in the patcher pipeline only consumes the status
 * stream, so the return value is purely a test affordance.)
 */
function loadCuration(yamlText, curationFilePath) {
    var parsed = _yamlParseCuration(String(yamlText == null ? "" : yamlText));
    if (!parsed.ok) {
        status(parsed.error);
        return null;
    }
    var curation = parsed.data || {};
    if (curation.curation_version === undefined) {
        status("loadCuration: malformed YAML at line 1");
        return null;
    }

    // Reconcile group ordering. Prefer the curation's own group keys (sorted
    // alphabetically — A, B, C…) so labels survive round-trip. Fall back to
    // target.groups (an integer count) only when groups is missing/empty.
    var groupLetters = [];
    if (curation.groups && typeof curation.groups === "object") {
        var keys = [];
        for (var k in curation.groups) {
            if (Object.prototype.hasOwnProperty.call(curation.groups, k)) keys.push(k);
        }
        keys.sort();
        for (var ki = 0; ki < keys.length; ki += 1) groupLetters.push(keys[ki]);
    }
    if (!groupLetters.length) {
        var n = (curation.target && curation.target.groups) || 0;
        for (var gi = 0; gi < n; gi += 1) groupLetters.push(_stgLetterFromIndex(gi));
    }
    if (!groupLetters.length) {
        status("loadCuration: malformed YAML at line 1");
        return null;
    }

    // Stale-reference surface. The actual stale-detection logic is Phase 4B;
    // here we just emit a status line per referenced forge so downstream
    // tooling (popup, server) can decide whether to escalate.
    var refs = curation.referenced_forges;
    if (refs && refs.length) {
        for (var ri = 0; ri < refs.length; ri += 1) {
            var ref = refs[ri];
            var hash = ref && ref.manifest_hash;
            // The Phase 4B detector compares against the live forge hash;
            // we emit unconditionally so tests can grep for the prefix and
            // verify the line was written when a referenced_forges block
            // exists.
            if (ref && ref.slug) {
                status("staging: stale reference noted " + ref.slug
                    + " (hash " + String(hash || "?").substring(0, 8) + ")");
            }
        }
    }

    // Idempotent reset.
    _deleteStagingTracks();
    _createStagingTracks(groupLetters);
    var first = groupLetters[0];
    var last = groupLetters[groupLetters.length - 1];
    status("staging: created STG-" + first + " through STG-" + last);

    var totalPads = 0;
    var populated = 0;
    for (var li = 0; li < groupLetters.length; li += 1) {
        var letter = groupLetters[li];
        var groupBlock = (curation.groups && curation.groups[letter]) || {};
        var pads = groupBlock.pads || [];
        var trackIdx = _findTrackIndexByName("STG-" + letter);
        for (var pi = 0; pi < pads.length; pi += 1) {
            totalPads += 1;
            var pad = pads[pi];
            var padId = pad && pad.pad_id;
            var parsedPad = _parsePadId(padId);
            // Use canonical interpunct form for status emissions to match the
            // user-facing display in the popup.
            var displayId = parsedPad
                ? (parsedPad.letter + "·"
                    + (parsedPad.slot < 9 ? "0" : "") + (parsedPad.slot + 1))
                : String(padId || "?");
            if (!pad || !pad.source) {
                status("staging: skipped " + displayId + " (no source)");
                continue;
            }
            if (!parsedPad) {
                status("staging: skipped " + displayId + " (unparsable pad_id)");
                continue;
            }
            if (trackIdx < 0) {
                status("staging: skipped " + displayId + " (track STG-" + letter + " not found)");
                continue;
            }
            var slotIdx = parsedPad.slot;
            var clipLength = _curationClipLengthBeats(pad);
            var slotPath = "live_set tracks " + trackIdx + " clip_slots " + slotIdx;
            var slotApi = new LiveAPI(slotPath);
            slotApi.call("create_clip", clipLength);
            var clipApi = new LiveAPI(slotPath + " clip");
            // Resolve audio_path (may be relative to curation YAML dir).
            var audioPath = _resolvePadAudioPath(pad.source.audio_path, curationFilePath);
            if (audioPath) {
                try { clipApi.set("file_path", audioPath); } catch (_) {}
            }
            // Clip name = source.clip_id when present, else the pad id.
            var clipName = pad.source.clip_id || padId;
            try { clipApi.set("name", String(clipName)); } catch (_) {}
            _applyCurationClipSettings(clipApi, pad);
            populated += 1;
            status("staging: populated " + displayId + " (" + clipName + ")");
        }
    }

    // Phase 2 keystone: record the active curation so `commit()` knows
    // which name to address the server with and which letters to walk.
    activeCuration = {
        name: String(curation.name || ""),
        groupLetters: groupLetters.slice()
    };

    status("loadCuration: complete (" + groupLetters.length + " groups, "
        + populated + "/" + totalPads + " pads populated)");
    return curation;
}

// Find a track by exact name. Local helper for loadCuration so we don't
// disturb the legacy findTrackByName (case-insensitive) behaviour.
function _findTrackIndexByName(name) {
    var target = String(name);
    var n = trackCount();
    for (var i = 0; i < n; i += 1) {
        if (trackName(i) === target) return i;
    }
    return -1;
}

// ─────────────────────────────────────────────────────────────────────────────
// Configurator v1 Phase 2 — COMMIT keystone.
//
// Walk the staging tracks (STG-A..STG-N for the active curation), snapshot
// each clip slot's state into a Pad-shaped wire payload, ship it to the
// server which does the forge reverse-lookup + persists the new curation
// YAML.
//
// Spec refs: §2.3 (Pad shape, destination), §3.3 (verbs), §6.6 (commit
// flow), §11 (keystone — once this works the architecture's promise holds).
//
// Wire format (decided in PR description — chosen because the server's
// `POST /curations/{name}/commit` already exists, and the response payload
// — the new Curation — is information the device needs back; UDP is
// fire-and-forget so HTTP is the cleaner pick):
//
//   messnamed("sf-commit-send", curationName, jsonPayload)
//
// The patcher wires `sf-commit-send` to a Node-for-Max HTTP shim that
// POSTs to /curations/{name}/commit and bangs back `sf-commit-ack` on
// success (or `sf-commit-err <reason>` on failure). For headless tests we
// capture `sf-commit-send` directly off max-stub's messnamed log.
//
// Payload shape (matches DeviceCommitBody Pydantic schema):
//
//   {
//     "als_path": null,            // Phase 4A will fill this
//     "groups": {
//       "A": {
//         "label": null,           // null = preserve existing
//         "template": null,
//         "pads": [
//           { "pad_id": "A01",
//             "audio_path": "/abs/path/to/clip.wav",
//             "clip_settings": {
//               "warp_bpm": 138.0,
//               "loop_start_bar": 0,
//               "loop_end_bar": 4,
//               "looping": true
//             }
//           },
//           { "pad_id": "A02" }    // empty pad — no audio_path
//         ]
//       }
//     }
//   }
// ─────────────────────────────────────────────────────────────────────────────

// Clip slot cap per staging track. Matches loadCuration's default and
// curation.target.pads_per_group for the EP-133 device-class (12).
var COMMIT_SLOT_COUNT = 12;

// Receive port the patcher subscribes to for outgoing commit payloads.
var COMMIT_SEND_RECV = "sf-commit-send";

// Receive port the patcher's HTTP shim bangs back on success so the device
// can emit a `commit: server ack received` status line. Wired via the
// `commitAck()` message handler. Outside the [udpreceive] route table for
// now — Phase 4 wires the proper UDP path; this stub keeps the contract
// testable via `messnamed("commitAck", ...)`.
var COMMIT_ACK_RECV = "sf-commit-ack";

// Read a clip's properties via LiveAPI and return a flat JSON-ready shape.
// Returns null when the slot is empty (no clip → LiveAPI id "0").
function _commitReadClipSettings(clipApi) {
    if (!clipApi || clipApi.id === "0") return null;
    var rawWarp = clipApi.get("warp_bpm");
    var warpBpm = (rawWarp && rawWarp.length) ? Number(rawWarp[0]) : null;
    var rawLoopStart = clipApi.get("loop_start");
    var rawLoopEnd = clipApi.get("loop_end");
    var loopStartBeats = (rawLoopStart && rawLoopStart.length) ? Number(rawLoopStart[0]) : 0;
    var loopEndBeats = (rawLoopEnd && rawLoopEnd.length) ? Number(rawLoopEnd[0]) : 4;
    var rawLooping = clipApi.get("looping");
    var looping = (rawLooping && rawLooping.length) ? !!Number(rawLooping[0]) : true;
    // Convert beats → bars (4/4 assumption — matches loadCuration's
    // inverse and the server's _normalize_clip_settings fallback).
    return {
        warp_bpm: warpBpm,
        loop_start_bar: loopStartBeats / 4.0,
        loop_end_bar: loopEndBeats / 4.0,
        looping: !!looping
    };
}

// Read a clip's `file_path` (the absolute audio file the clip points at).
// Returns "" when the property is missing — that's the empty-clip case.
function _commitReadAudioPath(clipApi) {
    if (!clipApi || clipApi.id === "0") return "";
    try {
        var raw = clipApi.get("file_path");
        if (raw && raw.length) {
            var s = String(raw[0]);
            // Live can emit HFS-style paths in some Max versions; strip
            // the prefix so the server's reverse-lookup matches.
            return _sfNormalizePath(s);
        }
    } catch (_) {}
    return "";
}

// Walk one STG-<letter> track and return its group snapshot. Empty pads
// keep their slot via `{pad_id: <letter>NN}` with no audio_path.
function _commitWalkGroup(letter) {
    var pads = [];
    var trackIdx = _findTrackIndexByName("STG-" + letter);
    var nSlots = COMMIT_SLOT_COUNT;
    if (trackIdx < 0) {
        // Track missing — emit the placeholder pad ids so the server
        // still recognises the group geometry. The server preserves
        // existing label/template (null below) so a missing staging
        // track doesn't blow away the user's prior commit.
        for (var k = 0; k < nSlots; k += 1) {
            var slotNumK = k + 1;
            var padIdK = letter + (slotNumK < 10 ? "0" : "") + slotNumK;
            pads.push({ pad_id: padIdK });
        }
        return { label: null, template: null, pads: pads };
    }
    for (var i = 0; i < nSlots; i += 1) {
        var slotNum = i + 1;
        var padId = letter + (slotNum < 10 ? "0" : "") + slotNum;
        var slotPath = "live_set tracks " + trackIdx + " clip_slots " + i;
        var clipApi = new LiveAPI(slotPath + " clip");
        var audioPath = _commitReadAudioPath(clipApi);
        if (!audioPath) {
            pads.push({ pad_id: padId });
            continue;
        }
        var settings = _commitReadClipSettings(clipApi);
        var pad = { pad_id: padId, audio_path: audioPath };
        if (settings) pad.clip_settings = settings;
        pads.push(pad);
    }
    // label/template at the group level are popup-edited via PATCH; we
    // explicitly leave them null so the server's merge keeps whatever is
    // already on the curation (per merge_device_snapshot semantics).
    return { label: null, template: null, pads: pads };
}

// Build the full DeviceCommitBody payload from current LOM state.
// Exposed for L3 tests so the snapshot can be asserted without the
// messnamed round-trip.
function _commitBuildPayload() {
    var letters = (activeCuration && activeCuration.groupLetters) || [];
    if (!letters.length) {
        // Fallback: if no active curation was set (loadCuration not yet
        // called), assume EP-133 4-letter default. This keeps the
        // commit() entry point useful when devs trigger it manually
        // post a user drag-only session.
        letters = ["A", "B", "C", "D"];
    }
    var groups = {};
    for (var i = 0; i < letters.length; i += 1) {
        groups[letters[i]] = _commitWalkGroup(letters[i]);
    }
    return { als_path: null, groups: groups };
}

/**
 * commit() — the Phase 2 keystone entry point.
 *
 * Walks STG-A..STG-N (driven by the active curation set during
 * loadCuration), snapshots each populated clip, packages a
 * DeviceCommitBody-shaped JSON payload, and fires
 * `messnamed("sf-commit-send", curationName, jsonText)` for the patcher's
 * HTTP shim to POST.
 *
 * Status emissions (all greppable by L3 tests):
 *   "commit: walked <N> pads"
 *   "commit: no active curation — load one first"  (no-op exit path)
 *   "commit: sent <curationName> (<N> pads, <bytes>B)"
 *
 * Returns the payload object (for direct test access). The boolean-y
 * caller in the patcher pipeline ignores the return value.
 */
function commit() {
    if (!activeCuration || !activeCuration.name) {
        status("commit: no active curation — load one first");
        return null;
    }
    var payload = _commitBuildPayload();
    var totalPads = 0;
    var populatedPads = 0;
    for (var letter in payload.groups) {
        if (!Object.prototype.hasOwnProperty.call(payload.groups, letter)) continue;
        var groupPads = payload.groups[letter].pads;
        for (var i = 0; i < groupPads.length; i += 1) {
            totalPads += 1;
            if (groupPads[i].audio_path) populatedPads += 1;
        }
    }
    status("commit: walked " + populatedPads + " pads");
    var jsonText;
    try {
        jsonText = JSON.stringify(payload);
    } catch (e) {
        status("commit: stringify failed: " + e);
        return null;
    }
    try {
        messnamed(COMMIT_SEND_RECV, activeCuration.name, jsonText);
    } catch (e2) {
        status("commit: messnamed send failed: " + e2);
        return payload;
    }
    status("commit: sent " + activeCuration.name + " ("
        + populatedPads + "/" + totalPads + " pads, "
        + jsonText.length + "B)");
    return payload;
}

/**
 * commitAck() — bound to the `commitAck` message in the patcher (and
 * routed off `sf-commit-ack` UDP / Node-for-Max bang). Emits a status
 * line so the device's UI loop knows the server persisted the snapshot.
 *
 * In Phase 2 the patcher's HTTP shim fires `commitAck` synchronously
 * after a 200 response from `POST /curations/{name}/commit`. Phase 4
 * may extend this to carry the new manifest_hash for stale-detection.
 */
function commitAck() {
    status("commit: server ack received");
    try { messnamed("primary-btn-enabled", 1); } catch (_) {}
    status("commit: complete");
}

// `primary` — fired by the patcher's single primary button. Dispatches to
// the right verb based on pickedSource.type. Status emissions cover the
// "nothing picked" path so the user sees feedback even when the button is
// click-throughable.
function primary() {
    if (!pickedSource || !pickedSource.validated) {
        status("primary: no source picked");
        return;
    }
    if (pickedSource.type === "audio") {
        status("primary: dispatching FORGE on " + pickedSource.path);
        // FORGE pipeline lives in the bridge / native binary; the patcher
        // routes this through the standard NDJSON pipeline (existing wire).
        try { messnamed("sf-run-forge", pickedSource.path); } catch (_) {}
        return;
    }
    if (pickedSource.type === "forge_manifest"
            || pickedSource.type === "arrangement_manifest") {
        status("primary: dispatching LOAD FORGE on " + pickedSource.path);
        loadManifest("loadManifest", pickedSource.path);
        return;
    }
    if (pickedSource.type === "prechop_manifest") {
        // Legacy arrangement-pipeline manifest. Delegates to the
        // pre-rebuild arrangement-view loader; preserved per spec §11.
        status("primary: dispatching LOAD ARRANGEMENT on " + pickedSource.path);
        loadArrangementFromManifest("loadArrangementFromManifest", pickedSource.path);
        return;
    }
    if (pickedSource.type === "curation") {
        status("primary: dispatching LOAD CURATION on " + pickedSource.path);
        var text = readFileContents(pickedSource.path);
        if (text == null) {
            status("loadCuration: could not read " + pickedSource.path);
            return;
        }
        loadCuration(text, pickedSource.path);
        return;
    }
    status("primary: unknown type " + pickedSource.type);
}

// ─────────────────────────────────────────────────────────────────────────────
// Configurator v1 Phase 3A — Templates (.adg per-group).
//
// The popup edits `curation.groups[<letter>].template = <name>` via
//   PATCH /curations/{name}/template
// The server validates the template exists, writes the YAML, and fires a UDP
// datagram at the device:
//   udpsend localhost 7420 template-changed <letter> <template-or-dash>
//
// The patcher's `[udpreceive 7420]` already exists (Phase 2's commit shim
// listens on it). A new `[route template-changed]` table dispatches the
// arguments into `templateChanged(letter, name)` on the loader JS — see
// the test below for the message-handler contract.
//
// `templateChanged()` calls `applyGroupTemplate()` which resolves the
// `STG-<letter>` staging track and invokes `load_browser_item` on the
// device-0 slot of that track. The path is resolved from
//   ~/stemforge/templates/<name>.adg
//
// Wire-protocol decision (matches Phase 2's spirit): Phase 2 used HTTP via
// `messnamed` because the device needed the response payload back. Phase 3A
// is fire-and-forget — the server writes the YAML and the device hot-
// applies; no return value is needed. UDP is the simpler fit.
// ─────────────────────────────────────────────────────────────────────────────

// Path templates resolve against (mirrors `default_templates_dir()` in
// stemforge.configurator.template_io). The trailing slash is intentional —
// concatenated with the template name + ".adg".
var TEMPLATE_DIR_REL = "/stemforge/templates/";
// Sentinel emitted by the server when clearing a template assignment.
var TEMPLATE_CLEAR_SENTINEL = "-";

// Test-only override for the absolute templates dir. Tests set this so they
// don't depend on `_getHomePath()`'s `/Users/` walk (which doesn't work in
// the Node test env). Always "" in production.
var _templateDirOverride = "";

// Resolve the on-disk path of a template by name. Returns "" if Max's
// home-dir resolver couldn't pin down a user.
function _templatePathFor(name) {
    if (!name || name === TEMPLATE_CLEAR_SENTINEL) return "";
    if (_templateDirOverride) {
        var tail = _templateDirOverride.charAt(_templateDirOverride.length - 1) === "/"
            ? "" : "/";
        return _templateDirOverride + tail + String(name) + ".adg";
    }
    var home = "";
    try {
        home = _getHomePath();
    } catch (e) {
        return "";
    }
    if (!home) return "";
    return home + TEMPLATE_DIR_REL + String(name) + ".adg";
}

/**
 * applyGroupTemplate(groupLetter, templateName) — load <templateName>.adg
 * onto the STG-<letter> staging track.
 *
 * Behaviour:
 *   - templateName == null/"-": clear path — the server's convention for
 *     "remove the template assignment". v1 does NOT delete the loaded rack
 *     (that would risk losing dry signal); it just records the new state
 *     and emits a status line. A future Phase 4 will sweep stale racks.
 *   - templateName non-null: walks track names looking for STG-<letter>,
 *     then calls `load_browser_item` on the track's device-0 slot.
 *
 * The exact LOM verb is `load_browser_item` per Live's LOM reference; it
 * accepts an absolute path to a `.adg` file. If your Live version's LOM
 * uses a different verb (older builds shipped `load_device_from_path`),
 * the [udpsend] receive-side wrapper in the patcher can translate.
 *
 * Status emissions (greppable by L3 tests):
 *   "template: applied <name> to STG-<letter>"
 *   "template: cleared on STG-<letter>"
 *   "template: STG-<letter> not found"
 *   "template: home resolution failed"
 */
function applyGroupTemplate(groupLetter, templateName) {
    var letter = String(groupLetter || "").toUpperCase();
    if (!letter) {
        status("template: missing group letter");
        return false;
    }
    var trackIdx = _findTrackIndexByName("STG-" + letter);
    if (trackIdx < 0) {
        status("template: STG-" + letter + " not found");
        return false;
    }
    var isClear = (templateName == null
        || templateName === TEMPLATE_CLEAR_SENTINEL
        || templateName === "");
    if (isClear) {
        status("template: cleared on STG-" + letter);
        return true;
    }
    var path = _templatePathFor(templateName);
    if (!path) {
        status("template: home resolution failed");
        return false;
    }
    var trackApi = new LiveAPI("live_set tracks " + trackIdx);
    try {
        trackApi.call("load_browser_item", path);
    } catch (e) {
        status("template: load failed: " + e);
        return false;
    }
    status("template: applied " + templateName + " to STG-" + letter);
    return true;
}

/**
 * templateChanged(letter, name) — message entry point bound to the
 * patcher's `[route template-changed]` table. The patcher's
 * `[udpreceive 7420]` decomposes the incoming datagram into the route
 * keyword + positional args; `template-changed` lands here as two
 * strings.
 *
 * Idempotent: calling twice with the same args results in two calls to
 * `load_browser_item` but no error path — Live treats the second call
 * as a no-op (rack already there) modulo the file mtime.
 */
function templateChanged(letter, name) {
    applyGroupTemplate(letter, name);
}

// ─────────────────────────────────────────────────────────────────────────────
// Configurator v1 Phase 4A — active-curation bootstrap on Live `.als` open.
//
// On every `loadbang` (Live finishes initializing this device), the loader
// asks Live for the current set's absolute path and POSTs it to the server's
// `/als-opened` route via the established `messnamed("sf-als-opened", path)`
// HTTP shim. The patcher's HTTP wrapper does the request, hands the JSON
// response body back via `messnamed("sf-als-opened-ack", curationOrEmpty)`,
// which lands on `alsOpenedAck()` here. If the ack carries a curation name,
// we load it as if the user had picked the curation YAML manually.
//
// LOM-verb caveat (deferred to Phase 5 — live-in-the-loop verification):
//   The exact verb that returns the absolute path to the open `.als` is
//   not yet fully nailed down — Live's published LOM reference advertises
//   `live_app view get path_to_set_file` but builds differ. The loader
//   tries that first, then falls back to `live_set get path` (newer
//   builds) and finally `live_set get name` (filename without dir).
//   Tests cover all three paths; field verification is part of Phase 5.
// ─────────────────────────────────────────────────────────────────────────────

// messnamed targets for the HTTP shim. Patcher dispatches:
//   [r sf-als-opened] → POST /als-opened → response body → [s sf-als-opened-ack]
var ALS_OPENED_SEND = "sf-als-opened";
var ALS_OPENED_ACK_RECV = "sf-als-opened-ack";

// Guard against double-loadbang (Max fires loadbang twice in some patcher
// reload scenarios — once on initial open, once on the [js] reload). We
// only want a single bootstrap round-trip per device-open event.
var _alsOpenedFired = false;

// Test-only override hook: tests can pre-set the path the loader will
// "discover" from LOM via setAlsPathForTest(). Always "" in production —
// the LiveAPI walk wins.
var _alsPathOverrideForTest = null;

/**
 * Resolve the absolute path to the currently-open .als file.
 *
 * Tries (in order):
 *   1. The test override (set via setAlsPathForTest()).
 *   2. `new LiveAPI("live_app view").get("path_to_set_file")` — the
 *      documented verb.
 *   3. `new LiveAPI("live_set").get("path")` — newer builds.
 *   4. `new LiveAPI("live_set").get("name")` — filename-only fallback.
 *
 * Returns the resolved path string (possibly just a basename) or "" if
 * nothing surfaced. The empty-string case is forwarded to the server so
 * a "Live just opened Untitled" event still rings the SSE bell.
 */
function _getAlsPath() {
    if (_alsPathOverrideForTest != null) {
        return String(_alsPathOverrideForTest || "");
    }
    // Live 12's actual LOM attribute names (verified empirically; the
    // earlier probes `live_app view path_to_set_file` and `live_set path`
    // raised "no attribute" errors on every device load).
    //
    //   1. Song (`live_set`) → `file_path` — the absolute path of the
    //      currently-open .als, or empty for an untitled set.
    //   2. Song (`live_set`) → `name` — the filename without the dir,
    //      empty for an untitled set. Lets the server fall back to
    //      "best-effort" key lookup even when full path is missing.
    //
    // jsliveapi emits its own error if an attribute doesn't exist, even
    // when wrapped in try/catch on the JS side. We probe ONLY attributes
    // that definitely exist on the host class to keep the console quiet.
    try {
        var liveSet = new LiveAPI("live_set");
        var got = liveSet.get("file_path");
        if (got && got.length) {
            var path = String(got[0] == null ? "" : got[0]);
            if (path) return path;
        }
    } catch (_e1) { /* fall through */ }
    try {
        var liveSet2 = new LiveAPI("live_set");
        var gotName = liveSet2.get("name");
        if (gotName && gotName.length) {
            return String(gotName[0] == null ? "" : gotName[0]);
        }
    } catch (_e2) { /* fall through */ }
    return "";
}

/**
 * loadbang() — Max entry point fired when this [js] object finishes
 * loading. INTENTIONALLY a noop: at [js]-box-load time Live's LOM hasn't
 * been initialized yet, so calling LiveAPI here produces a stream of
 * "Live API is not initialized" warnings + an empty .als path.
 *
 * The real bootstrap fires from the patcher's `[live.thisdevice]` outlet
 * 3 (the "Live API ready" bang) via `[message liveApiReady]` → here.
 */
function loadbang() {
    // No-op — see `liveApiReady` below. Logging suppressed since Max
    // sometimes fires `loadbang` multiple times during script reload and
    // we don't want noise.
}

/**
 * liveApiReady() — driven by `[live.thisdevice]` outlet 3 in the
 * patcher. Now safe to read LiveAPI verbs because Live has finished
 * initializing the LOM. Sends the current .als path to the server so
 * it can ack back with the active curation (if any) and we auto-load.
 *
 * Idempotent within a single device-open event.
 */
function liveApiReady() {
    if (_alsOpenedFired) {
        status("als-opened: skipping (already fired)");
        return;
    }
    _alsOpenedFired = true;
    var alsPath = _getAlsPath();
    try {
        messnamed(ALS_OPENED_SEND, alsPath);
        status("als-opened: sent " + (alsPath || "<unknown>"));
    } catch (e) {
        status("als-opened: messnamed failed: " + e);
    }
}

// ── Open Editor (Phase 4B) ────────────────────────────────────────────────────
//
// The footer's [ Open Editor ] button is bound via the patcher's
// `[r sf-open-editor]` → message → [js] route; `[textbutton] → [t b] →
// [message openEditor]` lands here. We resolve the configurator server's
// port from `~/stemforge/.configurator_port` (written by
// `stemforge.configurator.server.discover_port`) and ask Max to open the
// popup URL via `messnamed("max", "launchbrowser", url)`. Per spec §4.2
// this is the only [shell]-free pop-out that's been proven to work inside
// Live's M4L sandbox.
//
// If the port file is missing (server not running), we fall back to the
// well-known port 7430 — the start of the server's PORT_RANGE — so a
// "Open Editor" click still attempts to reach a running server in the
// common single-instance case. The browser will surface the connection
// error if nothing is listening.

var CONFIGURATOR_PORT_FILE_PATH = "/stemforge/.configurator_port";
var CONFIGURATOR_DEFAULT_PORT = 7430;
var CONFIGURATOR_HOST = "127.0.0.1";

function _readConfiguratorPort() {
    // Max's classic [js] File API doesn't reliably expand ~ on macOS, so
    // we compose the absolute path from $HOME like sf_logger does. The
    // file's contents are a single integer (the resolved server port);
    // anything malformed → null.
    try {
        var home;
        try {
            if (typeof max !== "undefined" && max && typeof max.getsystemvariable === "function") {
                home = String(max.getsystemvariable("HOME") || "");
            }
        } catch (_) { /* try File.getenv next */ }
        if (!home) {
            try {
                if (typeof File !== "undefined" && typeof File.getenv === "function") {
                    home = String(File.getenv("HOME") || "");
                }
            } catch (_) { /* fall through */ }
        }
        if (!home) return null;
        var maxPath = "Macintosh HD:" + home + CONFIGURATOR_PORT_FILE_PATH;
        var f = new File(maxPath, "read");
        if (!f || !f.isopen) return null;
        f.position = 0;
        var raw = f.readstring(64);
        f.close();
        if (raw == null) return null;
        var s = String(raw).replace(/\s+/g, "");
        if (!s.length) return null;
        var n = parseInt(s, 10);
        if (!isFinite(n) || n <= 0) return null;
        return n;
    } catch (e) {
        try { post("[sf_loader] _readConfiguratorPort error: " + e + "\n"); } catch (_) {}
        return null;
    }
}

/**
 * alsOpenedAck(curationOrSentinel) — message handler bound to the
 * patcher's `[r sf-als-opened-ack]`. The HTTP shim parses the
 * `/als-opened` response body and posts the resolved curation name
 * (or the empty-string / "-" sentinel for "no active curation").
 *
 * Behaviour:
 *   - non-empty + non-sentinel curation name → look up the curation YAML
 *     on disk via `~/stemforge/curations/<name>.yaml` and call
 *     loadCuration() with its contents.
 *   - empty / "-" sentinel → emit a status line and do nothing else.
 *
 * Status lines (greppable by L3 tests):
 *   "als-opened: ack <name>"
 *   "als-opened: ack <none>"
 *   "als-opened: curation file not found: <path>"
 */
function alsOpenedAck(curationOrSentinel) {
    var name = String(curationOrSentinel == null ? "" : curationOrSentinel);
    if (!name || name === TEMPLATE_CLEAR_SENTINEL) {
        status("als-opened: ack <none>");
        return;
    }
    status("als-opened: ack " + name);
    // Resolve the curation file path under ~/stemforge/curations/<name>.yaml.
    var home = "";
    try {
        home = _getHomePath();
    } catch (_e) {
        status("als-opened: home resolution failed");
        return;
    }
    if (!home) {
        status("als-opened: home resolution failed");
        return;
    }
    var curationPath = home + "/stemforge/curations/" + name + ".yaml";
    var text = "";
    try {
        text = readFileContents(curationPath);
    } catch (_e2) {
        text = "";
    }
    if (!text) {
        status("als-opened: curation file not found: " + curationPath);
        return;
    }
    loadCuration(text, curationPath);
}

/**
 * openEditor — bound to the footer's "Open Editor" button via the
 * patcher's `[r sf-open-editor]` receiver.
 *
 * Resolves the configurator server's port from disk (or falls back to
 * 7430 — the start of the server's PORT_RANGE) and asks Max to open the
 * popup URL via the documented `messnamed("max", "launchbrowser", url)`
 * verb. Returns the URL so tests can assert against it without driving
 * `messnamed` through a real Max.
 */
function openEditor() {
    var port = _readConfiguratorPort();
    if (port == null) port = CONFIGURATOR_DEFAULT_PORT;
    var url = "http://" + CONFIGURATOR_HOST + ":" + port + "/";
    try { messnamed("max", "launchbrowser", url); } catch (e) {
        try { post("[sf_loader] openEditor messnamed failed: " + e + "\n"); } catch (_) {}
    }
    status("editor → " + url);
    return url;
}

// ── Entry points from Max ─────────────────────────────────────────────────────
// These aren't stored on `globalThis`; Max's classic [js] object scans for
// top-level functions automatically.

// Eslint-friendly re-exports — tests import the file as CommonJS via a shim.
if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        STEM_TARGETS: STEM_TARGETS,
        SIMPLER_TEMPLATE: SIMPLER_TEMPLATE,
        BAR_TRACK_ORDER: BAR_TRACK_ORDER,
        BAR_TRACK_COLORS: BAR_TRACK_COLORS,
        PROCESSING_CONFIG: PROCESSING_CONFIG,
        // Configurator v1 Phase 1C — picker + sniffer + LOAD curation.
        _yamlParseCuration: _yamlParseCuration,
        _snifferInspect: _snifferInspect,
        _primaryLabelFor: _primaryLabelFor,
        _parsePadId: _parsePadId,
        _findStagingTrackIndices: _findStagingTrackIndices,
        _resolvePadAudioPath: _resolvePadAudioPath,
        applyPickedSource: applyPickedSource,
        pickSource: pickSource,
        resetPickedSource: resetPickedSource,
        loadCuration: loadCuration,
        primary: primary,
        getPickedSource: function () { return pickedSource; },
        // Configurator v1 Phase 2 — COMMIT keystone (device walker).
        commit: commit,
        commitAck: commitAck,
        _commitBuildPayload: _commitBuildPayload,
        _commitWalkGroup: _commitWalkGroup,
        _commitReadClipSettings: _commitReadClipSettings,
        _commitReadAudioPath: _commitReadAudioPath,
        // Configurator v1 Phase 3A — template hot-apply (server→device).
        applyGroupTemplate: applyGroupTemplate,
        templateChanged: templateChanged,
        _templatePathFor: _templatePathFor,
        TEMPLATE_CLEAR_SENTINEL: TEMPLATE_CLEAR_SENTINEL,
        setTemplateDirForTest: function (dir) {
            _templateDirOverride = String(dir || "");
        },
        // Configurator v1 Phase 4B — Open Editor button (footer of StemForge.amxd).
        openEditor: openEditor,
        _readConfiguratorPort: _readConfiguratorPort,
        CONFIGURATOR_DEFAULT_PORT: CONFIGURATOR_DEFAULT_PORT,
        CONFIGURATOR_HOST: CONFIGURATOR_HOST,
        // Configurator v1 Phase 3B — BOUNCE refactor (curation-driven render).
        bounceCuration: bounceCuration,
        _bounceCropOnePad: _bounceCropOnePad,
        _bounceSoloGroup: _bounceSoloGroup,
        _bounceUnsoloAll: _bounceUnsoloAll,
        _bouncePadCanon: _bouncePadCanon,
        _readLoopRegion: _readLoopRegion,
        getActiveCuration: function () { return activeCuration; },
        setActiveCurationForTest: function (name, letters) {
            activeCuration = {
                name: String(name || ""),
                groupLetters: (letters || []).slice()
            };
        },
        // Configurator v1 Phase 4A — als-opened bootstrap.
        loadbang: loadbang,
        liveApiReady: liveApiReady,
        alsOpenedAck: alsOpenedAck,
        _getAlsPath: _getAlsPath,
        ALS_OPENED_SEND: ALS_OPENED_SEND,
        ALS_OPENED_ACK_RECV: ALS_OPENED_ACK_RECV,
        setAlsPathForTest: function (path) {
            _alsPathOverrideForTest = path == null ? null : String(path);
        },
        resetAlsOpenedFiredForTest: function () {
            _alsOpenedFired = false;
        }
    };
}
