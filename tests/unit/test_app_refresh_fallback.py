"""Tests for the refresh fallback and error deduplication logic in app.py."""

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


class TestErrorNotificationDeduplication:
    """Tests for notification deduplication on repeated refresh failures."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    def test_history_failure_notifies_once(self) -> None:
        """First history failure shows notification, second does not."""
        app = SlurmMonitor()
        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]

        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            # First failure - should notify
            app._handle_refresh_fallback(running_jobs, None, 0, 0, 0)
            assert mock_call.call_count == 1

            # Second failure - should NOT notify again
            app._handle_refresh_fallback(running_jobs, None, 0, 0, 0)
            assert mock_call.call_count == 1

    def test_history_success_clears_error_flag(self) -> None:
        """Successful history fetch clears the error flag so next failure re-notifies."""
        app = SlurmMonitor()
        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]
        history_jobs = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]

        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            # First failure - notifies
            app._handle_refresh_fallback(running_jobs, None, 0, 0, 0)
            assert mock_call.call_count == 1

            # Success - clears flag
            app._handle_refresh_fallback(running_jobs, history_jobs, 1, 0, 0)
            assert app._error_notified.get("history_jobs") is False

            # Second failure after recovery - notifies again
            app._handle_refresh_fallback(running_jobs, None, 0, 0, 0)
            assert mock_call.call_count == 2

    def test_running_jobs_failure_notifies_once(self) -> None:
        """Running jobs failure notification shows only on first occurrence."""
        app = SlurmMonitor()

        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            # First failure
            results: dict[str, object] = {"user_jobs": (None, None, 0, 0, 0)}
            app._process_refresh_results(results)
            assert mock_call.call_count == 1
            assert app._error_notified.get("running_jobs") is True

            # Second failure - no new notification
            mock_call.reset_mock()
            app._process_refresh_results(results)
            assert mock_call.call_count == 0

    def test_running_jobs_success_clears_error_flag(self) -> None:
        """Successful running jobs fetch clears the error flag."""
        app = SlurmMonitor()
        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]
        history_jobs = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]

        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            # First failure
            results_fail: dict[str, object] = {"user_jobs": (None, None, 0, 0, 0)}
            app._process_refresh_results(results_fail)
            assert mock_call.call_count == 1

            # Success clears flag
            results_ok: dict[str, object] = {"user_jobs": (running_jobs, history_jobs, 1, 0, 0)}
            app._process_refresh_results(results_ok)
            assert app._error_notified.get("running_jobs") is False

            # Next failure re-notifies
            mock_call.reset_mock()
            app._process_refresh_results(results_fail)
            assert mock_call.call_count == 1

    def test_independent_tracking_of_running_and_history(self) -> None:
        """Running jobs and history errors are tracked independently."""
        app = SlurmMonitor()
        running_jobs = [("1", "job1", "RUNNING", "1:00", "1", "node1")]

        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            # Running OK, history fails - should notify once for history
            results: dict[str, object] = {"user_jobs": (running_jobs, None, 0, 0, 0)}
            app._process_refresh_results(results)
            assert mock_call.call_count == 1
            assert app._error_notified.get("running_jobs") is False
            assert app._error_notified.get("history_jobs") is True

    def test_both_fail_simultaneously(self) -> None:
        """Both running and history failing shows both notifications once."""
        app = SlurmMonitor()

        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            # Both fail
            results: dict[str, object] = {"user_jobs": (None, None, 0, 0, 0)}
            app._process_refresh_results(results)
            # Running jobs failed notification
            assert mock_call.call_count == 1
            assert app._error_notified.get("running_jobs") is True

            # Second cycle - no new notifications
            mock_call.reset_mock()
            app._process_refresh_results(results)
            assert mock_call.call_count == 0

    def test_manual_refresh_resets_error_flags(self) -> None:
        """Manual refresh clears error flags so user always gets feedback."""
        app = SlurmMonitor()

        # Pre-set error flags
        app._error_notified["running_jobs"] = True
        app._error_notified["history_jobs"] = True

        with (
            patch.object(app, "notify"),
            patch.object(app, "_start_refresh_worker"),
        ):
            app.action_refresh()

        assert app._error_notified == {}

    def test_history_processed_independently_when_running_fails(self) -> None:
        """Valid history data is still cached when running jobs fail."""
        app = SlurmMonitor()
        history_jobs = [("2", "job2", "COMPLETED", "0:00", "1", "node1")]

        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread"),
        ):
            results: dict[str, object] = {"user_jobs": (None, history_jobs, 5, 1, 2)}
            app._process_refresh_results(results)

            # History should be cached even though running jobs failed
            assert app._last_history_jobs == history_jobs
            assert app._last_history_stats == (5, 1, 2)
            assert app._error_notified.get("history_jobs") is False

    def test_user_jobs_not_in_results(self) -> None:
        """No notification or crash when user_jobs key is missing from results."""
        app = SlurmMonitor()

        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            results: dict[str, object] = {}
            app._process_refresh_results(results)
            # No notifications when the key is simply missing
            assert mock_call.call_count == 0
