# Shared Memory Convention

Claude Code subagents do not have shared memory. They share state through:

1. **Filesystem** — read + write, concurrent-safe as long as tracks write to distinct paths.
2. **Git** — branches, commits, and optionally `isolation: "worktree"` for temporary copies.
3. **Return messages** — agent → orchestrator only, not agent → agent.

This document defines the filesystem conventions that substitute for shared memory in v0.

## Directory Layout

```
v0/
├── PLAN.md                     # master plan, read-only to agents
├── DAG.md                      # execution graph, read-only
├── SHARED.md                   # this file, read-only
│
├── interfaces/                 # API contracts — read-only during Wave 2+
│   ├── ndjson.schema.json      # binary → M4L event protocol
│   ├── tracks.yaml             # Ableton template track spec
│   └── device.yaml             # M4L device UI + binary resolution
│
├── tracks/                     # per-track briefs — read-only to agents
│   ├── A-native-binary.md
│   ├── B-package-split.md
│   ├── C-m4l-device.md
│   ├── D-als-template.md
│   ├── E-installer.md
│   ├── F-cicd.md
│   └── G-integration-tests.md
│
├── state/                      # runtime coordination — write-your-own-dir only
│   ├── A/
│   │   ├── progress.ndjson     # agent writes status updates here
│   │   ├── artifacts.json      # agent writes final artifact metadata
│   │   ├── done.flag           # agent writes when track complete
│   │   └── blocker.md          # agent writes if blocked (mutually exclusive with done)
│   ├── B/
│   ├── C/
│   └── ... (one dir per track)
│
├── build/                      # build artifacts — multi-writer, track-namespaced files
│   ├── stemforge-native        # produced by A
│   ├── StemForge.amxd          # produced by C
│   ├── StemForge.als           # produced by D
│   └── StemForge-0.0.0.pkg     # produced by E
│
├── src/                        # generator source code — track-namespaced subdirs
│   ├── maxpat-builder/         # C's tooling
│   └── als-builder/            # D's tooling
│
├── tests/                      # G's tests
│   └── fixtures/
│
└── assets/                     # committed build-time assets (e.g., .als skeleton)
```

## Write Rules

1. **An agent writes only under `v0/state/<its-id>/` and `v0/src/<its-subdir>/`.**
2. **Agents write final artifacts to `v0/build/<artifact-filename>`.** Filenames are pre-assigned per track brief; no collisions possible if names are respected.
3. **Agents read `v0/interfaces/*` but never modify it.** If an interface change is needed, escalate to orchestrator.
4. **Agents modifying the `stemforge/` package (Tracks A, B)** touch only the files explicitly listed in their brief.

## Predecessor Detection

To wait on a predecessor, an agent checks for its `done.flag`:

```bash
# Wait pattern (blocking, used by C waiting on A)
while [ ! -f v0/state/A/done.flag ]; do sleep 5; done
[ -f v0/state/A/blocker.md ] && { echo "Track A blocked"; exit 1; }
```

Event-driven harnesses can watch the `state/` tree and dispatch on flag creation.

## Status Reporting

Each agent continuously appends to `v0/state/<id>/progress.ndjson`:

```json
{"ts": "2026-04-15T19:22:01Z", "phase": "building", "pct": 40, "message": "collecting torch imports"}
{"ts": "2026-04-15T19:23:50Z", "phase": "signing", "pct": 80, "message": "codesign running"}
```

On completion, the agent writes `v0/state/<id>/artifacts.json`:

```json
{
  "track": "A",
  "status": "complete",
  "artifacts": [
    {
      "path": "v0/build/stemforge-native",
      "sha256": "…",
      "size_bytes": 834521000,
      "arch": "universal2",
      "signed": true,
      "notarized": true
    }
  ],
  "duration_sec": 2840
}
```

Then touches `v0/state/<id>/done.flag` (any contents; presence is the signal).

## Blocker Reporting

If an agent hits an unresolvable issue (e.g., missing signing cert, undocumented format), it writes `v0/state/<id>/blocker.md` describing:

- What it tried
- What the blocker is
- What it recommends (escalate to human? change of approach? scope cut?)

It does **not** write `done.flag`. The orchestrator picks up the blocker and either:
- Remediates and re-invokes the agent
- Adjusts the plan and reassigns

## Locking (rare)

If two tracks legitimately need to write the same file (should not happen in v0), use advisory file locks:

```bash
(flock 9 && do_thing) 9>v0/state/.lock-<resource>
```

None are expected for v0 — if you reach for this, stop and reconsider the design.

## Concurrency Contract

Given these rules:

- **Tracks A, B, D, F can run fully concurrent** — disjoint write sets.
- **Track C must wait for A's `done.flag`** — needs the binary to integration-test the node.script spawn.
- **Track E must wait for A, C, D flags.**
- **Track G must wait for A, C, D flags.**

No other synchronization is required.

## Orchestrator Responsibilities (your harness)

- Dispatch agents per DAG.md.
- Pass each agent its track brief path and the interface files.
- Poll `v0/state/*/done.flag` and `blocker.md`.
- On all `done.flag` present: run final acceptance tests (Track G).
- On any `blocker.md`: route to human or remediation sub-agent.
