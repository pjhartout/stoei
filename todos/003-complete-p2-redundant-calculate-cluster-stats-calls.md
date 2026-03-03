---
status: complete
priority: p2
issue_id: "003"
tags: [code-review, performance, redundancy]
dependencies: ["001"]
---

# 003 · `_calculate_cluster_stats()` called 3× per cycle

## Problem Statement

`_apply_fetch_result` calls `self._calculate_cluster_stats()` in three separate branches:
`nodes`, `all_jobs`, and `wait_time`.  The first two invocations produce a `ClusterStats` object
that is immediately overwritten by the next invocation; only the third write survives until the
next call.  This wastes CPU and — combined with the race described in todo 001 — means the sidebar
can briefly display stats derived from partial data before the final write.

Relatedly, `_update_cluster_sidebar` (which reads `_cached_cluster_stats`) is triggered three
times per cycle: once from `_update_nodes_and_sidebar`, once from `_update_all_jobs_widgets`, and
once directly from the `wait_time` branch.  That's three full sidebar re-renders per cycle.

## Findings

- `stoei/app.py` — `_apply_fetch_result`, `nodes` branch (line ~954): `self._cached_cluster_stats = self._calculate_cluster_stats()`
- `stoei/app.py` — `_apply_fetch_result`, `all_jobs` branch (line ~963): same
- `stoei/app.py` — `_apply_fetch_result`, `wait_time` branch (line ~970): same
- `stoei/app.py` — `_update_nodes_and_sidebar` calls `_update_cluster_sidebar`
- `stoei/app.py` — `_update_all_jobs_widgets` calls `_update_cluster_sidebar`
- `stoei/app.py` — `wait_time` branch calls `call_from_thread(self._update_cluster_sidebar)` directly

## Proposed Solutions

### Option A — Defer stats recomputation to `_on_refresh_complete` (Recommended, Small effort)

Remove the three redundant `_calculate_cluster_stats()` calls from the per-label branches.
Compute stats once after all futures complete, in `_on_refresh_complete`, then call
`_update_cluster_sidebar` once.

Each per-label callback still updates its own widget (jobs table, node overview, user overview)
but does not touch cluster stats.

```python
# _apply_fetch_result — nodes branch
self._cluster_nodes = result
self._cached_node_infos = self._parse_node_infos()
self.call_from_thread(self._update_node_overview_only)  # no sidebar

# _on_refresh_complete
self._cached_cluster_stats = self._calculate_cluster_stats()
self._update_cluster_sidebar()  # called once, on main thread already
```

Pros: single stats computation; single sidebar render per cycle; fixes half the race from todo 001.
Cons: sidebar now shows stale (previous cycle) stats until `_on_refresh_complete` fires, rather
than being partially updated mid-cycle.  For most users this is acceptable.
Effort: Small | Risk: Low

### Option B — Pass partial stats snapshot to callbacks (Medium effort)

Keep progressive sidebar updates but pass a snapshot of the current (partial) stats to each
callback via closure instead of through the shared field.  See also todo 001 Option A.

Pros: sidebar updates progressively and race-free.
Cons: `_calculate_cluster_stats` still called 3×; need to thread value through helpers.
Effort: Medium | Risk: Low

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `stoei/app.py` (`_apply_fetch_result`, `_update_nodes_and_sidebar`, `_update_all_jobs_widgets`)

## Acceptance Criteria

- [ ] `_calculate_cluster_stats()` called at most once per refresh cycle
- [ ] `_update_cluster_sidebar()` called at most once per refresh cycle
- [ ] No visible regression in sidebar accuracy
- [ ] `uv run pytest` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52

## Resources

- PR #52: feat/progressive-rendering
- Related: todo 001 (race condition on `_cached_cluster_stats`)
