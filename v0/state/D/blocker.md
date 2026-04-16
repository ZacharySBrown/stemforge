# Track D — Blocker: missing `v0/assets/skeleton.als`

**Date:** 2026-04-16 (refreshed for v0 ship W3)
**Status:** Blocked on human step.
**Blocking deliverable:** `v0/build/StemForge.als`
**Handoff issue:** https://github.com/ZacharySBrown/stemforge/issues/12
(stays OPEN until zak runs the capture step)

## Summary

Blocked on human step; see
[`docs/skeleton-als-capture.md`](../../../docs/skeleton-als-capture.md)
for the exact Ableton Live 12.1.x capture procedure and post-capture
follow-up commands.

## Why an agent can't do this

`.als` is gzipped XML but only Ableton Live writes the XML correctly.
We will not hand-roll the XML (see `v0/assets/README.md`). Therefore
`skeleton.als` must be saved by a human running Live 12.1.x once.

## What Track D delivered autonomously

Builder, tests (30/30 pass against synthetic fixture), device
fragments, VST3 lookup, and README are all committed. Only
`v0/build/StemForge.als` remains, and it depends on `skeleton.als`.

## Unblock path

Follow [`docs/skeleton-als-capture.md`](../../../docs/skeleton-als-capture.md):

1. Save `v0/assets/skeleton.als` from Ableton Live 12.1.x (~5 min).
2. `uv run python v0/src/als-builder/builder.py` to emit
   `v0/build/StemForge.als`.
3. `uv run pytest v0/src/als-builder/tests/` to confirm.
4. Optional: rebuild the `.pkg` for v0.1 so the template ships.

The v0 pkg ship is **not** gated on this — `build-pkg.sh` skips `.als`
gracefully, per `docs/v0-ship-spec.md` §1.
