# Handoff: post-breaks-n-beats work — 2026-05-12

## TL;DR

The EP-133 deck pipeline is hardware-validated and the user is happy. **PR #62 (merged) + one pending commit on `main`** (loop-region collapse) ship the production-grade machinery. You're picking up where step 0 of the user's request left off — they've explicitly asked you to plan and execute the next four phases:

1. **Finish hardening + automated-testing work in flight.**
2. **Clean up the repo, make it presentable.**
3. **Update docs to be pristine + user-friendly.**
4. **Consider an actual release.**

## Where to start

Read these in this order:

1. **`docs/sessions/2026-05-12_breaks_n_beats_complete.md`** — what just shipped, what we learned. Single source of truth for current state.
2. **`docs/issues/*.md`** — followup work. Each file is a self-contained issue with status + why + fix path + done-when. As of handoff there are 14 of them.
3. **CLAUDE.md** — project conventions, role definitions, write-scope matrix. You're entering as an unscoped agent; the user will likely want you to pick a role (Architect or Operator most likely) before doing repo-wide cleanup.
4. **Memory** (`/Users/zak/.claude/projects/-Users-zak-zacharysbrown-stemforge/memory/MEMORY.md`) — load-bearing context that won't be in the code or git log. Especially: m4l_device_development_guide, the EP-133 protocol findings, and the LOM quirk memories.

## Pre-flight: repo state at handoff time

```
On branch main, up to date with origin/main.

Uncommitted in working tree:
  - Loop-region collapse landed via 3 file edits but NOT YET COMMITTED:
    v0/src/m4l-js/stemforge_loader.v0.js
    v0/src/m4l-package/StemForge/javascript/stemforge_loader.v0.js
    tests/js_mocks/test_bounce.test.js
    tests/test_js_bridge.py
    v0/build/StemForge.amxd  (rebuilt)
  - Plus pre-existing modifications (presets/clean.json — see issue file).
  - Plus lots of untracked docs/specs/artifacts directories left over from earlier work.

Pytest: 843 passed, 11 skipped.
JS bounce suite: 6/6 pass (node tests/js_mocks/test_bounce.test.js).
.pkg installed and JS in installed-runtime location is in sync with repo.
```

**First action:** commit the loop-region work as its own focused commit before starting any cleanup. Suggested message:

```
feat(m4l): _collapseToLoopRegion — bake loop region into bounce

When a clip is looping, _bounceCropTrack now writes loop_start/loop_end
onto start_marker/end_marker BEFORE calling crop, so the loop region
gets materialized into the bounced WAV. 6 JS mock tests cover
looping=1+divergent bounds, looping=0 preserved, idempotent, and the
degenerate-bounds safety guard. Wired into pytest via test_js_bounce_suite.
Hardware-validated 2026-05-12 on the breaks-n-beats1 .ppak (46 pads,
A=12 B=12 C=10 D=12 with hold-to-play drum profile).
```

Then `git push` and open a PR. Don't merge until phases 1-3 below are at least scoped.

## Phase 1 — Finish hardening + automated-testing work

Goal: every must-keep-green path has live test coverage, no stale TODOs in `STACKED_PR_PENDING`, and CI catches issues that bit us in PR #62 (format check, missing fixtures).

### Concrete tasks (priority-ordered)

1. **Wire all `tests/js_mocks/*.test.js` into pytest.** See [`docs/issues/hardening-test-coverage-gaps.md`](../issues/hardening-test-coverage-gaps.md). Highest ROI: `test_commit.test.js` has 27 cases of real coverage going unused.
2. **Remove `test_commit.test.js` from `tests/test_path_coverage.py:STACKED_PR_PENDING`.** The file exists, it passes, the comment claims "pending merge of PR #48" but that PR landed long ago.
3. **Add a `deck-from-manifest --profile <vocal|drum|texture|preserve_source>` flag** so the inline regex patch we did for breaks-n-beats1 becomes a proper CLI option. Also a `--all-drum` shortcut.
4. **Local pre-commit hook for `ruff format --check`.** CI caught the format issue in PR #62 only after the push round-trip — local hook saves time.
5. **Investigate the bounce-stub race** ([`bounce-stub-race.md`](../issues/bounce-stub-race.md)) — fix is small (atomic rename), prevents the polling foot-gun.
6. **Fix or document the broken reload forwarder** ([`js-reload-forwarder-broken.md`](../issues/js-reload-forwarder-broken.md)).

### Where you can punt

The bar-inference canopy issue ([`bar-inference-canopy.md`](../issues/bar-inference-canopy.md)) is informational — leave it open unless real odd-meter content surfaces. Same with [`max-startup-sendmessage-errors.md`](../issues/max-startup-sendmessage-errors.md) — three lines of harmless noise, not a release blocker.

## Phase 2 — Repo cleanup

Goal: a stranger cloning the repo sees a clean root, can find what they need, and isn't confused by working-tree detritus.

### Concrete tasks

1. **Root-level cleanup.** As of handoff, `git status` shows these untracked items at root:
   ```
   DUMP, EP133_DEBRIEF.md, EXPORT_CONFIGURATOR_*.md (4 files),
   STEMFORGE_CONFIGURATOR_SPEC_v{2,3}.md, TOP3_TUNING_*.md (4 files),
   artifacts/, backups/, export/, log, new_specs/, research/,
   targets/, tbstemmed/, specs/EP-133-KO-II-Guide.pdf, specs/files (1).zip,
   specs/*handoff*.md, specs/*briefing*.md, .vscode/
   ```
   Each needs a decision: commit (with a home in `docs/`), move to `.local/`, gitignore, or delete. **Don't delete without asking** — many of these are user work-in-progress.

2. **Resolve issue files** that have clear answers:
   - [`ep133-debrief-disposition.md`](../issues/ep133-debrief-disposition.md) — delete `EP133_DEBRIEF.md`.
   - [`log-file-collision.md`](../issues/log-file-collision.md) — move root `log` file, gitignore `log/`.
   - [`dump-file-split.md`](../issues/dump-file-split.md) — split into `.local/mus/`.
   - [`presets-clean-json-disposition.md`](../issues/presets-clean-json-disposition.md) — commit or revert (user-decision).
   - [`worktree-cleanup.md`](../issues/worktree-cleanup.md) — inspect, decide per worktree.

3. **`docs/` structure check.** This handoff dropped 14 new docs into `docs/issues/` and 1 into `docs/sessions/`. Verify all referenced docs exist (no broken links).

4. **Memory hygiene.** Audit `/Users/zak/.claude/projects/.../memory/MEMORY.md` — load-bearing entries should stay; obsolete ones (e.g. references to retired branches) should be pruned. Check each `[[link]]` resolves.

5. **`tools/` package contents.** PR #62 added `tools` to the setuptools find target so `sf-remote` could install as a console script. The directory has lots of other things — they're now technically packageable but probably shouldn't be. Either (a) explicit module list in pyproject.toml, or (b) split into `tools/cli/` (packaged) and `tools/scripts/` (not).

### Constraints

- **Don't `rm -rf` user dirs without explicit OK.** Per CLAUDE.md: "If you discover unexpected state like unfamiliar files, branches, or configuration, investigate before deleting or overwriting".
- **Memory `feedback_commit_hygiene.md`**: commit every substantial change mid-session; never `git reset --hard` without explicit user yes.

## Phase 3 — Documentation pass

Goal: a user-friendly README + getting-started flow + topic guides for the major workflows.

### Concrete tasks

1. **Top-level README.** Currently the project's intro is implicit in CLAUDE.md (which is agent-facing). A user-facing README should cover:
   - What is StemForge (one paragraph: stem-split + bar-curate + EP-133 kit-builder for Ableton workflows)
   - Quickstart: install → process a track → load on EP-133
   - Architecture overview (the 3-zone model from CLAUDE.md)
   - Pipeline catalog (arrangement vs curation vs production_idm)
   - Link to the M4L device guide + EP-133 protocol findings

2. **EP-133 workflow guide.** A canonical "here's how to make a breaks-n-beats deck" walkthrough. The session debrief covers the technical machinery; this would be the user-facing version.

3. **CLI reference.** `stemforge --help` is fine for discoverability but a single doc listing every command with example invocations is more presentable. Auto-generate from click metadata or hand-curate.

4. **Migrate session-handoff specs** out of `specs/` (where briefings get scattered) into `docs/sessions/` consistently. Memory should reference the new locations.

5. **Architecture diagrams.** The pipeline diagram in `docs/sessions/2026-05-12_breaks_n_beats_complete.md` is ASCII — could become a proper diagram. Optional.

### What "pristine" looks like

A new user clones the repo, opens README, follows quickstart, has a stem-split + bar-curated track loaded in Ableton within 15 minutes. No need to read CLAUDE.md, memory, or session debriefs.

## Phase 4 — Consider a release

**Don't act on this without explicit user OK.** This phase is genuinely "consider" — version 0.0.1 is what the .pkg currently ships as. Real release questions:

1. **Version scheme.** Is 0.1.0 the right next bump? (Major-version 1 would imply API stability promises.)
2. **What's in scope.** Just `stemforge` CLI + M4L device? Or `sf-remote` + the EP-133 deck pipeline as separate releasable units?
3. **Distribution.** `.pkg` for Mac users; `pip install stemforge` for Python users — both?
4. **Release notes.** Aggregate of PR descriptions since the last tag. Generate from `git log`.
5. **Demo content.** The breaks-n-beats1.ppak makes a great demo asset — but it ships with user-specific audio. Cleared rights? Or build a from-public-samples demo deck.
6. **Tests passing on a fresh checkout.** The integration tests touch `~/stemforge/processed/` — need fixtures or a CI-only path that doesn't depend on the user's directory.

**Recommended flow:** present a release plan to the user with these questions answered, get sign-off, then execute. Don't bump a version without their explicit OK.

## Constraints summary

- **Per CLAUDE.md** — agents respect role write scopes. You're likely operating as Architect (docs+specs) for phase 3, Operator (tools+docs+state cleanup) for phase 2. Phase 1 has Engineer scope (tests). Pick deliberately.
- **Per memory** — see the existing `MEMORY.md` index. Especially: M4L test/deploy discipline, drum profile defaults, EP-133 protocol findings, and the LOM quirks docs.
- **Branch protection** — `main` is the merge target. Use feature branches per phase or per closeable group of issues. Don't push to main directly.
- **Commit hygiene** — small focused commits, no `--no-verify` unless user-OKed, no `git reset --hard` without explicit yes.
- **Don't run `ultrareview` yourself** — it's user-triggered and billed.
- **`~/mus/` is sandbox-blocked** — use the `DUMP` file (after the [`dump-file-split.md`](../issues/dump-file-split.md) cleanup) or ask the user to refresh it.

## Recommended phase ordering

Do **Phase 1 in parallel with Phase 2** (engineering + cleanup don't conflict, different file scopes). **Phase 3** depends on a clean repo so do it after 2. **Phase 4** is gated on user decisions — don't start until phases 1-3 land at least at PR-open state.

## When to escalate to the user

- Anything that touches `presets/clean.json` (the unresolved color refactor).
- Any `git worktree remove` call.
- Any decision on what to do with `~/mus/` library tooling.
- Version bumps + release tagging.
- Memory edits beyond hygiene (i.e. anything that changes how a remembered fact reads, not just where it lives).

## Open questions you'll need answered

These weren't resolved in the current session and might come up:

- Is the `breaks-n-beats1.ppak` content shareable as a demo? (User-specific audio.)
- What's the long-term home for `EP133_DEBRIEF.md` content — keep, move to docs/, or delete entirely?
- Should `sf-remote` ship as part of the `.pkg` installer too, or stay Python-only?
- Is there an existing CI workflow file we should be updating? Current PR #62 used GH Actions but I haven't audited the workflows directory.

---

**Final note:** the user is happy with the current state. Don't break what works. The bar for any change in phase 2/3 is "does this make the repo more presentable without regressing functionality?" — when in doubt, ask.
