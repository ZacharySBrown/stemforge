# EP-133 Pad Assignment — Capture Plan

Goal: get enough SysEx captures from the TE Sample Tool to reverse-engineer
the "assign pad to slot" and "switch project" protocol, the same way we
did for uploads. Fixtures drop into `tests/ep133/fixtures/pad/`.

## Setup

**Tool:** [SysEx Librarian](https://www.snoize.com/SysExLibrarian/) (free, Mac).
Or MIDIMonitor from the same author if you prefer live viewing.

1. Connect EP-133 via USB-C.
2. Open SysEx Librarian → *Record Many* → source = EP-133 output port.
3. Open the TE Sample Tool in Chrome (the working web app, the one that
   drops files via drag-drop).
4. Confirm the tool sees the device. You should see the project grid.

**Important:** Each capture should be of exactly ONE action with a clean
start and clean stop, so the fixture file only contains the bytes we care
about. After each operation, click *Stop Recording* → *Save*.

## Prerequisites

You need at least one sample already in a library slot. The kick upload we
just did (slot 1) is perfect. If that's gone, just re-run:

```
uv run stemforge ep133 upload <any_wav> --slot 1
```

## Captures to record

Name each file exactly as shown — the fixture tests will look for these
paths. Save to `tests/ep133/fixtures/pad/`.

### Tier 1: isolate each variable

These five captures triangulate the encoding by changing one thing at a time.

| # | File | Action in Sample Tool |
|---|------|------------------------|
| 1 | `assign_p01_A01_to_slot001.syx` | Project 1, assign pad **A1** to library slot **1** |
| 2 | `assign_p01_A02_to_slot001.syx` | Project 1, assign pad **A2** to slot **1** — same slot, different pad |
| 3 | `assign_p01_B01_to_slot001.syx` | Project 1, assign pad **B1** to slot **1** — same slot, different group |
| 4 | `assign_p02_A01_to_slot001.syx` | Project **2**, assign pad **A1** to slot **1** — same pad, different project |
| 5 | `assign_p01_A01_to_slot002.syx` | Project 1, assign pad **A1** to slot **2** — same pad/project, different slot |

Between captures #4 and #5 you may need to upload a second sample so slot 2
exists. Any short WAV is fine:
```
uv run stemforge ep133 upload <any_wav> --slot 2
```

### Tier 2: unassign + switch

| # | File | Action |
|---|------|--------|
| 6 | `unassign_p01_A01.syx` | Project 1, clear/remove the assignment on pad A1 |
| 7 | `switch_to_p02.syx` | Change the Sample Tool's project selector from 1 → 2 |
| 8 | `switch_to_p01.syx` | Change it back from 2 → 1 |

Captures #7 and #8 may turn out to be empty (the tool might switch projects
locally without sending anything). That's useful information — capture them
anyway.

### Tier 3 (optional, if easy): pad params

If the Sample Tool lets you edit a pad's volume / playmode / envelope and
you can do it without extra clicks, capture one:

| # | File | Action |
|---|------|--------|
| 9 | `set_pad_p01_A01_volume.syx` | Project 1, pad A1, change volume to any non-default value |

## After capture

Just tell me the files are in place and I'll:
1. Decode each capture (same method as the upload captures).
2. Figure out how project / group / pad / slot are packed into bytes.
3. Add a `build_pad_assign(project, group, pad, slot)` builder to
   `payloads.py`, plus `build_project_switch(project)` if there's something
   to switch.
4. Add byte-identical fixture tests — same gate that proved upload worked.
5. Extend `EP133Client` with `assign_pad(project, group, pad, slot)` and
   `switch_project(n)`, and wire the existing `EP133Mapping` YAML pipeline
   through to the device.

Expected turnaround once fixtures are in place: ~1-2 hours.
