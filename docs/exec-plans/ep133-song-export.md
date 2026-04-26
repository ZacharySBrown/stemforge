# Exec Plan: EP-133 Arrangement → Song Export

**Spec:** `specs/ep133-arrangement-song-export.md`
**Branch:** `feat/ep133-song-export`

## Track briefs (one per agent)

Each track is independent until the integration step. Agents read this file + the spec, then execute their track. All tracks must ship tests.

### Track A — Format library + .ppak writer

**Owner files (yours alone — write freely):**
- `stemforge/exporters/ep133/song_format.py`
- `stemforge/exporters/ep133/ppak_writer.py`
- `tests/ep133/test_song_format.py`
- `tests/ep133/test_ppak_writer.py`

**Read-only references:**
- `~/repos/EP133-skill/scripts/create_ppak.py` — write reference (works on real device but has bugs in note/duration encoding — see spec §"Pattern file")
- `~/repos/ep133-export-to-daw/src/lib/parsers.ts` — read reference (canonical truth)
- `~/repos/ep133-export-to-daw/docs/EP133_FORMATS.md` — format spec
- `tests/ep133/fixtures/reference.ppak` — known-good template (provided by Track D OR by user manual capture)

**Public API (must match spec exactly):** `PpakSpec`, `Pattern`, `SceneSpec`, `PadSpec`, `Event`, `build_pattern()`, `build_scenes()`, `build_pad()`, `build_settings()`, `build_ppak()`. See spec §"Component contracts" for dataclasses.

**Critical correctness checks:**
- Pattern header byte 1 = `bars` (NOT constant 0x01 — DannyDesert got this wrong)
- Pattern event byte 3 = MIDI note (NOT "column 0x3c constant")
- Pattern event bytes 5-6 = duration uint16 LE (NOT "flags 0x10 0x00")
- ZIP entries start with `/` or device shows "PAK FILE IS EMPTY"
- Settings file is 222 bytes — preserve template, only patch BPM (bytes 4-7, float32 LE)
- Tar uses POSIX format, no compression

**Tests required:**
- Round-trip every byte builder via in-Python parser
- One end-to-end build of a minimal `PpakSpec` (1 scene, 1 pattern, 1 pad, 1 sample) → assert exact byte layout at known offsets
- (Optional, nice to have) Round-trip via phones24's TS parser via subprocess — gates on whether `node` and `pnpm` are available

**Exit criteria:**
- All tests pass: `uv run pytest tests/ep133/test_song_format.py tests/ep133/test_ppak_writer.py -v`
- Lint clean for new files: `uv run ruff check stemforge/exporters/ep133/song_format.py stemforge/exporters/ep133/ppak_writer.py`
- Commit message: `feat(ep133): song-mode binary format + .ppak writer`

---

### Track B — Arrangement LOM reader (M4L JS)

**Owner files (yours alone):**
- `v0/src/m4l-js/sf_arrangement_reader.js` (NEW)
- `v0/src/m4l-package/StemForge/javascript/sf_arrangement_reader.js` (sync — keep identical to above per dual-location rule in `memory/feedback_js_source_of_truth.md`)
- `v0/tests/test_arrangement_reader.js` (or `.py` if existing test harness is Python)

**Files you may MODIFY but with care (used by other features):**
- `v0/src/m4l-js/stemforge_loader.v0.js` — wire one new message handler `exportArrangementSnapshot`. Don't touch existing logic.
- `v0/src/m4l-package/StemForge/javascript/stemforge_loader.v0.js` — sync of above

**Public message contract:**
```
exportArrangementSnapshot <output_path>
```

Writes JSON file at `<output_path>` matching the snapshot.json shape in spec §"Component contracts → snapshot.json".

**LOM properties to read (verified available in Live 12.4 beta):**
- `live_set tempo` — float
- `live_set signature_numerator` — int
- `live_set signature_denominator` — int
- `live_set cue_points` — list; each has `name` (string) and `time` (beats)
- `live_set tracks N arrangement_clips` — list; each has `file_path`, `start_time` (beats), `length` (beats), `warping`
- Beats → seconds via session BPM: `seconds = beats * 60 / tempo`

**Track filter:** only tracks with `name` ∈ {"A", "B", "C", "D"}. Use existing `findTrackByName()` helper from `stemforge_loader.v0.js`.

**Tests required:**
- M4L test harness fixture with mock arrangement → verify JSON output shape
- Edge cases: track absent (e.g., no "C" track), no clips on a track, no locators, locator at time 0

**Exit criteria:**
- Tests pass in M4L harness
- JS files synced between `m4l-js/` and `m4l-package/...` (verify with `diff`)
- Commit message: `feat(m4l): arrangement-view snapshot reader for EP-133 song export`

---

### Track C — Resolver + synthesizer + CLI

**Owner files (yours alone):**
- `stemforge/exporters/ep133/song_resolver.py`
- `stemforge/exporters/ep133/song_synthesizer.py`
- `tests/ep133/test_song_resolver.py`
- `tests/ep133/test_song_synthesizer.py`
- `tests/ep133/fixtures/sample_arrangement.json`
- `tests/ep133/fixtures/sample_manifest.json`

**Files you may MODIFY:**
- `stemforge/cli.py` — add `export-song` subcommand. Don't touch existing commands.

**Function contracts:**

```python
# song_resolver.py
def resolve_scenes(
    arrangement: dict,           # snapshot.json shape
    manifest: dict,              # stems.json shape (uses session_tracks)
) -> list[Snapshot]:
    """One Snapshot per locator. Snapshot = which clip is playing on each group."""

@dataclass
class Snapshot:
    locator_time_sec: float
    locator_name: str
    a_clip: ArrangementClip | None
    b_clip: ArrangementClip | None
    c_clip: ArrangementClip | None
    d_clip: ArrangementClip | None
```

```python
# song_synthesizer.py
def synthesize(
    snapshots: list[Snapshot],
    manifest: dict,              # for session_tracks pad lookup
    project_bpm: float,
    time_sig: tuple[int, int],
    project_slot: int,
) -> PpakSpec:
    """Convert resolver output to a PpakSpec ready for Track A's writer."""
```

**CLI:**
```bash
stemforge export-song \
  --arrangement snapshot.json \
  --manifest stems.json \
  --reference-template tests/ep133/fixtures/reference.ppak \
  --project 1 \
  --out song.ppak \
  [--mode locator]              # locator-only for v1; "bars" reserved
```

Order of operations: load arrangement + manifest → `resolve_scenes` → `synthesize` → `build_ppak` (Track A's API) → write bytes to `--out`.

**Tests required:**
- Resolver: overlapping clips (latest-started wins), no clip at locator (→ silent), file not in session_tracks (→ error with clear message), locator at exact clip-end (boundary case)
- Synthesizer: pattern dedup (same group+pad+bars → one pattern), scene mapping (snapshots correctly converted to scene rows), bars inference (small clip lengths snap to 1/2/4)
- CLI: smoke test with fixture inputs → output `.ppak` exists and parses

**Exit criteria:**
- All tests pass: `uv run pytest tests/ep133/test_song_resolver.py tests/ep133/test_song_synthesizer.py -v`
- CLI smoke test passes
- Lint clean for new files
- Commit message: `feat(ep133): snapshot resolver + song synthesizer + export-song CLI`

---

### Track D — Reference capture + integration test + workflow doc

**Owner files (yours alone):**
- `tools/ep133_capture_reference.py`
- `tests/ep133/test_song_integration.py`
- `docs/ep133-song-export-workflow.md`
- `tests/ep133/fixtures/reference.ppak` (the captured artifact — commit as binary)

**Two paths to reference.ppak:**

**Path A — Wrap existing SysEx project reader:**
1. Use `stemforge/exporters/ep133/project_reader.py:read_project_file()` to read project TAR via SysEx
2. Build `meta.json` matching the spec template
3. Wrap TAR + meta.json into ZIP with leading-slash entries → `.ppak`
4. CLI: `python tools/ep133_capture_reference.py --project 1 --out tests/ep133/fixtures/reference.ppak`

**Path B — User-provided fallback:**
- If user has manually captured a `.ppak` via Sample Tool, accept it as-is. Validate format (must contain `/projects/PXX.tar`, must contain `pads/`, `patterns/`, `scenes`, `settings`).

The capture tool should do Path A. Path B is "user already has the file in fixtures dir, no action needed."

**Integration test** (`test_song_integration.py`):
- Loads `tests/ep133/fixtures/sample_arrangement.json` (from Track C) + `sample_manifest.json` + `reference.ppak`
- Calls full pipeline: resolver → synthesizer → ppak writer
- Re-parses the resulting `.ppak` (extracts ZIP, then TAR, then walks pads/patterns/scenes)
- Asserts: pattern count, scene count, pad assignments, settings BPM matches input
- Optional: subprocess into `~/repos/ep133-export-to-daw` and run their parser via `node` if available; assert no warnings/errors

**Workflow doc** (`docs/ep133-song-export-workflow.md`):
- Step-by-step user guide (matches spec §"User experience" but expanded with screenshots-worth of detail in text)
- How to capture a reference template (point at `tools/ep133_capture_reference.py`)
- Common errors + fixes (e.g., "PAK FILE IS EMPTY" → reference template missing or wrong format)

**Exit criteria:**
- `uv run python tools/ep133_capture_reference.py --project 1 --out tests/ep133/fixtures/reference.ppak` produces a valid file (validate via integration test)
- Integration test passes: `uv run pytest tests/ep133/test_song_integration.py -v`
- Workflow doc renders cleanly (manual review)
- Commit message: `feat(ep133): reference-ppak capture tool + song-export integration test + workflow doc`

---

## Integration step (after all tracks land)

The Architect (or a dedicated integrator agent) does the following sequentially:

1. Verify all tracks pushed their commits to `feat/ep133-song-export`
2. Run full test suite: `uv run pytest tests/ -v`
3. Run lint: `uv run ruff check stemforge/exporters/ep133/`
4. Build the M4L device: `uv run python v0/src/maxpat-builder/build_amxd.py` (per memory `feedback_build_deploy_process.md`)
5. Package + install: `bash v0/build/build-pkg.sh && bash v0/build/install.sh`
6. Manual smoke test on a real song:
   - Open StemForge.als with The Champ loaded
   - Drag clips into arrangement view, place 4 locators
   - Click "EXPORT SONG"
   - Run `stemforge export-song ...` against the snapshot
   - Upload `.ppak` to EP-133 via Sample Tool
   - Verify song mode plays correctly on device

If integration smoke test fails: open issue, fix, repeat. Don't merge until on-device works.

## Coordination rules

- **Each agent claims its track** by adding a session file to `.claude/sessions/engineer-<role>-<HHmmss>.json` per CLAUDE.md
- **Don't touch other tracks' owner files** — modify-shared rules in CLAUDE.md apply
- **JS dual-location** — Track B must keep `m4l-js/` and `m4l-package/.../javascript/` in sync per `memory/feedback_js_source_of_truth.md`
- **Tests are mandatory** — no track ships without passing tests. Per project rule: "Every feature/fix needs tests."
- **Commit per track**, narrow scope, descriptive message. Per `memory/feedback_commit_hygiene.md`.

## Risk register (live)

| Risk | Owner | Status |
|------|-------|--------|
| Reference `.ppak` template missing | Track D | UNBLOCKED if user provides via Sample Tool; or Track D auto-captures via SysEx |
| `phones24` parser unavailable for cross-validation | Track A | Optional; in-Python parser is primary check |
| Live 12.4 beta `arrangement_clips` quirks | Track B | Document any LOM oddities in track commit message |
| Slot conflicts on device | Track C | Use slot 100+ range (matches hybrid loader); document in workflow |
