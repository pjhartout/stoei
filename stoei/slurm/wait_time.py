"""Wait time calculation utilities for SLURM jobs."""

from dataclasses import dataclass
from datetime import datetime
from statistics import mean, median

from stoei.logger import get_logger

logger = get_logger(__name__)

# SLURM timestamp format
SLURM_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Values that indicate unknown/missing timestamps
UNKNOWN_TIMESTAMP_VALUES = frozenset({"Unknown", "None", "N/A", ""})

# Time unit constants for formatting
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
THRESHOLD_FOR_INTEGER_DISPLAY = 10


@dataclass
class PartitionWaitStats:
    """Wait time statistics for a partition."""

    partition: str
    job_count: int
    mean_seconds: float
    median_seconds: float
    min_seconds: float
    max_seconds: float


def parse_slurm_timestamp(timestamp_str: str) -> datetime | None:
    """Parse SLURM timestamp (YYYY-MM-DDTHH:MM:SS) to datetime.

    Args:
        timestamp_str: The timestamp string to parse.

    Returns:
        Parsed datetime or None if invalid/unknown.
    """
    if not timestamp_str or timestamp_str.strip() in UNKNOWN_TIMESTAMP_VALUES:
        return None

    try:
        return datetime.strptime(timestamp_str.strip(), SLURM_TIMESTAMP_FORMAT)
    except ValueError:
        logger.debug(f"Failed to parse SLURM timestamp: {timestamp_str}")
        return None


def calculate_wait_time_seconds(submit_time: str, start_time: str) -> float | None:
    """Calculate wait time in seconds between submit and start times.

    Args:
        submit_time: Job submit timestamp string.
        start_time: Job start timestamp string.

    Returns:
        Wait time in seconds, or None if either timestamp is invalid.
    """
    submit_dt = parse_slurm_timestamp(submit_time)
    start_dt = parse_slurm_timestamp(start_time)

    if submit_dt is None or start_dt is None:
        return None

    # Calculate difference in seconds
    delta = start_dt - submit_dt
    wait_seconds = delta.total_seconds()

    # Negative wait time indicates data issue (start before submit)
    if wait_seconds < 0:
        logger.debug(f"Negative wait time detected: submit={submit_time}, start={start_time}")
        return None

    return wait_seconds


def format_wait_time(seconds: float) -> str:
    """Format seconds into compact human-readable string.

    Args:
        seconds: Time in seconds.

    Returns:
        Compact string (e.g., '5m', '2h', '1d').
    """
    if seconds < 0:
        return "0s"

    # Less than 60 seconds: show seconds
    if seconds < SECONDS_PER_MINUTE:
        return f"{int(seconds)}s"

    # Less than 60 minutes: show minutes
    minutes = seconds / SECONDS_PER_MINUTE
    if minutes < MINUTES_PER_HOUR:
        return f"{int(minutes)}m"

    # Less than 24 hours: show hours
    hours = minutes / MINUTES_PER_HOUR
    if hours < HOURS_PER_DAY:
        return f"{hours:.1f}h" if hours < THRESHOLD_FOR_INTEGER_DISPLAY else f"{int(hours)}h"

    # Show days
    days = hours / HOURS_PER_DAY
    return f"{days:.1f}d" if days < THRESHOLD_FOR_INTEGER_DISPLAY else f"{int(days)}d"


def calculate_partition_wait_stats(jobs: list[tuple[str, ...]]) -> dict[str, PartitionWaitStats]:
    """Calculate wait time statistics per partition from job data.

    Args:
        jobs: List of job tuples (JobID, Partition, State, Submit, Start).

    Returns:
        Dict mapping partition name to PartitionWaitStats.
    """
    # Group wait times by partition
    partition_wait_times: dict[str, list[float]] = {}

    # Expected field indices
    partition_idx = 1
    submit_idx = 3
    start_idx = 4
    min_fields = 5

    for job in jobs:
        if len(job) < min_fields:
            continue

        partition = job[partition_idx].strip() if job[partition_idx] else "unknown"
        submit_time = job[submit_idx].strip() if job[submit_idx] else ""
        start_time = job[start_idx].strip() if job[start_idx] else ""

        wait_seconds = calculate_wait_time_seconds(submit_time, start_time)
        if wait_seconds is not None:
            if partition not in partition_wait_times:
                partition_wait_times[partition] = []
            partition_wait_times[partition].append(wait_seconds)

    # Calculate statistics for each partition
    result: dict[str, PartitionWaitStats] = {}

    for partition, wait_times in partition_wait_times.items():
        if not wait_times:
            continue

        result[partition] = PartitionWaitStats(
            partition=partition,
            job_count=len(wait_times),
            mean_seconds=mean(wait_times),
            median_seconds=median(wait_times),
            min_seconds=min(wait_times),
            max_seconds=max(wait_times),
        )

    logger.debug(f"Calculated wait stats for {len(result)} partitions from {len(jobs)} jobs")
    return result
