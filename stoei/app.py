"""Main Textual TUI application for stoei."""

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Static

from stoei.logging import get_logger
from stoei.slurm.commands import get_job_history, get_job_info, get_running_jobs
from stoei.styles.theme import ANSI_CSS
from stoei.widgets.job_stats import JobStats
from stoei.widgets.screens import JobInfoScreen, JobInputScreen

logger = get_logger(__name__)


class SlurmMonitor(App[None]):
    """Textual TUI app for monitoring SLURM jobs."""

    ENABLE_COMMAND_PALETTE = False
    CSS = ANSI_CSS
    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh Now"),
        ("i", "show_job_info", "Job Info"),
        ("enter", "show_selected_job_info", "View Selected Job"),
    )

    def __init__(self) -> None:
        """Initialize the SLURM monitor app."""
        super().__init__()
        self.refresh_interval: float = 2.0
        self.auto_refresh_timer: Timer | None = None
        logger.info("Initializing SlurmMonitor app")

    def compose(self) -> ComposeResult:
        """Create the UI layout.

        Yields:
            The widgets that make up the application UI.
        """
        yield Header(show_clock=True)

        with Container(id="stats-container"):
            yield JobStats()

        with VerticalScroll(id="running-table"):
            yield Static("[bold]🏃 Currently Running/Pending Jobs[/bold]")
            yield DataTable(id="running_jobs_table")

        with VerticalScroll(id="history-table"):
            yield Static("[bold]📜 Job History (Last 30 Days)[/bold]")
            yield DataTable(id="history_jobs_table")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize tables and start auto-refresh."""
        logger.info("Mounting application")

        running_table = self.query_one("#running_jobs_table", DataTable)
        running_table.cursor_type = "row"
        running_table.add_columns("JobID", "JobName", "State", "Time", "Nodes", "NodeList")

        history_table = self.query_one("#history_jobs_table", DataTable)
        history_table.cursor_type = "row"
        history_table.add_columns("JobID", "JobName", "State", "Restarts", "Elapsed", "ExitCode", "Node")

        self.refresh_data()
        self.auto_refresh_timer = self.set_interval(self.refresh_interval, self.refresh_data)
        logger.info(f"Auto-refresh started with interval {self.refresh_interval}s")

    def refresh_data(self) -> None:
        """Refresh tables and summary statistics."""
        logger.debug("Refreshing data")

        # Get running jobs
        running_jobs = get_running_jobs()
        running_table = self.query_one("#running_jobs_table", DataTable)
        running_table.clear()

        for job in running_jobs:
            running_table.add_row(*job)

        # Get job history
        history_jobs, total_jobs, total_requeues, max_requeues = get_job_history()
        history_table = self.query_one("#history_jobs_table", DataTable)
        history_table.clear()

        for job in history_jobs:
            history_table.add_row(*job)

        # Update statistics
        stats_widget = self.query_one(JobStats)
        stats_widget.update_stats(total_jobs, total_requeues, max_requeues, len(running_jobs))

    def action_refresh(self) -> None:
        """Manual refresh action."""
        logger.info("Manual refresh triggered")
        self.refresh_data()
        self.notify("Data refreshed!")

    def action_show_job_info(self) -> None:
        """Show job info dialog."""

        def handle_job_id(job_id: str | None) -> None:
            if job_id:
                logger.info(f"Looking up job info for {job_id}")
                job_info, error = get_job_info(job_id)
                self.push_screen(JobInfoScreen(job_id, job_info, error))

        self.push_screen(JobInputScreen(), handle_job_id)

    def action_show_selected_job_info(self) -> None:
        """Show job info for the currently selected row in either table."""
        running_table = self.query_one("#running_jobs_table", DataTable)
        history_table = self.query_one("#history_jobs_table", DataTable)

        # Check which table has focus
        focused = self.focused
        if focused is running_table and running_table.row_count > 0:
            table = running_table
        elif focused is history_table and history_table.row_count > 0:
            table = history_table
        elif running_table.row_count > 0:
            table = running_table
        elif history_table.row_count > 0:
            table = history_table
        else:
            self.notify("No jobs to display", severity="warning")
            return

        # Get the job ID from the first column of the selected row
        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row < 0:
            self.notify("No row selected", severity="warning")
            return

        try:
            row_key = table.get_row_at(cursor_row)
            job_id = str(row_key[0]).strip()
            logger.info(f"Showing info for selected job {job_id}")
            job_info, error = get_job_info(job_id)
            self.push_screen(JobInfoScreen(job_id, job_info, error))
        except (IndexError, KeyError):
            logger.error(f"Could not get job ID from row {cursor_row}")
            self.notify("Could not get job ID from selected row", severity="error")

    async def action_quit(self) -> None:
        """Quit the application."""
        logger.info("Quitting application")
        if self.auto_refresh_timer:
            self.auto_refresh_timer.stop()
        self.exit()


def main() -> None:
    """Run the SLURM monitor TUI app."""
    logger.info("Starting stoei")
    app = SlurmMonitor()
    app.run()
    logger.info("Stoei exited")
