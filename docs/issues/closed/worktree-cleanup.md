# `.claude/worktrees/` — disposition needed

**Status:** Open — captured 2026-05-12.

## What's there

```
.claude/worktrees/
  curation-library-router/
  tempo-detection-half-time/
  .dontindex
```

These are git worktrees from prior multi-agent sessions. Neither is on the current main branch state.

## What we know

- **`curation-library-router`** — corresponds to the curation-library-v2 branch state. Memory: [`project_curation_library_v2_state.md`] called this stale 2026-05-05 ("42 ahead, 7 behind main; cherry-pick router/init_library/song-form docs forward, skip prechop, retire branch"). Status: probably still stale; no progress this session.
- **`tempo-detection-half-time`** — context unclear from memory. Likely tempo-reconciler half-time work; possibly related to the beat-this fallback issues that bit us on heather/braun.

## What to do

1. **Inspect each worktree.** Check branch name, commits ahead/behind main, and `git log -10` for last activity.
2. **For each worktree, decide**:
   - Cherry-pick still-valuable commits forward into a PR.
   - Hard-delete the worktree (`git worktree remove --force`) if obsolete.
3. **Update or retire the memory entries** referencing these branches.

## Done when

`.claude/worktrees/` contains only worktrees with active work-in-progress, OR is empty if all branches are retired.

## Constraints

- **Don't delete without inspection** — these are user work-in-progress per CLAUDE.md guidance.
- The memory [`feedback_curation_library_v2_branch_direction.md`] is explicit: "One-way: merge main IN, never merge OUT to main. No PR/push without explicit go-ahead." — so anything from `curation-library-router` requires user authorization before pushing.
