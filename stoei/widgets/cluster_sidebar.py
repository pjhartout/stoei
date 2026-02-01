"""Cluster load sidebar widget."""

from dataclasses import dataclass, field
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from stoei.colors import get_theme_colors
from stoei.slurm.wait_time import PartitionWaitStats, format_wait_time

# Conversion constant: 1 TB = 1024 GB
GB_PER_TB = 1024


def format_memory_gb(memory_gb: float) -> str:
    """Format a memory quantity in GB into a display string.

    Args:
        memory_gb: Memory in gigabytes.

    Returns:
        Human-friendly string in GB or TB.
    """
    if memory_gb >= GB_PER_TB:
        return f"{memory_gb / GB_PER_TB:.1f} TB"
    return f"{memory_gb:.1f} GB"


@dataclass
class PendingPartitionStats:
    """Aggregated pending resources for a single partition."""

    jobs_count: int = 0
    cpus: int = 0
    memory_gb: float = 0.0
    gpus: int = 0
    gpus_by_type: dict[str, int] = field(default_factory=dict)


@dataclass
class ClusterStats:
    """Cluster statistics data."""

    total_nodes: int = 0
    free_nodes: int = 0
    allocated_nodes: int = 0
    total_cpus: int = 0
    allocated_cpus: int = 0
    total_memory_gb: float = 0.0
    allocated_memory_gb: float = 0.0
    total_gpus: int = 0
    allocated_gpus: int = 0
    gpus_by_type: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Pending job resources
    pending_jobs_count: int = 0
    pending_cpus: int = 0
    pending_memory_gb: float = 0.0
    pending_gpus: int = 0
    pending_gpus_by_type: dict[str, int] = field(default_factory=dict)
    pending_by_partition: dict[str, PendingPartitionStats] = field(default_factory=dict)
    # Wait time statistics per partition (from last N hours)
    wait_stats_by_partition: dict[str, PartitionWaitStats] = field(default_factory=dict)
    wait_stats_hours: int = 1  # Time window used for stats

    @property
    def free_nodes_pct(self) -> float:
        """Calculate percentage of free nodes."""
        if self.total_nodes == 0:
            return 0.0
        return (self.free_nodes / self.total_nodes) * 100.0

    @property
    def free_cpus_pct(self) -> float:
        """Calculate percentage of free CPUs."""
        if self.total_cpus == 0:
            return 0.0
        return ((self.total_cpus - self.allocated_cpus) / self.total_cpus) * 100.0

    @property
    def free_memory_pct(self) -> float:
        """Calculate percentage of free memory."""
        if self.total_memory_gb == 0:
            return 0.0
        return ((self.total_memory_gb - self.allocated_memory_gb) / self.total_memory_gb) * 100.0

    @property
    def free_gpus_pct(self) -> float:
        """Calculate percentage of free GPUs."""
        if self.total_gpus == 0:
            return 0.0
        return ((self.total_gpus - self.allocated_gpus) / self.total_gpus) * 100.0

    def get_gpu_type_free_pct(self, gpu_type: str) -> float:
        """Calculate percentage of free GPUs for a specific type.

        Args:
            gpu_type: The GPU type (e.g., 'h200', 'a100', 'gpu').

        Returns:
            Percentage of free GPUs for this type.
        """
        if gpu_type not in self.gpus_by_type:
            return 0.0
        total, allocated = self.gpus_by_type[gpu_type]
        if total == 0:
            return 0.0
        return ((total - allocated) / total) * 100.0


class ClusterSidebar(VerticalScroll):
    """Scrollable widget to display cluster load statistics in a sidebar."""

    # Minimum and maximum width in characters
    MIN_WIDTH = 25
    MAX_WIDTH = 80

    DEFAULT_CSS: ClassVar[str] = """
    ClusterSidebar {
        width: 30;
        border: heavy $accent;
        background: $panel;
        padding: 1;
        scrollbar-gutter: stable;
        scrollbar-size: 1 1;
        scrollbar-background: $panel;
        scrollbar-color: $border;
        scrollbar-color-hover: $accent-hover;
        scrollbar-color-active: $accent;
    }

    #cluster-sidebar-content {
        width: 100%;
        height: auto;
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
        """Initialize the ClusterSidebar widget.

        Args:
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled.
        """
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.stats: ClusterStats = ClusterStats()
        self._data_loaded: bool = False
        self._content_markup: str = "[bold]Cluster Load[/bold]\n\n[bright_black]Loading cluster data...[/bright_black]"
        self._content_widget: Static | None = None

    def set_width(self, width: int) -> None:
        """Set the sidebar width in characters.

        Args:
            width: The width in characters (clamped to MIN_WIDTH..MAX_WIDTH).
        """
        clamped_width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, width))
        self.styles.width = clamped_width

    def compose(self) -> ComposeResult:
        """Compose the scrollable content."""
        self._content_widget = Static(self._content_markup, id="cluster-sidebar-content")
        yield self._content_widget

    def update_stats(self, stats: ClusterStats) -> None:
        """Update the cluster statistics display.

        Args:
            stats: Cluster statistics to display.
        """
        self.stats = stats
        self._data_loaded = True
        self._content_markup = self._render_stats()
        if self._content_widget is not None:
            self._content_widget.update(self._content_markup)

    def _color_pct(self, pct: float, *, green_threshold: float = 50.0, yellow_threshold: float = 25.0) -> str:
        """Color code a percentage with Rich markup using theme colors."""
        try:
            colors = get_theme_colors(self.app)
        except (LookupError, RuntimeError):
            # Fallback when not mounted to an app
            colors = get_theme_colors(None)
        # Inverted logic: high percentage = good (more resources free)
        color = colors.pct_color(pct, high_threshold=green_threshold, mid_threshold=yellow_threshold, invert=True)
        return f"[{color}]{pct:.1f}%[/{color}]"

    def _append_gpu_section(self, lines: list[str], stats: ClusterStats, *, gpus_pct: float | None) -> None:
        """Append the GPU section to the sidebar output."""
        if stats.gpus_by_type:
            lines.append("")
            lines.append("[bold]GPUs:[/bold]")
            # Sort by type name for consistent display
            for gpu_type in sorted(stats.gpus_by_type.keys()):
                total, allocated = stats.gpus_by_type[gpu_type]
                free_pct = stats.get_gpu_type_free_pct(gpu_type)
                type_display = gpu_type if gpu_type != "gpu" else "generic"
                lines.append(f"  {type_display}: {allocated}/{total} ({self._color_pct(free_pct)})")
            return

        if stats.total_gpus > 0 and gpus_pct is not None:
            free_gpus = stats.total_gpus - stats.allocated_gpus
            lines.extend(
                [
                    "",
                    "[bold]GPUs:[/bold]",
                    f"  Total: {stats.total_gpus}",
                    f"  Free: {free_gpus} ({self._color_pct(gpus_pct)})",
                ]
            )

    def _append_pending_queue_section(self, lines: list[str], stats: ClusterStats) -> None:
        """Append the pending queue section to the sidebar output."""
        if stats.pending_jobs_count <= 0:
            return

        lines.append("")
        lines.append("[bold]Pending Queue[/bold]")

        if not stats.pending_by_partition:
            lines.append("  (No partition breakdown available)")
            return

        for partition, pstats in sorted(stats.pending_by_partition.items(), key=lambda item: item[0].casefold()):
            part_name = partition or "unknown"
            lines.append(f"  {part_name}: {pstats.jobs_count} jobs")

            if pstats.cpus > 0:
                lines.append(f"    CPUs: {pstats.cpus:,}")
            if pstats.memory_gb > 0:
                lines.append(f"    Memory: {format_memory_gb(pstats.memory_gb)}")

            if pstats.gpus_by_type:
                lines.append("    GPUs:")
                for gpu_type in sorted(pstats.gpus_by_type.keys()):
                    gpu_count = pstats.gpus_by_type[gpu_type]
                    type_display = gpu_type if gpu_type != "gpu" else "generic"
                    lines.append(f"      {type_display}: {gpu_count}")
            elif pstats.gpus > 0:
                lines.append(f"    GPUs: {pstats.gpus}")

    def _append_wait_time_section(self, lines: list[str], stats: ClusterStats) -> None:
        """Append the wait time statistics section to the sidebar output.

        Shows wait times for jobs that started in the last N hours.
        Format per partition: mean/median/range
        Example output:
            Wait Times
            Jobs started in last 1h
            (mean/median/range)
              gpu-a100: 5m/3m/1m-2h
              cpu: 30s/15s/5s-3m
        """
        if not stats.wait_stats_by_partition:
            return

        lines.append("")
        lines.append("[bold]Wait Times[/bold]")
        lines.append(f"[bright_black]Jobs started in last {stats.wait_stats_hours}h[/bright_black]")
        lines.append("[bright_black](mean/median/range)[/bright_black]")

        for partition in sorted(stats.wait_stats_by_partition.keys(), key=lambda p: p.casefold()):
            wstats = stats.wait_stats_by_partition[partition]
            mean_str = format_wait_time(wstats.mean_seconds)
            median_str = format_wait_time(wstats.median_seconds)
            min_str = format_wait_time(wstats.min_seconds)
            max_str = format_wait_time(wstats.max_seconds)
            lines.append(f"  {partition}: {mean_str}/{median_str}/{min_str}-{max_str}")

    def _render_stats(self) -> str:
        """Render the statistics as a string.

        Returns:
            Formatted statistics string with Rich markup.
        """
        stats = self.stats

        # Format percentages
        nodes_pct = stats.free_nodes_pct
        cpus_pct = stats.free_cpus_pct
        memory_pct = stats.free_memory_pct
        gpus_pct = stats.free_gpus_pct if stats.total_gpus > 0 else None

        # Handle case where data hasn't been loaded yet
        if not self._data_loaded:
            return "[bold]Cluster Load[/bold]\n\n[bright_black]Loading cluster data...[/bright_black]"

        lines = [
            "[bold]Cluster Load[/bold]",
            "",
            "[bold]Nodes:[/bold]",
            f"  Free: {self._color_pct(nodes_pct)}",
            f"  {stats.free_nodes}/{stats.total_nodes} available",
            "",
            "[bold]CPUs:[/bold]",
            f"  Free: {self._color_pct(cpus_pct)}",
            f"  {stats.total_cpus - stats.allocated_cpus}/{stats.total_cpus} available",
            "",
            "[bold]Memory:[/bold]",
            f"  Free: {self._color_pct(memory_pct)}",
            f"  {stats.total_memory_gb - stats.allocated_memory_gb:.1f}/{stats.total_memory_gb:.1f} GB",
        ]

        self._append_gpu_section(lines, stats, gpus_pct=gpus_pct)
        self._append_wait_time_section(lines, stats)
        self._append_pending_queue_section(lines, stats)

        return "\n".join(lines)
