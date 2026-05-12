# EP-133: delete tracks/pads from a project via CLI

**Status:** Implemented — needs hardware validation (2026-05-12). Branch `feat/cli-time-sig-and-ep133-clear-pad`.

A new `stemforge ep133-clear-pad PROJECT_SLOT PAD [--dry-run]` CLI command clears a single pad's sample assignment over USB-MIDI SysEx, without touching the rest of the project. PAD accepts both `A1`..`D12` letter form and numeric `1`..`48`.

**Strategy that worked:** reuse the existing, byte-tested pad-assign primitive (`build_assign_pad`) with `slot=0` — the device's unassigned-sample sentinel. On the wire this is `FILE_METADATA_SET` of `{"sym":0}` to the pad's fileId. No new SysEx opcode, no probing of unmapped fileIds (avoiding the wedge risk documented in agent memory `feedback_ep133_probing_safety`).

**What was NOT tried** (deferred):
- Writing an empty WAV buffer to the underlying slot (the brief's plan-C fallback). Skipped because plan A above is sufficient for the "remove pad from project" use case and is built on a well-tested wire path.
- Clearing the pad's playback parameters (envelope, time mode, amplitude, etc.). The clear today removes only the slot binding — those fields stay at whatever the pad was previously configured with. Could be added later if needed.

**Hardware validation pending:** dry-run byte structure is regression-tested (payload + frame hex). What needs checking on a connected EP-133:
1. Send `stemforge ep133-clear-pad <slot> A1` against a project where pad A1 currently has an assigned sample. Confirm the pad goes silent / shows as unassigned in the device UI.
2. Confirm the rest of the project (other pads, songs, patterns) is untouched.
3. Confirm the device's project archive round-trip (read back via SysEx) shows `{"sym":0}` at the pad's fileId.

Out of scope (still TODO):
- `--all-slots` / multi-pad clear (deferred behind the future-flag note in the CLI docstring).
- In-place `.ppak` editing on disk — separate longstanding round-trip TODO.

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
