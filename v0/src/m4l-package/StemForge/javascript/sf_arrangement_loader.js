// sf_arrangement_loader.js
// ─────────────────────────────────────────────────────────────────────────────
// Arrangement-view loader for `prechop_manifest.json` output.
//
// Companion to:
//   - stemforge/prechop.py     (writes the padded chunk WAVs + manifest)
//   - pipelines/arrangement.yaml (configures bars / pad_bars / pad_last)
//
// What it does:
//   Reads a `prechop_manifest.json`, then for each stem's pre-chopped chunks
//   creates an arrangement-view audio clip on a stem-named track, positioning
//   them end-to-end on the timeline. Each clip's loop region is set from the
//   manifest's `loop_start_sec` / `loop_end_sec` so playback hits only the
//   target N-bar window by default — but the padding (which is real audio
//   from the surrounding bars of the song) sits available on either side
//   for the user to drag-extend into.
//
// Public entry point (called from stemforge_loader.v0.js's
// `loadArrangementFromManifest` wrapper via classic [js] include(); name kept
// distinct from the wrapper so include() doesn't clobber the wrapper after
// reload):
//
//     runArrangementLoad(manifestPath: string) -> bool
//
// Manifest shape (subset relevant to us — see prechop.py for full):
//
//     {
//       "bpm": 120.0,
//       "bars": 4,
//       "pad_bars": 1,
//       "pad_last": true,
//       "beats_per_bar": 4,
//       "stems": {
//         "drums": {
//           "dir": "drums_prechop",
//           "chunk_count": 4,
//           "chunks": [
//             {
//               "file": "drums_prechop/drums_chunk_001.wav",
//               "stem": "drums",
//               "chunk_index": 1,
//               "bars": 4,
//               "pad_bars": 1,
//               "pad_pre_bars": 0.0,
//               "pad_post_bars": 1.0,
//               "loop_start_sec": 0.0,
//               "loop_end_sec": 8.0,
//               "total_sec": 10.0
//             }, ...
//           ]
//         },
//         "bass": { ... },
//         "other": { ... },
//         "vocals": { ... }
//       }
//     }
//
// Per-clip mapping:
//   - Timeline position (beats): chunk_index_zero_based * bars * beats_per_bar
//                                = i * bars * 4   (4/4 assumed)
//   - Clip source: chunk's WAV path (resolved relative to the manifest file).
//   - Clip span (start_marker / end_marker): the loop region inside the WAV,
//     converted from seconds → beats via the manifest BPM. So in the
//     arrangement-view timeline, the clip occupies exactly `bars` bars of
//     wall time and plays the target audio. The padding sits inside the
//     clip's source but outside its span — drag the right edge to extend.
//   - looping = true; loop_start / loop_end mirror the start/end markers
//     (both expressed in beats relative to the clip's start_time).
//
// LOM conventions adopted from sf_arrangement_reader.js:
//   - Top-level functions are auto-exposed to Max's classic [js].
//   - LOM scalars come back as 1-element arrays; unwrap with the helpers.
//   - File paths going INTO LiveAPI need an absolute filesystem path (NOT
//     "Macintosh HD:" prefixed — that prefix is for the Max File API).
//   - 4/4 time signature is assumed by the manifest schema; a future
//     arrangement.yaml field could parameterize this.
//
// Riskiest assumption (CALL OUT FOR USER REVIEW):
//   Live 11+ exposes `Track.create_audio_clip(filepath, start_time_in_beats)`.
//   This call has been observed to be Live-version-sensitive and the LOM
//   docs note it is a deferred call. We use it via LiveAPI.call(...). If it
//   doesn't return the new clip's id we walk arrangement_clips by start time
//   to find it. If your Live version returns the id directly that's used.
// ─────────────────────────────────────────────────────────────────────────────

/* global LiveAPI, File, Folder, post, outlet, max */

// ── Logging (mirrors arrangement_reader pattern so failures land in the same
// log file the user already tails) ─────────────────────────────────────────

function _alFileLog(msg) {
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
        var line = "[" + ts + "] [sf_arrangement_loader] " + String(msg) + "\n";
        var f = new File(maxPath, "write", "TEXT", "TEXT");
        if (!f.isopen) return;
        try { f.position = f.eof; } catch (_) {}
        f.writestring(line);
        try { f.eof = f.position; } catch (_) {}
        f.close();
    } catch (_) {}
}

function _alStatus(msg) {
    try { post("[sf_arrangement_loader] " + String(msg) + "\n"); } catch (_) {}
    _alFileLog(msg);
}

// ── Path / LOM helpers (intentional duplicates of reader helpers — keeps
// this module loadable without sourcing the 1900-line loader) ─────────────

function _alHomeDir() {
    var h = "";
    try {
        if (typeof max !== "undefined" && max && typeof max.getsystemvariable === "function") {
            h = String(max.getsystemvariable("HOME") || "");
        }
    } catch (_) {}
    if (!h) {
        try {
            if (typeof File !== "undefined" && typeof File.getenv === "function") {
                h = String(File.getenv("HOME") || "");
            }
        } catch (_) {}
    }
    if (!h) h = "/Users/zak";
    if (h.charAt(h.length - 1) === "/") h = h.substring(0, h.length - 1);
    return h;
}

function _alExpandTilde(p) {
    var s = String(p || "");
    if (s === "~") return _alHomeDir();
    if (s.length >= 2 && s.charAt(0) === "~" && s.charAt(1) === "/") {
        return _alHomeDir() + s.substring(1);
    }
    return s;
}

function _alToMaxPath(p) {
    var s = _alExpandTilde(p);
    if (s.length > 0 && s.charAt(0) === "/") return "Macintosh HD:" + s;
    return s;
}

function _alDirname(absPath) {
    // Returns the parent directory of an absolute POSIX path. No trailing slash.
    var s = String(absPath);
    var i = s.lastIndexOf("/");
    if (i <= 0) return "/";
    return s.substring(0, i);
}

function _alJoin(dir, rel) {
    // Resolve `rel` against `dir`. Absolute `rel` wins.
    var r = String(rel);
    if (r.length > 0 && r.charAt(0) === "/") return r;
    var d = String(dir);
    if (d.length > 0 && d.charAt(d.length - 1) === "/") {
        d = d.substring(0, d.length - 1);
    }
    return d + "/" + r;
}

function _alGetLomNumber(api, prop) {
    try {
        var v = api.get(prop);
        if (v && typeof v === "object") return Number(v[0]);
        return Number(v);
    } catch (_) {
        return NaN;
    }
}

// ── File I/O ────────────────────────────────────────────────────────────────

function _alReadFile(absPath) {
    // Reads a UTF-8 text file. Returns the string or null on failure.
    try {
        var maxPath = _alToMaxPath(absPath);
        // Two-arg form: the third "type" arg filters by Mac OS 4-char file
        // type code, which Python-written .json files lack — passing "TEXT"
        // makes the open silently fail (f.isopen === false). Match the
        // sf_manifest_loader.js read pattern.
        var f = new File(maxPath, "read");
        if (!f.isopen) {
            _alStatus("read: could not open " + absPath);
            return null;
        }
        try { f.position = 0; } catch (_) {}
        // Max File.readstring caps at signed-short max (32767 chars) per call
        // and returns truncated data on N > 32767 — the JSON parse then fails.
        // Loop with explicit position-advance guard so we fail fast if the
        // API lies. Mirrors sf_manifest_loader._readFileContents.
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
        _alStatus("read error: " + e);
        return null;
    }
}

// ── Track lookup / creation ─────────────────────────────────────────────────
// We expose two strategies and use the first that finds a track:
//   1. Match by exact name (e.g. "drums", "bass") — case-insensitive.
//   2. Match by name CONTAINS the stem name — handles "SF | Drums Raw" etc.
//
// If neither finds anything, we create a new audio track at the end of the
// track list and rename it to the stem name. The audible setup is left to
// the user (no devices, no template chain).

function _alTrackCount() {
    return new LiveAPI("live_set").getcount("tracks");
}

function _alTrackName(i) {
    var raw = new LiveAPI("live_set tracks " + i).get("name");
    return (raw && typeof raw === "object") ? String(raw[0]) : String(raw);
}

function _alIsAudioTrack(i) {
    var api = new LiveAPI("live_set tracks " + i);
    var v = api.get("has_audio_input");
    if (v && typeof v === "object") return Number(v[0]) === 1;
    return Number(v) === 1;
}

// Schema vs prechop label variance: schema is singular ("drum","vocal"),
// prechop is plural ("drums","vocals"). Re-anchor reloads via the prechop
// manifest, so the loader sees plural keys; without this alias table it
// substring-fails against the singular tracks LOAD FORGE created
// ("definition | drum") and falls through to `_alCreateAudioTrack`,
// duplicating "drums"/"vocals" tracks. Caught 2026-05-15 after ANCH.
var _AL_STEM_ALIASES = {
    drum: ["drum", "drums"],
    drums: ["drums", "drum"],
    vocal: ["vocal", "vocals"],
    vocals: ["vocals", "vocal"],
    bass: ["bass"],
    other: ["other"]
};

function _alFindTrackForStem(stemName) {
    var n = _alTrackCount();
    var lc = String(stemName).toLowerCase();
    var aliases = _AL_STEM_ALIASES[lc] || [lc];
    var firstContains = -1;
    for (var i = 0; i < n; i++) {
        if (!_alIsAudioTrack(i)) continue;
        var name = _alTrackName(i).toLowerCase();
        for (var ai = 0; ai < aliases.length; ai++) {
            var alias = aliases[ai];
            if (name === alias) return i;
            if (firstContains < 0 && name.indexOf(alias) >= 0) firstContains = i;
        }
    }
    return firstContains;
}

function _alCreateAudioTrack(stemName) {
    // create_audio_track(-1) inserts at the end. Returns the new index by
    // rescanning track count — Live's call return value isn't always reliable.
    var liveSet = new LiveAPI("live_set");
    var before = _alTrackCount();
    try {
        liveSet.call("create_audio_track", -1);
    } catch (e) {
        _alStatus("create_audio_track failed: " + e);
        return -1;
    }
    var after = _alTrackCount();
    if (after <= before) {
        _alStatus("create_audio_track: track count did not increase");
        return -1;
    }
    var newIdx = after - 1;
    try {
        new LiveAPI("live_set tracks " + newIdx).set("name", stemName);
    } catch (_) {}
    return newIdx;
}

function _alResolveTrack(stemName) {
    var idx = _alFindTrackForStem(stemName);
    if (idx >= 0) {
        _alStatus("stem " + stemName + " → track " + idx + " (" + _alTrackName(idx) + ")");
        return idx;
    }
    idx = _alCreateAudioTrack(stemName);
    if (idx >= 0) {
        _alStatus("stem " + stemName + " → created track " + idx);
    }
    return idx;
}

// ── Clip creation on arrangement view ───────────────────────────────────────

function _alFindClipAtBeat(trackIdx, beat) {
    // Find the arrangement_clip whose start_time matches `beat`. Used after
    // create_audio_clip when its return value is unreliable.
    //
    // Performance: this used to walk arrangement_clips from index 0, which
    // is O(N) per call and O(N²) over a stem's load. On a 328-clip
    // arrangement (true_love_waits @ doubled BPM) the walk dominated cost
    // at chunk 80 (~160 LiveAPI gets per chunk vs 7 at chunk 1, observed
    // ~13ms per iter) and produced the exponential decay pattern in
    // sf_debug.log. Killed by walking REVERSE: create_audio_clip appends,
    // so the new clip is at index n-1 (and almost always the only valid
    // candidate). Walk back only on the rare case where the last index
    // doesn't match (e.g. another writer created a clip concurrently).
    var trackApi = new LiveAPI("live_set tracks " + trackIdx);
    var n = 0;
    try { n = trackApi.getcount("arrangement_clips") | 0; }
    catch (_) { return -1; }
    if (n === 0) return -1;

    for (var i = n - 1; i >= 0; i--) {
        var clip = new LiveAPI(
            "live_set tracks " + trackIdx + " arrangement_clips " + i
        );
        if (!clip || clip.id === "0") continue;
        var st = _alGetLomNumber(clip, "start_time");
        if (isFinite(st) && Math.abs(st - beat) < 1e-3) return i;
    }
    return -1;
}

function _alCreateAndConfigureClip(trackIdx, absWavPath, startBeat, lengthBeats,
                                   loopStartSec, loopEndSec, bpm) {
    // Creates an audio clip on `trackIdx`'s arrangement view at `startBeat`,
    // sources it from `absWavPath`, sets the playback span (start_marker /
    // end_marker) and loop region to [loopStartSec, loopEndSec] (in SECONDS,
    // since we disable warping below — see comment).
    //
    // Returns the clip's arrangement_clips index (>= 0) on success, -1 on fail.
    var trackPath = "live_set tracks " + trackIdx;
    var trackApi = new LiveAPI(trackPath);

    // Live 11 audio-track create_audio_clip signature: (path, position_beats).
    // The call is deferred — the new clip is queryable via arrangement_clips.
    try {
        trackApi.call("create_audio_clip", absWavPath, startBeat);
    } catch (e) {
        _alStatus("create_audio_clip failed: " + e + " path=" + absWavPath);
        return -1;
    }

    var idx = _alFindClipAtBeat(trackIdx, startBeat);
    if (idx < 0) {
        _alStatus("created clip not found at beat " + startBeat
            + " (track " + trackIdx + ")");
        return -1;
    }

    var clipPath = trackPath + " arrangement_clips " + idx;
    var clip = new LiveAPI(clipPath);

    // Force warping OFF so start_marker/end_marker/loop_start/loop_end are
    // interpreted in SECONDS — the chunks are pre-rendered at manifest bpm
    // and the project tempo is already aligned (set in runArrangementLoad),
    // so unwarped playback at the native rate stays in sync with the
    // arrangement timeline. Avoids fighting Live's auto-warp tempo guess.
    // Note: warp_bpm is read-only; the warped path requires explicit warp
    // markers (see stemforge_loader.v0.js's add_warp_marker pattern), which
    // we don't need for chunks that already match project tempo.
    try { clip.set("warping", 0); } catch (_) {}

    // Loop / markers: all in SECONDS (since warping is off above).
    // Order matters in some Live versions — set looping=1 LAST.
    try { clip.set("start_marker", loopStartSec); } catch (e) {
        _alStatus("set start_marker fail: " + e);
    }
    try { clip.set("end_marker", loopEndSec); } catch (e) {
        _alStatus("set end_marker fail: " + e);
    }
    try { clip.set("loop_start", loopStartSec); } catch (e) {
        _alStatus("set loop_start fail: " + e);
    }
    try { clip.set("loop_end", loopEndSec); } catch (e) {
        _alStatus("set loop_end fail: " + e);
    }
    try { clip.set("looping", 1); } catch (e) {
        _alStatus("set looping fail: " + e);
    }

    // The arrangement-view extent is governed by `end_marker` (set above):
    // playback stops there, and the visible block ends there. `Clip.length`
    // is read-only in current Live and `Clip.end_time` returns "Invalid
    // syntax", so neither helps; both prior attempts at writing them
    // produced 1 console error per chunk × N chunks.
    void lengthBeats;

    return idx;
}

// ── Manifest → arrangement view ─────────────────────────────────────────────

function _alSecToBeats(sec, bpm) {
    // beats = seconds * bpm / 60. Defensive: clamp negatives to 0.
    var b = Number(sec) * Number(bpm) / 60.0;
    if (!isFinite(b) || b < 0) return 0;
    return b;
}

function _alClearStemfgClips(trackIdx, manifestDir) {
    // Delete every arrangement_clip on this track whose file_path sits inside
    // `manifestDir`. Why scoped to that dir: a re-load (e.g. after re-anchor)
    // must wipe the prior chunks before placing new ones, otherwise the new
    // clips collide with the old ones at identical start beats and
    // create_audio_clip silently fails — leaving the OLD audio on the
    // arrangement view despite the WAV files having been rewritten on disk.
    // Scoping to `manifestDir` preserves any user-placed clips (their own
    // recordings, MIDI bounces, etc.) that share the stem track.
    //
    // Walk arrangement_clips in REVERSE so deletion doesn't shift the
    // indices of clips we haven't visited yet.
    var trackApi = new LiveAPI("live_set tracks " + trackIdx);
    var n = 0;
    try { n = trackApi.getcount("arrangement_clips") | 0; }
    catch (_) { return 0; }
    var deleted = 0;
    var prefix = String(manifestDir || "");
    for (var i = n - 1; i >= 0; i--) {
        var clipPath = "live_set tracks " + trackIdx + " arrangement_clips " + i;
        var clip = new LiveAPI(clipPath);
        if (!clip || clip.id === "0") continue;
        var fp = "";
        try { fp = String(clip.get("file_path") || ""); } catch (_) {}
        if (!fp) continue;
        if (fp.indexOf(prefix) !== 0) continue;
        try {
            trackApi.call("delete_clip", "id", clip.id);
            deleted++;
        } catch (e) {
            _alStatus("delete_clip failed for " + fp + ": " + e);
        }
    }
    return deleted;
}

function _alLoadStem(stemName, stemBlock, manifestDir, bpm, beatsPerBar, shiftBeats) {
    // Returns {ok: bool, clips_created: int}.
    var trackIdx = _alResolveTrack(stemName);
    if (trackIdx < 0) {
        _alStatus("could not resolve track for stem " + stemName);
        return { ok: false, clips_created: 0 };
    }

    // Wipe any prior stemforge-owned clips on this track before placing the
    // new ones. Necessary on re-anchor: the WAV file paths often coincide
    // with prior load (drums_chunk_001.wav etc), and create_audio_clip won't
    // overwrite a clip already at the same start_time.
    var wiped = _alClearStemfgClips(trackIdx, manifestDir);
    if (wiped > 0) {
        _alStatus("stem " + stemName + " → wiped " + wiped + " prior clip(s)");
    }

    var chunks = (stemBlock && stemBlock.chunks) ? stemBlock.chunks : [];
    var created = 0;
    var shift = Number(shiftBeats) || 0;

    for (var i = 0; i < chunks.length; i++) {
        var ch = chunks[i];
        if (!ch || !ch.file) continue;

        var absWav = _alJoin(manifestDir, ch.file);
        var bars = (ch.bars != null) ? Number(ch.bars) : 4;
        // Prefer explicit `start_bar` (set by the chunks[]-shape adapter from
        // each chunk's `bar_position`). The sequential `i * bars` fallback only
        // works when every chunk has the same length — the new-shape adapter
        // carries per-chunk positions, so honor them when present.
        var startBar = (ch.start_bar != null && isFinite(Number(ch.start_bar)))
            ? Number(ch.start_bar) : (i * bars);
        var startBeat = startBar * beatsPerBar + shift;
        // Ableton refuses negative start_time; clamp to 0. Note: this
        // clips off the leading portion of any intro chunk that would
        // have hung off the left edge. User-visible result: a partial
        // intro chunk at the very start of the timeline.
        if (startBeat < 0) startBeat = 0;
        // Markers stay in SECONDS — the configurer disables warping, which
        // is the unit Live uses for unwarped clip markers/loop boundaries.
        var loopStartSec = Number(ch.loop_start_sec) || 0;
        var loopEndSec = Number(ch.loop_end_sec) || 0;
        var lengthBeats = bars * beatsPerBar;

        // Sanity: loop_end must be > loop_start. If the manifest is malformed
        // fall back to [0, total_sec] so the clip still plays.
        if (loopEndSec <= loopStartSec) {
            _alStatus("malformed loop region for " + stemName + " chunk "
                + (i + 1) + "; falling back to full clip");
            loopStartSec = 0;
            loopEndSec = Number(ch.total_sec) || (60 * lengthBeats / bpm);
        }

        var clipIdx = _alCreateAndConfigureClip(
            trackIdx, absWav, startBeat, lengthBeats,
            loopStartSec, loopEndSec, bpm
        );
        if (clipIdx >= 0) created++;
    }

    return { ok: created > 0, clips_created: created };
}

// Adapt the flat `chunks[]` arrangement-manifest shape (real forges + the
// sample-forge fixture) into the legacy `stems{}` nested shape this loader
// was built for. The flat shape carries per-chunk `stem`, `bar_position`,
// `duration_bars`, `duration_sec`, and `audio_path`; we fan those out into
// per-stem chunks{} arrays without losing positional info. Field-name
// mapping:
//   audio_path  → file        (relative or absolute, _alJoin handles both)
//   duration_bars → bars
//   duration_sec  → total_sec (drives the loop-end fallback in _alLoadStem)
//   bar_position  → start_bar (honored by _alLoadStem instead of sequential
//                              i * bars positioning — important when chunks
//                              are different lengths or sparse).
//
// Returns the adapted stems{} dict (empty if no convertible chunks found).
// Pure function: callers responsible for status emission.
function _alAdaptChunksToStems(chunks) {
    var adapted = {};
    if (!Array.isArray(chunks)) return adapted;
    for (var ci = 0; ci < chunks.length; ci++) {
        var c = chunks[ci];
        if (!c || !c.stem || !c.audio_path) continue;
        var stemKey = String(c.stem);
        if (!adapted[stemKey]) adapted[stemKey] = { chunks: [] };
        adapted[stemKey].chunks.push({
            file: String(c.audio_path),
            bars: (c.duration_bars != null) ? Number(c.duration_bars) : 4,
            total_sec: Number(c.duration_sec) || 0,
            start_bar: (c.bar_position != null && isFinite(Number(c.bar_position)))
                ? Number(c.bar_position) : null
        });
    }
    return adapted;
}

function runArrangementLoad(manifestPath, shiftBeats) {
    // Public entry point. Reads `manifestPath`, then walks each stem block
    // creating arrangement-view audio clips with proper loop regions.
    //
    // shiftBeats (optional, default 0): translate every chunk's start_time
    // by this many beats. Used by sf_locator_anchor's ANCH button to slide
    // the whole arrangement so musical bar 1 lands at the user's locator,
    // without re-cutting source audio.
    //
    // Returns true on success (every stem loaded at least one clip), false
    // otherwise. Either way, status is logged to ~/stemforge/logs/sf_debug.log
    // and to the Max console.
    if (!manifestPath || String(manifestPath).length === 0) {
        _alStatus("runArrangementLoad: missing manifestPath");
        return false;
    }
    var path = _alExpandTilde(String(manifestPath));
    var shift = Number(shiftBeats) || 0;

    var raw = _alReadFile(path);
    if (raw == null) return false;
    var manifest;
    try { manifest = JSON.parse(raw); }
    catch (e) {
        _alStatus("manifest parse error: " + e);
        return false;
    }

    var bpm = Number(manifest.bpm) || 120.0;
    var beatsPerBar = Number(manifest.beats_per_bar) || 4;
    var stems = manifest.stems || {};
    var manifestDir = _alDirname(path);

    // New-shape manifests (auto-curation forge + sample-forge fixture) carry
    // flat `chunks[]` with no `stems{}` nested object. Adapt before walking.
    // Without this, `for (var stemName in stems)` is a no-op → 0 clips →
    // `runArrangementLoad` returns false → device emits "Arrangement load
    // failed" with no diagnostic. Same class of bug as the LOAD FORGE
    // clips→stems adapter in stemforge_loader.v0.js. Caught 2026-05-15.
    if ((!stems || Object.keys(stems).length === 0)
            && Array.isArray(manifest.chunks)) {
        stems = _alAdaptChunksToStems(manifest.chunks);
        _alStatus("arrangement: adapted " + manifest.chunks.length
            + " chunks → " + Object.keys(stems).length + " stems (chunks[] shape)");
    }

    // Match Live's project tempo to the manifest tempo. The chunks are
    // pre-rendered at manifest bpm and clips are warped to it; if the
    // project tempo differs, audio is time-stretched and bar boundaries
    // drift. Setting tempo before clip creation keeps everything aligned.
    if (bpm > 0 && isFinite(bpm)) {
        try { new LiveAPI("live_set").set("tempo", bpm); } catch (_) {}
        _alStatus("project tempo → " + bpm + " BPM");
    }

    var totalCreated = 0;
    var anyOk = false;
    for (var stemName in stems) {
        if (!Object.prototype.hasOwnProperty.call(stems, stemName)) continue;
        var res = _alLoadStem(stemName, stems[stemName], manifestDir, bpm,
            beatsPerBar, shift);
        if (res.ok) anyOk = true;
        totalCreated += res.clips_created;
    }
    _alStatus("loaded " + totalCreated + " clips from " + path
        + " (bpm=" + bpm + ", beats_per_bar=" + beatsPerBar
        + (shift !== 0 ? ", shift=" + shift.toFixed(2) + " beats" : "") + ")");
    return anyOk;
}

// ── CommonJS shim — mirrors the reader's test export so the Node-vm sandbox
// in tests/js_mocks/ can drive these functions directly. Max's classic [js]
// ignores `module` so this is a no-op at runtime in the device. ───────────

if (typeof module !== "undefined" && module.exports) {
    module.exports.__test__ = {
        runArrangementLoad: runArrangementLoad,
        _alJoin: _alJoin,
        _alDirname: _alDirname,
        _alSecToBeats: _alSecToBeats,
        _alExpandTilde: _alExpandTilde,
        _alAdaptChunksToStems: _alAdaptChunksToStems,
        _alFindTrackForStem: _alFindTrackForStem,
        _AL_STEM_ALIASES: _AL_STEM_ALIASES
    };
}
