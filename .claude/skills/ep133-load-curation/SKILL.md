---
name: ep133-load-curation
description: Load a whole curation onto an EP-133 K.O. II over USB-MIDI SysEx — upload every pad's WAV and assign the pads — bypassing the TE Sample Tool .ppak import (which livelocks). Use when the user asks to load/push a curation or deck to the EP-133, or to re-assign pad play modes (e.g. "load this onto the EP-133", "send the kit to the K.O. II", "switch the pads to key mode"). Wraps tools/ep133_load_curation.py; dry-run-then-confirm.
allowed-tools: Bash(uv run:*), Bash(uv run --directory:*), Bash(ls:*), Bash(cat:*), Read
---

# ep133-load-curation — load a curation to the EP-133 over SysEx

Wraps `tools/ep133_load_curation.py`. It uploads each pad's WAV to an EP-133
library slot and assigns the pads, directly over USB-MIDI SysEx — the
reliable path. (TE Sample Tool's `.ppak` project import livelocks in device
filesystem enumeration; this skill sidesteps it entirely.)

## Prerequisites

- **Deps:** the `ep133` extra (mido + python-rtmidi). If `run_load` raises
  `ImportError`, run `./scripts/setup.sh` (the `all` extra covers it).
- **Device:** EP-133 connected over USB. Power-cycle it first if it's been
  through failed loads — a wedged file session causes hangs.
- **Input:** a `*.projectspec.json` — emitted by `stemforge build-deck`
  next to its `.ppak`. If the user only has a curation, build the deck
  first (`build-deck`) so the spec exists.

## How to invoke

```bash
uv run --directory /Users/zak/zacharysbrown/stemforge \
  python tools/ep133_load_curation.py <projectspec.json> [options]
```

| Option | Use |
|--------|-----|
| `--project N` | target project slot 1–9 (default 1) |
| `--playmode key` | gated playback — pad plays while held, stops on release. Also `oneshot` (default) / `legato`. |
| `--assign-only` | skip the WAV upload, just re-assign pads — for changing play mode / params on already-loaded samples (seconds, not minutes) |
| `--dry-run` | print the plan, no MIDI I/O |
| `--start-slot N` | library-slot base for group A (default 700) |

## Dry-run-then-confirm

This **writes to hardware** — it overwrites the target project's pads.
**Always `--dry-run` first**, show the plan, and confirm before the real
run, unless the user already said *"just do it"*.

```bash
uv run --directory /Users/zak/zacharysbrown/stemforge \
  python tools/ep133_load_curation.py "$SPEC" --project 1 --dry-run
```

The dry-run prints the full pad table (group, pad, slot, BPM, mode, WAV)
and flags any missing files. Surface it, then on confirm drop `--dry-run`.

## Timing — set expectations

- **Full load** ≈ 20–25 s per sample (chunked PCM over SysEx) — a 36-pad
  curation is ~15 min. Run it in the background and report progress.
- **`--assign-only`** ≈ seconds (no PCM transfer). Use it whenever the
  samples are already on the device and only params change.

## Common requests

| User says | Command |
|-----------|---------|
| "load the kit onto the EP-133" | `… "$SPEC" --project 1` (dry-run first) |
| "...in key mode" / "stop on release" | add `--playmode key` |
| "switch the pads to key mode" (already loaded) | `… "$SPEC" --assign-only --playmode key` |
| "put it in project 3" | `--project 3` |

## After loading

The process can hang briefly in MIDI-port teardown *after* all work is
done — if it stalls at the end with every pad reported done, the device
got everything; the hang is harmless Python cleanup. Confirm on the device.

Report the result: `Loaded N/36 pads to project P<N>`, or the failing pad
if `ImportError` (deps) / a WAV was missing.

## Note — what this loads

Samples + per-pad assignment (playmode, time mode, source BPM). It does
**not** write step-sequencer patterns or scenes — those live only in the
`.ppak` project tar. For getting loops onto pads to play, this is complete.
