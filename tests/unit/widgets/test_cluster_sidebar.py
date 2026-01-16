"""Unit tests for the ClusterSidebar widget."""

import pytest
from stoei.colors import FALLBACK_COLORS
from stoei.widgets.cluster_sidebar import ClusterSidebar, ClusterStats, PendingPartitionStats


def _has_color(result: str, color_name: str) -> bool:
    """Check if result contains a color (either name or hex value).

    Args:
        result: The formatted string to check.
        color_name: Semantic color name (success, warning, error) or ANSI name (green, yellow, red).

    Returns:
        True if the result contains a color markup.
    """
    # Map ANSI names to semantic names
    ansi_to_semantic = {
        "green": "success",
        "yellow": "warning",
        "red": "error",
    }
    semantic_name = ansi_to_semantic.get(color_name, color_name)

    # Check for ANSI color name (legacy)
    if f"[{color_name}]" in result:
        return True
    # Check for hex color from fallback colors
    return bool(semantic_name in FALLBACK_COLORS and FALLBACK_COLORS[semantic_name] in result)


class TestClusterStats:
    """Tests for the ClusterStats dataclass."""

    def test_initial_values(self) -> None:
        """Test initial default values."""
        stats = ClusterStats()
        assert stats.total_nodes == 0
        assert stats.free_nodes == 0
        assert stats.allocated_nodes == 0
        assert stats.total_cpus == 0
        assert stats.allocated_cpus == 0
        assert stats.total_memory_gb == 0.0
        assert stats.allocated_memory_gb == 0.0
        assert stats.total_gpus == 0
        assert stats.allocated_gpus == 0

    def test_free_nodes_pct_zero_total(self) -> None:
        """Test free_nodes_pct when total_nodes is zero."""
        stats = ClusterStats(total_nodes=0, free_nodes=0)
        assert stats.free_nodes_pct == 0.0

    def test_free_nodes_pct_calculation(self) -> None:
        """Test free_nodes_pct calculation."""
        stats = ClusterStats(total_nodes=100, free_nodes=30)
        assert stats.free_nodes_pct == 30.0

    def test_free_cpus_pct_calculation(self) -> None:
        """Test free_cpus_pct calculation."""
        stats = ClusterStats(total_cpus=1000, allocated_cpus=700)
        assert stats.free_cpus_pct == 30.0

    def test_free_memory_pct_calculation(self) -> None:
        """Test free_memory_pct calculation."""
        stats = ClusterStats(total_memory_gb=1000.0, allocated_memory_gb=250.0)
        assert stats.free_memory_pct == 75.0

    def test_free_gpus_pct_calculation(self) -> None:
        """Test free_gpus_pct calculation."""
        stats = ClusterStats(total_gpus=50, allocated_gpus=20)
        assert stats.free_gpus_pct == 60.0

    def test_free_gpus_pct_zero_total(self) -> None:
        """Test free_gpus_pct when total_gpus is zero."""
        stats = ClusterStats(total_gpus=0, allocated_gpus=0)
        assert stats.free_gpus_pct == 0.0


class TestClusterSidebar:
    """Tests for the ClusterSidebar widget."""

    @pytest.fixture
    def cluster_sidebar(self) -> ClusterSidebar:
        """Create a ClusterSidebar widget for testing."""
        return ClusterSidebar(id="test-sidebar")

    def test_initial_stats(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test initial statistics are zero."""
        assert cluster_sidebar.stats.total_nodes == 0
        assert cluster_sidebar.stats.total_cpus == 0

    def test_update_stats(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test updating statistics."""
        new_stats = ClusterStats(
            total_nodes=100,
            free_nodes=50,
            allocated_nodes=50,
            total_cpus=1000,
            allocated_cpus=500,
            total_memory_gb=2000.0,
            allocated_memory_gb=1000.0,
            total_gpus=50,
            allocated_gpus=25,
        )
        cluster_sidebar.update_stats(new_stats)
        assert cluster_sidebar.stats.total_nodes == 100
        assert cluster_sidebar.stats.free_nodes == 50

    def test_render_stats_contains_cluster_load(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that rendered stats contain cluster load title."""
        rendered = cluster_sidebar._render_stats()
        assert "Cluster Load" in rendered

    def test_render_stats_contains_nodes(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that rendered stats contain nodes information."""
        stats = ClusterStats(total_nodes=100, free_nodes=50)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "Nodes" in rendered
        assert "50" in rendered
        assert "100" in rendered

    def test_render_stats_contains_cpus(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that rendered stats contain CPUs information."""
        stats = ClusterStats(total_cpus=1000, allocated_cpus=300)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "CPUs" in rendered
        assert "700" in rendered  # free CPUs
        assert "1000" in rendered

    def test_render_stats_contains_memory(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that rendered stats contain memory information."""
        stats = ClusterStats(total_memory_gb=2000.0, allocated_memory_gb=500.0)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "Memory" in rendered
        assert "GB" in rendered

    def test_render_stats_with_gpus(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that rendered stats contain GPUs when available."""
        stats = ClusterStats(total_gpus=50, allocated_gpus=20)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "GPUs" in rendered
        assert "30" in rendered  # free GPUs
        assert "50" in rendered
        assert "free" in rendered.lower()  # Should show "free" in the display

    def test_render_stats_without_gpus(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that rendered stats don't contain GPUs when not available."""
        stats = ClusterStats(total_gpus=0, allocated_gpus=0)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "GPUs" not in rendered

    def test_render_stats_color_coding_high_availability(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test color coding for high availability (>=50%)."""
        stats = ClusterStats(total_nodes=100, free_nodes=60)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert _has_color(rendered, "green")

    def test_render_stats_color_coding_medium_availability(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test color coding for medium availability (25-50%)."""
        stats = ClusterStats(total_nodes=100, free_nodes=30)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert _has_color(rendered, "yellow")

    def test_render_stats_color_coding_low_availability(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test color coding for low availability (<25%)."""
        stats = ClusterStats(total_nodes=100, free_nodes=10)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert _has_color(rendered, "red")

    def test_render_stats_loading_state(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that loading state shows loading message."""
        rendered = cluster_sidebar._render_stats()
        assert "Loading cluster data" in rendered or "bright_black" in rendered
        assert not cluster_sidebar._data_loaded

    def test_render_stats_after_data_loaded(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that stats render correctly after data is loaded."""
        stats = ClusterStats(total_nodes=10, free_nodes=5)
        cluster_sidebar.update_stats(stats)
        assert cluster_sidebar._data_loaded
        rendered = cluster_sidebar._render_stats()
        assert "Loading cluster data" not in rendered
        assert "Nodes" in rendered

    def test_update_stats_sets_data_loaded_flag(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that update_stats sets the _data_loaded flag."""
        assert not cluster_sidebar._data_loaded
        stats = ClusterStats(total_nodes=10, free_nodes=5)
        cluster_sidebar.update_stats(stats)
        assert cluster_sidebar._data_loaded

    def test_render_stats_with_zero_values(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test rendering with all zero values."""
        stats = ClusterStats()
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "0/0" in rendered
        assert "0.0/0.0" in rendered or "0/0" in rendered

    def test_render_stats_gpu_none_handling(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that None gpu_pct doesn't cause errors."""
        stats = ClusterStats(total_gpus=0, allocated_gpus=0)
        cluster_sidebar.update_stats(stats)
        # Should not raise an error
        rendered = cluster_sidebar._render_stats()
        assert "GPUs" not in rendered

    def test_render_stats_boundary_values(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test rendering with boundary percentage values."""
        # Exactly 50% (should be green/success)
        stats = ClusterStats(total_nodes=100, free_nodes=50)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert _has_color(rendered, "green")

        # Exactly 25% (should be yellow/warning)
        stats = ClusterStats(total_nodes=100, free_nodes=25)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert _has_color(rendered, "yellow")

        # Just below 25% (should be red/error)
        stats = ClusterStats(total_nodes=100, free_nodes=24)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert _has_color(rendered, "red")

    def test_render_stats_memory_formatting(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that memory values are formatted with one decimal place."""
        stats = ClusterStats(total_memory_gb=1234.567, allocated_memory_gb=567.891)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        # Should contain formatted memory values
        assert "GB" in rendered
        # Check for decimal formatting (one decimal place)
        import re

        memory_matches = re.findall(r"(\d+\.\d+)\s*GB", rendered)
        assert len(memory_matches) > 0
        for match in memory_matches:
            # Each match should have exactly one decimal place
            assert len(match.split(".")[1]) == 1

    def test_render_stats_cpu_calculation(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that CPU calculation shows free CPUs correctly."""
        stats = ClusterStats(total_cpus=100, allocated_cpus=30)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        # Should show 70 free CPUs (100 - 30)
        assert "70" in rendered
        assert "100" in rendered

    def test_multiple_updates(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that multiple updates work correctly."""
        stats1 = ClusterStats(total_nodes=10, free_nodes=5)
        cluster_sidebar.update_stats(stats1)
        assert cluster_sidebar.stats.total_nodes == 10

        stats2 = ClusterStats(total_nodes=20, free_nodes=15)
        cluster_sidebar.update_stats(stats2)
        assert cluster_sidebar.stats.total_nodes == 20
        assert cluster_sidebar.stats.free_nodes == 15


class TestClusterStatsPendingResources:
    """Tests for pending resource fields in ClusterStats."""

    def test_pending_fields_initial_values(self) -> None:
        """Test initial default values for pending fields."""
        stats = ClusterStats()
        assert stats.pending_jobs_count == 0
        assert stats.pending_cpus == 0
        assert stats.pending_memory_gb == 0.0
        assert stats.pending_gpus == 0
        assert stats.pending_gpus_by_type == {}
        assert stats.pending_by_partition == {}

    def test_pending_fields_with_values(self) -> None:
        """Test pending fields with set values."""
        stats = ClusterStats(
            pending_jobs_count=42,
            pending_cpus=1280,
            pending_memory_gb=10240.0,
            pending_gpus=64,
            pending_gpus_by_type={"h200": 32, "a100": 16, "gpu": 16},
            pending_by_partition={
                "gpu": PendingPartitionStats(jobs_count=40, cpus=1200, memory_gb=10000.0, gpus=64),
                "cpu": PendingPartitionStats(jobs_count=2, cpus=80, memory_gb=240.0, gpus=0),
            },
        )
        assert stats.pending_jobs_count == 42
        assert stats.pending_cpus == 1280
        assert stats.pending_memory_gb == 10240.0
        assert stats.pending_gpus == 64
        assert stats.pending_gpus_by_type == {"h200": 32, "a100": 16, "gpu": 16}
        assert stats.pending_by_partition["gpu"].jobs_count == 40
        assert stats.pending_by_partition["cpu"].jobs_count == 2


class TestClusterSidebarPendingQueue:
    """Tests for pending queue display in ClusterSidebar."""

    @pytest.fixture
    def cluster_sidebar(self) -> ClusterSidebar:
        """Create a ClusterSidebar widget for testing."""
        return ClusterSidebar(id="test-sidebar")

    def test_render_stats_no_pending_jobs(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that pending section is not displayed when no pending jobs."""
        stats = ClusterStats(total_nodes=10, free_nodes=5, pending_jobs_count=0)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "Pending Queue" not in rendered

    def test_render_stats_with_pending_jobs(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that pending section is displayed when there are pending jobs."""
        stats = ClusterStats(
            total_nodes=10,
            free_nodes=5,
            pending_jobs_count=42,
            pending_cpus=1280,
            pending_memory_gb=512.0,
            pending_gpus=64,
            pending_by_partition={
                "cpu": PendingPartitionStats(jobs_count=2, cpus=64, memory_gb=512.0, gpus=0),
                "gpu": PendingPartitionStats(jobs_count=40, cpus=1216, memory_gb=0.0, gpus=64),
            },
        )
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "Pending Queue" in rendered
        assert "  cpu: 2 jobs" in rendered
        assert "  gpu: 40 jobs" in rendered

    def test_render_stats_pending_by_partition(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that pending queue can be broken down by partition."""
        stats = ClusterStats(
            total_nodes=10,
            free_nodes=5,
            pending_jobs_count=3,
            pending_cpus=96,
            pending_memory_gb=768.0,
            pending_gpus=12,
            pending_by_partition={
                "cpu": PendingPartitionStats(jobs_count=1, cpus=64, memory_gb=512.0, gpus=8),
                "gpu": PendingPartitionStats(jobs_count=2, cpus=32, memory_gb=256.0, gpus=4),
            },
        )
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        cpu_pos = rendered.find("  cpu: 1 jobs")
        gpu_pos = rendered.find("  gpu: 2 jobs")
        assert cpu_pos != -1
        assert gpu_pos != -1
        assert cpu_pos < gpu_pos

    def test_render_stats_pending_memory_tb(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that pending memory shows TB when >= 1024 GB."""
        stats = ClusterStats(
            total_nodes=10,
            free_nodes=5,
            pending_jobs_count=10,
            pending_by_partition={
                "gpu": PendingPartitionStats(jobs_count=10, cpus=0, memory_gb=2048.0, gpus=0),  # 2 TB
            },
        )
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "2.0 TB" in rendered
        assert "2048" not in rendered  # Should not show raw GB value

    def test_render_stats_pending_gpus_by_type(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that pending GPUs are shown by type per partition."""
        stats = ClusterStats(
            total_nodes=10,
            free_nodes=5,
            pending_jobs_count=10,
            pending_by_partition={
                "gpu": PendingPartitionStats(
                    jobs_count=10,
                    cpus=100,
                    memory_gb=100.0,
                    gpus=48,
                    gpus_by_type={"h200": 32, "a100": 16},
                ),
            },
        )
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "GPUs:" in rendered
        assert "h200: 32" in rendered
        assert "a100: 16" in rendered

    def test_render_stats_pending_gpus_generic_type(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that generic GPU type is displayed as 'generic'."""
        stats = ClusterStats(
            total_nodes=10,
            free_nodes=5,
            pending_jobs_count=10,
            pending_by_partition={
                "gpu": PendingPartitionStats(
                    jobs_count=10,
                    cpus=100,
                    memory_gb=100.0,
                    gpus=16,
                    gpus_by_type={"gpu": 16},
                ),
            },
        )
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "generic: 16" in rendered

    def test_render_stats_pending_gpus_total_only(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that pending GPUs show total when no type breakdown."""
        stats = ClusterStats(
            total_nodes=10,
            free_nodes=5,
            pending_jobs_count=10,
            pending_by_partition={
                "gpu": PendingPartitionStats(jobs_count=10, cpus=100, memory_gb=100.0, gpus=32),
            },
        )
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "GPUs: 32" in rendered

    def test_render_stats_pending_section_order(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test that pending section appears after GPU section."""
        stats = ClusterStats(
            total_nodes=10,
            free_nodes=5,
            total_gpus=50,
            allocated_gpus=25,
            gpus_by_type={"h200": (50, 25)},
            pending_jobs_count=10,
            pending_by_partition={"gpu": PendingPartitionStats(jobs_count=10, cpus=100, memory_gb=0.0, gpus=0)},
        )
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        gpu_pos = rendered.find("GPUs:")
        pending_pos = rendered.find("Pending Queue")
        assert gpu_pos < pending_pos, "Pending Queue should appear after GPUs"
