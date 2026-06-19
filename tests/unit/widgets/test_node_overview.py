"""Unit tests for the NodeOverviewTab widget."""

import pytest
from stoei.widgets.node_overview import NodeInfo, NodeOverviewTab

from tests.helpers import has_color as _has_color


class TestNodeInfo:
    """Tests for the NodeInfo dataclass."""

    def test_cpu_usage_pct_calculation(self) -> None:
        """Test CPU usage percentage calculation."""
        node = NodeInfo(
            name="node01",
            state="ALLOCATED",
            cpus_alloc=8,
            cpus_total=16,
            memory_alloc_gb=32.0,
            memory_total_gb=64.0,
            gpus_alloc=0,
            gpus_total=0,
            partitions="gpu",
        )
        assert node.cpu_usage_pct == 50.0

    def test_cpu_usage_pct_zero_total(self) -> None:
        """Test CPU usage percentage when total is zero."""
        node = NodeInfo(
            name="node01",
            state="IDLE",
            cpus_alloc=0,
            cpus_total=0,
            memory_alloc_gb=0.0,
            memory_total_gb=0.0,
            gpus_alloc=0,
            gpus_total=0,
            partitions="cpu",
        )
        assert node.cpu_usage_pct == 0.0

    def test_memory_usage_pct_calculation(self) -> None:
        """Test memory usage percentage calculation."""
        node = NodeInfo(
            name="node01",
            state="MIXED",
            cpus_alloc=4,
            cpus_total=8,
            memory_alloc_gb=16.0,
            memory_total_gb=32.0,
            gpus_alloc=0,
            gpus_total=0,
            partitions="gpu",
        )
        assert node.memory_usage_pct == 50.0

    def test_gpu_usage_pct_calculation(self) -> None:
        """Test GPU usage percentage calculation."""
        node = NodeInfo(
            name="node01",
            state="ALLOCATED",
            cpus_alloc=8,
            cpus_total=16,
            memory_alloc_gb=32.0,
            memory_total_gb=64.0,
            gpus_alloc=2,
            gpus_total=4,
            partitions="gpu",
        )
        assert node.gpu_usage_pct == 50.0

    def test_gpu_usage_pct_zero_total(self) -> None:
        """Test GPU usage percentage when total is zero."""
        node = NodeInfo(
            name="node01",
            state="IDLE",
            cpus_alloc=0,
            cpus_total=8,
            memory_alloc_gb=0.0,
            memory_total_gb=32.0,
            gpus_alloc=0,
            gpus_total=0,
            partitions="cpu",
        )
        assert node.gpu_usage_pct == 0.0


class TestNodeOverviewTab:
    """Tests for the NodeOverviewTab widget."""

    @pytest.fixture
    def node_tab(self) -> NodeOverviewTab:
        """Create a NodeOverviewTab widget for testing."""
        return NodeOverviewTab(id="test-node-tab")

    def test_initial_nodes_empty(self, node_tab: NodeOverviewTab) -> None:
        """Test that initial nodes list is empty."""
        assert node_tab.nodes == []

    def test_update_nodes(self, node_tab: NodeOverviewTab) -> None:
        """Test updating nodes."""
        nodes = [
            NodeInfo(
                name="node01",
                state="IDLE",
                cpus_alloc=0,
                cpus_total=16,
                memory_alloc_gb=0.0,
                memory_total_gb=64.0,
                gpus_alloc=0,
                gpus_total=0,
                partitions="cpu",
            ),
            NodeInfo(
                name="node02",
                state="ALLOCATED",
                cpus_alloc=8,
                cpus_total=16,
                memory_alloc_gb=32.0,
                memory_total_gb=64.0,
                gpus_alloc=0,
                gpus_total=0,
                partitions="gpu",
            ),
        ]
        node_tab.update_nodes(nodes)
        assert len(node_tab.nodes) == 2
        assert node_tab.nodes[0].name == "node01"
        assert node_tab.nodes[1].name == "node02"

    def test_format_pct_high_usage(self, node_tab: NodeOverviewTab) -> None:
        """Test percentage formatting for high usage (>=90%)."""
        result = node_tab._format_pct(95.0)
        assert _has_color(result, "red")
        assert "95.0" in result

    def test_format_pct_medium_usage(self, node_tab: NodeOverviewTab) -> None:
        """Test percentage formatting for medium usage (70-90%)."""
        result = node_tab._format_pct(80.0)
        assert _has_color(result, "yellow")
        assert "80.0" in result

    def test_format_pct_low_usage(self, node_tab: NodeOverviewTab) -> None:
        """Test percentage formatting for low usage (<70%)."""
        result = node_tab._format_pct(50.0)
        assert _has_color(result, "green")
        assert "50.0" in result

    def test_format_state_idle(self, node_tab: NodeOverviewTab) -> None:
        """Test state formatting for IDLE nodes."""
        result = node_tab._format_state("IDLE")
        assert _has_color(result, "green")
        assert "IDLE" in result

    def test_format_state_allocated(self, node_tab: NodeOverviewTab) -> None:
        """Test state formatting for ALLOCATED nodes."""
        result = node_tab._format_state("ALLOCATED")
        assert _has_color(result, "yellow")
        assert "ALLOCATED" in result

    def test_format_state_mixed(self, node_tab: NodeOverviewTab) -> None:
        """Test state formatting for MIXED nodes."""
        result = node_tab._format_state("MIXED")
        assert _has_color(result, "yellow")
        assert "MIXED" in result

    def test_format_state_down(self, node_tab: NodeOverviewTab) -> None:
        """Test state formatting for DOWN nodes."""
        result = node_tab._format_state("DOWN")
        assert _has_color(result, "red")
        assert "DOWN" in result

    def test_format_state_drain(self, node_tab: NodeOverviewTab) -> None:
        """Test state formatting for DRAIN nodes."""
        result = node_tab._format_state("DRAIN")
        assert _has_color(result, "red")
        assert "DRAIN" in result

    def test_format_state_unknown(self, node_tab: NodeOverviewTab) -> None:
        """Test state formatting for unknown states."""
        result = node_tab._format_state("UNKNOWN")
        # Unknown states still get a color (foreground color from theme)
        assert "UNKNOWN" in result

    def test_reason_column_in_config(self) -> None:
        """Test that Reason column is present in column configs."""
        column_keys = [col.key for col in NodeOverviewTab.NODE_TABLE_COLUMN_CONFIGS]
        assert "reason" in column_keys

    def test_update_nodes_with_reason(self, node_tab: NodeOverviewTab) -> None:
        """Test that reason field is included in node display."""
        nodes = [
            NodeInfo(
                name="node01",
                state="IDLE+DRAIN",
                cpus_alloc=0,
                cpus_total=16,
                memory_alloc_gb=0.0,
                memory_total_gb=64.0,
                gpus_alloc=0,
                gpus_total=0,
                partitions="cpu",
                reason="Maintenance scheduled",
            ),
        ]
        node_tab.update_nodes(nodes)
        assert node_tab.nodes[0].reason == "Maintenance scheduled"
