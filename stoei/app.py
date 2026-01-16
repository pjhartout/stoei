"""Main Textual TUI application for stoei."""

import contextlib
import re
import time
from pathlib import Path
from typing import ClassVar

from rich.console import RenderableType
from textual._path import CSSPathType
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Static
from textual.widgets.data_table import ColumnKey, RowKey
from textual.worker import Worker, WorkerState

from stoei.colors import get_theme_colors
from stoei.logger import add_tui_sink, get_logger, remove_tui_sink
from stoei.settings import Settings, load_settings, save_settings
from stoei.slurm.array_parser import parse_array_size
from stoei.slurm.cache import Job, JobCache, JobState
from stoei.slurm.commands import (
    cancel_job,
    get_all_job_history_6months,
    get_all_running_jobs,
    get_cluster_nodes,
    get_job_history,
    get_job_info,
    get_job_log_paths,
    get_node_info,
    get_running_jobs,
    get_user_jobs,
)
from stoei.slurm.formatters import format_compact_timeline, format_user_info
from stoei.slurm.gpu_parser import (
    aggregate_gpu_counts,
    calculate_total_gpus,
    format_gpu_types,
    has_specific_gpu_types,
    parse_gpu_entries,
    parse_gpu_from_gres,
)
from stoei.slurm.validation import check_slurm_available
from stoei.themes import DEFAULT_THEME_NAME, REGISTERED_THEMES
from stoei.widgets.cluster_sidebar import ClusterSidebar, ClusterStats, PendingPartitionStats
from stoei.widgets.help_screen import HelpScreen
from stoei.widgets.loading_indicator import LoadingIndicator
from stoei.widgets.loading_screen import LoadingScreen, LoadingStep
from stoei.widgets.log_pane import LogPane
from stoei.widgets.node_overview import NodeInfo, NodeOverviewTab
from stoei.widgets.screens import (
    CancelConfirmScreen,
    JobInfoScreen,
    JobInputScreen,
    NodeInfoScreen,
    UserInfoScreen,
)
from stoei.widgets.settings_screen import SettingsScreen
from stoei.widgets.slurm_error_screen import SlurmUnavailableScreen
from stoei.widgets.tabs import TabContainer, TabSwitched
from stoei.widgets.user_overview import UserOverviewTab, UserStats

logger = get_logger(__name__)

# Path to styles directory
STYLES_DIR = Path(__file__).parent / "styles"

# Minimum window width to show sidebar (sidebar is 30 wide, need space for content)
MIN_WIDTH_FOR_SIDEBAR = 100

# Loading steps for initial data load
LOADING_STEPS = [
    LoadingStep("slurm_check", "Checking SLURM availability...", weight=0.5),
    LoadingStep("cluster_nodes", "Fetching cluster nodes...", weight=2.0),
    LoadingStep("parse_nodes", "Parsing node information...", weight=1.0),
    LoadingStep("user_running", "Fetching your running jobs...", weight=1.0),
    LoadingStep("user_history", "Fetching your job history...", weight=2.0),
    LoadingStep("all_running", "Fetching all running jobs...", weight=2.0),
    LoadingStep("energy_history", "Fetching 6-month energy history...", weight=3.0),
    LoadingStep("aggregate_users", "Aggregating user statistics...", weight=1.0),
    LoadingStep("cluster_stats", "Calculating cluster statistics...", weight=1.0),
    LoadingStep("finalize", "Finalizing...", weight=0.5),
]


class SlurmMonitor(App[None]):
    """Textual TUI app for monitoring SLURM jobs."""

    TITLE = "STOEI"
    ENABLE_COMMAND_PALETTE = False
    LAYERS: ClassVar[list[str]] = ["base", "overlay"]
    CSS_PATH: ClassVar[CSSPathType | None] = [
        STYLES_DIR / "app.tcss",
        STYLES_DIR / "modals.tcss",
    ]
    THEME_VARIABLE_DEFAULTS: ClassVar[dict[str, str]] = {
        "text-muted": "ansi_bright_black",
        "text-subtle": "ansi_bright_black",
        "border": "ansi_bright_black",
        "border-muted": "ansi_black",
        "accent-hover": "ansi_bright_blue",
        "accent-active": "ansi_blue",
        "text-on-accent": "ansi_bright_white",
        "text-on-error": "ansi_bright_white",
        "text-on-warning": "ansi_black",
        "text-on-success": "ansi_black",
    }
    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh Now"),
        ("s", "show_settings", "Settings"),
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
    ]
    JOB_TABLE_COLUMNS: ClassVar[tuple[str, ...]] = ("JobID", "Name", "State", "Time", "Nodes", "NodeList", "Timeline")

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Provide default values for custom theme variables."""
        return {**super().get_theme_variable_defaults(), **self.THEME_VARIABLE_DEFAULTS}

    def __init__(self) -> None:
        """Initialize the SLURM monitor app."""
        self._settings: Settings = load_settings()
        super().__init__()
        self._register_custom_themes()
        self._apply_theme(self._settings.theme)
        self.refresh_interval: float = self._settings.refresh_interval
        self.auto_refresh_timer: Timer | None = None
        self._job_cache: JobCache = JobCache()
        self._refresh_worker: Worker[None] | None = None
        self._initial_load_complete: bool = False
        self._log_sink_id: int | None = None
        self._cluster_nodes: list[dict[str, str]] = []
        self._all_users_jobs: list[tuple[str, ...]] = []
        self._energy_history_jobs: list[tuple[str, ...]] = []  # 6-month energy history (loaded once at startup)
        self._is_narrow: bool = False
        self._loading_screen: LoadingScreen | None = None
        self._job_row_keys: dict[str, RowKey] = {}
        self._job_table_column_keys: list[ColumnKey] = []
        self._last_history_jobs: list[tuple[str, ...]] = []
        self._last_history_stats: tuple[int, int, int] = (0, 0, 0)

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
                    yield DataTable(id="jobs_table")

                # Nodes tab
                with Container(id="tab-nodes-content", classes="tab-content"):
                    yield NodeOverviewTab(id="node-overview")

                # Users tab
                with Container(id="tab-users-content", classes="tab-content"):
                    yield UserOverviewTab(id="user-overview")

                # Logs tab
                with Container(id="tab-logs-content", classes="tab-content"):
                    yield LogPane(id="log_pane", max_lines=self._settings.max_log_lines)

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
        self._job_table_column_keys = jobs_table.add_columns(
            "JobID", "Name", "State", "Time", "Nodes", "NodeList", "Timeline"
        )
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

        # Save initial history for fallback
        self._last_history_jobs = history_jobs
        self._last_history_stats = (total_jobs, total_requeues, max_requeues)

        # Build job cache from fetched data
        self._loading_update_step(9)
        self._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)
        self._loading_complete_step(9, "Ready")

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
        if not self._load_step_check_slurm():
            return None

        # Steps 1-2: Load cluster nodes
        self._load_step_cluster_nodes()

        # Step 3: Fetch user's running jobs
        running_jobs = self._load_step_running_jobs()

        # Step 4: Fetch user's job history
        history_jobs, total_jobs, total_requeues, max_requeues = self._load_step_job_history()

        # Step 5: Fetch all running jobs (for user overview)
        self._load_step_all_running_jobs()

        # Step 6: Fetch 6-month energy history (only at startup)
        self._load_step_energy_history()

        # Steps 7-8: Calculate statistics
        self._load_step_statistics()

        return running_jobs, history_jobs, total_jobs, total_requeues, max_requeues

    def _load_step_check_slurm(self) -> bool:
        """Execute step 0: Check SLURM availability."""
        self._loading_update_step(0)
        is_available, error_msg = check_slurm_available()
        if not is_available:
            self._loading_fail_step(0, error_msg or "SLURM not available")
            logger.error(f"SLURM not available: {error_msg}")
            self.call_from_thread(self._show_slurm_error)
            return False
        self._loading_complete_step(0, "SLURM available")
        return True

    def _load_step_cluster_nodes(self) -> None:
        """Execute steps 1-2: Fetch and parse cluster nodes."""
        self._loading_update_step(1)
        nodes, error = get_cluster_nodes()
        if error:
            self._loading_fail_step(1, error)
            logger.warning(f"Failed to get cluster nodes: {error}")
            nodes = []
        else:
            self._loading_complete_step(1, f"{len(nodes)} nodes")
        self._cluster_nodes = nodes

        self._loading_update_step(2)
        self._loading_complete_step(2, f"{len(self._cluster_nodes)} nodes parsed")

    def _load_step_running_jobs(self) -> list[tuple[str, ...]]:
        """Execute step 3: Fetch user's running jobs."""
        self._loading_update_step(3)
        running_jobs, error = get_running_jobs()
        if error:
            self._loading_fail_step(3, error)
            logger.warning(f"Failed to get running jobs: {error}")
            return []
        self._loading_complete_step(3, f"{len(running_jobs)} running/pending")
        return running_jobs

    def _load_step_job_history(self) -> tuple[list[tuple[str, ...]], int, int, int]:
        """Execute step 4: Fetch user's job history."""
        self._loading_update_step(4)
        job_history_days = self._settings.job_history_days
        history_jobs, total_jobs, total_requeues, max_requeues, error = get_job_history(days=job_history_days)
        if error:
            self._loading_fail_step(4, error)
            logger.warning(f"Failed to get job history: {error}")
            return [], 0, 0, 0
        self._loading_complete_step(4, f"{total_jobs} jobs in {job_history_days} days")
        return history_jobs, total_jobs, total_requeues, max_requeues

    def _load_step_all_running_jobs(self) -> None:
        """Execute step 5: Fetch all running jobs for user overview."""
        self._loading_update_step(5)
        all_running, error = get_all_running_jobs()
        if error:
            self._loading_fail_step(5, error)
            logger.warning(f"Failed to get all running jobs: {error}")
            all_running = []
        else:
            self._loading_complete_step(5, f"{len(all_running)} jobs")
        self._all_users_jobs = all_running

    def _load_step_energy_history(self) -> None:
        """Execute step 6: Fetch 6-month energy history (only at startup)."""
        self._loading_update_step(6)
        energy_jobs, error = get_all_job_history_6months()
        if error:
            self._loading_fail_step(6, error)
            logger.warning(f"Failed to get 6-month energy history: {error}")
            energy_jobs = []
        else:
            self._loading_complete_step(6, f"{len(energy_jobs)} jobs")
        self._energy_history_jobs = energy_jobs

    def _load_step_statistics(self) -> None:
        """Execute steps 7-8: Calculate user and cluster statistics."""
        self._loading_update_step(7)
        user_stats = UserOverviewTab.aggregate_user_stats(self._all_users_jobs)
        self._loading_complete_step(7, f"{len(user_stats)} users")

        self._loading_update_step(8)
        cluster_stats = self._calculate_cluster_stats()
        self._loading_complete_step(8, f"{cluster_stats.total_nodes} nodes, {cluster_stats.total_gpus} GPUs")

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
        self._log_sink_id = add_tui_sink(log_pane.sink, level=self._settings.log_level)

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

    def _register_custom_themes(self) -> None:
        """Register custom themes for the app."""
        for theme in REGISTERED_THEMES:
            self.register_theme(theme)

    def _apply_theme(self, theme_name: str) -> None:
        """Apply a theme by name.

        Args:
            theme_name: Name of the theme to apply.
        """
        if theme_name not in self.available_themes:
            logger.warning(f"Unknown theme '{theme_name}', falling back to {DEFAULT_THEME_NAME}")
            theme_name = DEFAULT_THEME_NAME
        self.theme = theme_name

    def _apply_log_settings(self) -> None:
        """Apply log settings to the active log sink."""
        if self._log_sink_id is None:
            return
        log_pane = self.query_one("#log_pane", LogPane)
        remove_tui_sink(self._log_sink_id)
        self._log_sink_id = add_tui_sink(log_pane.sink, level=self._settings.log_level)

    def _apply_log_pane_settings(self) -> None:
        """Apply log pane settings."""
        log_pane = self.query_one("#log_pane", LogPane)
        log_pane.max_lines = self._settings.max_log_lines

    def _apply_refresh_interval(self, old_interval: float, new_interval: float) -> None:
        """Apply refresh interval changes by restarting the timer if needed.

        Args:
            old_interval: Previous refresh interval.
            new_interval: New refresh interval.
        """
        if old_interval == new_interval:
            return

        self.refresh_interval = new_interval

        # Restart timer if running
        if self.auto_refresh_timer is not None:
            self.auto_refresh_timer.stop()
            self.auto_refresh_timer = self.set_interval(self.refresh_interval, self._start_refresh_worker)
            logger.info(f"Refresh interval changed from {old_interval}s to {new_interval}s")

    def action_show_settings(self) -> None:
        """Open the settings screen."""
        self.push_screen(SettingsScreen(self._settings), self._handle_settings_updated)

    def _handle_settings_updated(self, settings: Settings | None) -> None:
        """Handle settings updates from the settings screen.

        Args:
            settings: Updated settings or None if canceled.
        """
        if settings is None:
            return
        old_settings = self._settings
        self._settings = settings
        save_settings(settings)
        self._apply_theme(settings.theme)
        self._apply_log_pane_settings()
        self._apply_log_settings()
        self._apply_refresh_interval(old_settings.refresh_interval, settings.refresh_interval)
        self.notify("Settings saved")

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
                running_jobs = None

            # Get history
            job_history_days = self._settings.job_history_days
            history_jobs, total_jobs, total_requeues, max_requeues, h_error = get_job_history(days=job_history_days)
            if h_error:
                logger.warning(f"Failed to refresh job history: {h_error}")
                history_jobs = None
            else:
                # Update cache of raw history data
                self._last_history_jobs = history_jobs
                self._last_history_stats = (total_jobs, total_requeues, max_requeues)

            # Handle partial failures with fallback
            if running_jobs is not None:
                self._handle_refresh_fallback(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)
            else:
                self.call_from_thread(
                    lambda: self.notify("Running jobs refresh failed - keeping old data", severity="warning")
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

    def _handle_refresh_fallback(
        self,
        running_jobs: list[tuple[str, ...]],
        history_jobs: list[tuple[str, ...]] | None,
        total_jobs: int,
        total_requeues: int,
        max_requeues: int,
    ) -> None:
        """Handle refresh logic with fallback for failed history.

        Args:
            running_jobs: List of running jobs tuples.
            history_jobs: List of history jobs tuples (or None if failed).
            total_jobs: Total job count from history.
            total_requeues: Total requeues from history.
            max_requeues: Max requeues from history.
        """
        if history_jobs is None:
            # Reuse last successful history
            history_jobs = list(self._last_history_jobs)
            total_jobs, total_requeues, max_requeues = self._last_history_stats
            self.call_from_thread(
                lambda: self.notify("History refresh failed - using cached history", severity="warning")
            )
        else:
            # Update cache of raw history data on success
            self._last_history_jobs = history_jobs
            self._last_history_stats = (total_jobs, total_requeues, max_requeues)

        self._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)

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

        jobs = self._sorted_jobs_for_display(self._job_cache.jobs)
        desired_job_ids = {job.job_id for job in jobs}

        desired_order = [job.job_id for job in jobs]
        current_order = self._current_jobs_table_order(jobs_table)

        # If order changed (e.g., new/pending job submitted), rebuild to ensure "top of queue" ordering.
        if current_order != desired_order:
            removed_rows = jobs_table.row_count
            rows_changed = self._rebuild_jobs_table(jobs_table, jobs)
        else:
            removed_rows = self._remove_missing_job_rows(jobs_table, desired_job_ids)
            rows_changed = self._upsert_job_rows(jobs_table, jobs)

        cursor_restored = self._restore_jobs_table_cursor(jobs_table, cursor_row, cursor_job_id)
        jobs_table.display = jobs_table.row_count > 0
        if not cursor_restored and jobs_table.row_count == 0:
            jobs_table.cursor_type = "row"

        logger.debug(
            f"Jobs table reconciled: {jobs_table.row_count} rows, {rows_changed} updates, {removed_rows} removals"
        )

    def _sorted_jobs_for_display(self, jobs: list[Job]) -> list[Job]:
        """Sort jobs for stable, user-friendly display.

        Ordering:
        - Active jobs first
        - Pending jobs above running jobs (newly-submitted jobs are usually pending)
        - Newest job IDs first (best-effort by numeric prefix)
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

    def _current_jobs_table_order(self, jobs_table: DataTable) -> list[str]:
        """Return the current job ID order in the table (top to bottom)."""
        job_ids: list[str] = []
        for idx in range(jobs_table.row_count):
            try:
                row = jobs_table.get_row_at(idx)
            except Exception as exc:
                logger.debug(f"Failed to read jobs table row {idx}: {exc}")
                continue
            if not row:
                continue
            job_ids.append(str(row[0]))
        return job_ids

    def _rebuild_jobs_table(self, jobs_table: DataTable, jobs: list[Job]) -> int:
        """Clear and repopulate the jobs table in the provided order."""
        jobs_table.clear(columns=False)
        self._job_row_keys.clear()
        changes = 0
        for job in jobs:
            try:
                new_key = jobs_table.add_row(*self._job_row_values(job))
            except Exception:
                logger.exception(f"Failed to add job {job.job_id} to table")
                continue
            self._job_row_keys[job.job_id] = new_key
            changes += 1
        return changes

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

    def _safe_get_row(self, jobs_table: DataTable, row_key: RowKey) -> list[RenderableType] | None:
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
        existing_values: list[RenderableType],
        job_id: str,
    ) -> bool:
        """Update individual cells that have changed."""
        updated = False
        for idx, (new_value, existing_value) in enumerate(zip(new_values, existing_values, strict=False)):
            # existing_value may be a Text/Renderable, so normalize to string for comparison
            if new_value == str(existing_value):
                continue
            try:
                column_key: ColumnKey | str
                if idx < len(self._job_table_column_keys):
                    column_key = self._job_table_column_keys[idx]
                else:
                    column_key = self.JOB_TABLE_COLUMNS[idx] if idx < len(self.JOB_TABLE_COLUMNS) else str(idx)
                jobs_table.update_cell(row_key, column_key, new_value)
                updated = True
            except Exception:
                column_name = self.JOB_TABLE_COLUMNS[idx] if idx < len(self.JOB_TABLE_COLUMNS) else str(idx)
                logger.exception(f"Failed to update {column_name} for job {job_id}")
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
        colors = get_theme_colors(self)
        state_formats = {
            JobState.RUNNING: f"[bold {colors.success}]{state}[/bold {colors.success}]",
            JobState.PENDING: f"[bold {colors.warning}]{state}[/bold {colors.warning}]",
            JobState.COMPLETED: f"[{colors.success}]{state}[/{colors.success}]",
            JobState.FAILED: f"[bold {colors.error}]{state}[/bold {colors.error}]",
            JobState.CANCELLED: f"[{colors.text_muted}]{state}[/{colors.text_muted}]",
            JobState.TIMEOUT: f"[{colors.error}]{state}[/{colors.error}]",
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

    def _parse_tres_for_pending(self, tres_str: str) -> tuple[int, float, list[tuple[str, int]]]:
        """Parse TRES string to extract CPU, memory (GB), and GPU entries.

        Args:
            tres_str: TRES string in format like "cpu=32,mem=256G,node=4,gres/gpu=16"
                or "cpu=32,mem=256G,node=4,gres/gpu:h200=8".

        Returns:
            Tuple of (cpus, memory_gb, gpu_entries) where gpu_entries is a list of
            (gpu_type, gpu_count) tuples.
        """
        cpus = 0
        memory_gb = 0.0

        if not tres_str or tres_str.strip() == "":
            return cpus, memory_gb, []

        # Parse CPU count
        cpu_match = re.search(r"cpu=(\d+)", tres_str)
        if cpu_match:
            with contextlib.suppress(ValueError):
                cpus = int(cpu_match.group(1))

        # Parse memory (can be in G, M, or T)
        mem_match = re.search(r"mem=(\d+)([GMT])", tres_str, re.IGNORECASE)
        if mem_match:
            try:
                mem_value = int(mem_match.group(1))
                mem_unit = mem_match.group(2).upper()
                if mem_unit == "G":
                    memory_gb = float(mem_value)
                elif mem_unit == "M":
                    memory_gb = mem_value / 1024.0
                elif mem_unit == "T":
                    memory_gb = mem_value * 1024.0
            except ValueError:
                pass

        # Use shared GPU parser
        gpu_entries = parse_gpu_entries(tres_str)

        return cpus, memory_gb, gpu_entries

    def _aggregate_pending_gpus(
        self,
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

    def _calculate_pending_resources(self, stats: ClusterStats) -> None:
        """Calculate resources requested by pending jobs.

        Array jobs (e.g., 12345_[0-99]) are expanded so that resources are
        multiplied by the number of tasks in the array.

        Args:
            stats: ClusterStats object to update with pending resource data.
        """
        # Job tuple indices
        job_id_index, partition_index, state_index, tres_index = 0, 3, 4, 8
        min_fields_for_tres = 9

        pending_cpus, pending_memory_gb, pending_gpus, pending_jobs_count = 0, 0.0, 0, 0
        pending_gpus_by_type: dict[str, int] = {}
        pending_by_partition: dict[str, PendingPartitionStats] = {}

        for job in self._all_users_jobs:
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

            cpus, memory_gb, gpu_entries = self._parse_tres_for_pending(job[tres_index])
            pending_cpus += cpus * array_size
            pending_memory_gb += memory_gb * array_size
            partition_stats.cpus += cpus * array_size
            partition_stats.memory_gb += memory_gb * array_size

            pending_gpus += self._aggregate_pending_gpus(gpu_entries, array_size, pending_gpus_by_type, partition_stats)

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

    def _calculate_cluster_stats(self) -> ClusterStats:
        """Calculate cluster statistics from node data.

        Returns:
            ClusterStats object with aggregated statistics.
        """
        stats = ClusterStats()

        if not self._cluster_nodes:
            logger.debug("No cluster nodes available for stats calculation")
            # Still calculate pending resources even if no cluster nodes
            self._calculate_pending_resources(stats)
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

        # Calculate pending job resources
        self._calculate_pending_resources(stats)

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
        """Update the user overview tab with running, pending, and energy stats."""
        try:
            user_tab = self.query_one("#user-overview", UserOverviewTab)

            # Filter for running jobs only (exclude PENDING/PD for running stats)
            state_index = 4
            running_jobs = [
                j
                for j in self._all_users_jobs
                if len(j) > state_index and j[state_index].strip().upper() not in ("PENDING", "PD")
            ]

            # Running job stats
            user_stats = UserOverviewTab.aggregate_user_stats(running_jobs)
            logger.debug(f"Updating user overview with {len(user_stats)} users from {len(running_jobs)} running jobs")
            user_tab.update_users(user_stats)

            # Pending job stats (includes array expansion)
            pending_stats = UserOverviewTab.aggregate_pending_user_stats(self._all_users_jobs)
            logger.debug(f"Updating pending user stats with {len(pending_stats)} users")
            user_tab.update_pending_users(pending_stats)

            # Energy stats (from 6-month history, loaded once at startup)
            if self._energy_history_jobs:
                energy_stats = UserOverviewTab.aggregate_energy_stats(self._energy_history_jobs)
                job_count = len(self._energy_history_jobs)
                logger.debug(f"Updating energy stats with {len(energy_stats)} users from {job_count} historical jobs")
                user_tab.update_energy_users(energy_stats)
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
                # Ensure the jobs table is refreshed when switching back to it (e.g., after background refreshes)
                self.call_later(self._update_ui_from_cache)
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
        # Check which table is selected
        if event.data_table.id == "nodes_table":
            self._show_node_info_for_row(event.data_table, event.row_key)
        elif event.data_table.id == "users_table":
            self._show_user_info_for_row(event.data_table, event.row_key)
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

    def _show_user_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show user info for a specific row in the users table.

        Args:
            table: The DataTable containing the row.
            row_key: The key of the row to show info for.
        """
        try:
            row_data = table.get_row(row_key)
            username = str(row_data[0]).strip()
            # Remove Rich markup tags if present
            username = re.sub(r"\[.*?\]", "", username).strip()

            if not username:
                logger.warning(f"Could not extract username from row {row_key}")
                self.notify("Could not get username from selected row", severity="error")
                return

            logger.info(f"Showing info for selected user {username}")
            self._show_user_info(username)

        except (IndexError, KeyError):
            logger.exception(f"Could not get username from row {row_key}")
            self.notify("Could not get username from selected row", severity="error")

    def _show_user_info(self, username: str) -> None:
        """Show detailed information for a user.

        Args:
            username: The username to display.
        """
        logger.info(f"Fetching user info for {username}")
        self.notify("Loading user information...", timeout=2)

        # Get user info in a worker to avoid blocking
        def fetch_user_info() -> None:
            jobs, error = get_user_jobs(username)
            if error:
                self.call_from_thread(lambda: self._display_user_info(username, "", error))
                return

            # Aggregate user stats from the jobs
            # Build a job list in the format expected by aggregate_user_stats
            # Jobs from get_user_jobs: (JobID, Name, Partition, State, Time, Nodes, NodeList, TRES)
            # aggregate_user_stats expects: (JobID, Name, User, Partition, State, Time, Nodes, NodeList, TRES)
            min_user_job_fields = 8  # Minimum fields from get_user_jobs
            formatted_jobs: list[tuple[str, ...]] = []
            for job in jobs:
                if len(job) >= min_user_job_fields:
                    # Insert username at position 2
                    formatted_job = (job[0], job[1], username, job[2], job[3], job[4], job[5], job[6], job[7])
                    formatted_jobs.append(formatted_job)

            user_stats_list = UserOverviewTab.aggregate_user_stats(formatted_jobs)

            # Find stats for this user
            user_stats: UserStats | None = None
            for stats in user_stats_list:
                if stats.username == username:
                    user_stats = stats
                    break

            if user_stats is None:
                # Create default stats if no jobs
                user_stats = UserStats(
                    username=username,
                    job_count=0,
                    total_cpus=0,
                    total_memory_gb=0.0,
                    total_gpus=0,
                    total_nodes=0,
                    gpu_types="",
                )

            formatted_info = format_user_info(username, user_stats, jobs)
            self.call_from_thread(lambda: self._display_user_info(username, formatted_info, None))

        self.run_worker(fetch_user_info, name="fetch_user_info", thread=True)

    def _display_user_info(self, username: str, user_info: str, error: str | None) -> None:
        """Display user information in a modal screen.

        Args:
            username: The username.
            user_info: Formatted user information.
            error: Optional error message.
        """
        self.push_screen(UserInfoScreen(username, user_info, error))
        logger.debug(f"Displayed user info screen for {username}")

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
