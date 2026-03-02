---
title: "fix: Display unique node count instead of summed node-slots"
type: fix
date: 2026-03-02
---

# fix: Display unique node count instead of summed node-slots

## Problem Statement

The "Nodes" column in the User Overview (and the "Total Nodes" label in the user/account info screens) displays the **sum of `NumNodes` per job**, not the count of unique physical nodes. For users running many single-node jobs — the common case — this value equals the job count, not the node count.

### Root Cause (confirmed)

In `stoei/widgets/user_overview.py`, `_process_job_for_user()` (line ~550):

```python
# Current (buggy): adds the raw NodeList string as one opaque set element
if nodelist_str and not nodelist_str.startswith("("):
    user_data["node_names"].add(nodelist_str)
```

A job with `NodeList = "node[01-04]"` adds the string `"node[01-04]"` — one element — rather than the four individual hostnames. Additionally, `UserStats.total_nodes` (line ~604) is derived from a separate numeric accumulator (`sum(NumNodes per job)`), not from `len(node_names)`.

The same bug exists in `stoei/slurm/formatters.py` in `format_account_info()` (line ~932), which independently accumulates `total_nodes` by summing `_parse_node_count(nodes_str)` per job.

### Example

A user has 3 jobs all on `node01`:
- **Current output:** `Nodes = 3` (sum of NumNodes, equals job count)
- **Correct output:** `Nodes = 1` (one unique physical node)

## Proposed Fix

1. **Introduce `expand_nodelist(s: str) -> set[str]`** in a new `stoei/slurm/nodelist.py`. This function expands Slurm bracket notation to individual hostnames without adding a new dependency:
   - `"node01"` → `{"node01"}`
   - `"node[01-04]"` → `{"node01", "node02", "node03", "node04"}`
   - `"node01,node[03-05]"` → `{"node01", "node03", "node04", "node05"}`
   - `"gpu[01-02],cpu[01-02]"` → `{"gpu01", "gpu02", "cpu01", "cpu02"}`
   - `"(None)"` / `"(Resources)"` / `""` → `set()`
   - Truncated/malformed input → return partial result and log a warning

2. **Update `_process_job_for_user()`** (`user_overview.py`): replace `.add(nodelist_str)` with `user_data["node_names"].update(expand_nodelist(nodelist_str))`.

3. **Update `_convert_to_user_stats()`** (`user_overview.py`): change `total_nodes=int(data["total_nodes"])` to `total_nodes=len(data["node_names"])`. Remove (or rename to `node_slots`) the now-unused `"total_nodes"` numeric accumulator in `_UserDataDict`.

4. **Apply the same fix to `format_account_info()`** (`formatters.py`): replace the per-job `NumNodes` sum with NodeList expansion.

5. **Update UI labels**: `"Total Nodes"` → `"Unique Nodes"` in `format_user_info()` (formatters.py:690) and `format_account_info()` (formatters.py:940). The table column `"Nodes"` in the user overview stays as is (it's already ambiguous; the label change in the info panel is sufficient).

**PENDING jobs:** Their `NodeList` is always `"(None)"` / `"(Resources)"` etc., so `expand_nodelist` returns `set()` for them — they contribute zero to the unique-node count. This is the correct semantic: show nodes *currently allocated*, not nodes *requested*.

## Acceptance Criteria

- [ ] A user with N running jobs all on the same node sees `Nodes = 1`, not `N`
- [ ] A user with jobs on overlapping node ranges sees the correct deduplicated count
- [ ] PENDING-only users see `Nodes = 0`
- [ ] NodeList strings with bracket notation are correctly expanded to individual hostnames
- [ ] Truncated NodeList strings (>80 chars, cut mid-bracket) log a warning and return what can be parsed
- [ ] UI labels updated: "Total Nodes" → "Unique Nodes" in user and account info panels
- [ ] `format_account_info()` shows the same unique-node count as the user overview
- [ ] All existing tests pass; new tests cover the scenarios below
- [ ] `uv run ruff check .`, `uv run ty check stoei/`, `uv run pytest` all pass

## Files to Change

| File | Change |
|---|---|
| `stoei/slurm/nodelist.py` | **New file** — `expand_nodelist(s: str) -> set[str]` |
| `stoei/widgets/user_overview.py` | `_process_job_for_user()` + `_convert_to_user_stats()` + `_UserDataDict` |
| `stoei/slurm/formatters.py` | `format_account_info()` node accumulation + label change |
| `stoei/slurm/formatters.py` | `format_user_info()` label change |
| `tests/unit/slurm/test_nodelist.py` | **New file** — unit tests for `expand_nodelist` |
| `tests/unit/widgets/test_user_overview.py` | Update assertions for `total_nodes`; add shared-node dedup tests |

## Test Scenarios

### `test_nodelist.py` — `expand_nodelist` unit tests

| Input | Expected |
|---|---|
| `"node01"` | `{"node01"}` |
| `"node[01-04]"` | `{"node01", "node02", "node03", "node04"}` |
| `"node[01,03,05]"` | `{"node01", "node03", "node05"}` |
| `"node[01-03,07]"` | `{"node01", "node02", "node03", "node07"}` |
| `"node01,node[03-05]"` | `{"node01", "node03", "node04", "node05"}` |
| `"gpu[01-02],cpu[01-02]"` | `{"gpu01", "gpu02", "cpu01", "cpu02"}` |
| `"node[001-003]"` | `{"node001", "node002", "node003"}` |
| `""` | `set()` |
| `"(None)"` | `set()` |
| `"(Resources)"` | `set()` |
| Truncated `"node[01-"` | `set()` + warning logged |

### `test_user_overview.py` — updated/new aggregation tests

| Scenario | Expected `total_nodes` |
|---|---|
| 3 jobs all on `node01` | `1` |
| 2 jobs on `node[01-02]`, 1 job on `node[01-02]` | `2` (deduplicated) |
| Jobs on non-overlapping ranges | correct sum of unique nodes |
| Pending job `(None)` only | `0` |
| Mix of running (`node01`) + pending (`(None)`) | `1` |
| Multi-node job `node[01-04]` | `4` |

## References

- `stoei/widgets/user_overview.py:526-569` — `_process_job_for_user()`
- `stoei/widgets/user_overview.py:583-609` — `_convert_to_user_stats()`
- `stoei/widgets/user_overview.py:612-660` — `aggregate_user_stats()`
- `stoei/slurm/formatters.py:912-940` — `format_account_info()` node accumulation
- `stoei/slurm/formatters.py:690` — `format_user_info()` "Total Nodes" label
- `stoei/slurm/commands.py:733` — squeue format string with `NodeList:80`
