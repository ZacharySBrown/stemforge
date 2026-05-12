# EP-133: delete tracks/pads from a project via CLI

**Status:** Open — captured 2026-05-12. User-flagged.

## Why

Today the EP-133 deck pipeline can only **write** projects: `build-deck` produces a `.ppak` that overwrites whatever's in the target project slot on the device. There's no way to:

- Delete a single pad's sample without rebuilding the whole project
- Clear a group (A/B/C/D)
- Remove a track/pad from a deck spec partway through iteration
- Selectively re-bounce only one row of a deck

This matters for iterative deck work: if you commit 12 vocals on group A then realize pad 7 is the wrong take, you currently rebuild and re-upload the whole project.

## What to investigate

- `ppak_writer` produces a TAR per project. Can we synthesize a "delete this slot" partial update (TAR diff) the Sample Tool accepts? Probably no — Sample Tool reads whole projects.
- The hardware path via SysEx (memory: [`project_ep133_sysex_upload.md`]) supports per-slot writes (slot 1..255 confirmed). Per-slot **delete** via SysEx — is there a verb for it, or does write-empty-buffer suffice?
- The on-device UI clears pads via long-press + delete. Does that route through SysEx (capturable by sniffing) or stay device-internal?

## Where to look

- `stemforge/exporters/ep133/ppak_writer.py` — TAR-pack path
- `stemforge/exporters/ep133/sysex.py` (if exists) — per-slot upload primitives
- Phones24 project-archive parser (referenced in [`project_ep133_archive_roundtrip_todo.md`]) — could inform inverse "delete" operations
- Memory: [`project_ep133_protocol_findings.md`], [`feedback_ep133_emit_vs_accept.md`]

## Done when

A CLI command (e.g. `stemforge ep133 clear-pad <project-slot> <group> <pad>`) clears a single pad's sample slot on a live-connected device without overwriting the rest of the project.

Out of scope for this issue: in-place edit of `.ppak` files on disk (round-trip is a separate longstanding TODO).
