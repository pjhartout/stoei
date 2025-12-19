"""Tests for the JobCache module."""

import pytest
from stoei.slurm.cache import Job, JobCache, JobState


class TestJobState:
    """Tests for the JobState enum."""

    def test_job_state_values(self) -> None:
        assert JobState.RUNNING.value == "RUNNING"
        assert JobState.PENDING.value == "PENDING"
        assert JobState.COMPLETED.value == "COMPLETED"
        assert JobState.FAILED.value == "FAILED"
        assert JobState.CANCELLED.value == "CANCELLED"
        assert JobState.TIMEOUT.value == "TIMEOUT"
        assert JobState.OTHER.value == "OTHER"


class TestJob:
    """Tests for the Job dataclass."""

    @pytest.fixture
    def running_job(self) -> Job:
        """Create a running job for testing."""
        return Job(
            job_id="12345",
            name="test_job",
            state="RUNNING",
            time="01:30:00",
            nodes="1",
            node_list="node01",
            is_active=True,
        )

    @pytest.fixture
    def completed_job(self) -> Job:
        """Create a completed job for testing."""
        return Job(
            job_id="12346",
            name="done_job",
            state="COMPLETED",
            time="00:45:00",
            nodes="",
            node_list="node02",
            exit_code="0:0",
            is_active=False,
        )

    @pytest.fixture
    def failed_job(self) -> Job:
        """Create a failed job for testing."""
        return Job(
            job_id="12347",
            name="failed_job",
            state="FAILED",
            time="00:10:00",
            nodes="",
            node_list="node03",
            exit_code="1:0",
            restarts=2,
            is_active=False,
        )

    def test_running_state_category(self, running_job: Job) -> None:
        assert running_job.state_category == JobState.RUNNING

    def test_completed_state_category(self, completed_job: Job) -> None:
        assert completed_job.state_category == JobState.COMPLETED

    def test_failed_state_category(self, failed_job: Job) -> None:
        assert failed_job.state_category == JobState.FAILED

    def test_pending_state_category(self) -> None:
        job = Job(
            job_id="12348",
            name="pending_job",
            state="PENDING",
            time="0:00",
            nodes="1",
            node_list="",
            is_active=True,
        )
        assert job.state_category == JobState.PENDING

    def test_cancelled_state_category(self) -> None:
        job = Job(
            job_id="12349",
            name="cancelled_job",
            state="CANCELLED",
            time="00:05:00",
            nodes="",
            node_list="node01",
            is_active=False,
        )
        assert job.state_category == JobState.CANCELLED

    def test_timeout_state_category(self) -> None:
        job = Job(
            job_id="12350",
            name="timeout_job",
            state="TIMEOUT",
            time="24:00:00",
            nodes="",
            node_list="node01",
            is_active=False,
        )
        assert job.state_category == JobState.TIMEOUT

    def test_node_fail_state_category(self) -> None:
        job = Job(
            job_id="12351",
            name="nodefail_job",
            state="NODE_FAIL",
            time="00:15:00",
            nodes="",
            node_list="node01",
            is_active=False,
        )
        assert job.state_category == JobState.FAILED

    def test_unknown_state_category(self) -> None:
        job = Job(
            job_id="12352",
            name="unknown_job",
            state="REQUEUED",
            time="00:00:00",
            nodes="",
            node_list="",
            is_active=False,
        )
        assert job.state_category == JobState.OTHER

    def test_as_row(self, running_job: Job) -> None:
        row = running_job.as_row()
        assert row == ("12345", "test_job", "RUNNING", "01:30:00", "1", "node01")

    def test_as_row_tuple_length(self, running_job: Job) -> None:
        row = running_job.as_row()
        assert len(row) == 6


class TestJobCache:
    """Tests for the JobCache singleton."""

    @pytest.fixture(autouse=True)
    def reset_cache(self) -> None:
        """Reset the singleton cache before each test."""
        JobCache.reset()

    def test_singleton_pattern(self) -> None:
        cache1 = JobCache()
        cache2 = JobCache()
        assert cache1 is cache2

    def test_initial_state(self) -> None:
        cache = JobCache()
        assert cache.jobs == []
        assert cache.running_count == 0
        assert cache.pending_count == 0
        assert cache.active_count == 0

    def test_stats_initial_values(self) -> None:
        cache = JobCache()
        total_jobs, total_requeues, max_requeues, running, pending = cache.stats
        assert total_jobs == 0
        assert total_requeues == 0
        assert max_requeues == 0
        assert running == 0
        assert pending == 0

    def test_get_active_jobs_empty(self) -> None:
        cache = JobCache()
        assert cache.get_active_jobs() == []

    def test_get_job_by_id_not_found(self) -> None:
        cache = JobCache()
        assert cache.get_job_by_id("99999") is None

    def test_reset_creates_new_instance(self) -> None:
        cache1 = JobCache()
        JobCache.reset()
        cache2 = JobCache()
        assert cache1 is not cache2
