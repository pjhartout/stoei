"""User overview tab widget."""

from collections import defaultdict
from dataclasses import dataclass
from typing import ClassVar

from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static


@dataclass
class UserStats:
    """User resource usage statistics."""

    username: str
    job_count: int
    total_cpus: int
    total_memory_gb: float
    total_gpus: int
    total_nodes: int


class UserOverviewTab(VerticalScroll):
    """Tab widget displaying user-level overview."""

    DEFAULT_CSS: ClassVar[str] = """
    UserOverviewTab {
        height: 100%;
        width: 100%;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """Initialize the UserOverviewTab widget.

        Args:
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled.
        """
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.users: list[UserStats] = []

    def compose(self) -> None:
        """Create the user overview layout."""
        yield Static("[bold]👥 User Overview[/bold]", id="user-overview-title")
        yield DataTable(id="users_table")

    def on_mount(self) -> None:
        """Initialize the data table."""
        users_table = self.query_one("#users_table", DataTable)
        users_table.cursor_type = "row"
        users_table.add_columns(
            "User",
            "Jobs",
            "CPUs",
            "Memory (GB)",
            "GPUs",
            "Nodes",
        )

    def update_users(self, users: list[UserStats]) -> None:
        """Update the user data table.

        Args:
            users: List of user statistics to display.
        """
        users_table = self.query_one("#users_table", DataTable)

        # Save cursor position
        cursor_row = users_table.cursor_row

        users_table.clear()

        # Sort by total CPUs (descending) to show heaviest users first
        sorted_users = sorted(users, key=lambda u: u.total_cpus, reverse=True)
        self.users = sorted_users

        for user in sorted_users:
            users_table.add_row(
                user.username,
                str(user.job_count),
                str(user.total_cpus),
                f"{user.total_memory_gb:.1f}",
                str(user.total_gpus) if user.total_gpus > 0 else "0",
                str(user.total_nodes),
            )

        # Restore cursor position
        if cursor_row is not None and users_table.row_count > 0:
            new_row = min(cursor_row, users_table.row_count - 1)
            users_table.move_cursor(row=new_row)

    @staticmethod
    def aggregate_user_stats(jobs: list[tuple[str, ...]]) -> list[UserStats]:
        """Aggregate job data into user statistics.

        Args:
            jobs: List of job tuples from squeue (JobID, Name, User, State, Time, Nodes, NodeList).

        Returns:
            List of UserStats objects.
        """
        user_data: dict[str, dict[str, int | float]] = defaultdict(
            lambda: {
                "job_count": 0,
                "total_cpus": 0,
                "total_memory_gb": 0.0,
                "total_gpus": 0,
                "total_nodes": 0,
            }
        )

        for job in jobs:
            if len(job) < 7:
                continue

            username = job[2].strip() if len(job) > 2 else ""
            if not username:
                continue

            user_data[username]["job_count"] += 1

            # Parse nodes (format: "4" or "4-8")
            nodes_str = job[5].strip() if len(job) > 5 else "0"
            try:
                if "-" in nodes_str:
                    # Range like "4-8" means 5 nodes
                    parts = nodes_str.split("-")
                    if len(parts) == 2:
                        start = int(parts[0])
                        end = int(parts[1])
                        node_count = end - start + 1
                    else:
                        node_count = int(nodes_str)
                else:
                    node_count = int(nodes_str)
            except ValueError:
                node_count = 0

            user_data[username]["total_nodes"] += node_count

            # Estimate CPUs (assuming 1 CPU per node as default, could be improved)
            # This is a rough estimate - actual CPU allocation would need job details
            user_data[username]["total_cpus"] += node_count

        # Convert to UserStats objects
        user_stats: list[UserStats] = []
        for username, data in user_data.items():
            user_stats.append(
                UserStats(
                    username=username,
                    job_count=data["job_count"],
                    total_cpus=data["total_cpus"],
                    total_memory_gb=data["total_memory_gb"],
                    total_gpus=data["total_gpus"],
                    total_nodes=data["total_nodes"],
                )
            )

        return user_stats
