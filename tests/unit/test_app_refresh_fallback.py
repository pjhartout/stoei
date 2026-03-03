"""Tests for the refresh fallback and error deduplication logic in app.py."""

from unittest.mock import MagicMock, patch

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


class TestApplyFetchResult:
    """Tests for _apply_fetch_result — one test per label."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Return a bare SlurmMonitor instance with heavy side-effects stubbed out."""
        instance = SlurmMonitor()
        # Stub out methods that walk the widget tree so they don't raise outside
        # a running Textual event loop.
        instance._parse_node_infos = MagicMock(return_value=[])  # type: ignore[method-assign]
        instance._compute_user_overview_cache = MagicMock()  # type: ignore[method-assign]
        instance._calculate_cluster_stats = MagicMock(return_value=None)  # type: ignore[method-assign]
        instance._compute_priority_overview_cache = MagicMock()  # type: ignore[method-assign]
        return instance

    # ------------------------------------------------------------------
    # user_jobs — running jobs fail path
    # ------------------------------------------------------------------

    def test_user_jobs_running_fail_notifies_and_updates_table(self, app: SlurmMonitor) -> None:
        """Failing running-jobs fetch notifies once and always schedules table update."""
        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            app._apply_fetch_result("user_jobs", (None, None, 0, 0, 0))

            # Error flag must be set
            assert app._error_notified.get("running_jobs") is True
            # call_from_thread called once: the warning notification lambda
            # (the table update is also scheduled — two calls total; first is
            # the notify lambda, second is _update_jobs_table)
            assert mock_call.call_count == 2
            # Second positional arg of the last call is _update_jobs_table (lambda)
            # We just verify it was called — we don't invoke it (needs event loop).
            assert mock_call.call_count >= 1

    def test_user_jobs_running_fail_second_time_no_extra_notification(self, app: SlurmMonitor) -> None:
        """Second consecutive running-jobs failure does not emit a second notification."""
        with (
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            app._apply_fetch_result("user_jobs", (None, None, 0, 0, 0))
            first_count = mock_call.call_count

            mock_call.reset_mock()
            app._apply_fetch_result("user_jobs", (None, None, 0, 0, 0))
            second_count = mock_call.call_count

            # First run: 2 calls (notify + table update)
            # Second run: only 1 call (table update, NO notify because flag already set)
            assert second_count < first_count

    # ------------------------------------------------------------------
    # nodes
    # ------------------------------------------------------------------

    def test_nodes_updates_cluster_nodes_and_schedules_tab_update(self, app: SlurmMonitor) -> None:
        """Nodes result updates _cluster_nodes and schedules _update_nodes_tab_only."""
        node_data: list[dict[str, str]] = [{"NodeName": "node1", "State": "IDLE"}]

        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("nodes", node_data)

        assert app._cluster_nodes == node_data
        mock_call.assert_called_once_with(app._update_nodes_tab_only)

    # ------------------------------------------------------------------
    # all_jobs
    # ------------------------------------------------------------------

    def test_all_jobs_updates_state_and_schedules_widget_update(self, app: SlurmMonitor) -> None:
        """all_jobs result stores data and schedules _update_all_jobs_widgets."""
        jobs: list[tuple[str, ...]] = [("1001", "jobA", "RUNNING", "2:00", "1", "nodeA")]

        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("all_jobs", jobs)

        assert app._all_users_jobs == jobs
        mock_call.assert_called_once_with(app._update_all_jobs_widgets)

    # ------------------------------------------------------------------
    # wait_time
    # ------------------------------------------------------------------

    def test_wait_time_updates_state_and_schedules_sidebar(self, app: SlurmMonitor) -> None:
        """wait_time result stores data and schedules a sidebar stats update."""
        wait_jobs: list[tuple[str, ...]] = [("1002", "jobB", "PENDING", "0:00", "1", "nodeB")]

        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("wait_time", wait_jobs)

        assert app._wait_time_jobs == wait_jobs
        assert mock_call.call_count == 1

    # ------------------------------------------------------------------
    # fair_share
    # ------------------------------------------------------------------

    def test_fair_share_first_half_does_not_update_priority_tab(self, app: SlurmMonitor) -> None:
        """First fair_share arrival increments counter but does not call update yet."""
        assert app._priority_halves_received == 0

        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("fair_share", ([], None))

        assert app._priority_halves_received == 1
        mock_call.assert_not_called()

    def test_fair_share_second_half_triggers_priority_tab_update(self, app: SlurmMonitor) -> None:
        """Second priority half (either label) triggers _update_priority_tab once."""
        # Simulate first half already received
        app._priority_halves_received = 1

        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("fair_share", ([], None))

        assert app._priority_halves_received == 0
        mock_call.assert_called_once_with(app._update_priority_tab)

    def test_fair_share_stores_entries_on_success(self, app: SlurmMonitor) -> None:
        """fair_share result without error stores entries in _fair_share_entries."""
        entries: list[tuple[str, ...]] = [("user1", "acct", "0.5")]

        with patch.object(app, "call_from_thread"):
            app._apply_fetch_result("fair_share", (entries, None))

        assert app._fair_share_entries == entries

    def test_fair_share_with_error_does_not_store_entries(self, app: SlurmMonitor) -> None:
        """fair_share result with an error string does not overwrite _fair_share_entries."""
        original: list[tuple[str, ...]] = [("user1", "acct", "0.5")]
        app._fair_share_entries = list(original)

        with (
            patch("stoei.app.logger") as mock_logger,
            patch.object(app, "call_from_thread"),
        ):
            app._apply_fetch_result("fair_share", ([], "sshare failed"))

        mock_logger.warning.assert_called_once()
        # Original entries unchanged
        assert app._fair_share_entries == original

    # ------------------------------------------------------------------
    # job_priority
    # ------------------------------------------------------------------

    def test_job_priority_first_half_does_not_update_priority_tab(self, app: SlurmMonitor) -> None:
        """First job_priority arrival increments counter but does not call update yet."""
        assert app._priority_halves_received == 0

        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("job_priority", ([], None))

        assert app._priority_halves_received == 1
        mock_call.assert_not_called()

    def test_job_priority_second_half_triggers_priority_tab_update(self, app: SlurmMonitor) -> None:
        """Second job_priority half triggers _update_priority_tab once."""
        app._priority_halves_received = 1

        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("job_priority", ([], None))

        assert app._priority_halves_received == 0
        mock_call.assert_called_once_with(app._update_priority_tab)

    def test_job_priority_stores_entries_on_success(self, app: SlurmMonitor) -> None:
        """job_priority result without error stores entries in _job_priority_entries."""
        entries: list[tuple[str, ...]] = [("999", "jobX", "0.75")]

        with patch.object(app, "call_from_thread"):
            app._apply_fetch_result("job_priority", (entries, None))

        assert app._job_priority_entries == entries

    def test_job_priority_with_error_does_not_store_entries(self, app: SlurmMonitor) -> None:
        """job_priority result with an error string does not overwrite existing entries."""
        original: list[tuple[str, ...]] = [("999", "jobX", "0.75")]
        app._job_priority_entries = list(original)

        with (
            patch("stoei.app.logger") as mock_logger,
            patch.object(app, "call_from_thread"),
        ):
            app._apply_fetch_result("job_priority", ([], "sprio failed"))

        mock_logger.warning.assert_called_once()
        assert app._job_priority_entries == original

    # ------------------------------------------------------------------
    # fair_share + job_priority coordination across two labels
    # ------------------------------------------------------------------

    def test_both_priority_halves_across_different_labels_trigger_one_update(self, app: SlurmMonitor) -> None:
        """One fair_share + one job_priority call triggers exactly one priority update."""
        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("fair_share", ([], None))
            app._apply_fetch_result("job_priority", ([], None))

        # Only the second call should have triggered _update_priority_tab
        assert mock_call.call_count == 1
        mock_call.assert_called_once_with(app._update_priority_tab)

    # ------------------------------------------------------------------
    # energy
    # ------------------------------------------------------------------

    def test_energy_loaded_true_schedules_energy_tab_update(self, app: SlurmMonitor) -> None:
        """Energy result with loaded=True stores data and schedules _update_energy_tab."""
        energy_jobs: list[tuple[str, ...]] = [("2001", "gpuJob", "COMPLETED")]

        with (
            patch(
                "stoei.widgets.user_overview.UserOverviewTab.aggregate_energy_stats",
                return_value=[],
            ),
            patch.object(app, "call_from_thread") as mock_call,
        ):
            app._apply_fetch_result("energy", (energy_jobs, True))

        assert app._energy_history_jobs == energy_jobs
        assert app._energy_data_loaded is True
        mock_call.assert_called_once_with(app._update_energy_tab)

    def test_energy_loaded_false_does_not_schedule_energy_tab_update(self, app: SlurmMonitor) -> None:
        """Energy result with loaded=False stores data but does NOT schedule tab update."""
        energy_jobs: list[tuple[str, ...]] = []

        with patch.object(app, "call_from_thread") as mock_call:
            app._apply_fetch_result("energy", (energy_jobs, False))

        assert app._energy_data_loaded is False
        mock_call.assert_not_called()

    # ------------------------------------------------------------------
    # unknown label
    # ------------------------------------------------------------------

    def test_unknown_label_logs_warning(self, app: SlurmMonitor) -> None:
        """An unrecognised label triggers a logger.warning call."""
        with patch("stoei.app.logger") as mock_logger:
            app._apply_fetch_result("totally_unknown_label", [])

        mock_logger.warning.assert_called_once()
        warning_message: str = mock_logger.warning.call_args[0][0]
        assert "totally_unknown_label" in warning_message


class TestOnRefreshComplete:
    """Tests for _on_refresh_complete — first-cycle and subsequent-cycle behaviour."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Return a SlurmMonitor instance with a pre-populated job info cache."""
        instance = SlurmMonitor()
        instance._job_info_cache["123"] = ("formatted", None, None, None)
        return instance

    def test_first_cycle_sets_initial_background_complete(self, app: SlurmMonitor) -> None:
        """First cycle sets _initial_background_complete = True."""
        app._initial_background_complete = False

        with (
            patch.object(app, "set_interval", return_value=MagicMock()),
            patch.object(app, "notify"),
        ):
            app._on_refresh_complete(is_first_cycle=True)

        assert app._initial_background_complete is True

    def test_first_cycle_starts_auto_refresh_timer(self, app: SlurmMonitor) -> None:
        """First cycle calls set_interval to set up the auto-refresh timer."""
        app._initial_background_complete = False

        with (
            patch.object(app, "set_interval", return_value=MagicMock()) as mock_set_interval,
            patch.object(app, "notify"),
        ):
            app._on_refresh_complete(is_first_cycle=True)

        mock_set_interval.assert_called_once_with(app.refresh_interval, app._start_refresh_worker)

    def test_first_cycle_notifies_user(self, app: SlurmMonitor) -> None:
        """First cycle calls notify to inform the user that data has loaded."""
        app._initial_background_complete = False

        with (
            patch.object(app, "set_interval", return_value=MagicMock()),
            patch.object(app, "notify") as mock_notify,
        ):
            app._on_refresh_complete(is_first_cycle=True)

        mock_notify.assert_called_once()
        notify_args, _ = mock_notify.call_args
        # The message should mention loaded/cluster data
        message: str = notify_args[0] if notify_args else ""
        assert "loaded" in message.lower() or "data" in message.lower()

    def test_first_cycle_clears_job_info_cache(self, app: SlurmMonitor) -> None:
        """_on_refresh_complete always clears the job info cache."""
        with (
            patch.object(app, "set_interval", return_value=MagicMock()),
            patch.object(app, "notify"),
        ):
            app._on_refresh_complete(is_first_cycle=True)

        assert app._job_info_cache == {}

    def test_subsequent_cycle_does_not_call_set_interval(self, app: SlurmMonitor) -> None:
        """Subsequent refresh cycles must not re-register the auto-refresh timer."""
        app._initial_background_complete = True

        with (
            patch.object(app, "set_interval") as mock_set_interval,
            patch.object(app, "notify") as mock_notify,
        ):
            app._on_refresh_complete(is_first_cycle=False)

        mock_set_interval.assert_not_called()
        mock_notify.assert_not_called()

    def test_subsequent_cycle_clears_job_info_cache(self, app: SlurmMonitor) -> None:
        """Subsequent refresh cycles still clear the job info cache."""
        app._initial_background_complete = True

        with (
            patch.object(app, "set_interval"),
            patch.object(app, "notify"),
        ):
            app._on_refresh_complete(is_first_cycle=False)

        assert app._job_info_cache == {}
