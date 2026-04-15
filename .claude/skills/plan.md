# /plan — Create an Execution Plan from a Design Document

## Role
Before beginning, read `.claude/agents/architect.md` and adopt that role's persona, constraints, and focus areas.

## Input

The user references a design document, by name or path.

## Process

### 1. Read the Design Document

- Read the referenced design doc in full
- If still "Draft" status, warn and ask if they want to proceed anyway

### 2. Read Architecture Context

- Review `stemforge/` structure for the affected zone
- Check `docs/` for conflicting in-progress plans
- Review relevant specs in `specs/`

### 3. Decompose into Tasks

Break the design into ordered steps. Each task should:
- Be completable in a single focused session
- Have clear inputs and outputs
- Have explicit dependencies on other tasks
- Include a TDD checkpoint: what test to write first

Organize tasks by zone, inside-out:
1. **Core first** — Backend, slicer, curator, manifest changes
2. **Pipeline configs** — YAML/JSON updates
3. **M4L** — Device patches, bridge scripts, LOM access
4. **Tools** — Utility scripts
5. **Tests** — Integration tests
6. **Docs** — README, setup guide, spec updates

### 4. Create the Execution Plan

Create `docs/exec-plans/{plan-name}.md`:

```markdown
# Execution Plan: {Feature Name}

## Design Doc
[{Feature Name}](../design-docs/{feature-name}.md)

## Status
Active — {N} tasks remaining

## Task Breakdown

### Task 1: {Description}
- **Zone**: core
- **Depends on**: (none)
- **Files**: `stemforge/{file}.py`
- **TDD**: Write test for {what} first
- **Done when**: {criterion}
- **Status**: [ ] pending

### Task 2: {Description}
- **Zone**: m4l
- **Depends on**: Task 1
...

## Decision Log
| Decision | Date | Context |

## Risks
- Risk: {description} — mitigation: {approach}
```

### 5. Present for Approval

- Total task count and critical path
- First tasks that can start immediately
- Risks or open questions
- Ask: "Does this plan look right?"

## Rules

- Every task must have a TDD checkpoint
- Tasks respect zone dependency order (core before m4l)
- Keep tasks completable in one session
- Each task has a clear "done when" criterion
- Do NOT start implementation — this skill produces a plan only
