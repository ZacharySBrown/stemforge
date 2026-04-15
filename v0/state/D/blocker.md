# Track D — Blocker: missing `v0/assets/skeleton.als`

**Date:** 2026-04-14
**Branch:** `feat/v0-D-als-template`
**Blocking deliverable:** `v0/build/StemForge.als`

## Summary

Track D's builder, tests, device fragments, VST3 lookup, and README are
all complete and committed. The only outstanding deliverable is the
build artifact `v0/build/StemForge.als`, which cannot be produced
autonomously because it requires a one-time human-created asset that
this agent does not have access to.

## What's needed

A single file: `v0/assets/skeleton.als`.

This is an empty Ableton Live 12 set saved by a human opening Ableton
once (see `v0/assets/README.md` for the exact steps — it takes ~30
seconds). It is committed to the repo and re-used forever; the user
never touches it again after this one-time step.

## Why I can't create it myself

- The agent does not have Ableton Live available in this environment.
- The brief (`v0/tracks/D-als-template.md` §"Produce" and the dispatch
  brief §"Approach") explicitly instructs: *"If this file doesn't exist
  AND you don't have Ableton to create it: write `v0/state/D/blocker.md`
  explaining the asset dependency and STOP. Do not fabricate."*
- Fabricating a hand-written XML would very likely drift from Live 12's
  actual schema and cause silent track drops or open-failures (see
  `v0/assets/README.md` §"Why not commit a hand-written XML?").

## What I've tried / verified

I did *not* attempt to synthesize a skeleton. I did verify the builder
works against a synthetic Live-shaped XML skeleton used by the test
suite — 30/30 tests pass, covering:

- Gzipped XML validity (stdlib parseable)
- 7 tracks emitted (6 audio + 1 midi, matching `tracks.yaml`)
- Track names match `tracks.yaml`
- Color hex values map to Live palette indices (nearest-neighbor)
- Audio vs MIDI track types match `tracks.yaml`
- Stock device params propagate (e.g. Compressor threshold=-18 for drums_raw)
- Set-wide Id uniqueness after renumbering
- Simpler slice mode set for the beat_chop track
- Missing skeleton raises `FileNotFoundError` (this exact check path)

## Manual steps for the human to unblock

1. On a Mac with Ableton Live 12.1.x installed, launch Live.
2. File → New Live Set. Do not modify anything.
3. File → Save Live Set As… → save as
   `v0/assets/skeleton.als` at the repo root.
4. Quit Live.
5. `git add v0/assets/skeleton.als && git commit -m "assets: skeleton.als from Live 12.1.x"`
6. From the repo root, run:
       `uv run python v0/src/als-builder/builder.py`
   This should write `v0/build/StemForge.als` with exit code 0.
7. Re-run the tests:
       `uv run pytest v0/src/als-builder/tests/`
8. Open `v0/build/StemForge.als` in Live 12 to visually verify (plugin-
   missing warnings for SoundToys/XLN are expected unless those are
   installed).

## Recommendation

Escalate to the human (user `zak@raindog.ai`) to run the 30-second
skeleton-save step, then re-invoke Track D (or simply run the builder
entry point — no re-dispatch needed).
