# /review — Structured Code Review

## Role
Before beginning, read `.claude/agents/reviewer.md` and adopt that role's persona, constraints, and focus areas.

## Input

The user indicates what to review — recent changes, a specific file, or a PR.

## Process

### 1. Identify Changed Files

- If given a file path, review that file
- If asked to review recent changes, run `git diff` and `git diff --cached`
- If given a PR number, use `gh pr diff {number}`

### 2. Run Checks

```bash
uv run ruff check .
uv run pytest
```

### 3. Check Test Coverage

For each changed file in `stemforge/`:
- Determine if tests exist for new/modified public functions
- Flag any new code without corresponding tests

### 4. Check Backend Contract

If backends were modified:
- Verify `AbstractBackend` subclass implements `separate()` correctly
- Check return type is `dict[str, Path]`

### 5. Check Manifest Compatibility

If `manifest.py` or stems.json handling changed:
- Verify M4L bridge code (`stemforge_bridge.js`) can still consume the output
- Flag any schema changes

### 6. Produce Review Checklist

```markdown
## Review Results

### CRITICAL (blocks merge)
- [ ] **{category}**: {file}:{line} — {description}

### ADVISORY (suggest, don't block)
- [ ] **{category}**: {description}

### Summary
- Critical issues: {count}
- Advisory issues: {count}
- Verdict: **PASS** / **FAIL**
```

### 7. Post to PR (Team Mode Only)

If reviewing a PR in team mode:
```bash
gh pr comment {number} --body "{review checklist}"
```

## Classification Rules

### CRITICAL
- Missing tests for new public functions
- Backend contract violations
- Broken existing tests
- Manifest schema changes without M4L compatibility check
- Security issues (hardcoded API keys, command injection)

### ADVISORY
- Style/formatting (auto-fixable)
- Missing docstrings
- Naming convention deviations
- File size concerns

## Rules

- Be specific: file paths, line numbers, function names
- For each critical issue, include a remediation suggestion
- Do NOT fix issues — only report them
