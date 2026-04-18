// stemforge_ndjson_parser.v0.js
// Classic Max [js] — parses NDJSON from [shell] stdout.
//
// Max's message system mangles JSON: quotes stripped, commas become list
// separators that insert "0" atoms between key:value pairs. Input arrives as:
//   {event:progress 0 message:decoding input 0 pct:2.0 0 phase:splitting}
// This parser handles that format.

inlets = 1;
outlets = 1;

function anything() {
    var atoms = arrayfromargs(messagename, arguments);
    var line = atoms.join(" ");

    if (!line || line.length < 2) return;

    var evt = parseMangled(line);
    if (!evt || !evt.event) {
        post("[stemforge] " + line.substring(0, 120) + "\n");
        return;
    }

    emitEvent(evt);
}

function parseMangled(line) {
    try {
        // Strip outer braces
        line = line.replace(/^\{/, "").replace(/\}$/, "").trim();

        // Split on " 0 " — Max inserts integer 0 between comma-separated atoms
        var parts = line.split(" 0 ");
        var obj = {};

        for (var i = 0; i < parts.length; i++) {
            var part = parts[i].trim();
            if (!part) continue;

            // Remove surrounding quotes
            if (part.charAt(0) === '"' && part.charAt(part.length - 1) === '"') {
                part = part.substring(1, part.length - 1);
            }

            // Split on FIRST colon only
            var colonIdx = part.indexOf(":");
            if (colonIdx < 0) continue;

            var key = part.substring(0, colonIdx).trim();
            var val = part.substring(colonIdx + 1).trim();

            // Clean up value
            if (val.charAt(0) === '"' && val.charAt(val.length - 1) === '"') {
                val = val.substring(1, val.length - 1);
            }

            // Try number conversion
            var num = Number(val);
            if (!isNaN(num) && val !== "" && val.indexOf("/") < 0) {
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

function bang() {
    outlet(0, "progress", 100, "done");
}
