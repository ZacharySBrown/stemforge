# /design — Create a Design Document

## Role
Before beginning, read `.claude/agents/architect.md` and adopt that role's persona, constraints, and focus areas.

## Input

The user provides a feature idea — brief description or detailed request.

## Process

### 1. Research the Codebase

Before writing anything, understand what exists:
- Search `stemforge/` for related code, backends, CLI commands
- Check `m4l/` if the feature involves Ableton integration
- Read `specs/` for existing architecture specs
- Check for any existing design docs in `docs/`

### 2. Create the Design Document

Create `docs/design-docs/{feature-name}.md`:

```markdown
# {Feature Name}

## Status
Draft — awaiting review

## Problem
What problem are we solving? Why now?

## Context
What exists today? Constraints? Related code?
Reference specific files: `stemforge/...`, `m4l/...`

## Proposed Approach
- Which zones are affected (core, m4l, tools)
- New modules or modifications
- Data flow through the pipeline
- Impact on stems.json manifest schema
- M4L integration points (if any)

## Alternatives Considered
At least 2 alternatives with trade-off analysis.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Open Questions
- [ ] Question 1 — needs human decision because...
```

### 3. Present for Review

After creating the design doc:
- One-paragraph summary of the proposed approach
- Key decisions needing approval
- Open questions requiring human judgment
- Ask: "Should I proceed to `/plan`, or revise the design first?"

## Rules

- Always research the codebase BEFORE writing the design doc
- Respect the zone model — Core stays independent of M4L
- Reference specific files when discussing existing code
- Flag any new dependencies (Core Belief: boring tech)
- If the feature is ambiguous, escalate (Core Belief: escalate ambiguity)
- Do NOT start implementation — this skill produces a design doc only
