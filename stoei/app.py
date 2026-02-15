"""Main Textual TUI application for stoei."""

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

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

from stoei.colors import get_theme_colors
from stoei.keybindings import Actions, KeybindingConfig
from stoei.logger import add_tui_sink, get_logger, remove_tui_sink
from stoei.settings import (
    MAX_SIDEBAR_WIDTH_PERCENT,
    MIN_SIDEBAR_WIDTH_PERCENT,
    Settings,
    load_settings,
    save_settings,
)
from stoei.slurm.array_parser import normalize_array_job_id, parse_array_size
from stoei.slurm.cache import Job, JobCache, JobState
from stoei.slurm.commands import (
    cancel_job,
    get_all_running_jobs,
    get_cluster_nodes,
    get_energy_job_history,
    get_fair_share_priority,
    get_job_history,
    get_job_info,
    get_job_log_paths,
    get_node_info,
    get_pending_job_priority,
    get_running_jobs,
    get_user_jobs,
    get_wait_time_job_history,
)
from stoei.slurm.formatters import format_account_info, format_compact_timeline, format_user_info
from stoei.slurm.gpu_parser import (
    aggregate_gpu_counts,
    calculate_total_gpus,
    format_gpu_types,
    has_specific_gpu_types,
    parse_gpu_entries,
    parse_gpu_from_gres,
)
from stoei.slurm.parser import parse_sprio_output, parse_sshare_output, parse_tres_resources
from stoei.slurm.validation import check_slurm_available, get_current_username
from stoei.slurm.wait_time import calculate_partition_wait_stats
from stoei.themes import DEFAULT_THEME_NAME, REGISTERED_THEMES
from stoei.widgets.cluster_sidebar import ClusterSidebar, ClusterStats, PendingPartitionStats
from stoei.widgets.filterable_table import ColumnConfig, FilterableDataTable
from stoei.widgets.help_screen import HelpScreen
from stoei.widgets.loading_indicator import LoadingIndicator
from stoei.widgets.loading_screen import LoadingScreen, LoadingStep
from stoei.widgets.log_pane import LogPane
from stoei.widgets.node_overview import NodeInfo, NodeOverviewTab
from stoei.widgets.priority_overview import (
    AccountPriority,
    JobPriority,
    PriorityOverviewTab,
    UserPriority,
)
from stoei.widgets.screens import (
    AccountInfoScreen,
    CancelConfirmScreen,
    JobInfoScreen,
    JobInputScreen,
    NodeInfoScreen,
    UserInfoScreen,
)
from stoei.widgets.settings_screen import SettingsScreen
from stoei.widgets.slurm_error_screen import SlurmUnavailableScreen
from stoei.widgets.tabs import TabContainer, TabSwitched
from stoei.widgets.user_overview import (
    UserEnergyStats,
    UserOverviewTab,
    UserPendingStats,
    UserStats,
)

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
    LoadingStep("energy_history", "Loading energy history...", weight=3.0),
    LoadingStep("wait_times", "Calculating wait times...", weight=1.0),
    LoadingStep("fair_share", "Loading fair-share priority...", weight=1.0),
    LoadingStep("job_priority", "Loading job priority factors...", weight=1.0),
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

    # --- Data messages for incremental UI updates ---
    # Each message carries raw data from a background fetch. Handlers run on the
    # main thread so the UI stays responsive between deliveries.

    class JobsDataReady(Message):
        """Posted when user's job data (running + history) is fetched."""

        def __init__(  # noqa: D107
            self,
            running_jobs: list[tuple[str, ...]] | None,
            history_jobs: list[tuple[str, ...]] | None,
            total_jobs: int,
            total_requeues: int,
            max_requeues: int,
        ) -> None:
            super().__init__()
            self.running_jobs = running_jobs
            self.history_jobs = history_jobs
            self.total_jobs = total_jobs
            self.total_requeues = total_requeues
            self.max_requeues = max_requeues

    class NodesDataReady(Message):
        """Posted when cluster node data is fetched."""

        def __init__(self, nodes: list[dict[str, str]]) -> None:  # noqa: D107
            super().__init__()
            self.nodes = nodes

    class AllJobsDataReady(Message):
        """Posted when all-users job data is fetched."""

        def __init__(self, all_jobs: list[tuple[str, ...]]) -> None:  # noqa: D107
            super().__init__()
            self.all_jobs = all_jobs

    class WaitTimeDataReady(Message):
        """Posted when wait-time history is fetched."""

        def __init__(self, wait_time_jobs: list[tuple[str, ...]]) -> None:  # noqa: D107
            super().__init__()
            self.wait_time_jobs = wait_time_jobs

    class PriorityDataReady(Message):
        """Posted when fair-share and priority data is fetched."""

        def __init__(  # noqa: D107
            self,
            fair_share_entries: list[tuple[str, ...]],
            job_priority_entries: list[tuple[str, ...]],
        ) -> None:
            super().__init__()
            self.fair_share_entries = fair_share_entries
            self.job_priority_entries = job_priority_entries

    class RefreshCycleComplete(Message):
        """Posted when all background fetches have completed (success or failure)."""

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
        self._last_history_jobs: list[tuple[str, ...]] = []
        self._last_history_stats: tuple[int, int, int] = (0, 0, 0)
        self._keybindings: KeybindingConfig = self._settings.get_keybindings()
        # Pre-computed data (computed in background worker to avoid UI blocking)
        self._cached_node_infos: list[NodeInfo] = []
        self._cached_cluster_stats: ClusterStats | None = None
        self._cached_running_user_stats: list[UserStats] = []
        self._cached_pending_user_stats: list[UserPendingStats] = []
        self._cached_energy_user_stats: list[UserEnergyStats] = []
        self._cached_user_priorities: list[UserPriority] = []
        self._cached_account_priorities: list[AccountPriority] = []
        self._cached_job_priorities: list[JobPriority] = []

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
                    yield PriorityOverviewTab(id="priority-overview")

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

    def _loading_skip_step(self, idx: int, reason: str) -> None:
        """Update loading screen to show step skipped."""
        screen = self._loading_screen
        if screen:
            self.call_from_thread(lambda: screen.skip_step(idx, reason))

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
        self._loading_update_step(12)
        self._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)
        self._loading_complete_step(12, "Ready")

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

        # Step 7: Fetch wait time history
        self._load_step_wait_times()

        # Step 8: Fetch fair-share priority data
        self._load_step_fair_share()

        # Step 9: Fetch pending job priority factors
        self._load_step_job_priority()

        # Steps 10-11: Calculate statistics
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
        """Execute step 6: Fetch energy history (only at startup, if enabled)."""
        self._loading_update_step(6)

        # Check if energy loading is enabled in settings
        if not self._settings.energy_loading_enabled:
            self._loading_skip_step(6, "Disabled - enable in Settings (s) > Energy Loading")
            self._energy_data_loaded = False
            self._energy_history_jobs = []
            return

        months = self._settings.energy_history_months
        energy_jobs, error = get_energy_job_history(months)
        if error:
            self._loading_fail_step(6, error)
            logger.warning(f"Failed to get {months}-month energy history: {error}")
            energy_jobs = []
            self._energy_data_loaded = False
        else:
            self._loading_complete_step(6, f"{len(energy_jobs)} jobs")
            self._energy_data_loaded = True
        self._energy_history_jobs = energy_jobs

    def _load_step_wait_times(self) -> None:
        """Execute step 7: Fetch wait time history for cluster sidebar."""
        self._loading_update_step(7)
        wait_time_jobs, error = get_wait_time_job_history(hours=1)
        if error:
            self._loading_fail_step(7, error)
            logger.warning(f"Failed to get wait time history: {error}")
            wait_time_jobs = []
        else:
            self._loading_complete_step(7, f"{len(wait_time_jobs)} jobs")
        self._wait_time_jobs = wait_time_jobs

    def _load_step_fair_share(self) -> None:
        """Execute step 8: Fetch fair-share priority data."""
        self._loading_update_step(8)
        fair_share_entries, error = get_fair_share_priority()
        if error:
            self._loading_fail_step(8, error)
            logger.warning(f"Failed to get fair-share priority: {error}")
            fair_share_entries = []
        else:
            self._loading_complete_step(8, f"{len(fair_share_entries)} entries")
        self._fair_share_entries = fair_share_entries

    def _load_step_job_priority(self) -> None:
        """Execute step 9: Fetch pending job priority factors."""
        self._loading_update_step(9)
        job_priority_entries, error = get_pending_job_priority()
        if error:
            self._loading_fail_step(9, error)
            logger.warning(f"Failed to get pending job priority: {error}")
            job_priority_entries = []
        else:
            self._loading_complete_step(9, f"{len(job_priority_entries)} pending jobs")
        self._job_priority_entries = job_priority_entries

    def _load_step_statistics(self) -> None:
        """Execute steps 10-11: Calculate user and cluster statistics."""
        self._loading_update_step(10)
        self._compute_user_overview_cache()
        self._loading_complete_step(10, f"{len(self._cached_running_user_stats)} users")

        self._loading_update_step(11)
        # Pre-compute and cache node infos and cluster stats (runs in worker thread)
        self._cached_node_infos = self._parse_node_infos()
        self._cached_cluster_stats = self._calculate_cluster_stats()
        self._compute_priority_overview_cache()
        logger.debug(
            f"Pre-computed {len(self._cached_node_infos)} node infos, "
            f"{len(self._cached_running_user_stats)} running user stats, "
            f"{len(self._cached_pending_user_stats)} pending user stats, "
            f"{len(self._cached_user_priorities)} user priorities, "
            f"{len(self._cached_account_priorities)} account priorities, "
            f"{len(self._cached_job_priorities)} job priorities"
        )
        self._loading_complete_step(
            11, f"{self._cached_cluster_stats.total_nodes} nodes, {self._cached_cluster_stats.total_gpus} GPUs"
        )

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

        # Apply saved column widths to jobs table
        try:
            jobs_filterable = self.query_one("#jobs-filterable-table", FilterableDataTable)
            self._apply_saved_column_widths("jobs", jobs_filterable)
        except Exception as exc:
            logger.debug(f"Failed to apply saved column widths to jobs table: {exc}")

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
        save_settings(settings)
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
            save_settings(self._settings)
            self._apply_sidebar_width()
            self.notify(f"Sidebar: {new_percent}%", timeout=1)

    def action_sidebar_shrink(self) -> None:
        """Decrease sidebar width by 5%."""
        current_percent = self._settings.sidebar_width_percent
        new_percent = max(MIN_SIDEBAR_WIDTH_PERCENT, current_percent - 5)
        if new_percent != current_percent:
            self._settings = replace(self._settings, sidebar_width_percent=new_percent)
            save_settings(self._settings)
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
            save_settings(self._settings)
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

    # --- Parallel fetch helpers (run inside ThreadPoolExecutor threads) ---

    def _fetch_user_jobs(self) -> tuple[list[tuple[str, ...]] | None, list[tuple[str, ...]] | None, int, int, int]:
        """Fetch user's running jobs and history.

        Returns:
            Tuple of (running_jobs, history_jobs, total_jobs, total_requeues, max_requeues).
        """
        running_jobs: list[tuple[str, ...]] | None
        running_raw, r_error = get_running_jobs()
        if r_error:
            logger.warning(f"Failed to refresh running jobs: {r_error}")
            running_jobs = None
        else:
            running_jobs = running_raw

        history_jobs: list[tuple[str, ...]] | None
        job_history_days = self._settings.job_history_days
        history_raw, total_jobs, total_requeues, max_requeues, h_error = get_job_history(days=job_history_days)
        if h_error:
            logger.warning(f"Failed to refresh job history: {h_error}")
            history_jobs = None
        else:
            history_jobs = history_raw

        return running_jobs, history_jobs, total_jobs, total_requeues, max_requeues

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

    def _fetch_priority(self) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
        """Fetch fair-share and pending job priority data.

        Returns:
            Tuple of (fair_share_entries, job_priority_entries).
        """
        fair_share_entries: list[tuple[str, ...]] = []
        job_priority_entries: list[tuple[str, ...]] = []

        fs_entries, fs_error = get_fair_share_priority()
        if fs_error:
            logger.warning(f"Failed to get fair-share priority: {fs_error}")
        else:
            fair_share_entries = fs_entries
            logger.debug(f"Fetched {len(fair_share_entries)} fair-share entries")

        jp_entries, jp_error = get_pending_job_priority()
        if jp_error:
            logger.warning(f"Failed to get pending job priority: {jp_error}")
        else:
            job_priority_entries = jp_entries
            logger.debug(f"Fetched {len(job_priority_entries)} job priority entries")

        return fair_share_entries, job_priority_entries

    # --- Main refresh worker ---

    def _refresh_data_async(self) -> None:
        """Parallel refresh of SLURM data (runs in background worker thread).

        Fetches independent data sources concurrently via ThreadPoolExecutor and
        posts a Textual Message for each as it completes. Message handlers on the
        main thread update the UI incrementally, keeping it responsive.
        """
        logger.debug("Background refresh starting (parallel)")
        self.call_from_thread(lambda: self._set_loading_indicator(True))
        worker = get_current_worker()

        try:
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {
                    pool.submit(self._fetch_user_jobs): "user_jobs",
                    pool.submit(self._fetch_nodes): "nodes",
                    pool.submit(self._fetch_all_jobs): "all_jobs",
                    pool.submit(self._fetch_wait_time): "wait_time",
                    pool.submit(self._fetch_priority): "priority",
                }

                for future in as_completed(futures):
                    if worker.is_cancelled:
                        logger.debug("Refresh worker cancelled, aborting")
                        return
                    label = futures[future]
                    try:
                        result = future.result()
                        self._post_fetch_message(label, result)
                    except Exception:
                        logger.exception(f"Failed to fetch {label}")

            # Signal that all fetches are done
            self.post_message(self.RefreshCycleComplete())
            logger.debug("Background refresh complete (all fetches done)")

        except Exception:
            logger.exception("Error during parallel refresh")
        finally:
            self.call_from_thread(lambda: self._set_loading_indicator(False))

    def _post_fetch_message(self, label: str, result: object) -> None:
        """Post the appropriate Message for a completed fetch.

        Args:
            label: Identifier for the fetch type.
            result: The data returned by the fetch helper.
        """
        if label == "user_jobs":
            running_jobs, history_jobs, total_jobs, total_requeues, max_requeues = result  # type: ignore[misc]
            self.post_message(self.JobsDataReady(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues))
        elif label == "nodes":
            self.post_message(self.NodesDataReady(result))  # type: ignore[arg-type]
        elif label == "all_jobs":
            self.post_message(self.AllJobsDataReady(result))  # type: ignore[arg-type]
        elif label == "wait_time":
            self.post_message(self.WaitTimeDataReady(result))  # type: ignore[arg-type]
        elif label == "priority":
            fair_share, job_prio = result  # type: ignore[misc]
            self.post_message(self.PriorityDataReady(fair_share, job_prio))

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

    def _update_jobs_table(self, jobs_filterable: FilterableDataTable) -> None:
        """Update the jobs table with cached job data.

        Args:
            jobs_filterable: The FilterableDataTable widget to update.
        """
        jobs = self._sorted_jobs_for_display(self._job_cache.jobs)

        # Convert jobs to row tuples
        rows: list[tuple[str, ...]] = []
        for job in jobs:
            row_values = self._job_row_values(job)
            rows.append(tuple(row_values))

        # Use set_data to update the filterable table
        jobs_filterable.set_data(rows)
        jobs_filterable.display = len(rows) > 0

        logger.debug(f"Jobs table updated: {len(rows)} jobs")

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
                jobs_filterable = self.query_one("#jobs-filterable-table", FilterableDataTable)
                self._update_jobs_table(jobs_filterable)
            except Exception:
                logger.exception("Failed to find jobs table")

        # Always update the My Usage banner (lives on the Jobs tab)
        self._update_my_usage_summary(self._cached_running_user_stats)

        # Update cluster sidebar
        self._update_cluster_sidebar()

        # Update node, user, and priority overview if those tabs are active
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "nodes":
                self._update_node_overview()
            elif tab_container.active_tab == "users":
                self._update_user_overview()
            elif tab_container.active_tab == "priority":
                self._update_priority_overview()
        except Exception as exc:
            logger.debug(f"Failed to update tab-specific overview: {exc}")

        # Check window size and adjust layout
        self._check_window_size()

    # --- Message handlers for incremental data updates ---

    def on_slurm_monitor_jobs_data_ready(self, message: JobsDataReady) -> None:
        """Handle fresh user job data from background fetch."""
        if message.running_jobs is not None:
            self._handle_refresh_fallback(
                message.running_jobs,
                message.history_jobs,
                message.total_jobs,
                message.total_requeues,
                message.max_requeues,
            )
            # Update jobs table immediately
            try:
                jobs_filterable = self.query_one("#jobs-filterable-table", FilterableDataTable)
                self._update_jobs_table(jobs_filterable)
            except Exception:
                logger.exception("Failed to update jobs table from message")
        else:
            self.notify("Running jobs refresh failed - keeping old data", severity="warning")

    def on_slurm_monitor_nodes_data_ready(self, message: NodesDataReady) -> None:
        """Handle fresh cluster node data from background fetch."""
        self._cluster_nodes = message.nodes
        # Pre-compute node infos and cluster stats on the main thread (fast: in-memory iteration)
        self._cached_node_infos = self._parse_node_infos()
        self._cached_cluster_stats = self._calculate_cluster_stats()
        self._update_cluster_sidebar()
        # Update node tab if it's active
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "nodes":
                self._update_node_overview()
        except Exception as exc:
            logger.debug(f"Failed to update node tab from message: {exc}")

    def on_slurm_monitor_all_jobs_data_ready(self, message: AllJobsDataReady) -> None:
        """Handle fresh all-users job data from background fetch."""
        self._all_users_jobs = message.all_jobs
        # Re-compute user stats and cluster stats (pending resources depend on all-jobs)
        self._compute_user_overview_cache()
        self._cached_cluster_stats = self._calculate_cluster_stats()
        self._update_my_usage_summary(self._cached_running_user_stats)
        self._update_cluster_sidebar()
        # Update user tab if it's active
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "users":
                self._apply_user_overview_from_cache()
        except Exception as exc:
            logger.debug(f"Failed to update user tab from message: {exc}")

    def on_slurm_monitor_wait_time_data_ready(self, message: WaitTimeDataReady) -> None:
        """Handle fresh wait-time history from background fetch."""
        self._wait_time_jobs = message.wait_time_jobs
        # Recompute cluster stats to update wait-time stats in sidebar
        self._cached_cluster_stats = self._calculate_cluster_stats()
        self._update_cluster_sidebar()

    def on_slurm_monitor_priority_data_ready(self, message: PriorityDataReady) -> None:
        """Handle fresh priority data from background fetch."""
        self._fair_share_entries = message.fair_share_entries
        self._job_priority_entries = message.job_priority_entries
        self._compute_priority_overview_cache()
        # Update priority tab if it's active
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "priority":
                self._apply_priority_overview_from_cache()
        except Exception as exc:
            logger.debug(f"Failed to update priority tab from message: {exc}")

    def on_slurm_monitor_refresh_cycle_complete(self, _message: RefreshCycleComplete) -> None:
        """Handle completion of a full refresh cycle."""
        logger.debug("Refresh cycle complete - all data sources updated")

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

            cpus, memory_gb, gpu_entries = parse_tres_resources(job[tres_index])
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

        # Calculate wait time statistics
        if self._wait_time_jobs:
            stats.wait_stats_by_partition = calculate_partition_wait_stats(self._wait_time_jobs)
            stats.wait_stats_hours = 1  # Currently hardcoded to 1 hour
            logger.debug(f"Calculated wait stats for {len(stats.wait_stats_by_partition)} partitions")

        return stats

    def _update_node_overview(self) -> None:
        """Update the node overview tab using cached node infos.

        Uses pre-computed node infos from background worker to avoid blocking UI.
        Falls back to computing on-demand if cache is empty (initial load).
        """
        try:
            node_tab = self.query_one("#node-overview", NodeOverviewTab)
            # Use cached node infos (computed in background worker)
            # Fall back to computing if cache is empty (shouldn't happen after initial load)
            node_infos = self._cached_node_infos if self._cached_node_infos else self._parse_node_infos()
            logger.debug(
                f"Updating node overview with {len(node_infos)} nodes (cached={bool(self._cached_node_infos)})"
            )
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
        """Pre-compute priority overview data from cached SLURM results.

        This method is safe to run in a background worker thread.
        """
        if self._fair_share_entries:
            user_data, account_data = parse_sshare_output(self._fair_share_entries)
            self._cached_user_priorities = [
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
            self._cached_account_priorities = [
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
            self._cached_user_priorities = []
            self._cached_account_priorities = []

        if self._job_priority_entries:
            job_data = parse_sprio_output(self._job_priority_entries)
            self._cached_job_priorities = [
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
            self._cached_job_priorities = []

    def _apply_user_overview_from_cache(self) -> None:
        """Apply cached user overview data to the UI (main thread only)."""
        user_tab = self.query_one("#user-overview", UserOverviewTab)
        user_tab.update_users(self._cached_running_user_stats)
        user_tab.update_pending_users(self._cached_pending_user_stats)
        if self._cached_energy_user_stats:
            user_tab.update_energy_users(self._cached_energy_user_stats)
        self._update_my_usage_summary(self._cached_running_user_stats)

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

        summary.update(f"My Usage: {' | '.join(parts)}")

    def _apply_priority_overview_from_cache(self) -> None:
        """Apply cached priority overview data to the UI (main thread only)."""
        priority_tab = self.query_one("#priority-overview", PriorityOverviewTab)
        priority_tab.update_user_priorities(self._cached_user_priorities)
        priority_tab.update_account_priorities(self._cached_account_priorities)
        priority_tab.update_job_priorities(self._cached_job_priorities)

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
                    self.call_from_thread(self._apply_user_overview_from_cache)

                self.run_worker(compute_and_apply, name="compute_user_overview", exclusive=True, thread=True)
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
                    self.call_from_thread(self._apply_priority_overview_from_cache)

                self.run_worker(compute_and_apply, name="compute_priority_overview", exclusive=True, thread=True)
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
        self.call_later(self._update_ui_from_cache)

    def _handle_tab_nodes_switched(self) -> None:
        """Handle switching to the nodes tab."""
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
        self.call_later(self._update_priority_overview)
        try:
            priority_tab = self.query_one("#priority-overview", PriorityOverviewTab)
            priority_table = priority_tab.query_one("#user_priority_table", DataTable)
            priority_table.focus()
            logger.debug("Focused priority table for arrow key navigation")
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
        # Hide all tab contents
        tab_content_ids = [
            "tab-jobs-content",
            "tab-nodes-content",
            "tab-users-content",
            "tab-priority-content",
            "tab-logs-content",
        ]
        for tab_id in tab_content_ids:
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

            # Dispatch to tab-specific handler
            tab_handlers = {
                "jobs": self._handle_tab_jobs_switched,
                "nodes": self._handle_tab_nodes_switched,
                "users": self._handle_tab_users_switched,
                "priority": self._handle_tab_priority_switched,
                "logs": self._handle_tab_logs_switched,
            }
            handler = tab_handlers.get(event.tab_name)
            if handler:
                handler()
        except Exception as exc:
            logger.warning(f"Failed to switch to tab {event.tab_name}: {exc}")

    def action_refresh(self) -> None:
        """Manual refresh action."""
        logger.info("Manual refresh triggered")
        self.notify("Refreshing...")
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
        self.run_worker(self._reload_energy_data_async, exclusive=True, thread=True)

    def _reload_energy_data_async(self) -> None:
        """Load energy data asynchronously (runs in worker thread)."""
        months = self._settings.energy_history_months
        logger.info(f"Reloading energy data for {months} months")

        energy_jobs, error = get_energy_job_history(months)
        if error:
            logger.warning(f"Failed to load energy data: {error}")
            self.call_from_thread(lambda: self.notify(f"Failed to load energy data: {error}", severity="error"))
            self._energy_data_loaded = False
            self._energy_history_jobs = []
            self._cached_energy_user_stats = []
            return

        self._energy_history_jobs = energy_jobs
        self._energy_data_loaded = True
        self._cached_energy_user_stats = UserOverviewTab.aggregate_energy_stats(energy_jobs)
        logger.info(f"Loaded {len(energy_jobs)} energy history jobs")

        # Update the UI
        self.call_from_thread(self._update_energy_ui)

    def _update_energy_ui(self) -> None:
        """Update the energy UI after data reload."""
        try:
            user_tab = self.query_one("#user-overview", UserOverviewTab)
            if self._cached_energy_user_stats:
                user_tab.update_energy_users(self._cached_energy_user_stats)
                # Update the period label
                user_tab.update_energy_period_label(self._settings.energy_history_months)
                self.notify(f"Loaded {len(self._energy_history_jobs)} energy history jobs", severity="information")
            else:
                self.notify("No energy data loaded", severity="warning")
        except Exception as exc:
            logger.error(f"Failed to update energy UI: {exc}", exc_info=True)

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

    def action_switch_tab_priority(self) -> None:
        """Switch to the Priority tab."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab("priority")
        except Exception as exc:
            logger.debug(f"Failed to switch to priority tab: {exc}")

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
            tab_order = ["jobs", "nodes", "users", "priority", "logs"]
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
            tab_order = ["jobs", "nodes", "users", "priority", "logs"]
            current_index = tab_order.index(current_tab)
            previous_index = (current_index - 1) % len(tab_order)
            tab_container.switch_tab(tab_order[previous_index])
        except Exception as exc:
            logger.debug(f"Failed to switch to previous tab: {exc}")

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

        def handle_job_id(job_id: str | None) -> None:
            if job_id:
                logger.info(f"Looking up job info for {job_id}")
                self.notify("Loading job information...", timeout=2)
                # Run SLURM queries in background worker to avoid blocking UI
                self.run_worker(
                    lambda: self._fetch_and_display_job_info(job_id),
                    name="fetch_job_info",
                    thread=True,
                )

        self.push_screen(JobInputScreen(), handle_job_id)

    def _fetch_and_display_job_info(self, job_id: str) -> None:
        """Fetch job info in background and display on main thread.

        Args:
            job_id: The SLURM job ID to fetch.
        """
        query_id = normalize_array_job_id(job_id)
        job_info, error = get_job_info(query_id)
        stdout_path, stderr_path, _ = get_job_log_paths(query_id)
        # Schedule UI update on main thread
        self.call_from_thread(
            lambda: self.push_screen(JobInfoScreen(job_id, job_info, error, stdout_path, stderr_path))
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in data tables.

        Args:
            event: The row selected event.
        """
        # Check which table is selected
        if event.data_table.id == "nodes_table":
            self._show_node_info_for_row(event.data_table, event.row_key)
        elif event.data_table.id in (
            "users_table",
            "pending_users_table",
            "energy_users_table",
            "user_priority_table",
        ):
            self._show_user_info_for_row(event.data_table, event.row_key)
        elif event.data_table.id == "account_priority_table":
            self._show_account_info_for_row(event.data_table, event.row_key)
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

        # Capture cached data references for use in worker thread
        all_users_jobs = self._all_users_jobs
        energy_history_jobs = self._energy_history_jobs
        fair_share_entries = self._fair_share_entries
        job_priority_entries = self._job_priority_entries

        # Get user info in a worker to avoid blocking
        def fetch_user_info() -> None:  # noqa: PLR0912
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

            # Gather pending stats from cached all users jobs
            pending_stats: UserPendingStats | None = None
            if all_users_jobs:
                pending_stats_list = UserOverviewTab.aggregate_pending_user_stats(all_users_jobs)
                for stats in pending_stats_list:
                    if stats.username == username:
                        pending_stats = stats
                        break

            # Gather energy stats from cached energy history
            energy_stats: UserEnergyStats | None = None
            if energy_history_jobs:
                energy_stats_list = UserOverviewTab.aggregate_energy_stats(energy_history_jobs)
                for stats in energy_stats_list:
                    if stats.username == username:
                        energy_stats = stats
                        break

            # Gather fair-share priority info from cached data
            # sshare format: (Account, User, RawShares, NormShares, RawUsage, NormUsage, EffectvUsage, FairShare)
            priority_info: dict[str, str] | None = None
            if fair_share_entries:
                min_sshare_fields = 8
                for entry in fair_share_entries:
                    if len(entry) >= min_sshare_fields and entry[1] == username:
                        priority_info = {
                            "account": entry[0],
                            "raw_shares": entry[2],
                            "norm_shares": entry[3],
                            "raw_usage": entry[4],
                            "norm_usage": entry[5],
                            "effective_usage": entry[6],
                            "fair_share": entry[7],
                        }
                        break

            # Gather pending job priorities for this user
            # sprio format: (JOBID, USER, ACCOUNT, PRIORITY, AGE, FAIRSHARE, JOBSIZE, PARTITION, QOS)
            job_priorities: list[dict[str, str]] = []
            if job_priority_entries:
                min_sprio_fields = 9
                for entry in job_priority_entries:
                    if len(entry) >= min_sprio_fields and entry[1] == username:
                        job_priorities.append(
                            {
                                "job_id": entry[0],
                                "priority": entry[3],
                                "age": entry[4],
                                "fair_share": entry[5],
                                "job_size": entry[6],
                                "partition": entry[7],
                                "qos": entry[8],
                            }
                        )

            formatted_info = format_user_info(
                username,
                user_stats,
                jobs,
                pending_stats=pending_stats,
                energy_stats=energy_stats,
                priority_info=priority_info,
                job_priorities=job_priorities if job_priorities else None,
            )
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

    def _show_account_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show account info for a specific row in the accounts table.

        Args:
            table: The DataTable containing the row.
            row_key: The key of the row to show info for.
        """
        try:
            row_data = table.get_row(row_key)
            account_name = str(row_data[0]).strip()
            # Remove Rich markup tags if present
            account_name = re.sub(r"\[.*?\]", "", account_name).strip()

            if not account_name:
                logger.warning(f"Could not extract account name from row {row_key}")
                self.notify("Could not get account name from selected row", severity="error")
                return

            logger.info(f"Showing info for selected account {account_name}")
            self._show_account_info(account_name)

        except (IndexError, KeyError):
            logger.exception(f"Could not get account name from row {row_key}")
            self.notify("Could not get account name from selected row", severity="error")

    def _show_account_info(self, account_name: str) -> None:
        """Show detailed information for an account/institute.

        Args:
            account_name: The account/institute name to display.
        """
        logger.info(f"Fetching account info for {account_name}")
        self.notify("Loading account information...", timeout=2)

        # Capture cached data references for use in worker thread
        fair_share_entries = self._fair_share_entries
        all_users_jobs = self._all_users_jobs
        job_priority_entries = self._job_priority_entries

        # Get account info in a worker to avoid blocking
        def fetch_account_info() -> None:  # noqa: PLR0912
            # Get account-level priority info from cached sshare data
            # sshare format: (Account, User, RawShares, NormShares, RawUsage, NormUsage, EffectvUsage, FairShare)
            account_priority: dict[str, str] = {}
            users_in_account: list[dict[str, str]] = []

            if fair_share_entries:
                min_sshare_fields = 8
                for entry in fair_share_entries:
                    if len(entry) >= min_sshare_fields and entry[0] == account_name:
                        if entry[1]:  # Has username - this is a user entry
                            users_in_account.append(
                                {
                                    "username": entry[1],
                                    "raw_shares": entry[2],
                                    "norm_shares": entry[3],
                                    "raw_usage": entry[4],
                                    "norm_usage": entry[5],
                                    "effective_usage": entry[6],
                                    "fair_share": entry[7],
                                }
                            )
                        else:  # No username - this is the account-level entry
                            account_priority = {
                                "raw_shares": entry[2],
                                "norm_shares": entry[3],
                                "raw_usage": entry[4],
                                "norm_usage": entry[5],
                                "effective_usage": entry[6],
                                "fair_share": entry[7],
                            }

            # Get usernames in this account for filtering jobs
            usernames_in_account = {u["username"] for u in users_in_account}

            # Filter running jobs for users in this account
            # Job format: (JobID, Name, User, Partition, State, Time, Nodes, NodeList, TRES)
            running_jobs: list[tuple[str, ...]] = []
            pending_jobs: list[tuple[str, ...]] = []

            if all_users_jobs:
                min_job_fields = 5
                username_index = 2
                state_index = 4
                for job in all_users_jobs:
                    if len(job) >= min_job_fields:
                        username = job[username_index].strip()
                        state = job[state_index].strip().upper()
                        if username in usernames_in_account:
                            if state in ("RUNNING", "R"):
                                running_jobs.append(job)
                            elif state in ("PENDING", "PD"):
                                pending_jobs.append(job)

            # Get pending job priorities for users in this account
            # sprio format: (JOBID, USER, ACCOUNT, PRIORITY, AGE, FAIRSHARE, JOBSIZE, PARTITION, QOS)
            job_priorities: list[dict[str, str]] = []
            if job_priority_entries:
                min_sprio_fields = 9
                for entry in job_priority_entries:
                    if len(entry) >= min_sprio_fields:
                        # Check if account matches or user is in account
                        entry_account = entry[2]
                        entry_user = entry[1]
                        if entry_account == account_name or entry_user in usernames_in_account:
                            job_priorities.append(
                                {
                                    "job_id": entry[0],
                                    "user": entry[1],
                                    "account": entry[2],
                                    "priority": entry[3],
                                    "age": entry[4],
                                    "fair_share": entry[5],
                                    "job_size": entry[6],
                                    "partition": entry[7],
                                    "qos": entry[8],
                                }
                            )

            formatted_info = format_account_info(
                account_name,
                account_priority,
                users_in_account,
                running_jobs,
                pending_jobs,
                job_priorities=job_priorities if job_priorities else None,
            )
            self.call_from_thread(lambda: self._display_account_info(account_name, formatted_info, None))

        self.run_worker(fetch_account_info, name="fetch_account_info", thread=True)

    def _display_account_info(self, account_name: str, account_info: str, error: str | None) -> None:
        """Display account information in a modal screen.

        Args:
            account_name: The account/institute name.
            account_info: Formatted account information.
            error: Optional error message.
        """
        self.push_screen(AccountInfoScreen(account_name, account_info, error))
        logger.debug(f"Displayed account info screen for {account_name}")

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
            self.notify("Loading job information...", timeout=2)
            # Run SLURM queries in background worker to avoid blocking UI
            self.run_worker(
                lambda: self._fetch_and_display_job_info(job_id),
                name="fetch_job_info",
                thread=True,
            )
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
            self.notify("Loading job information...", timeout=2)
            # Run SLURM queries in background worker to avoid blocking UI
            self.run_worker(
                lambda: self._fetch_and_display_job_info(job_id),
                name="fetch_job_info",
                thread=True,
            )
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
