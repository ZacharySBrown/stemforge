# Spec: EP-133 Loader — Ecosystem Plan (Final)

**Status:** TODO — no code extraction yet. Two decision gates before publishing.
**Owner:** Zak
**Last updated:** After reviewing actual stemforge/exporters/ep133 code and krate's PROTOCOL.md / CONTRIBUTING.md.

---

## TL;DR

- Current state: a working Python EP-133 SysEx write-path implementation inside stemforge, covering upload, pad assignment, and full `PadParams` (playmode, trim, envelope, pitch, pan, amplitude, mutegroup, time_mode, time_bpm).
- It's built on phones24's TypeScript (ported) + Garrett's captures (write-path reverse-engineered) + krate's PROTOCOL.md (field names for METADATA_SET JSON, used *after* the fact to extend `PadParams`).
- krate exists and covers Layers 1–2 (transport + single-sample primitives) with 188 commits, 486 tests, and a public PROTOCOL.md. It does not cover project-level orchestration, and projects are not on krate's roadmap.
- **Do not refactor stemforge to use krate as a transport.** See "Refactor question" below.
- **Do not publish anything yet.** Resolve the `time.bpm` hang first, then open one small issue on krate to see how collaboration feels. Decide extraction after that exchange.

---

## What we actually built (accurate inventory)

Read off the archive review:

### Transport + framing (`transport.py`, `sysex.py`, `packing.py`)
- `EP133Transport`: mido-backed USB-MIDI I/O with threaded reader loop, request/response queue, macOS-safe close.
- `build_sysex` / `parse_sysex`: frame TE SysEx with identity byte, 12-bit request IDs, flags, packed payload.
- `pack_to_buffer` / `unpack_in_place`: 7-bit packing. Ported from phones24's `utils.ts`, byte-verified against Garrett's captures.
- `RequestIdAllocator`: matches phones24's +1 mod 4096 scheme.
- Heritage: ported from phones24's TypeScript, independent of krate.

### Payloads (`payloads.py`, `commands.py`)
- `build_file_init`, `build_file_info` — ported from phones24.
- `build_file_put_meta`, `build_file_put_data`, `build_file_put_terminator` — reverse-engineered from Garrett's `.syx` fixtures (30 messages representing a single kick upload to slot 1). These are **not** in phones24 (phones24 is read-only).
- `build_metadata_set` — write-path complement to phones24's FILE_METADATA_GET. Wire format confirmed via MIDI Monitor captures across 8 pad assignments (projects 1/2/3/5/7, groups A/B/C/D, pad_nums 1/3/5/7/10/12).
- `pad_file_id(project, group, pad_num)` — confirmed formula: `3200 + (project-1)*1000 + group_index*100 + pad_num`. Matches krate's formula with different base arithmetic (krate's `2000 + (project × 1000) + 100 + group_offset + file_num` → same addresses).
- `PAD_LABEL_TO_NUM` — maps physical pad labels (`7`, `.`, `ENTER`, etc.) to visual pad numbers 1..12. Not in krate's PROTOCOL.md.
- `PadParams` dataclass — validated playback parameters including playmode, sample_start/end, envelope attack/release, pitch, amplitude, pan, mutegroup, time_mode, time_bpm. Field names and allowed values sourced from krate's PROTOCOL.md (after-the-fact extension). `time.bpm` is the one field name guessed following the dot-namespace convention and **not yet confirmed on device**.
- `build_assign_pad` — composes slot assignment and full PadParams into a single METADATA_SET message.

### Client (`client.py`)
- `EP133Client.upload_sample(wav, slot)` — end-to-end WAV → raw PCM → chunked upload → FILE_INFO commit.
- `EP133Client.assign_pad(project, group, pad_num, slot, params=None)` — single-message pad assignment with optional PadParams.
- `EP133Client.apply_pad_assignments(assignments)` — bulk dispatch over an iterable of `EP133PadAssignment`.
- Request/response correlation via 12-bit request IDs with timeout and stale-response filtering.

### Orchestration (`tools/ep133_load_project.py`)
- Reads a stemforge `manifest.json`, plans slot/pad/group layout, executes upload + assign for every op.
- Supports `--dry-run` for plan preview.
- Supports `--update-params` for metadata-only pushes (the path currently hanging on `time.bpm`).
- Writes a JSON load report post-run.
- Confirmed working: 48 samples × 2 tracks loaded successfully on 2026-04-23 (minus the `--update-params` issue).

### Audio (`audio.py`)
- `wav_to_ep133_pcm`: WAV → raw 16-bit LE mono PCM at 46875 Hz via soundfile + librosa.
- Stereo is downmixed; floats are clipped then scaled to int16.
- No TNGE metadata chunk written (EP-133 ingests raw PCM, not WAV, so not needed for this code path).

### Tests (`tests/ep133/`)
- `test_packing.py`, `test_payloads.py`, `test_assign_pad.py` — payload-level unit tests with fixtures.
- `conftest.py` — test harness.
- `fixtures/` — 30 kick upload `.syx` files, 8 pad-assign `.syx` files covering the projects/groups listed above.

### Specs + docs
- `specs/ep133_port_spec.md`, `specs/ep133_sysex_port_spec.md`, `specs/ep133_sysex_upload_plan_v2.md` — working notes on the port from phones24.
- `specs/ep133_pad_assign_capture_plan.md` + `_progress.md` — the pad-assign capture sessions that validated the fileId formula.
- `docs/ep133-archive-roundtrip-capture.md` — planned but unused approach (read/patch/rewrite `/projects/NN` tar archives). Superseded by the FILE_METADATA_SET approach once krate's field names were available.

---

## What's in the current code that krate doesn't have

Being strict about what's *ours* vs *Ivan's* vs *phones24's*:

1. **`PadParams` as a validated Pythonic API** — the dataclass, its post-init validation, its `to_json(slot)` method. krate doesn't expose this; it's just Python ergonomics on top of Ivan's documented fields.
2. **Composable `build_assign_pad(params=...)`** — writes slot + full parameters in a single METADATA_SET message. krate's client may or may not support this composition (didn't review every module; worth checking).
3. **`PAD_LABEL_TO_NUM` physical-to-visual mapping** — small, concrete, absent from PROTOCOL.md.
4. **Expanded pad fileId capture coverage** — 5 projects × 4 groups × 6 pad_nums vs krate's "A fully confirmed, B/C/D confirmed at 2 points each."
5. **The `time.bpm` field name guess** — unverified. Might be a contribution, might be wrong.
6. **Project-layer orchestration** — `tools/ep133_load_project.py` takes a manifest and executes a full library load. krate has nothing at this layer and it's not on his roadmap.
7. **Independent Python transport/framing implementation** — functionally duplicative with krate's Layer 1, but phones24-heritage rather than capture-heritage.

Items 1–5 are small. Item 6 is the real distinctive value. Item 7 is redundant with krate but not harmful to keep.

---

## Refactor question: should we swap to krate's transport?

**No.**

Reasons:

1. Your transport is ~150 lines, well-structured, and works. Replacing it costs time and creates dependency risk.
2. krate is a solo project. Hard-depending on someone else's unreleased-on-PyPI code for your production pipeline is fragile.
3. `UploadTransaction` in krate does its own VERIFY/METADATA_SET dance with defaults baked in. If Ivan's defaults don't match what you need (relevant for the current `time.bpm` debugging), you're fighting his API.
4. The refactor solves no problem you actually have. `time.bpm` is a field-name / session-state question, not a transport question.
5. If you decide to publish a sibling repo later, the "thin layer on krate" framing is a choice to make *then*, not a pre-commitment to make now.

**The one place to borrow from krate today:** capture format. If you record new `.syx` sessions, use a jsonl format compatible with his `midi_proxy.py --pretty` so captures are directly shareable. Zero-cost alignment.

---

## Two blocking questions (resolve before any publish decision)

### Q1: Does `time.bpm` actually work?

The `--update-params` run hung. Three hypotheses, in decreasing likelihood:

1. **Wrong field name.** `time.bpm` followed the dot-namespace convention but wasn't in PROTOCOL.md. Could be `time.tempo`, `sound.time.bpm`, or something else entirely.
2. **Pads require a prior FILE_PUT in the same session** before accepting metadata writes. The first run uploaded + assigned fine; the `--update-params` re-run hit pads that were previously-written but not this-session-written.
3. **Value encoding issue.** The BPM was `156.60511363636363`; maybe the device wants an integer, or a specific precision, or something else.

**Action:** capture the TE web tool's traffic when a user sets time mode to BPM on a pad via the UI. Do this as part of the expanded capture session (see "Expanded capture session" below) — don't do a standalone single-gap capture when you could pick up 3+ contributions in the same 15-minute window.

This is a small, well-scoped experiment. Do this first *after* filing the pad-coverage opener to Ivan.

### Q2: How does Ivan respond to a first contact?

Outreach strategy (see "Outreach" below) is to open one small, concrete issue that's genuinely useful to him — not to pitch collaboration on a big sibling repo. His response calibrates every later decision.

---

## Expanded capture session (do this once, get multiple contributions)

Ivan's PROTOCOL.md "Protocol Gaps" section lists five named unknowns. Several are achievable with the same MIDI Monitor setup already used for pad-assign captures. A single ~15-minute session can resolve the `time.bpm` question AND produce 3–4 additional PROTOCOL.md contributions.

### Gaps ranked by effort × value for us

**Green — capture these:**

1. **Pad mapping for groups B/C/D** — already done. 8 captures across projects 1/2/3/5/7, groups A/B/C/D, pad_nums 1/3/5/7/10/12. Widens Ivan's "B/C/D confirmed at 2 points each." *This is the opener regardless.*

2. **`time.bpm` + `time.mode=bars` encoding** — resolves Q1 blocker AND partial PROTOCOL.md contribution. Set a pad's time mode to BPM via the TE Sample Tool UI, capture the SysEx, note field name, value type (int/float/string), and precision. Repeat for `bars` mode.

3. **Device info TX (0x77/0x78)** — Ivan has the RX response format but not the TX request. Almost trivial to capture: connect the device, capture the first 10 seconds of startup handshake. Sample Tool must be sending *something* to populate firmware version / device name / serial.

4. **Memory stats TX** — Ivan has the `free_space_in_bytes` RX payload but not the TX command that triggers it. Capture 30 seconds of Sample Tool idle after full connect. The UI shows free space, so the tool must be polling it. Correlate RX payload → preceding TX.

**Yellow — try if time allows:**

5. **Project listing (0x7C)** — capture traffic when switching projects or opening any project-picker UI. May reveal a list command; may reveal there is no list command (the tool just probes each project slot), which is *also* a useful finding.

6. **Sound edit / FX / filter params** — your archive roundtrip doc (`docs/ep133-archive-roundtrip-capture.md`) has field names for parameters not yet in `PadParams`. Capture the Sample Tool sending FX/filter edits if the UI supports them. Caveat: some parameters may be device-only (unsettable from Sample Tool) — check before investing time.

**Red — skip:**

7. **Playback trigger (0x76)** — the trickiest of Ivan's gaps. Not what stemforge needs. Let someone else get it.

8. **`.ppak` SysEx extraction** — superseded by the FILE_METADATA_SET approach now that playmode/envelope/etc. are writable directly. Don't restart the round-trip work.

### One-sitting capture plan (~15 min)

With MIDI Monitor running and filtered to "To EP-133" SysEx:

1. **Fresh device connect** → captures device info handshake (gap #3). 30 seconds.
2. **Open Sample Tool, wait for full UI load** → captures memory stats polling (gap #4). 1–2 minutes.
3. **Set a pad to `time.mode=bpm`, then set another to `time.mode=bars`** → confirms `time.bpm`, picks up bars encoding (Q1 + gap #2). 2 minutes of UI clicking.
4. **Try setting any FX / filter / sound edit params via Sample Tool** → may or may not capture anything. If it does, expands `PadParams` + fills gap #6. 5 minutes.
5. **Switch projects / open project picker if one exists** → may capture project listing (gap #5). 2 minutes.

Clear the MIDI Monitor log between each step so captures stay discrete and decodable.

### Session hygiene

- Start each step from a known state (clear log, fresh pad, note exact UI values).
- Record what you *did* in each step alongside the hex. Future-you will not remember.
- Save each capture as a separate `.syx` or jsonl file named after the step.
- If any capture looks surprising, repeat it once — confirmation over speed.

### Don't bundle into one issue

Four small merged PRs beats one big one. Each merge is a positive signal; each issue is a discrete conversation. File in this order:

1. Pad coverage (highest confidence, smallest change) — opener.
2. `time.bpm` confirmation (resolves your blocker, genuinely useful to Ivan).
3. Device info TX (if captured).
4. Memory stats TX (if captured).
5. Anything else only after 1–4 have been engaged with.

---

## Outreach

### Ivan — one small issue first

**Do not open with "I want to build on your stuff and have a big plan."** That's a lot of words for a maintainer to absorb and respond to, and you haven't earned the meeting yet.

**Do open with something specific, small, and useful.** Best candidate: your expanded pad fileId coverage. You have captures across more projects/groups/pad_nums than his current confirmation set. That's a PROTOCOL.md addendum he can merge in ten minutes and it establishes you as someone who contributes data.

**File this FIRST, even before doing the expanded capture session.** It's already done. Don't delay it waiting for more captures — shipping the small thing gets feedback faster.

**Draft (opener — pad coverage only):**

> **Title:** Additional pad node coverage — projects 2/3/5/7, all groups, more pad_nums
>
> Hi Ivan,
>
> I've been working on a Python EP-133 write-path tool for my own stem pipeline and independently captured the pad-assign formula across a broader set than PROTOCOL.md currently confirms. Your formula (`2000 + project×1000 + 100 + group_offset + file_num`) matches my captures exactly across:
>
> - Projects: 1, 2, 3, 5, 7
> - Groups: A, B, C, D (all four)
> - pad_num values: 1, 3, 5, 7, 10, 12
>
> Happy to share the capture fixtures if useful for the test suite, or to PR a PROTOCOL.md note widening the "Group A fully confirmed; B/C/D confirmed at 2 points each" line to reflect the broader coverage.
>
> Also — a small question while I'm here. I extended my pad-params code to include a `time.bpm` field (for `time.mode=bpm`), guessing the name from your dot-namespace convention. My device hangs when I try to push it. Two hypotheses: the field name is wrong, or pads reject metadata writes when no FILE_PUT has occurred in the current session. Have you seen either in your captures? I'm planning a capture session of my own to figure it out either way.
>
> Thanks for PROTOCOL.md — it unblocked the sample-behavior work I was about to reverse-engineer the hard way.

**Why this works:**
- Lead is a contribution, not a request.
- Question is specific and he might actually know (and signals you're not helpless — you'll capture if needed).
- Closing credit is honest: his doc saved you work.
- Doesn't pitch a collaboration. Leaves room for one without forcing it.

### Follow-up issues (after the capture session + after opener gets a response)

Assuming the opener lands well, file discrete follow-ups — one per finding, each small and specific. Order:

1. **`time.bpm` + `time.mode=bars` encoding** — resolves the hanging question plus adds wire format for two time modes. File only after confirming on-device.
2. **Device info TX request** — if captured, send decoded hex + your reading of the wire format.
3. **Memory stats TX command** — same pattern.
4. **Anything else from the yellow list** — only if genuinely well-decoded.

Each follow-up is its own issue, titled specifically (e.g., "time.bpm field encoding — confirmed", "Device info TX request format"). This gives Ivan discrete merge decisions rather than one overwhelming omnibus PR.

**If he merges the opener and engages on the question:** you have an opened door. *Then* you can say "I've been building a project-orchestration layer on top of this — would be curious whether projects fit krate's scope or whether you'd prefer I publish separately." That conversation happens with you as a contributor, not a stranger.

**If he's quiet on the opener:** no harm done. You contributed something small. Wait 2 weeks, decide whether to publish independently or not at all. Don't pile on more issues while the first one is unanswered.

**If he declines the PR for any reason:** unusual but it happens. Proceed on your own; you lose nothing by having offered.

### Danny, phones24, op-forums

Defer. Whether to post to op-forums or contact Danny depends on whether you extract + publish, which depends on Q2 above. Don't preemptively announce.

---

## Three options after the Ivan exchange

Decide after Q1 and Q2 resolve. Don't commit now.

### Option A — Don't extract, contribute only

- Keep the loader inside stemforge.
- Contribute small protocol findings to krate via issues/PRs.
- stemforge stays proprietary (or is open-sourced later on its own merits, separate decision).
- **Best if:** your primary interest is stemforge; maintenance burden of an OSS library doesn't appeal; Ivan is receptive to contributions and that's enough community presence.
- **Cost:** zero marginal work beyond what you'd already do.
- **Benefit:** no maintenance burden, still establishes you in the ecosystem via contributions.

### Option B — Publish a small focused library

- Extract just the `PadParams` + `build_assign_pad` + `pad_file_id` + pad label mapping into a minimal library.
- Don't publish the transport layer — either bring your own mido, or (later) accept a krate client as a dependency-injection point.
- Scope is small enough that maintenance is light.
- README is honest: "Pythonic API for EP-133 pad parameters, built on protocol work by icherniukh/ep133-krate."
- **Best if:** you want a small OSS artifact without the full transport-maintenance surface.
- **Cost:** moderate — extraction, API polish, one release.
- **Benefit:** real repo with your name on it, scoped small enough not to compete with krate.

### Option C — Publish the full independent write-path library

- Extract everything: transport, framing, payloads, client, orchestration.
- README is honest: "Independent Python implementation of the EP-133 write path. For single-sample management and device TUI, see icherniukh/ep133-krate."
- Maintenance burden is real — you own transport bugs, firmware regressions, cross-platform MIDI issues.
- **Best if:** you genuinely want to be the "EP-133 Python write-path" person and are willing to carry the cost.
- **Cost:** higher — extraction, CI, platform testing, ongoing support.
- **Benefit:** maximum independence; no coordination overhead; you control the roadmap.

### My read

Option A is the boring right answer unless you have a specific reason otherwise. Option B is the goldilocks if you want an artifact without the burden. Option C is justifiable only if Ivan is non-responsive AND you want this to be a real thing you maintain.

---

## Things to keep regardless of direction

- **Capture new sessions in krate-compatible jsonl** going forward. Tiny cost, ecosystem-friendly.
- **Keep the pad-assign capture progress doc** — the 8 captures with decoded hex are directly useful as protocol contributions.
- **Don't fall for sunk cost.** You built good code. That doesn't mean it needs to be a public repo. The highest-leverage move might be to contribute findings upstream and keep the implementation private.
- **Treat raindog artifact value as secondary.** The narrative "I contributed to the EP-133 Python ecosystem" is strong whether or not you publish your own repo. Ivan merging a small PR from you is legitimately more credible than a stars-count on a sibling repo.

---

## Checklist (ordered)

**Phase 1 — opener (do this first, don't wait):**
- [ ] Draft the Ivan issue using the pad-coverage opener above. Personalize the capture-sharing offer.
- [ ] File it. Do not wait for the capture session — ship the small thing first.

**Phase 2 — capture session (~15 min on-device):**
- [ ] Capture device info TX (fresh connect, 30 sec).
- [ ] Capture memory stats TX (Sample Tool idle polling, 30–60 sec).
- [ ] Capture `time.mode=bpm` set on a pad. Decode field name + value encoding.
- [ ] Capture `time.mode=bars` set on a pad. Same decode.
- [ ] (Optional) Capture FX/filter/sound edit params if Sample Tool exposes them.
- [ ] (Optional) Capture project switching for project listing inference.

**Phase 3 — blocker resolution + follow-up PRs:**
- [ ] Fix `--update-params` based on `time.bpm` findings.
- [ ] File separate follow-up issues (one each) for confirmed findings, paced to Ivan's response.

**Phase 4 — decide on extraction (after Q1 + Q2 resolve):**
- [ ] Wait 2 weeks from opener for Ivan's response to shape direction.
- [ ] Revisit this spec with real information. Pick A, B, or C.
- [ ] If B or C: verify repo/PyPI name availability, write README, add attribution, ship.
- [ ] If A: move on, keep contributing.

---

## Non-goals

- No generic GrooveboxTarget abstraction. Defer until target #2.
- No beat/pattern programming. Danny's skill covers it for `.ppak`; not our scope for SysEx.
- No EP-40/EP-1320 support. KO II only.
- No GUI. ep-patch.studio's lane.
- No parallel PROTOCOL.md. Ivan owns that doc; we contribute to it.
- No commercial offering of this library. If raindog sells something, it's a higher-level stemforge product, not EP-133 plumbing.

---

## Next session (from 2026-04-23 build session)

### Immediate unresolved issues

**`sound.playmode` via FILE_METADATA_SET is unconfirmed writable.**
Running `--update-params --playmode key` set all pads to oneshot behavior — the opposite of intended. Two hypotheses: (a) `sound.playmode` is read-only on pad fileIds and can only be set via the project archive write path (TAR round-trip, byte [23] of each pad file), or (b) the full `PadParams` JSON we write resets something that causes the device to apply defaults. Quick probe: send a minimal `{"sym":700,"sound.playmode":"key"}` to one pad's fileId and observe behavior. If that doesn't work, the archive path is required.

**`--update-params` hung on first run.**
The first invocation (without `--playmode`, only `time_mode=bpm + time_bpm`) hung indefinitely — no response from the device. Possible causes per the doc above (wrong field name, session-state requirement, value encoding). Resolve via the capture session in Phase 2.

**`time.bpm` field name is unconfirmed.**
We guessed it from the dot-namespace convention. It's the most likely cause of the hang. Resolve by capturing the TE Sample Tool setting `time.mode=bpm` on a pad.

### Code state as of end of session

All in `stemforge/exporters/ep133/` and `tools/ep133_load_project.py`:

- `PadParams` dataclass is complete and tested (192 tests passing).
- `build_assign_pad(... params=PadParams)` is wired end-to-end through client.
- `--update-params --playmode <mode>` flag exists and runs without error, but playmode change is unconfirmed working.
- `--update-params` with only BPM hangs (unresolved).
- Archive round-trip (read `/projects/NN`, patch pad files, write back) is NOT implemented. It's the fallback if `sound.playmode` via metadata SET doesn't work.

### Confirmed working as of 2026-04-23

- Upload WAV → EP-133 library slot (slots 1–65535, u16 BE confirmed)
- Pad assignment via `{"sym": slot}` — 48 pads loaded across 2 songs (beware P1 slots 700–747, SMBU P8 slots 200–247)
- `apply_pad_assignments` + `assign_pad` with `params=None`

### Confirmed NOT working / unverified

- `sound.playmode` write via FILE_METADATA_SET on pad fileId
- `time.bpm` / `time.mode=bpm` push
- Any `PadParams` field other than `sym` — none have been confirmed applied by the device

### If archive round-trip is needed

The plan is already documented in `docs/ep133-archive-roundtrip-capture.md`. Binary pad file layout is known (from phones24 `parsers.ts`). Key byte:

| Byte | Field | Values |
|------|-------|--------|
| 23 | playMode | 0=oneshot, 1=key, 2=legato |

Implementation path: `FILE_METADATA_GET` on the project fileId to get the archive, untar, patch `pads/{group}/p{pad_num:02d}` byte [23], retar, `FILE_PUT` the archive back. No new protocol reverse-engineering needed — it's pure file manipulation on top of what we already have.
