# /simplify — Review Changed Code for Reuse, Quality, and Efficiency

## Role
Before beginning, read `.claude/agents/operator.md` and adopt that role's persona, constraints, and focus areas.

## Input

The user asks to simplify or review recent changes, a file, or a module.

## Process

### 1. Identify Scope

- If given a file or module, focus there
- If asked about recent changes, run `git diff` to find modified files
- If no scope given, scan the full `stemforge/` package

### 2. Check for Duplication

- Look for similar logic across backends, CLI commands, or utilities
- Identify copy-paste patterns that could be factored into shared helpers
- Check if new code duplicates existing functionality in `config.py` or other modules

### 3. Check for Unnecessary Complexity

- Functions doing too many things (could be split)
- Overly nested conditionals or loops
- Abstractions that aren't earning their keep
- Dead code or unreachable branches

### 4. Check for Efficiency

- Unnecessary file I/O (reading the same file multiple times)
- Audio processing that could be batched
- API calls that could be parallelized or cached

### 5. Report Findings

For each finding:
- **What**: specific file, function, lines
- **Why**: what's wrong and why it matters
- **How**: concrete suggestion for improvement
- **Impact**: low / medium / high

### 6. Ask Before Fixing

Present findings and ask: "Should I fix any of these? Which ones?"

## Rules

- Never fix without asking first
- Quantify: "3 functions share this pattern" not "some duplication exists"
- Prioritize by impact on maintainability and performance
- Don't over-abstract — three similar lines may be better than a premature abstraction
- Respect the existing style and patterns of the codebase
