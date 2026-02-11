---
title: "feat: Show which nodes each user is running jobs on"
type: feat
date: 2026-02-11
---

# feat: Show which nodes each user is running jobs on

## Overview

Add a "NodeList" column to the Running Users table and a NodeList section to the User Info modal so users can see which specific nodes each user is running jobs on, not just how many nodes they occupy.

## Problem Statement / Motivation

The Running Users tab currently shows: User, Jobs, CPUs, Memory (GB), GPUs, GPU Types, Nodes (integer count). While knowing *how many* nodes a user occupies is useful, knowing *which* nodes they're on is more actionable. This helps cluster users identify:
- Which nodes are occupied by a specific user
- Where to look for available resources
- If a user is monopolizing specific hardware

The data already flows through the system (`get_all_running_jobs()` fetches `NodeList` at tuple index 7) but is ignored during user aggregation.

## Proposed Solution

Collect per-job `NodeList` strings during user aggregation, deduplicate them, and display them in compressed Slurm notation (e.g., `gpu[01-04],cpu[10-12]`).

**Display locations:**
1. **Running Users table** — new "NodeList" column next to existing "Nodes" count
2. **User Info modal** — "NodeList" line in User Summary section + per-job NodeList in the Job List table

## Technical Approach

### Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Aggregation strategy | Collect unique raw per-job NodeList strings, sort, join with comma | Simple, preserves Slurm compressed notation, no need for hostlist parser |
| Pending job filtering | Filter parenthesized reason strings (e.g., `(Resources)`) in `_process_job_for_user()` | Defense-in-depth: safe regardless of caller pre-filtering |
| NodeList squeue width | Increase from `NodeList:30` to `NodeList:80` in both squeue format strings | 30 chars truncates multi-node jobs silently, producing invalid notation |
| Table column width | Add with `width=20` to `RUNNING_USERS_COLUMNS` | Balances information density with screen space |
| "Total Nodes" in modal | Keep both "Total Nodes" (count) and new "NodeList" (names) | Complementary info: count for quick comparison, names for specifics |
| Account Info modal | Not updated in this iteration | Follow-up work to maintain scope |

### Implementation Phases

#### Phase 1: Widen NodeList in squeue format strings

Update squeue format strings and recalculate fixed-width column constants.

**Files:**
- `stoei/slurm/commands.py:554-575` — Update `_SQUEUE_ALL_COL_*` and `_SQUEUE_USER_COL_*` constants
- `stoei/slurm/commands.py:649-653` — Update `get_all_running_jobs()` format string: `NodeList:30` → `NodeList:80`
- `stoei/slurm/commands.py:744-746` — Update `get_user_jobs()` format string: `NodeList:30` → `NodeList:80`

**Details for `get_all_running_jobs()` format:**
```
"JobID:30,Name:50,UserName:15,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:80,tres:80"
```

New column boundary constants (shifted +50 after NodeList):
```python
_SQUEUE_ALL_COL_JOBID_END = 30
_SQUEUE_ALL_COL_NAME_END = 80
_SQUEUE_ALL_COL_USER_END = 95
_SQUEUE_ALL_COL_PARTITION_END = 110
_SQUEUE_ALL_COL_STATE_END = 120
_SQUEUE_ALL_COL_TIME_END = 132
_SQUEUE_ALL_COL_NODES_END = 138
_SQUEUE_ALL_COL_NODELIST_END = 218   # was 168
# TRES starts at 218 (was 168)
```

**Details for `get_user_jobs()` format:**
```
"JobID:30,Name:50,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:80,tres:80"
```

New column boundary constants (shifted +50 after NodeList):
```python
_SQUEUE_USER_COL_JOBID_END = 30
_SQUEUE_USER_COL_NAME_END = 80
_SQUEUE_USER_COL_PARTITION_END = 95
_SQUEUE_USER_COL_STATE_END = 105
_SQUEUE_USER_COL_TIME_END = 117
_SQUEUE_USER_COL_NODES_END = 123
_SQUEUE_USER_COL_NODELIST_END = 203   # was 153
# TRES starts at 203 (was 153)
```

#### Phase 2: Add node_names to UserStats and aggregation

**Files:**
- `stoei/widgets/user_overview.py:36-47` — Add `node_names: str = ""` to `UserStats` dataclass
- `stoei/widgets/user_overview.py:49-57` — Add `node_names: set[str]` to `_UserDataDict` TypedDict
- `stoei/widgets/user_overview.py:617-626` — Update `_default_user_data()` to initialize `node_names: set()`
- `stoei/widgets/user_overview.py:522-559` — Update `_process_job_for_user()`:
  - Accept a new `nodelist_index` parameter (default 7)
  - Read `job[nodelist_index]` and add to `user_data["node_names"]` set
  - Skip values matching parenthesized reason strings (regex `^\(.*\)$`)
  - Skip empty strings
- `stoei/widgets/user_overview.py:574-597` — Update `_convert_to_user_stats()`:
  - Sort `node_names` set and join with comma to produce `UserStats.node_names`

```python
# In _process_job_for_user, after existing logic:
nodelist_str = job[nodelist_index].strip() if len(job) > nodelist_index else ""
if nodelist_str and not nodelist_str.startswith("("):
    user_data["node_names"].add(nodelist_str)
```

```python
# In _convert_to_user_stats:
node_names_str = ",".join(sorted(data["node_names"]))
```

Also update `aggregate_user_stats()` to pass `nodelist_index=7` to `_process_job_for_user()`.

#### Phase 3: Add NodeList column to Running Users table

**Files:**
- `stoei/widgets/user_overview.py:164-172` — Add `ColumnConfig(name="NodeList", key="nodelist", sortable=True, filterable=True, width=20)` after the "Nodes" column
- `stoei/widgets/user_overview.py:384-397` — Update `update_users()` to include `user.node_names` in row tuple (position after `str(user.total_nodes)`)

```python
rows.append(
    (
        user.username,
        str(user.job_count),
        str(user.total_cpus),
        f"{user.total_memory_gb:.1f}",
        str(user.total_gpus) if user.total_gpus > 0 else "0",
        gpu_types_display,
        str(user.total_nodes),
        user.node_names if user.node_names else "N/A",
    )
)
```

#### Phase 4: Update User Info modal

**Files:**
- `stoei/slurm/formatters.py:607-794` — Update `format_user_info()`:

**4a. User Summary section** (after line 650 "Total Nodes"):
```python
lines.append(f"  [bold {c.primary}]{'Total Nodes':.<24}[/bold {c.primary}] {user_stats.total_nodes}")
if user_stats.node_names:
    lines.append(
        f"  [bold {c.primary}]{'NodeList':.<24}[/bold {c.primary}] [{c.accent}]{user_stats.node_names}[/{c.accent}]"
    )
```

**4b. Job List table** — Add NodeList column (index 6 from `get_user_jobs()` tuples):
- Add `_USER_INFO_NODELIST_WIDTH = 20` constant
- Update header to include "NodeList" column
- Update each job row to show `job[6]` (NodeList) when available
- Increase separator width from 70 to 92

```python
# Updated header
lines.append(
    "  [dim]"
    f"{'JobID':<{_USER_INFO_JOBID_WIDTH}} "
    f"{'Name':<{_USER_INFO_NAME_WIDTH}} "
    f"{'State':<{_USER_INFO_STATE_WIDTH}} "
    f"{'Partition':<{_USER_INFO_PARTITION_WIDTH}} "
    f"{'Time':<{_USER_INFO_TIME_WIDTH}} "
    f"{'Nodes':<{_USER_INFO_NODES_WIDTH}} "
    f"{'NodeList':<{_USER_INFO_NODELIST_WIDTH}}"
    "[/dim]"
)
```

#### Phase 5: Tests

**Unit tests** (`tests/unit/widgets/test_user_overview.py` or similar):
- `test_aggregate_user_stats_collects_node_names` — Jobs on different nodes produce correct aggregated `node_names`
- `test_aggregate_user_stats_deduplicates_nodes` — Same NodeList across jobs is deduplicated
- `test_aggregate_user_stats_filters_pending_reasons` — `(Resources)`, `(Priority)` etc. are excluded from `node_names`
- `test_aggregate_user_stats_empty_nodelist` — Empty NodeList produces empty `node_names`
- `test_process_job_skips_parenthesized_reasons` — Direct test of reason filtering

**Unit tests** (`tests/unit/slurm/test_commands.py` or similar):
- `test_parse_fixed_width_squeue_line_wider_nodelist` — Verify parsing works with 80-char NodeList column
- `test_get_user_jobs_parses_wider_nodelist` — Verify user job parsing with wider column

**Unit tests** (`tests/unit/slurm/test_formatters.py` or similar):
- `test_format_user_info_includes_nodelist_in_summary` — NodeList appears in User Summary
- `test_format_user_info_includes_nodelist_per_job` — NodeList appears in Job List rows

**Integration tests** (`tests/integration/`):
- Verify Running Users table renders with NodeList column (mock squeue data)

## Acceptance Criteria

- [x] Running Users table shows a new "NodeList" column with compressed Slurm node names per user
- [x] User Info modal summary shows "NodeList" line below "Total Nodes"
- [x] User Info modal Job List table includes a "NodeList" column per job
- [x] Pending job reason strings like `(Resources)` are excluded from aggregated node names
- [x] NodeList squeue column width increased from 30 to 80 to reduce truncation
- [x] All fixed-width column constants updated consistently for both `get_all_running_jobs()` and `get_user_jobs()`
- [x] Existing tests still pass
- [x] New unit tests cover node name aggregation, deduplication, and reason filtering
- [ ] Test suite executes in under 20 seconds
- [x] `ruff format`, `ruff check`, and `ty check` pass

## References

### Internal References

- `stoei/widgets/user_overview.py:36-47` — `UserStats` dataclass (add `node_names`)
- `stoei/widgets/user_overview.py:49-57` — `_UserDataDict` TypedDict (add `node_names`)
- `stoei/widgets/user_overview.py:522-559` — `_process_job_for_user()` (collect NodeList)
- `stoei/widgets/user_overview.py:574-597` — `_convert_to_user_stats()` (format node_names)
- `stoei/widgets/user_overview.py:164-172` — `RUNNING_USERS_COLUMNS` (add column)
- `stoei/widgets/user_overview.py:384-397` — `update_users()` (add to row data)
- `stoei/slurm/commands.py:554-575` — Fixed-width column constants
- `stoei/slurm/commands.py:630-681` — `get_all_running_jobs()` format string
- `stoei/slurm/commands.py:715-811` — `get_user_jobs()` format string
- `stoei/slurm/formatters.py:607-794` — `format_user_info()` (add NodeList display)
- `stoei/app.py:1441-1458` — `_compute_user_overview_cache()` (pre-filters PENDING)
- `stoei/app.py:1927-2084` — `_show_user_info()` / `_show_user_info_for_row()`
