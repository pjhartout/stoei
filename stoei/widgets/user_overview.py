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
    gpu_types: str = ""


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
        gpu_entries: list[tuple[str, int]] = []

        if not tres_str or tres_str.strip() == "":
            return cpus, memory_gb, gpu_entries

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

        # Parse GPUs - handle both generic (gres/gpu=X) and typed (gres/gpu:type=X) formats
        # Pattern matches: gres/gpu:type=X or gres/gpu=X
        gpu_pattern = re.compile(r"gres/gpu(?::([^=,]+))?=(\d+)", re.IGNORECASE)
        for match in gpu_pattern.finditer(tres_str):
            gpu_type = match.group(1) if match.group(1) else "gpu"
            try:
                gpu_count = int(match.group(2))
                gpu_entries.append((gpu_type, gpu_count))
            except ValueError:
                pass

        return cpus, memory_gb, gpu_entries

    @staticmethod
    def aggregate_user_stats(jobs: list[tuple[str, ...]]) -> list[UserStats]:  # noqa: PLR0912
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
        range_parts_count = 2

        user_data: dict[str, dict[str, int | float | dict[str, int]]] = defaultdict(
            lambda: {
                "job_count": 0,
                "total_cpus": 0,
                "total_memory_gb": 0.0,
                "total_gpus": 0,
                "total_nodes": 0,
                "gpu_types": defaultdict(int),
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
            cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)

            # Use TRES CPU count if available, otherwise estimate from nodes
            if cpus > 0:
                user_data[username]["total_cpus"] += cpus
            else:
                # Fallback: estimate CPUs from nodes (1 CPU per node)
                user_data[username]["total_cpus"] += node_count

            # Add memory from TRES
            user_data[username]["total_memory_gb"] += memory_gb

            # Process GPU entries - track by type
            # Check if we have specific types (non-generic)
            has_specific_types = any(gpu_type != "gpu" for gpu_type, _ in gpu_entries)

            # Process entries: only count specific types if they exist, otherwise count generic
            for gpu_type, gpu_count in gpu_entries:
                if has_specific_types and gpu_type == "gpu":
                    # Skip generic if we have specific types
                    continue
                gpu_type_upper = gpu_type.upper()
                gpu_types_dict = user_data[username]["gpu_types"]
                if isinstance(gpu_types_dict, dict):
                    gpu_types_dict[gpu_type_upper] += gpu_count
                user_data[username]["total_gpus"] += gpu_count

        # Convert to UserStats objects
        user_stats: list[UserStats] = []
        for username, data in user_data.items():
            # Format GPU types string (e.g., "8x H200" or "4x A100, 2x V100")
            gpu_types_dict = data["gpu_types"]
            gpu_type_strs: list[str] = []
            if isinstance(gpu_types_dict, dict) and gpu_types_dict:
                for gpu_type, count in sorted(gpu_types_dict.items()):
                    gpu_type_strs.append(f"{count}x {gpu_type}")
            gpu_types_str = ", ".join(gpu_type_strs)

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
