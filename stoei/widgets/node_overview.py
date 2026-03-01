"""Node overview tab widget."""

from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from stoei.colors import get_theme_colors
from stoei.settings import load_settings
from stoei.widgets.filterable_table import ColumnConfig, FilterableDataTable


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
    gpu_types: str = ""

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

    NODE_TABLE_COLUMN_CONFIGS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="Node", key="node", sortable=True, filterable=True),
        ColumnConfig(name="State", key="state", sortable=True, filterable=True),
        ColumnConfig(name="CPUs", key="cpus", sortable=True, filterable=True),
        ColumnConfig(name="CPU%", key="cpu_pct", sortable=True, filterable=False),
        ColumnConfig(name="Memory", key="memory", sortable=True, filterable=True),
        ColumnConfig(name="Mem%", key="mem_pct", sortable=True, filterable=False),
        ColumnConfig(name="GPUs", key="gpus", sortable=True, filterable=True),
        ColumnConfig(name="GPU%", key="gpu_pct", sortable=True, filterable=False),
        ColumnConfig(name="GPU Types", key="gpu_types", sortable=True, filterable=True),
        ColumnConfig(name="Partitions", key="partitions", sortable=True, filterable=True),
        ColumnConfig(name="Reason", key="reason", sortable=True, filterable=True),
    ]

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
        self._settings = load_settings()

    def compose(self) -> ComposeResult:
        """Create the node overview layout."""
        yield Static("[bold]Node Overview[/bold]", id="node-overview-title")
        yield FilterableDataTable(
            columns=self.NODE_TABLE_COLUMN_CONFIGS,
            keybind_mode=self._settings.keybind_mode,
            table_id="nodes_table",
            id="nodes-filterable-table",
        )

    def on_mount(self) -> None:
        """Initialize the data table."""
        # FilterableDataTable handles column setup
        # If we already have nodes data, update the table
        if self.nodes:
            self.update_nodes(self.nodes)

    def update_nodes(self, nodes: list[NodeInfo]) -> None:
        """Update the node data table.

        Args:
            nodes: List of node information to display.
        """
        self.nodes = nodes
        try:
            nodes_filterable = self.query_one("#nodes-filterable-table", FilterableDataTable)
        except Exception:
            # Table might not be mounted yet, store nodes for later
            return

        # Build row data
        rows: list[tuple[str, ...]] = []
        for node in nodes:
            # Format CPU usage
            cpu_display = f"{node.cpus_alloc}/{node.cpus_total}"
            cpu_pct_str = self._format_pct(node.cpu_usage_pct)

            # Format memory usage
            mem_display = f"{node.memory_alloc_gb:.1f}/{node.memory_total_gb:.1f} GB"
            mem_pct_str = self._format_pct(node.memory_usage_pct)

            # Format GPU usage
            if node.gpus_total > 0:
                gpu_display = f"{node.gpus_alloc}/{node.gpus_total}"
                gpu_pct_str = self._format_pct(node.gpu_usage_pct)
                gpu_types_display = node.gpu_types if node.gpu_types else "N/A"
            else:
                gpu_display = "N/A"
                gpu_pct_str = "N/A"
                gpu_types_display = "N/A"

            # Format state with color
            state_display = self._format_state(node.state)

            # Ensure all fields have valid values
            node_name = node.name if node.name else "N/A"
            partitions_display = node.partitions if node.partitions else "N/A"

            reason_display = node.reason if node.reason else ""

            rows.append(
                (
                    node_name,
                    state_display,
                    cpu_display,
                    cpu_pct_str,
                    mem_display,
                    mem_pct_str,
                    gpu_display,
                    gpu_pct_str,
                    gpu_types_display,
                    partitions_display,
                    reason_display,
                )
            )

        # Use set_data to update with filtering/sorting support
        nodes_filterable.set_data(rows)

    def _format_pct(self, pct: float) -> str:
        """Format percentage with color coding.

        Args:
            pct: Percentage value.

        Returns:
            Formatted percentage string.
        """
        try:
            colors = get_theme_colors(self.app)
        except (LookupError, RuntimeError):
            # Fallback when not mounted to an app
            colors = get_theme_colors(None)
        color = colors.pct_color(pct, high_threshold=90.0, mid_threshold=70.0, invert=False)
        return f"[{color}]{pct:.1f}%[/{color}]"

    def _format_state(self, state: str) -> str:
        """Format node state with color coding.

        Args:
            state: Node state string.

        Returns:
            Formatted state string.
        """
        try:
            colors = get_theme_colors(self.app)
        except (LookupError, RuntimeError):
            # Fallback when not mounted to an app
            colors = get_theme_colors(None)
        color = colors.state_color(state)
        return f"[{color}]{state}[/{color}]"
