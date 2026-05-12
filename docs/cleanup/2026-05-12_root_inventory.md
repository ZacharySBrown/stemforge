# Root cleanup inventory — 2026-05-12

**Author:** Operator (worktree `agent-a27c1390d8714abdf`, branch `chore/phase2-cleanup-audit`).
**Status:** Phase 2 cleanup audit. Most items are *recommendations* — destructive actions wait on explicit user OK per the handoff brief ("many of these are user work-in-progress").

**PR target:** `integration/handoff-2026-05-12` (not `main`).

This doc covers:
1. Inventory + categorization of every untracked root-level item.
2. The safe items I executed in this branch.
3. Items needing user decision before action.
4. `tools/` packageability fix (Phase 2 task 5 in the handoff brief).
5. `docs/` link integrity.
6. Memory hygiene report.
7. `.claude/worktrees/` disposition (audit only).

---

## 1. Inventory

Categories used:
- **COMMIT(path)** — move to a sensible home and commit.
- **MOVE→.local/** — user work-in-progress; relocate to a gitignored `.local/` tree.
- **MOVE→docs/...** — committable as docs.
- **GITIGNORE** — leave on disk but exclude from git.
- **DELETE** — safe to remove; either already superseded or scratch.
- **ASK USER** — recommendation but I will not act without explicit OK.
- **AUTO-DONE** — handled in this branch.

### Root files

| Path | Type | Size/Note | Recommended | Rationale |
|------|------|-----------|-------------|-----------|
| `DUMP` | text file | 1005 lines (~92K); 3 sections: mus-tree, organize-log, prose docs | **ASK USER** (preferred: MOVE→`.local/mus/` split into 3 files) | Per `docs/issues/dump-file-split.md`: split into `.local/mus/mus_tree.txt` + `mus_events.log` + `mus_setup.md` + add refresh script. Currently untracked. Splitting now requires moving user-only content (the live mus tree) — escalate. Will note in PR. |
| `EP133_DEBRIEF.md` | tracked file | 165 lines, committed in PR #62 | **AUTO-DONE: delete** | Per `docs/issues/ep133-debrief-disposition.md`. Confirmed via grep: only references are in docs already noting its supersession (`docs/sessions/2026-05-12_breaks_n_beats_complete.md`, the handoff brief, and the disposition issue file itself). |
| `EXPORT_CONFIGURATOR_BUNDLE.md` | file | 546 lines, dated 2026-05-04 | **MOVE→`docs/configurator/research/`** | Research bundle prepared for a claude.ai design conversation. Not stale, but root-of-repo is wrong home. Group with other configurator research. |
| `EXPORT_CONFIGURATOR_TESTABILITY_BUNDLE.md` | file | 513 lines | **MOVE→`docs/configurator/research/`** | Same as above. |
| `EXPORT_CONFIGURATOR_TEST_HARNESS_PRIOR_ART.md` | file | 179 lines | **MOVE→`docs/configurator/research/`** | Same. |
| `EXPORT_CONFIGURATOR_UX_PATH_INVENTORY.md` | file | 344 lines | **MOVE→`docs/configurator/research/`** | Same. |
| `STEMFORGE_CONFIGURATOR_SPEC_v2.md` | file | 422 lines | **MOVE→`docs/configurator/archive/`** (or DELETE) | Superseded by v3 in root and v4 in `new_specs/`. Keep as history under archive/, or delete — escalate. ASK USER. |
| `STEMFORGE_CONFIGURATOR_SPEC_v3.md` | file | 624 lines | **MOVE→`docs/configurator/archive/`** (or DELETE) | Superseded by v4 in `new_specs/`. Same disposition as v2. ASK USER. |
| `TOP3_TUNING_ANSWERS.md` | file | 199 lines | **ASK USER** | Personal executive-planner tuning project — not related to StemForge core. Personal scratch; user might want under `.local/`. Don't move blindly. |
| `TOP3_TUNING_BRIEF.md` | file | 359 lines | **ASK USER** | Same. |
| `TOP3_TUNING_COMPLETION_REPORT.md` | file | 245 lines | **ASK USER** | Same. |
| `TOP3_TUNING_HANDOFF_UPDATE.md` | file | 822 lines | **ASK USER** | Same. |
| `log` | text file | 118 lines; EP-133 SysEx probe output | **AUTO-DONE: MOVE→`docs/ep133-song-triage/ep133-pad-slot-metadata-probe-2026-05-11.txt`** + add `/log/` to `.gitignore` | Per `docs/issues/log-file-collision.md`. File mtime is 2026-05-11. |

### Root directories

| Path | Type | Size | Recommended | Rationale |
|------|------|------|-------------|-----------|
| `artifacts/` | dir | ~3.0 GB | **AUTO-DONE: GITIGNORE** | `artifacts/README.md` claims it's already gitignored but it isn't. Add `/artifacts/` to `.gitignore`. README stays in working tree; content (ONNX exports) was always intended to be local-only. |
| `backups/` | dir | ~2.8 MB | **AUTO-DONE: GITIGNORE** | Contains an EP-133 device backup (`.ppak`) + a `.dontindex` sentinel. User-specific device state; not commit material. Add `/backups/` to `.gitignore`. |
| `export/` | dir | small | **GITIGNORE** | Per-track per-target export staging (`go_spastic/`, `nude/`, etc. each with `ep133/` subdir). Pipeline output, regeneratable. Add `/export/` to `.gitignore`. |
| `new_specs/` | dir | ~80K | **MOVE→`docs/configurator/specs/`** (v4 only) | `STEMFORGE_CONFIGURATOR_SPEC_v4.md` is the **active** spec per the spec text itself (and `PHASE_3_FRESH_SESSION_HANDOFF.md` confirms). Move v4 into docs as canonical. ASK USER on `STEMFORGE_TOP3_WORKFLOWS.md` and `VERSE_SWAP_DECK_PLAN.md`. |
| `research/` | dir | ~48K | **MOVE→`docs/research/`** | Contains `stemforge_lit_review.md` + `stemforge_implementation_roadmap.md`. Real research content; belongs under docs. |
| `targets/` | dir | ~32K | **MOVE→`docs/targets/`** or **DELETE** | Contains `koala.py`, `koala.zip`, `cli_koala.py`, `test_koala_exporter.py` — reference impl of the Koala app exporter (related to but separate from EP-133). ASK USER whether to keep as reference or drop. |
| `tbstemmed/` | dir | ~3.1 GB | **GITIGNORE** | Large FLAC/WAV source audio (Aphex Twin, ATCQ etc.). User music files, blatantly not commit material. Add `/tbstemmed/` to `.gitignore`. |
| `.vscode/` | dir | 8K | **AUTO-DONE: GITIGNORE** | Contains `settings.json` with `cmake.sourceDirectory` pointing at `v0/src/A`. Editor config; per-user. Add `.vscode/` to `.gitignore`. |

### `.claude/` items

| Path | Type | Note | Recommended | Rationale |
|------|------|------|-------------|-----------|
| `.claude/sessions/engineer-161737.json` | file | started 2026-05-02 | **AUTO-DONE: delete** | Per CLAUDE.md startup protocol: "Delete any file older than 4 hours". 10 days old. |
| `.claude/sessions/engineer-201502.json` | file | started 2026-05-08 | **AUTO-DONE: delete** | Same. 4 days old. |
| `.claude/sessions/engineer-aoj-batch.json` | file | started 2026-04-30 | **AUTO-DONE: delete** | Same. 12 days old. |
| `.claude/worktrees/.dontindex` | file | empty sentinel | **LEAVE** | Tells indexing to skip. Documented behavior. |
| `.claude/worktrees/curation-library-router/` | worktree | branch `feat/curation-library-router` | **CHERRY-PICK & RETIRE** — ASK USER | 7 commits ahead of main; 55 behind. See worktree report below. Has unmerged value (router, init_library, song-form docs). Per `feedback_curation_library_v2_branch_direction.md`: one-way, never merge OUT without explicit user OK. |
| `.claude/worktrees/tempo-detection-half-time/` | worktree | branch `feat/m4l-locator-anchor` | **RETIRE** — ASK USER | 0 commits ahead of main; 58 behind. Branch was merged via PR #37 long ago. Worktree is stale leftover. Safe to `git worktree remove`, but per CLAUDE.md/handoff this requires explicit user OK. |

### `specs/` items (untracked)

| Path | Type | Recommended | Rationale |
|------|------|-------------|-----------|
| `specs/EP-133-KO-II-Guide.pdf` | 16 MB PDF | **GITIGNORE** + ASK USER | Vendor manual. Identical bytes to `docs/EP-133-KO-II-Guide.pdf` (also untracked) — duplicate. Pick one home and gitignore both spots (16 MB×2 not commit material). |
| `docs/EP-133-KO-II-Guide.pdf` | 16 MB PDF | **GITIGNORE** + ASK USER | Same duplicate; recommend keeping `specs/` copy as canonical (specs/ is the "vendor doc" home per CLAUDE.md) and removing `docs/` copy. |
| `specs/files (1).zip` | zip file | **DELETE** — ASK USER | Generic download artifact name. Almost certainly a one-off. Investigate or drop. |
| `specs/ep133_morning_briefing_2026-04-26.md` | file | **MOVE→`docs/sessions/`** | Per handoff brief Phase 3 task 4: "Migrate session-handoff specs out of `specs/` (where briefings get scattered) into `docs/sessions/` consistently." Rename to `2026-04-26_ep133_morning_briefing.md` for consistency with the existing session-debrief filename pattern. |
| `specs/ep133_session_handoff_2026-04-25_eod.md` | file | **MOVE→`docs/sessions/`** | Same; rename `2026-04-25_ep133_session_handoff_eod.md`. |
| `specs/tlw_rebounce_handoff_2026-04-26.md` | file | **MOVE→`docs/sessions/`** | Same; rename `2026-04-26_tlw_rebounce_handoff.md`. |

### `tools/` items (untracked)

| Path | Type | Recommended | Rationale |
|------|------|-------------|-----------|
| `tools/batch_grooves.sh` | shell script | **AUTO-DONE: COMMIT** | Per session debrief: "one-time use, kept for reproducibility." Real Phase-2 spec mandated commit. |
| `tools/batch_grooves_overrides.sh` | shell script | **AUTO-DONE: COMMIT** | Same. |

### `v0/src/` items (untracked, **OUT OF OPERATOR SCOPE**)

| Path | Type | Recommended | Rationale |
|------|------|-------------|-----------|
| `v0/src/m4l-package/StemForge/presets/drums_only.json` | preset | **ASK USER** (engineer scope) | Looks like a real preset addition; matches existing pattern. `v0/src/` is Engineer scope per CLAUDE.md. Don't touch from Operator role. |

### `presets/` modified-tracked

| Path | Type | Recommended | Rationale |
|------|------|-------------|-----------|
| `presets/clean.json` | tracked, M | **ASK USER** | Per `docs/issues/presets-clean-json-disposition.md`. Color-schema refactor — needs decision before commit/revert. Out of scope here. |

---

## 2. Auto-resolved items (executed in this branch)

These were committed as small focused commits:

1. **Stale session files deleted** — `.claude/sessions/engineer-{161737,201502,aoj-batch}.json` removed per CLAUDE.md startup protocol (all 4+ days old, regeneratable bookkeeping).
2. **`EP133_DEBRIEF.md` deleted** — superseded by `docs/sessions/2026-05-12_breaks_n_beats_complete.md`. Confirmed no inbound code/doc references beyond the supersession notes themselves.
3. **`log` → `docs/ep133-song-triage/ep133-pad-slot-metadata-probe-2026-05-11.txt`** + added `/log/` to `.gitignore`.
4. **`.gitignore` additions** — `/artifacts/`, `/backups/`, `/export/`, `/tbstemmed/`, `.vscode/`. (Plus `/log/` from #3.)
5. **`tools/batch_grooves.sh` + `tools/batch_grooves_overrides.sh` committed** as one-shots with explanatory commit message.
6. **`pyproject.toml` setuptools `find` → explicit `include` for `tools.sf_remote` only** (Phase 2 task 5 — see section 4).

I deliberately did **not** move `EXPORT_CONFIGURATOR_*` / `STEMFORGE_CONFIGURATOR_SPEC_v{2,3}.md` / `research/` / `new_specs/` in this branch. Each is a meaningful set of moves and the user should sign off on the destination tree (especially the v2/v3 archive vs. delete question) before I move 5+ MB of documentation around. Listed as recommendations in section 3 instead.

## 3. Items needing user decision (top of mind)

In rough priority order:

1. **`DUMP` split** — recommended split into `.local/mus/{tree,events,setup}.{txt,log,md}` per the issue file. Requires fresh capture of `~/mus/` tree (user-side) and a new `tools/refresh_mus_dump.sh`. I can do the split mechanically; refresh has to be user-driven because of sandbox.
2. **`tbstemmed/` (3.1 GB) + `artifacts/` (3.0 GB)** — recommend gitignore now (done in this branch) but want to confirm: are any files under these paths referenced by tests / fixtures? Spot-checked: no references in `tests/`. Confirming.
3. **`EXPORT_CONFIGURATOR_*` + `STEMFORGE_CONFIGURATOR_SPEC_v{2,3}.md`** — happy to move into `docs/configurator/{research,archive}/` in a follow-up commit if you OK the destination paths. Or delete v2/v3 (superseded by `new_specs/STEMFORGE_CONFIGURATOR_SPEC_v4.md`).
4. **`TOP3_TUNING_*` (4 files, ~1600 lines total)** — completely unrelated to StemForge as far as I can tell. Recommend `.local/` rather than docs/. Confirm?
5. **Worktrees** — `tempo-detection-half-time` is stale (branch already merged via PR #37). `curation-library-router` has 7 commits of router/init_library/song-form-docs work — memory says cherry-pick. Both need explicit OK before `git worktree remove`.
6. **`specs/files (1).zip`** — unknown contents; investigate or drop.

## 4. `tools/` packageability — pyproject.toml

PR #62 set `include = ["stemforge*", "tools*"]` to make `sf-remote` console script installable. The `tools*` glob means any future `tools/<subpackage>/` directory gets vacuumed up into the wheel.

**Today the scope is identical** because `tools/` has only the one `__init__.py` (no nested packages). Verified via `setuptools.find_packages`: both `["stemforge*", "tools"]` and `["stemforge*", "tools*"]` resolve to the same list of 8 packages. The only setuptools-`find`-able package under `tools/` is `tools` itself.

**Change applied:** `include = ["stemforge*", "tools*"]` → `include = ["stemforge*", "tools"]`. This is a forward-protection: if someone later adds `tools/scripts/` with an `__init__.py`, the wheel won't silently include it. Verified `uv run sf-remote --help` still works after `uv pip install -e .`.

**Stricter fix not applied:** the brief's option (b) — split `tools/` into `tools/cli/` (packaged) + `tools/scripts/` (not packaged) — is invasive and touches the `sf-remote` entry point. That's an Engineer-scope refactor; not safe to take in this audit pass. Flagged as a followup.

## 5. `docs/` link integrity

Greped every relative `](../` link in `docs/{issues,sessions,handoff}/*.md`. Results:

- All cross-doc links resolve. No broken `(../issues/<name>.md)` references.
- Memory links from `docs/sessions/2026-05-12_breaks_n_beats_complete.md` (e.g. `(../../../.claude/projects/.../memory/feedback_arrangement_clip_lom.md)`) all resolve.
- The session-debrief references `EP133_DEBRIEF.md` as `(../../EP133_DEBRIEF.md)` — **this link will break** once the file is deleted (auto-done item #2). Acceptable: the surrounding text says "supersedes the in-tree EP133_DEBRIEF.md (which is now redundant)". The link will 404 but the context makes it clear what was there. Could rewrite to "previously at `EP133_DEBRIEF.md`, deleted in commit `<sha>`" for tidiness. **AUTO-DONE: rewrote the link to plain text** so the doc remains clean.

## 6. Memory hygiene

Reviewed `/Users/zak/.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/MEMORY.md` (66 entries). All linked files exist; no broken `(file.md)` links.

### Entries that look stale (recommend retire or update — DO NOT EDIT WITHOUT USER OK)

| Entry | Why stale | Recommended action |
|-------|-----------|--------------------|
| `project_ui_v2_debug_state.md` (line 4) | 2026-04-22 EOS snapshot; loader code has shipped through ~30 commits since | Mark superseded by `project_v0_state.md`, or delete |
| `project_bounce_v1_state.md` (line 42) | "Awaiting user OK to commit" — the fix shipped in `feat/curation-engine-v2` and is merged | Replace with a 2-line "shipped; see commit X" or retire |
| `project_session_handoff_2026_04_24.md` (line 31) | One-off handoff doc, two weeks old | Retire — handoffs in `docs/sessions/` are now the canonical place |
| `project_ep133_playwright_state.md` (line 24) | Superseded by SysEx approach per the entry's own description | Keep as historical context, but worth a "DO NOT USE" prefix |
| `project_curation_library_v2_state.md` (line 46) | Says "retire branch" but branch + worktree are still present | Update with current state once worktree decision is made |
| `feedback_canonical_tempos_full_suite_env.md` (line 55) | Refers to a test flake — if Phase 1 hardening fixed it, the entry needs updating | Verify against current `tests/` state after Phase 1 lands |

### Memory entries pointing at retired branches/dead paths

None outright dead. The two branches referenced (`feat/curation-library-v2`, `feat/m4l-locator-anchor`) still exist in the repo. The latter is merged; the former is still ahead of main.

### Recommendation

User-decision items above. I'm explicitly **not** editing memory files in this session — per the handoff brief: "Memory edits beyond hygiene escalate to the user".

## 7. Worktrees disposition (audit only)

Per `docs/issues/worktree-cleanup.md`. I did NOT run `git worktree remove`.

### `.claude/worktrees/curation-library-router/`

- **Branch:** `feat/curation-library-router`
- **Ahead of main:** 7 commits
- **Behind main:** 55 commits
- **Last commit:** `0408b91 chore(lint): drop unused RouteResult import in test_router`
- **Last activity:** 2026-05-05 (per directory mtime)
- **Status:** Clean working tree.

Top commits (oldest → newest from main):
```
983a7d3 feat(router): library-curation router + `stemforge route` CLI
e7ed75d feat(presets,tools): stems_only preset + init_library bootstrap
e62e35a docs(song-forms): five song-form template specs
5a25527 docs(exec-plan): device-side changes for curation library (review gate)
b3ec8cc docs(song-forms): per-template "Build in Live" step-by-step recipes
ad466b9 chore(lint): drop extraneous f-string prefixes in init_library
0408b91 chore(lint): drop unused RouteResult import in test_router
```

**Recommendation:** **CHERRY-PICK & RETIRE.** Per memory `project_curation_library_v2_state.md`: cherry-pick router/init_library/song-form docs forward. The 5 substantive commits are router CLI + init_library + 3 docs commits. Two lint cleanups can be folded in.

Requires explicit user OK to:
1. Cherry-pick the 5+2 commits to a new branch off `main` (or `integration/...`).
2. After cherry-pick lands, `git worktree remove` + `git branch -D feat/curation-library-router`.
3. Update memory entry to mark the branch retired.

### `.claude/worktrees/tempo-detection-half-time/`

- **Branch:** `feat/m4l-locator-anchor`
- **Ahead of main:** 0 commits (already merged)
- **Behind main:** 58 commits
- **Last commit:** `815f865 chore(presets): remove duplicate older IDM Production preset`
- **Last activity:** 2026-05-03 (per directory mtime)
- **Status:** Clean working tree. Branch was merged via PR #37.

**Recommendation:** **RETIRE.** No unmerged value. After explicit user OK:
1. `git worktree remove .claude/worktrees/tempo-detection-half-time`.
2. `git branch -d feat/m4l-locator-anchor` (safe delete — fully merged).

### Other worktrees not in scope

- `agent-a27c1390d8714abdf` — this worktree, in active use.
- `agent-a46fa6dec3a2f642b` — Phase 1 hardening in flight; do NOT touch.
- `agent-a*` (~17 of them, all empty) — empty leftover directory shells from prior agent sessions. Each is `0` bytes / no `.git` reachable. Safe to clean up but separate from this audit; logged as a follow-up.

---

## Appendix A — file paths touched in this branch

Created:
- `docs/cleanup/2026-05-12_root_inventory.md` (this doc)
- `docs/ep133-song-triage/ep133-pad-slot-metadata-probe-2026-05-11.txt` (moved from `/log`)

Modified:
- `.gitignore` (added `/artifacts/`, `/backups/`, `/export/`, `/tbstemmed/`, `.vscode/`, `/log/`)
- `pyproject.toml` (setuptools find scope tightened)
- `docs/sessions/2026-05-12_breaks_n_beats_complete.md` (rewrote dead link to deleted `EP133_DEBRIEF.md`)

Deleted:
- `EP133_DEBRIEF.md` (tracked; superseded)
- `log` (untracked; moved)
- `.claude/sessions/engineer-{161737,201502,aoj-batch}.json` (stale per CLAUDE.md startup protocol)

Added (untracked → tracked):
- `tools/batch_grooves.sh`
- `tools/batch_grooves_overrides.sh`
