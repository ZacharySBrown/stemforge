# Root `DUMP` file — hybrid content needs splitting

**Status:** Open — captured 2026-05-12.

## What it is

`/Users/zak/zacharysbrown/stemforge/DUMP` is a 1005-line Unicode text file at the repo root that contains **three intermixed sections**:

1. **Top: shallow directory tree** of `~/mus/` (Samples/, Projects/, Resources/, etc.). The `find` output is depth-limited to ~3-4 levels — useful for orientation but not enumeration.
2. **Middle: organize-event log** from a 2026-02-21 reorg run. Lines like `[2026-02-21 21:04:20] MOVED: <src> → <dst>` and `MIXED-CASE EXT: ...`. Leaks deeper paths than the tree alone shows.
3. **Bottom: prose documentation** about Ableton Cloud sync, AirDrop workflow, etc. Ends with "*Generated for Zak — IDM production environment setup — February 2026*".

Memory: [`reference_mus_library_structure.md`] points at DUMP as the workaround for the sandbox-blocked `~/mus/` library.

## Problems

- It's gitignored (or at least untracked — git status shows it as `??`), but agents reference it.
- Mixed sections force grep patterns to filter by line prefix (`^\.` for tree, `MOVED|CREATED` for log).
- Depth-3 tree can't answer "what pack files are in `Samples/Breaks/Jungle/`?" — agents have to ask the user to refresh with deeper enumeration.
- Last refreshed 2026-05-08 — drift risk against the live library.

## What "good" looks like

Split into three files under a `.local/mus/` directory (gitignored):
- `mus_tree.txt` — `find ~/mus -type f` or `tree -L 5 ~/mus` — deep, file-level.
- `mus_events.log` — organize-event log (append-only).
- `mus_setup.md` — prose docs section.

Plus a refresh script (`tools/refresh_mus_dump.sh`) that the user runs whenever they reorganize the library.

## Done when

Three separate files exist under `.local/mus/`, the refresh script is documented in CLAUDE.md, and the root `DUMP` file is moved/deleted.

## Out of scope

Actually unblocking `~/mus/` from sandbox restrictions. That's a macOS file-permissions / Claude Code config issue separate from how we surface the library to agents.
