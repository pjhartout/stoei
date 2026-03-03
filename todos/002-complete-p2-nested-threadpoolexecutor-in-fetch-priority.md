---
status: complete
priority: p2
issue_id: "002"
tags: [code-review, concurrency, architecture, threadpool]
dependencies: []
---

# 002 · Nested `ThreadPoolExecutor` in `_fetch_priority`

## Problem Statement

`_fetch_priority` is itself submitted to the outer `ThreadPoolExecutor` in `_refresh_data_async`.
Inside it, a *second* `ThreadPoolExecutor(max_workers=2)` is created, spinning up two extra threads
per refresh cycle.  This makes the actual thread budget opaque (outer pool: 5–6 workers, inner
pool: 2 extra per `_fetch_priority` invocation).  Additionally, the sequential
`for fut, name in ((fs_fut, "sshare"), (jp_fut, "sprio"))` loop calls `fut.result()` on `fs_fut`
first — if `sshare` is slow, the loop still blocks even though `sprio` may have finished.

## Findings

- `stoei/app.py` — `_fetch_priority` (line ~828)
- The nested pool is created every refresh cycle and torn down after two results are collected.
- `fs_fut.result()` is awaited before `jp_fut.result()`, negating parallelism in the error path.
- Performance oracle and architecture strategist both flagged this pattern.

## Proposed Solutions

### Option A — Submit both to the outer pool directly (Recommended, Small effort)

Rather than creating a nested pool, submit `get_fair_share_priority` and `get_pending_job_priority`
as two separate futures in `_refresh_data_async`, with distinct labels (`"fair_share"` and
`"job_priority"`), and handle each result independently in `_apply_fetch_result`.

```python
# in _refresh_data_async
futures = {
    ...
    pool.submit(get_fair_share_priority, max_retries=1): "fair_share",
    pool.submit(get_pending_job_priority, max_retries=1): "job_priority",
}

# in _apply_fetch_result
elif label == "fair_share":
    entries, error = result  # type: ignore[misc]
    if error:
        logger.warning(f"sshare failed: {error}")
    else:
        self._fair_share_entries = entries

elif label == "job_priority":
    entries, error = result  # type: ignore[misc]
    if error:
        logger.warning(f"sprio failed: {error}")
    else:
        self._job_priority_entries = entries
    # Update priority UI only after both halves have arrived — or accept partial update
    self._compute_priority_overview_cache()
    self.call_from_thread(self._update_priority_tab)
```

Note: combining the two results for a single priority tab update requires tracking which halves
have arrived (a small counter or two flags).

Pros: single thread-pool; true parallelism; cleaner accounting.
Cons: requires coordinating two labels before triggering the priority tab update.
Effort: Small-Medium | Risk: Low

### Option B — Keep `_fetch_priority` but use `as_completed` internally (Small effort)

Replace the sequential `for fut, name in (...)` loop with `as_completed`:

```python
for fut in as_completed({fs_fut: "sshare", jp_fut: "sprio"}):
    name = {fs_fut: "sshare", jp_fut: "sprio"}[fut]
    ...
```

Pros: both futures are consumed in completion order; minimal change.
Cons: still creates a nested pool; thread budget still opaque.
Effort: Tiny | Risk: Very Low

### Option C — Remove nested pool; run sequentially with reduced retries (Tiny effort)

Simply call the two functions sequentially (no inner pool) but with `max_retries=0`:

```python
def _fetch_priority(self) -> ...:
    fs_entries, fs_err = get_fair_share_priority(max_retries=0)
    jp_entries, jp_err = get_pending_job_priority(max_retries=0)
    ...
```

Worst case: 30s + 30s = 60s (same as current nested pool if one hangs).
Pros: simplest possible code; no extra threads.
Cons: loses true parallelism; priority tab still blocks for up to 60s.
Effort: Tiny | Risk: Very Low

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `stoei/app.py` (`_fetch_priority`, `_refresh_data_async`)
- **Affected commands**: `get_fair_share_priority`, `get_pending_job_priority` in `stoei/slurm/commands.py`

## Acceptance Criteria

- [ ] Only one `ThreadPoolExecutor` is active per refresh cycle
- [ ] `sshare` and `sprio` run concurrently
- [ ] Thread count per cycle is bounded and documented
- [ ] `uv run pytest` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52

## Resources

- PR #52: feat/progressive-rendering
