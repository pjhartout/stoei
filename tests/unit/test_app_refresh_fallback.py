"""Tests for the refresh fallback logic in app.py."""

from unittest.mock import patch

import pytest
from stoei.app import SlurmMonitor
from stoei.slurm.cache import JobCache


class TestRefreshFallback:
    """Tests for partial failure handling in _handle_refresh_fallback."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    def test_refresh_running_ok_history_ok(self) -> None:
        """Test normal case where both succeed."""
        app = SlurmMonitor()

        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]
        history_jobs = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]

        with patch.object(app._job_cache, "_build_from_data") as mock_build:
            app._handle_refresh_fallback(running_jobs, history_jobs, 1, 0, 0)

            # Should update cache with both
            mock_build.assert_called_once_with(running_jobs, history_jobs, 1, 0, 0)

            # Should update cached history
            assert app._last_history_jobs == history_jobs
            assert app._last_history_stats == (1, 0, 0)

    def test_refresh_running_ok_history_fail_first_time(self) -> None:
        """Test fallback when history fails and we have no cached history."""
        app = SlurmMonitor()

        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]

        with (
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
        ):
            app._handle_refresh_fallback(running_jobs, None, 0, 0, 0)

            # Should update cache with running jobs and default empty history
            # because _last_history_jobs is empty initially
            mock_build.assert_called_once_with(running_jobs, [], 0, 0, 0)

    def test_refresh_running_ok_history_fail_cached(self) -> None:
        """Test fallback when history fails but we have cached history."""
        app = SlurmMonitor()

        # Pre-populate cache
        cached_history = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]
        app._last_history_jobs = cached_history
        app._last_history_stats = (1, 0, 0)

        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]

        with (
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
        ):
            app._handle_refresh_fallback(running_jobs, None, 0, 0, 0)

            # Should update cache with running jobs and CACHED history
            mock_build.assert_called_once_with(running_jobs, cached_history, 1, 0, 0)

    def test_refresh_does_not_create_placeholder_orphaned_jobs(self) -> None:
        """Test that we do not create placeholder 'UNKNOWN' jobs when history refresh fails."""
        app = SlurmMonitor()
        # We simulate a job finishing, but history fetch failing; we keep cached history
        # and do not synthesize placeholder history entries.

        # Cached history has job 2
        cached_history = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]
        app._last_history_jobs = cached_history
        app._last_history_stats = (1, 0, 0)

        # New running jobs is EMPTY (job 1 finished)
        running_jobs: list[tuple[str, ...]] = []

        with (
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
        ):
            app._handle_refresh_fallback(running_jobs, None, 0, 0, 0)

            # Expected: history_jobs should be exactly cached_history (no placeholder rows)
            call_args = mock_build.call_args
            assert call_args is not None
            args = call_args[0]
            passed_running = args[0]
            passed_history = args[1]

            assert passed_running == []
            assert passed_history == cached_history


class TestJobsDataReadyHandler:
    """Tests for the on_slurm_monitor_jobs_data_ready message handler."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    def test_handler_calls_fallback_when_running_jobs_present(self) -> None:
        """Test that the handler calls _handle_refresh_fallback when running_jobs is not None."""
        app = SlurmMonitor()

        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]
        history_jobs = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]

        message = SlurmMonitor.JobsDataReady(running_jobs, history_jobs, 1, 0, 0)

        with (
            patch.object(app, "_handle_refresh_fallback") as mock_fallback,
            patch.object(app, "query_one"),
        ):
            app.on_slurm_monitor_jobs_data_ready(message)
            mock_fallback.assert_called_once_with(running_jobs, history_jobs, 1, 0, 0)

    def test_handler_notifies_on_running_jobs_failure(self) -> None:
        """Test that the handler notifies when running_jobs is None."""
        app = SlurmMonitor()

        message = SlurmMonitor.JobsDataReady(None, None, 0, 0, 0)

        with (
            patch.object(app, "_handle_refresh_fallback") as mock_fallback,
            patch.object(app, "notify") as mock_notify,
        ):
            app.on_slurm_monitor_jobs_data_ready(message)
            mock_fallback.assert_not_called()
            mock_notify.assert_called_once()
