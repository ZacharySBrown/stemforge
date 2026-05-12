# Bounce writes empty stub manifest before populating it

**Status:** Open — captured 2026-05-12.

## Symptom

In `bounceTracks` the first thing that happens is a 217-byte stub manifest file gets written via the direct File API ("Strategy B"). The real session_tracks content only appears after the crop loop finishes (typically ~10-15 seconds later for a 46-clip deck).

A polling reader that checks `os.path.exists(manifest)` will return *true* immediately but read garbage. We hit this once during the breaks-n-beats1 build — the post-fire polling script saw the stub at 5s and almost proceeded to `deck-from-manifest` with no session_tracks.

## Workaround we used

Poll for **size > 5000 bytes** instead of just existence. Real manifests are 10-20 KB; the stub is 217 bytes.

## Better fixes

1. **Write to a temp path + atomic rename at the end.** `manifest.json.tmp` → `manifest.json` only after the COMMIT loop runs. Readers never see partial state. Standard pattern.

2. **Write the stub to a different filename** (e.g. `.bouncing-marker`) so the canonical manifest path is binary: either non-existent (no bounce yet) or fully populated (done).

3. **Add a `status: "in-progress"` field to the stub** that COMMIT clears. Readers check it. Stronger than file size since size could legitimately vary.

Option 1 is the cleanest — atomic rename is portable across platforms.

## Where to look

- `stemforge_loader.v0.js` — find "stub written via direct File API (Strategy B)" log line, work backwards to the writer.
- `_commitSessionTracks` — the post-bounce writer that fills in session_tracks.

## Done when

Polling for the deck manifest file's existence after `bounceTracks` is sufficient — readers don't need to also check size, mtime, or content shape.
