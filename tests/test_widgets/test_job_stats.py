"""Tests for the JobStats widget."""

import pytest
from stoei.widgets.job_stats import JobStats


class TestJobStats:
    """Tests for the JobStats widget."""

    @pytest.fixture
    def job_stats(self) -> JobStats:
        """Create a JobStats widget for testing."""
        return JobStats()

    def test_initial_values(self, job_stats: JobStats) -> None:
        assert job_stats.total_jobs == 0
        assert job_stats.total_requeues == 0
        assert job_stats.max_requeues == 0
        assert job_stats.running_jobs == 0

    def test_update_stats(self, job_stats: JobStats) -> None:
        job_stats.update_stats(
            total_jobs=10,
            total_requeues=5,
            max_requeues=3,
            running_jobs=2,
        )

        assert job_stats.total_jobs == 10
        assert job_stats.total_requeues == 5
        assert job_stats.max_requeues == 3
        assert job_stats.running_jobs == 2

    def test_render_stats_contains_values(self, job_stats: JobStats) -> None:
        job_stats.update_stats(
            total_jobs=10,
            total_requeues=5,
            max_requeues=3,
            running_jobs=2,
        )

        rendered = job_stats._render_stats()

        assert "10" in rendered
        assert "5" in rendered
        assert "3" in rendered
        assert "2" in rendered

    def test_render_stats_contains_labels(self, job_stats: JobStats) -> None:
        rendered = job_stats._render_stats()

        assert "Total Jobs" in rendered
        assert "Running/Pending" in rendered
        assert "Total Requeues" in rendered
        assert "Max Requeues" in rendered

    def test_render_stats_contains_title(self, job_stats: JobStats) -> None:
        rendered = job_stats._render_stats()

        assert "Statistics" in rendered
        assert "24h" in rendered
