"""Main Textual TUI application for stoei."""

import contextlib
import re
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import ClassVar, TypeAlias, cast

from textual._path import CSSPathType
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.message import Message
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Static
from textual.widgets.data_table import RowKey
from textual.worker import Worker, WorkerState, get_current_worker

from stoei.cluster_stats import (
    ClusterStats,
    PendingPartitionStats,
    aggregate_pending_gpus,
    calculate_cluster_stats,
    calculate_pending_resources,
    parse_gpus_from_gres,
    parse_node_cpus,
    parse_node_memory,
    parse_node_state,
    process_gpu_entries_for_stats,
)
from stoei.colors import get_theme_colors
from stoei.detail_controller import DetailController
from stoei.keybindings import Actions, KeybindingConfig
from stoei.logger import add_tui_sink, get_logger, remove_tui_sink
from stoei.settings import (
    MAX_SIDEBAR_WIDTH_PERCENT,
    MIN_SIDEBAR_WIDTH_PERCENT,
    Settings,
    load_settings,
    save_settings,
)
from stoei.slurm.array_parser import normalize_array_job_id
from stoei.slurm.cache import Job, JobCache, JobState
from stoei.slurm.commands import (
    cancel_job,
    get_all_running_jobs,
    get_cluster_nodes,
    get_energy_job_history,
    get_fair_share_priority,
    get_job_history,
    get_job_info_and_log_paths,
    get_pending_job_priority,
    get_running_jobs,
    get_wait_time_job_history,
)
from stoei.slurm.formatters import format_compact_timeline
from stoei.slurm.gpu_parser import (
    aggregate_gpu_counts,
    calculate_total_gpus,
    format_gpu_types,
    parse_gpu_entries,
    parse_gpu_from_gres,
)
from stoei.slurm.parser import parse_sprio_output, parse_sshare_output
from stoei.slurm.validation import check_slurm_available, get_current_username
from stoei.themes import DEFAULT_THEME_NAME, REGISTERED_THEMES
from stoei.widgets.cluster_sidebar import ClusterSidebar
from stoei.widgets.filterable_table import ColumnConfig, FilterableDataTable
from stoei.widgets.help_screen import HelpScreen
from stoei.widgets.loading_indicator import LoadingIndicator
from stoei.widgets.loading_screen import LoadingScreen, LoadingStep
from stoei.widgets.log_pane import LogPane
from stoei.widgets.node_overview import NodeInfo, NodeOverviewTab
from stoei.widgets.priority_overview import (
    AccountPriority,
    JobPriority,
    PrebuiltPriorityData,
    PriorityOverviewTab,
    UserPriority,
    build_account_priority_rows,
    build_job_priority_rows,
    build_my_job_priority_rows,
    build_my_priority_summary,
    build_user_priority_rows,
)
from stoei.widgets.screens import (
    CancelConfirmScreen,
)
from stoei.widgets.settings_screen import SettingsScreen
from stoei.widgets.slurm_error_screen import SlurmUnavailableScreen
from stoei.widgets.tabs import TabContainer, TabName, TabSwitched
from stoei.widgets.user_overview import (
    UserEnergyStats,
    UserOverviewTab,
    UserPendingStats,
    UserStats,
)

logger = get_logger(__name__)

# Type aliases for fetch result types used in _apply_fetch_result.
_HistoryResult: TypeAlias = tuple[list[tuple[str, ...]] | None, int, int, int]
_PriorityHalfResult: TypeAlias = tuple[list[tuple[str, ...]], str | None]
_EnergyResult: TypeAlias = tuple[list[tuple[str, ...]], bool]
_FetchResult: TypeAlias = (
    _HistoryResult | list[dict[str, str]] | list[tuple[str, ...]] | _PriorityHalfResult | _EnergyResult
)

# The heavy data loop (history, nodes, all-users jobs, wait times, priority) refreshes
# at this multiple of the base refresh interval. Slow sacct/sshare/sprio calls then never
# gate the fast running-jobs loop that drives the jobs-table "Time" column.
HEAVY_REFRESH_MULTIPLIER = 4

# Path to styles directory
STYLES_DIR = Path(__file__).parent / "styles"

# Number of independent priority fetch futures (fair_share + job_priority).
# The priority tab is updated once both halves have arrived in the same cycle.
_PRIORITY_FETCH_COUNT = 2

# Minimum window width to show sidebar (sidebar is 30 wide, need space for content)
MIN_WIDTH_FOR_SIDEBAR = 100

# Loading steps for initial data load
LOADING_STEPS = [
    LoadingStep("slurm_check", "Checking SLURM availability...", weight=0.5),
    LoadingStep("user_jobs", "Fetching your jobs...", weight=3.0),
    LoadingStep("finalize", "Building job table...", weight=0.5),
]


class _UICallback(Message, bubble=False):
    """Non-blocking callback message posted from worker threads."""

    def __init__(self, callback: Callable[[], object]) -> None:
        super().__init__()
        self.callback = callback


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
        # Essential bindings (shown in footer)
        Binding("question_mark", "show_help", "Help", show=True, priority=True),
        Binding("h", "show_help", "Help", show=False),  # Alternative help key
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("s", "show_settings", "Settings", show=True),
        # Contextual bindings (hidden from footer, discoverable via ?)
        Binding("i", "show_job_info", "Job Info", show=False),
        Binding("enter", "show_selected_job_info", "View Selected Job", show=False),
        Binding("c", "cancel_job", "Cancel Job", show=False),
        # Tab navigation (hidden - use arrow keys or numbers)
        Binding("1", "switch_tab_jobs", "Jobs Tab", show=False),
        Binding("2", "switch_tab_nodes", "Nodes Tab", show=False),
        Binding("3", "switch_tab_users", "Users Tab", show=False),
        Binding("4", "switch_tab_priority", "Priority Tab", show=False),
        Binding("5", "switch_tab_logs", "Logs Tab", show=False),
        Binding("left", "previous_tab", "Previous Tab", show=False),
        Binding("right", "next_tab", "Next Tab", show=False),
        Binding("shift+tab", "previous_tab", "Previous Tab", show=False),
        # Column width controls
        Binding("]", "column_select_next", "Select Next Column", show=False),
        Binding("[", "column_select_prev", "Select Previous Column", show=False),
        Binding("plus", "column_grow", "Increase Column Width", show=False),
        Binding("minus", "column_shrink", "Decrease Column Width", show=False),
        Binding("0", "column_reset", "Reset Column Width", show=False),
        # Sidebar controls
        Binding("}", "sidebar_grow", "Grow Sidebar", show=False),
        Binding("{", "sidebar_shrink", "Shrink Sidebar", show=False),
    ]
    JOB_TABLE_COLUMNS: ClassVar[tuple[str, ...]] = ("JobID", "Name", "State", "Time", "Nodes", "NodeList", "Timeline")
    JOB_TABLE_COLUMN_CONFIGS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="JobID", key="jobid", sortable=True, filterable=True, width=20),
        ColumnConfig(name="Name", key="name", sortable=True, filterable=True, width=30),  # Wider to fix truncation
        ColumnConfig(name="State", key="state", sortable=True, filterable=True, width=12),
        ColumnConfig(name="Time", key="time", sortable=True, filterable=True, width=12),
        ColumnConfig(name="Nodes", key="nodes", sortable=True, filterable=True, width=8),
        ColumnConfig(name="NodeList", key="nodelist", sortable=True, filterable=True, width=20),
        ColumnConfig(name="Timeline", key="timeline", sortable=False, filterable=True),  # Auto width
    ]

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Provide default values for custom theme variables."""
        return {**super().get_theme_variable_defaults(), **self.THEME_VARIABLE_DEFAULTS}

    def __init__(self) -> None:
        """Initialize the SLURM monitor app."""
        self._settings: Settings = load_settings()
        super().__init__()
        self._register_custom_themes()
        self._apply_theme(self._settings.theme)
        self._init_refresh_state()
        self._initial_load_complete: bool = False
        self._current_username: str = get_current_username()
        self._log_sink_id: int | None = None
        self._cluster_nodes: list[dict[str, str]] = []
        self._all_users_jobs: list[tuple[str, ...]] = []
        self._energy_history_jobs: list[tuple[str, ...]] = []  # Energy history (loaded once at startup if enabled)
        self._energy_data_loaded: bool = False  # Track if energy data was loaded
        self._wait_time_jobs: list[tuple[str, ...]] = []  # Wait time history for cluster sidebar
        self._fair_share_entries: list[tuple[str, ...]] = []  # Fair-share priority data from sshare
        self._job_priority_entries: list[tuple[str, ...]] = []  # Pending job priority data from sprio
        self._is_narrow: bool = False
        self._loading_screen: LoadingScreen | None = None
        self._keybindings: KeybindingConfig = self._settings.get_keybindings()
        # Tracks whether the first background refresh cycle (which loads non-critical
        # data like nodes, all-users jobs, energy, etc.) has completed.
        self._initial_background_complete: bool = False
        # Job info cache: keyed by job_id, stores (formatted_info, error, stdout_path, stderr_path)
        # Cleared on each refresh cycle so stale data doesn't persist
        self._job_info_cache: dict[str, tuple[str, str | None, str | None, str | None]] = {}
        # Pre-computed data (computed in background worker to avoid UI blocking)
        self._cached_node_infos: list[NodeInfo] = []
        self._cached_cluster_stats: ClusterStats | None = None
        self._cached_running_user_stats: list[UserStats] = []
        self._cached_pending_user_stats: list[UserPendingStats] = []
        self._cached_energy_user_stats: list[UserEnergyStats] = []
        self._cached_user_priorities: list[UserPriority] = []
        self._cached_account_priorities: list[AccountPriority] = []
        self._cached_job_priorities: list[JobPriority] = []
        self._cached_user_priority_rows: list[tuple[str, ...]] = []
        self._cached_account_priority_rows: list[tuple[str, ...]] = []
        self._cached_job_priority_rows: list[tuple[str, ...]] = []
        self._cached_my_job_priority_rows: list[tuple[str, ...]] = []
        self._cached_priority_summary_markup: str = ""
        # Pre-computed job rows from worker thread for fast initial UI population
        self._precomputed_job_rows: list[tuple[str, ...]] = []
        # Dirty flags: True when data has changed but the tab's table hasn't been refreshed
        self._dirty_nodes_tab: bool = False
        self._dirty_users_tab: bool = False
        self._dirty_priority_tab: bool = False
        # Counts how many of the two priority halves (fair_share + job_priority)
        # have arrived so far in the current refresh cycle.  When both arrive the
        # priority tab is recomputed and updated once, avoiding double renders.
        self._priority_halves_received: int = 0
        # Error deduplication: tracks which error types have already been notified
        # so repeated refresh failures don't spam the user with the same message.
        self._error_notified: dict[str, bool] = {}
        # Tab switch debouncing: rapid key presses within the same event-loop
        # frame are batched so only the final tab is actually switched to.
        self._pending_tab_switch: TabName | None = None
        self._tab_switch_scheduled: bool = False
        self._init_update_generation_counters()
        # Collaborator owning the job/node/user/account detail-modal flows.
        self._detail: DetailController = DetailController(self)

    def _init_refresh_state(self) -> None:
        """Initialise the data-refresh state: timers, workers, cache, and snapshots.

        The app runs two refresh loops: a fast running-jobs loop (squeue, drives
        the jobs-table "Time" column) and a slow heavy loop (history, nodes,
        priority, ...). Each loop rebuilds the shared job cache from its own fresh
        data plus the other loop's last-known snapshot, serialized by a lock.
        """
        self.refresh_interval: float = self._settings.refresh_interval
        self.auto_refresh_timer: Timer | None = None
        self.heavy_refresh_timer: Timer | None = None
        self._job_cache: JobCache = JobCache()
        self._refresh_worker: Worker[None] | None = None
        self._running_refresh_worker: Worker[None] | None = None
        # Serializes job-cache rebuilds between the fast running-jobs loop and the
        # slow history loop so their _build_from_data calls never interleave.
        self._refresh_state_lock = Lock()
        self._last_running_jobs: list[tuple[str, ...]] = []
        self._last_history_jobs: list[tuple[str, ...]] = []
        self._last_history_stats: tuple[int, int, int] = (0, 0, 0)

    def _init_update_generation_counters(self) -> None:
        """Initialise generation counters for deferred UI updates.

        Each deferred callback captures the counter at schedule time.
        If a newer update arrives before the callback runs (e.g. after
        returning from another tmux tab), the stale callback is skipped.
        """
        self._jobs_update_gen: int = 0
        self._nodes_update_gen: int = 0
        self._users_update_gen: int = 0
        self._priority_update_gen: int = 0
        self._energy_update_gen: int = 0

    @property
    def keybindings(self) -> KeybindingConfig:
        """Get the current keybinding configuration."""
        return self._keybindings

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
                        yield Static("[bold]My Jobs[/bold]", id="jobs-title")
                    yield Static("My Usage: No running jobs", id="my-usage-summary")
                    yield FilterableDataTable(
                        columns=self.JOB_TABLE_COLUMN_CONFIGS,
                        keybind_mode=self._settings.keybind_mode,
                        keybindings=self._keybindings,
                        table_id="jobs_table",
                        id="jobs-filterable-table",
                    )

                # Nodes tab
                with Container(id="tab-nodes-content", classes="tab-content"):
                    yield NodeOverviewTab(id="node-overview")

                # Users tab
                with Container(id="tab-users-content", classes="tab-content"):
                    yield UserOverviewTab(id="user-overview")

                # Priority tab
                with Container(id="tab-priority-content", classes="tab-content"):
                    yield PriorityOverviewTab(current_username=self._current_username, id="priority-overview")

                # Logs tab
                with Container(id="tab-logs-content", classes="tab-content"):
                    yield LogPane(id="log_pane", max_lines=self._settings.max_log_lines)

            # Sidebar with cluster load (on the right)
            yield ClusterSidebar(id="cluster-sidebar")

        yield Footer()

    def on__uicallback(self, message: _UICallback) -> None:
        """Execute a callback posted from a worker thread."""
        message.callback()

    def _post_ui_callback(self, callback: Callable[[], object]) -> None:
        """Schedule *callback* on the main thread without blocking the caller.

        Unlike ``call_from_thread``, this does not wait for the callback to
        complete, so worker threads never stall on a slow or blocked event
        loop (e.g. when terminal I/O is congested over SSH).
        """
        self.post_message(_UICallback(callback))

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
            priority_tab = self.query_one("#tab-priority-content", Container)
            priority_tab.display = False
            logs_tab = self.query_one("#tab-logs-content", Container)
            logs_tab.display = False
        except Exception as exc:
            logger.warning(f"Failed to set tab visibility: {exc}")

        # Jobs table is now set up by FilterableDataTable
        logger.debug("Jobs table ready for data")

        # Apply initial sidebar width from settings
        self._apply_sidebar_width()

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
            group="data_load",
            exclusive=True,
            thread=True,
        )

    def _loading_update_step(self, idx: int) -> None:
        """Update loading screen to show step starting."""
        screen = self._loading_screen
        if screen:
            self._post_ui_callback(lambda: screen.start_step(idx))

    def _loading_complete_step(self, idx: int, msg: str | None = None) -> None:
        """Update loading screen to show step completed."""
        screen = self._loading_screen
        if screen:
            self._post_ui_callback(lambda: screen.complete_step(idx, msg))

    def _loading_fail_step(self, idx: int, error: str) -> None:
        """Update loading screen to show step failed."""
        screen = self._loading_screen
        if screen:
            self._post_ui_callback(lambda: screen.fail_step(idx, error))

    def _loading_skip_step(self, idx: int, reason: str) -> None:
        """Update loading screen to show step skipped."""
        screen = self._loading_screen
        if screen:
            self._post_ui_callback(lambda: screen.skip_step(idx, reason))

    def _initial_load_async(self) -> None:
        """Perform initial data load with step-by-step progress (runs in worker thread)."""
        logger.info("Starting initial data load")

        # Execute loading steps and collect results
        load_result = self._execute_loading_steps()
        if load_result is None:
            return  # SLURM error, already handled

        running_jobs, history_jobs, total_jobs, total_requeues, max_requeues = load_result

        # Save initial snapshots so each refresh loop can rebuild the table from
        # the other loop's last-known data without re-fetching it.
        self._last_running_jobs = running_jobs
        self._last_history_jobs = history_jobs
        self._last_history_stats = (total_jobs, total_requeues, max_requeues)

        # Build job cache from fetched data
        self._loading_update_step(2)
        self._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)

        # Pre-compute row tuples in the worker thread so the main thread
        # only needs to push them into the DataTable (the unavoidable DOM work).
        jobs = self._sorted_jobs_for_display(self._job_cache.jobs)
        self._precomputed_job_rows = [tuple(self._job_row_values(job)) for job in jobs]

        self._loading_complete_step(2, "Ready")

        # Transition to main UI — the loading screen stays up until the
        # first background refresh (cluster data) completes.
        self._post_ui_callback(self._finish_initial_load)

    def _execute_loading_steps(
        self,
    ) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], int, int, int] | None:
        """Execute critical loading steps and return collected data.

        Only loads the minimum data needed for the jobs table (SLURM check,
        running jobs, job history). All other data sources (cluster nodes,
        all-users jobs, energy, wait times, priority) are loaded in the
        background after the UI is shown.

        Returns:
            Tuple of (running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)
            or None if SLURM is not available.
        """
        # Step 0: Check SLURM availability
        if not self._load_step_check_slurm():
            return None

        # Step 1: Fetch running jobs + job history in parallel (no retries)
        running_jobs, history_jobs, total_jobs, total_requeues, max_requeues = self._load_step_user_jobs()

        return running_jobs, history_jobs, total_jobs, total_requeues, max_requeues

    def _load_step_check_slurm(self) -> bool:
        """Execute step 0: Check SLURM availability."""
        self._loading_update_step(0)
        is_available, error_msg = check_slurm_available()
        if not is_available:
            self._loading_fail_step(0, error_msg or "SLURM not available")
            logger.error(f"SLURM not available: {error_msg}")
            self._post_ui_callback(self._show_slurm_error)
            return False
        self._loading_complete_step(0, "SLURM available")
        return True

    def _load_step_user_jobs(
        self,
    ) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], int, int, int]:
        """Execute step 1: Fetch running jobs and job history in parallel (no retries)."""
        self._loading_update_step(1)
        job_history_days = self._settings.job_history_days

        running_jobs: list[tuple[str, ...]] = []
        history_jobs: list[tuple[str, ...]] = []
        total_jobs = 0
        total_requeues = 0
        max_requeues = 0
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_running = executor.submit(get_running_jobs, max_retries=0)
            future_history = executor.submit(get_job_history, days=job_history_days, max_retries=0)

            rj, rj_error = future_running.result()
            if rj_error:
                logger.warning(f"Failed to get running jobs: {rj_error}")
                errors.append(rj_error)
            else:
                running_jobs = rj

            hj, tj, tr, mr, hj_error = future_history.result()
            if hj_error:
                logger.warning(f"Failed to get job history: {hj_error}")
                errors.append(hj_error)
            else:
                history_jobs = hj
                total_jobs = tj
                total_requeues = tr
                max_requeues = mr

        if errors:
            self._loading_fail_step(1, "; ".join(errors))
        else:
            self._loading_complete_step(1, f"{len(running_jobs)} running/pending, {total_jobs} in {job_history_days}d")

        return running_jobs, history_jobs, total_jobs, total_requeues, max_requeues

    def _show_slurm_error(self) -> None:
        """Show SLURM unavailable error screen."""
        if self._loading_screen:
            with contextlib.suppress(Exception):
                self.pop_screen()
        self.push_screen(SlurmUnavailableScreen())

    def _finish_initial_load(self) -> None:
        """Populate the jobs table, dismiss the loading screen, and start background data loading.

        The jobs table is shown immediately. Cluster data (nodes, users,
        priority, etc.) loads asynchronously with a loading indicator visible
        in the UI. Tabs are usable right away — tabs without data yet show
        empty tables until the background refresh completes.
        """
        # Set up log pane as a loguru sink
        try:
            log_pane = self.query_one("#log_pane", LogPane)
            self._log_sink_id = add_tui_sink(log_pane.sink, level=self._settings.log_level)
        except Exception:
            logger.debug("LogPane not mounted yet, skipping sink setup")

        logger.info("Initial load complete, populating UI")

        # Use pre-computed rows from worker thread — avoids sorting and
        # tuple creation on the main thread.
        try:
            jobs_filterable = self.query_one("#jobs-filterable-table", FilterableDataTable)
            rows = self._precomputed_job_rows
            self._precomputed_job_rows = []  # Free memory
            jobs_filterable._all_rows = rows
            table = jobs_filterable.table
            table.clear(columns=False)
            table.add_rows(rows)
            jobs_filterable.display = len(rows) > 0
            logger.debug(f"Jobs table populated: {len(rows)} jobs")
            self._apply_saved_column_widths("jobs", jobs_filterable)
        except Exception as exc:
            logger.debug(f"Failed to populate jobs table: {exc}")

        # Dismiss loading screen — jobs are ready
        if self._loading_screen:
            with contextlib.suppress(Exception):
                self.pop_screen()
            self._loading_screen = None

        # Allow tab switching immediately
        self._initial_load_complete = True

        # Focus the jobs table
        try:
            jobs_table = self.query_one("#jobs_table", DataTable)
            jobs_table.focus()
        except Exception as exc:
            logger.warning(f"Failed to focus jobs table: {exc}")

        self._check_window_size()

        # Show loading indicator while cluster data loads in background
        self._set_loading_indicator(True)
        self.notify("Loading cluster data...", timeout=3, severity="information")

        # Clear the initial-load worker reference so _start_refresh_worker
        # doesn't skip because it still sees the (finishing) initial worker.
        self._refresh_worker = None

        # Start the fast running-jobs loop now so the jobs-table "Time" column
        # advances every refresh_interval, independent of the slow heavy load.
        self.auto_refresh_timer = self.set_interval(self.refresh_interval, self._start_running_refresh_worker)

        # Kick off the first heavy background load (nodes, all-users jobs, energy,
        # wait times, priority, history). Its recurring timer starts once it
        # completes, in _on_refresh_complete.
        logger.info("Starting background load for cluster data sources")
        self._start_refresh_worker()

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
        try:
            log_pane = self.query_one("#log_pane", LogPane)
        except Exception:
            return
        remove_tui_sink(self._log_sink_id)
        self._log_sink_id = add_tui_sink(log_pane.sink, level=self._settings.log_level)

    def _apply_log_pane_settings(self) -> None:
        """Apply log pane settings."""
        try:
            log_pane = self.query_one("#log_pane", LogPane)
        except Exception:
            return
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

        # Restart both loops' timers if running so the new interval takes effect.
        if self.auto_refresh_timer is not None:
            self.auto_refresh_timer.stop()
            self.auto_refresh_timer = self.set_interval(self.refresh_interval, self._start_running_refresh_worker)
        if self.heavy_refresh_timer is not None:
            self.heavy_refresh_timer.stop()
            self.heavy_refresh_timer = self.set_interval(self.heavy_refresh_interval, self._start_refresh_worker)
        logger.info(f"Refresh interval changed from {old_interval}s to {new_interval}s")

    def _apply_keybind_mode(self, settings: Settings) -> None:
        """Apply keybind mode to all filterable tables.

        Args:
            settings: The current settings containing keybind mode and overrides.
        """
        # Update app-level keybindings
        self._keybindings = settings.get_keybindings()

        try:
            for table in self.query(FilterableDataTable):
                table.set_keybind_mode(settings.keybind_mode, self._keybindings)
            logger.debug(f"Applied keybind mode: {settings.keybind_mode}")
        except Exception as exc:
            logger.debug(f"Failed to apply keybind mode: {exc}")

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
        self.run_worker(lambda s=settings: save_settings(s), thread=True, exclusive=True, group="save_settings")
        self._apply_theme(settings.theme)
        self._apply_log_pane_settings()
        self._apply_log_settings()
        self._apply_refresh_interval(old_settings.refresh_interval, settings.refresh_interval)
        self._apply_keybind_mode(settings)
        self.notify("Settings saved")

    # Column width action methods
    def _get_current_filterable_table(self) -> FilterableDataTable | None:
        """Get the FilterableDataTable for the current tab."""
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            active_tab = tab_container.active_tab
            if active_tab == "jobs":
                return self.query_one("#jobs-filterable-table", FilterableDataTable)
        except Exception as exc:
            logger.debug(f"Failed to get current filterable table: {exc}")
        return None

    def action_column_select_next(self) -> None:
        """Select the next column for resizing."""
        table = self._get_current_filterable_table()
        if table:
            table.select_next_column()
            col_key = table.get_selected_column_key()
            if col_key:
                self.notify(f"Column: {col_key}", timeout=1)

    def action_column_select_prev(self) -> None:
        """Select the previous column for resizing."""
        table = self._get_current_filterable_table()
        if table:
            table.select_previous_column()
            col_key = table.get_selected_column_key()
            if col_key:
                self.notify(f"Column: {col_key}", timeout=1)

    def action_column_grow(self) -> None:
        """Increase the selected column width."""
        table = self._get_current_filterable_table()
        if table and table.resize_selected_column(2):
            self._save_column_widths()

    def action_column_shrink(self) -> None:
        """Decrease the selected column width."""
        table = self._get_current_filterable_table()
        if table and table.resize_selected_column(-2):
            self._save_column_widths()

    def action_column_reset(self) -> None:
        """Reset the selected column to its default width."""
        table = self._get_current_filterable_table()
        if table and table.reset_selected_column_width():
            self._save_column_widths()
            self.notify("Column width reset", timeout=1)

    def _calculate_sidebar_width(self) -> int:
        """Calculate sidebar width based on percentage setting and terminal width.

        Returns:
            Width in characters, clamped to reasonable bounds.
        """
        terminal_width = self.size.width
        percent = self._settings.sidebar_width_percent
        calculated_width = int(terminal_width * percent / 100)
        # Clamp to sidebar min/max
        return max(ClusterSidebar.MIN_WIDTH, min(ClusterSidebar.MAX_WIDTH, calculated_width))

    def _apply_sidebar_width(self) -> None:
        """Apply the current sidebar width setting."""
        try:
            sidebar = self.query_one("#cluster-sidebar", ClusterSidebar)
            width = self._calculate_sidebar_width()
            sidebar.set_width(width)
        except Exception as exc:
            logger.debug(f"Failed to apply sidebar width: {exc}")

    def action_sidebar_grow(self) -> None:
        """Increase sidebar width by 5%."""
        current_percent = self._settings.sidebar_width_percent
        new_percent = min(MAX_SIDEBAR_WIDTH_PERCENT, current_percent + 5)
        if new_percent != current_percent:
            self._settings = replace(self._settings, sidebar_width_percent=new_percent)
            self.run_worker(lambda: save_settings(self._settings), thread=True, exclusive=True, group="save_settings")
            self._apply_sidebar_width()
            self.notify(f"Sidebar: {new_percent}%", timeout=1)

    def action_sidebar_shrink(self) -> None:
        """Decrease sidebar width by 5%."""
        current_percent = self._settings.sidebar_width_percent
        new_percent = max(MIN_SIDEBAR_WIDTH_PERCENT, current_percent - 5)
        if new_percent != current_percent:
            self._settings = replace(self._settings, sidebar_width_percent=new_percent)
            self.run_worker(lambda: save_settings(self._settings), thread=True, exclusive=True, group="save_settings")
            self._apply_sidebar_width()
            self.notify(f"Sidebar: {new_percent}%", timeout=1)

    def _save_column_widths(self) -> None:
        """Persist current column widths to settings."""
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            active_tab = tab_container.active_tab

            table = self._get_current_filterable_table()
            if not table:
                return

            widths = table.get_column_widths()
            if not widths:
                return

            # Convert existing column_widths to a mutable dict
            existing_widths = dict(self._settings.column_widths)
            existing_widths[active_tab] = tuple(widths.items())

            # Create new settings with updated column_widths using replace()
            self._settings = replace(self._settings, column_widths=tuple(existing_widths.items()))
            self.run_worker(lambda: save_settings(self._settings), thread=True, exclusive=True, group="save_settings")
            logger.debug(f"Saved column widths for {active_tab}: {widths}")

        except Exception as exc:
            logger.warning(f"Failed to save column widths: {exc}")

    def _apply_saved_column_widths(self, table_name: str, table: FilterableDataTable | None = None) -> None:
        """Apply saved column widths from settings to a table.

        Args:
            table_name: The name of the table (e.g., "jobs").
            table: Optional FilterableDataTable to apply widths to. If None, uses current table.
        """
        try:
            saved_widths = dict(self._settings.column_widths)
            if table_name not in saved_widths:
                return

            widths = dict(saved_widths[table_name])
            if not widths:
                return

            target_table = table if table is not None else self._get_current_filterable_table()
            if target_table:
                target_table.set_column_widths(widths)
                logger.debug(f"Applied saved column widths for {table_name}: {widths}")

        except Exception as exc:
            logger.warning(f"Failed to apply saved column widths for {table_name}: {exc}")

    @property
    def heavy_refresh_interval(self) -> float:
        """Interval (seconds) for the heavy data loop (history, nodes, priority, ...)."""
        return self.refresh_interval * HEAVY_REFRESH_MULTIPLIER

    def _start_refresh_worker(self) -> None:
        """Start the heavy background worker (history, nodes, all-users jobs, priority)."""
        if self._refresh_worker is not None and self._refresh_worker.state == WorkerState.RUNNING:
            logger.debug("Heavy refresh worker already running, skipping")
            return

        self._refresh_worker = self.run_worker(
            self._refresh_data_async,
            name="refresh_data",
            group="data_load",
            exclusive=True,
            thread=True,
        )

    def _start_running_refresh_worker(self) -> None:
        """Start the fast worker that refreshes running jobs (drives the jobs-table Time column).

        This loop fetches ``squeue`` only, so it is never gated by the slow
        ``sacct``/``sshare``/``sprio`` calls in the heavy loop.
        """
        if self._running_refresh_worker is not None and self._running_refresh_worker.state == WorkerState.RUNNING:
            logger.debug("Running-jobs refresh worker already running, skipping")
            return

        self._running_refresh_worker = self.run_worker(
            self._refresh_running_jobs_async,
            name="refresh_running_jobs",
            group="running_refresh",
            exclusive=True,
            thread=True,
        )

    def _refresh_running_jobs_async(self) -> None:
        """Fetch running jobs (squeue only) and refresh the jobs table (worker thread)."""
        worker = get_current_worker()
        running_jobs, error = get_running_jobs(max_retries=1)
        if worker.is_cancelled:
            return
        if error:
            logger.warning(f"Failed to refresh running jobs: {error}")
            self._apply_running_jobs_result(None)
        else:
            self._apply_running_jobs_result(running_jobs)

    def _apply_running_jobs_result(self, running_jobs: list[tuple[str, ...]] | None) -> None:
        """Rebuild the jobs table from fresh running jobs + cached history (worker thread).

        On a fetch failure (``running_jobs is None``) the previous table is kept
        and the user is notified once. On success the running-jobs snapshot is
        updated and the table is rebuilt against the last-known history snapshot,
        so the "Time" column advances without waiting on the heavy history loop.

        Args:
            running_jobs: Fresh squeue job tuples, or None if the fetch failed.
        """
        if running_jobs is None:
            if not self._error_notified.get("running_jobs"):
                self._error_notified["running_jobs"] = True
                self._post_ui_callback(
                    lambda: self.notify("Running jobs refresh failed - keeping old data", severity="warning")
                )
            return

        self._error_notified["running_jobs"] = False
        with self._refresh_state_lock:
            self._last_running_jobs = running_jobs
            old_states = self._job_states()
            total_jobs, total_requeues, max_requeues = self._last_history_stats
            self._job_cache._build_from_data(
                running_jobs, self._last_history_jobs, total_jobs, total_requeues, max_requeues
            )
            self._notify_new_jobs(set(old_states))
            self._invalidate_changed_job_info(old_states)
            job_rows = self._current_job_rows()
        self._post_ui_callback(lambda: self._update_jobs_table(job_rows))

    def _current_job_rows(self) -> list[tuple[str, ...]]:
        """Snapshot the cached jobs as display-ready table rows."""
        return [tuple(self._job_row_values(job)) for job in self._sorted_jobs_for_display(self._job_cache.jobs)]

    # --- Parallel fetch helpers (run inside ThreadPoolExecutor threads) ---

    def _fetch_history(self) -> _HistoryResult:
        """Fetch the user's job history (sacct) for the heavy refresh loop.

        Returns:
            Tuple of (history_jobs, total_jobs, total_requeues, max_requeues).
            ``history_jobs`` is None if the fetch failed.
        """
        history_raw, total_jobs, total_requeues, max_requeues, h_error = get_job_history(
            days=self._settings.job_history_days
        )
        if h_error:
            logger.warning(f"Failed to refresh job history: {h_error}")
            return None, 0, 0, 0
        return history_raw, total_jobs, total_requeues, max_requeues

    def _fetch_nodes(self) -> list[dict[str, str]]:
        """Fetch cluster node data.

        Returns:
            List of node data dicts, empty on error.
        """
        nodes, error = get_cluster_nodes()
        if error:
            logger.warning(f"Failed to get cluster nodes: {error}")
            return []
        logger.debug(f"Fetched {len(nodes)} cluster nodes")
        return nodes

    def _fetch_all_jobs(self) -> list[tuple[str, ...]]:
        """Fetch all-users running job data.

        Returns:
            List of job tuples, empty on error.
        """
        all_jobs, error = get_all_running_jobs()
        if error:
            logger.warning(f"Failed to get all running jobs: {error}")
            return []
        logger.debug(f"Fetched {len(all_jobs)} running jobs from all users")
        return all_jobs

    def _fetch_wait_time(self) -> list[tuple[str, ...]]:
        """Fetch wait-time history.

        Returns:
            List of wait-time job tuples, empty on error.
        """
        wait_time_jobs, error = get_wait_time_job_history(hours=1)
        if error:
            logger.warning(f"Failed to get wait time history: {error}")
            return []
        logger.debug(f"Fetched {len(wait_time_jobs)} jobs for wait time calculation")
        return wait_time_jobs

    def _fetch_energy(self) -> tuple[list[tuple[str, ...]], bool]:
        """Fetch energy history data (only used during first background cycle).

        Returns:
            Tuple of (energy_jobs, energy_loaded).
        """
        if not self._settings.energy_loading_enabled:
            logger.debug("Energy loading disabled, skipping")
            return [], False

        months = self._settings.energy_history_months
        energy_jobs, error = get_energy_job_history(months)
        if error:
            logger.warning(f"Failed to get {months}-month energy history: {error}")
            return [], False
        logger.debug(f"Fetched {len(energy_jobs)} energy history jobs")
        return energy_jobs, True

    # --- Main refresh worker ---

    def _refresh_data_async(self) -> None:
        """Parallel refresh of SLURM data (runs in background worker thread).

        Fetches all data sources concurrently. Each fetch result is processed
        and pushed to the UI as soon as it arrives (progressive rendering),
        so widgets update incrementally rather than waiting for all fetches.
        """
        is_first_cycle = not self._initial_background_complete
        logger.debug(f"Background refresh starting (parallel, first_cycle={is_first_cycle})")
        self._post_ui_callback(lambda: self._set_loading_indicator(True))
        worker = get_current_worker()

        try:
            max_workers = 7 if is_first_cycle else 6
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures: dict[Future[object], str] = {
                    pool.submit(self._fetch_history): "history",
                    pool.submit(self._fetch_nodes): "nodes",
                    pool.submit(self._fetch_all_jobs): "all_jobs",
                    pool.submit(self._fetch_wait_time): "wait_time",
                    pool.submit(get_fair_share_priority, max_retries=1): "fair_share",
                    pool.submit(get_pending_job_priority, max_retries=1): "job_priority",
                }
                if is_first_cycle:
                    futures[pool.submit(self._fetch_energy)] = "energy"

                for future in as_completed(futures):
                    if worker.is_cancelled:
                        logger.debug("Refresh worker cancelled, aborting")
                        return
                    label = futures[future]
                    try:
                        result = cast(_FetchResult, future.result())
                        self._apply_fetch_result(label, result)
                    except Exception:
                        logger.exception(f"Failed to fetch {label}")

            if worker.is_cancelled:
                return
            self._post_ui_callback(lambda: self._on_refresh_complete(is_first_cycle))

        except Exception:
            logger.exception("Error during parallel refresh")
        finally:
            self._post_ui_callback(lambda: self._set_loading_indicator(False))

    def _apply_fetch_result(self, label: str, result: _FetchResult) -> None:  # noqa: PLR0912, PLR0915
        """Process one completed fetch and push a partial UI update (worker thread).

        Called in the background worker thread as each data source completes.
        Updates shared state and schedules targeted main-thread UI updates.

        Args:
            label: Fetch label identifying the data source.
            result: The data returned by the fetch function.
        """
        if label == "history":
            history_jobs, total_jobs, total_requeues, max_requeues = cast(_HistoryResult, result)
            with self._refresh_state_lock:
                old_states = self._job_states()
                self._handle_refresh_fallback(
                    self._last_running_jobs, history_jobs, total_jobs, total_requeues, max_requeues
                )
                self._invalidate_changed_job_info(old_states)
                job_rows = self._current_job_rows()
            self._post_ui_callback(lambda: self._update_jobs_table(job_rows))

        elif label == "nodes":
            self._cluster_nodes = cast(list[dict[str, str]], result)
            self._cached_node_infos = self._parse_node_infos()
            self._post_ui_callback(self._update_nodes_tab_only)

        elif label == "all_jobs":
            self._all_users_jobs = cast(list[tuple[str, ...]], result)
            self._compute_user_overview_cache()
            self._post_ui_callback(self._update_all_jobs_widgets)

        elif label == "wait_time":
            self._wait_time_jobs = cast(list[tuple[str, ...]], result)
            stats = self._calculate_cluster_stats()
            self._cached_cluster_stats = stats
            self._post_ui_callback(lambda s=stats: self._update_cluster_sidebar_with_stats(s))

        elif label == "fair_share":
            entries, error = cast(_PriorityHalfResult, result)
            if error:
                logger.warning(f"sshare failed: {error}")
            else:
                self._fair_share_entries = entries
            # Only trigger priority tab update once both halves have arrived
            self._priority_halves_received += 1
            if self._priority_halves_received >= _PRIORITY_FETCH_COUNT:
                self._priority_halves_received = 0
                self._compute_priority_overview_cache()
                self._post_ui_callback(self._update_priority_tab)

        elif label == "job_priority":
            entries, error = cast(_PriorityHalfResult, result)
            if error:
                logger.warning(f"sprio failed: {error}")
            else:
                self._job_priority_entries = entries
            self._priority_halves_received += 1
            if self._priority_halves_received >= _PRIORITY_FETCH_COUNT:
                self._priority_halves_received = 0
                self._compute_priority_overview_cache()
                self._post_ui_callback(self._update_priority_tab)

        elif label == "energy":
            energy_jobs, energy_loaded = cast(_EnergyResult, result)
            self._energy_history_jobs = energy_jobs
            self._energy_data_loaded = energy_loaded
            if energy_loaded:
                self._cached_energy_user_stats = UserOverviewTab.aggregate_energy_stats(energy_jobs)
                self._post_ui_callback(self._update_energy_tab)

        else:
            logger.warning(f"_apply_fetch_result: unknown label {label!r}")

    def _update_nodes_and_sidebar(self) -> None:
        """Update cluster sidebar and node overview tab (main thread only)."""
        self.call_later(self._update_cluster_sidebar)
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "nodes":
                self.call_later(self._update_node_overview)
            else:
                self._dirty_nodes_tab = True
        except Exception as exc:
            logger.debug(f"Failed to update node tab: {exc}")

    def _update_nodes_and_sidebar_with_stats(self, stats: ClusterStats) -> None:
        """Update cluster sidebar (with pre-computed stats) and node overview tab (main thread only).

        Args:
            stats: Pre-computed cluster stats to pass directly to the sidebar.
        """
        self.call_later(self._update_cluster_sidebar_with_stats, stats)
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "nodes":
                self.call_later(self._update_node_overview)
            else:
                self._dirty_nodes_tab = True
        except Exception:
            logger.exception("Failed to update node tab")

    def _update_nodes_tab_only(self) -> None:
        """Update node overview tab without touching the sidebar (main thread only)."""
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "nodes":
                self._update_node_overview()
            else:
                self._dirty_nodes_tab = True
        except Exception:
            logger.exception("Failed to update node tab")

    def _update_all_jobs_widgets(self) -> None:
        """Update user overview and My Usage banner without touching the sidebar (main thread only)."""
        self.call_later(self._update_my_usage_summary, self._cached_running_user_stats)
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "users":
                self.call_later(self._apply_user_overview_from_cache)
            else:
                self._dirty_users_tab = True
        except Exception:
            logger.exception("Failed to update users tab")

    def _update_all_jobs_widgets_with_stats(self, stats: ClusterStats) -> None:
        """Update user overview, sidebar (with pre-computed stats), and My Usage banner (main thread only).

        Args:
            stats: Pre-computed cluster stats to pass directly to the sidebar.
        """
        self.call_later(self._update_cluster_sidebar_with_stats, stats)
        self.call_later(self._update_my_usage_summary, self._cached_running_user_stats)
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "users":
                self.call_later(self._apply_user_overview_from_cache)
            else:
                self._dirty_users_tab = True
        except Exception:
            logger.exception("Failed to update users tab")

    def _update_priority_tab(self) -> None:
        """Update priority overview if active, else mark dirty (main thread only)."""
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "priority":
                self._apply_priority_overview_from_cache()
            else:
                self._dirty_priority_tab = True
        except Exception:
            logger.exception("Failed to update priority tab")

    def _update_energy_tab(self) -> None:
        """Update energy subtab in user overview (main thread only).

        Uses a generation counter to skip stale updates.
        """
        self._energy_update_gen += 1
        gen = self._energy_update_gen
        energy = self._cached_energy_user_stats

        def _guarded() -> None:
            if gen != self._energy_update_gen:
                return
            try:
                tc = self.query_one("#tab-container", TabContainer)
                if tc.active_tab != "users":
                    self._dirty_users_tab = True
                    return
            except Exception:
                return
            try:
                user_tab = self.query_one("#user-overview", UserOverviewTab)
                user_tab.update_energy_users(energy)
            except Exception:
                logger.exception("Failed to update energy tab")

        self.call_later(_guarded)

    def _on_refresh_complete(self, is_first_cycle: bool) -> None:
        """Handle post-refresh bookkeeping (main thread only).

        On the first cycle this starts the recurring heavy-refresh timer and
        notifies the user that all cluster data has been loaded. The fast
        running-jobs timer is already started in :meth:`_finish_initial_load`.

        Args:
            is_first_cycle: Whether this was the first background refresh cycle.
        """
        if is_first_cycle:
            self._initial_background_complete = True
            self.heavy_refresh_timer = self.set_interval(self.heavy_refresh_interval, self._start_refresh_worker)
            self.notify("Cluster data ready", timeout=3, severity="information")
            logger.info(
                f"Background initial load complete. Running-jobs refresh every {self.refresh_interval}s, "
                f"heavy refresh every {self.heavy_refresh_interval}s"
            )
        else:
            logger.debug("Heavy refresh cycle complete - all data sources updated")

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
            if not self._error_notified.get("history_jobs"):
                self._error_notified["history_jobs"] = True
                self._post_ui_callback(
                    lambda: self.notify("History refresh failed - using cached history", severity="warning")
                )
        else:
            # Update cache of raw history data on success
            self._error_notified["history_jobs"] = False
            self._last_history_jobs = history_jobs
            self._last_history_stats = (total_jobs, total_requeues, max_requeues)

        self._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)

    def _notify_new_jobs(self, old_job_ids: set[str]) -> None:
        """Post a notification if new jobs appeared in the cache after a refresh.

        Compares the current cache contents against *old_job_ids* (captured
        before the cache was rebuilt) and notifies the user about any newly
        detected active (running/pending) jobs.

        Args:
            old_job_ids: Set of job IDs that were in the cache before the refresh.
        """
        if not old_job_ids:
            return  # First load — don't notify for initial data
        new_active_jobs = [j for j in self._job_cache.jobs if j.job_id not in old_job_ids and j.is_active]
        if not new_active_jobs:
            return
        if len(new_active_jobs) == 1:
            job = new_active_jobs[0]
            msg = f"New job detected: {job.job_id} ({job.name})"
        else:
            msg = f"{len(new_active_jobs)} new jobs detected"
        self._post_ui_callback(lambda m=msg: self.notify(m, timeout=5, severity="information"))

    def _job_states(self) -> dict[str, str]:
        """Return a snapshot mapping each cached job's ID to its current state."""
        return {job.job_id: job.state for job in self._job_cache.jobs}

    def _invalidate_changed_job_info(self, old_states: dict[str, str]) -> None:
        """Evict cached modal job-info for jobs whose state changed (worker thread).

        Compares each job's state before and after the cache rebuild. Any job
        whose state changed - or that disappeared from the cache - has its cached
        ``scontrol``/``sacct`` detail evicted so the next modal open re-fetches
        it; unchanged jobs keep their cached entry for instant display. Eviction
        is conservative: array tasks that share a normalized cache key are
        evicted together when any one of them changes.

        Called from ``_apply_fetch_result`` right after the cache rebuild, so the
        modal cache stays consistent with the table cache it was derived from
        instead of being gated behind full-cycle completion.

        Args:
            old_states: Job-ID-to-state snapshot captured before the rebuild.
        """
        new_states = self._job_states()
        for job_id, old_state in old_states.items():
            if new_states.get(job_id) != old_state:
                self._job_info_cache.pop(normalize_array_job_id(job_id), None)

    def _set_loading_indicator(self, active: bool) -> None:
        """Safely toggle the global loading indicator spinner."""
        try:
            indicator = self.query_one(LoadingIndicator)
            indicator.loading = active
        except Exception as exc:
            logger.debug(f"Failed to toggle loading indicator: {exc}")

    def _update_jobs_table(self, job_rows: list[tuple[str, ...]]) -> None:
        """Push pre-computed job rows into the jobs table widget (main thread only).

        Uses a generation counter so that if multiple updates are queued
        (e.g. after returning from another tmux tab), only the latest one
        actually rebuilds the table.

        Args:
            job_rows: Pre-computed job table rows ready for display.
        """
        self._jobs_update_gen += 1
        gen = self._jobs_update_gen
        try:
            jobs_filterable = self.query_one("#jobs-filterable-table", FilterableDataTable)

            def _apply_jobs() -> None:
                if gen != self._jobs_update_gen:
                    return
                jobs_filterable.set_data(job_rows)
                jobs_filterable.display = len(job_rows) > 0
                logger.debug(f"Jobs table updated: {len(job_rows)} jobs")

            self.call_later(_apply_jobs)
        except Exception:
            logger.exception("Failed to update jobs table")

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
        """Update the cluster sidebar with current statistics.

        Uses pre-computed cluster stats from background worker to avoid blocking UI.
        Falls back to computing on-demand if cache is empty (initial load).
        """
        try:
            sidebar = self.query_one("#cluster-sidebar", ClusterSidebar)
            # Use cached cluster stats (computed in background worker)
            # Fall back to computing if cache is empty (shouldn't happen after initial load)
            stats = self._cached_cluster_stats if self._cached_cluster_stats else self._calculate_cluster_stats()
            sidebar.update_stats(stats)
            is_cached = self._cached_cluster_stats is not None
            logger.debug(
                f"Updated cluster sidebar: {stats.total_nodes} nodes, {stats.total_cpus} CPUs (cached={is_cached})"
            )
        except Exception as exc:
            logger.error(f"Failed to update cluster sidebar: {exc}", exc_info=True)

    def _update_cluster_sidebar_with_stats(self, stats: ClusterStats) -> None:
        """Update the cluster sidebar using pre-computed stats (main thread only).

        Avoids reading the shared ``_cached_cluster_stats`` field, which may be
        overwritten by another worker-thread branch before the callback runs.

        Args:
            stats: Pre-computed cluster stats captured by the calling branch.
        """
        try:
            sidebar = self.query_one("#cluster-sidebar", ClusterSidebar)
            sidebar.update_stats(stats)
            logger.debug(f"Updated cluster sidebar: {stats.total_nodes} nodes, {stats.total_cpus} CPUs (pre-computed)")
        except Exception as exc:
            logger.error(f"Failed to update cluster sidebar: {exc}", exc_info=True)

    def _parse_node_state(self, state: str, stats: ClusterStats) -> bool:
        """Delegate to ``stoei.cluster_stats.parse_node_state``."""
        return parse_node_state(state, stats)

    def _parse_node_cpus(self, node_data: dict[str, str], stats: ClusterStats, *, include_total: bool = True) -> None:
        """Delegate to ``stoei.cluster_stats.parse_node_cpus``."""
        parse_node_cpus(node_data, stats, include_total=include_total)

    def _parse_node_memory(self, node_data: dict[str, str], stats: ClusterStats, *, include_total: bool = True) -> None:
        """Delegate to ``stoei.cluster_stats.parse_node_memory``."""
        parse_node_memory(node_data, stats, include_total=include_total)

    def _process_gpu_entries_for_stats(
        self, gpu_entries: list[tuple[str, int]], stats: ClusterStats, is_allocated: bool
    ) -> None:
        """Delegate to ``stoei.cluster_stats.process_gpu_entries_for_stats``."""
        process_gpu_entries_for_stats(gpu_entries, stats, is_allocated)

    def _parse_gpus_from_gres(
        self, node_data: dict[str, str], state: str, stats: ClusterStats, *, include_total: bool = True
    ) -> None:
        """Delegate to ``stoei.cluster_stats.parse_gpus_from_gres``."""
        parse_gpus_from_gres(node_data, state, stats, include_total=include_total)

    def _aggregate_pending_gpus(
        self,
        gpu_entries: list[tuple[str, int]],
        array_size: int,
        pending_gpus_by_type: dict[str, int],
        partition_stats: PendingPartitionStats,
    ) -> int:
        """Delegate to ``stoei.cluster_stats.aggregate_pending_gpus``."""
        return aggregate_pending_gpus(gpu_entries, array_size, pending_gpus_by_type, partition_stats)

    def _calculate_pending_resources(self, stats: ClusterStats) -> None:
        """Delegate to ``stoei.cluster_stats.calculate_pending_resources``."""
        calculate_pending_resources(self._all_users_jobs, stats)

    def _calculate_cluster_stats(self) -> ClusterStats:
        """Delegate to ``stoei.cluster_stats.calculate_cluster_stats``."""
        return calculate_cluster_stats(self._cluster_nodes, self._all_users_jobs, self._wait_time_jobs)

    def _update_node_overview(self) -> None:
        """Update the node overview tab using cached node infos.

        Uses a generation counter to skip stale updates and a staleness
        guard to skip work when the user has already switched away.
        """
        self._nodes_update_gen += 1
        gen = self._nodes_update_gen
        try:
            node_tab = self.query_one("#node-overview", NodeOverviewTab)
            node_infos = self._cached_node_infos if self._cached_node_infos else self._parse_node_infos()

            def _guarded() -> None:
                if gen != self._nodes_update_gen:
                    return
                try:
                    tc = self.query_one("#tab-container", TabContainer)
                    if tc.active_tab != "nodes":
                        self._dirty_nodes_tab = True
                        return
                except Exception:
                    return
                node_tab.update_nodes(node_infos)

            self.call_later(_guarded)
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
                # ALLOCATED = all resources in use, MIXED = some resources in use
                # For MIXED, we assume all GPUs allocated (same as sidebar logic)
                # since we can't determine exact allocation without AllocTRES
                state_upper = state.upper()
                if "ALLOCATED" in state_upper or "MIXED" in state_upper:
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

    def _compute_user_overview_cache(self) -> None:
        """Pre-compute user overview data from cached SLURM results.

        This method is safe to run in a background worker thread.
        """
        # Filter for running jobs only (exclude PENDING/PD for running stats)
        state_index = 4
        running_jobs = [
            j
            for j in self._all_users_jobs
            if len(j) > state_index and j[state_index].strip().upper() not in ("PENDING", "PD")
        ]

        self._cached_running_user_stats = UserOverviewTab.aggregate_user_stats(running_jobs)
        self._cached_pending_user_stats = UserOverviewTab.aggregate_pending_user_stats(self._all_users_jobs)
        self._cached_energy_user_stats = (
            UserOverviewTab.aggregate_energy_stats(self._energy_history_jobs) if self._energy_history_jobs else []
        )

    def _compute_priority_overview_cache(self) -> None:
        """Pre-compute priority overview data and display rows from cached SLURM results.

        Performs all heavy computation (parsing, sorting, ranking, row building)
        so the main thread only needs to push pre-built rows into widgets.

        This method is safe to run in a background worker thread.
        """
        colors = get_theme_colors(self)

        if self._fair_share_entries:
            user_data, account_data = parse_sshare_output(self._fair_share_entries)
            user_priorities = [
                UserPriority(
                    username=d["User"],
                    account=d["Account"],
                    raw_shares=d["RawShares"],
                    norm_shares=d["NormShares"],
                    raw_usage=d["RawUsage"],
                    norm_usage=d["NormUsage"],
                    effective_usage=d["EffectvUsage"],
                    fair_share=d["FairShare"],
                )
                for d in user_data
            ]
            account_priorities = [
                AccountPriority(
                    account=d["Account"],
                    raw_shares=d["RawShares"],
                    norm_shares=d["NormShares"],
                    raw_usage=d["RawUsage"],
                    norm_usage=d["NormUsage"],
                    effective_usage=d["EffectvUsage"],
                    fair_share=d["FairShare"],
                )
                for d in account_data
            ]
        else:
            user_priorities = []
            account_priorities = []

        if self._job_priority_entries:
            job_data = parse_sprio_output(self._job_priority_entries)
            job_priorities = [
                JobPriority(
                    job_id=d["JobID"],
                    user=d["User"],
                    account=d["Account"],
                    priority=d["Priority"],
                    age=d["Age"],
                    fair_share=d["FairShare"],
                    job_size=d["JobSize"],
                    partition=d["Partition"],
                    qos=d["QOS"],
                )
                for d in job_data
            ]
        else:
            job_priorities = []

        # Sort, rank, and build display rows (all in background thread)
        sorted_users, user_rows = build_user_priority_rows(
            user_priorities,
            self._current_username,
            colors,
        )
        current_user_account = next(
            (p.account for p in sorted_users if p.username == self._current_username),
            "",
        )
        sorted_accounts, account_rows = build_account_priority_rows(
            account_priorities,
            current_user_account,
            colors,
        )
        sorted_jobs, job_rows = build_job_priority_rows(
            job_priorities,
            self._current_username,
            colors,
        )
        my_job_rows = build_my_job_priority_rows(sorted_jobs, self._current_username)
        summary_markup = build_my_priority_summary(
            self._current_username,
            sorted_users,
            sorted_accounts,
            sorted_jobs,
            colors,
        )

        self._cached_user_priorities = sorted_users
        self._cached_account_priorities = sorted_accounts
        self._cached_job_priorities = sorted_jobs
        self._cached_user_priority_rows = user_rows
        self._cached_account_priority_rows = account_rows
        self._cached_job_priority_rows = job_rows
        self._cached_my_job_priority_rows = my_job_rows
        self._cached_priority_summary_markup = summary_markup

    def _apply_user_overview_from_cache(self) -> None:
        """Apply cached user overview data to the UI (main thread only).

        Uses a generation counter to skip stale updates and a staleness
        guard to skip work when the user has already switched away.
        """
        self._users_update_gen += 1
        gen = self._users_update_gen
        try:
            user_tab = self.query_one("#user-overview", UserOverviewTab)
        except Exception as exc:
            logger.debug(f"Failed to apply user overview from cache: {exc}")
            return

        running = self._cached_running_user_stats
        pending = self._cached_pending_user_stats
        energy = self._cached_energy_user_stats

        def _guarded_users() -> None:
            if gen != self._users_update_gen:
                return
            try:
                tc = self.query_one("#tab-container", TabContainer)
                if tc.active_tab != "users":
                    self._dirty_users_tab = True
                    return
            except Exception:
                return
            user_tab.update_users(running)
            user_tab.update_pending_users(pending)
            if energy:
                user_tab.update_energy_users(energy)

        self.call_later(_guarded_users)
        self.call_later(self._update_my_usage_summary, running)

    def _update_my_usage_summary(self, users: list[UserStats]) -> None:
        """Update the 'My Usage' banner on the Jobs tab.

        Args:
            users: List of all running user statistics.
        """
        try:
            summary = self.query_one("#my-usage-summary", Static)
        except Exception:
            return

        my_stats = next((u for u in users if u.username == self._current_username), None)
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

    def _apply_priority_overview_from_cache(self) -> None:
        """Apply cached priority overview data to the UI (main thread only).

        Uses a generation counter to skip stale updates and a staleness
        guard to skip work when the user has already switched away.
        """
        self._priority_update_gen += 1
        gen = self._priority_update_gen
        try:
            tc = self.query_one("#tab-container", TabContainer)
            if tc.active_tab != "priority":
                self._dirty_priority_tab = True
                return
        except Exception:
            return

        try:
            priority_tab = self.query_one("#priority-overview", PriorityOverviewTab)

            def _guarded() -> None:
                if gen != self._priority_update_gen:
                    return
                priority_tab.apply_prebuilt_data(
                    PrebuiltPriorityData(
                        user_priorities=self._cached_user_priorities,
                        account_priorities=self._cached_account_priorities,
                        job_priorities=self._cached_job_priorities,
                        user_rows=self._cached_user_priority_rows,
                        account_rows=self._cached_account_priority_rows,
                        job_rows=self._cached_job_priority_rows,
                        my_job_rows=self._cached_my_job_priority_rows,
                        summary_markup=self._cached_priority_summary_markup,
                    )
                )

            self.call_later(_guarded)
        except Exception as exc:
            logger.debug(f"Failed to apply priority overview from cache: {exc}")

    def _update_user_overview(self) -> None:
        """Update the user overview tab without blocking the UI."""
        try:
            has_data = bool(self._all_users_jobs) or bool(self._energy_history_jobs)
            has_cache = (
                bool(self._cached_running_user_stats)
                or bool(self._cached_pending_user_stats)
                or bool(self._cached_energy_user_stats)
            )

            if has_data and not has_cache:
                # Compute in background (never block the UI on tab switch)
                def compute_and_apply() -> None:
                    self._compute_user_overview_cache()
                    self._post_ui_callback(self._apply_user_overview_from_cache)

                self.run_worker(
                    compute_and_apply, name="compute_user_overview", group="compute_user", exclusive=True, thread=True
                )
                return

            self._apply_user_overview_from_cache()
        except Exception as exc:
            logger.error(f"Failed to update user overview: {exc}", exc_info=True)

    def _update_priority_overview(self) -> None:
        """Update the priority overview tab without blocking the UI."""
        try:
            has_data = bool(self._fair_share_entries) or bool(self._job_priority_entries)
            has_cache = (
                bool(self._cached_user_priorities)
                or bool(self._cached_account_priorities)
                or bool(self._cached_job_priorities)
            )

            if has_data and not has_cache:
                # Compute in background (never block the UI on tab switch)
                def compute_and_apply() -> None:
                    self._compute_priority_overview_cache()
                    self._post_ui_callback(self._apply_priority_overview_from_cache)

                self.run_worker(
                    compute_and_apply,
                    name="compute_priority_overview",
                    group="compute_priority",
                    exclusive=True,
                    thread=True,
                )
                return

            self._apply_priority_overview_from_cache()
        except Exception as exc:
            logger.error(f"Failed to update priority overview: {exc}", exc_info=True)

    def _handle_tab_jobs_switched(self) -> None:
        """Handle switching to the jobs tab."""
        try:
            jobs_table = self.query_one("#jobs_table", DataTable)
            jobs_table.focus()
            logger.debug("Focused jobs table for arrow key navigation")
        except Exception as exc:
            logger.debug(f"Failed to focus jobs table: {exc}")

    def _handle_tab_nodes_switched(self) -> None:
        """Handle switching to the nodes tab."""
        if self._dirty_nodes_tab:
            self._dirty_nodes_tab = False
            self.call_later(self._update_node_overview)
        try:
            node_tab = self.query_one("#node-overview", NodeOverviewTab)
            nodes_table = node_tab.query_one("#nodes_table", DataTable)
            nodes_table.focus()
            logger.debug("Focused nodes table for arrow key navigation")
        except Exception as exc:
            logger.debug(f"Failed to focus nodes table: {exc}")

    def _handle_tab_users_switched(self) -> None:
        """Handle switching to the users tab."""
        if self._dirty_users_tab:
            self._dirty_users_tab = False
            self.call_later(self._update_user_overview)
        try:
            user_tab = self.query_one("#user-overview", UserOverviewTab)
            users_table = user_tab.query_one("#users_table", DataTable)
            users_table.focus()
            logger.debug("Focused users table for arrow key navigation")
        except Exception as exc:
            logger.debug(f"Failed to focus users table: {exc}")

    def _handle_tab_priority_switched(self) -> None:
        """Handle switching to the priority tab."""
        if self._dirty_priority_tab:
            self._dirty_priority_tab = False
            self.call_later(self._update_priority_overview)
        try:
            priority_tab = self.query_one("#priority-overview", PriorityOverviewTab)
            # Focus the table in the currently active sub-tab
            subtab_table_ids = {
                "mine": "my_job_priority_table",
                "users": "user_priority_table",
                "accounts": "account_priority_table",
                "jobs": "job_priority_table",
            }
            table_id = subtab_table_ids.get(priority_tab.active_subtab, "my_job_priority_table")
            priority_table = priority_tab.query_one(f"#{table_id}", DataTable)
            priority_table.focus()
            logger.debug(f"Focused priority table {table_id} for arrow key navigation")
        except Exception as exc:
            logger.debug(f"Failed to focus priority table: {exc}")

    def _handle_tab_logs_switched(self) -> None:
        """Handle switching to the logs tab."""
        try:
            log_pane = self.query_one("#log_pane", LogPane)
            log_pane.focus()
            logger.debug("Focused log pane")
        except Exception as exc:
            logger.debug(f"Failed to focus log pane: {exc}")

    def on_tab_switched(self, event: TabSwitched) -> None:
        """Handle tab switching events.

        Args:
            event: The TabSwitched event.
        """
        # Ignore stale events from rapid tab switching — TabContainer already
        # updated visibility, so we only need to run the tab-specific handler
        # for the tab that is *currently* active.
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            if tab_container.active_tab != event.tab_name:
                logger.debug(f"Ignoring stale tab event for {event.tab_name} (active: {tab_container.active_tab})")
                return
        except Exception:
            return

        # Dispatch to tab-specific handler (focus, lazy data load, etc.)
        tab_handlers = {
            "jobs": self._handle_tab_jobs_switched,
            "nodes": self._handle_tab_nodes_switched,
            "users": self._handle_tab_users_switched,
            "priority": self._handle_tab_priority_switched,
            "logs": self._handle_tab_logs_switched,
        }
        handler = tab_handlers.get(event.tab_name)
        if handler:
            try:
                handler()
            except Exception as exc:
                logger.warning(f"Failed to handle tab switch to {event.tab_name}: {exc}")

    def action_refresh(self) -> None:
        """Manual refresh action (refreshes both the running-jobs and heavy loops)."""
        logger.info("Manual refresh triggered")
        self._error_notified.clear()
        self.notify("Refreshing...")
        self._start_running_refresh_worker()
        self._start_refresh_worker()

    def reload_energy_data(self) -> None:
        """Reload energy data based on current settings.

        This is called when the user enables energy loading in settings
        and clicks the reload button.
        """
        if not self._settings.energy_loading_enabled:
            self.notify("Energy loading is disabled", severity="warning")
            return

        self.notify("Loading energy data...")
        self.run_worker(
            self._reload_energy_data_async, name="energy_reload", group="energy_reload", exclusive=True, thread=True
        )

    def _reload_energy_data_async(self) -> None:
        """Load energy data asynchronously (runs in worker thread)."""
        months = self._settings.energy_history_months
        logger.info(f"Reloading energy data for {months} months")

        energy_jobs, error = get_energy_job_history(months)
        if error:
            logger.warning(f"Failed to load energy data: {error}")
            self._post_ui_callback(lambda: self.notify(f"Failed to load energy data: {error}", severity="error"))
            self._energy_data_loaded = False
            self._energy_history_jobs = []
            self._cached_energy_user_stats = []
            return

        self._energy_history_jobs = energy_jobs
        self._energy_data_loaded = True
        self._cached_energy_user_stats = UserOverviewTab.aggregate_energy_stats(energy_jobs)
        logger.info(f"Loaded {len(energy_jobs)} energy history jobs")

        # Update the UI
        self._post_ui_callback(self._update_energy_ui)

    def _update_energy_ui(self) -> None:
        """Update the energy UI after data reload."""
        try:
            user_tab = self.query_one("#user-overview", UserOverviewTab)
            if self._cached_energy_user_stats:
                self.call_later(user_tab.update_energy_users, self._cached_energy_user_stats)
                self.call_later(user_tab.update_energy_period_label, self._settings.energy_history_months)
                self.notify(f"Loaded {len(self._energy_history_jobs)} energy history jobs", severity="information")
            else:
                self.notify("No energy data loaded", severity="warning")
        except Exception as exc:
            logger.error(f"Failed to update energy UI: {exc}", exc_info=True)

    def _switch_tab(self, tab_name: TabName) -> None:
        """Debounced tab switch.

        Multiple calls within the same event-loop frame are batched: only
        one ``call_later`` callback is scheduled, and it always switches to
        the *last* requested tab.  This means rapid key-presses that arrive
        in the same frame only trigger a single ``switch_tab()`` call.

        Args:
            tab_name: Name of the tab to switch to.
        """
        if not self._initial_load_complete:
            return
        self._pending_tab_switch = tab_name
        if not self._tab_switch_scheduled:
            self._tab_switch_scheduled = True
            self.call_later(self._execute_tab_switch)

    def _execute_tab_switch(self) -> None:
        """Execute the pending debounced tab switch."""
        self._tab_switch_scheduled = False
        tab_name = self._pending_tab_switch
        self._pending_tab_switch = None
        if tab_name is None:
            return
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab(tab_name)
        except Exception as exc:
            logger.debug(f"Failed to switch to {tab_name} tab: {exc}")

    def action_switch_tab_jobs(self) -> None:
        """Switch to the Jobs tab."""
        self._switch_tab("jobs")

    def action_switch_tab_nodes(self) -> None:
        """Switch to the Nodes tab."""
        self._switch_tab("nodes")

    def action_switch_tab_users(self) -> None:
        """Switch to the Users tab."""
        self._switch_tab("users")

    def action_switch_tab_priority(self) -> None:
        """Switch to the Priority tab."""
        self._switch_tab("priority")

    def action_switch_tab_logs(self) -> None:
        """Switch to the Logs tab."""
        self._switch_tab("logs")

    def _resolve_base_tab(self) -> TabName:
        """Return the tab name to use as base for next/previous cycling.

        If a debounced switch is pending, use that so rapid Tab presses
        advance correctly. Otherwise use the currently active tab.
        """
        if self._pending_tab_switch is not None:
            return self._pending_tab_switch
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
        except Exception:
            return "jobs"
        else:
            return tab_container.active_tab

    def action_next_tab(self) -> None:
        """Switch to the next tab (cycling)."""
        if not self._initial_load_complete:
            return
        tab_order: list[TabName] = ["jobs", "nodes", "users", "priority", "logs"]
        base = self._resolve_base_tab()
        current_index = tab_order.index(base) if base in tab_order else 0
        self._switch_tab(tab_order[(current_index + 1) % len(tab_order)])

    def action_previous_tab(self) -> None:
        """Switch to the previous tab (cycling)."""
        if not self._initial_load_complete:
            return
        tab_order: list[TabName] = ["jobs", "nodes", "users", "priority", "logs"]
        base = self._resolve_base_tab()
        current_index = tab_order.index(base) if base in tab_order else 0
        self._switch_tab(tab_order[(current_index - 1) % len(tab_order)])

    def on_key(self, event: Key) -> None:
        """Handle key events, intercepting Tab for tab navigation.

        Also handles emacs-mode keybindings when in emacs mode.

        Args:
            event: The key event.
        """
        # Intercept Tab for tab navigation (Shift+Tab is handled by binding)
        # Check if it's a plain tab (not shift+tab which comes through as binding)
        if event.key == "tab" and event.name == "tab":
            event.prevent_default()
            self.action_next_tab()
            return

        # Handle emacs-mode keybindings
        if self._settings.keybind_mode == "emacs":
            key = event.key
            action_map = {
                self._keybindings.get_key(Actions.QUIT): self.action_quit,
                self._keybindings.get_key(Actions.HELP): self.action_show_help,
                self._keybindings.get_key(Actions.REFRESH): self.action_refresh,
                self._keybindings.get_key(Actions.SETTINGS): self.action_show_settings,
                self._keybindings.get_key(Actions.JOB_INFO): self.action_show_job_info,
                self._keybindings.get_key(Actions.JOB_CANCEL): self.action_cancel_job,
            }
            if key in action_map and action_map[key] is not None:
                event.prevent_default()
                action_map[key]()

    def action_show_help(self) -> None:
        """Show help screen with keybindings."""
        logger.debug("Showing help screen")
        self.push_screen(HelpScreen(keybindings=self._keybindings))

    def action_show_job_info(self) -> None:
        """Show job info dialog."""
        self._detail.show_job_info_prompt()

    def _fetch_and_display_job_info(self, job_id: str) -> None:
        """Fetch job info in background and display on main thread.

        Args:
            job_id: The SLURM job ID to fetch.
        """
        self._detail.fetch_and_display_job_info(job_id)

    def _prefetch_job_info(self, job_id: str) -> None:
        """Pre-fetch job info into cache in background.

        Called when the cursor moves to a new row so the info is ready
        when the user presses Enter/i.

        Args:
            job_id: The SLURM job ID to pre-fetch.
        """
        query_id = normalize_array_job_id(job_id)
        if query_id in self._job_info_cache:
            return
        logger.debug(f"Pre-fetching job info for {query_id}")
        result = get_job_info_and_log_paths(query_id)
        # Only cache if this worker wasn't cancelled
        worker = get_current_worker()
        if not worker.is_cancelled:
            self._job_info_cache[query_id] = result

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Pre-fetch job info when cursor moves to a new row.

        Uses an exclusive worker so only the latest cursor position is fetched.

        Args:
            event: The row highlighted event.
        """
        if event.data_table.id != "jobs_table":
            return
        if event.data_table.row_count == 0:
            return
        try:
            row_data = event.data_table.get_row(event.row_key)
            job_id = str(row_data[0]).strip()
            if job_id:
                self.run_worker(
                    lambda: self._prefetch_job_info(job_id),
                    name="prefetch_job_info",
                    group="prefetch_job_info",
                    exclusive=True,
                    thread=True,
                )
        except Exception:
            logger.debug(f"Could not pre-fetch job info for highlighted row: {event.row_key}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in data tables.

        Args:
            event: The row selected event.
        """
        # Check which table is selected
        if event.data_table.id == "nodes_table":
            self._detail.show_node_info_for_row(event.data_table, event.row_key)
        elif event.data_table.id in (
            "users_table",
            "pending_users_table",
            "energy_users_table",
            "user_priority_table",
        ):
            self._detail.show_user_info_for_row(event.data_table, event.row_key)
        elif event.data_table.id == "account_priority_table":
            self._detail.show_account_info_for_row(event.data_table, event.row_key)
        else:
            # Default to job info for jobs table
            self._detail.show_job_info_for_row(event.data_table, event.row_key)

    def _show_detail_for_row(self, table: DataTable, row_key: RowKey, noun: str, show: Callable[[str], None]) -> None:
        """Extract the first-column identifier from a row and open its detail modal."""
        self._detail.show_detail_for_row(table, row_key, noun, show)

    def _show_node_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show node info for a specific row in the nodes table."""
        self._detail.show_node_info_for_row(table, row_key)

    def _show_node_info(self, node_name: str) -> None:
        """Show detailed information for a node."""
        self._detail.show_node_info(node_name)

    def _display_node_info(self, node_name: str, node_info: str, error: str | None) -> None:
        """Display node information in a modal screen."""
        self._detail.display_node_info(node_name, node_info, error)

    def _show_user_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show user info for a specific row in the users table."""
        self._detail.show_user_info_for_row(table, row_key)

    def _show_user_info(self, username: str) -> None:
        """Show detailed information for a user."""
        self._detail.show_user_info(username)

    def _display_user_info(self, username: str, user_info: str, error: str | None) -> None:
        """Display user information in a modal screen."""
        self._detail.display_user_info(username, user_info, error)

    def _show_account_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show account info for a specific row in the accounts table."""
        self._detail.show_account_info_for_row(table, row_key)

    def _show_account_info(self, account_name: str) -> None:
        """Show detailed information for an account/institute."""
        self._detail.show_account_info(account_name)

    def _display_account_info(self, account_name: str, account_info: str, error: str | None) -> None:
        """Display account information in a modal screen."""
        self._detail.display_account_info(account_name, account_info, error)

    def _show_job_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show job info for a specific row in a table."""
        self._detail.show_job_info_for_row(table, row_key)

    def action_show_selected_job_info(self) -> None:
        """Show job info for the currently selected row."""
        self._detail.show_selected_job_info()

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
        # Recalculate sidebar width based on new terminal size
        self._apply_sidebar_width()

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
