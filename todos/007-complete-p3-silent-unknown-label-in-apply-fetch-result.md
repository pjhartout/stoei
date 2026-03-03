---
status: complete
priority: p3
issue_id: "007"
tags: [code-review, quality, error-handling]
dependencies: []
---

# 007 · Silent failure for unknown labels in `_apply_fetch_result`

## Problem Statement

`_apply_fetch_result` is a chain of `if/elif` branches with no final `else`.  If a new label is
introduced (or an existing one is misspelled) the method silently does nothing.  This can make
bugs very hard to find during development.

## Findings

- `stoei/app.py` — `_apply_fetch_result` (line ~922)
- No `else` clause after the `elif label == "energy":` branch.

## Proposed Solutions

### Option A — Add an `else` with a `logger.warning` (Recommended, Tiny effort)

```python
else:
    logger.warning(f"_apply_fetch_result: unknown label {label!r}")
```

Pros: surfaces typos and missing branches immediately.
Cons: none.
Effort: Tiny | Risk: None

### Option B — Raise `ValueError` in development / log in production

```python
else:
    if __debug__:
        raise ValueError(f"Unknown fetch label: {label!r}")
    logger.error(f"_apply_fetch_result: unknown label {label!r}")
```

Pros: crashes fast in tests; non-fatal in production.
Cons: slightly more complex.
Effort: Tiny | Risk: None

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `stoei/app.py` (`_apply_fetch_result`)

## Acceptance Criteria

- [ ] An unknown label produces a log warning (or error) rather than silent no-op
- [ ] `uv run pytest` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52

## Resources

- PR #52: feat/progressive-rendering
