"""Cluster statistics data models and computation.

This is a dependency-free domain module: it depends only on ``stoei.slurm.*``
and the standard library. It must never import from ``stoei.widgets`` or
``stoei.app`` so the dependency direction stays one-way
(``slurm -> cluster_stats -> widgets/app``).
"""

from dataclasses import dataclass, field

from stoei.logger import get_logger
from stoei.slurm.array_parser import parse_array_size
from stoei.slurm.gpu_parser import (
    has_specific_gpu_types,
    parse_gpu_entries,
    parse_gpu_from_gres,
)
from stoei.slurm.parser import parse_tres_resources
from stoei.slurm.wait_time import PartitionWaitStats, calculate_partition_wait_stats

logger = get_logger(__name__)


@dataclass
class PendingPartitionStats:
    """Aggregated pending resources for a single partition."""

    jobs_count: int = 0
    cpus: int = 0
    memory_gb: float = 0.0
    gpus: int = 0
    gpus_by_type: dict[str, int] = field(default_factory=dict)


@dataclass
class ClusterStats:
    """Cluster statistics data."""

    total_nodes: int = 0
    free_nodes: int = 0
    allocated_nodes: int = 0
    total_cpus: int = 0
    allocated_cpus: int = 0
    total_memory_gb: float = 0.0
    allocated_memory_gb: float = 0.0
    total_gpus: int = 0
    allocated_gpus: int = 0
    gpus_by_type: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Draining nodes (excluded from totals, tracked separately)
    draining_nodes: int = 0
    # Pending job resources
    pending_jobs_count: int = 0
    pending_cpus: int = 0
    pending_memory_gb: float = 0.0
    pending_gpus: int = 0
    pending_gpus_by_type: dict[str, int] = field(default_factory=dict)
    pending_by_partition: dict[str, PendingPartitionStats] = field(default_factory=dict)
    # Wait time statistics per partition (from last N hours)
    wait_stats_by_partition: dict[str, PartitionWaitStats] = field(default_factory=dict)
    wait_stats_hours: int = 1  # Time window used for stats

    @property
    def free_nodes_pct(self) -> float:
        """Calculate percentage of free nodes."""
        if self.total_nodes == 0:
            return 0.0
        return (self.free_nodes / self.total_nodes) * 100.0

    @property
    def free_cpus_pct(self) -> float:
        """Calculate percentage of free CPUs."""
        if self.total_cpus == 0:
            return 0.0
        return ((self.total_cpus - self.allocated_cpus) / self.total_cpus) * 100.0

    @property
    def free_memory_pct(self) -> float:
        """Calculate percentage of free memory."""
        if self.total_memory_gb == 0:
            return 0.0
        return ((self.total_memory_gb - self.allocated_memory_gb) / self.total_memory_gb) * 100.0

    @property
    def free_gpus_pct(self) -> float:
        """Calculate percentage of free GPUs."""
        if self.total_gpus == 0:
            return 0.0
        return ((self.total_gpus - self.allocated_gpus) / self.total_gpus) * 100.0

    def get_gpu_type_free_pct(self, gpu_type: str) -> float:
        """Calculate percentage of free GPUs for a specific type.

        Args:
            gpu_type: The GPU type (e.g., 'h200', 'a100', 'gpu').

        Returns:
            Percentage of free GPUs for this type.
        """
        if gpu_type not in self.gpus_by_type:
            return 0.0
        total, allocated = self.gpus_by_type[gpu_type]
        if total == 0:
            return 0.0
        return ((total - allocated) / total) * 100.0


def parse_node_state(state: str, stats: ClusterStats) -> bool:
    """Parse node state and update node counts.

    Draining nodes are excluded from total_nodes but their allocated
    resources are still counted. This prevents draining nodes from
    inflating the denominator of utilization percentages.

    Args:
        state: Node state string (uppercase).
        stats: ClusterStats object to update.

    Returns:
        True if the node is draining (excluded from totals).
    """
    if "DRAIN" in state:
        stats.draining_nodes += 1
        if "ALLOCATED" in state or "MIXED" in state:
            stats.allocated_nodes += 1
        return True
    stats.total_nodes += 1
    if "IDLE" in state:
        stats.free_nodes += 1
    elif "ALLOCATED" in state or "MIXED" in state:
        stats.allocated_nodes += 1
    return False


def parse_node_cpus(node_data: dict[str, str], stats: ClusterStats, *, include_total: bool = True) -> None:
    """Parse CPU information from node data.

    Args:
        node_data: Node data dictionary.
        stats: ClusterStats object to update.
        include_total: Whether to include in total_cpus (False for draining nodes).
    """
    cpus_total_str = node_data.get("CPUTot", "0")
    cpus_alloc_str = node_data.get("CPUAlloc", "0")
    try:
        cpus_total = int(cpus_total_str)
        cpus_alloc = int(cpus_alloc_str)
        if include_total:
            stats.total_cpus += cpus_total
        stats.allocated_cpus += cpus_alloc
    except ValueError:
        pass


def parse_node_memory(node_data: dict[str, str], stats: ClusterStats, *, include_total: bool = True) -> None:
    """Parse memory information from node data.

    Args:
        node_data: Node data dictionary.
        stats: ClusterStats object to update.
        include_total: Whether to include in total_memory_gb (False for draining nodes).
    """
    mem_total_str = node_data.get("RealMemory", "0")
    mem_alloc_str = node_data.get("AllocMem", "0")
    try:
        mem_total_mb = int(mem_total_str)
        mem_alloc_mb = int(mem_alloc_str)
        if include_total:
            stats.total_memory_gb += mem_total_mb / 1024.0
        stats.allocated_memory_gb += mem_alloc_mb / 1024.0
    except ValueError:
        pass


def process_gpu_entries_for_stats(gpu_entries: list[tuple[str, int]], stats: ClusterStats, is_allocated: bool) -> None:
    """Process GPU entries and update cluster stats.

    Args:
        gpu_entries: List of (gpu_type, gpu_count) tuples.
        stats: ClusterStats object to update.
        is_allocated: Whether these are allocated GPUs.
    """
    has_specific = has_specific_gpu_types(gpu_entries)

    for gpu_type, gpu_count in gpu_entries:
        if has_specific and gpu_type.lower() == "gpu":
            continue
        current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
        if is_allocated:
            stats.gpus_by_type[gpu_type] = (current_total, current_alloc + gpu_count)
            stats.allocated_gpus += gpu_count
        else:
            stats.gpus_by_type[gpu_type] = (current_total + gpu_count, current_alloc)
            stats.total_gpus += gpu_count


def parse_gpus_from_gres(
    node_data: dict[str, str], state: str, stats: ClusterStats, *, include_total: bool = True
) -> None:
    """Parse GPUs from Gres field (fallback when TRES is not available).

    Args:
        node_data: Node data dictionary.
        state: Node state string (uppercase).
        stats: ClusterStats object to update.
        include_total: Whether to include in total_gpus (False for draining nodes).
    """
    gres = node_data.get("Gres", "")
    gpu_entries = parse_gpu_from_gres(gres)

    for gpu_type, gpu_count in gpu_entries:
        current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
        if include_total:
            stats.gpus_by_type[gpu_type] = (current_total + gpu_count, current_alloc)
            stats.total_gpus += gpu_count
        # Estimate allocated GPUs based on node state (skip for draining nodes)
        if include_total and ("ALLOCATED" in state or "MIXED" in state):
            current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
            stats.gpus_by_type[gpu_type] = (current_total, current_alloc + gpu_count)
            stats.allocated_gpus += gpu_count


def aggregate_pending_gpus(
    gpu_entries: list[tuple[str, int]],
    array_size: int,
    pending_gpus_by_type: dict[str, int],
    partition_stats: PendingPartitionStats,
) -> int:
    """Aggregate GPU counts from pending jobs.

    Args:
        gpu_entries: List of (gpu_type, gpu_count) tuples.
        array_size: Array size multiplier.
        pending_gpus_by_type: Dict to update with GPU counts by type.
        partition_stats: Partition stats to update.

    Returns:
        Total pending GPUs from these entries.
    """
    total_gpus = 0
    for gpu_type, gpu_count in gpu_entries:
        scaled_gpu_count = gpu_count * array_size
        total_gpus += scaled_gpu_count
        partition_stats.gpus += scaled_gpu_count
        pending_gpus_by_type[gpu_type] = pending_gpus_by_type.get(gpu_type, 0) + scaled_gpu_count
        partition_stats.gpus_by_type[gpu_type] = partition_stats.gpus_by_type.get(gpu_type, 0) + scaled_gpu_count
    return total_gpus


def calculate_pending_resources(all_users_jobs: list[tuple[str, ...]], stats: ClusterStats) -> None:
    """Calculate resources requested by pending jobs.

    Array jobs (e.g., 12345_[0-99]) are expanded so that resources are
    multiplied by the number of tasks in the array.

    Args:
        all_users_jobs: All users' job tuples to scan for pending jobs.
        stats: ClusterStats object to update with pending resource data.
    """
    # Job tuple indices
    job_id_index, partition_index, state_index, tres_index = 0, 3, 4, 8
    min_fields_for_tres = 9

    pending_cpus, pending_memory_gb, pending_gpus, pending_jobs_count = 0, 0.0, 0, 0
    pending_gpus_by_type: dict[str, int] = {}
    pending_by_partition: dict[str, PendingPartitionStats] = {}

    for job in all_users_jobs:
        if len(job) <= state_index or job[state_index].strip().upper() not in ("PENDING", "PD"):
            continue

        job_id = job[job_id_index].strip() if len(job) > job_id_index else ""
        array_size = parse_array_size(job_id)
        pending_jobs_count += array_size

        partition_key = (job[partition_index].strip() if len(job) > partition_index else "") or "unknown"
        partition_stats = pending_by_partition.setdefault(partition_key, PendingPartitionStats())
        partition_stats.jobs_count += array_size

        if len(job) < min_fields_for_tres or not job[tres_index]:
            continue

        cpus, memory_gb, gpu_entries = parse_tres_resources(job[tres_index])
        pending_cpus += cpus * array_size
        pending_memory_gb += memory_gb * array_size
        partition_stats.cpus += cpus * array_size
        partition_stats.memory_gb += memory_gb * array_size

        pending_gpus += aggregate_pending_gpus(gpu_entries, array_size, pending_gpus_by_type, partition_stats)

    stats.pending_jobs_count = pending_jobs_count
    stats.pending_cpus = pending_cpus
    stats.pending_memory_gb = pending_memory_gb
    stats.pending_gpus = pending_gpus
    stats.pending_gpus_by_type = pending_gpus_by_type
    stats.pending_by_partition = pending_by_partition

    logger.debug(
        f"Pending resources: {pending_jobs_count} jobs, {pending_cpus} CPUs, "
        f"{pending_memory_gb:.1f} GB memory, {pending_gpus} GPUs"
    )


def calculate_cluster_stats(
    cluster_nodes: list[dict[str, str]],
    all_users_jobs: list[tuple[str, ...]],
    wait_time_jobs: list[tuple[str, ...]],
) -> ClusterStats:
    """Calculate cluster statistics from node data.

    Args:
        cluster_nodes: Node data dictionaries describing cluster nodes.
        all_users_jobs: All users' job tuples (used for pending resources).
        wait_time_jobs: Recent jobs used for wait time statistics.

    Returns:
        ClusterStats object with aggregated statistics.
    """
    stats = ClusterStats()

    if not cluster_nodes:
        logger.debug("No cluster nodes available for stats calculation")
        # Still calculate pending resources even if no cluster nodes
        calculate_pending_resources(all_users_jobs, stats)
        return stats

    for node_data in cluster_nodes:
        # Parse node information
        state = node_data.get("State", "").upper()

        # Count nodes (draining nodes excluded from totals)
        is_draining = parse_node_state(state, stats)

        # Parse CPUs (draining nodes: allocated only, no totals)
        parse_node_cpus(node_data, stats, include_total=not is_draining)

        # Parse memory (draining nodes: allocated only, no totals)
        parse_node_memory(node_data, stats, include_total=not is_draining)

        # Parse GPUs by type from CfgTRES and AllocTRES
        cfg_tres = node_data.get("CfgTRES", "")
        alloc_tres = node_data.get("AllocTRES", "")

        # Parse CfgTRES for total GPUs by type (skip for draining nodes)
        # Note: If both generic (gres/gpu=8) and specific (gres/gpu:h200=8) exist,
        # they represent the same GPUs, so we only count specific types to avoid double-counting
        if not is_draining:
            gpu_entries = parse_gpu_entries(cfg_tres)
            process_gpu_entries_for_stats(gpu_entries, stats, is_allocated=False)

        # Parse AllocTRES for allocated GPUs by type (skip for draining nodes)
        if not is_draining:
            alloc_entries = parse_gpu_entries(alloc_tres)
            process_gpu_entries_for_stats(alloc_entries, stats, is_allocated=True)

        # Fallback: if no TRES data, try parsing Gres field
        if not cfg_tres and not alloc_tres:
            parse_gpus_from_gres(node_data, state, stats, include_total=not is_draining)

    # Calculate pending job resources
    calculate_pending_resources(all_users_jobs, stats)

    # Calculate wait time statistics
    if wait_time_jobs:
        stats.wait_stats_by_partition = calculate_partition_wait_stats(wait_time_jobs)
        stats.wait_stats_hours = 1  # Currently hardcoded to 1 hour
        logger.debug(f"Calculated wait stats for {len(stats.wait_stats_by_partition)} partitions")

    return stats
