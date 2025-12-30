"""Unit tests for the TabContainer widget."""

import pytest
from textual.app import App
from textual.containers import Container
from textual.widgets import Button

from stoei.widgets.tabs import TabContainer, TabSwitched


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
        async with app.run_test() as pilot:
            tab_container = app.query_one("#tab-container", TabContainer)
            tab_container.switch_tab("nodes")
            assert tab_container.active_tab == "nodes"

    async def test_switch_tab_to_users(self) -> None:
        """Test switching to users tab."""
        app = TabTestApp()
        async with app.run_test() as pilot:
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
        async with app.run_test() as pilot:
            tab_container = app.query_one("#tab-container", TabContainer)
            tab_container.switch_tab("nodes")
            assert tab_container.active_tab == "nodes"
            # Check button has active class
            nodes_btn = app.query_one("#tab-nodes", Button)
            assert "active" in nodes_btn.classes
