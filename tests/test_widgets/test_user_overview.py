"""Unit tests for the UserOverviewTab widget."""

import pytest
from stoei.widgets.user_overview import UserOverviewTab, UserStats


class TestUserStats:
    """Tests for the UserStats dataclass."""

    def test_user_stats_creation(self) -> None:
        """Test creating a UserStats object."""
        stats = UserStats(
            username="testuser",
            job_count=5,
            total_cpus=20,
            total_memory_gb=100.0,
            total_gpus=2,
            total_nodes=3,
        )
        assert stats.username == "testuser"
        assert stats.job_count == 5
        assert stats.total_cpus == 20
        assert stats.total_memory_gb == 100.0
        assert stats.total_gpus == 2
        assert stats.total_nodes == 3


class TestUserOverviewTab:
    """Tests for the UserOverviewTab widget."""

    @pytest.fixture
    def user_tab(self) -> UserOverviewTab:
        """Create a UserOverviewTab widget for testing."""
        return UserOverviewTab(id="test-user-tab")

    def test_initial_users_empty(self, user_tab: UserOverviewTab) -> None:
        """Test that initial users list is empty."""
        assert user_tab.users == []

    async def test_update_users(self) -> None:
        """Test updating users - requires mounted widget."""
        from textual.app import App

        class UserTestApp(App[None]):
            def compose(self):
                yield UserOverviewTab(id="user-overview")

        app = UserTestApp()
        async with app.run_test(size=(80, 24)):
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
                UserStats(
                    username="user2",
                    job_count=5,
                    total_cpus=20,
                    total_memory_gb=128.0,
                    total_gpus=2,
                    total_nodes=3,
                ),
            ]
            user_tab.update_users(users)
            assert len(user_tab.users) == 2

    def test_aggregate_user_stats_empty_list(self) -> None:
        """Test aggregating stats from empty job list."""
        result = UserOverviewTab.aggregate_user_stats([])
        assert result == []

    def test_aggregate_user_stats_single_user(self) -> None:
        """Test aggregating stats for a single user."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "2", "node01,node02"),
            ("12346", "job2", "user1", "RUNNING", "0:30:00", "1", "node03"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].username == "user1"
        assert result[0].job_count == 2
        assert result[0].total_nodes == 3  # 2 + 1

    def test_aggregate_user_stats_multiple_users(self) -> None:
        """Test aggregating stats for multiple users."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "2", "node01,node02"),
            ("12346", "job2", "user2", "RUNNING", "0:30:00", "1", "node03"),
            ("12347", "job3", "user1", "PENDING", "0:00:00", "1", "(null)"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 2
        user1 = next(u for u in result if u.username == "user1")
        user2 = next(u for u in result if u.username == "user2")
        assert user1.job_count == 2
        assert user2.job_count == 1

    def test_aggregate_user_stats_node_range(self) -> None:
        """Test aggregating stats with node range notation."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "4-8", "node[04-08]"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # Range 4-8 means 5 nodes (4, 5, 6, 7, 8)
        assert result[0].total_nodes == 5

    def test_aggregate_user_stats_invalid_node_count(self) -> None:
        """Test aggregating stats with invalid node count."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "invalid", "node01"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # Should default to 0 when parsing fails
        assert result[0].total_nodes == 0

    def test_aggregate_user_stats_missing_fields(self) -> None:
        """Test aggregating stats with jobs missing fields."""
        jobs = [
            ("12345", "job1", "user1"),  # Missing fields
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        # Should skip jobs with insufficient fields
        assert len(result) == 0

    def test_aggregate_user_stats_empty_username(self) -> None:
        """Test aggregating stats with empty username."""
        jobs = [
            ("12345", "job1", "", "RUNNING", "1:00:00", "1", "node01"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        # Should skip jobs with empty username
        assert len(result) == 0

    async def test_update_users_sorts_by_cpus(self) -> None:
        """Test that users are sorted by CPU usage (descending)."""
        from textual.app import App

        class UserTestApp(App[None]):
            def compose(self):
                yield UserOverviewTab(id="user-overview")

        app = UserTestApp()
        async with app.run_test(size=(80, 24)):
            user_tab = app.query_one("#user-overview", UserOverviewTab)
            users = [
                UserStats(
                    username="user1",
                    job_count=2,
                    total_cpus=10,
                    total_memory_gb=50.0,
                    total_gpus=0,
                    total_nodes=1,
                ),
                UserStats(
                    username="user2",
                    job_count=5,
                    total_cpus=50,
                    total_memory_gb=200.0,
                    total_gpus=2,
                    total_nodes=5,
                ),
                UserStats(
                    username="user3",
                    job_count=1,
                    total_cpus=5,
                    total_memory_gb=25.0,
                    total_gpus=0,
                    total_nodes=1,
                ),
            ]
            user_tab.update_users(users)
            # Users should be sorted by total_cpus descending
            assert user_tab.users[0].username == "user2"
            assert user_tab.users[1].username == "user1"
            assert user_tab.users[2].username == "user3"

    def test_parse_tres_with_memory_gb(self) -> None:
        """Test parsing TRES with memory in GB."""
        tres_str = "cpu=32,mem=256G,node=4,gres/gpu=16"
        cpus, memory_gb, gpus = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 32
        assert memory_gb == 256.0
        assert gpus == 16

    def test_parse_tres_with_memory_mb(self) -> None:
        """Test parsing TRES with memory in MB (converted to GB)."""
        tres_str = "cpu=8,mem=8192M,node=1,gres/gpu=1"
        cpus, memory_gb, gpus = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 8
        assert memory_gb == 8.0  # 8192 MB / 1024 = 8 GB
        assert gpus == 1

    def test_parse_tres_without_gpus(self) -> None:
        """Test parsing TRES without GPU information."""
        tres_str = "cpu=16,mem=128G,node=2"
        cpus, memory_gb, gpus = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 16
        assert memory_gb == 128.0
        assert gpus == 0

    def test_parse_tres_without_memory(self) -> None:
        """Test parsing TRES without memory information."""
        tres_str = "cpu=32,node=4,gres/gpu=8"
        cpus, memory_gb, gpus = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 32
        assert memory_gb == 0.0
        assert gpus == 8

    def test_parse_tres_empty_string(self) -> None:
        """Test parsing empty TRES string."""
        cpus, memory_gb, gpus = UserOverviewTab._parse_tres("")
        assert cpus == 0
        assert memory_gb == 0.0
        assert gpus == 0

    def test_parse_tres_invalid_format(self) -> None:
        """Test parsing invalid TRES format."""
        tres_str = "invalid format"
        cpus, memory_gb, gpus = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 0
        assert memory_gb == 0.0
        assert gpus == 0

    def test_aggregate_user_stats_with_tres_memory(self) -> None:
        """Test aggregating stats with TRES memory information."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "2", "node01,node02", "cpu=32,mem=256G,node=2,gres/gpu=8"),
            ("12346", "job2", "user1", "RUNNING", "0:30:00", "1", "node03", "cpu=16,mem=128G,node=1,gres/gpu=4"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].username == "user1"
        assert result[0].total_memory_gb == 384.0  # 256 + 128
        assert result[0].total_gpus == 12  # 8 + 4
        assert result[0].total_cpus == 48  # 32 + 16

    def test_aggregate_user_stats_with_tres_memory_mb(self) -> None:
        """Test aggregating stats with TRES memory in MB."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "1", "node01", "cpu=8,mem=8192M,node=1,gres/gpu=1"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].total_memory_gb == 8.0  # 8192 MB / 1024 = 8 GB
        assert result[0].total_gpus == 1

    def test_aggregate_user_stats_with_tres_multiple_users(self) -> None:
        """Test aggregating stats with TRES for multiple users."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "2", "node01,node02", "cpu=32,mem=256G,node=2,gres/gpu=8"),
            ("12346", "job2", "user2", "RUNNING", "0:30:00", "1", "node03", "cpu=16,mem=128G,node=1,gres/gpu=4"),
            ("12347", "job3", "user1", "PENDING", "0:00:00", "1", "(null)", "cpu=8,mem=64G,node=1,gres/gpu=2"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 2
        user1 = next(u for u in result if u.username == "user1")
        user2 = next(u for u in result if u.username == "user2")
        assert user1.total_memory_gb == 320.0  # 256 + 64
        assert user1.total_gpus == 10  # 8 + 2
        assert user1.total_cpus == 40  # 32 + 8
        assert user2.total_memory_gb == 128.0
        assert user2.total_gpus == 4
        assert user2.total_cpus == 16

    def test_aggregate_user_stats_without_tres(self) -> None:
        """Test aggregating stats when TRES field is missing."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "2", "node01,node02"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # Should fall back to node-based CPU estimation
        assert result[0].total_cpus == 2  # Based on nodes
        assert result[0].total_memory_gb == 0.0
        assert result[0].total_gpus == 0

    def test_aggregate_user_stats_with_empty_tres(self) -> None:
        """Test aggregating stats when TRES field is empty."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "2", "node01,node02", ""),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # Should fall back to node-based CPU estimation
        assert result[0].total_cpus == 2
        assert result[0].total_memory_gb == 0.0
        assert result[0].total_gpus == 0

    def test_aggregate_user_stats_tres_overrides_node_cpu_estimation(self) -> None:
        """Test that TRES CPU count overrides node-based estimation."""
        jobs = [
            (
                "12345",
                "job1",
                "user1",
                "RUNNING",
                "1:00:00",
                "2",
                "node01,node02",
                "cpu=64,mem=512G,node=2,gres/gpu=16",
            ),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # Should use TRES CPU count (64) instead of node-based estimation (2)
        assert result[0].total_cpus == 64
        assert result[0].total_memory_gb == 512.0
        assert result[0].total_gpus == 16

    def test_aggregate_user_stats_mixed_tres_and_no_tres(self) -> None:
        """Test aggregating stats with mix of jobs with and without TRES."""
        jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "2", "node01,node02", "cpu=32,mem=256G,node=2,gres/gpu=8"),
            ("12346", "job2", "user1", "RUNNING", "0:30:00", "1", "node03"),  # No TRES
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # First job uses TRES (32 CPUs), second uses node estimation (1 CPU)
        assert result[0].total_cpus == 33  # 32 + 1
        assert result[0].total_memory_gb == 256.0  # Only from first job
        assert result[0].total_gpus == 8  # Only from first job
