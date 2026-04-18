// stemforge_ndjson_parser.v0.js
// Classic Max [js] object — parses NDJSON from [shell] stdout.
//
// [shell] mangles JSON through Max's message parser: quotes are stripped,
// commas become list separators, and keys become key:value atoms. This parser
// handles BOTH valid JSON (from file) and Max-mangled format (from [shell]).
//
// Inlet 0: messages from [shell] outlet 0 (mangled JSON atoms)
// Outlet 0: parsed events as Max messages

inlets = 1;
outlets = 1;

function anything() {
    // Rejoin all atoms into a single string
    var atoms = arrayfromargs(messagename, arguments);
    var line = atoms.join(" ");

    if (!line || line.length < 2) return;

    var evt = null;

    // Try standard JSON parse first (works if input is clean)
    if (line.charAt(0) === "{") {
        try {
            evt = JSON.parse(line);
        } catch (e) {
            // Max-mangled format: {key:value , key:value , ...}
            evt = parseMangled(line);
        }
    } else {
        // Might be a mangled line without leading brace (Max ate it)
        evt = parseMangled("{" + line + "}");
    }

    if (!evt || !evt.event) {
        // Non-event line — log it
        post("[stemforge] " + line.substring(0, 120) + "\n");
        return;
    }

    emitEvent(evt);
}

function parseMangled(line) {
    // Max-mangled JSON looks like:
    //   {event:progress , "message:segment 1/6", pct:45.0, phase:splitting}
    //
    // Rules:
    // - Outer braces wrap the content
    // - Key:value pairs separated by commas (with optional spaces)
    // - Quoted strings may contain colons (e.g. "message:some text")
    // - Values can be strings, numbers, or nested
    try {
        // Strip outer braces
        var inner = line.replace(/^\{/, "").replace(/\}$/, "").trim();

        // Split on comma-space boundaries, being careful with quoted strings
        var pairs = splitPairs(inner);
        var obj = {};

        for (var i = 0; i < pairs.length; i++) {
            var pair = pairs[i].trim();
            if (!pair) continue;

            // Remove surrounding quotes if present
            if (pair.charAt(0) === '"' && pair.charAt(pair.length - 1) === '"') {
                pair = pair.substring(1, pair.length - 1);
            }

            // Split on first colon only
            var colonIdx = pair.indexOf(":");
            if (colonIdx < 0) continue;

            var key = pair.substring(0, colonIdx).trim();
            var val = pair.substring(colonIdx + 1).trim();

            // Remove quotes from value
            if (val.charAt(0) === '"' && val.charAt(val.length - 1) === '"') {
                val = val.substring(1, val.length - 1);
            }

            // Try to parse as number
            var num = Number(val);
            if (!isNaN(num) && val !== "") {
                obj[key] = num;
            } else {
                obj[key] = val;
            }
        }

        return obj;
    } catch (e) {
        post("[stemforge parse error] " + e + "\n");
        return null;
    }
}

function splitPairs(s) {
    // Split on ", " or " , " but not inside quotes
    var parts = [];
    var current = "";
    var inQuote = false;

    for (var i = 0; i < s.length; i++) {
        var ch = s.charAt(i);
        if (ch === '"') {
            inQuote = !inQuote;
            current += ch;
        } else if (ch === "," && !inQuote) {
            parts.push(current.trim());
            current = "";
        } else {
            current += ch;
        }
    }
    if (current.trim()) {
        parts.push(current.trim());
    }
    return parts;
}

function emitEvent(evt) {
    switch (evt.event) {
        case "started":
            outlet(0, "progress", 0, "starting");
            break;
        case "progress":
            outlet(0, "progress", evt.pct || 0, evt.phase || evt.message || "");
            break;
        case "stem":
            outlet(0, "stem", evt.name || "", evt.path || "", evt.size_bytes || 0);
            break;
        case "bpm":
            outlet(0, "bpm", evt.bpm || 0, evt.beat_count || 0);
            break;
        case "slice_dir":
            outlet(0, "slice_dir", evt.stem || "", evt.dir || "", evt.count || 0);
            break;
        case "complete":
            outlet(0, "complete", evt.manifest || "", evt.bpm || 0, evt.stem_count || 0);
            break;
        case "error":
            outlet(0, "error", evt.phase || "", evt.message || "");
            break;
        default:
            post("[stemforge] unknown event: " + evt.event + "\n");
    }
}

// Handle bang (e.g. from [shell] outlet 1 = process done)
function bang() {
    outlet(0, "progress", 100, "done");
}
