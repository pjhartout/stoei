---
title: "feat: Show running job and array counts in My Usage banner"
type: feat
date: 2026-03-02
---

# feat: Show running job and array counts in My Usage banner

## Problem Statement

The "My Usage" banner shows resource consumption (CPUs, RAM, GPUs, Nodes) but gives no indication of **how many jobs are running** or **how many are job arrays**. A user with 100 running tasks from a single array cannot tell this from the current display.

**Current banner:**
```
My Usage: 48 CPUs | 192.0 GB | 4 GPUs (4x H100) | 3 Nodes
```

**Desired banner:**
```
My Usage: 48 CPUs | 192.0 GB | 4 GPUs (4x H100) | 3 Nodes | 100 tasks (1 array, 0 jobs)
```

## Proposed Solution

Add a job-count segment to the banner using data already available in `UserStats`. Classify each running job at aggregation time by inspecting the JobID field:

- `"47441"` — no `_` → plain regular job (counts toward `plain_job_count`)
- `"47474_5"` — `_` present, no `[` → running array task (base ID `"47474"` added to `array_base_ids`)
- `"47700_[0-49]"` — contains `_[` → pending array (ignored in running aggregation)

## Technical Approach

### New fields on `UserStats` (`stoei/widgets/user_overview.py:38`)

```python
array_count: int = 0        # distinct running arrays (unique base job IDs)
plain_job_count: int = 0    # non-array running jobs
```

`job_count` keeps its current meaning (total running task rows).

### New accumulator keys in `_UserDataDict` (`user_overview.py:51`)

```python
array_base_ids: set[str]    # replace total_nodes analogy: a set, not int
plain_job_count: int
```

### Update `_process_job_for_user()` (`user_overview.py:525`)

Classify `job[0]` (the JobID field):

```python
# stoei/widgets/user_overview.py (inside _process_job_for_user)
job_id = job[0].strip()
if "_[" in job_id:
    pass  # pending array leaking in — ignore for running counts
elif "_" in job_id:
    user_data["array_base_ids"].add(job_id.split("_")[0])
else:
    user_data["plain_job_count"] += 1
```

### Update `_convert_to_user_stats()` (`user_overview.py:583`)

```python
array_count=len(data["array_base_ids"]),
plain_job_count=data["plain_job_count"],
```

### Update `_update_my_usage_summary()` (`app.py:1707`)

Append a new segment after Nodes. Use singular/plural:

```python
# stoei/app.py (inside _update_my_usage_summary)
x = my_stats.job_count
y = my_stats.array_count
z = my_stats.plain_job_count
task_word = "task" if x == 1 else "tasks"
array_word = "array" if y == 1 else "arrays"
job_word = "job" if z == 1 else "jobs"
parts.append(f"{x} {task_word} ({y} {array_word}, {z} {job_word})")
```

## Acceptance Criteria

- [ ] A user with N tasks in a single array sees `N tasks (1 array, 0 jobs)`
- [ ] A user with tasks spread across 2 arrays and 3 regular jobs sees `X tasks (2 arrays, 3 jobs)`
- [ ] A user with only regular jobs sees `N tasks (0 arrays, N jobs)`
- [ ] Singular forms used correctly: `1 task`, `1 array`, `1 job`
- [ ] Pending-only user: banner falls through to `"My Usage: No running jobs"` — unchanged
- [ ] `job_count` semantics unchanged (existing Users tab column unaffected)
- [ ] `_update_my_usage_summary()` test verifies banner string includes the new segment
- [ ] `uv run ruff check .`, `uv run ty check stoei/`, `uv run pytest` all pass

## Files to Change

| File | Change |
|---|---|
| `stoei/widgets/user_overview.py` | `UserStats` (2 new fields), `_UserDataDict` (2 new keys), `_process_job_for_user()` (classify job ID), `_convert_to_user_stats()` (populate new fields), `_default_user_data()` (init new keys) |
| `stoei/app.py` | `_update_my_usage_summary()` — append task-count segment to `parts` |
| `tests/unit/widgets/test_user_overview.py` | New tests for aggregation with array/regular/mixed jobs |
| `tests/unit/test_app.py` | New test for `_update_my_usage_summary` banner string with array counts |

## Test Scenarios

### `test_user_overview.py` — aggregation classification

| Scenario | Jobs | Expected `array_count` | Expected `plain_job_count` |
|---|---|---|---|
| All plain jobs | `"47441"`, `"47442"`, `"47443"` | `0` | `3` |
| 5 tasks from 1 array | `"12345_0"` … `"12345_4"` | `1` | `0` |
| Tasks from 2 distinct arrays | `"12345_0"`, `"12345_1"`, `"99999_0"` | `2` | `0` |
| Mixed | `"12345_0"`, `"99999_0"`, `"47441"`, `"47442"`, `"47443"` | `2` | `3` |
| Single array task | `"12345_0"` | `1` | `0` |
| Pending array leaking in | `"12345_[0-49]"` | `0` | `0` |
| Empty job ID | `""` | `0` | `1` (no `_`, treated as plain) |

### `test_app.py` — banner string

| Scenario | `array_count` | `plain_job_count` | `job_count` | Expected segment |
|---|---|---|---|---|
| Mixed | `2` | `3` | `15` | `"15 tasks (2 arrays, 3 jobs)"` |
| All array | `1` | `0` | `10` | `"10 tasks (1 array, 0 jobs)"` |
| Singular | `1` | `1` | `2` | `"2 tasks (1 array, 1 job)"` |
| Single task | `0` | `1` | `1` | `"1 task (0 arrays, 1 job)"` |

## References

- `stoei/widgets/user_overview.py:38` — `UserStats` dataclass
- `stoei/widgets/user_overview.py:51` — `_UserDataDict`
- `stoei/widgets/user_overview.py:525` — `_process_job_for_user()`
- `stoei/widgets/user_overview.py:583` — `_convert_to_user_stats()`
- `stoei/widgets/user_overview.py:610` — `aggregate_user_stats()`
- `stoei/app.py:1707` — `_update_my_usage_summary()`
- `stoei/app.py:256` — `my-usage-summary` Static widget
- `stoei/slurm/array_parser.py` — existing `normalize_array_job_id()`, `parse_array_size()`
