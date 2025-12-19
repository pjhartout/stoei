"""Tests for the main SlurmMonitor app."""

from unittest.mock import MagicMock, patch

import pytest
from stoei.app import REFRESH_INTERVAL, SlurmMonitor
from stoei.slurm.cache import JobCache, JobState


class TestSlurmMonitorInit:
    """Tests for SlurmMonitor initialization."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    def test_init_sets_refresh_interval(self) -> None:
        app = SlurmMonitor()
        assert app.refresh_interval == REFRESH_INTERVAL

    def test_init_no_timer_initially(self) -> None:
        app = SlurmMonitor()
        assert app.auto_refresh_timer is None

    def test_init_no_refresh_worker_initially(self) -> None:
        app = SlurmMonitor()
        assert app._refresh_worker is None

    def test_init_initial_load_not_complete(self) -> None:
        app = SlurmMonitor()
        assert app._initial_load_complete is False


class TestFormatState:
    """Tests for the _format_state method."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Create a SlurmMonitor instance for testing."""
        return SlurmMonitor()

    def test_format_running_state(self, app: SlurmMonitor) -> None:
        result = app._format_state("RUNNING", JobState.RUNNING)
        assert "[bold green]RUNNING[/bold green]" in result

    def test_format_pending_state(self, app: SlurmMonitor) -> None:
        result = app._format_state("PENDING", JobState.PENDING)
        assert "[bold yellow]PENDING[/bold yellow]" in result

    def test_format_completed_state(self, app: SlurmMonitor) -> None:
        result = app._format_state("COMPLETED", JobState.COMPLETED)
        assert "[green]COMPLETED[/green]" in result

    def test_format_failed_state(self, app: SlurmMonitor) -> None:
        result = app._format_state("FAILED", JobState.FAILED)
        assert "[bold red]FAILED[/bold red]" in result

    def test_format_cancelled_state(self, app: SlurmMonitor) -> None:
        result = app._format_state("CANCELLED", JobState.CANCELLED)
        assert "[dim]CANCELLED[/dim]" in result

    def test_format_timeout_state(self, app: SlurmMonitor) -> None:
        result = app._format_state("TIMEOUT", JobState.TIMEOUT)
        assert "[red]TIMEOUT[/red]" in result

    def test_format_unknown_state_returns_raw(self, app: SlurmMonitor) -> None:
        result = app._format_state("UNKNOWN_STATE", JobState.OTHER)
        assert result == "UNKNOWN_STATE"


class TestStartRefreshWorker:
    """Tests for the _start_refresh_worker method."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    def test_refresh_worker_uses_thread_mode(self) -> None:
        """Verify that the refresh worker is started with thread=True.

        This is critical - without thread=True, a sync function passed to
        run_worker will raise WorkerError because it expects an async function.
        """
        app = SlurmMonitor()

        with patch.object(app, "run_worker", return_value=MagicMock()) as mock_run_worker:
            app._start_refresh_worker()

            mock_run_worker.assert_called_once_with(
                app._refresh_data_async,
                name="refresh_data",
                exclusive=True,
                thread=True,
            )

    def test_refresh_worker_not_restarted_when_running(self) -> None:
        """Verify that a new worker isn't started if one is already running."""
        from textual.worker import WorkerState

        app = SlurmMonitor()

        # Create a mock running worker
        mock_worker = MagicMock()
        mock_worker.state = WorkerState.RUNNING
        app._refresh_worker = mock_worker

        with patch.object(app, "run_worker") as mock_run_worker:
            app._start_refresh_worker()

            # run_worker should NOT be called since worker is already running
            mock_run_worker.assert_not_called()

    def test_refresh_worker_started_when_previous_finished(self) -> None:
        """Verify that a new worker is started if the previous one finished."""
        from textual.worker import WorkerState

        app = SlurmMonitor()

        # Create a mock finished worker
        mock_worker = MagicMock()
        mock_worker.state = WorkerState.SUCCESS
        app._refresh_worker = mock_worker

        with patch.object(app, "run_worker", return_value=MagicMock()) as mock_run_worker:
            app._start_refresh_worker()

            # run_worker should be called since previous worker finished
            mock_run_worker.assert_called_once()


class TestRefreshDataAsync:
    """Tests for the _refresh_data_async method."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    def test_refresh_data_is_sync_function(self) -> None:
        """Verify that _refresh_data_async is a regular sync function (not async).

        This confirms the need for thread=True in run_worker.
        """
        import inspect

        app = SlurmMonitor()

        # The method should NOT be a coroutine function
        assert not inspect.iscoroutinefunction(app._refresh_data_async)

    def test_refresh_data_calls_cache_refresh(self) -> None:
        """Verify that _refresh_data_async calls the cache refresh."""
        app = SlurmMonitor()

        with (
            patch.object(app._job_cache, "refresh") as mock_refresh,
            patch.object(app, "call_from_thread"),
        ):
            app._refresh_data_async()
            mock_refresh.assert_called_once()

    def test_refresh_data_schedules_ui_update(self) -> None:
        """Verify that _refresh_data_async schedules UI update on main thread."""
        app = SlurmMonitor()

        with (
            patch.object(app._job_cache, "refresh"),
            patch.object(app, "call_from_thread") as mock_call_from_thread,
        ):
            app._refresh_data_async()
            mock_call_from_thread.assert_called_once_with(app._update_ui_from_cache)
