"""Table and overview widget-update flows for the SLURM monitor.

This module owns the logic that renders the jobs table, the cluster sidebar,
the "My Usage" banner, and the node overview tab. It collaborates with the
main app through a small :class:`_TableHost` protocol so it can read cached
SLURM data, schedule UI callbacks, and query widgets without importing the
concrete ``SlurmMonitor`` app (which would create an import cycle, since the
app imports this module).

The cursor/scroll preservation and column/filter handling live inside the
widgets these methods drive (``FilterableDataTable.set_data``,
``NodeOverviewTab.update_nodes``, ...); the controller only forwards
pre-computed rows and stats, so that fluidity-critical behaviour is preserved
exactly as before.
"""

import re
from collections.abc import Callable
from typing import Protocol, TypeVar

from textual.widgets import Static

from stoei.cluster_stats import ClusterStats
from stoei.logger import get_logger
from stoei.slurm.cache import Job, JobState
from stoei.slurm.formatters import format_compact_timeline
from stoei.widgets.cluster_sidebar import ClusterSidebar
from stoei.widgets.filterable_table import FilterableDataTable
from stoei.widgets.node_overview import NodeInfo, NodeOverviewTab
from stoei.widgets.tabs import TabContainer
from stoei.widgets.user_overview import UserStats

logger = get_logger(__name__)

# Widget type returned by ``query_one`` for a given selector/expect_type pair.
_WidgetType = TypeVar("_WidgetType")


class _TableHost(Protocol):
    """Minimal surface the :class:`TableController` needs from the app.

    Declares only the attributes and methods the controller touches so the
    controller stays decoupled from the concrete ``SlurmMonitor`` app and no
    import cycle is introduced.
    """

    # Identity / cached SLURM data the renders read from the app.
    _current_username: str
    _cached_cluster_stats: ClusterStats | None
    _cached_node_infos: list[NodeInfo]
    # Generation counters used to skip stale deferred UI updates.
    _jobs_update_gen: int
    _nodes_update_gen: int
    # Dirty flag set when the node tab is updated while inactive.
    _dirty_nodes_tab: bool

    def query_one(self, selector: str, expect_type: type[_WidgetType]) -> _WidgetType:
        """Return the single widget matching *selector* with the given type."""
        ...

    def call_later(self, callback: Callable[..., object], *args: object, **kwargs: object) -> bool:
        """Schedule *callback* to run after the current message is handled."""
        ...

    def _calculate_cluster_stats(self) -> ClusterStats:
        """Compute cluster stats on demand from cached node/job data."""
        ...

    def _parse_node_infos(self) -> list[NodeInfo]:
        """Parse cached cluster node data into :class:`NodeInfo` objects."""
        ...

    def _format_state(self, state: str, category: JobState) -> str:
        """Format a job state string with theme-aware colour markup."""
        ...


class TableController:
    """Owns the jobs-table, sidebar, usage-banner, and node-overview renders.

    The controller forwards pre-computed rows and stats into the relevant
    widgets and delegates all UI access back to the host app via the
    :class:`_TableHost` protocol.
    """

    def __init__(self, host: _TableHost) -> None:
        """Initialise the controller.

        Args:
            host: The app whose widgets the controller renders into.
        """
        self._host = host

    def update_jobs_table(self, job_rows: list[tuple[str, ...]]) -> None:
        """Push pre-computed job rows into the jobs table widget (main thread only).

        Uses a generation counter so that if multiple updates are queued
        (e.g. after returning from another tmux tab), only the latest one
        actually rebuilds the table.

        Args:
            job_rows: Pre-computed job table rows ready for display.
        """
        self._host._jobs_update_gen += 1
        gen = self._host._jobs_update_gen
        try:
            jobs_filterable = self._host.query_one("#jobs-filterable-table", FilterableDataTable)

            def _apply_jobs() -> None:
                if gen != self._host._jobs_update_gen:
                    return
                jobs_filterable.set_data(job_rows)
                jobs_filterable.display = len(job_rows) > 0
                logger.debug(f"Jobs table updated: {len(job_rows)} jobs")

            self._host.call_later(_apply_jobs)
        except Exception:
            logger.exception("Failed to update jobs table")

    def sorted_jobs_for_display(self, jobs: list[Job]) -> list[Job]:
        """Sort jobs for stable, user-friendly display.

        Ordering:
        - Active jobs first
        - Pending jobs above running jobs (newly-submitted jobs are usually pending)
        - Newest job IDs first (best-effort by numeric prefix)

        Args:
            jobs: The jobs to sort.

        Returns:
            The jobs ordered for display.
        """

        def _job_id_number(job_id: str) -> int:
            match = re.match(r"^(?P<num>\d+)", job_id)
            if match is None:
                return 0
            try:
                return int(match.group("num"))
            except ValueError:
                return 0

        def _sort_key(job: Job) -> tuple[int, int, int]:
            active_rank = 0 if job.is_active else 1
            pending_rank = 0 if job.state_category == JobState.PENDING else 1
            job_num = _job_id_number(job.job_id)
            return (active_rank, pending_rank, -job_num)

        return sorted(jobs, key=_sort_key)

    def job_row_values(self, job: Job) -> list[str]:
        """Build the row values for a job.

        Args:
            job: The job to render into a row.

        Returns:
            The ordered column values for the job row.
        """
        state_display = self._host._format_state(job.state, job.state_category)
        timeline = format_compact_timeline(
            job.submit_time,
            job.start_time,
            job.end_time,
            job.state,
            job.restarts,
        )
        return [
            job.job_id,
            job.name,
            state_display,
            job.time,
            job.nodes,
            job.node_list,
            timeline,
        ]

    def update_cluster_sidebar(self) -> None:
        """Update the cluster sidebar with current statistics.

        Uses pre-computed cluster stats from background worker to avoid blocking UI.
        Falls back to computing on-demand if cache is empty (initial load).
        """
        try:
            sidebar = self._host.query_one("#cluster-sidebar", ClusterSidebar)
            # Use cached cluster stats (computed in background worker)
            # Fall back to computing if cache is empty (shouldn't happen after initial load)
            stats = (
                self._host._cached_cluster_stats
                if self._host._cached_cluster_stats
                else self._host._calculate_cluster_stats()
            )
            sidebar.update_stats(stats)
            is_cached = self._host._cached_cluster_stats is not None
            logger.debug(
                f"Updated cluster sidebar: {stats.total_nodes} nodes, {stats.total_cpus} CPUs (cached={is_cached})"
            )
        except Exception as exc:
            logger.error(f"Failed to update cluster sidebar: {exc}", exc_info=True)

    def update_cluster_sidebar_with_stats(self, stats: ClusterStats) -> None:
        """Update the cluster sidebar using pre-computed stats (main thread only).

        Avoids reading the shared ``_cached_cluster_stats`` field, which may be
        overwritten by another worker-thread branch before the callback runs.

        Args:
            stats: Pre-computed cluster stats captured by the calling branch.
        """
        try:
            sidebar = self._host.query_one("#cluster-sidebar", ClusterSidebar)
            sidebar.update_stats(stats)
            logger.debug(f"Updated cluster sidebar: {stats.total_nodes} nodes, {stats.total_cpus} CPUs (pre-computed)")
        except Exception as exc:
            logger.error(f"Failed to update cluster sidebar: {exc}", exc_info=True)

    def update_node_overview(self) -> None:
        """Update the node overview tab using cached node infos.

        Uses a generation counter to skip stale updates and a staleness
        guard to skip work when the user has already switched away.
        """
        self._host._nodes_update_gen += 1
        gen = self._host._nodes_update_gen
        try:
            node_tab = self._host.query_one("#node-overview", NodeOverviewTab)
            node_infos = (
                self._host._cached_node_infos if self._host._cached_node_infos else self._host._parse_node_infos()
            )

            def _guarded() -> None:
                if gen != self._host._nodes_update_gen:
                    return
                try:
                    tc = self._host.query_one("#tab-container", TabContainer)
                    if tc.active_tab != "nodes":
                        self._host._dirty_nodes_tab = True
                        return
                except Exception:
                    return
                node_tab.update_nodes(node_infos)

            self._host.call_later(_guarded)
        except Exception as exc:
            logger.error(f"Failed to update node overview: {exc}", exc_info=True)

    def update_my_usage_summary(self, users: list[UserStats]) -> None:
        """Update the 'My Usage' banner on the Jobs tab.

        Args:
            users: List of all running user statistics.
        """
        try:
            summary = self._host.query_one("#my-usage-summary", Static)
        except Exception:
            return

        my_stats = next((u for u in users if u.username == self._host._current_username), None)
        if my_stats is None:
            summary.update("My Usage: No running jobs")
            return

        parts = [
            f"{my_stats.total_cpus} CPUs",
            f"{my_stats.total_memory_gb:.1f} GB RAM",
        ]
        if my_stats.total_gpus > 0:
            gpu_label = f"{my_stats.total_gpus} GPUs"
            if my_stats.gpu_types:
                gpu_label += f" ({my_stats.gpu_types})"
            parts.append(gpu_label)
        parts.append(f"{my_stats.total_nodes} Nodes")

        x = my_stats.job_count
        y = my_stats.array_count
        z = my_stats.plain_job_count
        task_word = "task" if x == 1 else "tasks"
        array_word = "array" if y == 1 else "arrays"
        job_word = "job" if z == 1 else "jobs"
        parts.append(f"{x} {task_word} ({y} {array_word}, {z} {job_word})")

        summary.update(f"My Usage: {' | '.join(parts)}")
