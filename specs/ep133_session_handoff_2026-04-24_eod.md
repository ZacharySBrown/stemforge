# EP-133 Protocol — Session Handoff (2026-04-24 EOD)

Primer for the next push. Read this first, then the files in §5.

---

## TL;DR

We cracked live SysEx project-file reads on the EP-133, decoded the two
per-pad BPM encodings, and shipped the whole thing with tests and docs.
A synthetic-`.ppak` write attempt at the end went sideways (ERROR CLOCK 43,
required flash format). Device is now clean, everything we learned is
preserved in code and memory.

**Today's open-question shortlist, ranked:**

1. Does Sample Tool's real `.ppak` `settings` file let a modified `.ppak`
   load successfully? (biggest unlock)
2. Resolve phones24's "float32 = BPM" vs our "float32 = BPM/2".
3. What actually triggers float32 vs override encoding selection on a pad?

---

## 1. Device state right now

- **Just flash-formatted** (`SHIFT + ERASE` at boot). All samples, projects,
  settings wiped.
- Firmware: **not recorded this session** (first-priority task next time
  — check `SETTINGS → SYSTEM → VERSION` and note it).
- No known state wedges, corruptions, or lingering errors.

---

## 2. What landed this session

### Commits on `feat/curation-engine-v2`

```
53a548f  docs: CLOCK 43 failure mode + settings-file warning in validation guide
5dda4d5  docs: capture plan for async protocol analysis
ef2a2bd  docs: complete protocol spec
b92903d  feat: project-file reader + per-pad BPM decoder
8d1b11f  feat: SampleParams partial-write dataclass for sample-slot metadata
99cf42c  feat: auto-pair envelope.release with playmode
67c0337  fix: revert integer wire encoding — device accepts strings only
```

**108 tests pass** in `tests/ep133/`.

### New code

| File | What |
|------|------|
| `stemforge/exporters/ep133/project_reader.py` | Live SysEx read of project-file TAR |
| `stemforge/exporters/ep133/pad_record.py` | TAR scan + `decode_bpm()` (both encodings) |
| `stemforge/exporters/ep133/payloads.py` (modified) | `SampleParams` class, playmode/release auto-pair |
| `tests/ep133/test_pad_record.py` | 11 tests using exact observed bytes |
| `tests/ep133/test_sample_params.py` | 8 tests for the new dataclass |

### New specs

| File | Purpose |
|------|---------|
| `specs/ep133_protocol_spec.md` | Complete protocol reference — 458 lines |
| `specs/ep133_protocol_capture_plan.md` | Next-session capture matrix |
| `specs/ep133_validation_guide.md` | Synthetic-`.ppak` validation + CLOCK 43 post-mortem |
| `specs/ep133_session_handoff_2026-04-24_eod.md` | this file |

### Handoff zip (external analyst)

`/tmp/ep133_handoff_20260424.zip` — 52KB bundle: 8 dumps + docs + reference
source. Designed for an off-device analyst (no device access required).
Regenerate from `/tmp/ep133_handoff_20260424/` staging dir if needed.

### Experimental script (didn't work)

`ep133_bpm_writer.py` at repo root — attempts to generate a `.ppak` from
scratch to write per-pad BPM via import. **Triggered ERROR CLOCK 43 on the
device. Don't re-run without fixing the `settings` file and timestamps.**
See `specs/ep133_validation_guide.md` top-section for the post-mortem.

---

## 3. What's open

### Big unlocks

1. **Real `.ppak` round-trip.** Sample Tool can BACKUP a device's state
   into a real `.ppak`. If we extract one, diff it against
   `ep133_bpm_writer.py`'s output, and patch just the wrong parts
   (`settings`, `meta.json`, TAR mtimes), we should get a load-safe
   `.ppak`. That unlocks programmatic per-pad BPM writes. Highest-ROI
   next move.

2. **Run the BPM encoding matrix** from `specs/ep133_protocol_capture_plan.md`
   §3. 10 saves + dumps, each with a known state change, resolves:
   - Which pad-state transitions trigger float32 vs override encoding
   - Whether float32 stores BPM or BPM/2
   - What bytes toggle on the low/high-range boundary (127 → 128)

### Medium

3. **Validate phones24's unverified pad-record field offsets** (volume,
   pitch, pan, loop points, time.mode at byte 20/21). Doable via diff
   analysis — for each field, make one on-device change, dump, and compare
   to baseline. The analyst-bundle approach works well for this.

4. **Patterns + scenes.** The 53KB project-7 read stopped at `pads/d/...`
   and trailing metadata — no pattern data seen. Are they in a separate
   file inside the `.ppak`? Different fileId range? Open.

### Parked / low priority

5. Project write path. `FILE_INIT(w)` + `03 00` accepts, but the data
   sub-command is unmapped and speculation wedges the device. Probably
   only worth pushing if (1) above doesn't pan out.

6. Extend `EP133Client` with a clean `.read_project_file(N)` method.
   Currently `project_reader.read_project_file()` opens its own MIDI ports
   — would be nicer integrated.

---

## 4. Safety rules (memorize)

These are in `feedback_ep133_probing_safety.md` in memory — the TL;DR:

1. **Never `03 00 <fid>` without confirming `0B <fid>` stat first** returns
   non-invalid. Speculative opens wedge the device → ERROR 8200 → power
   cycle.
2. **Never `FILE_INIT(write)` + `03 00` on unknown fileIds.** Open write
   handles accumulate even without data writes.
3. **Never generate + import a synthetic `.ppak` without a real-backup
   reference** for the `settings` file. This session's ERROR CLOCK 43
   persisted across power cycles and required flash format.
4. **`0B <fid>` stat is always safe.** Use it to enumerate.
5. **`06 02 <fid>` is FILE_DELETE.** Don't call it casually.

---

## 5. Required reading (order matters)

For the next Claude Code session to be effective:

1. **This file.** You're reading it.
2. **`specs/ep133_protocol_spec.md`** — definitive protocol reference.
   458 lines, scannable. At minimum read §2 (fileIds), §3 (commands),
   §6 (pad binary record), §9 (safety rules).
3. **`specs/ep133_validation_guide.md`** — the CLOCK 43 post-mortem is at
   the top. Must-read before any `.ppak` generation.
4. **Memory entries** (auto-loaded, but worth re-reading):
   - `project_ep133_protocol_findings.md`
   - `project_ep133_binary_pad_record.md`
   - `feedback_ep133_probing_safety.md`
   - `feedback_ep133_emit_vs_accept.md`
   - `feedback_ep133_coupled_fields.md`
5. **`stemforge/exporters/ep133/pad_record.py`** — `decode_bpm()` is the
   canonical byte-level decoder with both encodings documented in the
   module docstring.
6. *(Optional)* `specs/ep133_protocol_capture_plan.md` if running
   on-device experiments.

---

## 6. Useful commands / starter snippets

### Reload device with our known-safe pipeline

Samples + a 12-pad matrix in Project 7 Group C, using the manifest-driven
loader we've been using all session:

```bash
# 1. Write a tiny manifest pointing at a few stems
cat > /tmp/sf_restart.json <<'JSON'
{
  "track": "sf_restart",
  "bpm": 120.0,
  "stems": {
    "drums": {
      "loops": [
        {"position": 0, "file": "/Users/zak/zacharysbrown/stemforge/export/true_love_waits/ep133/001_true_love_waits_drums_1.wav"}
      ]
    }
  }
}
JSON

# 2. Load it — needs python-rtmidi + mido
uv run --with python-rtmidi --with mido python tools/ep133_load_project.py \
  /tmp/sf_restart.json -P 7 -g C=drums -s 100 -n 1
```

### Read a project file live

```python
from stemforge.exporters.ep133.project_reader import read_project_file
content = read_project_file(project_num=7)  # returns TAR bytes
```

### Extract a real `.ppak` reference (recommended first action)

Open Chrome → [teenageengineering.com/apps/ep-sample-tool](https://teenageengineering.com/apps/ep-sample-tool) → connect
→ **Backup** button → save as `/tmp/ep133_real_backup.ppak`. No edits, just
save. That's the reference we need for the synthetic-`.ppak` path.

### Run tests

```bash
uv run pytest tests/ep133/ -q
# 108 passed
```

---

## 7. Suggested opening move next session

A single 15-minute investment with huge payoff:

1. **Record firmware version** (Settings → System → Version → note it)
2. **Run Sample Tool backup** → save as `/tmp/ep133_real_backup.ppak`
3. **Diff against our generated `.ppak`** with:
   ```bash
   unzip -l /tmp/ep133_real_backup.ppak
   unzip -p /tmp/ep133_real_backup.ppak /meta.json
   unzip -p /tmp/ep133_real_backup.ppak /settings | xxd | head -20
   ```
4. Patch `ep133_bpm_writer.py` to use the real `settings` bytes + correct
   `device_sku` + realistic timestamps
5. Try the one-pad MVP again with the patched generator

If that loads cleanly, we have programmatic per-pad-BPM writes — and
everything else in the open-questions list becomes easier.

---

*End of handoff. Good luck, next session.*
