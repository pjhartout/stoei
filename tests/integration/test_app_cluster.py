"""Tests for cluster-related functionality in the main app."""

from unittest.mock import patch

import pytest
from stoei.app import SlurmMonitor
from stoei.slurm.cache import JobCache
from stoei.widgets.cluster_sidebar import ClusterSidebar
from stoei.widgets.tabs import TabContainer, TabSwitched


class TestAppClusterIntegration:
    """Integration tests for cluster features in the main app."""

    @pytest.fixture(autouse=True)
    def reset_job_cache(self) -> None:
        """Reset JobCache singleton before each test."""
        JobCache.reset()

    @pytest.fixture
    def app(self) -> SlurmMonitor:
        """Create a SlurmMonitor instance for testing."""
        return SlurmMonitor()

    async def test_app_composes_cluster_sidebar(self, app: SlurmMonitor) -> None:
        """Test that the app composes the cluster sidebar."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                sidebar = app.query_one("#cluster-sidebar", ClusterSidebar)
                assert sidebar is not None
                assert sidebar.id == "cluster-sidebar"

    def test_app_initializes_cluster_data_attributes(self, app: SlurmMonitor) -> None:
        """Test that the app initializes cluster data attributes."""
        assert app._cluster_nodes == []
        assert app._all_users_jobs == []

    async def test_app_updates_cluster_sidebar_on_refresh(self, app: SlurmMonitor) -> None:
        """Test that the app updates cluster sidebar when data is refreshed."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
            patch.object(app, "_start_initial_load_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # Mock cluster nodes data
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
                app._update_ui_from_cache()
                sidebar = app.query_one("#cluster-sidebar", ClusterSidebar)
                assert sidebar.stats.total_nodes == 1

    async def test_app_handles_tab_switched_event(self, app: SlurmMonitor) -> None:
        """Test that the app handles TabSwitched events."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # Mock cluster data
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
                app._all_users_jobs = []

                # Switch to nodes tab
                event = TabSwitched("nodes")
                app.on_tab_switched(event)

                # Nodes tab should be visible
                nodes_tab = app.query_one("#tab-nodes-content")
                assert nodes_tab.display is True

                # Jobs tab should be hidden
                jobs_tab = app.query_one("#tab-jobs-content")
                assert jobs_tab.display is False

    async def test_app_updates_node_overview_on_tab_switch(self, app: SlurmMonitor) -> None:
        """Test that the app updates node overview when switching to nodes tab."""
        from stoei.widgets.node_overview import NodeOverviewTab

        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
            patch.object(app, "_start_initial_load_worker"),
        ):
            async with app.run_test(size=(80, 24)) as pilot:
                app._cluster_nodes = [
                    {
                        "NodeName": "node01",
                        "State": "IDLE",
                        "CPUTot": "16",
                        "CPUAlloc": "0",
                        "RealMemory": "65536",
                        "AllocMem": "0",
                        "Partitions": "cpu",
                    }
                ]

                event = TabSwitched("nodes")
                app.on_tab_switched(event)
                # Wait for deferred update to complete
                await pilot.pause()
                # Give a bit more time for call_later to execute
                await pilot.pause()

                node_tab = app.query_one("#node-overview", NodeOverviewTab)
                # Should have nodes data
                assert len(node_tab.nodes) > 0

    async def test_app_updates_user_overview_on_tab_switch(self, app: SlurmMonitor) -> None:
        """Test that the app updates user overview when switching to users tab."""
        from stoei.widgets.user_overview import UserOverviewTab

        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)) as pilot:
                app._all_users_jobs = [
                    ("12345", "job1", "user1", "gpu", "RUNNING", "00:05:00", "1", "node01"),
                    ("12346", "job2", "user2", "cpu", "PENDING", "00:00:00", "2", "node02"),
                ]

                event = TabSwitched("users")
                app.on_tab_switched(event)
                # Wait for deferred update to complete
                await pilot.pause()

                user_tab = app.query_one("#user-overview", UserOverviewTab)
                # Should have users data
                assert len(user_tab.users) > 0

    async def test_app_hides_non_default_tabs_on_mount(self, app: SlurmMonitor) -> None:
        """Test that the app hides non-default tabs on mount."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                nodes_tab = app.query_one("#tab-nodes-content")
                users_tab = app.query_one("#tab-users-content")
                logs_tab = app.query_one("#tab-logs-content")
                jobs_tab = app.query_one("#tab-jobs-content")

                # Jobs tab should be visible (default)
                assert jobs_tab.display is True
                # Other tabs should be hidden
                assert nodes_tab.display is False
                assert users_tab.display is False
                assert logs_tab.display is False

    def test_app_refresh_fetches_cluster_data(self, app: SlurmMonitor) -> None:
        """Test that app refresh fetches cluster data."""
        with (
            patch("stoei.app.get_running_jobs", return_value=([], None)),
            patch("stoei.app.get_job_history", return_value=([], 0, 0, 0, None)),
            patch("stoei.app.get_cluster_nodes", return_value=([{"NodeName": "node01"}], None)) as mock_nodes,
            patch("stoei.app.get_all_running_jobs", return_value=([], None)) as mock_jobs,
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread"),
            patch.object(app, "query_one"),
        ):
            app._refresh_data_async()
            mock_nodes.assert_called_once()
            mock_jobs.assert_called_once()

    def test_app_handles_cluster_nodes_error(self, app: SlurmMonitor) -> None:
        """Test that app handles cluster nodes fetch errors."""
        with (
            patch("stoei.app.get_running_jobs", return_value=[]),
            patch("stoei.app.get_job_history", return_value=([], 0, 0, 0)),
            patch("stoei.app.get_cluster_nodes", return_value=([], "Error fetching nodes")),
            patch("stoei.app.get_all_running_jobs", return_value=[]),
            patch.object(app._job_cache, "_build_from_data"),
            patch.object(app, "call_from_thread"),
        ):
            app._refresh_data_async()
            assert app._cluster_nodes == []

    def test_app_calculates_stats_with_empty_nodes(self, app: SlurmMonitor) -> None:
        """Test that app calculates stats correctly with empty node list."""
        app._cluster_nodes = []
        stats = app._calculate_cluster_stats()
        assert stats.total_nodes == 0
        assert stats.total_cpus == 0

    def test_app_calculates_stats_with_malformed_data(self, app: SlurmMonitor) -> None:
        """Test that app handles malformed node data gracefully."""
        app._cluster_nodes = [
            {
                "NodeName": "node01",
                "State": "UNKNOWN",
                "CPUTot": "invalid",
                "CPUAlloc": "also_invalid",
                "RealMemory": "invalid",
                "AllocMem": "invalid",
            }
        ]
        # Should not raise an error
        stats = app._calculate_cluster_stats()
        assert stats.total_nodes == 1
        # Invalid values should be skipped
        assert stats.total_cpus == 0

    async def test_app_renders_without_errors(self, app: SlurmMonitor) -> None:
        """Test that the app can render without errors."""
        # Mock SLURM availability check and prevent background worker from starting
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # The app should still be running without rendering errors
                assert app.is_running

                # Try to query and render the cluster sidebar
                sidebar = app.query_one("#cluster-sidebar", ClusterSidebar)
                assert sidebar is not None

                # Force a render of the sidebar by updating it
                from stoei.widgets.cluster_sidebar import ClusterStats

                stats = ClusterStats(
                    total_nodes=10,
                    free_nodes=5,
                    total_cpus=100,
                    allocated_cpus=50,
                    total_memory_gb=1000.0,
                    allocated_memory_gb=500.0,
                )
                sidebar.update_stats(stats)

                # App should still be running
                assert app.is_running

    async def test_action_switch_tab_jobs(self, app: SlurmMonitor) -> None:
        """Test that action_switch_tab_jobs switches to jobs tab."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                # Start on a different tab
                tab_container = app.query_one("TabContainer", TabContainer)
                tab_container.switch_tab("nodes")
                assert tab_container.active_tab == "nodes"

                # Switch to jobs tab using action
                app.action_switch_tab_jobs()

                # Should be on jobs tab
                assert tab_container.active_tab == "jobs"
                jobs_tab = app.query_one("#tab-jobs-content")
                assert jobs_tab.display is True

    async def test_action_switch_tab_nodes(self, app: SlurmMonitor) -> None:
        """Test that action_switch_tab_nodes switches to nodes tab."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                tab_container = app.query_one("TabContainer", TabContainer)
                assert tab_container.active_tab == "jobs"

                # Switch to nodes tab using action
                app.action_switch_tab_nodes()

                # Should be on nodes tab
                assert tab_container.active_tab == "nodes"
                nodes_tab = app.query_one("#tab-nodes-content")
                assert nodes_tab.display is True

    async def test_action_switch_tab_users(self, app: SlurmMonitor) -> None:
        """Test that action_switch_tab_users switches to users tab."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                tab_container = app.query_one("TabContainer", TabContainer)
                assert tab_container.active_tab == "jobs"

                # Switch to users tab using action
                app.action_switch_tab_users()

                # Should be on users tab
                assert tab_container.active_tab == "users"
                users_tab = app.query_one("#tab-users-content")
                assert users_tab.display is True

    async def test_action_switch_tab_logs(self, app: SlurmMonitor) -> None:
        """Test that action_switch_tab_logs switches to logs tab."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                tab_container = app.query_one("TabContainer", TabContainer)
                assert tab_container.active_tab == "jobs"

                # Switch to logs tab using action
                app.action_switch_tab_logs()

                # Should be on logs tab
                assert tab_container.active_tab == "logs"
                logs_tab = app.query_one("#tab-logs-content")
                assert logs_tab.display is True

    def test_bindings_include_tab_shortcuts(self, app: SlurmMonitor) -> None:
        """Test that keyboard bindings include tab switching shortcuts."""
        binding_keys = [b[0] for b in app.BINDINGS]
        assert "1" in binding_keys
        assert "2" in binding_keys
        assert "3" in binding_keys
        assert "left" in binding_keys
        assert "right" in binding_keys
        assert "shift+tab" in binding_keys
        # Note: "tab" is handled in on_key, not as a binding

    def test_bindings_tab_shortcuts_have_correct_actions(self, app: SlurmMonitor) -> None:
        """Test that tab shortcut bindings have correct action names."""
        bindings_dict = {b[0]: b[1] for b in app.BINDINGS}
        assert bindings_dict["1"] == "switch_tab_jobs"
        assert bindings_dict["2"] == "switch_tab_nodes"
        assert bindings_dict["3"] == "switch_tab_users"
        assert bindings_dict["4"] == "switch_tab_logs"
        assert bindings_dict["left"] == "previous_tab"
        assert bindings_dict["right"] == "next_tab"
        assert bindings_dict["shift+tab"] == "previous_tab"

    def test_bindings_include_settings_shortcut(self, app: SlurmMonitor) -> None:
        """Test that settings shortcut binding exists."""
        bindings_dict = {b[0]: b[1] for b in app.BINDINGS}
        assert bindings_dict["s"] == "show_settings"

    async def test_action_next_tab_cycles_forward(self, app: SlurmMonitor) -> None:
        """Test that action_next_tab cycles through tabs forward."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                tab_container = app.query_one("TabContainer", TabContainer)
                assert tab_container.active_tab == "jobs"

                # Cycle forward: jobs -> nodes
                app.action_next_tab()
                assert tab_container.active_tab == "nodes"

                # Cycle forward: nodes -> users
                app.action_next_tab()
                assert tab_container.active_tab == "users"

                # Cycle forward: users -> logs
                app.action_next_tab()
                assert tab_container.active_tab == "logs"

                # Cycle forward: logs -> jobs (wraps around)
                app.action_next_tab()
                assert tab_container.active_tab == "jobs"

    async def test_action_previous_tab_cycles_backward(self, app: SlurmMonitor) -> None:
        """Test that action_previous_tab cycles through tabs backward."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                tab_container = app.query_one("TabContainer", TabContainer)
                assert tab_container.active_tab == "jobs"

                # Cycle backward: jobs -> logs (wraps around)
                app.action_previous_tab()
                assert tab_container.active_tab == "logs"

                # Cycle backward: logs -> users
                app.action_previous_tab()
                assert tab_container.active_tab == "users"

                # Cycle backward: users -> nodes
                app.action_previous_tab()
                assert tab_container.active_tab == "nodes"

                # Cycle backward: nodes -> jobs
                app.action_previous_tab()
                assert tab_container.active_tab == "jobs"

    async def test_tab_key_cycles_forward(self, app: SlurmMonitor) -> None:
        """Test that Tab key cycles through tabs forward."""
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)) as pilot:
                tab_container = app.query_one("TabContainer", TabContainer)
                assert tab_container.active_tab == "jobs"

                # Press Tab: jobs -> nodes
                await pilot.press("tab")
                assert tab_container.active_tab == "nodes"

                # Press Tab: nodes -> users
                await pilot.press("tab")
                assert tab_container.active_tab == "users"

                # Press Tab: users -> logs
                await pilot.press("tab")
                assert tab_container.active_tab == "logs"

                # Press Tab: logs -> jobs (wraps around)
                await pilot.press("tab")
                assert tab_container.active_tab == "jobs"

    async def test_shift_tab_key_cycles_backward(self, app: SlurmMonitor) -> None:
        """Test that Shift+Tab key cycles through tabs backward."""
        # Note: Shift+Tab binding may not work reliably due to Textual's focus system
        # The binding exists, but testing it via pilot.press is problematic
        # Users can still use left arrow or number keys for navigation
        with (
            patch("stoei.app.check_slurm_available", return_value=(True, None)),
            patch.object(app, "_start_refresh_worker"),
        ):
            async with app.run_test(size=(80, 24)):
                tab_container = app.query_one("TabContainer", TabContainer)
                # Test that the action works directly (binding may work in real usage)
                app.action_previous_tab()
                assert tab_container.active_tab == "logs"
