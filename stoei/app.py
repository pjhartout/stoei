"""Main Textual TUI application for stoei."""

from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.timer import Timer
from textual.widgets import Button, DataTable, Footer, Header, Static
from textual.widgets.data_table import RowKey
from textual.worker import Worker, WorkerState

from stoei.logging import add_tui_sink, get_logger, remove_tui_sink
from stoei.slurm.cache import JobCache, JobState
from stoei.slurm.commands import cancel_job, get_job_info, get_job_log_paths
from stoei.slurm.validation import check_slurm_available
from stoei.widgets.job_stats import JobStats
from stoei.widgets.log_pane import LogPane
from stoei.widgets.screens import CancelConfirmScreen, JobInfoScreen, JobInputScreen
from stoei.widgets.slurm_error_screen import SlurmUnavailableScreen

logger = get_logger(__name__)

# Path to styles directory
STYLES_DIR = Path(__file__).parent / "styles"

# Refresh interval in seconds (increased for better performance)
REFRESH_INTERVAL = 5.0


class SlurmMonitor(App[None]):
    """Textual TUI app for monitoring SLURM jobs."""

    ENABLE_COMMAND_PALETTE = False
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
    )

    def __init__(self) -> None:
        """Initialize the SLURM monitor app."""
        super().__init__()
        self.refresh_interval: float = REFRESH_INTERVAL
        self.auto_refresh_timer: Timer | None = None
        self._job_cache: JobCache = JobCache()
        self._refresh_worker: Worker[None] | None = None
        self._initial_load_complete: bool = False
        self._log_sink_id: int | None = None
        logger.info("Initializing SlurmMonitor app")

    def compose(self) -> ComposeResult:
        """Create the UI layout.

        Yields:
            The widgets that make up the application UI.
        """
        yield Header(show_clock=True)

        with Container(id="stats-container"):
            yield JobStats()

        with VerticalScroll(id="jobs-panel"):
            with Horizontal(id="jobs-header"):
                yield Static("[bold]📋 All Jobs[/bold]", id="jobs-title")
                yield Button("🗑️ Cancel Job", variant="error", id="cancel-job-btn")
            yield DataTable(id="jobs_table")

        with Container(id="log-panel"):
            yield Static("[bold]📝 Logs[/bold]", id="log-title")
            yield LogPane(id="log_pane")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize table and start data loading."""
        # Check SLURM availability first
        is_available, error_msg = check_slurm_available()
        if not is_available:
            logger.error(f"SLURM not available: {error_msg}")
            self.push_screen(SlurmUnavailableScreen())
            return

        # Set up log pane as a loguru sink
        log_pane = self.query_one("#log_pane", LogPane)
        self._log_sink_id = add_tui_sink(log_pane.sink, level="DEBUG")

        logger.info("Mounting application")

        jobs_table = self.query_one("#jobs_table", DataTable)
        jobs_table.cursor_type = "row"
        jobs_table.add_columns("JobID", "Name", "State", "Time", "Nodes", "NodeList")

        # Show loading message
        self.notify("Loading job data...", timeout=2)

        # Initial data load in background worker
        self._start_refresh_worker()

    def _start_refresh_worker(self) -> None:
        """Start background worker for data refresh."""
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
        """Refresh data from SLURM (runs in background worker thread)."""
        logger.debug("Background refresh starting")

        # Workers run in a separate thread, so blocking calls are safe
        self._job_cache.refresh()

        # Schedule UI update on main thread
        self.call_from_thread(self._update_ui_from_cache)

    def _update_ui_from_cache(self) -> None:
        """Update UI components from cached data (must run on main thread)."""
        jobs_table = self.query_one("#jobs_table", DataTable)

        # Save cursor position before clearing
        cursor_row = jobs_table.cursor_row

        jobs_table.clear()

        # Add jobs from cache with state-based styling
        jobs = self._job_cache.jobs
        for job in jobs:
            # Apply state-based row styling using Rich markup
            state_display = self._format_state(job.state, job.state_category)
            jobs_table.add_row(
                job.job_id,
                job.name,
                state_display,
                job.time,
                job.nodes,
                job.node_list,
            )

        # Restore cursor position if possible
        if cursor_row is not None and jobs_table.row_count > 0:
            new_row = min(cursor_row, jobs_table.row_count - 1)
            jobs_table.move_cursor(row=new_row)

        # Update statistics
        total_jobs, total_requeues, max_requeues, running, pending = self._job_cache.stats
        stats_widget = self.query_one(JobStats)
        stats_widget.update_stats(total_jobs, total_requeues, max_requeues, running + pending)

        # Start auto-refresh timer after initial load
        if not self._initial_load_complete:
            self._initial_load_complete = True
            self.auto_refresh_timer = self.set_interval(self.refresh_interval, self._start_refresh_worker)
            logger.info(f"Auto-refresh started with interval {self.refresh_interval}s")

            # Focus the table
            jobs_table.focus()

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
            JobState.CANCELLED: f"[dim]{state}[/dim]",
            JobState.TIMEOUT: f"[red]{state}[/red]",
        }
        return state_formats.get(category, state)

    def action_refresh(self) -> None:
        """Manual refresh action."""
        logger.info("Manual refresh triggered")
        self.notify("Refreshing...")
        self._start_refresh_worker()

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
        """Handle row selection (Enter key) in DataTable.

        Args:
            event: The row selection event from the DataTable.
        """
        self._show_job_info_for_row(event.data_table, event.row_key)

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
        except (IndexError, KeyError) as exc:
            logger.error(f"Could not get job ID from row {row_key}: {exc}")
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
            logger.error(f"Could not get job ID from row {cursor_row}")
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
                    success, error = cancel_job(job_id)
                    if success:
                        logger.info(f"Successfully cancelled job {job_id}")
                        self.notify(f"Job {job_id} cancelled", severity="information")
                        self._start_refresh_worker()  # Refresh to update state
                    else:
                        logger.error(f"Failed to cancel job {job_id}: {error}")
                        self.notify(f"Failed to cancel: {error}", severity="error")

            self.push_screen(CancelConfirmScreen(job_id, job_name), handle_confirmation)

        except (IndexError, KeyError) as exc:
            logger.error(f"Could not get job ID from row {cursor_row}: {exc}")
            self.notify("Could not get job ID from selected row", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: The button press event.
        """
        if event.button.id == "cancel-job-btn":
            self.action_cancel_job()

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
    logger.info("Starting stoei")
    app = SlurmMonitor()
    app.run()
    logger.info("Stoei exited")
