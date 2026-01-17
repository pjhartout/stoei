"""Tests for the FilterableDataTable widget."""

from __future__ import annotations

import pytest
from stoei.widgets.filterable_table import (
    ColumnConfig,
    FilterableDataTable,
    FilterState,
    SortDirection,
    SortState,
)
from textual.app import App
from textual.widgets import DataTable


class TestColumnConfig:
    """Tests for ColumnConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default values for ColumnConfig."""
        col = ColumnConfig(name="Test", key="test")
        assert col.name == "Test"
        assert col.key == "test"
        assert col.sortable is True
        assert col.filterable is True
        assert col.sort_key is None

    def test_custom_values(self) -> None:
        """Test custom values for ColumnConfig."""
        col = ColumnConfig(name="Test", key="test", sortable=False, filterable=False)
        assert col.sortable is False
        assert col.filterable is False


class TestSortState:
    """Tests for SortState dataclass."""

    def test_default_values(self) -> None:
        """Test default values for SortState."""
        state = SortState()
        assert state.column_key is None
        assert state.direction == SortDirection.NONE

    def test_custom_values(self) -> None:
        """Test custom values for SortState."""
        state = SortState(column_key="name", direction=SortDirection.ASCENDING)
        assert state.column_key == "name"
        assert state.direction == SortDirection.ASCENDING


class TestFilterState:
    """Tests for FilterState dataclass."""

    def test_default_values(self) -> None:
        """Test default values for FilterState."""
        state = FilterState()
        assert state.query == ""
        assert state.column_filters == {}
        assert state.general_filter == ""

    def test_custom_values(self) -> None:
        """Test custom values for FilterState."""
        state = FilterState(
            query="state:RUNNING test",
            column_filters={"state": "running"},
            general_filter="test",
        )
        assert state.query == "state:RUNNING test"
        assert state.column_filters == {"state": "running"}
        assert state.general_filter == "test"


class TestFilterableDataTableBasic:
    """Basic tests for FilterableDataTable widget."""

    def test_init_default_values(self) -> None:
        """Test default initialization values."""
        table = FilterableDataTable()
        assert table._columns == []
        assert table._keybind_mode == "vim"
        assert table._sort_state.column_key is None
        assert table._filter_state.query == ""

    def test_init_with_columns(self) -> None:
        """Test initialization with columns."""
        columns = [
            ColumnConfig(name="Name", key="name"),
            ColumnConfig(name="Value", key="value"),
        ]
        table = FilterableDataTable(columns=columns)
        assert len(table._columns) == 2
        assert table._columns[0].name == "Name"
        assert table._columns[1].name == "Value"

    def test_init_with_keybind_mode(self) -> None:
        """Test initialization with keybind mode."""
        table = FilterableDataTable(keybind_mode="emacs")
        assert table._keybind_mode == "emacs"

    def test_init_with_table_id(self) -> None:
        """Test initialization with custom table ID."""
        table = FilterableDataTable(table_id="custom_table")
        assert table._table_id == "custom_table"


class TestFilterableDataTableInApp:
    """Tests for FilterableDataTable running in an app context."""

    @pytest.fixture
    def sample_columns(self) -> list[ColumnConfig]:
        """Create sample column configurations."""
        return [
            ColumnConfig(name="Name", key="name", sortable=True, filterable=True),
            ColumnConfig(name="State", key="state", sortable=True, filterable=True),
            ColumnConfig(name="Value", key="value", sortable=True, filterable=True),
        ]

    @pytest.mark.asyncio
    async def test_composes_correctly(self, sample_columns: list[ColumnConfig]) -> None:
        """Test that FilterableDataTable composes correctly."""

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=sample_columns,
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Check the filterable table exists
            filterable = app.query_one("#filterable", FilterableDataTable)
            assert filterable is not None

            # Check the inner DataTable exists
            inner_table = app.query_one("#test_table", DataTable)
            assert inner_table is not None

    @pytest.mark.asyncio
    async def test_set_data(self, sample_columns: list[ColumnConfig]) -> None:
        """Test setting data on the table."""

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=sample_columns,
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)

            # Set some test data
            rows = [
                ("Alice", "RUNNING", "100"),
                ("Bob", "PENDING", "200"),
                ("Charlie", "COMPLETED", "300"),
            ]
            filterable.set_data(rows)
            await pilot.pause()

            # Check row count
            assert filterable.row_count == 3

    @pytest.mark.asyncio
    async def test_filter_by_general_term(self, sample_columns: list[ColumnConfig]) -> None:
        """Test filtering by a general term."""

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=sample_columns,
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)

            # Set some test data
            rows = [
                ("Alice", "RUNNING", "100"),
                ("Bob", "PENDING", "200"),
                ("Charlie", "COMPLETED", "300"),
            ]
            filterable.set_data(rows)

            # Apply filter
            filterable._apply_filter("alice")
            await pilot.pause()

            # Check that only matching rows are shown
            assert filterable.row_count == 1

    @pytest.mark.asyncio
    async def test_filter_by_column(self, sample_columns: list[ColumnConfig]) -> None:
        """Test filtering by a specific column."""

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=sample_columns,
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)

            # Set some test data
            rows = [
                ("Alice", "RUNNING", "100"),
                ("Bob", "PENDING", "200"),
                ("Charlie", "RUNNING", "300"),
            ]
            filterable.set_data(rows)

            # Apply column-specific filter
            filterable._apply_filter("state:RUNNING")
            await pilot.pause()

            # Check that only matching rows are shown
            assert filterable.row_count == 2

    @pytest.mark.asyncio
    async def test_clear_filter(self, sample_columns: list[ColumnConfig]) -> None:
        """Test clearing a filter."""

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=sample_columns,
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)

            # Set some test data
            rows = [
                ("Alice", "RUNNING", "100"),
                ("Bob", "PENDING", "200"),
                ("Charlie", "COMPLETED", "300"),
            ]
            filterable.set_data(rows)

            # Apply filter
            filterable._apply_filter("alice")
            await pilot.pause()
            assert filterable.row_count == 1

            # Clear filter
            filterable._apply_filter("")
            await pilot.pause()
            assert filterable.row_count == 3

    @pytest.mark.asyncio
    async def test_sort_ascending(self, sample_columns: list[ColumnConfig]) -> None:
        """Test sorting in ascending order."""

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=sample_columns,
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)

            # Set some test data
            rows = [
                ("Charlie", "RUNNING", "300"),
                ("Alice", "PENDING", "100"),
                ("Bob", "COMPLETED", "200"),
            ]
            filterable.set_data(rows)

            # Sort by name ascending
            filterable._set_sort("name", SortDirection.ASCENDING)
            await pilot.pause()

            # Check first row is Alice
            first_row = filterable.get_row_at(0)
            assert "Alice" in str(first_row[0])

    @pytest.mark.asyncio
    async def test_sort_descending(self, sample_columns: list[ColumnConfig]) -> None:
        """Test sorting in descending order."""

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=sample_columns,
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)

            # Set some test data
            rows = [
                ("Charlie", "RUNNING", "300"),
                ("Alice", "PENDING", "100"),
                ("Bob", "COMPLETED", "200"),
            ]
            filterable.set_data(rows)

            # Sort by name descending
            filterable._set_sort("name", SortDirection.DESCENDING)
            await pilot.pause()

            # Check first row is Charlie
            first_row = filterable.get_row_at(0)
            assert "Charlie" in str(first_row[0])

    @pytest.mark.asyncio
    async def test_filter_and_sort_combined(self, sample_columns: list[ColumnConfig]) -> None:
        """Test filtering and sorting together."""

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=sample_columns,
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)

            # Set some test data
            rows = [
                ("Charlie", "RUNNING", "300"),
                ("Alice", "RUNNING", "100"),
                ("Bob", "PENDING", "200"),
                ("David", "RUNNING", "400"),
            ]
            filterable.set_data(rows)

            # Filter by RUNNING and sort by name
            filterable._apply_filter("state:RUNNING")
            filterable._set_sort("name", SortDirection.ASCENDING)
            await pilot.pause()

            # Check we have 3 running jobs sorted by name
            assert filterable.row_count == 3
            first_row = filterable.get_row_at(0)
            assert "Alice" in str(first_row[0])


class TestFilterableDataTableVimMode:
    """Tests for vim keybind mode."""

    @pytest.mark.asyncio
    async def test_filter_hidden_by_default_in_vim_mode(self) -> None:
        """Test that filter is hidden by default in vim mode."""
        columns = [ColumnConfig(name="Name", key="name")]

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=columns,
                    keybind_mode="vim",
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)
            assert filterable.filter_visible is False


class TestFilterableDataTableEmacsMode:
    """Tests for emacs keybind mode."""

    @pytest.mark.asyncio
    async def test_filter_visible_in_emacs_mode(self) -> None:
        """Test that filter is visible in emacs mode."""
        columns = [ColumnConfig(name="Name", key="name")]

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=columns,
                    keybind_mode="emacs",
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)
            assert filterable.filter_visible is True

    @pytest.mark.asyncio
    async def test_set_keybind_mode(self) -> None:
        """Test changing keybind mode."""
        columns = [ColumnConfig(name="Name", key="name")]

        class TestApp(App[None]):
            def compose(self):
                yield FilterableDataTable(
                    columns=columns,
                    keybind_mode="vim",
                    table_id="test_table",
                    id="filterable",
                )

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            filterable = app.query_one("#filterable", FilterableDataTable)

            # Initially vim mode (hidden)
            assert filterable.filter_visible is False

            # Switch to emacs mode
            filterable.set_keybind_mode("emacs")
            await pilot.pause()
            assert filterable.filter_visible is True


class TestFilterableDataTableBindings:
    """Tests for keybindings."""

    def test_bindings_defined(self) -> None:
        """Test that bindings are defined."""
        assert len(FilterableDataTable.BINDINGS) > 0

    def test_bindings_include_filter(self) -> None:
        """Test that filter binding is included."""
        binding_keys = [b.key for b in FilterableDataTable.BINDINGS]
        assert "slash" in binding_keys

    def test_bindings_include_sort(self) -> None:
        """Test that sort binding is included."""
        binding_keys = [b.key for b in FilterableDataTable.BINDINGS]
        assert "o" in binding_keys

    def test_bindings_include_escape(self) -> None:
        """Test that escape binding is included."""
        binding_keys = [b.key for b in FilterableDataTable.BINDINGS]
        assert "escape" in binding_keys
