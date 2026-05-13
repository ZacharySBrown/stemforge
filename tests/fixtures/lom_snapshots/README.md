# LOM Snapshots

JSON dumps of the Ableton Live Object Model (LOM) state at specific
moments. Used to drive `tools/test-harness/max-stub.js` against
device-JS tests without requiring Live to be running.

This is the breakthrough that lets device-JS development move into the
test loop (spec §7.5).

## Schema

```jsonc
{
  "_description": "Human-readable note about what this snapshot captures.",
  "live_set": {
    "tracks": [
      {
        "name": "FORGE/my-track/drum",     // LOM 'name' property
        "track_index": 0,
        "clip_slots": [
          {
            "clip": {                       // null on empty slots
              "name": "drum-bar0-4",
              "file_path": "/abs/path/to/clip.wav",
              "warp_bpm": 138.0,
              "loop_start": 0,              // beats relative to clip start
              "loop_end": 4,
              "looping": 1
            }
          },
          { "clip": null }
        ]
      }
    ],
    "scenes": []
  }
}
```

`max-stub.js` walks paths like `new LiveAPI("live_set tracks 0 clip_slots 5 clip")`
against this tree. The path tokens are split on whitespace; integer
tokens become array indices and string tokens become object keys.

## Available snapshots

| File | Purpose |
|---|---|
| `empty-set.json` | Brand-new Live set, no tracks, no scenes. |
| `forge-loaded.json` | 4 `FORGE/my-track/*` tracks, each 16 clip slots, half populated. |
| `staging-empty.json` | STG-A through STG-D created, all 12 slots empty per track. |
| `staging-4-pads-stg-a.json` | STG-A through STG-D; STG-A populated A01-A04. |
| `staging-full-46-pads.json` | STG-A through STG-D, 46 pads spread (12/12/12/10). |

## Capturing a new snapshot from real Live (future)

When Phase 5's smoke-test infrastructure lands, snapshots will be
captured one-time via:

```bash
# Hypothetical — not implemented yet, lives in the Phase 5 ticket.
uv run sf-remote dump-lom --out tests/fixtures/lom_snapshots/my-new-snapshot.json
```

`sf-remote dump-lom` will walk Live via the existing UDP channel,
serialize the LOM tree into the schema above, and write the file.

For now, hand-author the JSON. Keep clip slot arrays the same length as
the real session-view height (16 for older versions, varies in Live 12);
nulls are cheap.

## Adding fields

When device JS starts reading a LOM property that isn't in the schema
above (e.g. `clip.loop_start_unit`, `track.has_audio_input`), add it to
every relevant snapshot AND document it in this README. The stub returns
`[]` for missing properties, so tests will hit `undefined` and signal
the gap loudly.

## Testing the schema

`tools/test-harness/max-stub.test.js` exercises every snapshot end-to-end.
If a snapshot is malformed, the harness tests fail.
