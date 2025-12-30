"""Node overview tab widget."""

from dataclasses import dataclass
from typing import ClassVar

from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static


@dataclass
class NodeInfo:
    """Node information data."""

    name: str
    state: str
    cpus_alloc: int
    cpus_total: int
    memory_alloc_gb: float
    memory_total_gb: float
    gpus_alloc: int
    gpus_total: int
    partitions: str
    reason: str = ""

    @property
    def cpu_usage_pct(self) -> float:
        """Calculate CPU usage percentage."""
        if self.cpus_total == 0:
            return 0.0
        return (self.cpus_alloc / self.cpus_total) * 100.0

    @property
    def memory_usage_pct(self) -> float:
        """Calculate memory usage percentage."""
        if self.memory_total_gb == 0:
            return 0.0
        return (self.memory_alloc_gb / self.memory_total_gb) * 100.0

    @property
    def gpu_usage_pct(self) -> float:
        """Calculate GPU usage percentage."""
        if self.gpus_total == 0:
            return 0.0
        return (self.gpus_alloc / self.gpus_total) * 100.0


class NodeOverviewTab(VerticalScroll):
    """Tab widget displaying node-level overview."""

    DEFAULT_CSS: ClassVar[str] = """
    NodeOverviewTab {
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
        """Initialize the NodeOverviewTab widget.

        Args:
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled.
        """
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.nodes: list[NodeInfo] = []

    def compose(self) -> None:
        """Create the node overview layout."""
        yield Static("[bold]🖥️  Node Overview[/bold]", id="node-overview-title")
        yield DataTable(id="nodes_table")

    def on_mount(self) -> None:
        """Initialize the data table."""
        nodes_table = self.query_one("#nodes_table", DataTable)
        nodes_table.cursor_type = "row"
        nodes_table.add_columns(
            "Node",
            "State",
            "CPUs",
            "CPU%",
            "Memory",
            "Mem%",
            "GPUs",
            "GPU%",
            "Partitions",
        )

    def update_nodes(self, nodes: list[NodeInfo]) -> None:
        """Update the node data table.

        Args:
            nodes: List of node information to display.
        """
        self.nodes = nodes
        nodes_table = self.query_one("#nodes_table", DataTable)

        # Save cursor position
        cursor_row = nodes_table.cursor_row

        nodes_table.clear()

        for node in nodes:
            # Format CPU usage
            cpu_display = f"{node.cpus_alloc}/{node.cpus_total}"
            cpu_pct = node.cpu_usage_pct
            cpu_pct_str = self._format_pct(cpu_pct)

            # Format memory usage
            mem_display = f"{node.memory_alloc_gb:.1f}/{node.memory_total_gb:.1f} GB"
            mem_pct = node.memory_usage_pct
            mem_pct_str = self._format_pct(mem_pct)

            # Format GPU usage
            if node.gpus_total > 0:
                gpu_display = f"{node.gpus_alloc}/{node.gpus_total}"
                gpu_pct = node.gpu_usage_pct
                gpu_pct_str = self._format_pct(gpu_pct)
            else:
                gpu_display = "N/A"
                gpu_pct_str = "N/A"

            # Format state with color
            state_display = self._format_state(node.state)

            nodes_table.add_row(
                node.name,
                state_display,
                cpu_display,
                cpu_pct_str,
                mem_display,
                mem_pct_str,
                gpu_display,
                gpu_pct_str,
                node.partitions,
            )

        # Restore cursor position
        if cursor_row is not None and nodes_table.row_count > 0:
            new_row = min(cursor_row, nodes_table.row_count - 1)
            nodes_table.move_cursor(row=new_row)

    def _format_pct(self, pct: float) -> str:
        """Format percentage with color coding.

        Args:
            pct: Percentage value.

        Returns:
            Formatted percentage string.
        """
        if pct >= 90:
            return f"[red]{pct:.1f}%[/red]"
        elif pct >= 70:
            return f"[yellow]{pct:.1f}%[/yellow]"
        else:
            return f"[green]{pct:.1f}%[/green]"

    def _format_state(self, state: str) -> str:
        """Format node state with color coding.

        Args:
            state: Node state string.

        Returns:
            Formatted state string.
        """
        state_upper = state.upper()
        if "ALLOCATED" in state_upper or "MIXED" in state_upper:
            return f"[yellow]{state}[/yellow]"
        elif "IDLE" in state_upper:
            return f"[green]{state}[/green]"
        elif "DOWN" in state_upper or "DRAIN" in state_upper:
            return f"[red]{state}[/red]"
        else:
            return state
