"""User overview tab widget."""

import contextlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import ClassVar, TypedDict

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static

from stoei.slurm.gpu_parser import (
    aggregate_gpu_counts,
    calculate_total_gpus,
    format_gpu_types,
    parse_gpu_entries,
)


@dataclass
class UserStats:
    """User resource usage statistics."""

    username: str
    job_count: int
    total_cpus: int
    total_memory_gb: float
    total_gpus: int
    total_nodes: int
    gpu_types: str = ""


class _UserDataDict(TypedDict):
    """Internal dictionary structure for aggregating user statistics."""

    job_count: int
    total_cpus: int
    total_memory_gb: float
    total_gpus: int
    total_nodes: int
    gpu_types: dict[str, int]


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
            "GPU Types",
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
            gpu_types_display = user.gpu_types if user.gpu_types else "N/A"
            users_table.add_row(
                user.username,
                str(user.job_count),
                str(user.total_cpus),
                f"{user.total_memory_gb:.1f}",
                str(user.total_gpus) if user.total_gpus > 0 else "0",
                gpu_types_display,
                str(user.total_nodes),
            )

        # Restore cursor position
        if cursor_row is not None and users_table.row_count > 0:
            new_row = min(cursor_row, users_table.row_count - 1)
            users_table.move_cursor(row=new_row)

    @staticmethod
    def _parse_tres(tres_str: str) -> tuple[int, float, list[tuple[str, int]]]:
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

        # Use shared GPU parser
        gpu_entries = parse_gpu_entries(tres_str)

        return cpus, memory_gb, gpu_entries

    @staticmethod
    def _parse_node_count(nodes_str: str) -> int:
        """Parse node count from nodes string.

        Args:
            nodes_str: Node string in format "4" or "4-8".

        Returns:
            Number of nodes.
        """
        range_parts_count = 2
        try:
            if "-" in nodes_str:
                # Range like "4-8" means 5 nodes
                parts = nodes_str.split("-")
                if len(parts) == range_parts_count:
                    start = int(parts[0])
                    end = int(parts[1])
                    return end - start + 1
            return int(nodes_str)
        except ValueError:
            return 0

    @staticmethod
    def _process_gpu_entries(
        user_data: _UserDataDict,
        gpu_entries: list[tuple[str, int]],
    ) -> None:
        """Process GPU entries and update user data.

        Args:
            user_data: User data dictionary to update.
            gpu_entries: List of (gpu_type, gpu_count) tuples.
        """
        # Use shared GPU parser functions
        gpu_counts = aggregate_gpu_counts(gpu_entries)

        gpu_types_dict = user_data["gpu_types"]
        if isinstance(gpu_types_dict, dict):
            for gpu_type, count in gpu_counts.items():
                gpu_types_dict[gpu_type] += count

        user_data["total_gpus"] += calculate_total_gpus(gpu_entries)

    @staticmethod
    def _process_job_for_user(
        user_data: _UserDataDict,
        job: tuple[str, ...],
        nodes_index: int,
        tres_index: int,
    ) -> None:
        """Process a single job and update user data.

        Args:
            user_data: User data dictionary to update.
            job: Job tuple from squeue.
            nodes_index: Index of nodes in job tuple.
            tres_index: Index of TRES in job tuple.
        """
        user_data["job_count"] += 1

        # Parse nodes (format: "4" or "4-8")
        nodes_str = job[nodes_index].strip() if len(job) > nodes_index else "0"
        node_count = UserOverviewTab._parse_node_count(nodes_str)
        user_data["total_nodes"] += node_count

        # Parse TRES for CPU, memory, and GPU information
        tres_str = job[tres_index].strip() if len(job) > tres_index else ""
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)

        # Use TRES CPU count if available, otherwise estimate from nodes
        if cpus > 0:
            user_data["total_cpus"] += cpus
        else:
            # Fallback: estimate CPUs from nodes (1 CPU per node)
            user_data["total_cpus"] += node_count

        # Add memory from TRES
        user_data["total_memory_gb"] += memory_gb

        # Process GPU entries
        UserOverviewTab._process_gpu_entries(user_data, gpu_entries)

    @staticmethod
    def _format_gpu_types(gpu_types_dict: dict[str, int]) -> str:
        """Format GPU types dictionary into a string.

        Args:
            gpu_types_dict: Dictionary mapping GPU type to count.

        Returns:
            Formatted string like "8x H200" or "4x A100, 2x V100".
        """
        return format_gpu_types(gpu_types_dict)

    @staticmethod
    def _convert_to_user_stats(user_data: dict[str, _UserDataDict]) -> list[UserStats]:
        """Convert user data dictionary to list of UserStats objects.

        Args:
            user_data: Dictionary mapping username to user data.

        Returns:
            List of UserStats objects.
        """
        user_stats: list[UserStats] = []
        for username, data in user_data.items():
            gpu_types_str = UserOverviewTab._format_gpu_types(data["gpu_types"])
            user_stats.append(
                UserStats(
                    username=username,
                    job_count=int(data["job_count"]),
                    total_cpus=int(data["total_cpus"]),
                    total_memory_gb=data["total_memory_gb"],
                    total_gpus=int(data["total_gpus"]),
                    total_nodes=int(data["total_nodes"]),
                    gpu_types=gpu_types_str,
                )
            )
        return user_stats

    @staticmethod
    def aggregate_user_stats(jobs: list[tuple[str, ...]]) -> list[UserStats]:
        """Aggregate job data into user statistics.

        Args:
            jobs: List of job tuples from squeue (JobID, Name, User, State, Time, Nodes, NodeList, [TRES]).
                TRES is optional (8th field).

        Returns:
            List of UserStats objects.
        """
        # Constants for job tuple indices
        min_job_fields = 7  # Minimum: JobID, Name, User, State, Time, Nodes, NodeList
        username_index = 2
        nodes_index = 5
        tres_index = 7  # Optional 8th field

        def _default_user_data() -> _UserDataDict:
            """Create default user data dictionary."""
            return {
                "job_count": 0,
                "total_cpus": 0,
                "total_memory_gb": 0.0,
                "total_gpus": 0,
                "total_nodes": 0,
                "gpu_types": defaultdict(int),
            }

        user_data: dict[str, _UserDataDict] = defaultdict(_default_user_data)

        for job in jobs:
            if len(job) < min_job_fields:
                continue

            username = job[username_index].strip() if len(job) > username_index else ""
            if not username:
                continue

            UserOverviewTab._process_job_for_user(
                user_data[username],
                job,
                nodes_index,
                tres_index,
            )

        return UserOverviewTab._convert_to_user_stats(user_data)
