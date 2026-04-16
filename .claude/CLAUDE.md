

# StemForge

Dual-mode audio production system: Python CLI for stem splitting + beat slicing, Max for Live devices for Ableton Live integration.

## Architecture: 3-Zone Model

| Zone | Path | Purpose |
|------|------|---------|
| **Core** | `stemforge/` | CLI, backends, slicer, analyzer, curator, manifest |
| **M4L** | `m4l/` | Max for Live devices, Node-for-Max bridge, LOM scripts |
| **Tools** | `tools/` | Standalone utilities, batch scripts, curation workflows |

**Zone rules:**
- Core has zero M4L dependencies — it's a standalone Python package
- M4L reads Core's output (stems.json manifests) but never imports Core code
- Tools may call Core CLI commands but don't import M4L code

**Supporting directories:**
- `pipelines/` — YAML pipeline configs (user-editable) + compiled JSON for M4L
- `specs/` — Technical architecture specs
- `tests/` — Pytest suite
- `docs/` — Design docs, exec plans (created as needed)

## Key Commands

```bash
# Python
uv run pytest                              # Run tests
uv run ruff check .                        # Lint
uv run ruff format --check .               # Format check

# StemForge CLI
uv run stemforge split <audio_file>        # Full stem + slice pipeline
uv run stemforge forge <audio_file>        # Integrated M4L workflow
uv run stemforge list                      # List pipelines/options
uv run stemforge balance                   # Check LALAL.AI credits

# Pipeline management
uv run stemforge generate-pipeline-json    # Compile YAML → JSON for M4L
```

## Conventions

- **Python 3.11+**, managed with `uv`
- **Click CLI** with **Rich** console output
- **Pluggable backends**: All stem separation backends extend `AbstractBackend`
- **Manifest-driven**: All pipeline output described by `stems.json`
- **snake_case** for modules/functions, **PascalCase** for classes
- **Tests**: Every feature/fix needs tests. `tests/` directory.
- **File size**: Keep modules focused. Split when a file gets unwieldy.

## Backend Pattern

```python
class AbstractBackend(ABC):
    @abstractmethod
    def separate(self, audio_path, output_dir, **kwargs) -> dict[str, Path]:
        """Returns {stem_name: stem_wav_path}"""

# Implementations: DemucsBackend (local), LalalBackend (API), MusicAiBackend (SDK)
```

## Pipeline Flow

```
Audio file → Backend.separate() → Slicer (BPM + beat/bar slicing)
  → Curator (diversity selection) → Manifest (stems.json)
  → M4L Loader (Ableton integration)
```

## Agent Roles

Four specialized roles for multi-agent Claude Code sessions. Roles activate automatically via skills or manually.

| Role | Skills | Posture |
|------|--------|---------|
| **Architect** | `/design`, `/plan` | Strategic — designs systems, evaluates trade-offs |
| **Engineer** | (default for implementation) | Tactical — implements via TDD, follows patterns |
| **Reviewer** | `/review` | Reactive — reviews changes, enforces quality |
| **Operator** | `/simplify` | Proactive — scans health, manages entropy |

- **Role personas**: `.claude/agents/{role}.md`
- **Activate manually**: tell Claude to adopt a role (persists until switched)
- **Auto-activation**: each skill loads its mapped role automatically

## Development Workflow

```
/design → Design Doc → /plan → Exec Plan → Implement (TDD) → /review → Merge
```

## Review Gates

**Critical (blocks merge):**
- Missing tests for new code
- Broken existing tests
- Backend interface violations (AbstractBackend contract)
- Manifest schema changes without migration

**Advisory (suggest, don't block):**
- Style/formatting (auto-fixable)
- Missing docstrings
- File size concerns

## Session Management

When multiple Claude Code windows run simultaneously, follow these rules.

### Startup Protocol

On first interaction in a new session:

1. **Detect active sessions** — Read `.claude/sessions/*.json`. Delete any file older than 4 hours (stale).
2. **Detect dev mode** — Check `git remote -v`. Remote exists → **team mode**. No remote → **solo mode**.
3. **Select a role** — If the user's first message isn't a specific task, ask which role. If it IS a task, infer and confirm.
4. **Register this session** — Write `.claude/sessions/{role}-{HHmmss}.json`:
   ```json
   {"role": "engineer", "mode": "solo", "started": "2026-04-14T10:15:00Z", "focus": ""}
   ```
5. **Claim work** — Note what you're working on in the session file.

On session end: delete the session file.

### Coordination Rules

1. **Own your lane** — Each role has a defined write scope. Don't modify files outside it.

| Role | Can Modify | Read-Only |
|------|-----------|-----------|
| Architect | `docs/`, `specs/`, `v0/PLAN.md`, `v0/PIVOT.md`, `v0/DAG.md`, `v0/SHARED.md`, `v0/tracks/`, `v0/interfaces/` (pre-lock only), `.claude/` (excl. `sessions/`) | Everything |
| Engineer | `stemforge/`, `m4l/`, `tests/`, `pipelines/`, `v0/src/<my-track-id>/`, `v0/state/<my-track-id>/`, `v0/build/<my-artifacts>` | Everything |
| Reviewer | Nothing (read-only) | Everything |
| Operator | `tools/`, `docs/`, `v0/state/` (cleanup only — stale flags, never another track's `done.flag`) | Everything |

**v0 track write-lane rules** (see `v0/SHARED.md` for full spec):
- Engineers claim exactly one v0 track per session; record `"v0_track": "A"` in their session file.
- `v0/interfaces/` is read-only once locked (Wave 1 complete). Interface changes escalate to Architect.
- Filesystem coordination flags (`done.flag`, `blocker.md`) are per-track — only that track's Engineer writes them.

2. **Claim before you build** — Every coding session must have a stated focus in its session file.
3. **One task at a time** — WIP limit of 1 per session. Finish or park before switching.
4. **Dependencies flow forward** — Design → plan → implement → review. Don't start downstream work until upstream is done.
5. **Conflicts mean stop** — If you need a file another session owns, tell the user and wait.

### Dev Mode: Solo vs Team

| Aspect | Solo | Team |
|--------|------|------|
| Task tracking | Session files only | Session files + GH Issues |
| PR workflow | Optional | Required |
| Review output | Terminal only | Terminal + PR comment |

## Core Beliefs

1. **Docs first, always** — Plan before build. `/design` and `/plan` enforce this.
2. **Tests prove correctness** — No feature complete without tests. TDD preferred.
3. **Boring tech by default** — Prefer well-documented, stable libraries. Novel deps need justification.
4. **Escalate ambiguity** — Agents escalate decisions with no clear right answer to the human rather than guessing.
5. **Manifest is the contract** — `stems.json` is the interface between Core and M4L. Changes need migration thought.
6. **Backends are pluggable** — New stem separation services implement `AbstractBackend`. No special-casing in CLI.
