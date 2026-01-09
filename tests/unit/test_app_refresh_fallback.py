"""Tests for the refresh fallback logic in app.py."""

from unittest.mock import patch

import pytest
from stoei.app import SlurmMonitor
from stoei.slurm.cache import JobCache


class TestRefreshFallback:
    """Tests for partial failure handling in _refresh_data_async."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    def test_refresh_running_ok_history_ok(self) -> None:
        """Test normal case where both succeed."""
        app = SlurmMonitor()

        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]
        history_jobs = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]

        with (
            patch("stoei.app.get_running_jobs", return_value=(running_jobs, None)),
            patch("stoei.app.get_job_history", return_value=(history_jobs, 1, 0, 0, None)),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()

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
            patch("stoei.app.get_running_jobs", return_value=(running_jobs, None)),
            patch("stoei.app.get_job_history", return_value=(None, 0, 0, 0, "Error")),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()

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
            patch("stoei.app.get_running_jobs", return_value=(running_jobs, None)),
            patch("stoei.app.get_job_history", return_value=(None, 0, 0, 0, "Error")),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()

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
        running_jobs = []

        with (
            patch("stoei.app.get_running_jobs", return_value=(running_jobs, None)),
            patch("stoei.app.get_job_history", return_value=(None, 0, 0, 0, "Error")),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()

            # Expected: history_jobs should be exactly cached_history (no placeholder rows)
            call_args = mock_build.call_args
            assert call_args is not None
            args = call_args[0]
            passed_running = args[0]
            passed_history = args[1]

            assert passed_running == []
            assert passed_history == cached_history

    def test_refresh_running_fail_history_ok(self) -> None:
        """Test behavior when running jobs fail."""
        app = SlurmMonitor()

        history_jobs = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]

        with (
            patch("stoei.app.get_running_jobs", return_value=(None, "Error")),
            patch("stoei.app.get_job_history", return_value=(history_jobs, 1, 0, 0, None)),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()

            # Should NOT update cache because running jobs are critical
            mock_build.assert_not_called()

            # BUT should update cached history for future use
            assert app._last_history_jobs == history_jobs
