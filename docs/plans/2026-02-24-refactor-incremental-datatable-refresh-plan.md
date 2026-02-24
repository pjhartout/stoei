---
title: "Incremental DataTable Refresh"
type: refactor
date: 2026-02-24
---

# Incremental DataTable Refresh

## Overview

Replace the current clear-and-rebuild refresh pattern in `FilterableDataTable` with diff-based incremental updates. The current approach calls `table.clear(columns=False)` + `table.add_rows(sorted_rows)` on every 30-second refresh cycle, which destroys cursor position, resets scroll, causes visible flicker/reflow, and makes the TUI unusable when trying to interact with table rows.

## Problem Statement

Every refresh cycle in `_apply_refresh_to_ui()` (app.py:1030) pushes data through `FilterableDataTable.set_data()` (filterable_table.py:654), which calls `_refresh_table_data()` (filterable_table.py:604). This method:

1. Saves cursor position by index (not identity)
2. Clears all rows (`table.clear(columns=False)`)
3. Rebuilds all rows (`table.add_rows(sorted_rows)`)
4. Attempts to restore cursor to the same index

This causes:
- **Visible flicker**: Brief empty state between clear and rebuild
- **Cursor jump**: Cursor restored by position, not by row identity -- if rows shift, cursor lands on a different job
- **Scroll reset**: `clear()` resets scroll position to 0
- **Full DOM churn**: All internal row data structures, render caches, and dimension calculations are destroyed and recreated

The problem is most acute on the Jobs tab (always updated every cycle) but affects all 8 `FilterableDataTable` instances.

## Proposed Solution

Use Textual's `DataTable` cell-level and row-level APIs to apply minimal changes:

- **`update_cell(row_key, col_key, value, update_width=False)`** for changed cell values
- **`add_row(*cells, key=row_key)`** for new rows
- **`remove_row(row_key)`** for disappeared rows
- **`app.batch_update()`** to suppress intermediate repaints during multi-cell updates

The diff logic lives inside `FilterableDataTable`, making it transparent to all callers (`app.py`, tab widgets).

## Technical Approach

### Architecture

The change is concentrated in two files:

1. **`stoei/widgets/filterable_table.py`** -- Core diff engine inside `FilterableDataTable`
2. **`stoei/app.py`** -- Minor changes to pass keyed row data

All 8 `FilterableDataTable` instances benefit automatically since the logic is in the shared widget.

### Key Design Decisions

**Row keys**: Each table row gets a stable identity key passed to `DataTable.add_row(key=...)`. Natural keys per table:

| Table | Key Field | Column Index |
|-------|-----------|--------------|
| Jobs | `job_id` | 0 |
| Nodes | `node_name` | 0 |
| Users (running) | `username` | 0 |
| Users (pending) | `username` | 0 |
| Users (energy) | `username` | 0 |
| Priority (users) | `username` | 0 |
| Priority (accounts) | `account` | 0 |
| Priority (jobs) | `job_id` | 0 |

All tables conveniently use column 0 as the key.

**Diff location**: Computed on the main thread inside `FilterableDataTable.set_data()`. For typical job counts (tens to low hundreds of rows, ~7-10 columns), the diff computation is sub-millisecond and does not warrant threading.

**Fallback threshold**: If more than 60% of rows are added or removed, fall back to clear+rebuild. This handles bulk state changes (e.g., large array job completing) where `remove_row()` O(n)-per-call overhead exceeds a single clear+rebuild.

**Sort interaction**: When rows are added or removed AND a sort is active, fall back to full rebuild of visible rows (since `DataTable.add_row()` is append-only with no positional insertion). When only cell values change (no add/remove), incremental `update_cell()` is used and sort order may be temporarily stale until the next sort toggle or full rebuild.

**Filter interaction**: Diff operates on `_all_rows` (pre-filter). After computing the diff, re-evaluate `_row_matches_filter()` for changed/added rows to determine visibility changes.

**Data-change vs view-change**: Only `set_data()` uses the diff path. Sort changes (`_set_sort()`) and filter changes (`_apply_filter()`) continue to use clear+rebuild, since the entire visible row set transforms.

### Implementation Phases

#### Phase 1: Row Key Infrastructure

Add key awareness to `FilterableDataTable`:

**`stoei/widgets/filterable_table.py`**:
- Add `key_column_index: int = 0` parameter to `__init__()` (or make it configurable per instance)
- Change `_all_rows` from `list[tuple[Any, ...]]` to maintain a parallel `dict[str, tuple[Any, ...]]` keyed by the key column value (`_rows_by_key`)
- In `_refresh_table_data()`, pass `key=row[key_column_index]` to `add_row()` calls
- Store column keys from `add_columns()` for use with `update_cell()`

**Acceptance Criteria**:
- [x] All tables add rows with explicit keys
- [x] `_rows_by_key` tracks current row state for diffing
- [x] Existing behavior unchanged (still clear+rebuild, just with keys)
- [x] All tests pass

#### Phase 2: Diff Engine in `FilterableDataTable`

Implement the diff logic:

**`stoei/widgets/filterable_table.py`**:

New method `_apply_incremental_update()`:

```
def _apply_incremental_update(self, new_rows_by_key, new_all_rows):
    old_keys = set(self._rows_by_key.keys())
    new_keys = set(new_rows_by_key.keys())

    added = new_keys - old_keys
    removed = old_keys - new_keys
    common = old_keys & new_keys

    # Fallback: too many structural changes
    if len(added) + len(removed) > 0.6 * max(len(old_keys), 1):
        -> fall back to clear+rebuild

    # Fallback: sort is active AND rows added/removed
    if self._sort_state and (added or removed):
        -> fall back to clear+rebuild (add_row is append-only)

    # Apply removals
    for key in removed:
        if row was visible (matched filter):
            table.remove_row(key)

    # Apply additions
    for key in added:
        if row matches current filter:
            table.add_row(*row, key=key)

    # Apply cell updates (with batch_update)
    with self.app.batch_update():
        for key in common:
            old_row = self._rows_by_key[key]
            new_row = new_rows_by_key[key]
            if old_row != new_row:
                # Check filter visibility changes
                was_visible = self._row_matches_filter(old_row)
                now_visible = self._row_matches_filter(new_row)
                if was_visible and not now_visible:
                    table.remove_row(key)
                elif not was_visible and now_visible:
                    table.add_row(*new_row, key=key)
                elif was_visible and now_visible:
                    for col_idx, col_key in enumerate(self._column_keys):
                        if old_row[col_idx] != new_row[col_idx]:
                            table.update_cell(key, col_key, new_row[col_idx],
                                              update_width=False)

    # Update internal state
    self._rows_by_key = new_rows_by_key
    self._all_rows = new_all_rows
```

Modify `set_data()`:
```
def set_data(self, rows):
    new_rows_by_key = {row[self._key_column_index]: row for row in rows}
    if self._rows_by_key is not None:  # Not first load
        self._apply_incremental_update(new_rows_by_key, rows)
    else:
        self._all_rows = list(rows)
        self._rows_by_key = new_rows_by_key
        self._refresh_table_data()  # First load: full build
```

**Acceptance Criteria**:
- [x] Cell updates use `update_cell()` instead of clear+rebuild
- [ ] New rows use `add_row(key=...)` (deferred: visible set changes trigger full rebuild for correctness)
- [ ] Removed rows use `remove_row(key)` (deferred: visible set changes trigger full rebuild for correctness)
- [ ] Fallback to clear+rebuild above 60% structural change threshold (simplified: any visible set change triggers rebuild)
- [ ] Fallback to clear+rebuild when sort active + rows added/removed (simplified: any visible set change triggers rebuild)
- [x] First load uses full build (no previous state to diff)
- [x] Filter visibility changes handled correctly

#### Phase 3: Cursor Preservation by Identity

**`stoei/widgets/filterable_table.py`**:
- Before any update, capture the cursor's row **key** (not index): `cursor_key = table.get_row_key_at(table.cursor_row)` (or equivalent lookup)
- After incremental update, restore cursor to the row with the same key
- If the key was removed, move cursor to the nearest row by index (min of old position, new row count - 1)
- For clear+rebuild fallback, also restore cursor by key instead of by index

**Acceptance Criteria**:
- [x] Cursor stays on the same job across refreshes when job still exists
- [x] Cursor moves to nearest row when tracked job disappears
- [x] Scroll position preserved during cell-only updates
- [x] Scroll position reasonable after row additions/removals

#### Phase 4: Cleanup and Optimization

- Remove dead code: unused message handlers from the incremental delivery pattern in app.py (lines 1258-1376) and `_post_fetch_message()` (line 1088) that are leftover from commit `1c53267`
- Add DEBUG logging for diff stats: `"Diff: {added} added, {removed} removed, {updated_cells} cells updated, {unchanged} rows unchanged"`
- Verify `update_width=False` is used consistently to avoid column width recalculation overhead
- Profile with typical SLURM output (50-200 jobs) to confirm performance improvement

**Acceptance Criteria**:
- [ ] No dead code from previous incremental delivery attempt (deferred to separate cleanup PR)
- [x] Debug logging shows diff statistics
- [x] Performance measurably improved (no visible flicker, cursor stable)

## Acceptance Criteria

### Functional Requirements

- [ ] Cursor stays on the same row (by job ID) across refresh cycles
- [ ] Scroll position preserved when only cell values change
- [ ] New jobs appear in the table without disturbing existing rows
- [ ] Completed/cancelled jobs disappear without disturbing cursor on other rows
- [ ] Filter still works correctly: filtered-out rows that change state and now match the filter become visible
- [ ] Sort still works correctly (toggling sort re-sorts correctly)
- [ ] First load (no previous data) works identically to current behavior
- [ ] SLURM fetch errors handled gracefully (no crash, stale data preserved)
- [ ] All 8 `FilterableDataTable` instances benefit from incremental updates
- [ ] Dirty flag optimization for non-active tabs still works

### Non-Functional Requirements

- [ ] No visible flicker during refresh
- [ ] Refresh cycle completes in under 100ms of main-thread time (for typical 50-200 jobs)
- [ ] Test suite passes and stays under 20 seconds
- [ ] No regressions in existing functionality

## Dependencies & Risks

**Dependencies**:
- Textual 6.11.0 `DataTable.update_cell()`, `add_row(key=...)`, `remove_row()` APIs (already available)
- Textual `App.batch_update()` context manager (already available)

**Risks**:
- `remove_row()` is O(n) per call due to `TwoWayDict` rebuild. Mitigated by the 60% fallback threshold.
- `add_row()` is append-only (no positional insertion). Mitigated by falling back to full rebuild when sort is active and rows are added/removed.
- Rich markup in cell values may cause false-positive "changed" detections if formatting changes without data changes. Mitigated by comparing raw row tuples which include the formatting.
- Array job expansion (one pending row -> many running rows) triggers the fallback threshold naturally, since it's a large structural change.

## References & Research

### Internal References

- `FilterableDataTable._refresh_table_data()`: `stoei/widgets/filterable_table.py:604` -- current clear+rebuild
- `FilterableDataTable.set_data()`: `stoei/widgets/filterable_table.py:654` -- entry point for data updates
- `SlurmMonitor._apply_refresh_to_ui()`: `stoei/app.py:1030` -- where refresh data hits the UI
- `SlurmMonitor._refresh_data_async()`: `stoei/app.py:930` -- background refresh worker
- `Job` dataclass: `stoei/slurm/cache.py:53` -- job data model
- `SlurmMonitor._job_row_values()`: `stoei/app.py:1196` -- job-to-row mapping

### External References

- [Textual DataTable docs](https://textual.textualize.io/widgets/data_table/)
- [Textual Discussion #3328: Updating DataTable data](https://github.com/Textualize/textual/discussions/3328) -- periodic update with `update_cell`
- [Textual Discussion #5953: DataTable performance](https://github.com/Textualize/textual/discussions/5953) -- column count impacts rendering
- [Textual Issue #5273: Bulk row removal](https://github.com/Textualize/textual/issues/5273) -- `remove_rows` not yet available
- [Textual 0.12.0 blog: batch updates](https://textual.textualize.io/blog/2023/02/24/textual-0120-adds-syntactical-sugar-and-batch-updates/)

### Key Textual API Notes

- `update_cell(row_key, col_key, value, update_width=False)`: O(1) with `update_width=False`. Always use this flag.
- `add_row(*cells, key=key)`: Appends to end. No positional insertion.
- `remove_row(row_key)`: O(n) due to TwoWayDict rebuild. Avoid in tight loops on large tables.
- `batch_update()`: Suppresses screen repaints. Good for multi-cell updates spanning `await` points.
- `clear()`: Resets cursor to (0,0) and scroll to 0. This is the root cause of the current UX issues.
