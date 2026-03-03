---
status: pending
priority: p3
issue_id: "009"
tags: [code-review, quality, readability]
dependencies: []
---

# 009 · Redundant double guard in `_on_refresh_complete`

## Problem Statement

`_on_refresh_complete` contains a nested guard:

```python
def _on_refresh_complete(self, is_first_cycle: bool) -> None:
    self._job_info_cache.clear()
    if is_first_cycle and not self._initial_background_complete:
        self._initial_background_complete = True
        ...
```

`is_first_cycle` is derived at the *start* of `_refresh_data_async` as
`not self._initial_background_complete`, so `is_first_cycle and not self._initial_background_complete`
is logically equivalent to just `is_first_cycle`.  The second half of the condition
(`not self._initial_background_complete`) will always be `True` when `is_first_cycle` is `True`,
because nothing else sets `_initial_background_complete = True` between the two points.

The redundant check causes readers to wonder whether there is a concurrent path that could set
`_initial_background_complete` between the `_refresh_data_async` start and `_on_refresh_complete`.

## Findings

- `stoei/app.py` — `_on_refresh_complete` (line ~1034):
  ```python
  if is_first_cycle and not self._initial_background_complete:
  ```

## Proposed Solutions

### Option A — Remove the redundant guard (Recommended, Tiny effort)

```python
if is_first_cycle:
    self._initial_background_complete = True
    ...
```

Pros: clearer; no spurious re-check.
Cons: none, assuming no concurrent writes to `_initial_background_complete`.
Effort: Tiny | Risk: None

### Option B — Document why both checks are present (Tiny effort)

If the double check is intentional defensive programming (e.g., guarding against hypothetical
future concurrent callers), add a comment explaining why.

```python
# is_first_cycle is captured at _refresh_data_async start; the second guard
# defends against future concurrent calls that might race to set this flag.
if is_first_cycle and not self._initial_background_complete:
```

Pros: documents intent; no code change.
Cons: leaves misleading code in place.
Effort: Tiny | Risk: None

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `stoei/app.py` (`_on_refresh_complete`)

## Acceptance Criteria

- [ ] `if is_first_cycle and not self._initial_background_complete` simplified to `if is_first_cycle`
- [ ] `uv run pytest` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52

## Resources

- PR #52: feat/progressive-rendering
