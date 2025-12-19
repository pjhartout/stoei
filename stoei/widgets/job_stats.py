"""Job statistics widget."""

from textual.widgets import Static


class JobStats(Static):
    """Widget to display job statistics."""

    def __init__(self) -> None:
        """Initialize the JobStats widget."""
        super().__init__()
        self.total_jobs: int = 0
        self.total_requeues: int = 0
        self.max_requeues: int = 0
        self.running_jobs: int = 0

    def update_stats(
        self,
        total_jobs: int,
        total_requeues: int,
        max_requeues: int,
        running_jobs: int,
    ) -> None:
        """Update the statistics display.

        Args:
            total_jobs: Total number of jobs in history.
            total_requeues: Total number of requeues across all jobs.
            max_requeues: Maximum requeue count for any single job.
            running_jobs: Number of currently running/pending jobs.
        """
        self.total_jobs = total_jobs
        self.total_requeues = total_requeues
        self.max_requeues = max_requeues
        self.running_jobs = running_jobs
        self.update(self._render_stats())

    def _render_stats(self) -> str:
        """Render the statistics as a string.

        Returns:
            Formatted statistics string with Rich markup.
        """
        return (
            f"[bold]📊 Statistics (Last 30 Days)[/bold]\n"
            f"  Total Jobs: {self.total_jobs}  |  "
            f"Active: {self.running_jobs}  |  "
            f"Total Requeues: {self.total_requeues}  |  "
            f"Max Requeues: {self.max_requeues}"
        )
