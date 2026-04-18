# v0 Execution Graph

> **ONNX-first update (2026-04-14):** see `v0/PIVOT.md`. Track A0 (ONNX conversion + parity) is inserted as Wave 1.5 and gates Track A. Tracks B, D, F remain parallel to A0. Track A now depends on A0's `done.flag` as well as interfaces.

## Dependency DAG

```
             ┌─────────────────┐
             │ Phase 0: setup  │
             │ (write contracts│
             │  in interfaces/)│
             └────────┬────────┘
                      │
      ┌───────────────┼───────────────┬────────────┐
      ▼               ▼               ▼            ▼
   ┌─────┐        ┌─────┐        ┌─────┐      ┌─────┐
   │  A  │        │  B  │        │  D  │      │  F  │
   │bin  │        │pkg  │        │ als │      │ CI  │
   │     │        │split│        │gen  │      │skel │
   └──┬──┘        └─────┘        └──┬──┘      └──┬──┘
      │                             │            │
      │ (NDJSON binary exists)      │            │
      ▼                             │            │
   ┌─────┐                          │            │
   │  C  │                          │            │
   │amxd │                          │            │
   │gen  │                          │            │
   └──┬──┘                          │            │
      │                             │            │
      └──────────────┬──────────────┘            │
                     ▼                           │
                  ┌─────┐                        │
                  │  E  │ ◄──────────────────────┘
                  │ pkg │                       (F wires A+E into CI)
                  └──┬──┘
                     │
                     ▼
                  ┌─────┐
                  │  G  │
                  │tests│
                  └─────┘
```

## Parallelism Plan

### Wave 1 — write contracts (serial, do first)
One agent writes all files in `v0/interfaces/`. These are the API; every other track reads them. Don't start Wave 2 until interfaces are locked.

### Wave 2 — four tracks in parallel
- **A** — native binary
- **B** — package split
- **D** — .als generation
- **F** — CI skeleton (workflow file, matrix, no release publish yet)

No filesystem overlap. Each writes to its own `v0/state/<id>/` and `v0/build/<artifact>`.

### Wave 3 — serial, gated on A
- **C** — .amxd generation. Needs A's binary to test NDJSON wiring end-to-end. Can start stub work earlier, but acceptance requires A done.

### Wave 4 — serial, gated on A+C+D
- **E** — installer. Consumes all three artifacts, builds .pkg.

### Wave 5 — parallel, gated on A+C+D
- **G** — integration tests.
- **F** — finishes wiring release publish (needs E tooling committed).

## Agent Assignment (suggested)

If using Claude Code's built-in agent types (adapt for your harness):

| Track | Suggested agent | Why |
|---|---|---|
| Interfaces | `general-purpose` | Schema-writing, needs repo context |
| A | `general-purpose`, `isolation: worktree` | Big build work, isolate from others |
| B | `general-purpose` | Touches `stemforge/` package, small diff |
| C | `general-purpose`, `isolation: worktree` | Exploratory — .amxd format R/E |
| D | `general-purpose`, `isolation: worktree` | Exploratory — .als XML schema work |
| E | `general-purpose` | Consumes artifacts, low exploration |
| F | `general-purpose` | YAML + shell, low exploration |
| G | `general-purpose` | Test harness, reads artifacts |

Tracks in worktrees merge back to `claude/review-packaging-strategy-NNuOc` after completion.

## Coordination Signals

Agents check for predecessors via `v0/state/<id>/done.flag`. Before starting dependent work:

```bash
test -f v0/state/A/done.flag || exit 1  # C waits on A
```

If your harness supports event-driven scheduling, use `done.flag` creation as the trigger.

## Failure Handling

- Each track writes `v0/state/<id>/blocker.md` if it hits an unresolvable issue.
- Orchestrator (you, or the harness) checks blocker.md files; dispatches remediation or adjusts plan.
- No track silently degrades. A track either succeeds and writes `done.flag`, or fails and writes `blocker.md`.

## Time Budget (rough, for planning — not a commitment)

| Wave | Budget |
|---|---|
| 1 — interfaces | 30 min (one agent) |
| 2 — A, B, D, F | A dominates — ~4–8h agent-wall-time |
| 3 — C | 3–6h (exploratory) |
| 4 — E | 1–2h |
| 5 — G | 1–2h |

Biggest risks: **A** (PyInstaller + torch is famously finicky) and **C** (.amxd format is semi-proprietary — may need fallback strategy; see track brief).
