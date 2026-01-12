"""Cluster load sidebar widget."""

from dataclasses import dataclass, field
from typing import ClassVar

from textual.widgets import Static

# Conversion constant: 1 TB = 1024 GB
GB_PER_TB = 1024


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


class ClusterSidebar(Static):
    """Widget to display cluster load statistics in a sidebar."""

    DEFAULT_CSS: ClassVar[str] = """
    ClusterSidebar {
        width: 30;
        border: heavy ansi_cyan;
        background: #000000;
        padding: 1;
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
        # Initialize with loading message (use bright_black instead of dim for better compatibility)
        loading_msg = "[bold]Cluster Load[/bold]\n\n[bright_black]Loading cluster data...[/bright_black]"
        super().__init__(loading_msg, name=name, id=id, classes=classes, disabled=disabled)
        self.stats: ClusterStats = ClusterStats()
        self._data_loaded: bool = False

    def update_stats(self, stats: ClusterStats) -> None:
        """Update the cluster statistics display.

        Args:
            stats: Cluster statistics to display.
        """
        self.stats = stats
        self._data_loaded = True
        self.update(self._render_stats())

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

        # Color coding based on availability
        # Thresholds for color coding: green >= 50%, yellow >= 25%, red < 25%
        green_threshold = 50.0
        yellow_threshold = 25.0

        def color_pct(pct: float) -> str:
            """Color code percentage."""
            if pct >= green_threshold:
                return f"[green]{pct:.1f}%[/green]"
            elif pct >= yellow_threshold:
                return f"[yellow]{pct:.1f}%[/yellow]"
            else:
                return f"[red]{pct:.1f}%[/red]"

        # Handle case where data hasn't been loaded yet
        if not self._data_loaded:
            return "[bold]Cluster Load[/bold]\n\n[bright_black]Loading cluster data...[/bright_black]"

        lines = [
            "[bold]Cluster Load[/bold]",
            "",
            "[bold]Nodes:[/bold]",
            f"  Free: {color_pct(nodes_pct)}",
            f"  {stats.free_nodes}/{stats.total_nodes} available",
            "",
            "[bold]CPUs:[/bold]",
            f"  Free: {color_pct(cpus_pct)}",
            f"  {stats.total_cpus - stats.allocated_cpus}/{stats.total_cpus} available",
            "",
            "[bold]Memory:[/bold]",
            f"  Free: {color_pct(memory_pct)}",
            f"  {stats.total_memory_gb - stats.allocated_memory_gb:.1f}/{stats.total_memory_gb:.1f} GB",
        ]

        # Display GPUs by type if available
        if stats.gpus_by_type:
            lines.append("")
            lines.append("[bold]GPUs:[/bold]")
            # Sort by type name for consistent display
            for gpu_type in sorted(stats.gpus_by_type.keys()):
                total, allocated = stats.gpus_by_type[gpu_type]
                free_pct = stats.get_gpu_type_free_pct(gpu_type)
                type_display = gpu_type if gpu_type != "gpu" else "generic"
                lines.append(f"  {type_display}: {allocated}/{total} ({color_pct(free_pct)})")
        elif stats.total_gpus > 0 and gpus_pct is not None:
            # Fallback to old format if no type-specific data
            free_gpus = stats.total_gpus - stats.allocated_gpus
            lines.extend(
                [
                    "",
                    "[bold]GPUs:[/bold]",
                    f"  Total: {stats.total_gpus}",
                    f"  Free: {free_gpus} ({color_pct(gpus_pct)})",
                ]
            )

        # Display pending queue section if there are pending jobs
        if stats.pending_jobs_count > 0:
            lines.append("")
            lines.append("[bold]Pending Queue[/bold]")
            lines.append(f"  {stats.pending_jobs_count} jobs waiting")
            lines.append(f"  CPUs: {stats.pending_cpus:,}")
            # Format memory with appropriate unit
            pending_mem = stats.pending_memory_gb
            if pending_mem >= GB_PER_TB:
                lines.append(f"  Memory: {pending_mem / GB_PER_TB:.1f} TB")
            else:
                lines.append(f"  Memory: {pending_mem:.1f} GB")
            # Display pending GPUs by type if available
            if stats.pending_gpus_by_type:
                lines.append("  GPUs:")
                for gpu_type in sorted(stats.pending_gpus_by_type.keys()):
                    gpu_count = stats.pending_gpus_by_type[gpu_type]
                    type_display = gpu_type if gpu_type != "gpu" else "generic"
                    lines.append(f"    {type_display}: {gpu_count}")
            elif stats.pending_gpus > 0:
                lines.append(f"  GPUs: {stats.pending_gpus}")

        return "\n".join(lines)
