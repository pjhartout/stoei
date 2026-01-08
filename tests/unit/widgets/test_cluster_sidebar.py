"""Unit tests for the ClusterSidebar widget."""

import pytest
from stoei.widgets.cluster_sidebar import ClusterSidebar, ClusterStats


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
        assert "[green]" in rendered

    def test_render_stats_color_coding_medium_availability(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test color coding for medium availability (25-50%)."""
        stats = ClusterStats(total_nodes=100, free_nodes=30)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "[yellow]" in rendered

    def test_render_stats_color_coding_low_availability(self, cluster_sidebar: ClusterSidebar) -> None:
        """Test color coding for low availability (<25%)."""
        stats = ClusterStats(total_nodes=100, free_nodes=10)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "[red]" in rendered

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
        # Exactly 50% (should be green)
        stats = ClusterStats(total_nodes=100, free_nodes=50)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "[green]" in rendered

        # Exactly 25% (should be yellow)
        stats = ClusterStats(total_nodes=100, free_nodes=25)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "[yellow]" in rendered

        # Just below 25% (should be red)
        stats = ClusterStats(total_nodes=100, free_nodes=24)
        cluster_sidebar.update_stats(stats)
        rendered = cluster_sidebar._render_stats()
        assert "[red]" in rendered

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
