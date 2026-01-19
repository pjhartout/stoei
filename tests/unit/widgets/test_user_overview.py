"""Unit tests for the UserOverviewTab widget."""

import pytest
from stoei.widgets.user_overview import (
    UserEnergyStats,
    UserOverviewTab,
    UserPendingStats,
    UserStats,
)


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
            gpu_types="2x H200",
        )
        assert stats.username == "testuser"
        assert stats.job_count == 5
        assert stats.total_cpus == 20
        assert stats.total_memory_gb == 100.0
        assert stats.total_gpus == 2
        assert stats.total_nodes == 3
        assert stats.gpu_types == "2x H200"


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
                    gpu_types="1x GPU",
                ),
                UserStats(
                    username="user2",
                    job_count=5,
                    total_cpus=20,
                    total_memory_gb=128.0,
                    total_gpus=2,
                    total_nodes=3,
                    gpu_types="2x GPU",
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
            ("12345", "job1", "user1", "gpu", "RUNNING", "1:00:00", "2", "node01,node02"),
            ("12346", "job2", "user1", "gpu", "RUNNING", "0:30:00", "1", "node03"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].username == "user1"
        assert result[0].job_count == 2
        assert result[0].total_nodes == 3  # 2 + 1

    def test_aggregate_user_stats_multiple_users(self) -> None:
        """Test aggregating stats for multiple users."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "RUNNING", "1:00:00", "2", "node01,node02"),
            ("12346", "job2", "user2", "gpu", "RUNNING", "0:30:00", "1", "node03"),
            ("12347", "job3", "user1", "gpu", "PENDING", "0:00:00", "1", "(null)"),
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
            ("12345", "job1", "user1", "gpu", "RUNNING", "1:00:00", "4-8", "node[04-08]"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # Range 4-8 means 5 nodes (4, 5, 6, 7, 8)
        assert result[0].total_nodes == 5

    def test_aggregate_user_stats_invalid_node_count(self) -> None:
        """Test aggregating stats with invalid node count."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "RUNNING", "1:00:00", "invalid", "node01"),
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
            ("12345", "job1", "", "gpu", "RUNNING", "1:00:00", "1", "node01"),
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
                    gpu_types="",
                ),
                UserStats(
                    username="user2",
                    job_count=5,
                    total_cpus=50,
                    total_memory_gb=200.0,
                    total_gpus=2,
                    total_nodes=5,
                    gpu_types="2x GPU",
                ),
                UserStats(
                    username="user3",
                    job_count=1,
                    total_cpus=5,
                    total_memory_gb=25.0,
                    total_gpus=0,
                    total_nodes=1,
                    gpu_types="",
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
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 32
        assert memory_gb == 256.0
        assert len(gpu_entries) == 1
        assert gpu_entries[0] == ("gpu", 16)

    def test_parse_tres_with_memory_mb(self) -> None:
        """Test parsing TRES with memory in MB (converted to GB)."""
        tres_str = "cpu=8,mem=8192M,node=1,gres/gpu=1"
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 8
        assert memory_gb == 8.0  # 8192 MB / 1024 = 8 GB
        assert len(gpu_entries) == 1
        assert gpu_entries[0] == ("gpu", 1)

    def test_parse_tres_without_gpus(self) -> None:
        """Test parsing TRES without GPU information."""
        tres_str = "cpu=16,mem=128G,node=2"
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 16
        assert memory_gb == 128.0
        assert len(gpu_entries) == 0

    def test_parse_tres_without_memory(self) -> None:
        """Test parsing TRES without memory information."""
        tres_str = "cpu=32,node=4,gres/gpu=8"
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 32
        assert memory_gb == 0.0
        assert len(gpu_entries) == 1
        assert gpu_entries[0] == ("gpu", 8)

    def test_parse_tres_empty_string(self) -> None:
        """Test parsing empty TRES string."""
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres("")
        assert cpus == 0
        assert memory_gb == 0.0
        assert len(gpu_entries) == 0

    def test_parse_tres_invalid_format(self) -> None:
        """Test parsing invalid TRES format."""
        tres_str = "invalid format"
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 0
        assert memory_gb == 0.0
        assert len(gpu_entries) == 0

    def test_parse_tres_with_gpu_types(self) -> None:
        """Test parsing TRES with GPU type information."""
        tres_str = "cpu=32,mem=256G,node=4,gres/gpu:h200=8"
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 32
        assert memory_gb == 256.0
        assert len(gpu_entries) == 1
        assert gpu_entries[0] == ("h200", 8)

    def test_parse_tres_with_multiple_gpu_types(self) -> None:
        """Test parsing TRES with multiple GPU types."""
        tres_str = "cpu=32,mem=256G,node=4,gres/gpu:h200=8,gres/gpu:a100=4"
        cpus, memory_gb, gpu_entries = UserOverviewTab._parse_tres(tres_str)
        assert cpus == 32
        assert memory_gb == 256.0
        assert len(gpu_entries) == 2
        assert ("h200", 8) in gpu_entries
        assert ("a100", 4) in gpu_entries

    def test_aggregate_user_stats_with_tres_memory(self) -> None:
        """Test aggregating stats with TRES memory information."""
        jobs = [
            (
                "12345",
                "job1",
                "user1",
                "gpu",
                "RUNNING",
                "1:00:00",
                "2",
                "node01,node02",
                "cpu=32,mem=256G,node=2,gres/gpu=8",
            ),
            ("12346", "job2", "user1", "gpu", "RUNNING", "0:30:00", "1", "node03", "cpu=16,mem=128G,node=1,gres/gpu=4"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].username == "user1"
        assert result[0].total_memory_gb == 384.0  # 256 + 128
        assert result[0].total_gpus == 12  # 8 + 4
        assert result[0].total_cpus == 48  # 32 + 16
        assert result[0].gpu_types == "12x GPU"

    def test_aggregate_user_stats_with_tres_memory_mb(self) -> None:
        """Test aggregating stats with TRES memory in MB."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "RUNNING", "1:00:00", "1", "node01", "cpu=8,mem=8192M,node=1,gres/gpu=1"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].total_memory_gb == 8.0  # 8192 MB / 1024 = 8 GB
        assert result[0].total_gpus == 1
        assert result[0].gpu_types == "1x GPU"

    def test_aggregate_user_stats_with_tres_multiple_users(self) -> None:
        """Test aggregating stats with TRES for multiple users."""
        jobs = [
            (
                "12345",
                "job1",
                "user1",
                "gpu",
                "RUNNING",
                "1:00:00",
                "2",
                "node01,node02",
                "cpu=32,mem=256G,node=2,gres/gpu=8",
            ),
            ("12346", "job2", "user2", "gpu", "RUNNING", "0:30:00", "1", "node03", "cpu=16,mem=128G,node=1,gres/gpu=4"),
            ("12347", "job3", "user1", "gpu", "PENDING", "0:00:00", "1", "(null)", "cpu=8,mem=64G,node=1,gres/gpu=2"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 2
        user1 = next(u for u in result if u.username == "user1")
        user2 = next(u for u in result if u.username == "user2")
        assert user1.total_memory_gb == 320.0  # 256 + 64
        assert user1.total_gpus == 10  # 8 + 2
        assert user1.total_cpus == 40  # 32 + 8
        assert user1.gpu_types == "10x GPU"
        assert user2.total_memory_gb == 128.0
        assert user2.total_gpus == 4
        assert user2.total_cpus == 16
        assert user2.gpu_types == "4x GPU"

    def test_aggregate_user_stats_without_tres(self) -> None:
        """Test aggregating stats when TRES field is missing."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "RUNNING", "1:00:00", "2", "node01,node02"),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # Should fall back to node-based CPU estimation
        assert result[0].total_cpus == 2  # Based on nodes
        assert result[0].total_memory_gb == 0.0
        assert result[0].total_gpus == 0
        assert result[0].gpu_types == ""

    def test_aggregate_user_stats_with_empty_tres(self) -> None:
        """Test aggregating stats when TRES field is empty."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "RUNNING", "1:00:00", "2", "node01,node02", ""),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # Should fall back to node-based CPU estimation
        assert result[0].total_cpus == 2
        assert result[0].total_memory_gb == 0.0
        assert result[0].total_gpus == 0
        assert result[0].gpu_types == ""

    def test_aggregate_user_stats_tres_overrides_node_cpu_estimation(self) -> None:
        """Test that TRES CPU count overrides node-based estimation."""
        jobs = [
            (
                "12345",
                "job1",
                "user1",
                "gpu",
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
        assert result[0].gpu_types == "16x GPU"

    def test_aggregate_user_stats_mixed_tres_and_no_tres(self) -> None:
        """Test aggregating stats with mix of jobs with and without TRES."""
        jobs = [
            (
                "12345",
                "job1",
                "user1",
                "gpu",
                "RUNNING",
                "1:00:00",
                "2",
                "node01,node02",
                "cpu=32,mem=256G,node=2,gres/gpu=8",
            ),
            ("12346", "job2", "user1", "gpu", "RUNNING", "0:30:00", "1", "node03"),  # No TRES
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        # First job uses TRES (32 CPUs), second uses node estimation (1 CPU)
        assert result[0].total_cpus == 33  # 32 + 1
        assert result[0].total_memory_gb == 256.0  # Only from first job
        assert result[0].total_gpus == 8  # Only from first job
        assert result[0].gpu_types == "8x GPU"

    def test_aggregate_user_stats_with_gpu_types(self) -> None:
        """Test aggregating stats with GPU type information."""
        jobs = [
            (
                "12345",
                "job1",
                "user1",
                "gpu",
                "RUNNING",
                "1:00:00",
                "1",
                "node01",
                "cpu=32,mem=256G,node=1,gres/gpu:h200=8",
            ),
            (
                "12346",
                "job2",
                "user1",
                "gpu",
                "RUNNING",
                "0:30:00",
                "1",
                "node02",
                "cpu=16,mem=128G,node=1,gres/gpu:h200=4",
            ),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].total_gpus == 12  # 8 + 4
        assert result[0].gpu_types == "12x H200"

    def test_aggregate_user_stats_with_multiple_gpu_types(self) -> None:
        """Test aggregating stats with multiple GPU types."""
        jobs = [
            (
                "12345",
                "job1",
                "user1",
                "gpu",
                "RUNNING",
                "1:00:00",
                "1",
                "node01",
                "cpu=32,mem=256G,node=1,gres/gpu:h200=8",
            ),
            (
                "12346",
                "job2",
                "user1",
                "gpu",
                "RUNNING",
                "0:30:00",
                "1",
                "node02",
                "cpu=16,mem=128G,node=1,gres/gpu:a100=4",
            ),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].total_gpus == 12  # 8 + 4
        # Should be sorted alphabetically
        assert result[0].gpu_types == "4x A100, 8x H200"

    def test_aggregate_user_stats_skip_generic_when_specific_types_exist(self) -> None:
        """Test that generic GPU entries are skipped when specific types exist."""
        jobs = [
            # Both generic and specific types in same TRES (should only count specific)
            (
                "12345",
                "job1",
                "user1",
                "gpu",
                "RUNNING",
                "1:00:00",
                "1",
                "node01",
                "cpu=32,mem=256G,node=1,gres/gpu=8,gres/gpu:h200=8",
            ),
        ]
        result = UserOverviewTab.aggregate_user_stats(jobs)
        assert len(result) == 1
        assert result[0].total_gpus == 8  # Only h200, generic is skipped
        assert result[0].gpu_types == "8x H200"


class TestUserPendingStats:
    """Tests for the UserPendingStats dataclass."""

    def test_user_pending_stats_creation(self) -> None:
        """Test creating a UserPendingStats object."""
        stats = UserPendingStats(
            username="testuser",
            pending_job_count=10,
            pending_cpus=80,
            pending_memory_gb=320.0,
            pending_gpus=10,
            pending_gpu_types="10x H200",
        )
        assert stats.username == "testuser"
        assert stats.pending_job_count == 10
        assert stats.pending_cpus == 80
        assert stats.pending_memory_gb == 320.0
        assert stats.pending_gpus == 10
        assert stats.pending_gpu_types == "10x H200"

    def test_user_pending_stats_default_gpu_types(self) -> None:
        """Test UserPendingStats with default gpu_types."""
        stats = UserPendingStats(
            username="testuser",
            pending_job_count=5,
            pending_cpus=40,
            pending_memory_gb=160.0,
            pending_gpus=0,
        )
        assert stats.pending_gpu_types == ""


class TestAggregatePendingUserStats:
    """Tests for aggregate_pending_user_stats method."""

    def test_aggregate_pending_empty_list(self) -> None:
        """Test aggregating pending stats from empty job list."""
        result = UserOverviewTab.aggregate_pending_user_stats([])
        assert result == []

    def test_aggregate_pending_no_pending_jobs(self) -> None:
        """Test aggregating when there are no pending jobs."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "RUNNING", "1:00:00", "2", "node01,node02", "cpu=32,mem=256G"),
            ("12346", "job2", "user2", "gpu", "COMPLETED", "0:30:00", "1", "node03", "cpu=16,mem=128G"),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 0

    def test_aggregate_pending_single_user(self) -> None:
        """Test aggregating pending stats for a single user."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)", "cpu=32,mem=256G,gres/gpu=4"),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 1
        assert result[0].username == "user1"
        assert result[0].pending_job_count == 1
        assert result[0].pending_cpus == 32
        assert result[0].pending_memory_gb == 256.0
        assert result[0].pending_gpus == 4

    def test_aggregate_pending_multiple_users(self) -> None:
        """Test aggregating pending stats for multiple users."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)", "cpu=32,mem=256G,gres/gpu=4"),
            ("12346", "job2", "user2", "gpu", "PENDING", "0:00", "1", "(Resources)", "cpu=64,mem=512G,gres/gpu=8"),
            ("12347", "job3", "user1", "gpu", "RUNNING", "1:00:00", "1", "node01", "cpu=8,mem=32G"),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 2
        # Sorted by pending_cpus descending
        assert result[0].username == "user2"
        assert result[0].pending_cpus == 64
        assert result[1].username == "user1"
        assert result[1].pending_cpus == 32

    def test_aggregate_pending_recognizes_pd_state(self) -> None:
        """Test that 'PD' state is recognized as pending."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "PD", "0:00", "1", "(Priority)", "cpu=16,mem=128G"),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 1
        assert result[0].pending_job_count == 1
        assert result[0].pending_cpus == 16

    def test_aggregate_pending_array_job_expands(self) -> None:
        """Test that pending array jobs are expanded."""
        jobs = [
            # Array job with 50 tasks
            (
                "47700_[0-49]",
                "array_job",
                "user1",
                "gpu",
                "PENDING",
                "0:00",
                "1",
                "(Priority)",
                "cpu=8,mem=32G,gres/gpu=1",
            ),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 1
        assert result[0].pending_job_count == 50
        assert result[0].pending_cpus == 400  # 8 * 50
        assert result[0].pending_memory_gb == 1600.0  # 32 * 50
        assert result[0].pending_gpus == 50  # 1 * 50

    def test_aggregate_pending_mixed_array_and_regular(self) -> None:
        """Test mix of array and regular pending jobs."""
        jobs = [
            # Regular pending job
            ("12345", "job1", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)", "cpu=32,mem=256G,gres/gpu=4"),
            # Array job with 10 tasks
            ("47700_[0-9]", "array", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)", "cpu=8,mem=32G,gres/gpu=1"),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 1
        # 1 regular + 10 array = 11 jobs
        assert result[0].pending_job_count == 11
        # 32 + (8*10) = 112 CPUs
        assert result[0].pending_cpus == 112
        # 256 + (32*10) = 576 GB
        assert result[0].pending_memory_gb == 576.0
        # 4 + (1*10) = 14 GPUs
        assert result[0].pending_gpus == 14

    def test_aggregate_pending_array_with_throttle(self) -> None:
        """Test that array job with throttle still counts all tasks."""
        jobs = [
            # Array job with 100 tasks and %10 throttle
            ("47700_[0-99%10]", "throttled", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)", "cpu=4,mem=16G"),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 1
        assert result[0].pending_job_count == 100
        assert result[0].pending_cpus == 400  # 4 * 100

    def test_aggregate_pending_single_array_task_not_expanded(self) -> None:
        """Test that single array task is not expanded."""
        jobs = [
            ("47700_5", "single_task", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)", "cpu=8,mem=32G"),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 1
        assert result[0].pending_job_count == 1
        assert result[0].pending_cpus == 8

    def test_aggregate_pending_with_gpu_types(self) -> None:
        """Test aggregating pending stats with GPU types."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)", "cpu=32,mem=256G,gres/gpu:h200=8"),
            ("12346", "job2", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)", "cpu=16,mem=128G,gres/gpu:a100=4"),
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 1
        assert result[0].pending_gpus == 12
        # GPU types are formatted as lowercase from parsing
        assert result[0].pending_gpu_types == "4x a100, 8x h200"

    def test_aggregate_pending_without_tres(self) -> None:
        """Test aggregating pending stats without TRES field."""
        jobs = [
            ("12345", "job1", "user1", "gpu", "PENDING", "0:00", "1", "(Priority)"),  # No TRES
        ]
        result = UserOverviewTab.aggregate_pending_user_stats(jobs)
        assert len(result) == 1
        assert result[0].pending_job_count == 1
        assert result[0].pending_cpus == 0  # No TRES data

    async def test_update_pending_users(self) -> None:
        """Test updating pending users - requires mounted widget."""
        from textual.app import App

        class UserTestApp(App[None]):
            def compose(self):
                yield UserOverviewTab(id="user-overview")

        app = UserTestApp()
        async with app.run_test(size=(80, 24)):
            user_tab = app.query_one("#user-overview", UserOverviewTab)
            pending_users = [
                UserPendingStats(
                    username="user1",
                    pending_job_count=10,
                    pending_cpus=80,
                    pending_memory_gb=320.0,
                    pending_gpus=10,
                    pending_gpu_types="10x H200",
                ),
                UserPendingStats(
                    username="user2",
                    pending_job_count=5,
                    pending_cpus=40,
                    pending_memory_gb=160.0,
                    pending_gpus=5,
                    pending_gpu_types="5x A100",
                ),
            ]
            user_tab.update_pending_users(pending_users)
            assert len(user_tab.pending_users) == 2


class TestUserEnergyStats:
    """Tests for the UserEnergyStats dataclass."""

    def test_user_energy_stats_creation(self) -> None:
        """Test creating a UserEnergyStats object."""
        stats = UserEnergyStats(
            username="testuser",
            total_energy_wh=1_234_567.0,
            job_count=150,
            gpu_hours=4500.0,
            cpu_hours=89000.0,
        )
        assert stats.username == "testuser"
        assert stats.total_energy_wh == 1_234_567.0
        assert stats.job_count == 150
        assert stats.gpu_hours == 4500.0
        assert stats.cpu_hours == 89000.0


class TestAggregateEnergyStats:
    """Tests for aggregate_energy_stats method."""

    def test_aggregate_energy_empty_list(self) -> None:
        """Test aggregating energy stats from empty job list."""
        result = UserOverviewTab.aggregate_energy_stats([])
        assert result == []

    def test_aggregate_energy_single_user(self) -> None:
        """Test aggregating energy stats for a single user."""
        # Job format: (JobID, User, Elapsed, NCPUS, AllocTRES)
        jobs = [
            ("12345", "user1", "01:00:00", "32", "cpu=32,mem=256G,gres/gpu:h200=8"),
        ]
        result = UserOverviewTab.aggregate_energy_stats(jobs)
        assert len(result) == 1
        assert result[0].username == "user1"
        assert result[0].job_count == 1
        assert result[0].gpu_hours == 8.0  # 8 GPUs * 1 hour
        assert result[0].cpu_hours == 32.0  # 32 CPUs * 1 hour
        # Energy: 8 H200 GPUs * 700W * 1h + 32 CPUs * 10W * 1h = 5600 + 320 = 5920 Wh
        assert result[0].total_energy_wh == 5920.0

    def test_aggregate_energy_multiple_users(self) -> None:
        """Test aggregating energy stats for multiple users."""
        jobs = [
            ("12345", "user1", "02:00:00", "32", "cpu=32,mem=256G,gres/gpu:a100=4"),
            ("12346", "user2", "01:00:00", "64", "cpu=64,mem=512G,gres/gpu:h200=8"),
            ("12347", "user1", "00:30:00", "16", "cpu=16,mem=128G,gres/gpu:a100=2"),
        ]
        result = UserOverviewTab.aggregate_energy_stats(jobs)
        assert len(result) == 2

        # Find user1 and user2
        user1 = next(u for u in result if u.username == "user1")
        user2 = next(u for u in result if u.username == "user2")

        assert user1.job_count == 2
        assert user2.job_count == 1

        # User1: 4 A100 * 2h + 2 A100 * 0.5h = 8 + 1 = 9 GPU-hours
        assert user1.gpu_hours == 9.0

        # User2: 8 H200 * 1h = 8 GPU-hours
        assert user2.gpu_hours == 8.0

    def test_aggregate_energy_with_days(self) -> None:
        """Test aggregating energy with multi-day jobs."""
        jobs = [
            ("12345", "user1", "1-12:00:00", "64", "cpu=64,mem=512G,gres/gpu:h200=8"),
        ]
        result = UserOverviewTab.aggregate_energy_stats(jobs)
        assert len(result) == 1

        # Duration: 1 day + 12 hours = 36 hours
        assert result[0].gpu_hours == 8.0 * 36.0  # 288 GPU-hours
        assert result[0].cpu_hours == 64.0 * 36.0  # 2304 CPU-hours

    def test_aggregate_energy_sorted_by_energy(self) -> None:
        """Test that results are sorted by energy (descending)."""
        jobs = [
            ("12345", "small_user", "01:00:00", "8", "cpu=8,mem=32G"),
            ("12346", "big_user", "10:00:00", "128", "cpu=128,mem=1024G,gres/gpu:h200=16"),
            ("12347", "medium_user", "02:00:00", "32", "cpu=32,mem=256G,gres/gpu:a100=4"),
        ]
        result = UserOverviewTab.aggregate_energy_stats(jobs)
        assert len(result) == 3

        # Should be sorted by total_energy_wh descending
        assert result[0].username == "big_user"
        assert result[1].username == "medium_user"
        assert result[2].username == "small_user"

    def test_aggregate_energy_no_gpus(self) -> None:
        """Test aggregating energy with CPU-only jobs."""
        jobs = [
            ("12345", "user1", "02:00:00", "64", "cpu=64,mem=256G"),
        ]
        result = UserOverviewTab.aggregate_energy_stats(jobs)
        assert len(result) == 1
        assert result[0].gpu_hours == 0.0
        assert result[0].cpu_hours == 128.0  # 64 CPUs * 2 hours
        # Energy: 64 CPUs * 10W * 2h = 1280 Wh
        assert result[0].total_energy_wh == 1280.0

    def test_aggregate_energy_skips_generic_when_specific_exists(self) -> None:
        """Test that generic GPU entries are skipped when specific types exist."""
        jobs = [
            # Both generic and specific GPU types (should only count specific)
            ("12345", "user1", "01:00:00", "32", "cpu=32,mem=256G,gres/gpu=8,gres/gpu:h200=8"),
        ]
        result = UserOverviewTab.aggregate_energy_stats(jobs)
        assert len(result) == 1
        # Should only count 8 GPUs, not 16
        assert result[0].gpu_hours == 8.0

    def test_aggregate_energy_zero_elapsed(self) -> None:
        """Test that jobs with zero elapsed time are skipped."""
        jobs = [
            ("12345", "user1", "00:00:00", "32", "cpu=32,mem=256G,gres/gpu:h200=8"),
            ("12346", "user1", "01:00:00", "32", "cpu=32,mem=256G,gres/gpu:h200=8"),
        ]
        result = UserOverviewTab.aggregate_energy_stats(jobs)
        assert len(result) == 1
        assert result[0].job_count == 1  # Only the non-zero job counted

    def test_aggregate_energy_empty_username(self) -> None:
        """Test that jobs with empty username are skipped."""
        jobs = [
            ("12345", "", "01:00:00", "32", "cpu=32,mem=256G,gres/gpu:h200=8"),
            ("12346", "user1", "01:00:00", "32", "cpu=32,mem=256G,gres/gpu:h200=8"),
        ]
        result = UserOverviewTab.aggregate_energy_stats(jobs)
        assert len(result) == 1
        assert result[0].username == "user1"


class TestUserOverviewSubtabs:
    """Tests for sub-tab functionality in UserOverviewTab."""

    def test_initial_subtab_is_running(self) -> None:
        """Test that initial active subtab is 'running'."""
        tab = UserOverviewTab(id="test-tab")
        assert tab.active_subtab == "running"

    async def test_switch_subtab_pending(self) -> None:
        """Test switching to pending subtab."""
        from textual.app import App

        class SubtabTestApp(App[None]):
            def compose(self):
                yield UserOverviewTab(id="user-overview")

        app = SubtabTestApp()
        async with app.run_test(size=(80, 24)):
            user_tab = app.query_one("#user-overview", UserOverviewTab)

            # Initially running
            assert user_tab.active_subtab == "running"

            # Switch to pending
            user_tab.switch_subtab("pending")
            assert user_tab.active_subtab == "pending"

    async def test_switch_subtab_energy(self) -> None:
        """Test switching to energy subtab."""
        from textual.app import App

        class SubtabTestApp(App[None]):
            def compose(self):
                yield UserOverviewTab(id="user-overview")

        app = SubtabTestApp()
        async with app.run_test(size=(80, 24)):
            user_tab = app.query_one("#user-overview", UserOverviewTab)

            # Mark energy data as loaded to avoid modal popup
            app._energy_data_loaded = True  # type: ignore[attr-defined]

            # Switch to energy
            user_tab.switch_subtab("energy")
            assert user_tab.active_subtab == "energy"

    async def test_switch_subtab_same_tab_no_change(self) -> None:
        """Test that switching to the same subtab does nothing."""
        from textual.app import App

        class SubtabTestApp(App[None]):
            def compose(self):
                yield UserOverviewTab(id="user-overview")

        app = SubtabTestApp()
        async with app.run_test(size=(80, 24)):
            user_tab = app.query_one("#user-overview", UserOverviewTab)

            # Switch to running (already active)
            user_tab.switch_subtab("running")
            assert user_tab.active_subtab == "running"

    async def test_update_energy_users(self) -> None:
        """Test updating energy users table."""
        from textual.app import App

        class EnergyTestApp(App[None]):
            def compose(self):
                yield UserOverviewTab(id="user-overview")

        app = EnergyTestApp()
        async with app.run_test(size=(80, 24)):
            user_tab = app.query_one("#user-overview", UserOverviewTab)
            energy_users = [
                UserEnergyStats(
                    username="user1",
                    total_energy_wh=1_234_567.0,
                    job_count=150,
                    gpu_hours=4500.0,
                    cpu_hours=89000.0,
                ),
                UserEnergyStats(
                    username="user2",
                    total_energy_wh=500_000.0,
                    job_count=75,
                    gpu_hours=1500.0,
                    cpu_hours=45000.0,
                ),
            ]
            user_tab.update_energy_users(energy_users)
            # Should be sorted by energy descending
            assert len(user_tab.energy_users) == 2
            assert user_tab.energy_users[0].username == "user1"
            assert user_tab.energy_users[1].username == "user2"
