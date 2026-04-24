# EP-133 Pad Assign — Capture Progress

Paste MIDI Monitor "To EP-133" log output under each capture heading
below. Each code block is where the hex goes. When all four are filled in,
ping Claude and it'll decode + implement.

---

## Setup (one-time, already done)

MIDI Monitor + spy driver installed. Sources panel:
- ✅ **Spy on output to destinations → EP-133** (this is what we want)
- ❌ MIDI sources → EP-133 (unchecked — skips inbound waveform noise)
- Filter: SysEx only

## Capture flow (for each)

1. Set up the target in the Sample Tool (project, group) **before** recording
2. MIDI Monitor: **Clear** log (⌘K)
3. Sample Tool: drag a sample to the target pad
4. Select all "To EP-133" rows → **Edit → Copy**
5. Paste into the code block under the matching heading below

---

## Key finding so far

**Pad assignment is a single SysEx message:**

```
cmd=5, payload: 07 01 [padFileId:u16 BE] {"sym":<slot>}\0
```

where `07 01` is the `TE_SYSEX_FILE_METADATA` SET sub-command (the write
counterpart to phones24's `07 02` read). Everything else in a capture is
the Sample Tool reading state to refresh its UI — we can ignore it.

The three captures below isolate how `(project, group, pad)` map to
`padFileId`.

---

## Capture 1 — P1, group A, pad "." → slot 1 ✅ DONE

**Decoded:**
- Target `padFileId` = `0x0C8A` = **3210**
- Wire payload: `07 01 0C 8A 7B 22 73 79 6D 22 3A 31 7D 00`
- Hypothesis: within P1 group A, pad-0 = 3200, pad-. = 3210, ENTER = 3211
  (`3200 + N` where N is the numeric label, `.` = 10, ENTER = 11)

```
F0 00 20 76 33 40 66 67 05 08 07 01 0C 0A 7B 22 73 00 79 6D 22 3A 31 7D 00 F7
```

---

## Capture 2 — P1, group A, pad "1" → slot 1

**Setup:** make sure Sample Tool is on **project 1**, showing **group A**.
Drag a sample onto the pad labeled **"1"** (row 3, leftmost).

**Expected** (if hypothesis holds): padFileId = 3201 = `0x0C 81`.

Paste the "To EP-133" log rows here:

```
09:44:34.442	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 66 68 05 08 07 02 07 50 00 00 F7
09:44:34.452	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 66 69 05 04 0B 0B 38 F7
09:44:34.452	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 66 6A 05 00 07 02 0C 1C 00 00 F7
09:44:34.452	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 66 6B 05 04 0B 0C 00 F7
09:44:34.452	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 66 6C 05 08 07 02 0C 00 00 00 F7
09:44:34.452	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 66 6D 05 08 07 01 0C 00 7B 22 61 00 63 74 69 76 65 22 3A 00 33 32 30 36 7D 00 F7
09:44:34.455	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 66 6E 05 04 0B 00 5A F7
09:44:34.456	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 66 6F 05 08 07 02 00 5A 00 00 F7
09:44:34.464	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 66 70 05 08 07 02 00 5A 00 01 F7
09:44:34.465	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 66 71 05 08 07 02 07 50 00 00 F7
09:44:34.466	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 66 72 05 08 03 00 00 5A 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 16 07 50 F7
09:44:34.475	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 73 05 00 03 01 00 00 F7
09:44:34.477	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 74 05 00 03 01 00 01 F7
09:44:34.480	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 75 05 00 03 01 00 02 F7
09:44:34.483	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 76 05 00 03 01 00 03 F7
09:44:34.486	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 77 05 00 03 01 00 04 F7
09:44:34.488	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 78 05 00 03 01 00 05 F7
09:44:34.491	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 79 05 00 03 01 00 06 F7
09:44:34.493	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 7A 05 00 03 01 00 07 F7
09:44:34.495	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 7B 05 00 03 01 00 08 F7
09:44:34.498	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 7C 05 00 03 01 00 09 F7
09:44:34.501	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 7D 05 00 03 01 00 0A F7
09:44:34.503	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 7E 05 00 03 01 00 0B F7
09:44:34.506	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 66 7F 05 00 03 01 00 0C F7
09:44:34.508	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 00 05 00 03 01 00 0D F7
09:44:34.510	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 01 05 00 03 01 00 0E F7
09:44:34.513	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 02 05 00 03 01 00 0F F7
09:44:34.516	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 03 05 00 03 01 00 10 F7
09:44:34.518	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 04 05 00 03 01 00 11 F7
09:44:34.521	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 05 05 00 03 01 00 12 F7
09:44:34.523	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 06 05 00 03 01 00 13 F7
09:44:34.525	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 07 05 00 03 01 00 14 F7
09:44:34.528	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 08 05 00 03 01 00 15 F7
09:44:34.531	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 09 05 00 03 01 00 16 F7
09:44:34.533	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 0A 05 00 03 01 00 17 F7
09:44:34.536	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 0B 05 00 03 01 00 18 F7
09:44:34.539	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 67 0C 05 04 0B 0B 38 F7
09:44:34.542	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 0D 05 08 07 02 07 50 00 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 0E 05 00 07 02 0C 1C 00 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 67 0F 05 04 0B 0B 38 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 67 10 05 04 0B 0C 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 11 05 00 07 02 0C 1C 00 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 12 05 08 07 02 0C 00 00 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 67 13 05 04 0B 0C 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 67 14 05 08 07 01 0C 00 7B 22 61 00 63 74 69 76 65 22 3A 00 33 32 30 35 7D 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 15 05 08 07 02 0C 00 00 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 67 16 05 04 0B 00 48 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 67 17 05 08 07 01 0C 00 7B 22 61 00 63 74 69 76 65 22 3A 00 33 32 30 37 7D 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 18 05 08 07 02 00 48 00 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 19 05 08 07 02 00 48 00 01 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 67 1A 05 00 0B 00 01 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 1B 05 00 07 02 00 01 00 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 67 1C 05 00 07 02 00 01 00 01 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 67 1D 05 00 03 00 00 01 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 28 07 50 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 1E 05 00 03 01 00 00 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 1F 05 00 03 01 00 01 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 20 05 00 03 01 00 02 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 21 05 00 03 01 00 03 F7
09:44:34.597	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 22 05 00 03 01 00 04 F7
09:44:34.598	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 23 05 00 03 01 00 05 F7
09:44:34.600	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 24 05 00 03 01 00 06 F7
09:44:34.602	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 25 05 00 03 01 00 07 F7
09:44:34.604	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 26 05 00 03 01 00 08 F7
09:44:34.607	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 27 05 00 03 01 00 09 F7
09:44:34.609	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 28 05 00 03 01 00 0A F7
09:44:34.611	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 29 05 00 03 01 00 0B F7
09:44:34.614	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 2A 05 00 03 01 00 0C F7
09:44:34.616	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 2B 05 00 03 01 00 0D F7
09:44:34.618	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 2C 05 00 03 01 00 0E F7
09:44:34.620	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 2D 05 00 03 01 00 0F F7
09:44:34.622	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 2E 05 00 03 01 00 10 F7
09:44:34.625	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 2F 05 00 03 01 00 11 F7
09:44:34.628	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 30 05 00 03 01 00 12 F7
09:44:34.630	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 31 05 00 03 01 00 13 F7
09:44:34.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 32 05 00 03 01 00 14 F7
09:44:34.634	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 33 05 00 03 01 00 15 F7
09:44:34.637	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 34 05 00 03 01 00 16 F7
09:44:34.639	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 35 05 00 03 01 00 17 F7
09:44:34.641	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 67 36 05 00 03 01 00 18 F7
09:44:35.161	To EP-133	SysEx		Teenage Engineering 26 bytes	F0 00 20 76 33 40 67 37 05 08 07 01 0C 07 7B 22 73 00 79 6D 22 3A 31 7D 00 F7
```

---

## Capture 3 — P1, group B, pad "." → slot 1

**Setup:** Sample Tool on **project 1**. Switch the visible group from A
to **B** before starting to record (that switch may generate traffic —
clear the log *after* the switch and *before* the drag).
Drag onto **B's** bottom-left pad (the "." position).

**Expected:** padFileId somewhere predictable — probably `3200 + 12 = 3212`
(`0x0C 8C`) if groups are 12 pads apart, or `3200 + 48 = 3248` if they
stride per-project. Diff tells us which.

```
09:45:49.406	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 48 05 08 07 02 07 50 00 00 F7
09:45:49.413	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 69 49 05 04 0B 0B 38 F7
09:45:49.413	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 4A 05 00 07 02 0C 1C 00 00 F7
09:45:49.413	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 69 4B 05 04 0B 0C 64 F7
09:45:49.413	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 4C 05 08 07 02 0C 64 00 00 F7
09:45:49.413	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 69 4D 05 08 07 01 0C 64 7B 22 61 00 63 74 69 76 65 22 3A 00 33 33 30 35 7D 00 F7
09:45:49.417	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 69 4E 05 04 0B 01 33 F7
09:45:49.419	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 4F 05 08 07 02 01 33 00 00 F7
09:45:49.427	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 50 05 08 07 02 01 33 00 01 F7
09:45:49.429	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 69 51 05 08 03 00 01 33 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 10 07 50 F7
09:45:49.436	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 52 05 00 03 01 00 00 F7
09:45:49.439	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 53 05 00 03 01 00 01 F7
09:45:49.441	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 54 05 00 03 01 00 02 F7
09:45:49.443	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 55 05 00 03 01 00 03 F7
09:45:49.446	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 56 05 00 03 01 00 04 F7
09:45:49.448	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 57 05 00 03 01 00 05 F7
09:45:49.450	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 58 05 00 03 01 00 06 F7
09:45:49.452	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 59 05 00 03 01 00 07 F7
09:45:49.454	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 5A 05 00 03 01 00 08 F7
09:45:49.456	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 5B 05 00 03 01 00 09 F7
09:45:49.459	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 5C 05 00 03 01 00 0A F7
09:45:49.461	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 5D 05 00 03 01 00 0B F7
09:45:49.463	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 5E 05 00 03 01 00 0C F7
09:45:49.466	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 5F 05 00 03 01 00 0D F7
09:45:49.468	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 60 05 00 03 01 00 0E F7
09:45:49.469	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 61 05 00 03 01 00 0F F7
09:45:49.471	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 62 05 00 03 01 00 10 F7
09:45:49.473	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 63 05 00 03 01 00 11 F7
09:45:49.476	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 64 05 00 03 01 00 12 F7
09:45:49.478	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 65 05 00 03 01 00 13 F7
09:45:49.480	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 66 05 00 03 01 00 14 F7
09:45:49.482	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 67 05 00 03 01 00 15 F7
09:45:49.484	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 68 05 00 03 01 00 16 F7
09:45:49.487	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 69 05 00 03 01 00 17 F7
09:45:49.488	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 6A 05 00 03 01 00 18 F7
09:45:49.572	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 6B 05 08 07 02 07 50 00 00 F7
09:45:49.572	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 69 6C 05 04 0B 0B 38 F7
09:45:49.573	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 6D 05 00 07 02 0C 1C 00 00 F7
09:45:49.574	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 69 6E 05 04 0B 0C 64 F7
09:45:49.576	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 6F 05 08 07 02 0C 64 00 00 F7
09:45:49.577	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 69 70 05 08 07 01 0C 64 7B 22 61 00 63 74 69 76 65 22 3A 00 33 33 30 38 7D 00 F7
09:45:49.581	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 69 71 05 04 0B 01 24 F7
09:45:49.582	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 72 05 08 07 02 01 24 00 00 F7
09:45:49.592	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 69 73 05 08 07 02 01 24 00 01 F7
09:45:49.594	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 69 74 05 08 03 00 01 24 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 2E 07 50 F7
09:45:49.602	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 75 05 00 03 01 00 00 F7
09:45:49.605	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 76 05 00 03 01 00 01 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 77 05 00 03 01 00 02 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 78 05 00 03 01 00 03 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 79 05 00 03 01 00 04 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 7A 05 00 03 01 00 05 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 7B 05 00 03 01 00 06 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 7C 05 00 03 01 00 07 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 7D 05 00 03 01 00 08 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 7E 05 00 03 01 00 09 F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 69 7F 05 00 03 01 00 0A F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 00 05 00 03 01 00 0B F7
09:45:49.633	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 01 05 00 03 01 00 0C F7
09:45:49.634	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 02 05 00 03 01 00 0D F7
09:45:49.637	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 03 05 00 03 01 00 0E F7
09:45:49.639	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 04 05 00 03 01 00 0F F7
09:45:49.642	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 05 05 00 03 01 00 10 F7
09:45:49.645	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 06 05 00 03 01 00 11 F7
09:45:49.648	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 07 05 00 03 01 00 12 F7
09:45:49.650	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 08 05 00 03 01 00 13 F7
09:45:49.653	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 09 05 00 03 01 00 14 F7
09:45:49.656	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 0A 05 00 03 01 00 15 F7
09:45:49.659	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 0B 05 00 03 01 00 16 F7
09:45:49.661	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 0C 05 00 03 01 00 17 F7
09:45:49.664	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 0D 05 00 03 01 00 18 F7
09:45:49.740	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6A 0E 05 08 07 02 07 50 00 00 F7
09:45:49.743	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6A 0F 05 04 0B 0B 38 F7
09:45:49.744	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6A 10 05 00 07 02 0C 1C 00 00 F7
09:45:49.745	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6A 11 05 04 0B 0C 64 F7
09:45:49.746	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6A 12 05 08 07 02 0C 64 00 00 F7
09:45:49.748	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 6A 13 05 08 07 01 0C 64 7B 22 61 00 63 74 69 76 65 22 3A 00 33 33 31 30 7D 00 F7
09:45:49.753	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6A 14 05 00 0B 00 07 F7
09:45:49.753	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6A 15 05 00 07 02 00 07 00 00 F7
09:45:49.762	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6A 16 05 00 07 02 00 07 00 01 F7
09:45:49.763	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 6A 17 05 00 03 00 00 07 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 04 07 50 F7
09:45:49.771	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 18 05 00 03 01 00 00 F7
09:45:49.774	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 19 05 00 03 01 00 01 F7
09:45:49.776	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 1A 05 00 03 01 00 02 F7
09:45:49.779	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 1B 05 00 03 01 00 03 F7
09:45:49.780	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 1C 05 00 03 01 00 04 F7
09:45:49.783	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 1D 05 00 03 01 00 05 F7
09:45:49.786	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 1E 05 00 03 01 00 06 F7
09:45:49.787	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 1F 05 00 03 01 00 07 F7
09:45:49.790	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 20 05 00 03 01 00 08 F7
09:45:49.792	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 21 05 00 03 01 00 09 F7
09:45:49.794	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 22 05 00 03 01 00 0A F7
09:45:49.796	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 23 05 00 03 01 00 0B F7
09:45:49.798	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 24 05 00 03 01 00 0C F7
09:45:49.800	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 25 05 00 03 01 00 0D F7
09:45:49.802	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 26 05 00 03 01 00 0E F7
09:45:49.805	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 27 05 00 03 01 00 0F F7
09:45:49.807	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 28 05 00 03 01 00 10 F7
09:45:49.809	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 29 05 00 03 01 00 11 F7
09:45:49.836	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 2A 05 00 03 01 00 12 F7
09:45:49.836	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 2B 05 00 03 01 00 13 F7
09:45:49.836	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 2C 05 00 03 01 00 14 F7
09:45:49.836	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 2D 05 00 03 01 00 15 F7
09:45:49.836	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 2E 05 00 03 01 00 16 F7
09:45:49.836	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 2F 05 00 03 01 00 17 F7
09:45:49.836	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 30 05 00 03 01 00 18 F7
09:45:50.196	To EP-133	SysEx		Teenage Engineering 26 bytes	F0 00 20 76 33 40 6A 31 05 08 07 01 0C 6E 7B 22 73 00 79 6D 22 3A 31 7D 00 F7
09:45:50.239	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6A 32 05 00 0B 00 01 F7
09:45:50.240	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6A 33 05 00 07 02 00 01 00 00 F7
09:45:50.249	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6A 34 05 00 07 02 00 01 00 01 F7
09:45:50.251	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 6A 35 05 00 03 00 00 01 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 28 07 50 F7
09:45:50.258	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 36 05 00 03 01 00 00 F7
09:45:50.260	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 37 05 00 03 01 00 01 F7
09:45:50.262	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 38 05 00 03 01 00 02 F7
09:45:50.265	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 39 05 00 03 01 00 03 F7
09:45:50.268	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 3A 05 00 03 01 00 04 F7
09:45:50.271	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 3B 05 00 03 01 00 05 F7
09:45:50.273	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 3C 05 00 03 01 00 06 F7
09:45:50.276	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 3D 05 00 03 01 00 07 F7
09:45:50.278	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 3E 05 00 03 01 00 08 F7
09:45:50.281	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 3F 05 00 03 01 00 09 F7
09:45:50.284	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 40 05 00 03 01 00 0A F7
09:45:50.287	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 41 05 00 03 01 00 0B F7
09:45:50.290	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 42 05 00 03 01 00 0C F7
09:45:50.292	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 43 05 00 03 01 00 0D F7
09:45:50.295	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 44 05 00 03 01 00 0E F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 45 05 00 03 01 00 0F F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 46 05 00 03 01 00 10 F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 47 05 00 03 01 00 11 F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 48 05 00 03 01 00 12 F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 49 05 00 03 01 00 13 F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 4A 05 00 03 01 00 14 F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 4B 05 00 03 01 00 15 F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 4C 05 00 03 01 00 16 F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 4D 05 00 03 01 00 17 F7
09:45:50.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6A 4E 05 00 03 01 00 18 F7
```

---

## Capture 4 — P2, group A, pad "." → slot 1 ← most important

**Setup:** in the Sample Tool, switch to **project 2** first (that switch
may generate its own traffic — wait for it to settle, then clear the log).
Drag onto **A-"."**, same pad position as capture 1 but on project 2.

**Expected:** this reveals the project offset. The difference between
Capture 1's padFileId (3210) and this one tells us how projects stride.

```
09:46:38.376	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 01 05 08 07 02 07 50 00 00 F7
09:46:38.384	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 02 05 04 0B 0F 20 F7
09:46:38.384	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 03 05 00 07 02 10 04 00 00 F7
09:46:38.384	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 04 05 00 0B 10 68 F7
09:46:38.384	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 05 05 00 07 02 10 68 00 00 F7
09:46:38.385	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 71 06 05 00 07 01 10 68 7B 22 61 00 63 74 69 76 65 22 3A 00 34 32 30 38 7D 00 F7
09:46:38.387	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 07 05 00 0B 00 75 F7
09:46:38.388	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 08 05 00 07 02 00 75 00 00 F7
09:46:38.396	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 09 05 00 07 02 00 75 00 01 F7
09:46:38.398	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 71 0A 05 00 03 00 00 75 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 03 07 50 F7
09:46:38.405	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 0B 05 00 03 01 00 00 F7
09:46:38.407	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 0C 05 00 03 01 00 01 F7
09:46:38.410	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 0D 05 00 03 01 00 02 F7
09:46:38.412	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 0E 05 00 03 01 00 03 F7
09:46:38.414	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 0F 05 00 03 01 00 04 F7
09:46:38.416	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 10 05 00 03 01 00 05 F7
09:46:38.418	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 11 05 00 03 01 00 06 F7
09:46:38.420	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 12 05 00 03 01 00 07 F7
09:46:38.422	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 13 05 00 03 01 00 08 F7
09:46:38.424	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 14 05 00 03 01 00 09 F7
09:46:38.426	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 15 05 00 03 01 00 0A F7
09:46:38.428	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 16 05 00 03 01 00 0B F7
09:46:38.431	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 17 05 00 03 01 00 0C F7
09:46:38.434	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 18 05 00 03 01 00 0D F7
09:46:38.436	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 19 05 00 03 01 00 0E F7
09:46:38.438	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 1A 05 00 03 01 00 0F F7
09:46:38.440	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 1B 05 00 03 01 00 10 F7
09:46:38.442	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 1C 05 00 03 01 00 11 F7
09:46:38.444	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 1D 05 00 03 01 00 12 F7
09:46:38.446	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 1E 05 00 03 01 00 13 F7
09:46:38.448	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 1F 05 00 03 01 00 14 F7
09:46:38.450	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 20 05 00 03 01 00 15 F7
09:46:38.453	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 21 05 00 03 01 00 16 F7
09:46:38.455	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 22 05 00 03 01 00 17 F7
09:46:38.457	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 23 05 00 03 01 00 18 F7
09:46:38.643	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 24 05 08 07 02 07 50 00 00 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 25 05 04 0B 0F 20 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 26 05 00 07 02 10 04 00 00 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 27 05 00 0B 10 68 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 28 05 00 07 02 10 68 00 00 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 71 29 05 00 07 01 10 68 7B 22 61 00 63 74 69 76 65 22 3A 00 34 32 31 31 7D 00 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 2A 05 00 0B 00 18 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 2B 05 00 07 02 00 18 00 00 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 2C 05 00 07 02 00 18 00 01 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 71 2D 05 00 03 00 00 18 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 04 07 50 F7
09:46:38.671	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 2E 05 00 03 01 00 00 F7
09:46:38.672	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 2F 05 00 03 01 00 01 F7
09:46:38.674	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 30 05 00 03 01 00 02 F7
09:46:38.676	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 31 05 00 03 01 00 03 F7
09:46:38.678	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 32 05 00 03 01 00 04 F7
09:46:38.683	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 33 05 00 03 01 00 05 F7
09:46:38.687	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 34 05 00 03 01 00 06 F7
09:46:38.689	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 35 05 00 03 01 00 07 F7
09:46:38.691	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 36 05 00 03 01 00 08 F7
09:46:38.693	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 37 05 00 03 01 00 09 F7
09:46:38.696	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 38 05 00 03 01 00 0A F7
09:46:38.698	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 39 05 00 03 01 00 0B F7
09:46:38.700	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 3A 05 00 03 01 00 0C F7
09:46:38.702	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 3B 05 00 03 01 00 0D F7
09:46:38.704	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 3C 05 00 03 01 00 0E F7
09:46:38.706	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 3D 05 00 03 01 00 0F F7
09:46:38.708	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 3E 05 00 03 01 00 10 F7
09:46:38.710	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 3F 05 00 03 01 00 11 F7
09:46:38.712	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 40 05 00 03 01 00 12 F7
09:46:38.715	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 41 05 00 03 01 00 13 F7
09:46:38.718	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 42 05 00 03 01 00 14 F7
09:46:38.720	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 43 05 00 03 01 00 15 F7
09:46:38.722	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 44 05 00 03 01 00 16 F7
09:46:38.724	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 45 05 00 03 01 00 17 F7
09:46:38.726	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 46 05 00 03 01 00 18 F7
09:46:38.841	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 47 05 08 07 02 07 50 00 00 F7
09:46:38.843	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 48 05 04 0B 0F 20 F7
09:46:38.844	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 49 05 00 07 02 10 04 00 00 F7
09:46:38.845	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 4A 05 00 0B 10 68 F7
09:46:38.862	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 4B 05 00 07 02 10 68 00 00 F7
09:46:38.862	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 71 4C 05 00 07 01 10 68 7B 22 61 00 63 74 69 76 65 22 3A 00 34 32 31 30 7D 00 F7
09:46:38.862	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 4D 05 00 0B 00 07 F7
09:46:38.862	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 4E 05 00 07 02 00 07 00 00 F7
09:46:38.862	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 4F 05 00 07 02 00 07 00 01 F7
09:46:38.862	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 71 50 05 00 03 00 00 07 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 04 07 50 F7
09:46:38.868	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 51 05 00 03 01 00 00 F7
09:46:38.870	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 52 05 00 03 01 00 01 F7
09:46:38.872	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 53 05 00 03 01 00 02 F7
09:46:38.874	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 54 05 00 03 01 00 03 F7
09:46:38.876	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 55 05 00 03 01 00 04 F7
09:46:38.878	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 56 05 00 03 01 00 05 F7
09:46:38.882	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 57 05 00 03 01 00 06 F7
09:46:38.884	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 58 05 00 03 01 00 07 F7
09:46:38.887	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 59 05 00 03 01 00 08 F7
09:46:38.889	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 5A 05 00 03 01 00 09 F7
09:46:38.891	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 5B 05 00 03 01 00 0A F7
09:46:38.894	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 5C 05 00 03 01 00 0B F7
09:46:38.896	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 5D 05 00 03 01 00 0C F7
09:46:38.898	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 5E 05 00 03 01 00 0D F7
09:46:38.900	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 5F 05 00 03 01 00 0E F7
09:46:38.902	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 60 05 00 03 01 00 0F F7
09:46:38.905	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 61 05 00 03 01 00 10 F7
09:46:38.907	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 62 05 00 03 01 00 11 F7
09:46:38.909	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 63 05 00 03 01 00 12 F7
09:46:38.911	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 64 05 00 03 01 00 13 F7
09:46:38.913	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 65 05 00 03 01 00 14 F7
09:46:38.915	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 66 05 00 03 01 00 15 F7
09:46:38.917	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 67 05 00 03 01 00 16 F7
09:46:38.919	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 68 05 00 03 01 00 17 F7
09:46:38.921	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 69 05 00 03 01 00 18 F7
09:46:39.394	To EP-133	SysEx		Teenage Engineering 26 bytes	F0 00 20 76 33 40 71 6A 05 00 07 01 10 72 7B 22 73 00 79 6D 22 3A 31 7D 00 F7
09:46:39.428	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 71 6B 05 00 0B 00 01 F7
09:46:39.429	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 6C 05 00 07 02 00 01 00 00 F7
09:46:39.436	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 71 6D 05 00 07 02 00 01 00 01 F7
09:46:39.437	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 71 6E 05 00 03 00 00 01 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 28 07 50 F7
09:46:39.445	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 6F 05 00 03 01 00 00 F7
09:46:39.448	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 70 05 00 03 01 00 01 F7
09:46:39.452	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 71 05 00 03 01 00 02 F7
09:46:39.454	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 72 05 00 03 01 00 03 F7
09:46:39.457	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 73 05 00 03 01 00 04 F7
09:46:39.460	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 74 05 00 03 01 00 05 F7
09:46:39.462	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 75 05 00 03 01 00 06 F7
09:46:39.465	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 76 05 00 03 01 00 07 F7
09:46:39.468	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 77 05 00 03 01 00 08 F7
09:46:39.470	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 78 05 00 03 01 00 09 F7
09:46:39.473	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 79 05 00 03 01 00 0A F7
09:46:39.476	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 7A 05 00 03 01 00 0B F7
09:46:39.479	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 7B 05 00 03 01 00 0C F7
09:46:39.481	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 7C 05 00 03 01 00 0D F7
09:46:39.483	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 7D 05 00 03 01 00 0E F7
09:46:39.486	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 7E 05 00 03 01 00 0F F7
09:46:39.489	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 71 7F 05 00 03 01 00 10 F7
09:46:39.491	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 72 00 05 00 03 01 00 11 F7
09:46:39.494	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 72 01 05 00 03 01 00 12 F7
09:46:39.520	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 72 02 05 00 03 01 00 13 F7
09:46:39.520	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 72 03 05 00 03 01 00 14 F7
09:46:39.520	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 72 04 05 00 03 01 00 15 F7
09:46:39.520	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 72 05 05 00 03 01 00 16 F7
09:46:39.520	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 72 06 05 00 03 01 00 17 F7
09:46:39.520	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 72 07 05 00 03 01 00 18 F7
```

---

## Derived formula (validated by captures 1-4)

```
padFileId = 3200 + (project - 1) × 1000 + group_index × 100 + pad_num
```

- `group_index`: A=0, B=1, C=2, D=3
- `pad_num`: 1..12, **visual position** (top-to-bottom, left-to-right)
- Label-to-pad_num: 7→1, 8→2, 9→3, 4→4, 5→5, 6→6, 1→7, 2→8, 3→9, .→10, 0→11, ENTER→12

Assignment wire format: `cmd=5, payload = 07 01 [padFileId:u16 BE] {"sym":<slot>}\0`

## Validation round — 4 more captures (random coverage)

**Before capturing #6 or #8: upload a sample to slot 2.**
```
uv run stemforge ep133 upload <any_wav> --slot 2
```

---

### Capture 5 — P3, group C, pad "5" → slot 1

**Setup:** Sample Tool on **project 3**, group **C**. Drag a sample onto the
pad labeled **"5"** (middle row, middle column).

**Expected:** padFileId = 5405 = `0x15 1D`. Final msg payload unpacks to
`07 01 15 1D {"sym":1}\0`.

```
10:47:19.810	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 33 05 08 07 02 07 50 00 00 F7
10:47:19.819	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 79 34 05 04 0B 13 08 F7
10:47:19.819	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 35 05 08 07 02 13 6C 00 00 F7
10:47:19.819	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 79 36 05 00 0B 15 18 F7
10:47:19.819	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 37 05 00 07 02 15 18 00 00 F7
10:47:19.819	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 79 38 05 00 07 01 15 18 7B 22 61 00 63 74 69 76 65 22 3A 00 35 34 30 36 7D 00 F7
10:47:19.820	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 79 39 05 00 0B 02 1E F7
10:47:19.820	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 3A 05 00 07 02 02 1E 00 00 F7
10:47:19.827	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 3B 05 00 07 02 02 1E 00 01 F7
10:47:19.829	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 79 3C 05 00 03 00 02 1E 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 40 07 50 F7
10:47:19.836	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 3D 05 00 03 01 00 00 F7
10:47:19.838	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 3E 05 00 03 01 00 01 F7
10:47:19.841	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 3F 05 00 03 01 00 02 F7
10:47:19.844	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 40 05 00 03 01 00 03 F7
10:47:19.846	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 41 05 00 03 01 00 04 F7
10:47:19.849	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 42 05 00 03 01 00 05 F7
10:47:19.852	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 43 05 00 03 01 00 06 F7
10:47:19.855	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 44 05 00 03 01 00 07 F7
10:47:19.857	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 45 05 00 03 01 00 08 F7
10:47:19.860	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 46 05 00 03 01 00 09 F7
10:47:19.863	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 47 05 00 03 01 00 0A F7
10:47:19.865	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 48 05 00 03 01 00 0B F7
10:47:19.868	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 49 05 00 03 01 00 0C F7
10:47:19.871	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 4A 05 00 03 01 00 0D F7
10:47:19.873	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 4B 05 00 03 01 00 0E F7
10:47:19.876	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 4C 05 00 03 01 00 0F F7
10:47:19.877	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 4D 05 00 03 01 00 10 F7
10:47:19.880	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 4E 05 00 03 01 00 11 F7
10:47:19.882	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 4F 05 00 03 01 00 12 F7
10:47:19.884	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 50 05 00 03 01 00 13 F7
10:47:19.887	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 51 05 00 03 01 00 14 F7
10:47:19.890	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 52 05 00 03 01 00 15 F7
10:47:19.893	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 53 05 00 03 01 00 16 F7
10:47:19.895	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 54 05 00 03 01 00 17 F7
10:47:19.898	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 55 05 00 03 01 00 18 F7
10:47:19.901	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 56 05 00 03 01 00 19 F7
10:47:19.904	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 57 05 00 03 01 00 1A F7
10:47:19.906	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 58 05 00 03 01 00 1B F7
10:47:19.909	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 59 05 00 03 01 00 1C F7
10:47:19.939	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 5A 05 00 03 01 00 1D F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 5B 05 00 03 01 00 1E F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 5C 05 00 03 01 00 1F F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 5D 05 00 03 01 00 20 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 5E 05 00 03 01 00 21 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 5F 05 00 03 01 00 22 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 60 05 00 03 01 00 23 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 61 05 00 03 01 00 24 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 62 05 00 03 01 00 25 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 63 05 00 03 01 00 26 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 64 05 00 03 01 00 27 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 65 05 00 03 01 00 28 F7
10:47:19.940	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 66 05 00 03 01 00 29 F7
10:47:19.943	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 67 05 00 03 01 00 2A F7
10:47:19.946	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 68 05 00 03 01 00 2B F7
10:47:19.949	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 69 05 00 03 01 00 2C F7
10:47:19.951	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 6A 05 00 03 01 00 2D F7
10:47:19.955	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 6B 05 00 03 01 00 2E F7
10:47:19.958	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 6C 05 00 03 01 00 2F F7
10:47:19.961	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 6D 05 00 03 01 00 30 F7
10:47:19.964	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 6E 05 00 03 01 00 31 F7
10:47:19.969	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 6F 05 08 07 02 07 50 00 00 F7
10:47:19.970	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 79 70 05 04 0B 13 08 F7
10:47:19.972	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 71 05 08 07 02 13 6C 00 00 F7
10:47:19.973	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 79 72 05 00 0B 15 18 F7
10:47:19.974	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 73 05 00 07 02 15 18 00 00 F7
10:47:19.975	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 79 74 05 00 07 01 15 18 7B 22 61 00 63 74 69 76 65 22 3A 00 35 34 30 35 7D 00 F7
10:47:19.978	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 79 75 05 00 0B 02 19 F7
10:47:19.979	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 76 05 00 07 02 02 19 00 00 F7
10:47:19.986	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 79 77 05 00 07 02 02 19 00 01 F7
10:47:19.988	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 79 78 05 00 03 00 02 19 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 3E 07 50 F7
10:47:19.993	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 79 05 00 03 01 00 00 F7
10:47:19.995	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 7A 05 00 03 01 00 01 F7
10:47:19.998	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 7B 05 00 03 01 00 02 F7
10:47:20.001	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 7C 05 00 03 01 00 03 F7
10:47:20.003	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 7D 05 00 03 01 00 04 F7
10:47:20.006	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 7E 05 00 03 01 00 05 F7
10:47:20.008	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 79 7F 05 00 03 01 00 06 F7
10:47:20.011	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 00 05 00 03 01 00 07 F7
10:47:20.036	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 01 05 00 03 01 00 08 F7
10:47:20.036	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 02 05 00 03 01 00 09 F7
10:47:20.037	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 03 05 00 03 01 00 0A F7
10:47:20.037	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 04 05 00 03 01 00 0B F7
10:47:20.037	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 05 05 00 03 01 00 0C F7
10:47:20.037	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 06 05 00 03 01 00 0D F7
10:47:20.037	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 07 05 00 03 01 00 0E F7
10:47:20.037	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 08 05 00 03 01 00 0F F7
10:47:20.037	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 09 05 00 03 01 00 10 F7
10:47:20.039	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 0A 05 00 03 01 00 11 F7
10:47:20.042	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 0B 05 00 03 01 00 12 F7
10:47:20.044	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 0C 05 00 03 01 00 13 F7
10:47:20.047	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 0D 05 00 03 01 00 14 F7
10:47:20.049	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 0E 05 00 03 01 00 15 F7
10:47:20.051	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 0F 05 00 03 01 00 16 F7
10:47:20.054	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 10 05 00 03 01 00 17 F7
10:47:20.057	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 11 05 00 03 01 00 18 F7
10:47:20.060	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 12 05 00 03 01 00 19 F7
10:47:20.063	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 13 05 00 03 01 00 1A F7
10:47:20.065	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 14 05 00 03 01 00 1B F7
10:47:20.067	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 15 05 00 03 01 00 1C F7
10:47:20.070	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 16 05 00 03 01 00 1D F7
10:47:20.073	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 17 05 00 03 01 00 1E F7
10:47:20.076	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 18 05 00 03 01 00 1F F7
10:47:20.078	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 19 05 00 03 01 00 20 F7
10:47:20.081	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 1A 05 00 03 01 00 21 F7
10:47:20.085	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 1B 05 00 03 01 00 22 F7
10:47:20.088	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 1C 05 00 03 01 00 23 F7
10:47:20.091	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 1D 05 00 03 01 00 24 F7
10:47:20.093	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 1E 05 00 03 01 00 25 F7
10:47:20.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 1F 05 00 03 01 00 26 F7
10:47:20.099	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 20 05 00 03 01 00 27 F7
10:47:20.102	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 21 05 00 03 01 00 28 F7
10:47:20.105	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 22 05 00 03 01 00 29 F7
10:47:20.107	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 23 05 00 03 01 00 2A F7
10:47:20.110	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 24 05 00 03 01 00 2B F7
10:47:20.133	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 25 05 00 03 01 00 2C F7
10:47:20.133	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 26 05 00 03 01 00 2D F7
10:47:20.133	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 27 05 00 03 01 00 2E F7
10:47:20.133	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 28 05 00 03 01 00 2F F7
10:47:20.133	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 29 05 00 03 01 00 30 F7
10:47:20.133	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 2A 05 00 03 01 00 31 F7
10:47:20.582	To EP-133	SysEx		Teenage Engineering 28 bytes	F0 00 20 76 33 40 7A 2B 05 00 07 01 15 1D 7B 22 73 00 79 6D 22 3A 31 39 7D 00 00 F7
10:47:20.612	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 7A 2C 05 00 0B 00 13 F7
10:47:20.613	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 7A 2D 05 00 07 02 00 13 00 00 F7
10:47:20.620	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 7A 2E 05 00 07 02 00 13 00 01 F7
10:47:20.622	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 7A 2F 05 00 03 00 00 13 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 05 07 50 F7
10:47:20.628	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 30 05 00 03 01 00 00 F7
10:47:20.630	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 31 05 00 03 01 00 01 F7
10:47:20.632	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 32 05 00 03 01 00 02 F7
10:47:20.634	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 33 05 00 03 01 00 03 F7
10:47:20.636	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 34 05 00 03 01 00 04 F7
10:47:20.639	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 35 05 00 03 01 00 05 F7
10:47:20.641	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 36 05 00 03 01 00 06 F7
10:47:20.643	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 37 05 00 03 01 00 07 F7
10:47:20.645	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 38 05 00 03 01 00 08 F7
10:47:20.647	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 39 05 00 03 01 00 09 F7
10:47:20.649	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 3A 05 00 03 01 00 0A F7
10:47:20.652	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 3B 05 00 03 01 00 0B F7
10:47:20.654	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 3C 05 00 03 01 00 0C F7
10:47:20.656	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 3D 05 00 03 01 00 0D F7
10:47:20.658	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 3E 05 00 03 01 00 0E F7
10:47:20.660	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 3F 05 00 03 01 00 0F F7
10:47:20.662	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 40 05 00 03 01 00 10 F7
10:47:20.664	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 41 05 00 03 01 00 11 F7
10:47:20.666	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 42 05 00 03 01 00 12 F7
10:47:20.668	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 43 05 00 03 01 00 13 F7
10:47:20.671	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 44 05 00 03 01 00 14 F7
10:47:20.674	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 45 05 00 03 01 00 15 F7
10:47:20.676	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 46 05 00 03 01 00 16 F7
10:47:20.678	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 47 05 00 03 01 00 17 F7
10:47:20.681	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 7A 48 05 00 03 01 00 18 F7
```

---

### Capture 6 — P7, group D, pad "9" → slot 2

**Setup:** Sample Tool on **project 7**, group **D**. Drag a sample from
**slot 2** onto the pad labeled **"9"** (top-right corner).

**Expected:** padFileId = 9503 = `0x25 1F`. Final msg:
`07 01 25 1F {"sym":2}\0`.

```
10:49:31.918	To EP-133	SysEx		Teenage Engineering 24 bytes	F0 00 20 76 33 40 6B 13 05 00 05 01 00 18 00 00 00 10 00 00 00 03 68 F7
10:49:34.377	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6B 14 05 08 07 02 07 50 00 00 F7
10:49:34.382	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6B 15 05 00 0B 23 28 F7
10:49:34.382	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6B 16 05 08 07 02 23 0C 00 00 F7
10:49:34.382	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6B 17 05 00 0B 25 1C F7
10:49:34.382	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6B 18 05 00 07 02 25 1C 00 00 F7
10:49:34.383	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 6B 19 05 00 07 01 25 1C 7B 22 61 00 63 74 69 76 65 22 3A 00 39 35 30 33 7D 00 F7
10:49:34.969	To EP-133	SysEx		Teenage Engineering 28 bytes	F0 00 20 76 33 40 6B 1A 05 00 07 01 25 1F 7B 22 73 00 79 6D 22 3A 32 34 7D 00 00 F7
10:49:35.012	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6B 1B 05 00 0B 25 1F F7
10:49:35.014	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6B 1C 05 00 0B 25 1F F7
10:49:35.015	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6B 1D 05 00 07 02 25 1F 00 00 F7
10:49:35.017	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6B 1E 05 00 07 02 25 1F 00 00 F7
10:49:35.020	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6B 1F 05 00 0B 00 18 F7
10:49:35.022	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6B 20 05 00 07 02 00 18 00 00 F7
10:49:35.031	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6B 21 05 00 07 02 00 18 00 01 F7
10:49:35.032	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 6B 22 05 00 03 00 00 18 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 04 07 50 F7
10:49:35.041	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 23 05 00 03 01 00 00 F7
10:49:35.043	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 24 05 00 03 01 00 01 F7
10:49:35.046	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 25 05 00 03 01 00 02 F7
10:49:35.049	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 26 05 00 03 01 00 03 F7
10:49:35.052	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 27 05 00 03 01 00 04 F7
10:49:35.054	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 28 05 00 03 01 00 05 F7
10:49:35.057	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 29 05 00 03 01 00 06 F7
10:49:35.059	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 2A 05 00 03 01 00 07 F7
10:49:35.061	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 2B 05 00 03 01 00 08 F7
10:49:35.064	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 2C 05 00 03 01 00 09 F7
10:49:35.066	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 2D 05 00 03 01 00 0A F7
10:49:35.068	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 2E 05 00 03 01 00 0B F7
10:49:35.070	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 2F 05 00 03 01 00 0C F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 30 05 00 03 01 00 0D F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 31 05 00 03 01 00 0E F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 32 05 00 03 01 00 0F F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 33 05 00 03 01 00 10 F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 34 05 00 03 01 00 11 F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 35 05 00 03 01 00 12 F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 36 05 00 03 01 00 13 F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 37 05 00 03 01 00 14 F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 38 05 00 03 01 00 15 F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 39 05 00 03 01 00 16 F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 3A 05 00 03 01 00 17 F7
10:49:35.096	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6B 3B 05 00 03 01 00 18 F7
```

---

### Capture 7 — P5, group A, pad "ENTER" → slot 1

**Setup:** Sample Tool on **project 5**, group **A**. Drag slot 1 onto the
pad labeled **"ENTER"** (bottom-right corner).

**Expected:** padFileId = 7212 = `0x1C 2C`. Final msg:
`07 01 1C 2C {"sym":1}\0`.

```
10:48:36.233	To EP-133	SysEx		Teenage Engineering 28 bytes	F0 00 20 76 33 40 61 71 05 00 07 01 1C 2C 7B 22 73 00 79 6D 22 3A 31 31 7D 00 00 F7
10:48:36.260	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 61 72 05 00 0B 00 0B F7
10:48:36.262	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 61 73 05 00 07 02 00 0B 00 00 F7
10:48:36.269	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 61 74 05 00 07 02 00 0B 00 01 F7
10:48:36.271	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 61 75 05 00 03 00 00 0B 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 03 07 50 F7
10:48:36.276	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 76 05 00 03 01 00 00 F7
10:48:36.278	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 77 05 00 03 01 00 01 F7
10:48:36.280	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 78 05 00 03 01 00 02 F7
10:48:36.282	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 79 05 00 03 01 00 03 F7
10:48:36.284	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 7A 05 00 03 01 00 04 F7
10:48:36.286	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 7B 05 00 03 01 00 05 F7
10:48:36.288	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 7C 05 00 03 01 00 06 F7
10:48:36.290	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 7D 05 00 03 01 00 07 F7
10:48:36.291	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 7E 05 00 03 01 00 08 F7
10:48:36.293	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 61 7F 05 00 03 01 00 09 F7
10:48:36.295	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 00 05 00 03 01 00 0A F7
10:48:36.297	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 01 05 00 03 01 00 0B F7
10:48:36.299	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 02 05 00 03 01 00 0C F7
10:48:36.301	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 03 05 00 03 01 00 0D F7
10:48:36.303	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 04 05 00 03 01 00 0E F7
10:48:36.305	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 05 05 00 03 01 00 0F F7
10:48:36.307	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 06 05 00 03 01 00 10 F7
10:48:36.309	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 07 05 00 03 01 00 11 F7
10:48:36.311	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 08 05 00 03 01 00 12 F7
10:48:36.313	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 09 05 00 03 01 00 13 F7
10:48:36.315	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 0A 05 00 03 01 00 14 F7
10:48:36.317	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 0B 05 00 03 01 00 15 F7
10:48:36.319	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 0C 05 00 03 01 00 16 F7
10:48:36.322	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 0D 05 00 03 01 00 17 F7
10:48:36.324	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 62 0E 05 00 03 01 00 18 F7
```

---

### Capture 8 — P2, group B, pad "7" → slot 2

**Setup:** Sample Tool on **project 2**, group **B**. Drag slot 2 onto the
pad labeled **"7"** (top-left corner).

**Expected:** padFileId = 4301 = `0x10 CD`. Final msg:
`07 01 10 CD {"sym":2}\0`.

```
10:50:19.995	To EP-133	SysEx		Teenage Engineering 24 bytes	F0 00 20 76 33 40 6C 74 05 08 05 01 01 1E 00 00 00 10 00 00 00 03 68 F7
10:50:21.065	To EP-133	SysEx		Teenage Engineering 24 bytes	F0 00 20 76 33 40 6C 75 05 08 05 01 01 1F 00 00 00 10 00 00 00 03 68 F7
10:50:23.161	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6C 76 05 08 07 02 07 50 00 00 F7
10:50:23.170	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6C 77 05 04 0B 0F 20 F7
10:50:23.171	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6C 78 05 00 07 02 10 04 00 00 F7
10:50:23.171	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6C 79 05 04 0B 10 4C F7
10:50:23.171	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6C 7A 05 08 07 02 10 4C 00 00 F7
10:50:23.171	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 6C 7B 05 08 07 01 10 4C 7B 22 61 00 63 74 69 76 65 22 3A 00 34 33 30 32 7D 00 F7
10:50:23.171	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6C 7C 05 04 0B 01 43 F7
10:50:23.173	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6C 7D 05 08 07 02 01 43 00 00 F7
10:50:23.183	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 6C 7E 05 08 03 00 01 43 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 07 07 50 F7
10:50:23.191	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6C 7F 05 00 03 01 00 00 F7
10:50:23.193	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 00 05 00 03 01 00 01 F7
10:50:23.195	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 01 05 00 03 01 00 02 F7
10:50:23.198	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 02 05 00 03 01 00 03 F7
10:50:23.200	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 03 05 00 03 01 00 04 F7
10:50:23.203	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 04 05 00 03 01 00 05 F7
10:50:23.206	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 05 05 00 03 01 00 06 F7
10:50:23.207	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 06 05 00 03 01 00 07 F7
10:50:23.210	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 07 05 00 03 01 00 08 F7
10:50:23.213	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 08 05 00 03 01 00 09 F7
10:50:23.215	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 09 05 00 03 01 00 0A F7
10:50:23.217	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 0A 05 00 03 01 00 0B F7
10:50:23.219	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 0B 05 00 03 01 00 0C F7
10:50:23.221	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 0C 05 00 03 01 00 0D F7
10:50:23.223	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 0D 05 00 03 01 00 0E F7
10:50:23.225	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 0E 05 00 03 01 00 0F F7
10:50:23.227	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 0F 05 00 03 01 00 10 F7
10:50:23.229	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 10 05 00 03 01 00 11 F7
10:50:23.232	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 11 05 00 03 01 00 12 F7
10:50:23.233	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 12 05 00 03 01 00 13 F7
10:50:23.236	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 13 05 00 03 01 00 14 F7
10:50:23.238	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 14 05 00 03 01 00 15 F7
10:50:23.240	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 15 05 00 03 01 00 16 F7
10:50:23.243	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 16 05 00 03 01 00 17 F7
10:50:23.245	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 17 05 00 03 01 00 18 F7
10:50:23.248	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6D 18 05 08 07 02 07 50 00 00 F7
10:50:23.249	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6D 19 05 04 0B 0F 20 F7
10:50:23.250	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6D 1A 05 00 07 02 10 04 00 00 F7
10:50:23.251	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6D 1B 05 04 0B 10 4C F7
10:50:23.252	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6D 1C 05 08 07 02 10 4C 00 00 F7
10:50:23.253	To EP-133	SysEx		Teenage Engineering 33 bytes	F0 00 20 76 33 40 6D 1D 05 08 07 01 10 4C 7B 22 61 00 63 74 69 76 65 22 3A 00 34 33 30 31 7D 00 F7
10:50:23.257	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6D 1E 05 04 0B 01 3E F7
10:50:23.258	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6D 1F 05 08 07 02 01 3E 00 00 F7
10:50:23.285	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6D 20 05 08 07 02 01 3E 00 01 F7
10:50:23.285	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 6D 21 05 08 03 00 01 3E 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 09 07 50 F7
10:50:23.285	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 22 05 00 03 01 00 00 F7
10:50:23.286	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 23 05 00 03 01 00 01 F7
10:50:23.286	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 24 05 00 03 01 00 02 F7
10:50:23.286	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 25 05 00 03 01 00 03 F7
10:50:23.286	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 26 05 00 03 01 00 04 F7
10:50:23.288	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 27 05 00 03 01 00 05 F7
10:50:23.290	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 28 05 00 03 01 00 06 F7
10:50:23.292	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 29 05 00 03 01 00 07 F7
10:50:23.294	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 2A 05 00 03 01 00 08 F7
10:50:23.296	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 2B 05 00 03 01 00 09 F7
10:50:23.299	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 2C 05 00 03 01 00 0A F7
10:50:23.300	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 2D 05 00 03 01 00 0B F7
10:50:23.303	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 2E 05 00 03 01 00 0C F7
10:50:23.305	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 2F 05 00 03 01 00 0D F7
10:50:23.307	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 30 05 00 03 01 00 0E F7
10:50:23.309	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 31 05 00 03 01 00 0F F7
10:50:23.311	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 32 05 00 03 01 00 10 F7
10:50:23.313	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 33 05 00 03 01 00 11 F7
10:50:23.315	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 34 05 00 03 01 00 12 F7
10:50:23.317	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 35 05 00 03 01 00 13 F7
10:50:23.319	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 36 05 00 03 01 00 14 F7
10:50:23.321	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 37 05 00 03 01 00 15 F7
10:50:23.323	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 38 05 00 03 01 00 16 F7
10:50:23.325	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 39 05 00 03 01 00 17 F7
10:50:23.327	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 3A 05 00 03 01 00 18 F7
10:50:23.329	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 3B 05 00 03 01 00 19 F7
10:50:23.331	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 3C 05 00 03 01 00 1A F7
10:50:23.332	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 3D 05 00 03 01 00 1B F7
10:50:23.334	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 3E 05 00 03 01 00 1C F7
10:50:23.336	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 3F 05 00 03 01 00 1D F7
10:50:23.339	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 40 05 00 03 01 00 1E F7
10:50:23.341	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 41 05 00 03 01 00 1F F7
10:50:23.343	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 42 05 00 03 01 00 20 F7
10:50:23.345	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 43 05 00 03 01 00 21 F7
10:50:23.347	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 44 05 00 03 01 00 22 F7
10:50:23.349	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 45 05 00 03 01 00 23 F7
10:50:23.352	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 46 05 00 03 01 00 24 F7
10:50:23.353	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 47 05 00 03 01 00 25 F7
10:50:23.355	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 48 05 00 03 01 00 26 F7
10:50:23.357	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 49 05 00 03 01 00 27 F7
10:50:23.359	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 4A 05 00 03 01 00 28 F7
10:50:23.361	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 4B 05 00 03 01 00 29 F7
10:50:23.385	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 4C 05 00 03 01 00 2A F7
10:50:23.385	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 4D 05 00 03 01 00 2B F7
10:50:23.385	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 4E 05 00 03 01 00 2C F7
10:50:23.385	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 4F 05 00 03 01 00 2D F7
10:50:23.385	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 50 05 00 03 01 00 2E F7
10:50:23.385	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 51 05 00 03 01 00 2F F7
10:50:23.385	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 52 05 00 03 01 00 30 F7
10:50:23.385	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 53 05 00 03 01 00 31 F7
10:50:23.931	To EP-133	SysEx		Teenage Engineering 29 bytes	F0 00 20 76 33 40 6D 54 05 08 07 01 10 4D 7B 22 73 00 79 6D 22 3A 34 31 35 00 7D 00 F7
10:50:24.079	To EP-133	SysEx		Teenage Engineering 14 bytes	F0 00 20 76 33 40 6D 55 05 04 0B 01 1F F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6D 56 05 08 07 02 01 1F 00 00 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 17 bytes	F0 00 20 76 33 40 6D 57 05 08 07 02 01 1F 00 01 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 34 bytes	F0 00 20 76 33 40 6D 58 05 08 03 00 01 1F 00 00 00 00 00 00 00 00 00 00 00 40 00 00 01 00 13 07 50 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 59 05 00 03 01 00 00 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 5A 05 00 03 01 00 01 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 5B 05 00 03 01 00 02 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 5C 05 00 03 01 00 03 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 5D 05 00 03 01 00 04 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 5E 05 00 03 01 00 05 F7
10:50:24.108	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 5F 05 00 03 01 00 06 F7
10:50:24.110	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 60 05 00 03 01 00 07 F7
10:50:24.113	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 61 05 00 03 01 00 08 F7
10:50:24.115	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 62 05 00 03 01 00 09 F7
10:50:24.118	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 63 05 00 03 01 00 0A F7
10:50:24.121	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 64 05 00 03 01 00 0B F7
10:50:24.123	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 65 05 00 03 01 00 0C F7
10:50:24.125	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 66 05 00 03 01 00 0D F7
10:50:24.127	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 67 05 00 03 01 00 0E F7
10:50:24.130	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 68 05 00 03 01 00 0F F7
10:50:24.133	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 69 05 00 03 01 00 10 F7
10:50:24.136	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 6A 05 00 03 01 00 11 F7
10:50:24.138	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 6B 05 00 03 01 00 12 F7
10:50:24.140	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 6C 05 00 03 01 00 13 F7
10:50:24.143	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 6D 05 00 03 01 00 14 F7
10:50:24.145	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 6E 05 00 03 01 00 15 F7
10:50:24.148	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 6F 05 00 03 01 00 16 F7
10:50:24.151	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 70 05 00 03 01 00 17 F7
10:50:24.153	To EP-133	SysEx		Teenage Engineering 15 bytes	F0 00 20 76 33 40 6D 71 05 00 03 01 00 18 F7
```

---

## When captures 5-8 are in

If all four match the expected hex, formula is validated. Claude then:

1. Adds `build_metadata_set(file_id, json_payload)` to `payloads.py`
2. Adds `build_assign_pad(project, group, pad, slot)` wrapper
3. Saves all 8 captures as `.syx` fixtures + byte-identical tests
4. Adds `EP133Client.assign_pad(project, group, pad, slot)`
5. Adds `stemforge ep133 assign-pad` CLI command
6. Wires `EP133Mapping` YAML through to device via the new client

If any don't match, stops and investigates before implementing.

ETA once the captures are in: ~1 hour.
