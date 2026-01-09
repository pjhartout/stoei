"""Main Textual TUI application for stoei."""

import re
import time
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.timer import Timer
from textual.widgets import Button, DataTable, Footer, Header, Static
from textual.widgets.data_table import RowKey
from textual.worker import Worker, WorkerState

from stoei.logger import add_tui_sink, get_logger, remove_tui_sink
from stoei.slurm.cache import Job, JobCache, JobState
from stoei.slurm.commands import (
    cancel_job,
    get_all_running_jobs,
    get_cluster_nodes,
    get_job_history,
    get_job_info,
    get_job_log_paths,
    get_node_info,
    get_running_jobs,
)
from stoei.slurm.gpu_parser import (
    aggregate_gpu_counts,
    calculate_total_gpus,
    format_gpu_types,
    has_specific_gpu_types,
    parse_gpu_entries,
    parse_gpu_from_gres,
)
from stoei.slurm.validation import check_slurm_available
from stoei.widgets.cluster_sidebar import ClusterSidebar, ClusterStats
from stoei.widgets.help_screen import HelpScreen
from stoei.widgets.loading_indicator import LoadingIndicator
from stoei.widgets.loading_screen import LoadingScreen, LoadingStep
from stoei.widgets.log_pane import LogPane
from stoei.widgets.node_overview import NodeInfo, NodeOverviewTab
from stoei.widgets.screens import CancelConfirmScreen, JobInfoScreen, JobInputScreen, NodeInfoScreen
from stoei.widgets.slurm_error_screen import SlurmUnavailableScreen
from stoei.widgets.tabs import TabContainer, TabSwitched
from stoei.widgets.user_overview import UserOverviewTab

logger = get_logger(__name__)

# Path to styles directory
STYLES_DIR = Path(__file__).parent / "styles"

# Refresh interval in seconds (increased for better performance)
REFRESH_INTERVAL = 5.0

# Minimum window width to show sidebar (sidebar is 30 wide, need space for content)
MIN_WIDTH_FOR_SIDEBAR = 100

# Job history days (user's jobs from the last N days)
JOB_HISTORY_DAYS = 7

# Loading steps for initial data load
LOADING_STEPS = [
    LoadingStep("slurm_check", "Checking SLURM availability...", weight=0.5),
    LoadingStep("cluster_nodes", "Fetching cluster nodes...", weight=2.0),
    LoadingStep("parse_nodes", "Parsing node information...", weight=1.0),
    LoadingStep("user_running", "Fetching your running jobs...", weight=1.0),
    LoadingStep("user_history", "Fetching your job history (7 days)...", weight=2.0),
    LoadingStep("all_running", "Fetching all running jobs...", weight=2.0),
    LoadingStep("aggregate_users", "Aggregating user statistics...", weight=1.0),
    LoadingStep("cluster_stats", "Calculating cluster statistics...", weight=1.0),
    LoadingStep("finalize", "Finalizing...", weight=0.5),
]


class SlurmMonitor(App[None]):
    """Textual TUI app for monitoring SLURM jobs."""

    TITLE = "STOEI"
    ENABLE_COMMAND_PALETTE = False
    LAYERS: ClassVar[list[str]] = ["base", "overlay"]
    CSS_PATH: ClassVar[list[Path]] = [
        STYLES_DIR / "app.tcss",
        STYLES_DIR / "modals.tcss",
    ]
    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh Now"),
        ("i", "show_job_info", "Job Info"),
        ("enter", "show_selected_job_info", "View Selected Job"),
        ("c", "cancel_job", "Cancel Job"),
        ("1", "switch_tab_jobs", "Jobs Tab"),
        ("2", "switch_tab_nodes", "Nodes Tab"),
        ("3", "switch_tab_users", "Users Tab"),
        ("4", "switch_tab_logs", "Logs Tab"),
        ("left", "previous_tab", "Previous Tab"),
        ("right", "next_tab", "Next Tab"),
        ("shift+tab", "previous_tab", "Previous Tab"),
        ("question_mark", "show_help", "Help"),
    )
    JOB_TABLE_COLUMNS: ClassVar[tuple[str, ...]] = ("JobID", "Name", "State", "Time", "Nodes", "NodeList")

    def __init__(self) -> None:
        """Initialize the SLURM monitor app."""
        super().__init__()
        self.refresh_interval: float = REFRESH_INTERVAL
        self.auto_refresh_timer: Timer | None = None
        self._job_cache: JobCache = JobCache()
        self._refresh_worker: Worker[None] | None = None
        self._initial_load_complete: bool = False
        self._log_sink_id: int | None = None
        self._cluster_nodes: list[dict[str, str]] = []
        self._all_users_jobs: list[tuple[str, ...]] = []
        self._is_narrow: bool = False
        self._loading_screen: LoadingScreen | None = None
        self._job_row_keys: dict[str, RowKey] = {}

    def compose(self) -> ComposeResult:
        """Create the UI layout.

        Yields:
            The widgets that make up the application UI.
        """
        yield Header(show_clock=True, icon="")
        yield LoadingIndicator(id="loading-indicator")

        with Horizontal(id="main-container"):
            # Main content area with tabs
            with Container(id="content-area"):
                yield TabContainer(id="tab-container")

                # Jobs tab (default)
                with Container(id="tab-jobs-content", classes="tab-content"):
                    with Horizontal(id="jobs-header"):
                        yield Static("[bold]📋 My Jobs[/bold]", id="jobs-title")
                        yield Button("🗑️ Cancel Job", variant="error", id="cancel-job-btn")
                    yield DataTable(id="jobs_table")

                # Nodes tab
                with Container(id="tab-nodes-content", classes="tab-content"):
                    yield NodeOverviewTab(id="node-overview")

                # Users tab
                with Container(id="tab-users-content", classes="tab-content"):
                    yield UserOverviewTab(id="user-overview")

                # Logs tab
                with Container(id="tab-logs-content", classes="tab-content"):
                    yield LogPane(id="log_pane")

            # Sidebar with cluster load (on the right)
            yield ClusterSidebar(id="cluster-sidebar")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize table and start data loading."""
        logger.info("Mounting application")

        # Hide non-default tabs initially and ensure jobs tab is visible
        try:
            jobs_tab = self.query_one("#tab-jobs-content", Container)
            jobs_tab.display = True
            nodes_tab = self.query_one("#tab-nodes-content", Container)
            nodes_tab.display = False
            users_tab = self.query_one("#tab-users-content", Container)
            users_tab.display = False
            logs_tab = self.query_one("#tab-logs-content", Container)
            logs_tab.display = False
        except Exception as exc:
            logger.warning(f"Failed to set tab visibility: {exc}")

        jobs_table = self.query_one("#jobs_table", DataTable)
        jobs_table.cursor_type = "row"
        jobs_table.add_columns("JobID", "Name", "State", "Time", "Nodes", "NodeList")
        logger.debug("Jobs table columns added, ready for data")

        # Show loading screen and start step-by-step loading
        self._loading_screen = LoadingScreen(LOADING_STEPS)
        self.push_screen(self._loading_screen)

        # Start initial load in background worker
        self._start_initial_load_worker()

    def _start_initial_load_worker(self) -> None:
        """Start background worker for initial step-by-step data load."""
        self._refresh_worker = self.run_worker(
            self._initial_load_async,
            name="initial_load",
            exclusive=True,
            thread=True,
        )

    def _loading_update_step(self, idx: int) -> None:
        """Update loading screen to show step starting."""
        screen = self._loading_screen
        if screen:
            self.call_from_thread(lambda: screen.start_step(idx))

    def _loading_complete_step(self, idx: int, msg: str | None = None) -> None:
        """Update loading screen to show step completed."""
        screen = self._loading_screen
        if screen:
            self.call_from_thread(lambda: screen.complete_step(idx, msg))

    def _loading_fail_step(self, idx: int, error: str) -> None:
        """Update loading screen to show step failed."""
        screen = self._loading_screen
        if screen:
            self.call_from_thread(lambda: screen.fail_step(idx, error))

    def _initial_load_async(self) -> None:
        """Perform initial data load with step-by-step progress (runs in worker thread)."""
        logger.info("Starting initial data load")

        # Execute loading steps and collect results
        load_result = self._execute_loading_steps()
        if load_result is None:
            return  # SLURM error, already handled

        running_jobs, history_jobs, total_jobs, total_requeues, max_requeues = load_result

        # Build job cache from fetched data
        self._loading_update_step(8)
        self._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)
        self._loading_complete_step(8, "Ready")

        # Mark loading complete and transition
        if self._loading_screen:
            self.call_from_thread(self._loading_screen.set_complete)
        time.sleep(0.5)  # Small delay to show completion state
        self.call_from_thread(self._finish_initial_load)

    def _execute_loading_steps(
        self,
    ) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], int, int, int] | None:
        """Execute loading steps and return collected data.

        Returns:
            Tuple of (running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)
            or None if SLURM is not available.
        """
        # Step 0: Check SLURM availability
        self._loading_update_step(0)
        is_available, error_msg = check_slurm_available()
        if not is_available:
            self._loading_fail_step(0, error_msg or "SLURM not available")
            logger.error(f"SLURM not available: {error_msg}")
            self.call_from_thread(self._show_slurm_error)
            return None
        self._loading_complete_step(0, "SLURM available")

        # Step 1: Fetch cluster nodes
        self._loading_update_step(1)
        nodes, error = get_cluster_nodes()
        if error:
            self._loading_fail_step(1, error)
            logger.warning(f"Failed to get cluster nodes: {error}")
            nodes = []
        else:
            self._loading_complete_step(1, f"{len(nodes)} nodes")
        self._cluster_nodes = nodes

        # Step 2: Parse node information
        self._loading_update_step(2)
        self._loading_complete_step(2, f"{len(self._cluster_nodes)} nodes parsed")

        # Step 3: Fetch user's running jobs
        self._loading_update_step(3)
        running_jobs, error = get_running_jobs()
        if error:
            self._loading_fail_step(3, error)
            logger.warning(f"Failed to get running jobs: {error}")
            # Non-fatal during initial load, just empty
            running_jobs = []
        else:
            self._loading_complete_step(3, f"{len(running_jobs)} running/pending")

        # Step 4: Fetch user's job history (7 days)
        self._loading_update_step(4)
        history_jobs, total_jobs, total_requeues, max_requeues, error = get_job_history(days=JOB_HISTORY_DAYS)
        if error:
            self._loading_fail_step(4, error)
            logger.warning(f"Failed to get job history: {error}")
            history_jobs, total_jobs, total_requeues, max_requeues = [], 0, 0, 0
        else:
            self._loading_complete_step(4, f"{total_jobs} jobs in {JOB_HISTORY_DAYS} days")

        # Step 5: Fetch all running jobs (for user overview)
        self._loading_update_step(5)
        all_running, error = get_all_running_jobs()
        if error:
            self._loading_fail_step(5, error)
            logger.warning(f"Failed to get all running jobs: {error}")
            all_running = []
        else:
            self._loading_complete_step(5, f"{len(all_running)} jobs")
        self._all_users_jobs = all_running

        # Step 6: Aggregate user statistics
        self._loading_update_step(6)
        user_stats = UserOverviewTab.aggregate_user_stats(self._all_users_jobs)
        self._loading_complete_step(6, f"{len(user_stats)} users")

        # Step 7: Calculate cluster statistics
        self._loading_update_step(7)
        cluster_stats = self._calculate_cluster_stats()
        self._loading_complete_step(7, f"{cluster_stats.total_nodes} nodes, {cluster_stats.total_gpus} GPUs")

        return running_jobs, history_jobs, total_jobs, total_requeues, max_requeues

    def _show_slurm_error(self) -> None:
        """Show SLURM unavailable error screen."""
        if self._loading_screen:
            self.pop_screen()
        self.push_screen(SlurmUnavailableScreen())

    def _finish_initial_load(self) -> None:
        """Finish initial load and transition to main UI."""
        # Pop the loading screen
        if self._loading_screen:
            self.pop_screen()
            self._loading_screen = None

        # Set up log pane as a loguru sink
        log_pane = self.query_one("#log_pane", LogPane)
        self._log_sink_id = add_tui_sink(log_pane.sink, level="DEBUG")

        logger.info("Initial load complete, transitioning to main UI")

        # Update all UI components
        self._update_ui_from_cache()

        # Mark initial load as complete
        self._initial_load_complete = True

        # Start auto-refresh timer
        self.auto_refresh_timer = self.set_interval(self.refresh_interval, self._start_refresh_worker)
        logger.info(f"Auto-refresh started with interval {self.refresh_interval}s")

        # Focus the jobs table
        try:
            jobs_table = self.query_one("#jobs_table", DataTable)
            jobs_table.focus()
            logger.debug("Focused jobs table")
        except Exception as exc:
            logger.warning(f"Failed to focus jobs table: {exc}")

        # Check window size
        self._check_window_size()

    def _start_refresh_worker(self) -> None:
        """Start background worker for lightweight data refresh."""
        if self._refresh_worker is not None and self._refresh_worker.state == WorkerState.RUNNING:
            logger.debug("Refresh worker already running, skipping")
            return

        self._refresh_worker = self.run_worker(
            self._refresh_data_async,
            name="refresh_data",
            exclusive=True,
            thread=True,
        )

    def _refresh_data_async(self) -> None:
        """Lightweight refresh of SLURM data (runs in background worker thread).

        This is used for periodic refreshes after initial load.
        Uses single commands with no loops for efficiency.
        """
        logger.debug("Background refresh starting")
        self.call_from_thread(lambda: self._set_loading_indicator(True))

        try:
            # Refresh user's jobs (running + 7-day history)
            # Use separate try/except blocks to prevent partial failures from stopping everything
            # but generally we want to update the cache only if we have data

            # Get running jobs
            running_jobs, r_error = get_running_jobs()
            if r_error:
                logger.warning(f"Failed to refresh running jobs: {r_error}")
                # Keep old data for running jobs if failed, OR maybe we should skip cache update entirely?
                # For now, let's skip cache update if ANY critical part fails to avoid inconsistencies
                running_jobs = None

            # Get history
            history_jobs, total_jobs, total_requeues, max_requeues, h_error = get_job_history(days=JOB_HISTORY_DAYS)
            if h_error:
                logger.warning(f"Failed to refresh job history: {h_error}")
                history_jobs = None

            # Only update job cache if both succeeded
            # This implements the "failover" behavior: if data fetch fails, we keep the old data displayed
            if running_jobs is not None and history_jobs is not None:
                self._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)
            else:
                self.call_from_thread(
                    lambda: self.notify("Partial refresh failure - keeping old data", severity="warning")
                )

            # Refresh cluster nodes (single scontrol command)
            nodes, error = get_cluster_nodes()
            if error:
                logger.warning(f"Failed to get cluster nodes: {error}")
                # Keep existing nodes on error
            else:
                logger.debug(f"Fetched {len(nodes)} cluster nodes")
                self._cluster_nodes = nodes

            # Refresh all running jobs (single squeue command with TRES)
            all_jobs, error = get_all_running_jobs()
            if error:
                logger.warning(f"Failed to get all running jobs: {error}")
                # Keep existing jobs on error
            else:
                logger.debug(f"Fetched {len(all_jobs)} running jobs from all users")
                self._all_users_jobs = all_jobs

            # Schedule UI update on main thread
            self.call_from_thread(self._update_ui_from_cache)

        except Exception:
            logger.exception("Error during refresh")
        finally:
            self.call_from_thread(lambda: self._set_loading_indicator(False))

    def _set_loading_indicator(self, active: bool) -> None:
        """Safely toggle the global loading indicator spinner."""
        try:
            indicator = self.query_one(LoadingIndicator)
            indicator.loading = active
        except Exception as exc:
            logger.debug(f"Failed to toggle loading indicator: {exc}")

    def _update_jobs_table(self, jobs_table: DataTable) -> None:
        """Update the jobs table with cached job data.

        Args:
            jobs_table: The DataTable widget to update.
        """
        cursor_row = jobs_table.cursor_row
        cursor_job_id = self._job_id_from_row_index(jobs_table, cursor_row)

        jobs = self._job_cache.jobs
        desired_job_ids = {job.job_id for job in jobs}

        removed_rows = self._remove_missing_job_rows(jobs_table, desired_job_ids)
        rows_changed = self._upsert_job_rows(jobs_table, jobs)

        cursor_restored = self._restore_jobs_table_cursor(jobs_table, cursor_row, cursor_job_id)
        jobs_table.display = jobs_table.row_count > 0
        if not cursor_restored and jobs_table.row_count == 0:
            jobs_table.cursor_type = "row"

        logger.debug(
            f"Jobs table reconciled: {jobs_table.row_count} rows, {rows_changed} updates, {removed_rows} removals"
        )

    def _remove_missing_job_rows(self, jobs_table: DataTable, desired_job_ids: set[str]) -> int:
        """Remove rows that are no longer present in the latest data."""
        removed = 0
        for job_id in list(self._job_row_keys):
            if job_id in desired_job_ids:
                continue
            row_key = self._job_row_keys.pop(job_id)
            try:
                jobs_table.remove_row(row_key)
                removed += 1
            except Exception as exc:
                logger.debug(f"Failed to remove row for {job_id}: {exc}")
        return removed

    def _upsert_job_rows(self, jobs_table: DataTable, jobs: list[Job]) -> int:
        """Insert new rows and update existing ones with the latest job data."""
        changes = 0
        for job in jobs:
            row_values = self._job_row_values(job)
            row_key = self._job_row_keys.get(job.job_id)
            if row_key is None:
                try:
                    new_key = jobs_table.add_row(*row_values)
                    self._job_row_keys[job.job_id] = new_key
                    changes += 1
                except Exception:
                    logger.exception(f"Failed to add job {job.job_id} to table")
                continue
            current_row = self._safe_get_row(jobs_table, row_key)
            if current_row is None or len(current_row) != len(row_values):
                if self._replace_job_row(jobs_table, job.job_id, row_key, row_values):
                    changes += 1
                continue
            if self._update_changed_cells(jobs_table, row_key, row_values, current_row, job.job_id):
                changes += 1
        return changes

    def _safe_get_row(self, jobs_table: DataTable, row_key: RowKey) -> list[str] | None:
        """Return row values for the provided key, handling missing rows gracefully."""
        try:
            return jobs_table.get_row(row_key)
        except Exception:
            return None

    def _replace_job_row(
        self,
        jobs_table: DataTable,
        job_id: str,
        old_key: RowKey,
        row_values: list[str],
    ) -> bool:
        """Replace an existing row entirely."""
        try:
            jobs_table.remove_row(old_key)
        except Exception as exc:
            logger.debug(f"Failed to remove stale row for {job_id}: {exc}")
        try:
            new_key = jobs_table.add_row(*row_values)
        except Exception:
            logger.exception(f"Failed to re-add row for {job_id}")
            return False
        self._job_row_keys[job_id] = new_key
        return True

    def _update_changed_cells(
        self,
        jobs_table: DataTable,
        row_key: RowKey,
        new_values: list[str],
        existing_values: list[str],
        job_id: str,
    ) -> bool:
        """Update individual cells that have changed."""
        updated = False
        for column_key, new_value, existing_value in zip(
            self.JOB_TABLE_COLUMNS,
            new_values,
            existing_values,
            strict=False,
        ):
            if new_value == existing_value:
                continue
            try:
                jobs_table.update_cell(row_key, column_key, new_value)
                updated = True
            except Exception:
                logger.exception(f"Failed to update {column_key} for job {job_id}")
        return updated

    def _restore_jobs_table_cursor(
        self,
        jobs_table: DataTable,
        cursor_row: int | None,
        cursor_job_id: str | None,
    ) -> bool:
        """Restore the cursor position after the table has been updated."""
        if cursor_job_id and cursor_job_id in self._job_row_keys:
            try:
                row_index = jobs_table.get_row_index(self._job_row_keys[cursor_job_id])
            except Exception as exc:
                logger.debug(f"Failed to restore cursor to job {cursor_job_id}: {exc}")
            else:
                jobs_table.move_cursor(row=row_index)
                return True
        if jobs_table.row_count == 0:
            return False
        target_row = cursor_row if cursor_row is not None else 0
        target_row = max(0, min(target_row, jobs_table.row_count - 1))
        jobs_table.move_cursor(row=target_row)
        return True

    def _job_row_values(self, job: Job) -> list[str]:
        """Build the row values for a job."""
        state_display = self._format_state(job.state, job.state_category)
        return [
            job.job_id,
            job.name,
            state_display,
            job.time,
            job.nodes,
            job.node_list,
        ]

    def _job_id_from_row_index(self, jobs_table: DataTable, row_index: int | None) -> str | None:
        """Get job ID from a row index if available."""
        if row_index is None or row_index < 0:
            return None
        try:
            row_values = jobs_table.get_row_at(row_index)
        except Exception:
            return None
        return row_values[0] if row_values else None

    def _update_ui_from_cache(self) -> None:
        """Update UI components from cached data (must run on main thread)."""
        # Check which tab is active
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            active_tab = tab_container.active_tab
        except Exception:
            active_tab = "jobs"  # Default to jobs tab if we can't determine

        # Only update jobs table if jobs tab is active
        if active_tab == "jobs":
            try:
                jobs_table = self.query_one("#jobs_table", DataTable)
                self._update_jobs_table(jobs_table)
            except Exception:
                logger.exception("Failed to find jobs table")

        # Update cluster sidebar
        self._update_cluster_sidebar()

        # Update node and user overview if those tabs are active
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "nodes":
                self._update_node_overview()
            elif tab_container.active_tab == "users":
                self._update_user_overview()
        except Exception as exc:
            logger.debug(f"Failed to update tab-specific overview: {exc}")

        # Check window size and adjust layout
        self._check_window_size()

    def _format_state(self, state: str, category: JobState) -> str:
        """Format job state with color coding.

        Args:
            state: Raw state string.
            category: Categorized state.

        Returns:
            Rich-formatted state string.
        """
        state_formats = {
            JobState.RUNNING: f"[bold green]{state}[/bold green]",
            JobState.PENDING: f"[bold yellow]{state}[/bold yellow]",
            JobState.COMPLETED: f"[green]{state}[/green]",
            JobState.FAILED: f"[bold red]{state}[/bold red]",
            JobState.CANCELLED: f"[bright_black]{state}[/bright_black]",
            JobState.TIMEOUT: f"[red]{state}[/red]",
        }
        return state_formats.get(category, state)

    def _update_cluster_sidebar(self) -> None:
        """Update the cluster sidebar with current statistics."""
        try:
            sidebar = self.query_one("#cluster-sidebar", ClusterSidebar)
            stats = self._calculate_cluster_stats()
            sidebar.update_stats(stats)
            logger.debug(f"Updated cluster sidebar: {stats.total_nodes} nodes, {stats.total_cpus} CPUs")
        except Exception as exc:
            logger.error(f"Failed to update cluster sidebar: {exc}", exc_info=True)

    def _parse_node_state(self, state: str, stats: ClusterStats) -> None:
        """Parse node state and update node counts.

        Args:
            state: Node state string (uppercase).
            stats: ClusterStats object to update.
        """
        stats.total_nodes += 1
        if "IDLE" in state or "ALLOCATED" in state or "MIXED" in state:
            if "IDLE" in state:
                stats.free_nodes += 1
            else:
                stats.allocated_nodes += 1

    def _parse_node_cpus(self, node_data: dict[str, str], stats: ClusterStats) -> None:
        """Parse CPU information from node data.

        Args:
            node_data: Node data dictionary.
            stats: ClusterStats object to update.
        """
        cpus_total_str = node_data.get("CPUTot", "0")
        cpus_alloc_str = node_data.get("CPUAlloc", "0")
        try:
            cpus_total = int(cpus_total_str)
            cpus_alloc = int(cpus_alloc_str)
            stats.total_cpus += cpus_total
            stats.allocated_cpus += cpus_alloc
        except ValueError:
            pass

    def _parse_node_memory(self, node_data: dict[str, str], stats: ClusterStats) -> None:
        """Parse memory information from node data.

        Args:
            node_data: Node data dictionary.
            stats: ClusterStats object to update.
        """
        mem_total_str = node_data.get("RealMemory", "0")
        mem_alloc_str = node_data.get("AllocMem", "0")
        try:
            mem_total_mb = int(mem_total_str)
            mem_alloc_mb = int(mem_alloc_str)
            stats.total_memory_gb += mem_total_mb / 1024.0
            stats.allocated_memory_gb += mem_alloc_mb / 1024.0
        except ValueError:
            pass

    def _process_gpu_entries_for_stats(
        self, gpu_entries: list[tuple[str, int]], stats: ClusterStats, is_allocated: bool
    ) -> None:
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

    def _parse_gpus_from_gres(self, node_data: dict[str, str], state: str, stats: ClusterStats) -> None:
        """Parse GPUs from Gres field (fallback when TRES is not available).

        Args:
            node_data: Node data dictionary.
            state: Node state string (uppercase).
            stats: ClusterStats object to update.
        """
        gres = node_data.get("Gres", "")
        gpu_entries = parse_gpu_from_gres(gres)

        for gpu_type, gpu_count in gpu_entries:
            current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
            stats.gpus_by_type[gpu_type] = (current_total + gpu_count, current_alloc)
            stats.total_gpus += gpu_count
            # Estimate allocated GPUs based on node state
            if "ALLOCATED" in state or "MIXED" in state:
                current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
                stats.gpus_by_type[gpu_type] = (current_total, current_alloc + gpu_count)
                stats.allocated_gpus += gpu_count

    def _calculate_cluster_stats(self) -> ClusterStats:
        """Calculate cluster statistics from node data.

        Returns:
            ClusterStats object with aggregated statistics.
        """
        stats = ClusterStats()

        if not self._cluster_nodes:
            logger.debug("No cluster nodes available for stats calculation")
            return stats

        for node_data in self._cluster_nodes:
            # Parse node information
            state = node_data.get("State", "").upper()

            # Count nodes
            self._parse_node_state(state, stats)

            # Parse CPUs
            self._parse_node_cpus(node_data, stats)

            # Parse memory
            self._parse_node_memory(node_data, stats)

            # Parse GPUs by type from CfgTRES and AllocTRES
            cfg_tres = node_data.get("CfgTRES", "")
            alloc_tres = node_data.get("AllocTRES", "")

            # Parse CfgTRES for total GPUs by type
            # Note: If both generic (gres/gpu=8) and specific (gres/gpu:h200=8) exist,
            # they represent the same GPUs, so we only count specific types to avoid double-counting
            gpu_entries = parse_gpu_entries(cfg_tres)
            self._process_gpu_entries_for_stats(gpu_entries, stats, is_allocated=False)

            # Parse AllocTRES for allocated GPUs by type
            alloc_entries = parse_gpu_entries(alloc_tres)
            self._process_gpu_entries_for_stats(alloc_entries, stats, is_allocated=True)

            # Fallback: if no TRES data, try parsing Gres field
            if not cfg_tres and not alloc_tres:
                self._parse_gpus_from_gres(node_data, state, stats)

        return stats

    def _update_node_overview(self) -> None:
        """Update the node overview tab."""
        try:
            node_tab = self.query_one("#node-overview", NodeOverviewTab)
            node_infos = self._parse_node_infos()
            logger.debug(f"Updating node overview with {len(node_infos)} nodes")
            node_tab.update_nodes(node_infos)
        except Exception as exc:
            logger.error(f"Failed to update node overview: {exc}", exc_info=True)

    def _parse_node_infos(self) -> list[NodeInfo]:
        """Parse cluster node data into NodeInfo objects.

        Returns:
            List of NodeInfo objects.
        """
        node_infos: list[NodeInfo] = []

        for node_data in self._cluster_nodes:
            node_name = node_data.get("NodeName", "").strip()
            # Skip nodes with empty names
            if not node_name:
                logger.warning("Skipping node with empty name")
                continue

            state = node_data.get("State", "").strip() or "UNKNOWN"
            partitions = node_data.get("Partitions", "").strip() or "N/A"
            reason = node_data.get("Reason", "").strip()

            # Parse CPUs
            cpus_total = int(node_data.get("CPUTot", "0") or "0")
            cpus_alloc = int(node_data.get("CPUAlloc", "0") or "0")

            # Parse memory (MB to GB)
            mem_total_mb = int(node_data.get("RealMemory", "0") or "0")
            mem_alloc_mb = int(node_data.get("AllocMem", "0") or "0")
            mem_total_gb = mem_total_mb / 1024.0
            mem_alloc_gb = mem_alloc_mb / 1024.0

            # Parse GPUs - use TRES data first (more accurate), fallback to Gres
            gpus_total = 0
            gpus_alloc = 0
            gpu_types_str = ""

            cfg_tres = node_data.get("CfgTRES", "")
            alloc_tres = node_data.get("AllocTRES", "")
            gres = node_data.get("Gres", "")

            # Parse total GPUs from CfgTRES (preferred) or Gres (fallback)
            gpu_type_counts_dict: dict[str, int] = {}

            if cfg_tres:
                gpu_entries = parse_gpu_entries(cfg_tres)
                gpu_type_counts_dict = aggregate_gpu_counts(gpu_entries)
                gpus_total = calculate_total_gpus(gpu_entries)
            elif "gpu:" in gres.lower():
                gpu_entries = parse_gpu_from_gres(gres)
                gpu_type_counts_dict = aggregate_gpu_counts(gpu_entries)
                gpus_total = calculate_total_gpus(gpu_entries)

            # Format GPU types string (e.g., "8x H200" or "4x A100, 2x V100")
            gpu_types_str = format_gpu_types(gpu_type_counts_dict)

            # Parse allocated GPUs from AllocTRES or state-based logic
            if alloc_tres:
                alloc_entries = parse_gpu_entries(alloc_tres)
                gpus_alloc = calculate_total_gpus(alloc_entries)
            elif gpus_total > 0:
                # Fallback to state-based allocation if no AllocTRES
                if "ALLOCATED" in state.upper():
                    gpus_alloc = gpus_total

            node_infos.append(
                NodeInfo(
                    name=node_name,
                    state=state,
                    cpus_alloc=cpus_alloc,
                    cpus_total=cpus_total,
                    memory_alloc_gb=mem_alloc_gb,
                    memory_total_gb=mem_total_gb,
                    gpus_alloc=gpus_alloc,
                    gpus_total=gpus_total,
                    partitions=partitions,
                    reason=reason,
                    gpu_types=gpu_types_str,
                )
            )

        return node_infos

    def _update_user_overview(self) -> None:
        """Update the user overview tab."""
        try:
            user_tab = self.query_one("#user-overview", UserOverviewTab)
            user_stats = UserOverviewTab.aggregate_user_stats(self._all_users_jobs)
            logger.debug(f"Updating user overview with {len(user_stats)} users from {len(self._all_users_jobs)} jobs")
            user_tab.update_users(user_stats)
        except Exception as exc:
            logger.error(f"Failed to update user overview: {exc}", exc_info=True)

    def on_tab_switched(self, event: TabSwitched) -> None:
        """Handle tab switching events.

        Args:
            event: The TabSwitched event.
        """
        # Hide all tab contents
        for tab_id in ["tab-jobs-content", "tab-nodes-content", "tab-users-content", "tab-logs-content"]:
            try:
                tab_content = self.query_one(f"#{tab_id}", Container)
                tab_content.display = False
            except Exception as exc:
                logger.debug(f"Failed to hide tab {tab_id}: {exc}")

        # Show the active tab content
        active_tab_id = f"tab-{event.tab_name}-content"
        try:
            active_tab = self.query_one(f"#{active_tab_id}", Container)
            active_tab.display = True

            # Update the tab content if needed (always update when switching to ensure data is shown)
            # Defer heavy operations to avoid blocking the tab switch
            if event.tab_name == "jobs":
                # Focus the jobs table to enable arrow key navigation
                try:
                    jobs_table = self.query_one("#jobs_table", DataTable)
                    jobs_table.focus()
                    logger.debug("Focused jobs table for arrow key navigation")
                except Exception as exc:
                    logger.debug(f"Failed to focus jobs table: {exc}")
            elif event.tab_name == "nodes":
                # Defer heavy update to avoid blocking tab switch
                self.call_later(self._update_node_overview)
                # Focus the nodes table to enable arrow key navigation
                try:
                    node_tab = self.query_one("#node-overview", NodeOverviewTab)
                    nodes_table = node_tab.query_one("#nodes_table", DataTable)
                    nodes_table.focus()
                    logger.debug("Focused nodes table for arrow key navigation")
                except Exception as exc:
                    logger.debug(f"Failed to focus nodes table: {exc}")
            elif event.tab_name == "users":
                # Defer heavy update to avoid blocking tab switch
                self.call_later(self._update_user_overview)
                # Focus the users table to enable arrow key navigation
                try:
                    user_tab = self.query_one("#user-overview", UserOverviewTab)
                    users_table = user_tab.query_one("#users_table", DataTable)
                    users_table.focus()
                    logger.debug("Focused users table for arrow key navigation")
                except Exception as exc:
                    logger.debug(f"Failed to focus users table: {exc}")
            elif event.tab_name == "logs":
                # Focus the log pane when switching to logs tab
                try:
                    log_pane = self.query_one("#log_pane", LogPane)
                    log_pane.focus()
                    logger.debug("Focused log pane")
                except Exception as exc:
                    logger.debug(f"Failed to focus log pane: {exc}")
        except Exception as exc:
            logger.warning(f"Failed to switch to tab {event.tab_name}: {exc}")

    def action_refresh(self) -> None:
        """Manual refresh action."""
        logger.info("Manual refresh triggered")
        self.notify("Refreshing...")
        self._start_refresh_worker()

    def action_switch_tab_jobs(self) -> None:
        """Switch to the Jobs tab."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab("jobs")
        except Exception as exc:
            logger.debug(f"Failed to switch to jobs tab: {exc}")

    def action_switch_tab_nodes(self) -> None:
        """Switch to the Nodes tab."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab("nodes")
        except Exception as exc:
            logger.debug(f"Failed to switch to nodes tab: {exc}")

    def action_switch_tab_users(self) -> None:
        """Switch to the Users tab."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab("users")
        except Exception as exc:
            logger.debug(f"Failed to switch to users tab: {exc}")

    def action_switch_tab_logs(self) -> None:
        """Switch to the Logs tab."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab("logs")
        except Exception as exc:
            logger.debug(f"Failed to switch to logs tab: {exc}")

    def action_next_tab(self) -> None:
        """Switch to the next tab (cycling)."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            current_tab = tab_container.active_tab
            tab_order = ["jobs", "nodes", "users", "logs"]
            current_index = tab_order.index(current_tab)
            next_index = (current_index + 1) % len(tab_order)
            tab_container.switch_tab(tab_order[next_index])
        except Exception as exc:
            logger.debug(f"Failed to switch to next tab: {exc}")

    def action_previous_tab(self) -> None:
        """Switch to the previous tab (cycling)."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            current_tab = tab_container.active_tab
            tab_order = ["jobs", "nodes", "users", "logs"]
            current_index = tab_order.index(current_tab)
            previous_index = (current_index - 1) % len(tab_order)
            tab_container.switch_tab(tab_order[previous_index])
        except Exception as exc:
            logger.debug(f"Failed to switch to previous tab: {exc}")

    def on_key(self, event: Key) -> None:
        """Handle key events, intercepting Tab for tab navigation.

        Args:
            event: The key event.
        """
        # Intercept Tab for tab navigation (Shift+Tab is handled by binding)
        # Check if it's a plain tab (not shift+tab which comes through as binding)
        if event.key == "tab" and event.name == "tab":
            event.prevent_default()
            self.action_next_tab()

    def action_show_help(self) -> None:
        """Show help screen with keybindings."""
        logger.debug("Showing help screen")
        self.push_screen(HelpScreen())

    def action_show_job_info(self) -> None:
        """Show job info dialog."""

        def handle_job_id(job_id: str | None) -> None:
            if job_id:
                logger.info(f"Looking up job info for {job_id}")
                job_info, error = get_job_info(job_id)
                stdout_path, stderr_path, _ = get_job_log_paths(job_id)
                self.push_screen(JobInfoScreen(job_id, job_info, error, stdout_path, stderr_path))

        self.push_screen(JobInputScreen(), handle_job_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in data tables.

        Args:
            event: The row selected event.
        """
        # Check if this is the nodes table
        if event.data_table.id == "nodes_table":
            self._show_node_info_for_row(event.data_table, event.row_key)
        else:
            # Default to job info for jobs table
            self._show_job_info_for_row(event.data_table, event.row_key)

    def _show_node_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show node info for a specific row in the nodes table.

        Args:
            table: The DataTable containing the row.
            row_key: The key of the row to show info for.
        """
        try:
            row_data = table.get_row(row_key)
            node_name = str(row_data[0]).strip()
            # Remove Rich markup tags if present
            node_name = re.sub(r"\[.*?\]", "", node_name).strip()

            if not node_name:
                logger.warning(f"Could not extract node name from row {row_key}")
                self.notify("Could not get node name from selected row", severity="error")
                return

            logger.info(f"Showing info for selected node {node_name}")
            self._show_node_info(node_name)

        except (IndexError, KeyError):
            logger.exception(f"Could not get node name from row {row_key}")
            self.notify("Could not get node name from selected row", severity="error")

    def _show_node_info(self, node_name: str) -> None:
        """Show detailed information for a node.

        Args:
            node_name: The name of the node to display.
        """
        logger.info(f"Fetching node info for {node_name}")
        self.notify("Loading node information...", timeout=2)

        # Get node info in a worker to avoid blocking
        def fetch_node_info() -> None:
            node_info, error = get_node_info(node_name)
            self.call_from_thread(lambda: self._display_node_info(node_name, node_info, error))

        self.run_worker(fetch_node_info, name="fetch_node_info", thread=True)

    def _display_node_info(self, node_name: str, node_info: str, error: str | None) -> None:
        """Display node information in a modal screen.

        Args:
            node_name: The node name.
            node_info: Formatted node information.
            error: Optional error message.
        """
        self.push_screen(NodeInfoScreen(node_name, node_info, error))
        logger.debug(f"Displayed node info screen for {node_name}")

    def _show_job_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show job info for a specific row in a table.

        Args:
            table: The DataTable containing the row.
            row_key: The key of the row to show info for.
        """
        try:
            row_data = table.get_row(row_key)
            job_id = str(row_data[0]).strip()
            logger.info(f"Showing info for selected job {job_id}")
            job_info, error = get_job_info(job_id)
            stdout_path, stderr_path, _ = get_job_log_paths(job_id)
            self.push_screen(JobInfoScreen(job_id, job_info, error, stdout_path, stderr_path))
        except (IndexError, KeyError):
            logger.exception(f"Could not get job ID from row {row_key}")
            self.notify("Could not get job ID from selected row", severity="error")

    def action_show_selected_job_info(self) -> None:
        """Show job info for the currently selected row."""
        jobs_table = self.query_one("#jobs_table", DataTable)

        if jobs_table.row_count == 0:
            self.notify("No jobs to display", severity="warning")
            return

        cursor_row = jobs_table.cursor_row
        if cursor_row is None or cursor_row < 0:
            self.notify("No row selected", severity="warning")
            return

        try:
            row_data = jobs_table.get_row_at(cursor_row)
            job_id = str(row_data[0]).strip()
            logger.info(f"Showing info for selected job {job_id}")
            job_info, error = get_job_info(job_id)
            stdout_path, stderr_path, _ = get_job_log_paths(job_id)
            self.push_screen(JobInfoScreen(job_id, job_info, error, stdout_path, stderr_path))
        except (IndexError, KeyError):
            logger.exception(f"Could not get job ID from row {cursor_row}")
            self.notify("Could not get job ID from selected row", severity="error")

    def action_cancel_job(self) -> None:
        """Cancel the selected job after confirmation."""
        jobs_table = self.query_one("#jobs_table", DataTable)

        if jobs_table.row_count == 0:
            self.notify("No jobs to cancel", severity="warning")
            return

        cursor_row = jobs_table.cursor_row
        if cursor_row is None or cursor_row < 0:
            self.notify("No job selected", severity="warning")
            return

        try:
            row_data = jobs_table.get_row_at(cursor_row)
            job_id = str(row_data[0]).strip()
            job_name = str(row_data[1]).strip() if len(row_data) > 1 else None

            # Check if job is active (can be cancelled)
            cached_job = self._job_cache.get_job_by_id(job_id)
            if cached_job and not cached_job.is_active:
                self.notify("Cannot cancel completed job", severity="warning")
                return

            def handle_confirmation(confirmed: bool | None) -> None:
                if confirmed is True:
                    try:
                        success, error = cancel_job(job_id)
                        if success:
                            logger.info(f"Successfully cancelled job {job_id}")
                            self.notify(f"Job {job_id} cancelled", severity="information")
                            try:
                                self._start_refresh_worker()  # Refresh to update state
                            except Exception:
                                logger.exception(f"Failed to start refresh worker after cancelling job {job_id}")
                                # Don't fail the cancellation if refresh fails
                        else:
                            logger.error(f"Failed to cancel job {job_id}: {error}")
                            self.notify(f"Failed to cancel: {error}", severity="error")
                    except Exception as exc:
                        logger.exception(f"Unexpected error while cancelling job {job_id}")
                        self.notify(f"Unexpected error cancelling job: {exc}", severity="error")

            self.push_screen(CancelConfirmScreen(job_id, job_name), handle_confirmation)

        except (IndexError, KeyError):
            logger.exception(f"Could not get job ID from row {cursor_row}")
            self.notify("Could not get job ID from selected row", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: The button press event.
        """
        if event.button.id == "cancel-job-btn":
            self.action_cancel_job()

    def _check_window_size(self) -> None:
        """Check window size and adjust layout accordingly."""
        try:
            width = self.size.width
            # Hide sidebar if window is narrower than threshold
            # Sidebar is 30 wide, so we need at least MIN_WIDTH_FOR_SIDEBAR for comfortable viewing
            is_narrow = width < MIN_WIDTH_FOR_SIDEBAR

            if is_narrow != self._is_narrow:
                self._is_narrow = is_narrow
                self._update_responsive_layout()

        except Exception as exc:
            logger.debug(f"Failed to check window size: {exc}")

    def _update_responsive_layout(self) -> None:
        """Update layout based on window size."""
        try:
            # Update sidebar visibility
            sidebar = self.query_one("#cluster-sidebar", ClusterSidebar)
            if self._is_narrow:
                sidebar.add_class("narrow")
            else:
                sidebar.remove_class("narrow")

            # Update tab compact mode
            tab_container = self.query_one("#tab-container", TabContainer)
            tab_container.set_compact(self._is_narrow)

        except Exception as exc:
            logger.debug(f"Failed to update responsive layout: {exc}")

    def on_resize(self) -> None:
        """Handle window resize events."""
        self._check_window_size()

    async def action_quit(self) -> None:
        """Quit the application."""
        logger.info("Quitting application")
        if self.auto_refresh_timer:
            self.auto_refresh_timer.stop()
        # Clean up log sink
        if self._log_sink_id is not None:
            remove_tui_sink(self._log_sink_id)
            self._log_sink_id = None
        self.exit()


def main() -> None:
    """Run the SLURM monitor TUI app."""
    app = SlurmMonitor()
    app.run()
    logger.info("Stoei exited")
