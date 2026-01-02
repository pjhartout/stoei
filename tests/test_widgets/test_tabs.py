"""Unit tests for the TabContainer widget."""

import pytest
from stoei.widgets.tabs import TabContainer, TabSwitched
from textual.app import App
from textual.widgets import Button


class TestTabSwitched:
    """Tests for the TabSwitched message."""

    def test_tab_switched_creation(self) -> None:
        """Test creating a TabSwitched message."""
        message = TabSwitched("nodes")
        assert message.tab_name == "nodes"


class TabTestApp(App[None]):
    """Test app for tab testing."""

    def compose(self):
        """Create test app layout."""
        yield TabContainer(id="tab-container")


class TestTabContainer:
    """Tests for the TabContainer widget."""

    @pytest.fixture
    def tab_container(self) -> TabContainer:
        """Create a TabContainer widget for testing."""
        return TabContainer(id="test-tabs")

    def test_initial_active_tab(self, tab_container: TabContainer) -> None:
        """Test that initial active tab is 'jobs'."""
        assert tab_container.active_tab == "jobs"

    async def test_switch_tab_to_nodes(self) -> None:
        """Test switching to nodes tab."""
        app = TabTestApp()
        async with app.run_test(size=(80, 24)):
            tab_container = app.query_one("#tab-container", TabContainer)
            tab_container.switch_tab("nodes")
            assert tab_container.active_tab == "nodes"

    async def test_switch_tab_to_users(self) -> None:
        """Test switching to users tab."""
        app = TabTestApp()
        async with app.run_test(size=(80, 24)):
            tab_container = app.query_one("#tab-container", TabContainer)
            tab_container.switch_tab("users")
            assert tab_container.active_tab == "users"

    def test_switch_tab_same_tab(self, tab_container: TabContainer) -> None:
        """Test switching to the same tab does nothing."""
        initial_tab = tab_container.active_tab
        tab_container.switch_tab("jobs")
        assert tab_container.active_tab == initial_tab

    async def test_switch_tab_updates_button_states(self) -> None:
        """Test that switching tabs updates button active states."""
        app = TabTestApp()
        async with app.run_test(size=(80, 24)):
            tab_container = app.query_one("#tab-container", TabContainer)
            tab_container.switch_tab("nodes")
            assert tab_container.active_tab == "nodes"
            # Check button has active class
            nodes_btn = app.query_one("#tab-nodes", Button)
            assert "active" in nodes_btn.classes

    async def test_clicking_jobs_button_switches_tab(self) -> None:
        """Test that clicking jobs button switches to jobs tab."""
        app = TabTestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            tab_container = app.query_one("#tab-container", TabContainer)
            # First switch away from jobs
            tab_container.switch_tab("nodes")
            assert tab_container.active_tab == "nodes"

            # Now click the jobs button
            jobs_btn = app.query_one("#tab-jobs", Button)
            jobs_btn.press()
            await pilot.pause()
            assert tab_container.active_tab == "jobs"

    async def test_clicking_nodes_button_switches_tab(self) -> None:
        """Test that clicking nodes button switches to nodes tab."""
        app = TabTestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            tab_container = app.query_one("#tab-container", TabContainer)
            assert tab_container.active_tab == "jobs"

            # Click nodes button
            nodes_btn = app.query_one("#tab-nodes", Button)
            nodes_btn.press()
            await pilot.pause()
            assert tab_container.active_tab == "nodes"

    async def test_clicking_users_button_switches_tab(self) -> None:
        """Test that clicking users button switches to users tab."""
        app = TabTestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            tab_container = app.query_one("#tab-container", TabContainer)
            assert tab_container.active_tab == "jobs"

            # Click users button
            users_btn = app.query_one("#tab-users", Button)
            users_btn.press()
            await pilot.pause()
            assert tab_container.active_tab == "users"

    async def test_jobs_button_removes_active_from_other_buttons(self) -> None:
        """Test that switching removes active class from other buttons."""
        app = TabTestApp()
        async with app.run_test(size=(80, 24)):
            tab_container = app.query_one("#tab-container", TabContainer)

            # Switch to nodes
            tab_container.switch_tab("nodes")
            nodes_btn = app.query_one("#tab-nodes", Button)
            jobs_btn = app.query_one("#tab-jobs", Button)
            assert "active" in nodes_btn.classes
            assert "active" not in jobs_btn.classes

            # Switch back to jobs
            tab_container.switch_tab("jobs")
            assert "active" in jobs_btn.classes
            assert "active" not in nodes_btn.classes
