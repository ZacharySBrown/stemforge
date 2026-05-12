# Root `log` text file blocks `log/` directory patterns

**Status:** Open — captured 2026-05-12.

## Symptom

Scripts that try `mkdir -p log` + write to `log/<name>.log` fail because `/Users/zak/zacharysbrown/stemforge/log` is an existing **file** (118 lines, UTF-8 text — looks like EP-133 SysEx debug output from an earlier session).

We hit this when writing `tools/batch_grooves.sh` and worked around by sending logs to `/tmp/batch_grooves.log` instead.

## What's in the file

```
================================================================================
PHASE 1: SLOT + PAD JSON METADATA (via SysEx FILE_METADATA_GET)
================================================================================

--- Pad C/p01 → slot 740  (def f2) ---
```

That's clearly an EP-133 protocol-investigation log — useful as a one-time capture, NOT something that should be persistent at the repo root with the bare name `log`.

## Fix

1. **Move** to `docs/ep133-song-triage/` (or wherever the protocol investigations live) with a more descriptive name (`ep133-pad-slot-metadata-probe.txt`).
2. **Delete** if it's a one-off that's already been mined for its findings.
3. **Add `log/` to `.gitignore`** so future scripts can create a logs directory cleanly.

## Done when

`/Users/zak/zacharysbrown/stemforge/log` doesn't exist at the repo root, and `log/` is gitignored.
