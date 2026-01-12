"""Tests for the main SlurmMonitor app."""

from unittest.mock import MagicMock, patch

import pytest
from stoei.app import SlurmMonitor
from stoei.settings import DEFAULT_REFRESH_INTERVAL
from stoei.slurm.cache import JobCache, JobState
from stoei.widgets.cluster_sidebar import ClusterStats


class TestSlurmMonitorInit:
    """Tests for SlurmMonitor initialization."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    def test_init_sets_refresh_interval_from_settings(self) -> None:
        app = SlurmMonitor()
        assert app.refresh_interval == app._settings.refresh_interval

    def test_init_uses_default_refresh_interval(self) -> None:
        app = SlurmMonitor()
        assert app.refresh_interval == DEFAULT_REFRESH_INTERVAL

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
        assert "[bright_black]CANCELLED[/bright_black]" in result

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

    def test_refresh_data_calls_cache_build(self) -> None:
        """Verify that _refresh_data_async calls the cache _build_from_data."""
        app = SlurmMonitor()

        with (
            patch("stoei.app.get_running_jobs", return_value=([], None)),
            patch("stoei.app.get_job_history", return_value=([], 0, 0, 0, None)),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data") as mock_build,
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()
            mock_build.assert_called_once()

    def test_refresh_data_schedules_ui_update(self) -> None:
        """Verify that _refresh_data_async schedules UI update on main thread."""
        app = SlurmMonitor()

        with (
            patch("stoei.app.get_running_jobs", return_value=([], None)),
            patch("stoei.app.get_job_history", return_value=([], 0, 0, 0, None)),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread") as mock_call_from_thread,
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()
            # It's called multiple times (for loading indicator, notify, and update), we check update is one of them
            # mock_call_from_thread.assert_any_call(app._update_ui_from_cache)
            # Or better, check that it's called with the update method
            calls = [call.args[0] for call in mock_call_from_thread.call_args_list if call.args]
            assert app._update_ui_from_cache in calls

    def test_refresh_data_fetches_cluster_nodes(self) -> None:
        """Verify that _refresh_data_async fetches cluster nodes."""
        from unittest.mock import patch

        app = SlurmMonitor()

        with (
            patch("stoei.app.get_running_jobs", return_value=([], None)),
            patch("stoei.app.get_job_history", return_value=([], 0, 0, 0, None)),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)) as mock_get_nodes,
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()
            mock_get_nodes.assert_called_once()

    def test_refresh_data_fetches_all_users_jobs(self) -> None:
        """Verify that _refresh_data_async fetches all running jobs."""
        from unittest.mock import patch

        app = SlurmMonitor()

        with (
            patch("stoei.app.get_running_jobs", return_value=([], None)),
            patch("stoei.app.get_job_history", return_value=([], 0, 0, 0, None)),
            patch("stoei.app.get_cluster_nodes", return_value=([], None)),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)) as mock_get_jobs,
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()
            mock_get_jobs.assert_called_once()

    def test_refresh_data_handles_cluster_nodes_error(self) -> None:
        """Verify that _refresh_data_async handles cluster nodes errors gracefully."""
        from unittest.mock import patch

        app = SlurmMonitor()

        with (
            patch("stoei.app.get_running_jobs", return_value=([], None)),
            patch("stoei.app.get_job_history", return_value=([], 0, 0, 0, None)),
            patch("stoei.app.get_cluster_nodes", return_value=([], "Error message")),
            patch("stoei.app.get_all_running_jobs", return_value=([], None)),
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            # Should not raise an error
            app._refresh_data_async()
            assert app._cluster_nodes == []


class TestCalculateClusterStats:
    """Tests for the _calculate_cluster_stats method."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Create a SlurmMonitor instance for testing."""
        return SlurmMonitor()

    def test_calculate_stats_empty_nodes(self, app: SlurmMonitor) -> None:
        """Test calculating stats with empty node list."""
        app._cluster_nodes = []
        stats = app._calculate_cluster_stats()
        assert stats.total_nodes == 0
        assert stats.total_cpus == 0

    def test_calculate_stats_single_node(self, app: SlurmMonitor) -> None:
        """Test calculating stats with a single node."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "IDLE",
                "CPUTot": "16",
                "CPUAlloc": "0",
                "RealMemory": "65536",  # 64 GB in MB
                "AllocMem": "0",
                "Gres": "",
            }
        ]
        stats = app._calculate_cluster_stats()
        assert stats.total_nodes == 1
        assert stats.free_nodes == 1
        assert stats.total_cpus == 16
        assert stats.allocated_cpus == 0

    def test_calculate_stats_idle_node(self, app: SlurmMonitor) -> None:
        """Test calculating stats for an IDLE node."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "IDLE",
                "CPUTot": "16",
                "CPUAlloc": "0",
                "RealMemory": "65536",
                "AllocMem": "0",
            }
        ]
        stats = app._calculate_cluster_stats()
        assert stats.free_nodes == 1
        assert stats.allocated_nodes == 0

    def test_calculate_stats_allocated_node(self, app: SlurmMonitor) -> None:
        """Test calculating stats for an ALLOCATED node."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "ALLOCATED",
                "CPUTot": "16",
                "CPUAlloc": "8",
                "RealMemory": "65536",
                "AllocMem": "32768",
            }
        ]
        stats = app._calculate_cluster_stats()
        assert stats.free_nodes == 0
        assert stats.allocated_nodes == 1
        assert stats.allocated_cpus == 8

    def test_calculate_stats_mixed_node(self, app: SlurmMonitor) -> None:
        """Test calculating stats for a MIXED node."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "MIXED",
                "CPUTot": "16",
                "CPUAlloc": "8",
                "RealMemory": "65536",
                "AllocMem": "32768",
            }
        ]
        stats = app._calculate_cluster_stats()
        assert stats.allocated_nodes == 1

    def test_calculate_stats_with_gpus(self, app: SlurmMonitor) -> None:
        """Test calculating stats with GPU information."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "ALLOCATED",
                "CPUTot": "16",
                "CPUAlloc": "8",
                "RealMemory": "65536",
                "AllocMem": "32768",
                "Gres": "gpu:a100:4",
            }
        ]
        stats = app._calculate_cluster_stats()
        assert stats.total_gpus == 4
        assert stats.allocated_gpus == 4

    def test_calculate_stats_with_gpu_idle(self, app: SlurmMonitor) -> None:
        """Test calculating stats with GPU on IDLE node."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "IDLE",
                "CPUTot": "16",
                "CPUAlloc": "0",
                "RealMemory": "65536",
                "AllocMem": "0",
                "Gres": "gpu:a100:4",
            }
        ]
        stats = app._calculate_cluster_stats()
        assert stats.total_gpus == 4
        assert stats.allocated_gpus == 0

    def test_calculate_stats_with_gpu_types(self, app: SlurmMonitor) -> None:
        """Test calculating stats with GPU types from CfgTRES and AllocTRES."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "MIXED",
                "CPUTot": "192",
                "CPUAlloc": "144",
                "RealMemory": "2000000",
                "AllocMem": "650000",
                "CfgTRES": "cpu=192,mem=2000000M,gres/gpu=8,gres/gpu:h200=8",
                "AllocTRES": "cpu=144,mem=650000M,gres/gpu=6,gres/gpu:h200=6",
            },
            {
                "NodeName": "node02",
                "State": "IDLE",
                "CPUTot": "192",
                "CPUAlloc": "0",
                "RealMemory": "2000000",
                "AllocMem": "0",
                "CfgTRES": "cpu=192,mem=2000000M,gres/gpu=8,gres/gpu:h200=8",
                "AllocTRES": "",
            },
        ]
        stats = app._calculate_cluster_stats()
        # Check total GPUs (only counting specific types to avoid double-counting)
        assert stats.total_gpus == 16  # 8 + 8 from two nodes (h200 only, generic skipped)
        assert stats.allocated_gpus == 6  # 6 from first node
        # Check GPU types (only specific types are tracked when they exist)
        assert "h200" in stats.gpus_by_type
        assert stats.gpus_by_type["h200"] == (16, 6)  # 16 total, 6 allocated
        # Generic "gpu" type is not tracked when specific types exist
        assert "gpu" not in stats.gpus_by_type

    def test_parse_node_infos_with_gpu_types(self, app: SlurmMonitor) -> None:
        """Test parsing node infos with GPU type information."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "ALLOCATED",
                "CPUTot": "16",
                "CPUAlloc": "8",
                "RealMemory": "65536",
                "AllocMem": "32768",
                "Gres": "gpu:a100:4",
                "Partitions": "gpu",
            },
            {
                "NodeName": "node02",
                "State": "IDLE",
                "CPUTot": "16",
                "CPUAlloc": "0",
                "RealMemory": "65536",
                "AllocMem": "0",
                "Gres": "gpu:h200:8(S:0-1)",
                "Partitions": "gpu",
            },
            {
                "NodeName": "node03",
                "State": "MIXED",
                "CPUTot": "16",
                "CPUAlloc": "8",
                "RealMemory": "65536",
                "AllocMem": "32768",
                "Gres": "gpu:4",
                "AllocTRES": "cpu=8,mem=32768M,gres/gpu=2",
                "Partitions": "gpu",
            },
        ]
        node_infos = app._parse_node_infos()
        assert len(node_infos) == 3

        # Check first node with A100 GPUs
        assert node_infos[0].name == "node01"
        assert node_infos[0].gpus_total == 4
        assert node_infos[0].gpus_alloc == 4
        assert node_infos[0].gpu_types == "4x A100"

        # Check second node with H200 GPUs
        assert node_infos[1].name == "node02"
        assert node_infos[1].gpus_total == 8
        assert node_infos[1].gpus_alloc == 0
        assert node_infos[1].gpu_types == "8x H200"

        # Check third node with generic GPUs
        assert node_infos[2].name == "node03"
        assert node_infos[2].gpus_total == 4
        assert node_infos[2].gpus_alloc == 2  # From AllocTRES for MIXED state
        assert node_infos[2].gpu_types == "4x GPU"

    def test_calculate_stats_invalid_cpu_values(self, app: SlurmMonitor) -> None:
        """Test calculating stats with invalid CPU values."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "IDLE",
                "CPUTot": "invalid",
                "CPUAlloc": "also_invalid",
                "RealMemory": "65536",
                "AllocMem": "0",
            }
        ]
        stats = app._calculate_cluster_stats()
        # Should handle ValueError gracefully
        assert stats.total_nodes == 1
        assert stats.total_cpus == 0
        assert stats.allocated_cpus == 0

    def test_calculate_stats_invalid_memory_values(self, app: SlurmMonitor) -> None:
        """Test calculating stats with invalid memory values."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "IDLE",
                "CPUTot": "16",
                "CPUAlloc": "0",
                "RealMemory": "invalid",
                "AllocMem": "also_invalid",
            }
        ]
        stats = app._calculate_cluster_stats()
        # Should handle ValueError gracefully
        assert stats.total_nodes == 1
        assert stats.total_memory_gb == 0.0

    def test_calculate_stats_memory_conversion(self, app: SlurmMonitor) -> None:
        """Test that memory is correctly converted from MB to GB."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "IDLE",
                "CPUTot": "16",
                "CPUAlloc": "0",
                "RealMemory": "1024",  # 1 GB in MB
                "AllocMem": "512",  # 0.5 GB in MB
            }
        ]
        stats = app._calculate_cluster_stats()
        assert stats.total_memory_gb == 1.0
        assert stats.allocated_memory_gb == 0.5

    def test_calculate_stats_multiple_nodes(self, app: SlurmMonitor) -> None:
        """Test calculating stats with multiple nodes."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "IDLE",
                "CPUTot": "16",
                "CPUAlloc": "0",
                "RealMemory": "65536",
                "AllocMem": "0",
            },
            {
                "NodeName": "node02",
                "State": "ALLOCATED",
                "CPUTot": "32",
                "CPUAlloc": "16",
                "RealMemory": "131072",
                "AllocMem": "65536",
            },
        ]
        stats = app._calculate_cluster_stats()
        assert stats.total_nodes == 2
        assert stats.free_nodes == 1
        assert stats.allocated_nodes == 1
        assert stats.total_cpus == 48
        assert stats.allocated_cpus == 16


class TestUpdateClusterSidebar:
    """Tests for the _update_cluster_sidebar method."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Create a SlurmMonitor instance for testing."""
        return SlurmMonitor()

    async def test_update_cluster_sidebar_updates_widget(self, app: SlurmMonitor) -> None:
        """Test that _update_cluster_sidebar updates the sidebar widget."""
        from stoei.widgets.cluster_sidebar import ClusterSidebar

        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                app._cluster_nodes = [
                    {
                        "NodeName": "node01",
                        "State": "IDLE",
                        "CPUTot": "16",
                        "CPUAlloc": "0",
                        "RealMemory": "65536",
                        "AllocMem": "0",
                    }
                ]
                app._update_cluster_sidebar()
                sidebar = app.query_one("#cluster-sidebar", ClusterSidebar)
                assert sidebar.stats.total_nodes == 1
                assert sidebar.stats.free_nodes == 1

    async def test_update_cluster_sidebar_handles_missing_widget(self, app: SlurmMonitor) -> None:
        """Test that _update_cluster_sidebar handles missing widget gracefully."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # Remove the sidebar widget
                sidebar = app.query_one("#cluster-sidebar")
                sidebar.remove()
                # Should not raise an error
                app._update_cluster_sidebar()

    async def test_update_cluster_sidebar_handles_calculation_error(self, app: SlurmMonitor) -> None:
        """Test that _update_cluster_sidebar handles calculation errors gracefully."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                with patch.object(app, "_calculate_cluster_stats", side_effect=Exception("Test error")):
                    # Should not raise an error, should log it instead
                    app._update_cluster_sidebar()


class TestUpdateUIFromCache:
    """Tests for the _update_ui_from_cache method."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Create a SlurmMonitor instance for testing."""
        return SlurmMonitor()

    async def test_update_ui_displays_jobs_from_cache(self, app: SlurmMonitor) -> None:
        """Test that _update_ui_from_cache displays jobs from the cache."""
        from stoei.slurm.cache import Job
        from textual.widgets import DataTable

        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # Add jobs directly to the cache
                app._job_cache._jobs = [
                    Job(
                        job_id="12345",
                        name="test_job_1",
                        state="RUNNING",
                        time="00:10:00",
                        nodes="1",
                        node_list="node01",
                        is_active=True,
                    ),
                    Job(
                        job_id="12346",
                        name="test_job_2",
                        state="COMPLETED",
                        time="01:00:00",
                        nodes="2",
                        node_list="node01,node02",
                        is_active=False,
                    ),
                ]

                app._update_ui_from_cache()
                jobs_table = app.query_one("#jobs_table", DataTable)
                assert jobs_table.row_count == 2

    async def test_update_ui_displays_both_active_and_completed_jobs(self, app: SlurmMonitor) -> None:
        """Test that both active (running/pending) and completed jobs are displayed."""
        from stoei.slurm.cache import Job
        from textual.widgets import DataTable

        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # Add mix of active and completed jobs
                app._job_cache._jobs = [
                    Job(
                        job_id="1",
                        name="running",
                        state="RUNNING",
                        time="00:05:00",
                        nodes="1",
                        node_list="n1",
                        is_active=True,
                    ),
                    Job(
                        job_id="2",
                        name="pending",
                        state="PENDING",
                        time="00:00:00",
                        nodes="1",
                        node_list="n2",
                        is_active=True,
                    ),
                    Job(
                        job_id="3",
                        name="completed",
                        state="COMPLETED",
                        time="01:00:00",
                        nodes="1",
                        node_list="n3",
                        is_active=False,
                    ),
                    Job(
                        job_id="4",
                        name="failed",
                        state="FAILED",
                        time="00:30:00",
                        nodes="1",
                        node_list="n4",
                        is_active=False,
                    ),
                    Job(
                        job_id="5",
                        name="cancelled",
                        state="CANCELLED",
                        time="00:15:00",
                        nodes="1",
                        node_list="n5",
                        is_active=False,
                    ),
                ]

                app._update_ui_from_cache()
                jobs_table = app.query_one("#jobs_table", DataTable)
                assert jobs_table.row_count == 5

    async def test_update_ui_preserves_cursor_position(self, app: SlurmMonitor) -> None:
        """Test that cursor position is preserved after update."""
        from stoei.slurm.cache import Job
        from textual.widgets import DataTable

        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # Add initial jobs
                app._job_cache._jobs = [
                    Job(
                        job_id="1",
                        name="job1",
                        state="RUNNING",
                        time="00:05:00",
                        nodes="1",
                        node_list="n1",
                        is_active=True,
                    ),
                    Job(
                        job_id="2",
                        name="job2",
                        state="RUNNING",
                        time="00:10:00",
                        nodes="1",
                        node_list="n2",
                        is_active=True,
                    ),
                    Job(
                        job_id="3",
                        name="job3",
                        state="RUNNING",
                        time="00:15:00",
                        nodes="1",
                        node_list="n3",
                        is_active=True,
                    ),
                ]

                app._update_ui_from_cache()
                jobs_table = app.query_one("#jobs_table", DataTable)
                # Move cursor to row 1
                jobs_table.move_cursor(row=1)

                # Update again
                app._update_ui_from_cache()

                # Cursor should still be at row 1
                assert jobs_table.cursor_row == 1

    async def test_update_ui_updates_existing_job_row_values(self, app: SlurmMonitor) -> None:
        """Test that a job row is updated in-place when cached values change."""
        from stoei.slurm.cache import Job
        from textual.widgets import DataTable

        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # Initial cached job
                app._job_cache._jobs = [
                    Job(
                        job_id="1",
                        name="job1",
                        state="RUNNING",
                        time="00:01:00",
                        nodes="1",
                        node_list="n1",
                        is_active=True,
                    )
                ]
                app._update_ui_from_cache()

                jobs_table = app.query_one("#jobs_table", DataTable)
                assert jobs_table.row_count == 1
                assert jobs_table.get_row_at(0)[3] == "00:01:00"  # Time column

                # Update the cache with changed time/state
                app._job_cache._jobs = [
                    Job(
                        job_id="1",
                        name="job1",
                        state="PENDING",
                        time="00:02:00",
                        nodes="1",
                        node_list="n1",
                        is_active=True,
                    )
                ]
                app._update_ui_from_cache()

                # The existing row should be updated (not duplicated)
                assert jobs_table.row_count == 1
                assert jobs_table.get_row_at(0)[3] == "00:02:00"

    async def test_update_ui_orders_pending_and_newest_jobs_first(self, app: SlurmMonitor) -> None:
        """Test that pending/newest jobs appear at the top after refresh."""
        from stoei.slurm.cache import Job
        from textual.widgets import DataTable

        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                app._job_cache._jobs = [
                    Job(
                        job_id="100",
                        name="running_old",
                        state="RUNNING",
                        time="00:10:00",
                        nodes="1",
                        node_list="n1",
                        is_active=True,
                    ),
                    Job(
                        job_id="101",
                        name="pending_new",
                        state="PENDING",
                        time="00:00:00",
                        nodes="1",
                        node_list="(Priority)",
                        is_active=True,
                    ),
                ]

                app._update_ui_from_cache()
                jobs_table = app.query_one("#jobs_table", DataTable)
                assert jobs_table.row_count == 2
                assert str(jobs_table.get_row_at(0)[0]) == "101"


class TestParseTresForPending:
    """Tests for the _parse_tres_for_pending method."""

    @pytest.fixture(autouse=True)
    def mock_slurm(self) -> None:
        """Mock SLURM availability check."""
        with patch("stoei.app.check_slurm_available", return_value=(True, None)):
            yield

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Create a SlurmMonitor instance for testing."""
        return SlurmMonitor()

    def test_parse_tres_empty_string(self, app: SlurmMonitor) -> None:
        """Test parsing empty TRES string."""
        cpus, memory, gpus = app._parse_tres_for_pending("")
        assert cpus == 0
        assert memory == 0.0
        assert gpus == []

    def test_parse_tres_cpu_only(self, app: SlurmMonitor) -> None:
        """Test parsing TRES with CPU only."""
        cpus, memory, gpus = app._parse_tres_for_pending("cpu=32")
        assert cpus == 32
        assert memory == 0.0
        assert gpus == []

    def test_parse_tres_memory_gb(self, app: SlurmMonitor) -> None:
        """Test parsing TRES with memory in GB."""
        cpus, memory, gpus = app._parse_tres_for_pending("cpu=8,mem=256G")
        assert cpus == 8
        assert memory == 256.0
        assert gpus == []

    def test_parse_tres_memory_mb(self, app: SlurmMonitor) -> None:
        """Test parsing TRES with memory in MB."""
        cpus, memory, gpus = app._parse_tres_for_pending("cpu=8,mem=2048M")
        assert cpus == 8
        assert memory == 2.0  # 2048 MB = 2 GB
        assert gpus == []

    def test_parse_tres_memory_tb(self, app: SlurmMonitor) -> None:
        """Test parsing TRES with memory in TB."""
        cpus, memory, gpus = app._parse_tres_for_pending("cpu=8,mem=2T")
        assert cpus == 8
        assert memory == 2048.0  # 2 TB = 2048 GB
        assert gpus == []

    def test_parse_tres_with_gpus(self, app: SlurmMonitor) -> None:
        """Test parsing TRES with GPUs."""
        cpus, memory, gpus = app._parse_tres_for_pending("cpu=64,mem=512G,node=8,gres/gpu=32")
        assert cpus == 64
        assert memory == 512.0
        assert gpus == [("gpu", 32)]

    def test_parse_tres_with_gpu_types(self, app: SlurmMonitor) -> None:
        """Test parsing TRES with typed GPUs."""
        cpus, memory, gpus = app._parse_tres_for_pending("cpu=64,mem=512G,gres/gpu:h200=8")
        assert cpus == 64
        assert memory == 512.0
        assert gpus == [("h200", 8)]

    def test_parse_tres_full_example(self, app: SlurmMonitor) -> None:
        """Test parsing a full TRES string."""
        tres = "cpu=768,mem=8000G,node=4,gres/gpu=32"
        cpus, memory, gpus = app._parse_tres_for_pending(tres)
        assert cpus == 768
        assert memory == 8000.0
        assert gpus == [("gpu", 32)]


class TestCalculatePendingResources:
    """Tests for the _calculate_pending_resources method."""

    @pytest.fixture(autouse=True)
    def mock_slurm(self) -> None:
        """Mock SLURM availability check."""
        with patch("stoei.app.check_slurm_available", return_value=(True, None)):
            yield

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Create a SlurmMonitor instance for testing."""
        return SlurmMonitor()

    def test_no_pending_jobs(self, app: SlurmMonitor) -> None:
        """Test with no pending jobs."""
        app._all_users_jobs = [
            ("12345", "job1", "user1", "RUNNING", "1:00:00", "1", "node01", "cpu=8,mem=32G"),
        ]
        stats = ClusterStats()
        app._calculate_pending_resources(stats)
        assert stats.pending_jobs_count == 0
        assert stats.pending_cpus == 0
        assert stats.pending_memory_gb == 0.0
        assert stats.pending_gpus == 0

    def test_single_pending_job(self, app: SlurmMonitor) -> None:
        """Test with a single pending job."""
        app._all_users_jobs = [
            ("12345", "job1", "user1", "PENDING", "0:00", "1", "(Priority)", "cpu=32,mem=256G,gres/gpu=4"),
        ]
        stats = ClusterStats()
        app._calculate_pending_resources(stats)
        assert stats.pending_jobs_count == 1
        assert stats.pending_cpus == 32
        assert stats.pending_memory_gb == 256.0
        assert stats.pending_gpus == 4

    def test_multiple_pending_jobs(self, app: SlurmMonitor) -> None:
        """Test with multiple pending jobs."""
        app._all_users_jobs = [
            ("12345", "job1", "user1", "PENDING", "0:00", "1", "(Priority)", "cpu=32,mem=256G,gres/gpu=4"),
            ("12346", "job2", "user2", "PENDING", "0:00", "2", "(Resources)", "cpu=64,mem=512G,gres/gpu=8"),
            ("12347", "job3", "user1", "RUNNING", "1:00:00", "1", "node01", "cpu=8,mem=32G"),
        ]
        stats = ClusterStats()
        app._calculate_pending_resources(stats)
        assert stats.pending_jobs_count == 2
        assert stats.pending_cpus == 96  # 32 + 64
        assert stats.pending_memory_gb == 768.0  # 256 + 512
        assert stats.pending_gpus == 12  # 4 + 8

    def test_pending_state_pd(self, app: SlurmMonitor) -> None:
        """Test that 'PD' state is recognized as pending."""
        app._all_users_jobs = [
            ("12345", "job1", "user1", "PD", "0:00", "1", "(Priority)", "cpu=16,mem=128G"),
        ]
        stats = ClusterStats()
        app._calculate_pending_resources(stats)
        assert stats.pending_jobs_count == 1
        assert stats.pending_cpus == 16

    def test_pending_gpus_by_type(self, app: SlurmMonitor) -> None:
        """Test that pending GPUs are aggregated by type."""
        app._all_users_jobs = [
            ("12345", "job1", "user1", "PENDING", "0:00", "1", "(Priority)", "cpu=32,mem=256G,gres/gpu:h200=8"),
            ("12346", "job2", "user2", "PENDING", "0:00", "2", "(Resources)", "cpu=64,mem=512G,gres/gpu:a100=4"),
            ("12347", "job3", "user3", "PENDING", "0:00", "1", "(Priority)", "cpu=32,mem=256G,gres/gpu:h200=4"),
        ]
        stats = ClusterStats()
        app._calculate_pending_resources(stats)
        assert stats.pending_jobs_count == 3
        assert stats.pending_gpus == 16  # 8 + 4 + 4
        assert stats.pending_gpus_by_type == {"h200": 12, "a100": 4}

    def test_pending_job_without_tres(self, app: SlurmMonitor) -> None:
        """Test pending job without TRES field."""
        app._all_users_jobs = [
            ("12345", "job1", "user1", "PENDING", "0:00", "1", "(Priority)"),  # No TRES field
        ]
        stats = ClusterStats()
        app._calculate_pending_resources(stats)
        assert stats.pending_jobs_count == 1
        assert stats.pending_cpus == 0  # No TRES data

    def test_empty_jobs_list(self, app: SlurmMonitor) -> None:
        """Test with empty jobs list."""
        app._all_users_jobs = []
        stats = ClusterStats()
        app._calculate_pending_resources(stats)
        assert stats.pending_jobs_count == 0
        assert stats.pending_cpus == 0
        assert stats.pending_memory_gb == 0.0
        assert stats.pending_gpus == 0
        assert stats.pending_gpus_by_type == {}
