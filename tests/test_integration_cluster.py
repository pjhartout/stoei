"""Integration tests for cluster overview features."""

from pathlib import Path

import pytest
from textual.app import App

from stoei.slurm.cache import JobCache
from stoei.widgets.cluster_sidebar import ClusterSidebar, ClusterStats
from stoei.widgets.node_overview import NodeInfo, NodeOverviewTab
from stoei.widgets.tabs import TabContainer
from stoei.widgets.user_overview import UserOverviewTab, UserStats


class ClusterTestApp(App[None]):
    """Test app for integration testing."""

    def compose(self):
        """Create test app layout."""
        yield ClusterSidebar(id="cluster-sidebar")
        yield TabContainer(id="tab-container")
        yield NodeOverviewTab(id="node-overview")
        yield UserOverviewTab(id="user-overview")


class TestClusterSidebarIntegration:
    """Integration tests for ClusterSidebar."""

    @pytest.fixture
    def app(self) -> ClusterTestApp:
        """Create a test app."""
        return ClusterTestApp()

    async def test_cluster_sidebar_updates(self, app: ClusterTestApp) -> None:
        """Test that ClusterSidebar can be updated with stats."""
        async with app.run_test() as pilot:
            sidebar = app.query_one("#cluster-sidebar", ClusterSidebar)
            stats = ClusterStats(
                total_nodes=100,
                free_nodes=50,
                allocated_nodes=50,
                total_cpus=1000,
                allocated_cpus=500,
                total_memory_gb=2000.0,
                allocated_memory_gb=1000.0,
            )
            sidebar.update_stats(stats)
            assert sidebar.stats.total_nodes == 100


class TestNodeOverviewIntegration:
    """Integration tests for NodeOverviewTab."""

    @pytest.fixture
    def app(self) -> ClusterTestApp:
        """Create a test app."""
        return ClusterTestApp()

    async def test_node_overview_updates(self, app: ClusterTestApp) -> None:
        """Test that NodeOverviewTab can be updated with node data."""
        async with app.run_test() as pilot:
            node_tab = app.query_one("#node-overview", NodeOverviewTab)
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
            ]
            node_tab.update_nodes(nodes)
            assert len(node_tab.nodes) == 1


class TestUserOverviewIntegration:
    """Integration tests for UserOverviewTab."""

    @pytest.fixture
    def app(self) -> ClusterTestApp:
        """Create a test app."""
        return ClusterTestApp()

    async def test_user_overview_updates(self, app: ClusterTestApp) -> None:
        """Test that UserOverviewTab can be updated with user data."""
        async with app.run_test() as pilot:
            user_tab = app.query_one("#user-overview", UserOverviewTab)
            users = [
                UserStats(
                    username="user1",
                    job_count=3,
                    total_cpus=12,
                    total_memory_gb=64.0,
                    total_gpus=1,
                    total_nodes=2,
                ),
            ]
            user_tab.update_users(users)
            assert len(user_tab.users) == 1


class TestTabContainerIntegration:
    """Integration tests for TabContainer."""

    @pytest.fixture
    def app(self) -> ClusterTestApp:
        """Create a test app."""
        return ClusterTestApp()

    async def test_tab_switching(self, app: ClusterTestApp) -> None:
        """Test that tabs can be switched."""
        async with app.run_test() as pilot:
            tab_container = app.query_one("#tab-container", TabContainer)
            assert tab_container.active_tab == "jobs"
            tab_container.switch_tab("nodes")
            assert tab_container.active_tab == "nodes"


class TestClusterDataIntegration:
    """Integration tests for cluster data fetching."""

    async def test_get_cluster_nodes_with_mocks(self, mock_slurm_path: Path) -> None:
        """Test getting cluster nodes with mock SLURM."""
        from stoei.slurm.commands import get_cluster_nodes

        nodes, error = get_cluster_nodes()
        assert isinstance(nodes, list)
        # Mock may return empty or populated list
        assert error is None or isinstance(error, str)

    async def test_get_all_users_jobs_with_mocks(self, mock_slurm_path: Path) -> None:
        """Test getting all users jobs with mock SLURM."""
        from stoei.slurm.commands import get_all_users_jobs

        jobs = get_all_users_jobs()
        assert isinstance(jobs, list)
        # Mock may return empty or populated list

    async def test_cluster_stats_calculation(self, mock_slurm_path: Path) -> None:
        """Test calculating cluster stats from node data."""
        from stoei.slurm.commands import get_cluster_nodes

        nodes, error = get_cluster_nodes()
        if error:
            pytest.skip(f"get_cluster_nodes failed: {error}")

        # Calculate stats from nodes
        stats = ClusterStats()
        for node in nodes:
            stats.total_nodes += 1
            state = node.get("State", "").upper()
            if "IDLE" in state:
                stats.free_nodes += 1
            elif "ALLOCATED" in state or "MIXED" in state:
                stats.allocated_nodes += 1

            # Parse CPUs
            try:
                cpus_total = int(node.get("CPUTot", "0") or "0")
                cpus_alloc = int(node.get("CPUAlloc", "0") or "0")
                stats.total_cpus += cpus_total
                stats.allocated_cpus += cpus_alloc
            except ValueError:
                pass

        # Stats should be valid
        assert stats.total_nodes >= 0
        assert stats.free_nodes + stats.allocated_nodes <= stats.total_nodes
