"""Cluster load sidebar widget."""

from dataclasses import dataclass
from typing import ClassVar

from textual.widgets import Static


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


class ClusterSidebar(Static):
    """Widget to display cluster load statistics in a sidebar."""

    DEFAULT_CSS: ClassVar[str] = """
    ClusterSidebar {
        width: 30;
        border: heavy ansi_blue;
        background: ansi_black;
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
        # Initialize with empty content, will be set in on_mount
        super().__init__("", name=name, id=id, classes=classes, disabled=disabled)
        self.stats: ClusterStats = ClusterStats()
        self._data_loaded: bool = False

    def on_mount(self) -> None:
        """Initialize the widget with initial content."""
        # Set initial loading message
        loading_msg = "[bold]🖥️  Cluster Load[/bold]\n\n[dim]Loading cluster data...[/dim]"
        self.update(loading_msg)

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
        def color_pct(pct: float) -> str:
            """Color code percentage."""
            if pct >= 50:
                return f"[green]{pct:.1f}%[/green]"
            elif pct >= 25:
                return f"[yellow]{pct:.1f}%[/yellow]"
            else:
                return f"[red]{pct:.1f}%[/red]"

        # Handle case where data hasn't been loaded yet
        if not self._data_loaded:
            return "[bold]🖥️  Cluster Load[/bold]\n\n[dim]Loading cluster data...[/dim]"

        lines = [
            "[bold]🖥️  Cluster Load[/bold]",
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

        if stats.total_gpus > 0 and gpus_pct is not None:
            lines.extend(
                [
                    "",
                    "[bold]GPUs:[/bold]",
                    f"  Free: {color_pct(gpus_pct)}",
                    f"  {stats.total_gpus - stats.allocated_gpus}/{stats.total_gpus} available",
                ]
            )

        return "\n".join(lines)
