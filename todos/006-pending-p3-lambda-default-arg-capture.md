---
status: pending
priority: p3
issue_id: "006"
tags: [code-review, quality, readability]
dependencies: []
---

# 006 · Unnecessary default-arg capture in lambda

## Problem Statement

In `_apply_fetch_result`, the callback is posted as:

```python
self.call_from_thread(lambda rows=job_rows: self._update_jobs_table(rows))
```

The `rows=job_rows` default-arg idiom is a classic Python workaround for loop-variable capture in
`for` loops.  Here there is no loop; `job_rows` is a local variable that is not modified after
the lambda is created.  The idiom is therefore unnecessary and slightly misleads readers into
thinking a capture hazard is being guarded against.

## Findings

- `stoei/app.py` — `_apply_fetch_result`, `user_jobs` branch (line ~947)

## Proposed Solutions

### Option A — Remove the default-arg (Recommended, Tiny effort)

```python
self.call_from_thread(lambda: self._update_jobs_table(job_rows))
```

Pros: clearer intent; idiomatic Python.
Cons: none.
Effort: Tiny | Risk: None

### Option B — Extract to a named helper (Tiny effort)

```python
def _schedule_jobs_table_update(job_rows: list[tuple[str, ...]]) -> None:
    self.call_from_thread(lambda: self._update_jobs_table(job_rows))
```

Pros: even more explicit; reusable.
Cons: over-engineering for a one-liner.
Effort: Tiny | Risk: None

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `stoei/app.py` (`_apply_fetch_result`)

## Acceptance Criteria

- [ ] `lambda rows=job_rows:` pattern removed
- [ ] `uv run pytest` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52

## Resources

- PR #52: feat/progressive-rendering
