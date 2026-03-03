---
status: pending
priority: p1
issue_id: "001"
tags: [code-review, concurrency, race-condition, thread-safety]
dependencies: []
---

# 001 · Race condition on `_cached_cluster_stats`

## Problem Statement

`_apply_fetch_result` runs inside a worker thread and writes `_cached_cluster_stats` three times
across three different label branches (`nodes`, `all_jobs`, `wait_time`).  After each write it
immediately posts a `call_from_thread` callback to the main event loop.  That callback
(`_update_nodes_and_sidebar`, `_update_all_jobs_widgets`, or `_update_cluster_sidebar`) reads
`_cached_cluster_stats` on the **main thread** — but the `as_completed` loop continues to iterate
and overwrite `_cached_cluster_stats` on the **worker thread** concurrently.

Because CPython's GIL does not make complex object reads/writes atomic, a partially-constructed
`ClusterStats` object can be observed by the main thread mid-write.  More practically, the
sidebar may display stats that mix values from two different refresh batches.

## Findings

- `stoei/app.py` — `_apply_fetch_result`, branches `nodes` (line ~954), `all_jobs` (line ~963), `wait_time` (line ~970)
- Each branch does: `self._cached_cluster_stats = self._calculate_cluster_stats()` then immediately
  calls `self.call_from_thread(self._update_cluster_sidebar)`.
- The main-thread callback reads `self._cached_cluster_stats` while the worker thread may be
  writing it in a subsequent iteration.
- All 6 review agents flagged this as the most significant correctness issue in the PR.

## Proposed Solutions

### Option A — Local snapshot (Recommended, Small effort)

Pass the computed stats directly to the callback instead of reading the shared field:

```python
# worker thread
stats = self._calculate_cluster_stats()
self._cached_cluster_stats = stats          # still update the cache
self.call_from_thread(lambda s=stats: self._update_cluster_sidebar_with(s))

# main thread (new helper)
def _update_cluster_sidebar_with(self, stats: ClusterStats) -> None:
    sidebar = self.query_one("#cluster-sidebar", ClusterSidebar)
    sidebar.update(stats)
```

Pros: zero synchronisation primitives needed; snapshot is immutable in the callback's closure.
Cons: requires threading the stats value through several helper methods.
Effort: Small | Risk: Low

### Option B — `threading.Lock` around the cached field (Medium effort)

Wrap all reads/writes of `_cached_cluster_stats` in a `threading.Lock`:

```python
self._stats_lock = threading.Lock()
# writer (worker thread):
with self._stats_lock:
    self._cached_cluster_stats = self._calculate_cluster_stats()
# reader (main thread):
with self._stats_lock:
    stats = self._cached_cluster_stats
```

Pros: minimal code change; no method signature changes.
Cons: adds a lock that must be acquired consistently everywhere — easy to miss future call sites.
Effort: Small-Medium | Risk: Medium

### Option C — Compute stats only once per cycle (Medium effort)

Eliminate the redundant calls (see todo 003) so `_cached_cluster_stats` is written only once, at
the end of the cycle in `_on_refresh_complete`.  Each per-source callback queries the current
(possibly partial) local data directly rather than through the shared cache.

Pros: removes the source of contention entirely; aligns with the single-write-per-cycle model.
Cons: larger refactor; partial-data callbacks must compute their own sidebar values.
Effort: Medium | Risk: Medium

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `stoei/app.py` (`_apply_fetch_result`, `_update_cluster_sidebar`, `_update_nodes_and_sidebar`, `_update_all_jobs_widgets`)
- **Affected components**: ClusterStats shared state, sidebar widget, progressive rendering loop

## Acceptance Criteria

- [ ] A unit test demonstrates that the race cannot produce a partially-constructed stats view
- [ ] `_cached_cluster_stats` is never read on the main thread while the worker may still be writing it
- [ ] `uv run pytest` passes with no regressions
- [ ] `uv run ty check stoei/` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52 (progressive rendering)

## Resources

- PR #52: feat/progressive-rendering
- Textual docs on `call_from_thread`: https://textual.textualize.io/guide/workers/#thread-workers
