"""Job data caching for improved performance.

Caches SLURM job data to reduce subprocess calls and improve TUI responsiveness.
"""

from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import ClassVar

from stoei.logger import get_logger
from stoei.slurm.commands import get_job_history, get_running_jobs

logger = get_logger(__name__)

# Tuple field indices for squeue output
_SQUEUE_JOB_ID = 0
_SQUEUE_NAME = 1
_SQUEUE_STATE = 2
_SQUEUE_TIME = 3
_SQUEUE_NODES = 4
_SQUEUE_NODELIST = 5
_SQUEUE_MIN_FIELDS = 6

# Tuple field indices for sacct output
_SACCT_JOB_ID = 0
_SACCT_NAME = 1
_SACCT_STATE = 2
_SACCT_RESTARTS = 3
_SACCT_ELAPSED = 4
_SACCT_EXIT_CODE = 5
_SACCT_NODELIST = 6
_SACCT_MIN_FIELDS = 7


class JobState(Enum):
    """Job state categories for display."""

    RUNNING = "RUNNING"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    OTHER = "OTHER"


@dataclass
class Job:
    """Unified job representation combining squeue and sacct data."""

    job_id: str
    name: str
    state: str
    time: str  # Elapsed or running time
    nodes: str
    node_list: str
    restarts: int = 0
    exit_code: str = ""
    is_active: bool = False  # True for running/pending jobs

    @property
    def state_category(self) -> JobState:
        """Categorize the job state."""
        state_upper = self.state.upper()

        # Check keywords in priority order
        state_keywords = [
            ("RUNNING", JobState.RUNNING),
            ("PENDING", JobState.PENDING),
            ("COMPLETED", JobState.COMPLETED),
            ("FAILED", JobState.FAILED),
            ("NODE_FAIL", JobState.FAILED),
            ("CANCELLED", JobState.CANCELLED),
            ("TIMEOUT", JobState.TIMEOUT),
        ]

        for keyword, category in state_keywords:
            if keyword in state_upper:
                return category
        return JobState.OTHER

    def as_row(self) -> tuple[str, str, str, str, str, str]:
        """Convert to table row format.

        Returns:
            Tuple of (JobID, Name, State, Time, Nodes, NodeList).
        """
        return (
            self.job_id,
            self.name,
            self.state,
            self.time,
            self.nodes,
            self.node_list,
        )


class JobCache:
    """Thread-safe cache for SLURM job data.

    Provides unified access to both running and historical jobs with
    caching to reduce subprocess calls.
    """

    _instance: ClassVar["JobCache | None"] = None
    _lock: ClassVar[Lock] = Lock()

    def __new__(cls) -> "JobCache":
        """Singleton pattern for global cache access."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize the job cache."""
        if self._initialized:
            return
        self._initialized = True
        self._data_lock = Lock()
        self._jobs: list[Job] = []
        self._total_jobs: int = 0
        self._total_requeues: int = 0
        self._max_requeues: int = 0
        self._running_count: int = 0
        self._pending_count: int = 0

    def refresh(self) -> None:
        """Refresh cache from SLURM commands.

        Fetches both running jobs (squeue) and history (sacct),
        merging them into a unified list with active jobs first.
        """
        logger.debug("Refreshing job cache")

        # Fetch data (may be slow - runs subprocess calls)
        running_jobs, r_error = get_running_jobs()
        if r_error:
            logger.warning(f"Failed to refresh running jobs in cache: {r_error}")
            running_jobs = []

        history_jobs, total_jobs, total_requeues, max_requeues, h_error = get_job_history()
        if h_error:
            logger.warning(f"Failed to refresh job history in cache: {h_error}")
            history_jobs, total_jobs, total_requeues, max_requeues = [], 0, 0, 0

        # Build from fetched data
        self._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)

    def _build_from_data(
        self,
        running_jobs: list[tuple[str, ...]],
        history_jobs: list[tuple[str, ...]],
        total_jobs: int,
        total_requeues: int,
        max_requeues: int,
    ) -> None:
        """Build job cache from pre-fetched data.

        This method is useful when data has already been fetched (e.g., during
        step-by-step loading) to avoid duplicate SLURM command calls.

        Args:
            running_jobs: List of running/pending job tuples from squeue.
            history_jobs: List of historical job tuples from sacct.
            total_jobs: Total number of jobs in history.
            total_requeues: Total number of job requeues.
            max_requeues: Maximum requeues for any single job.
        """
        # Build job list
        jobs: list[Job] = []
        running_job_ids: set[str] = set()

        # Process running/pending jobs first
        running_count = 0
        pending_count = 0
        for job_tuple in running_jobs:
            if len(job_tuple) < _SQUEUE_MIN_FIELDS:
                continue

            job_id = job_tuple[_SQUEUE_JOB_ID].strip()
            running_job_ids.add(job_id)

            job = Job(
                job_id=job_id,
                name=job_tuple[_SQUEUE_NAME].strip(),
                state=job_tuple[_SQUEUE_STATE].strip(),
                time=job_tuple[_SQUEUE_TIME].strip(),
                nodes=job_tuple[_SQUEUE_NODES].strip(),
                node_list=job_tuple[_SQUEUE_NODELIST].strip(),
                is_active=True,
            )
            jobs.append(job)

            if job.state_category == JobState.RUNNING:
                running_count += 1
            elif job.state_category == JobState.PENDING:
                pending_count += 1

        # Process history jobs (excluding duplicates from running)
        for job_tuple in history_jobs:
            if len(job_tuple) < _SACCT_MIN_FIELDS:
                continue

            job_id = job_tuple[_SACCT_JOB_ID].strip()
            if job_id in running_job_ids:
                continue  # Skip duplicates

            restarts_str = job_tuple[_SACCT_RESTARTS].strip()
            job = Job(
                job_id=job_id,
                name=job_tuple[_SACCT_NAME].strip(),
                state=job_tuple[_SACCT_STATE].strip(),
                time=job_tuple[_SACCT_ELAPSED].strip(),
                nodes="",  # Not available in sacct output format
                node_list=job_tuple[_SACCT_NODELIST].strip(),
                restarts=int(restarts_str) if restarts_str.isdigit() else 0,
                exit_code=job_tuple[_SACCT_EXIT_CODE].strip(),
                is_active=False,
            )
            jobs.append(job)

        # Update cache atomically
        with self._data_lock:
            self._jobs = jobs
            self._total_jobs = total_jobs
            self._total_requeues = total_requeues
            self._max_requeues = max_requeues
            self._running_count = running_count
            self._pending_count = pending_count

        logger.debug(f"Cache built: {len(jobs)} jobs ({running_count} running, {pending_count} pending)")

    @property
    def jobs(self) -> list[Job]:
        """Get cached jobs (thread-safe copy)."""
        with self._data_lock:
            return list(self._jobs)

    @property
    def running_count(self) -> int:
        """Get count of running jobs."""
        with self._data_lock:
            return self._running_count

    @property
    def pending_count(self) -> int:
        """Get count of pending jobs."""
        with self._data_lock:
            return self._pending_count

    @property
    def active_count(self) -> int:
        """Get count of running + pending jobs."""
        with self._data_lock:
            return self._running_count + self._pending_count

    @property
    def stats(self) -> tuple[int, int, int, int, int]:
        """Get all stats at once (thread-safe).

        Returns:
            Tuple of (total_jobs, total_requeues, max_requeues, running_count, pending_count).
        """
        with self._data_lock:
            return (
                self._total_jobs,
                self._total_requeues,
                self._max_requeues,
                self._running_count,
                self._pending_count,
            )

    def get_active_jobs(self) -> list[Job]:
        """Get only running/pending jobs."""
        with self._data_lock:
            return [j for j in self._jobs if j.is_active]

    def get_job_by_id(self, job_id: str) -> Job | None:
        """Get a specific job by ID."""
        with self._data_lock:
            for job in self._jobs:
                if job.job_id == job_id:
                    return job
        return None

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None
