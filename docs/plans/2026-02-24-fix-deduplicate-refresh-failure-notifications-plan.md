---
title: "fix: Deduplicate refresh failure notifications"
type: fix
date: 2026-02-24
---

# fix: Deduplicate refresh failure notifications

When a SLURM data refresh fails, the app currently shows the same error notification on every single refresh cycle. This is bad UX -- the user should see the error **once**, and only again if the error recurs after a successful recovery.

## Problem Statement

The auto-refresh timer fires every N seconds. When a data source fails:

- **History failure** (live code, `app.py:1133`): `"History refresh failed - using cached history"` fires via `call_from_thread` on **every** cycle where `history_jobs is None`. This is the primary annoyance.
- **Running jobs failure** (silent): When `running_jobs is None`, `_process_refresh_results` (line 994) skips the entire processing block silently. No notification. Additionally, valid `history_jobs` data is **discarded** due to the gating `if running_jobs is not None` check.
- **Dead code** (`app.py:1275`): `on_slurm_monitor_jobs_data_ready` contains a running jobs failure notification, but `_post_fetch_message` is never called -- this handler is orphaned.

## Proposed Solution

### 1. Add error state tracking

Add a dict to `SlurmMonitor.__init__` (`app.py`, around line 243):

```python
self._error_notified: dict[str, bool] = {}
```

Keys: `"running_jobs"`, `"history_jobs"`. Set to `True` after first notification, cleared on success.

### 2. Deduplicate notifications

In `_handle_refresh_fallback` (`app.py:1111-1140`), wrap the history failure notification:

```python
if history_jobs is None:
    history_jobs = list(self._last_history_jobs)
    total_jobs, total_requeues, max_requeues = self._last_history_stats
    if not self._error_notified.get("history_jobs"):
        self._error_notified["history_jobs"] = True
        self.call_from_thread(
            lambda: self.notify("History refresh failed - using cached history", severity="warning")
        )
else:
    self._error_notified["history_jobs"] = False
```

### 3. Add running jobs failure notification (currently silent)

In `_process_refresh_results` (`app.py:992-995`), when `running_jobs is None`, add a one-time notification:

```python
if running_jobs is None:
    if not self._error_notified.get("running_jobs"):
        self._error_notified["running_jobs"] = True
        self.call_from_thread(
            lambda: self.notify("Running jobs refresh failed - keeping old data", severity="warning")
        )
else:
    self._error_notified["running_jobs"] = False
```

### 4. Fix data-gating bug

Process `history_jobs` independently of `running_jobs` at line 992-995. If running jobs fail but history succeeds, still update `_last_history_jobs` and rebuild cache with old running data + new history.

### 5. Reset flags on manual refresh

In `action_refresh()` (`app.py:2018`), clear the dict before triggering refresh so the user always gets feedback on explicit actions:

```python
def action_refresh(self) -> None:
    logger.info("Manual refresh triggered")
    self._error_notified.clear()
    self.notify("Refreshing...")
    self._start_refresh_worker()
```

### 6. Remove dead code

Remove orphaned handlers that will never fire and confuse future readers:
- `_post_fetch_message` (`app.py:1088-1110`)
- `on_slurm_monitor_jobs_data_ready` (`app.py:1258-1275`)
- Any other orphaned message handlers in the 1258-1376 range

## Thread Safety Note

All flag operations occur in the worker thread. The `exclusive=True` flag on `run_worker` (line 816) ensures only one refresh worker runs at a time, so no concurrent access. Manual refresh clears flags on the main thread before starting a new worker, which is safe since the old worker is cancelled by `exclusive=True`.

## Acceptance Criteria

- [x] History failure notification shows only once per failure episode
- [x] Running jobs failure notification shows once per failure episode (new behavior -- currently silent)
- [x] Flags reset on successful data fetch (next failure re-notifies)
- [x] Manual refresh always re-notifies on failure
- [x] Dead message handlers removed
- [x] Data-gating bug fixed: history processed independently of running jobs
- [x] Existing tests updated, new tests added for deduplication logic

## Files to Modify

- `stoei/app.py` -- all changes above
- `tests/unit/test_app_refresh_fallback.py` -- update/add tests for dedup behavior
- `CLAUDE.md` -- add note about notification design principle

## References

- Dead code identified in: `docs/plans/2026-02-24-refactor-incremental-datatable-refresh-plan.md:193`
- Refresh worker: `stoei/app.py:805-817`
- History fallback: `stoei/app.py:1111-1140`
- Process results: `stoei/app.py:979-1028`
