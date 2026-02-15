---
title: "Decouple UI from SLURM Data Fetching for Smooth Navigation"
type: refactor
date: 2026-02-15
---

# ♻️ Decouple UI from SLURM Data Fetching for Smooth Navigation

## Overview

Refactor the data fetching and UI update pipeline so the TUI remains fully
interactive (sort, filter, navigate, switch tabs) while background data refreshes
are in progress. The user should never feel the UI "freeze" or become sluggish
during a refresh cycle.

## Problem Statement

The current refresh mechanism in `stoei/app.py` has several coupling issues that
cause perceptible UI sluggishness:

1. **Sequential SLURM command execution**: `_refresh_data_async()` (line 889)
   calls 7+ SLURM commands one after another in a single worker thread. Each
   command is a blocking `subprocess.run` call with timeouts of 5–60 seconds.
   The total refresh can take 30+ seconds on a loaded cluster.

2. **All-or-nothing UI update**: The UI only updates after *all* commands
   complete (line 927: `self.call_from_thread(self._update_ui_from_cache)`).
   If `get_running_jobs()` finishes in 1 second but `get_cluster_nodes()` takes
   15 seconds, the user sees stale job data for the entire duration.

3. **Shared mutable state without locking**: The worker thread writes directly
   to `self._cluster_nodes`, `self._all_users_jobs`, `self._wait_time_jobs`,
   `self._fair_share_entries`, `self._job_priority_entries`, and all
   `self._cached_*` attributes. The UI thread reads these same attributes with
   no synchronization beyond what the GIL provides.

4. **UI blocked during data processing**: Pre-computation of user stats, node
   infos, cluster stats, and priority data (`_compute_user_overview_cache`,
   `_compute_priority_overview_cache`, `_parse_node_infos`,
   `_calculate_cluster_stats`) all run in the worker thread before the UI update
   is scheduled, adding to the total blocking time.

## Proposed Solution

### Architecture: Message-Based Incremental Updates

Replace the monolithic fetch-then-update pattern with a pipeline where each data
source posts a Textual `Message` as soon as it completes, and the corresponding
handler updates only the affected widget(s) immediately.

```
Worker Thread (ThreadPoolExecutor)           Main (UI) Thread
========================================     ==============================
get_running_jobs()  ──→ JobsDataReady  ──→  update jobs table
get_job_history()   ──→ JobsDataReady  ──→  (merged with above)
get_cluster_nodes() ──→ NodesDataReady ──→  update node overview + sidebar
get_all_running_jobs()──→ AllJobsReady ──→  update user overview + sidebar
get_wait_time_*()   ──→ WaitTimeReady  ──→  update sidebar wait stats
get_fair_share_*()  ──→ PriorityReady  ──→  update priority overview
get_pending_*()     ──→ PriorityReady  ──→  (merged with above)
```

Key principles:
- **Data carried by messages**: Each message carries its data payload. The worker
  never writes to `self._*` attributes directly — only message handlers (which
  run on the main thread) do. This eliminates the cross-thread shared state issue.
- **Parallel subprocess execution**: Independent SLURM commands run concurrently
  via `concurrent.futures.ThreadPoolExecutor` inside the worker thread.
- **Incremental UI updates**: Each message handler updates only its widget. The
  user can sort/filter/navigate the jobs table while node data is still loading.
- **Pre-computation in the fetching thread**: Expensive computations
  (`_parse_node_infos`, `_calculate_cluster_stats`, `_compute_user_overview_cache`,
  `_compute_priority_overview_cache`) run in the fetching thread *before* posting
  the message. The message carries pre-computed results so the main-thread handler
  is a fast attribute swap + widget update.

## Technical Approach

### Phase 1: Define Data Messages and Parallel Fetching

**Files to modify:** `stoei/app.py`

1. **Define custom Textual Message subclasses** on `SlurmMonitor`:

```python
# stoei/app.py — new Message classes inside SlurmMonitor

class JobsDataReady(Message):
    """Posted when user's job data (running + history) is fetched."""
    def __init__(
        self,
        running_jobs: list[tuple[str, ...]],
        history_jobs: list[tuple[str, ...]],
        total_jobs: int,
        total_requeues: int,
        max_requeues: int,
    ) -> None:
        super().__init__()
        self.running_jobs = running_jobs
        self.history_jobs = history_jobs
        self.total_jobs = total_jobs
        self.total_requeues = total_requeues
        self.max_requeues = max_requeues

class NodesDataReady(Message):
    """Posted when cluster node data is fetched and pre-computed."""
    def __init__(
        self,
        nodes: list[dict[str, str]],
        node_infos: list[NodeInfo],
        cluster_stats: ClusterStats,
    ) -> None:
        super().__init__()
        self.nodes = nodes
        self.node_infos = node_infos
        self.cluster_stats = cluster_stats

class AllJobsDataReady(Message):
    """Posted when all-users job data is fetched and user stats pre-computed."""
    def __init__(
        self,
        all_jobs: list[tuple[str, ...]],
        running_user_stats: list[UserStats],
        pending_user_stats: list[UserPendingStats],
    ) -> None:
        super().__init__()
        self.all_jobs = all_jobs
        self.running_user_stats = running_user_stats
        self.pending_user_stats = pending_user_stats

class WaitTimeDataReady(Message):
    """Posted when wait-time history is fetched."""
    def __init__(self, wait_time_jobs: list[tuple[str, ...]]) -> None:
        super().__init__()
        self.wait_time_jobs = wait_time_jobs

class PriorityDataReady(Message):
    """Posted when fair-share and priority data is fetched and pre-computed."""
    def __init__(
        self,
        fair_share_entries: list[tuple[str, ...]],
        job_priority_entries: list[tuple[str, ...]],
        user_priorities: list[UserPriority],
        account_priorities: list[AccountPriority],
        job_priorities: list[JobPriority],
    ) -> None:
        super().__init__()
        self.fair_share_entries = fair_share_entries
        self.job_priority_entries = job_priority_entries
        self.user_priorities = user_priorities
        self.account_priorities = account_priorities
        self.job_priorities = job_priorities

class RefreshCycleComplete(Message):
    """Posted when all data sources have completed (success or failure)."""
    pass
```

2. **Rewrite `_refresh_data_async`** to use `ThreadPoolExecutor` and post
   messages as each data source completes:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _refresh_data_async(self) -> None:
    self.call_from_thread(lambda: self._set_loading_indicator(True))
    worker = get_current_worker()

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self._fetch_user_jobs): "user_jobs",
                pool.submit(get_cluster_nodes): "nodes",
                pool.submit(get_all_running_jobs): "all_jobs",
                pool.submit(self._fetch_wait_and_priority): "wait_priority",
            }

            for future in as_completed(futures):
                if worker.is_cancelled:
                    return
                label = futures[future]
                try:
                    result = future.result()
                    self._post_data_message(label, result)
                except Exception:
                    logger.exception(f"Failed to fetch {label}")

        self.post_message(self.RefreshCycleComplete())

    except Exception:
        logger.exception("Error during refresh")
    finally:
        self.call_from_thread(lambda: self._set_loading_indicator(False))
```

3. **Group related commands**: `get_fair_share_priority` and
   `get_pending_job_priority` are both priority-related and can share a single
   fetch function. Similarly, `get_running_jobs` and `get_job_history` are
   fetched together for the jobs cache. `get_wait_time_job_history` can be
   grouped with priority or run independently.

### Phase 2: Message Handlers — Incremental UI Updates

**Files to modify:** `stoei/app.py`

Replace the monolithic `_update_ui_from_cache` with per-message handlers:

```python
def on_slurm_monitor_jobs_data_ready(self, message: JobsDataReady) -> None:
    """Handle fresh user job data."""
    # Build cache from the snapshot
    self._handle_refresh_fallback(
        message.running_jobs, message.history_jobs,
        message.total_jobs, message.total_requeues, message.max_requeues,
    )
    # Update jobs table immediately
    try:
        jobs_filterable = self.query_one("#jobs-filterable-table", FilterableDataTable)
        self._update_jobs_table(jobs_filterable)
    except Exception:
        logger.exception("Failed to update jobs table from message")

def on_slurm_monitor_nodes_data_ready(self, message: NodesDataReady) -> None:
    """Handle fresh node data (pre-computed in fetching thread)."""
    self._cluster_nodes = message.nodes
    self._cached_node_infos = message.node_infos        # already computed
    self._cached_cluster_stats = message.cluster_stats   # already computed
    self._update_cluster_sidebar()
    # Update node tab if active
    ...

def on_slurm_monitor_all_jobs_data_ready(self, message: AllJobsDataReady) -> None:
    """Handle fresh all-users job data (user stats pre-computed)."""
    self._all_users_jobs = message.all_jobs
    self._cached_running_user_stats = message.running_user_stats
    self._cached_pending_user_stats = message.pending_user_stats
    self._update_my_usage_summary(self._cached_running_user_stats)
    # Update user tab if active
    ...

# ... similar handlers for WaitTimeDataReady, PriorityDataReady
```

**Key behavior**: Each handler runs on the main thread (Textual message loop).
The user can continue navigating between message deliveries since each handler
is a fast attribute swap + widget update (no expensive computation).

**Note on `post_message` from pool threads**: The `ThreadPoolExecutor` threads
are plain Python threads (not Textual workers). Textual documents `post_message`
as thread-safe, so this is supported. The `worker.is_cancelled` check uses the
enclosing Textual worker reference captured before submitting to the pool.

### Phase 3: Optional Polish — Differential Table Updates

**Files to modify:** `stoei/widgets/filterable_table.py`

**Only pursue if Phases 1+2 still show visible flicker during table updates.**

Add an `update_data()` method to `FilterableDataTable` that diffs new rows
against current rows and only adds/removes/updates changed rows. This preserves
the cursor position and selection more reliably than the current `set_data()`
clear-and-rebuild approach.

This is explicitly optional — `set_data()` may be perfectly fine once updates
are incremental and pre-computed.

## Acceptance Criteria

### Functional Requirements

- [x] User can sort, filter, and navigate the jobs table while a refresh is in progress
- [x] User can switch tabs while a refresh is in progress and see latest cached data immediately
- [x] Each data source updates its widget independently as soon as its data arrives
- [x] Manual refresh (R key) while auto-refresh is in progress is handled gracefully (cancel old, start new)
- [x] Job details modal is not disrupted when underlying data refreshes
- [x] SLURM command failures are isolated — one failing command does not block others
- [x] Partial failure shows a notification but still updates widgets with successful data
- [x] Loading indicator reflects overall refresh cycle (shown while any fetch is in progress)

### Non-Functional Requirements

- [x] Total refresh wall-clock time reduced by parallelizing independent SLURM commands
- [x] Worker thread never writes to `self._*` attributes — only posts messages with data
- [x] Message handlers (main thread) are fast: attribute swap + widget update, no heavy computation
- [x] Test suite continues to pass in under 20 seconds
- [x] No new external dependencies (uses stdlib `concurrent.futures`)

### Quality Gates

- [x] `uv run ruff format --check .` passes
- [x] `uv run ruff check .` passes
- [x] `uv run ty check stoei/` passes
- [x] `uv run pytest` passes with all tests green

## Dependencies & Risks

### Dependencies
- No new external packages required — `concurrent.futures` is stdlib
- Textual's `post_message` is documented as thread-safe

### Risks
- **Message ordering**: Messages may arrive in any order since SLURM commands
  complete at different times. Each handler must be independent and not assume
  prior messages have been processed. Mitigated by having each handler operate
  on its own data slice.
- **Worker cancellation timing**: `ThreadPoolExecutor.submit` cannot cancel
  already-running `subprocess.run` calls. When a worker is cancelled, in-flight
  subprocesses run to completion. Mitigated by using subprocess timeouts (already
  in place) and checking `worker.is_cancelled` between future completions.
- **Pre-computation uses stale cross-data references**: For example,
  `_calculate_cluster_stats` needs both `_cluster_nodes` and `_all_users_jobs`.
  If these are fetched by separate pool threads, the pre-computation in one
  thread may not have the other's data yet. Mitigated by grouping dependent
  computations — e.g., `NodesDataReady` computes cluster stats using *only* node
  data, and `AllJobsDataReady` computes user stats using *only* all-jobs data.
  Cross-data stats (like pending resource overlay on sidebar) use the latest
  cached value for the other data source.
- **Test mocking surface changes**: Tests that mock `_start_refresh_worker` or
  `_refresh_data_async` may need updates. Mitigated by updating mocks to match
  new method signatures.

## Implementation Order

1. **Phase 1** — Message classes + parallel fetching with pre-computation
2. **Phase 2** — Message handlers replace `_update_ui_from_cache`
3. **Phase 3** — Differential table updates (optional, only if flicker observed)

Phases 1+2 should be landed together as they form the core behavior change.
Phase 3 is optional polish — pursue only if needed.

## References

### Internal References
- `stoei/app.py:820` — `_start_refresh_worker` (current refresh entry point)
- `stoei/app.py:833` — `_refresh_cluster_data` (sequential cluster data fetch)
- `stoei/app.py:889` — `_refresh_data_async` (main refresh worker)
- `stoei/app.py:1039` — `_update_ui_from_cache` (monolithic UI update)
- `stoei/slurm/commands.py` — all SLURM subprocess calls
- `stoei/slurm/cache.py` — `JobCache` singleton with thread-safe locking
- `stoei/widgets/filterable_table.py` — `FilterableDataTable.set_data()`

### External References
- [Textual Workers Guide](https://textual.textualize.io/guide/workers/) — `run_worker`, `call_from_thread`, `post_message` thread safety
- [Textual Events & Messages Guide](https://textual.textualize.io/guide/events/) — custom Message subclasses
- [`concurrent.futures` docs](https://docs.python.org/3/library/concurrent.futures.html) — `ThreadPoolExecutor`, `as_completed`
