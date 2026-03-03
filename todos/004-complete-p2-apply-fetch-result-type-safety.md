---
status: complete
priority: p2
issue_id: "004"
tags: [code-review, type-safety, architecture, quality]
dependencies: []
---

# 004 · `_apply_fetch_result` bypasses the type system with `result: object`

## Problem Statement

`_apply_fetch_result(self, label: str, result: object)` accepts an untyped `result` parameter and
uses six `# type: ignore[misc]` suppressions to destructure it per branch.  This defeats `ty`'s
ability to catch mismatches between what each fetch method returns and what the dispatcher
expects.  If a fetch method's return type changes, the bug will be silent until runtime.

## Findings

- `stoei/app.py` — `_apply_fetch_result` signature (line ~922)
- Six `# type: ignore[misc]` comments, one per label branch
- Each fetch method has a well-defined return type:
  - `_fetch_user_jobs` → `tuple[list[Job] | None, list[Job] | None, int, int, int]`
  - `_fetch_nodes` → `list[NodeInfo]`
  - `_fetch_all_jobs` → `list[Job]`
  - `_fetch_wait_time` → `list[Job]`
  - `_fetch_priority` → `tuple[list[tuple[str, ...]], list[tuple[str, ...]]]`
  - `_fetch_energy` → `tuple[list[Job], bool]`

## Proposed Solutions

### Option A — Union return type (Recommended, Small effort)

Define a `FetchResult` union type alias and annotate `result` with it:

```python
from typing import Union

UserJobsResult = tuple[list[Job] | None, list[Job] | None, int, int, int]
PriorityResult = tuple[list[tuple[str, ...]], list[tuple[str, ...]]]
EnergyResult = tuple[list[Job], bool]

FetchResult = Union[UserJobsResult, list[NodeInfo], list[Job], PriorityResult, EnergyResult]

def _apply_fetch_result(self, label: str, result: FetchResult) -> None: ...
```

The `# type: ignore` suppressions can be replaced with `isinstance`/`assert` guards or narrow
`cast()` calls.

Pros: type-checked; no runtime overhead.
Cons: the union is wide; narrowing is still manual per branch.
Effort: Small | Risk: Low

### Option B — Per-label typed handler methods (Medium effort)

Replace the single dispatcher with per-label private methods, each accepting the correct return
type:

```python
def _handle_user_jobs_result(self, result: UserJobsResult) -> None: ...
def _handle_nodes_result(self, result: list[NodeInfo]) -> None: ...
...

# _refresh_data_async:
handlers: dict[str, Callable[[Any], None]] = {
    "user_jobs": self._handle_user_jobs_result,
    ...
}
for future in as_completed(futures):
    label = futures[future]
    handlers[label](future.result())
```

Pros: each handler is fully typed; easy to test individually; no union needed.
Cons: more boilerplate; handler dispatch via dict introduces a new pattern.
Effort: Medium | Risk: Low

### Option C — `TypedDict` or `dataclass` result envelope (Large effort)

Wrap every fetch result in a `@dataclass` or `TypedDict` with a `label` field, removing the
string-dispatch pattern entirely.

Pros: most expressive; exhaustive pattern matching possible in Python 3.10+.
Cons: large refactor; more code than the problem warrants.
Effort: Large | Risk: Medium

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `stoei/app.py` (`_apply_fetch_result` and all six fetch methods)

## Acceptance Criteria

- [ ] Zero `# type: ignore` suppressions in `_apply_fetch_result`
- [ ] `uv run ty check stoei/` passes cleanly
- [ ] `uv run pytest` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52

## Resources

- PR #52: feat/progressive-rendering
