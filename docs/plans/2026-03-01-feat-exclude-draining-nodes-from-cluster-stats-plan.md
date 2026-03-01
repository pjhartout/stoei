---
title: "feat: Exclude draining nodes from cluster stats denominator"
type: feat
date: 2026-03-01
---

# feat: Exclude draining nodes from cluster stats denominator

## Problem Statement

Cluster stats currently count **all** nodes in the denominator (totals), including nodes in DRAIN/DRAINING/DRAINED states. These nodes are not accepting new jobs, so including them inflates the apparent total capacity and makes utilization percentages misleadingly low.

Additionally, `_parse_node_state` (`stoei/app.py:1239`) has a subtle bug: a node with state `IDLE+DRAIN` matches `"IDLE" in state` and gets counted as "free," even though it won't accept new jobs.

Finally, the node overview table shows the `State` column but not the `Reason` field, even though `NodeInfo` already stores the SLURM `Reason`. Users can't see **why** a node is draining.

## Proposed Solution

Two changes:

1. **Cluster stats**: Exclude draining nodes from the denominator. Count them as allocated in the numerator so they show as "in use." Track draining node count separately so the sidebar can display it.

2. **Node overview**: Add a `Reason` column to the node table so users can see why any node is in a non-normal state (draining, down, etc.).

### SLURM State Background

SLURM node states containing "DRAIN":
- `IDLE+DRAIN` / `DRAINED` -- fully drained, no jobs running
- `MIXED+DRAIN` / `ALLOCATED+DRAIN` -- still running jobs, draining in progress

All should be excluded from the denominator. Those still running jobs (`MIXED+DRAIN`, `ALLOCATED+DRAIN`) should have their allocated resources counted.

## Changes

### 1. `stoei/widgets/cluster_sidebar.py` -- Add draining count to `ClusterStats`

Add a field to track draining nodes separately:

```python
draining_nodes: int = 0
```

### 2. `stoei/app.py:1231` -- Update `_parse_node_state`

Check for DRAIN **before** IDLE/ALLOCATED/MIXED. Draining nodes increment `draining_nodes` but NOT `total_nodes`. Draining nodes that are still allocated count in `allocated_nodes`:

```python
def _parse_node_state(self, state: str, stats: ClusterStats) -> bool:
    """Parse node state and update node counts.

    Returns:
        True if the node is draining (excluded from totals).
    """
    if "DRAIN" in state:
        stats.draining_nodes += 1
        # Still count allocated draining nodes in allocated_nodes
        if "ALLOCATED" in state or "MIXED" in state:
            stats.allocated_nodes += 1
        return True
    stats.total_nodes += 1
    if "IDLE" in state:
        stats.free_nodes += 1
    elif "ALLOCATED" in state or "MIXED" in state:
        stats.allocated_nodes += 1
    return False
```

### 3. `stoei/app.py:1402` -- Update `_calculate_cluster_stats` loop

Use the return value to skip draining nodes from CPU/memory/GPU totals but still count their allocated resources:

```python
for node_data in self._cluster_nodes:
    state = node_data.get("State", "").upper()
    is_draining = self._parse_node_state(state, stats)

    if is_draining:
        # Only count allocated resources, skip totals
        self._parse_node_cpus_allocated_only(node_data, stats)
        self._parse_node_memory_allocated_only(node_data, stats)
        # GPU allocated parsing (similar approach)
        ...
        continue

    # Existing logic for non-draining nodes (counts both totals and allocated)
    self._parse_node_cpus(node_data, stats)
    self._parse_node_memory(node_data, stats)
    ...
```

Add helper methods `_parse_node_cpus_allocated_only` and `_parse_node_memory_allocated_only` that add to `allocated_cpus`/`allocated_memory_gb` but NOT `total_cpus`/`total_memory_gb`. Same pattern for GPUs.

### 4. `stoei/widgets/cluster_sidebar.py:280` -- Update sidebar display

Add a draining indicator to the Nodes section when draining nodes exist:

```
Cluster Load

Nodes:
  Free: 45.0%
  45/100 available
  (5 draining)
```

Use `bright_black` (dim) styling for the draining line, consistent with other secondary info.

### 5. `stoei/widgets/node_overview.py:63` -- Add Reason column to node table

Add a `Reason` column to `NODE_TABLE_COLUMN_CONFIGS`:

```python
ColumnConfig(name="Reason", key="reason", sortable=True, filterable=True),
```

And include `node.reason` in the row data (around line 154). Display `""` or `"N/A"` when no reason is set.

### 6. Tests

#### Unit tests -- `tests/unit/widgets/test_cluster_sidebar.py`

- `ClusterStats` with `draining_nodes` field set
- `_render_stats` shows "(N draining)" when `draining_nodes > 0`
- `_render_stats` hides draining line when `draining_nodes == 0`
- Percentages exclude draining from denominator

#### Unit tests -- `tests/unit/test_app.py`

- `_parse_node_state` returns `True` for DRAIN states, `False` otherwise
- `_parse_node_state` does NOT count `IDLE+DRAIN` as free
- `_parse_node_state` counts `ALLOCATED+DRAIN` as allocated but not in total_nodes
- `_calculate_cluster_stats` excludes draining from totals, includes allocated

#### Unit tests -- `tests/unit/widgets/test_node_overview.py`

- Reason column appears in the table
- Reason text is displayed for draining nodes

#### Integration tests -- `tests/integration/test_cluster_overview.py`

- Mixed cluster with normal + draining nodes: verify sidebar shows correct percentages and draining indicator

## Acceptance Criteria

- [x] Draining nodes are excluded from all denominators (total_nodes, total_cpus, total_memory_gb, total_gpus)
- [x] Allocated resources on draining nodes still count in numerators (allocated_cpus, etc.)
- [x] `IDLE+DRAIN` is no longer counted as a "free" node
- [x] Sidebar shows "(N draining)" when draining nodes exist, hidden otherwise
- [x] Node overview table has a Reason column showing SLURM's Reason field
- [x] All percentage calculations remain valid (0-100%)
- [x] Existing tests pass, new tests cover draining logic
- [x] `ruff`, `ty`, and `pytest` all pass

## References

- `stoei/app.py:1231` -- `_parse_node_state` (node state logic)
- `stoei/app.py:1245` -- `_parse_node_cpus` (CPU parsing)
- `stoei/app.py:1262` -- `_parse_node_memory` (memory parsing)
- `stoei/app.py:1402` -- `_calculate_cluster_stats` (main loop)
- `stoei/widgets/cluster_sidebar.py:43` -- `ClusterStats` dataclass
- `stoei/widgets/cluster_sidebar.py:280` -- `_render_stats` (sidebar display)
- `stoei/widgets/node_overview.py:16` -- `NodeInfo` (already has `reason` field)
- `stoei/widgets/node_overview.py:63` -- `NODE_TABLE_COLUMN_CONFIGS` (missing Reason column)
- `stoei/colors.py:103` -- DRAIN/DRAINED already have error color mapping
