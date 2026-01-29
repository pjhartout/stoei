"""User overview tab widget with sub-tabs for running, pending, and energy views."""

import contextlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import ClassVar, Literal, TypedDict

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from stoei.logger import get_logger
from stoei.settings import load_settings
from stoei.slurm.array_parser import parse_array_size
from stoei.slurm.energy import (
    calculate_job_energy_wh,
    format_energy,
    parse_cpu_count_from_tres,
    parse_elapsed_to_seconds,
    parse_gpu_info_from_tres,
)
from stoei.slurm.gpu_parser import (
    aggregate_gpu_counts,
    calculate_total_gpus,
    format_gpu_types,
    has_specific_gpu_types,
    parse_gpu_entries,
)
from stoei.widgets.filterable_table import ColumnConfig, FilterableDataTable
from stoei.widgets.screens import EnergyEnableModal

logger = get_logger(__name__)


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


@dataclass
class UserPendingStats:
    """User pending job resource statistics."""

    username: str
    pending_job_count: int
    pending_cpus: int
    pending_memory_gb: float
    pending_gpus: int
    pending_gpu_types: str = ""


class _UserPendingDataDict(TypedDict):
    """Internal dictionary structure for aggregating user pending statistics."""

    pending_job_count: int
    pending_cpus: int
    pending_memory_gb: float
    pending_gpus: int
    gpu_types: dict[str, int]


@dataclass
class UserEnergyStats:
    """User energy usage statistics over a historical period."""

    username: str
    total_energy_wh: float  # Total energy in Watt-hours
    job_count: int  # Number of completed jobs
    gpu_hours: float  # Total GPU-hours used
    cpu_hours: float  # Total CPU-hours used


class _UserEnergyDataDict(TypedDict):
    """Internal dictionary structure for aggregating user energy statistics."""

    total_energy_wh: float
    job_count: int
    gpu_hours: float
    cpu_hours: float


class SubtabSwitched(Message):
    """Message sent when a sub-tab within the user overview is switched."""

    def __init__(self, subtab_name: str) -> None:
        """Initialize the SubtabSwitched message.

        Args:
            subtab_name: Name of the sub-tab that was switched to.
        """
        super().__init__()
        self.subtab_name = subtab_name


# Type alias for subtab names
SubtabName = Literal["running", "pending", "energy"]


class UserOverviewTab(VerticalScroll):
    """Tab widget displaying user-level overview with sub-tabs."""

    DEFAULT_CSS: ClassVar[str] = """
    UserOverviewTab {
        height: 100%;
        width: 100%;
    }

    #user-subtab-header {
        height: 1;
        width: 100%;
        margin-bottom: 1;
    }

    .subtab-link {
        margin-right: 2;
    }

    .subtab-link.active {
        text-style: bold;
    }

    .subtab-content {
        height: 1fr;
        width: 100%;
    }

    .subtab-hidden {
        display: none;
    }

    #energy-period-info {
        margin-bottom: 1;
        color: $text-muted;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("r", "switch_subtab_running", "Running", show=False),
        Binding("p", "switch_subtab_pending", "Pending", show=False),
        Binding("e", "switch_subtab_energy", "Energy", show=False),
    ]

    # Column configs for each user table
    RUNNING_USERS_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="User", key="user", sortable=True, filterable=True),
        ColumnConfig(name="Jobs", key="jobs", sortable=True, filterable=True),
        ColumnConfig(name="CPUs", key="cpus", sortable=True, filterable=True),
        ColumnConfig(name="Memory (GB)", key="memory", sortable=True, filterable=True),
        ColumnConfig(name="GPUs", key="gpus", sortable=True, filterable=True),
        ColumnConfig(name="GPU Types", key="gpu_types", sortable=True, filterable=True),
        ColumnConfig(name="Nodes", key="nodes", sortable=True, filterable=True),
    ]

    PENDING_USERS_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="User", key="user", sortable=True, filterable=True),
        ColumnConfig(name="Pending Jobs", key="pending_jobs", sortable=True, filterable=True),
        ColumnConfig(name="CPUs Requested", key="cpus", sortable=True, filterable=True),
        ColumnConfig(name="Memory (GB)", key="memory", sortable=True, filterable=True),
        ColumnConfig(name="GPUs Requested", key="gpus", sortable=True, filterable=True),
        ColumnConfig(name="GPU Types", key="gpu_types", sortable=True, filterable=True),
    ]

    ENERGY_USERS_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="User", key="user", sortable=True, filterable=True),
        ColumnConfig(name="Jobs (6mo)", key="jobs", sortable=True, filterable=True),
        ColumnConfig(name="Energy", key="energy", sortable=True, filterable=True),
        ColumnConfig(name="GPU-hours", key="gpu_hours", sortable=True, filterable=True),
        ColumnConfig(name="CPU-hours", key="cpu_hours", sortable=True, filterable=True),
    ]

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
        self.pending_users: list[UserPendingStats] = []
        self.energy_users: list[UserEnergyStats] = []
        self._active_subtab: SubtabName = "running"
        self._settings = load_settings()

    def compose(self) -> ComposeResult:
        """Create the user overview layout with sub-tabs."""
        # Sub-tab header with keyboard shortcuts
        with Horizontal(id="user-subtab-header"):
            yield Static(
                "[bold]User Overview[/bold]  "
                "[bold reverse] r [/bold reverse]Running  "
                "[dim]p[/dim] Pending  "
                "[dim]e[/dim] Energy",
                id="subtab-header-text",
            )

        # Running users sub-tab (default visible)
        with Container(id="subtab-running", classes="subtab-content"):
            yield FilterableDataTable(
                columns=self.RUNNING_USERS_COLUMNS,
                keybind_mode=self._settings.keybind_mode,
                table_id="users_table",
                id="users-filterable-table",
            )

        # Pending users sub-tab (hidden by default)
        with Container(id="subtab-pending", classes="subtab-content subtab-hidden"):
            yield FilterableDataTable(
                columns=self.PENDING_USERS_COLUMNS,
                keybind_mode=self._settings.keybind_mode,
                table_id="pending_users_table",
                id="pending-users-filterable-table",
            )

        # Energy usage sub-tab (hidden by default)
        months = self._settings.energy_history_months
        with Container(id="subtab-energy", classes="subtab-content subtab-hidden"):
            yield Static(
                f"[dim]Energy usage over the last {months} months (100% utilization estimate)[/dim]",
                id="energy-period-info",
            )
            yield FilterableDataTable(
                columns=self.ENERGY_USERS_COLUMNS,
                keybind_mode=self._settings.keybind_mode,
                table_id="energy_users_table",
                id="energy-users-filterable-table",
            )

    def on_mount(self) -> None:
        """Initialize the data tables."""
        # FilterableDataTable handles column setup
        # If we already have data, update the tables
        if self.users:
            self.update_users(self.users)
        if self.pending_users:
            self.update_pending_users(self.pending_users)
        if self.energy_users:
            self.update_energy_users(self.energy_users)

    @property
    def active_subtab(self) -> SubtabName:
        """Get the currently active sub-tab name."""
        return self._active_subtab

    def switch_subtab(self, subtab: SubtabName) -> None:
        """Switch to a different sub-tab.

        Args:
            subtab: Name of the sub-tab to switch to ('running', 'pending', or 'energy').
        """
        if subtab == self._active_subtab:
            return

        # Check if trying to switch to energy tab but data is not loaded
        if subtab == "energy":
            # Access the app's energy data loaded status
            energy_data_loaded = getattr(self.app, "_energy_data_loaded", False)
            if not energy_data_loaded:
                self.app.push_screen(EnergyEnableModal(), self._on_energy_modal_result)
                return

        logger.debug(f"Switching user overview subtab from {self._active_subtab} to {subtab}")

        # Update header to show active tab
        self._update_subtab_header(subtab)

        # Hide all subtab containers
        for container_id in ["subtab-running", "subtab-pending", "subtab-energy"]:
            try:
                container = self.query_one(f"#{container_id}", Container)
                container.add_class("subtab-hidden")
            except Exception as exc:
                logger.debug(f"Failed to hide container {container_id}: {exc}")

        # Show the active subtab container
        active_container_id = f"subtab-{subtab}"
        try:
            active_container = self.query_one(f"#{active_container_id}", Container)
            active_container.remove_class("subtab-hidden")

            # Focus the appropriate filterable table
            filterable_ids = {
                "running": "users-filterable-table",
                "pending": "pending-users-filterable-table",
                "energy": "energy-users-filterable-table",
            }
            filterable_id = filterable_ids.get(subtab)
            if filterable_id:
                filterable_table = self.query_one(f"#{filterable_id}", FilterableDataTable)
                filterable_table.focus()
        except Exception as exc:
            logger.debug(f"Failed to show container {active_container_id}: {exc}")

        self._active_subtab = subtab
        self.post_message(SubtabSwitched(subtab))

    def _update_subtab_header(self, active: SubtabName) -> None:
        """Update the sub-tab header to highlight the active tab.

        Args:
            active: The active sub-tab name.
        """
        try:
            header = self.query_one("#subtab-header-text", Static)

            # Build header with active tab highlighted
            running_style = "[bold reverse] r [/bold reverse]Running" if active == "running" else "[dim]r[/dim] Running"
            pending_style = "[bold reverse] p [/bold reverse]Pending" if active == "pending" else "[dim]p[/dim] Pending"
            energy_style = "[bold reverse] e [/bold reverse]Energy" if active == "energy" else "[dim]e[/dim] Energy"

            header.update(f"[bold]User Overview[/bold]  {running_style}  {pending_style}  {energy_style}")
        except Exception as exc:
            logger.debug(f"Failed to update subtab header: {exc}")

    def action_switch_subtab_running(self) -> None:
        """Switch to the Running sub-tab."""
        self.switch_subtab("running")

    def action_switch_subtab_pending(self) -> None:
        """Switch to the Pending sub-tab."""
        self.switch_subtab("pending")

    def action_switch_subtab_energy(self) -> None:
        """Switch to the Energy sub-tab."""
        self.switch_subtab("energy")

    def _on_energy_modal_result(self, result: str | None) -> None:
        """Handle the result from the EnergyEnableModal.

        Args:
            result: "settings" if user wants to go to settings, "dismiss" otherwise.
        """
        if result == "settings":
            # Navigate to settings screen
            self.app.action_show_settings()  # type: ignore[attr-defined]

    def update_users(self, users: list[UserStats]) -> None:
        """Update the user data table.

        Args:
            users: List of user statistics to display.
        """
        try:
            users_filterable = self.query_one("#users-filterable-table", FilterableDataTable)
        except Exception:
            # Table might not be mounted yet, store users for later
            self.users = users
            return

        # Sort by total CPUs (descending) to show heaviest users first
        sorted_users = sorted(users, key=lambda u: u.total_cpus, reverse=True)
        self.users = sorted_users

        # Build row data
        rows: list[tuple[str, ...]] = []
        for user in sorted_users:
            gpu_types_display = user.gpu_types if user.gpu_types else "N/A"
            rows.append(
                (
                    user.username,
                    str(user.job_count),
                    str(user.total_cpus),
                    f"{user.total_memory_gb:.1f}",
                    str(user.total_gpus) if user.total_gpus > 0 else "0",
                    gpu_types_display,
                    str(user.total_nodes),
                )
            )

        users_filterable.set_data(rows)

    def update_pending_users(self, pending_users: list[UserPendingStats]) -> None:
        """Update the pending users data table.

        Args:
            pending_users: List of pending user statistics to display.
        """
        try:
            pending_filterable = self.query_one("#pending-users-filterable-table", FilterableDataTable)
        except Exception:
            # Table might not be mounted yet, store pending_users for later
            self.pending_users = pending_users
            return

        # Already sorted by pending_cpus in aggregate_pending_user_stats
        self.pending_users = pending_users

        # Build row data
        rows: list[tuple[str, ...]] = []
        for user in pending_users:
            gpu_types_display = user.pending_gpu_types if user.pending_gpu_types else "N/A"
            rows.append(
                (
                    user.username,
                    str(user.pending_job_count),
                    str(user.pending_cpus),
                    f"{user.pending_memory_gb:.1f}",
                    str(user.pending_gpus) if user.pending_gpus > 0 else "0",
                    gpu_types_display,
                )
            )

        pending_filterable.set_data(rows)

    def update_energy_users(self, energy_users: list[UserEnergyStats]) -> None:
        """Update the energy users data table.

        Args:
            energy_users: List of user energy statistics to display.
        """
        try:
            energy_filterable = self.query_one("#energy-users-filterable-table", FilterableDataTable)
        except Exception:
            # Table might not be mounted yet, store energy_users for later
            self.energy_users = energy_users
            return

        # Sort by total energy (descending) to show heaviest users first
        sorted_users = sorted(energy_users, key=lambda u: u.total_energy_wh, reverse=True)
        self.energy_users = sorted_users

        # Build row data
        rows: list[tuple[str, ...]] = []
        for user in sorted_users:
            rows.append(
                (
                    user.username,
                    str(user.job_count),
                    format_energy(user.total_energy_wh),
                    f"{user.gpu_hours:,.0f}",
                    f"{user.cpu_hours:,.0f}",
                )
            )

        energy_filterable.set_data(rows)

    def update_energy_period_label(self, months: int) -> None:
        """Update the energy period label to reflect the configured duration.

        Args:
            months: Number of months of energy history.
        """
        try:
            period_info = self.query_one("#energy-period-info", Static)
            period_info.update(f"[dim]Energy usage over the last {months} months (100% utilization estimate)[/dim]")
        except Exception as exc:
            logger.debug(f"Failed to update energy period label: {exc}")

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
            jobs: List of job tuples from squeue
                (JobID, Name, User, Partition, State, Time, Nodes, NodeList, [TRES]).
                TRES is optional (9th field).

        Returns:
            List of UserStats objects.
        """
        # Constants for job tuple indices
        min_job_fields = 8  # Minimum: JobID, Name, User, Partition, State, Time, Nodes, NodeList
        username_index = 2
        nodes_index = 6
        tres_index = 8  # Optional 9th field

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

    @staticmethod
    def aggregate_pending_user_stats(jobs: list[tuple[str, ...]]) -> list[UserPendingStats]:
        """Aggregate pending jobs into per-user statistics.

        Similar to aggregate_user_stats but:
        - Only includes PENDING/PD jobs
        - Accounts for array job sizes

        Args:
            jobs: List of job tuples from squeue
                (JobID, Name, User, Partition, State, Time, Nodes, NodeList, [TRES]).

        Returns:
            List of UserPendingStats objects sorted by pending CPUs (descending).
        """
        # Job tuple indices
        job_id_index = 0
        username_index = 2
        state_index = 4
        tres_index = 8
        min_job_fields = 8

        def _default_pending_data() -> _UserPendingDataDict:
            """Create default pending data dictionary."""
            return {
                "pending_job_count": 0,
                "pending_cpus": 0,
                "pending_memory_gb": 0.0,
                "pending_gpus": 0,
                "gpu_types": defaultdict(int),
            }

        user_data: dict[str, _UserPendingDataDict] = defaultdict(_default_pending_data)

        for job in jobs:
            if len(job) < min_job_fields:
                continue

            # Only process pending jobs
            state = job[state_index].strip().upper() if len(job) > state_index else ""
            if state not in ("PENDING", "PD"):
                continue

            username = job[username_index].strip() if len(job) > username_index else ""
            if not username:
                continue

            # Get array size (1 for non-array jobs)
            job_id = job[job_id_index].strip() if len(job) > job_id_index else ""
            array_size = parse_array_size(job_id)

            data = user_data[username]
            data["pending_job_count"] += array_size

            # Parse TRES if available
            tres_str = job[tres_index].strip() if len(job) > tres_index else ""
            if not tres_str:
                continue

            cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)
            data["pending_cpus"] += cpus * array_size
            data["pending_memory_gb"] += memory_gb * array_size

            # Process GPU entries
            for gpu_type, gpu_count in gpu_entries:
                scaled_count = gpu_count * array_size
                data["pending_gpus"] += scaled_count
                gpu_types_dict = data["gpu_types"]
                if isinstance(gpu_types_dict, dict):
                    gpu_types_dict[gpu_type] += scaled_count

        # Convert to UserPendingStats list
        result: list[UserPendingStats] = []
        for username, data in user_data.items():
            gpu_types_str = format_gpu_types(data["gpu_types"])
            result.append(
                UserPendingStats(
                    username=username,
                    pending_job_count=data["pending_job_count"],
                    pending_cpus=data["pending_cpus"],
                    pending_memory_gb=data["pending_memory_gb"],
                    pending_gpus=data["pending_gpus"],
                    pending_gpu_types=gpu_types_str,
                )
            )

        # Sort by pending CPUs (descending) to show heaviest users first
        return sorted(result, key=lambda u: u.pending_cpus, reverse=True)

    @staticmethod
    def aggregate_energy_stats(jobs: list[tuple[str, ...]]) -> list[UserEnergyStats]:
        """Aggregate job history into per-user energy statistics.

        Calculates energy consumption based on GPU and CPU usage, assuming 100%
        utilization for the job duration.

        Args:
            jobs: List of job tuples from sacct energy history query.
                Format: (JobID, User, Elapsed, NCPUS, AllocTRES, State).

        Returns:
            List of UserEnergyStats objects sorted by total energy (descending).
        """
        # Job tuple indices for energy history format
        user_index = 1
        elapsed_index = 2
        ncpus_index = 3
        tres_index = 4
        min_job_fields = 5  # State (index 5) is optional for backwards compatibility
        seconds_per_hour = 3600.0

        def _default_energy_data() -> _UserEnergyDataDict:
            """Create default energy data dictionary."""
            return {
                "total_energy_wh": 0.0,
                "job_count": 0,
                "gpu_hours": 0.0,
                "cpu_hours": 0.0,
            }

        user_data: dict[str, _UserEnergyDataDict] = defaultdict(_default_energy_data)

        for job in jobs:
            if len(job) < min_job_fields:
                continue

            username = job[user_index].strip() if len(job) > user_index else ""
            if not username:
                continue

            elapsed_str = job[elapsed_index].strip() if len(job) > elapsed_index else ""
            duration_seconds = parse_elapsed_to_seconds(elapsed_str)
            if duration_seconds <= 0:
                continue

            duration_hours = duration_seconds / seconds_per_hour

            # Parse CPU count - try NCPUS field first, then TRES
            ncpus_str = job[ncpus_index].strip() if len(job) > ncpus_index else ""
            try:
                cpu_count = int(ncpus_str) if ncpus_str else 0
            except ValueError:
                cpu_count = 0

            # Fall back to TRES for CPU count if NCPUS is missing
            tres_str = job[tres_index].strip() if len(job) > tres_index else ""
            if cpu_count == 0 and tres_str:
                cpu_count = parse_cpu_count_from_tres(tres_str)

            # Parse GPU info from TRES
            gpu_entries = parse_gpu_info_from_tres(tres_str)

            # Calculate total GPUs, skipping generic if specific types exist
            gpu_count = 0
            primary_gpu_type = "gpu"
            has_specific = has_specific_gpu_types(gpu_entries)

            for gpu_type, count in gpu_entries:
                if has_specific and gpu_type.lower() == "gpu":
                    continue
                gpu_count += count
                if gpu_type.lower() != "gpu":
                    primary_gpu_type = gpu_type

            # Calculate energy for this job
            energy_wh = calculate_job_energy_wh(
                gpu_count=gpu_count,
                gpu_type=primary_gpu_type,
                cpu_count=cpu_count,
                duration_seconds=duration_seconds,
            )

            # Update user aggregates
            data = user_data[username]
            data["total_energy_wh"] += energy_wh
            data["job_count"] += 1
            data["gpu_hours"] += gpu_count * duration_hours
            data["cpu_hours"] += cpu_count * duration_hours

        # Convert to UserEnergyStats list
        result: list[UserEnergyStats] = []
        for username, data in user_data.items():
            result.append(
                UserEnergyStats(
                    username=username,
                    total_energy_wh=data["total_energy_wh"],
                    job_count=data["job_count"],
                    gpu_hours=data["gpu_hours"],
                    cpu_hours=data["cpu_hours"],
                )
            )

        # Sort by total energy (descending) to show heaviest users first
        return sorted(result, key=lambda u: u.total_energy_wh, reverse=True)
