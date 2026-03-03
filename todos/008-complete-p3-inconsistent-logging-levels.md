---
status: complete
priority: p3
issue_id: "008"
tags: [code-review, quality, logging]
dependencies: []
---

# 008 · Inconsistent logging levels in new UI update helpers

## Problem Statement

The five new targeted UI update methods (`_update_nodes_and_sidebar`, `_update_all_jobs_widgets`,
`_update_priority_tab`, `_update_energy_tab`, and `_on_refresh_complete`) catch widget-not-found
exceptions and log them with `logger.debug`.  The existing codebase uses `logger.error` (or
`logger.exception`) for unexpected failures of this kind.  Using `debug` means these errors are
invisible at the default log level, making a broken layout silent in production.

## Findings

- `stoei/app.py` — `_update_nodes_and_sidebar` (line ~982): `logger.debug(f"Failed to update node tab: {exc}")`
- `stoei/app.py` — `_update_all_jobs_widgets` (line ~996): `logger.debug(f"Failed to update users tab: {exc}")`
- `stoei/app.py` — `_update_priority_tab` (line ~1010): `logger.debug(f"Failed to update priority tab: {exc}")`
- `stoei/app.py` — `_update_energy_tab` (line ~1022): `logger.debug(f"Failed to update energy tab: {exc}")`
- Existing pattern: `except Exception: logger.exception(...)` is used elsewhere for unexpected widget failures.

## Proposed Solutions

### Option A — Upgrade to `logger.exception` (Recommended, Tiny effort)

```python
except Exception:
    logger.exception("Failed to update node tab")
```

`logger.exception` automatically appends the traceback, which is more useful for diagnosing
layout failures than a bare exception message.

Pros: consistent with existing codebase patterns; full traceback available.
Cons: none.
Effort: Tiny | Risk: None

### Option B — Keep `debug` for expected widget-missing cases, `exception` for others

Some `query_one` failures may be expected (e.g., widget not yet mounted on first cycle).  In that
case, wrap the lookup in a guard and only log at `debug` if the widget is truly optional, otherwise
at `exception`.

Pros: more precise severity.
Cons: requires knowing which widgets are optional — adds complexity.
Effort: Small | Risk: Low

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `stoei/app.py` (`_update_nodes_and_sidebar`, `_update_all_jobs_widgets`, `_update_priority_tab`, `_update_energy_tab`)

## Acceptance Criteria

- [ ] Widget-not-found exceptions logged at `error` or `exception` level, not `debug`
- [ ] `uv run pytest` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52

## Resources

- PR #52: feat/progressive-rendering
