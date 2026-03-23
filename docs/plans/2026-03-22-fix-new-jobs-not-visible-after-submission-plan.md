---
title: "Fix new jobs not visible after submission"
type: fix
date: 2026-03-22
---

# Fix: New Jobs Not Visible After Submission

## Overview

When users submit new SLURM jobs while stoei is running, the newly submitted jobs are not prominently visible in the jobs table. The root cause is that the incremental update logic in `FilterableDataTable._apply_incremental_update` appends new rows at the **bottom** of the DataTable, while the data is pre-sorted by `_sorted_jobs_for_display` to place pending/new jobs at the **top**. Users looking at the top of their jobs table never see new jobs appear.

## Problem Statement

The incremental update system (introduced in the 2026-02-24 refactor) correctly detects new rows and adds them to the DataTable. However, Textual's `DataTable.add_row()` always appends to the end. The incremental update code at `filterable_table.py:769-771` does:

```python
for key in added:
    row = new_rows_by_key[key]
    table.add_row(*row, key=key)  # Always appends at the end
```

The sort-fallback check at `filterable_table.py:741-746` only triggers a full rebuild when the **user-initiated** DataTable sort is active (column header click). It does NOT account for the implicit pre-sort applied by `_sorted_jobs_for_display`, which orders pending jobs first and newest job IDs first.

**Result**: New jobs are added to the table but appear at the bottom. On subsequent refresh cycles, the row stays at the bottom because the incremental path only updates cell values, not positions. The user never sees the new job unless they scroll to the bottom.

**Secondary issue**: There is no notification or visual indicator that new jobs have been detected. The user has no way to know a new job appeared without manually scanning the entire table.

## Root Cause Analysis

### Data flow trace (verified by reading all code paths)

1. `_refresh_data_async` → `_fetch_user_jobs` → `get_running_jobs()` (squeue) — correctly returns new jobs
2. `_apply_fetch_result("user_jobs", ...)` → `_handle_refresh_fallback` → `_job_cache._build_from_data()` — correctly adds new jobs to cache
3. `_sorted_jobs_for_display(self._job_cache.jobs)` — correctly sorts new pending job to position 0
4. `_update_jobs_table(job_rows)` → `set_data(job_rows)` → `_apply_incremental_update(new_rows_by_key)`
5. **BUG HERE**: `_apply_incremental_update` detects the new key in `added = new_visible - old_visible`, but appends it at the end via `table.add_row()` instead of inserting at the correct sorted position

### Why the sort fallback doesn't help

```python
# filterable_table.py:741-746
sort_active = self._sort_state.column_key is not None and self._sort_state.direction != SortDirection.NONE
if added and sort_active:
    self._rows_by_key = new_rows_by_key
    self._refresh_table_data()  # Full rebuild with correct order
    return
```

`sort_active` checks `_sort_state`, which tracks **user-initiated** column header sorts. The implicit ordering from `_sorted_jobs_for_display` is applied upstream in the data, not through `_sort_state`. So when no column header is clicked, `sort_active` is `False`, and new rows are simply appended.

### Confirmed working parts

- squeue fetching, parsing, cache building: all correct
- Background refresh timer: starts correctly after first cycle, fires every `refresh_interval` seconds
- Generation counter coalescing in `_update_jobs_table`: correct, ensures latest data wins
- `_post_ui_callback` mechanism: correct non-blocking message posting
- Thread safety of `JobCache`: correct with data lock
- Error fallback and notification deduplication: correct

## Proposed Solution

### Fix 1: Always do full rebuild when rows are added or removed (Simple)

In `_apply_incremental_update`, trigger a full rebuild whenever `added` is non-empty, regardless of `sort_active`. The data passed to `set_data()` is already pre-sorted, so `_refresh_table_data` will produce the correct order.

**File**: `stoei/widgets/filterable_table.py` — `_apply_incremental_update` method

```python
# Replace the sort_active check with:
if added or removed:
    self._rows_by_key = new_rows_by_key
    self._refresh_table_data()
    return
```

**Trade-off**: This sacrifices the incremental optimization for add/remove cases. However:
- New job submissions are infrequent (seconds to minutes apart)
- The full rebuild preserves cursor by key identity (already implemented in `_refresh_table_data`)
- The large-delta check above this already falls back to full rebuild for bulk changes
- Cell-value-only updates (the common case on each 5s refresh) still use the efficient incremental path

### Fix 2: Notify user when new jobs are detected

Add a notification when the refresh detects new jobs that weren't in the previous data.

**File**: `stoei/app.py` — `_apply_fetch_result` for `user_jobs` label

Compare the current job cache keys with the new ones. If new keys are detected, post a notification like "New job detected: <job_id> (<job_name>)" or for multiple: "N new jobs detected".

### Fix 3: Clean up dead code

Remove the unused `_update_ui_from_cache` method at `app.py:1316-1351` which is never called.

## Acceptance Criteria

- [x] Newly submitted jobs appear at the correct sorted position (top of table for pending jobs) within one refresh cycle (~5 seconds)
- [x] Existing `test_new_jobs_appear_after_refresh` integration test continues to pass
- [x] New test: verify row ORDER after a new job is added (new pending job should be at row 0, not appended at bottom)
- [x] New test: verify that cell-value-only updates (no row adds/removes) still use the efficient incremental path (no full rebuild)
- [x] Cursor position is preserved by identity when a new row triggers a full rebuild
- [x] User receives a notification when new jobs are detected
- [ ] No performance regression — test suite runs in under 20 seconds

## Technical Considerations

- **Cursor preservation during full rebuild**: `_refresh_table_data` already saves/restores cursor by key identity (line 620-627, 651-658). This means a full rebuild on row add/remove will correctly keep the cursor on the same job.
- **Large delta guard**: The existing large-delta check (`delta > max_visible // 2 and delta > 10`) already falls back to full rebuild for bulk changes. The new fix makes the single-row-add case also use full rebuild, which is consistent.
- **Notification spam**: Follow the project's notification convention — only notify once per batch of new jobs per refresh cycle. The notification is per-event (not recurring), so it doesn't need deduplication like error notifications.

## References

- Prior incremental refresh refactor: `docs/plans/2026-02-24-refactor-incremental-datatable-refresh-plan.md`
- Incremental update logic: `stoei/widgets/filterable_table.py:706-781`
- Pre-sort logic: `stoei/app.py:1270-1294`
- Refresh data flow: `stoei/app.py:919-963` (refresh worker), `stoei/app.py:996-1022` (apply fetch result)
- Existing integration test: `tests/integration/test_user_actions.py:154-188`
