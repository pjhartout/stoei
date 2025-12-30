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
