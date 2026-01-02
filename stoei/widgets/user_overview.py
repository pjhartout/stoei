"""User overview tab widget."""

import contextlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
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

    def compose(self) -> ComposeResult:
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
        # If we already have users data, update the table
        if self.users:
            self.update_users(self.users)

    def update_users(self, users: list[UserStats]) -> None:
        """Update the user data table.

        Args:
            users: List of user statistics to display.
        """
        try:
            users_table = self.query_one("#users_table", DataTable)
        except Exception:
            # Table might not be mounted yet, store users for later
            self.users = users
            return

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
    def _parse_tres(tres_str: str) -> tuple[int, float, int]:
        """Parse TRES string to extract CPU, memory (GB), and GPU counts.

        Args:
            tres_str: TRES string in format like "cpu=32,mem=256G,node=4,gres/gpu=16".

        Returns:
            Tuple of (cpus, memory_gb, gpus).
        """
        cpus = 0
        memory_gb = 0.0
        gpus = 0

        if not tres_str or tres_str.strip() == "":
            return cpus, memory_gb, gpus

        # Parse CPU count
        cpu_match = re.search(r"cpu=(\d+)", tres_str)
        if cpu_match:
            with contextlib.suppress(ValueError):
                cpus = int(cpu_match.group(1))

        # Parse memory (can be in G or M)
        mem_match = re.search(r"mem=(\d+)([GM])", tres_str, re.IGNORECASE)
        if mem_match:
            try:
                mem_value = int(mem_match.group(1))
                mem_unit = mem_match.group(2).upper()
                if mem_unit == "G":
                    memory_gb = float(mem_value)
                elif mem_unit == "M":
                    memory_gb = mem_value / 1024.0
            except ValueError:
                pass

        # Parse GPUs (format: gres/gpu=X)
        gpu_match = re.search(r"gres/gpu=(\d+)", tres_str, re.IGNORECASE)
        if gpu_match:
            with contextlib.suppress(ValueError):
                gpus = int(gpu_match.group(1))

        return cpus, memory_gb, gpus

    @staticmethod
    def aggregate_user_stats(jobs: list[tuple[str, ...]]) -> list[UserStats]:
        """Aggregate job data into user statistics.

        Args:
            jobs: List of job tuples from squeue (JobID, Name, User, State, Time, Nodes, NodeList, TRES).

        Returns:
            List of UserStats objects.
        """
        # Constants for job tuple indices
        min_job_fields = 7
        username_index = 2
        nodes_index = 5
        tres_index = 7
        range_parts_count = 2

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
            if len(job) < min_job_fields:
                continue

            username = job[username_index].strip() if len(job) > username_index else ""
            if not username:
                continue

            user_data[username]["job_count"] += 1

            # Parse nodes (format: "4" or "4-8")
            nodes_str = job[nodes_index].strip() if len(job) > nodes_index else "0"
            try:
                if "-" in nodes_str:
                    # Range like "4-8" means 5 nodes
                    parts = nodes_str.split("-")
                    if len(parts) == range_parts_count:
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

            # Parse TRES for CPU, memory, and GPU information
            tres_str = job[tres_index].strip() if len(job) > tres_index else ""
            cpus, memory_gb, gpus = UserOverviewTab._parse_tres(tres_str)

            # Use TRES CPU count if available, otherwise estimate from nodes
            if cpus > 0:
                user_data[username]["total_cpus"] += cpus
            else:
                # Fallback: estimate CPUs from nodes (1 CPU per node)
                user_data[username]["total_cpus"] += node_count

            # Add memory and GPUs from TRES
            user_data[username]["total_memory_gb"] += memory_gb
            user_data[username]["total_gpus"] += gpus

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
