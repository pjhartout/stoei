"""Tests for the JobCache module."""

from pathlib import Path

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


class TestJobCacheRefresh:
    """Tests for JobCache.refresh() method."""

    @pytest.fixture(autouse=True)
    def reset_cache(self) -> None:
        """Reset the singleton cache before each test."""
        JobCache.reset()

    def test_refresh_with_mock_data(self, mock_slurm_path: Path) -> None:
        """Test refresh populates cache with mock data."""
        cache = JobCache()
        cache.refresh()

        # Should have jobs from both squeue and sacct
        assert len(cache.jobs) > 0

    def test_refresh_updates_stats(self, mock_slurm_path: Path) -> None:
        """Test refresh updates statistics."""
        cache = JobCache()
        cache.refresh()

        total_jobs, _total_requeues, _max_requeues, _running, _pending = cache.stats
        assert total_jobs > 0

    def test_refresh_running_jobs_first(self, mock_slurm_path: Path) -> None:
        """Test that running/pending jobs appear before history jobs."""
        cache = JobCache()
        cache.refresh()

        jobs = cache.jobs
        # Active jobs should come before inactive jobs
        active_seen = False
        inactive_seen = False
        active_after_inactive = False

        for job in jobs:
            if job.is_active:
                active_seen = True
                if inactive_seen:
                    active_after_inactive = True
            else:
                inactive_seen = True

        # If we have both active and inactive jobs, active should come first
        if active_seen and inactive_seen:
            assert not active_after_inactive

    def test_refresh_deduplicates_jobs(self, mock_slurm_path: Path) -> None:
        """Test that jobs appearing in both squeue and sacct are not duplicated."""
        cache = JobCache()
        cache.refresh()

        job_ids = [job.job_id for job in cache.jobs]
        # Check for duplicates
        assert len(job_ids) == len(set(job_ids))

    def test_refresh_marks_active_jobs(self, mock_slurm_path: Path) -> None:
        """Test that running/pending jobs are marked as active."""
        cache = JobCache()
        cache.refresh()

        active_jobs = cache.get_active_jobs()
        for job in active_jobs:
            assert job.is_active
            assert job.state_category in (JobState.RUNNING, JobState.PENDING)


class TestJobCacheProperties:
    """Tests for JobCache property accessors."""

    @pytest.fixture(autouse=True)
    def reset_cache(self) -> None:
        """Reset the singleton cache before each test."""
        JobCache.reset()

    def test_jobs_property_returns_copy(self) -> None:
        """Test that jobs property returns a copy, not the original list."""
        cache = JobCache()

        jobs1 = cache.jobs
        jobs2 = cache.jobs

        # Should be equal but not the same object
        assert jobs1 == jobs2
        assert jobs1 is not jobs2

    def test_running_count_property(self, mock_slurm_path: Path) -> None:
        """Test running_count property after refresh."""
        cache = JobCache()
        cache.refresh()

        running_count = cache.running_count
        assert isinstance(running_count, int)
        assert running_count >= 0

    def test_pending_count_property(self, mock_slurm_path: Path) -> None:
        """Test pending_count property after refresh."""
        cache = JobCache()
        cache.refresh()

        pending_count = cache.pending_count
        assert isinstance(pending_count, int)
        assert pending_count >= 0

    def test_active_count_equals_running_plus_pending(self, mock_slurm_path: Path) -> None:
        """Test that active_count equals running + pending."""
        cache = JobCache()
        cache.refresh()

        assert cache.active_count == cache.running_count + cache.pending_count


class TestJobCacheJobLookup:
    """Tests for JobCache job lookup methods."""

    @pytest.fixture(autouse=True)
    def reset_cache(self) -> None:
        """Reset the singleton cache before each test."""
        JobCache.reset()

    def test_get_job_by_id_found(self, mock_slurm_path: Path) -> None:
        """Test get_job_by_id returns job when found."""
        cache = JobCache()
        cache.refresh()

        # Get first job and look it up by ID
        if cache.jobs:
            first_job = cache.jobs[0]
            found_job = cache.get_job_by_id(first_job.job_id)
            assert found_job is not None
            assert found_job.job_id == first_job.job_id

    def test_get_active_jobs_filter(self, mock_slurm_path: Path) -> None:
        """Test get_active_jobs returns only active jobs."""
        cache = JobCache()
        cache.refresh()

        active_jobs = cache.get_active_jobs()
        for job in active_jobs:
            assert job.is_active is True


class TestJobCacheThreadSafety:
    """Tests for JobCache thread safety."""

    @pytest.fixture(autouse=True)
    def reset_cache(self) -> None:
        """Reset the singleton cache before each test."""
        JobCache.reset()

    def test_singleton_with_lock(self) -> None:
        """Test that singleton creation is thread-safe."""
        JobCache()  # Initialize singleton
        assert hasattr(JobCache, "_lock")
        assert hasattr(JobCache, "_instance")

    def test_data_access_with_lock(self) -> None:
        """Test that data access uses a lock."""
        cache = JobCache()
        assert hasattr(cache, "_data_lock")
