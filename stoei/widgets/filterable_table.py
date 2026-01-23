"""Filterable and sortable DataTable wrapper widget."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from stoei.keybindings import Actions, KeybindingConfig, get_default_config
from stoei.logger import get_logger

if TYPE_CHECKING:
    from textual.widgets.data_table import CellType, RowKey

logger = get_logger(__name__)


class SortDirection(Enum):
    """Sort direction for table columns."""

    NONE = "none"
    ASCENDING = "asc"
    DESCENDING = "desc"


@dataclass
class ColumnConfig:
    """Configuration for a table column."""

    name: str
    key: str
    sortable: bool = True
    filterable: bool = True
    # Custom sort key function (e.g., for numeric sorting)
    sort_key: Callable[[Any], Any] | None = None
    # Column width configuration
    width: int | None = None  # Width in characters, None for auto
    min_width: int = 5  # Minimum width to prevent unusable columns
    max_width: int | None = None  # Maximum width, None for unlimited


@dataclass
class SortState:
    """Current sort state for the table."""

    column_key: str | None = None
    direction: SortDirection = SortDirection.NONE


@dataclass
class FilterState:
    """Current filter state for the table."""

    query: str = ""
    # Parsed column-specific filters: {"column_key": "filter_value"}
    column_filters: dict[str, str] = field(default_factory=dict)
    # General filter (applies to all columns)
    general_filter: str = ""


class FilterChanged(Message):
    """Message sent when the filter changes."""

    def __init__(self, filter_state: FilterState) -> None:
        """Initialize the FilterChanged message.

        Args:
            filter_state: The new filter state.
        """
        super().__init__()
        self.filter_state = filter_state


class SortChanged(Message):
    """Message sent when the sort changes."""

    def __init__(self, sort_state: SortState) -> None:
        """Initialize the SortChanged message.

        Args:
            sort_state: The new sort state.
        """
        super().__init__()
        self.sort_state = sort_state


class FilterableDataTable(Vertical):
    """A DataTable wrapper with filtering and sorting capabilities.

    Features:
    - Filter bar that can be shown/hidden (vim mode) or always visible (emacs mode)
    - Column-specific filtering with prefix syntax (e.g., "state:RUNNING")
    - General filtering across all columns
    - Sortable columns with visual indicators
    - Click column headers or use keyboard to sort
    """

    DEFAULT_CSS: ClassVar[str] = """
    FilterableDataTable {
        height: 100%;
        width: 100%;
    }

    FilterableDataTable .filter-bar {
        height: auto;
        width: 100%;
        padding: 0 1;
        background: $surface;
        display: none;
    }

    FilterableDataTable .filter-bar.visible {
        display: block;
    }

    FilterableDataTable .filter-bar.always-visible {
        display: block;
    }

    FilterableDataTable .filter-input {
        width: 100%;
        height: 1;
        border: none;
        background: $surface;
    }

    FilterableDataTable .filter-help {
        height: 1;
        color: $text-muted;
        text-style: italic;
    }

    FilterableDataTable .filter-status {
        height: 1;
        color: $text-muted;
        dock: right;
        width: auto;
        padding-right: 1;
    }

    FilterableDataTable DataTable {
        height: 1fr;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("slash", "show_filter", "Filter", show=True),
        Binding("escape", "hide_filter", "Clear filter", show=False),
        Binding("o", "cycle_sort", "Sort", show=True),
    ]

    # Reactive property to track filter visibility
    filter_visible: reactive[bool] = reactive(False)

    def __init__(  # noqa: PLR0913
        self,
        *,
        columns: list[ColumnConfig] | None = None,
        keybind_mode: str = "vim",
        keybindings: KeybindingConfig | None = None,
        table_id: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """Initialize the FilterableDataTable.

        Args:
            columns: Column configurations for the table.
            keybind_mode: "vim" (filter hidden by default) or "emacs" (always visible).
            keybindings: Optional keybinding configuration (uses default for mode if not provided).
            table_id: ID for the inner DataTable widget.
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled.
        """
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self._columns = columns or []
        self._keybind_mode = keybind_mode
        self._keybindings = keybindings or get_default_config(keybind_mode)
        self._table_id = table_id or "filterable-inner-table"
        self._sort_state = SortState()
        self._filter_state = FilterState()
        # Store original data for filtering
        self._all_rows: list[tuple[Any, ...]] = []
        # Map column names to keys for filtering
        self._column_name_to_key: dict[str, str] = {}
        self._column_key_to_index: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        """Create the filterable table layout."""
        # Filter bar container
        filter_classes = "filter-bar"
        if self._keybind_mode == "emacs":
            filter_classes += " always-visible visible"

        with Vertical(classes=filter_classes, id="filter-bar-container"):
            yield Input(
                placeholder="Filter... (e.g., 'state:RUNNING' or 'search term')",
                classes="filter-input",
                id="filter-input",
            )
            yield Static(
                "[dim]Enter to apply, Escape to clear[/dim]",
                classes="filter-help",
                id="filter-help",
            )

        # The actual data table
        yield DataTable(id=self._table_id)

    def on_mount(self) -> None:
        """Initialize the table after mounting."""
        # Set up column name to key mapping
        for idx, col in enumerate(self._columns):
            self._column_name_to_key[col.name.lower()] = col.key
            self._column_key_to_index[col.key] = idx

        # Add columns to the inner table
        table = self.query_one(f"#{self._table_id}", DataTable)
        table.cursor_type = "row"

        for col in self._columns:
            # Add column with width if specified
            table.add_column(col.name, key=col.key, width=col.width)

        # Show filter bar if emacs mode
        if self._keybind_mode == "emacs":
            self.filter_visible = True
            self._update_filter_bar_visibility()

    @property
    def table(self) -> DataTable:
        """Get the inner DataTable widget."""
        return self.query_one(f"#{self._table_id}", DataTable)

    @property
    def sort_state(self) -> SortState:
        """Get the current sort state."""
        return self._sort_state

    @property
    def filter_state(self) -> FilterState:
        """Get the current filter state."""
        return self._filter_state

    def set_keybind_mode(self, mode: str, keybindings: KeybindingConfig | None = None) -> None:
        """Set the keybind mode and optionally update keybindings.

        Args:
            mode: "vim" or "emacs".
            keybindings: Optional keybinding configuration (uses default for mode if not provided).
        """
        self._keybind_mode = mode
        self._keybindings = keybindings or get_default_config(mode)
        if mode == "emacs":
            self.filter_visible = True
        self._update_filter_bar_visibility()

    def _update_filter_bar_visibility(self) -> None:
        """Update the filter bar visibility based on current state."""
        try:
            filter_bar = self.query_one("#filter-bar-container", Vertical)
            if self._keybind_mode == "emacs":
                filter_bar.add_class("always-visible")
                filter_bar.add_class("visible")
            elif self.filter_visible:
                filter_bar.add_class("visible")
                filter_bar.remove_class("always-visible")
            else:
                filter_bar.remove_class("visible")
                filter_bar.remove_class("always-visible")
        except Exception as exc:
            logger.debug(f"Failed to update filter bar visibility: {exc}")

    def watch_filter_visible(self, visible: bool) -> None:
        """React to filter visibility changes."""
        self._update_filter_bar_visibility()
        if visible:
            try:
                filter_input = self.query_one("#filter-input", Input)
                filter_input.focus()
            except Exception as exc:
                logger.debug(f"Failed to focus filter input: {exc}")

    def action_show_filter(self) -> None:
        """Show the filter bar and focus the input."""
        self.filter_visible = True

    def action_hide_filter(self) -> None:
        """Hide the filter bar and clear the filter."""
        if self._keybind_mode == "vim":
            self.filter_visible = False
        # Clear the filter
        try:
            filter_input = self.query_one("#filter-input", Input)
            filter_input.value = ""
        except Exception as exc:
            logger.debug(f"Failed to clear filter input: {exc}")
        self._apply_filter("")
        # Focus the table
        self.table.focus()

    def action_cycle_sort(self) -> None:
        """Cycle through sortable columns."""
        if not self._columns:
            return

        sortable_columns = [c for c in self._columns if c.sortable]
        if not sortable_columns:
            return

        current_key = self._sort_state.column_key
        current_direction = self._sort_state.direction

        if current_key is None:
            # Start with first sortable column, ascending
            new_key = sortable_columns[0].key
            new_direction = SortDirection.ASCENDING
        else:
            # Find current column index
            current_idx = next(
                (i for i, c in enumerate(sortable_columns) if c.key == current_key),
                -1,
            )

            if current_direction == SortDirection.ASCENDING:
                # Switch to descending
                new_key = current_key
                new_direction = SortDirection.DESCENDING
            elif current_direction == SortDirection.DESCENDING:
                # Move to next column or clear
                next_idx = (current_idx + 1) % len(sortable_columns)
                if next_idx == 0 and current_idx == len(sortable_columns) - 1:
                    # Wrap around means clear sort
                    new_key = None
                    new_direction = SortDirection.NONE
                else:
                    new_key = sortable_columns[next_idx].key
                    new_direction = SortDirection.ASCENDING
            else:
                new_key = sortable_columns[0].key
                new_direction = SortDirection.ASCENDING

        self._set_sort(new_key, new_direction)

    def _set_sort(self, column_key: str | None, direction: SortDirection) -> None:
        """Set the sort state and update the table.

        Args:
            column_key: The column key to sort by, or None to clear.
            direction: The sort direction.
        """
        old_state = self._sort_state
        self._sort_state = SortState(column_key=column_key, direction=direction)

        # Update column headers with sort indicators
        self._update_sort_indicators()

        # Re-apply data with new sort
        self._refresh_table_data()

        # Post message if sort changed
        if old_state.column_key != column_key or old_state.direction != direction:
            self.post_message(SortChanged(self._sort_state))

    def _update_sort_indicators(self) -> None:
        """Update column headers to show sort indicators."""
        # Note: Textual's DataTable doesn't support updating column labels directly
        # We would need to recreate columns or use a custom approach
        # For now, we'll rely on the status display
        pass

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header clicks for sorting.

        Args:
            event: The header selected event.
        """
        column_key = str(event.column_key)

        # Find the column config
        col_config = next((c for c in self._columns if c.key == column_key), None)
        if col_config is None or not col_config.sortable:
            return

        # Toggle sort direction
        if self._sort_state.column_key == column_key:
            if self._sort_state.direction == SortDirection.ASCENDING:
                new_direction = SortDirection.DESCENDING
            elif self._sort_state.direction == SortDirection.DESCENDING:
                new_direction = SortDirection.NONE
                column_key = None
            else:
                new_direction = SortDirection.ASCENDING
        else:
            new_direction = SortDirection.ASCENDING

        self._set_sort(column_key, new_direction)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle filter input submission.

        Args:
            event: The input submitted event.
        """
        if event.input.id == "filter-input":
            self._apply_filter(event.value)
            # Focus table after applying filter
            self.table.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input changes for live filtering.

        Args:
            event: The input changed event.
        """
        if event.input.id == "filter-input":
            # Apply filter as user types
            self._apply_filter(event.value)

    def _parse_filter_query(self, query: str) -> FilterState:
        """Parse a filter query into column-specific and general filters.

        Syntax:
        - "state:RUNNING" -> filter State column for "RUNNING"
        - "user:john state:PD" -> filter User for "john" AND State for "PD"
        - "search term" -> filter all columns for "search term"

        Args:
            query: The filter query string.

        Returns:
            Parsed FilterState.
        """
        column_filters: dict[str, str] = {}

        # Pattern for column:value
        pattern = re.compile(r"(\w+):(\S+)")

        remaining = query
        for match in pattern.finditer(query):
            col_name = match.group(1).lower()
            col_value = match.group(2)

            # Check if this is a valid column
            if col_name in self._column_name_to_key:
                column_filters[self._column_name_to_key[col_name]] = col_value.lower()
                remaining = remaining.replace(match.group(0), "", 1)

        # Remaining text is the general filter
        general_filter = " ".join(remaining.split()).lower()

        return FilterState(
            query=query,
            column_filters=column_filters,
            general_filter=general_filter,
        )

    def _apply_filter(self, query: str) -> None:
        """Apply a filter query to the table.

        Args:
            query: The filter query string.
        """
        old_state = self._filter_state
        self._filter_state = self._parse_filter_query(query)

        self._refresh_table_data()

        # Post message if filter changed
        if old_state.query != query:
            self.post_message(FilterChanged(self._filter_state))

    def _row_matches_filter(self, row: tuple[Any, ...]) -> bool:
        """Check if a row matches the current filter.

        Args:
            row: The row data tuple.

        Returns:
            True if the row matches the filter.
        """
        if not self._filter_state.query:
            return True

        # Check column-specific filters
        for col_key, filter_value in self._filter_state.column_filters.items():
            col_idx = self._column_key_to_index.get(col_key)
            if col_idx is not None and col_idx < len(row):
                cell_value = str(row[col_idx]).lower()
                # Remove Rich markup for comparison
                cell_value = re.sub(r"\[.*?\]", "", cell_value)
                if filter_value not in cell_value:
                    return False

        # Check general filter (matches any column)
        if self._filter_state.general_filter:
            found = False
            for cell in row:
                cell_value = str(cell).lower()
                # Remove Rich markup for comparison
                cell_value = re.sub(r"\[.*?\]", "", cell_value)
                if self._filter_state.general_filter in cell_value:
                    found = True
                    break
            if not found:
                return False

        return True

    def _sort_rows(self, rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
        """Sort rows according to current sort state.

        Args:
            rows: The rows to sort.

        Returns:
            Sorted rows.
        """
        if self._sort_state.column_key is None or self._sort_state.direction == SortDirection.NONE:
            return rows

        col_idx = self._column_key_to_index.get(self._sort_state.column_key)
        if col_idx is None:
            return rows

        # Find custom sort key function if defined
        col_config = next((c for c in self._columns if c.key == self._sort_state.column_key), None)
        sort_key_func = col_config.sort_key if col_config else None

        def get_sort_key(row: tuple[Any, ...]) -> Any:
            if col_idx >= len(row):
                return ""
            value = row[col_idx]
            # Remove Rich markup for sorting
            str_value = re.sub(r"\[.*?\]", "", str(value))
            if sort_key_func:
                return sort_key_func(str_value)
            # Try numeric sort
            try:
                return float(str_value.replace(",", ""))
            except ValueError:
                return str_value.lower()

        reverse = self._sort_state.direction == SortDirection.DESCENDING
        return sorted(rows, key=get_sort_key, reverse=reverse)

    def _refresh_table_data(self) -> None:
        """Refresh the table with filtered and sorted data."""
        table = self.table

        # Save cursor position
        cursor_row = table.cursor_row

        # Filter rows
        filtered_rows = [row for row in self._all_rows if self._row_matches_filter(row)]

        # Sort rows
        sorted_rows = self._sort_rows(filtered_rows)

        # Update table
        table.clear(columns=False)
        for row in sorted_rows:
            table.add_row(*row)

        # Restore cursor position
        if cursor_row is not None and table.row_count > 0:
            new_row = min(cursor_row, table.row_count - 1)
            table.move_cursor(row=new_row)

        # Update filter status
        self._update_filter_status(len(filtered_rows), len(self._all_rows))

    def _update_filter_status(self, visible: int, total: int) -> None:
        """Update the filter status display.

        Args:
            visible: Number of visible rows.
            total: Total number of rows.
        """
        try:
            help_text = self.query_one("#filter-help", Static)
            if self._filter_state.query:
                status = f"Showing {visible}/{total}"
                if self._sort_state.column_key:
                    direction = "▲" if self._sort_state.direction == SortDirection.ASCENDING else "▼"
                    status += f" | Sort: {self._sort_state.column_key} {direction}"
                help_text.update(f"[dim]{status} | Enter to apply, Escape to clear[/dim]")
            elif self._sort_state.column_key:
                direction = "▲" if self._sort_state.direction == SortDirection.ASCENDING else "▼"
                help_text.update(
                    f"[dim]Sort: {self._sort_state.column_key} {direction} | Enter to apply, Escape to clear[/dim]"
                )
            else:
                help_text.update("[dim]Enter to apply, Escape to clear[/dim]")
        except Exception as exc:
            logger.debug(f"Failed to update filter status: {exc}")

    def set_data(self, rows: list[tuple[Any, ...]]) -> None:
        """Set the table data.

        This stores all rows and applies current filter/sort.

        Args:
            rows: List of row data tuples.
        """
        self._all_rows = list(rows)
        self._refresh_table_data()

    def add_row(self, *cells: CellType, key: str | None = None) -> RowKey:
        """Add a row to the table.

        Args:
            *cells: Cell values for the row.
            key: Optional row key.

        Returns:
            The row key.
        """
        self._all_rows.append(cells)
        # Only add to visible table if it matches filter
        if self._row_matches_filter(cells):
            return self.table.add_row(*cells, key=key)
        # Return a dummy key if not visible
        return RowKey("")

    def clear(self, columns: bool = False) -> None:
        """Clear the table data.

        Args:
            columns: Whether to also clear columns.
        """
        self._all_rows.clear()
        self.table.clear(columns=columns)

    def on_key(self, event: Key) -> None:
        """Handle key events.

        Handles both vim and emacs mode keybindings.

        Args:
            event: The key event.
        """
        key = event.key

        # Handle escape/ctrl+g for hiding filter
        hide_key = self._keybindings.get_key(Actions.FILTER_HIDE)
        if key in {hide_key, "escape"}:
            try:
                filter_input = self.query_one("#filter-input", Input)
                if filter_input.has_focus:
                    event.stop()
                    self.action_hide_filter()
                    return
            except Exception as exc:
                logger.debug(f"Failed to handle escape key in filter input: {exc}")

        # Handle emacs-mode keybindings
        if self._keybind_mode == "emacs":
            filter_show_key = self._keybindings.get_key(Actions.FILTER_SHOW)
            sort_key = self._keybindings.get_key(Actions.SORT_CYCLE)

            if key == filter_show_key:
                event.stop()
                self.action_show_filter()
                return

            if key == sort_key:
                event.stop()
                self.action_cycle_sort()
                return

    def get_sort_indicator(self, column_key: str) -> str:
        """Get the sort indicator for a column.

        Args:
            column_key: The column key.

        Returns:
            Sort indicator string ("▲", "▼", or "").
        """
        if self._sort_state.column_key != column_key:
            return ""
        if self._sort_state.direction == SortDirection.ASCENDING:
            return " ▲"
        if self._sort_state.direction == SortDirection.DESCENDING:
            return " ▼"
        return ""

    @property
    def row_count(self) -> int:
        """Get the number of visible rows."""
        return self.table.row_count

    @property
    def cursor_row(self) -> int | None:
        """Get the current cursor row."""
        return self.table.cursor_row

    def focus(self, scroll_visible: bool = True) -> FilterableDataTable:
        """Focus the table.

        Args:
            scroll_visible: Whether to scroll the widget into view.

        Returns:
            Self for chaining.
        """
        self.table.focus(scroll_visible=scroll_visible)
        return self

    def get_row_at(self, index: int) -> list[Any]:
        """Get row data at the given index.

        Args:
            index: The row index.

        Returns:
            Row data.
        """
        return self.table.get_row_at(index)

    # Column width management
    _selected_column_index: int = 0

    def get_selected_column_index(self) -> int:
        """Get the currently selected column index for resizing."""
        return self._selected_column_index

    def select_next_column(self) -> None:
        """Select the next column for resizing."""
        if not self._columns:
            return
        self._selected_column_index = (self._selected_column_index + 1) % len(self._columns)
        logger.debug(f"Selected column: {self._columns[self._selected_column_index].key}")

    def select_previous_column(self) -> None:
        """Select the previous column for resizing."""
        if not self._columns:
            return
        self._selected_column_index = (self._selected_column_index - 1) % len(self._columns)
        logger.debug(f"Selected column: {self._columns[self._selected_column_index].key}")

    def get_selected_column_key(self) -> str | None:
        """Get the key of the currently selected column."""
        if not self._columns or self._selected_column_index >= len(self._columns):
            return None
        return self._columns[self._selected_column_index].key

    def resize_selected_column(self, delta: int) -> bool:
        """Resize the selected column by delta characters.

        Args:
            delta: Change in width (positive to grow, negative to shrink).

        Returns:
            True if the column was resized, False otherwise.
        """
        if not self._columns or self._selected_column_index >= len(self._columns):
            return False

        col_config = self._columns[self._selected_column_index]
        table = self.table

        # Get the column from the DataTable
        try:
            column = table.columns.get(col_config.key)
            if column is None:
                logger.warning(f"Column {col_config.key} not found in DataTable")
                return False

            # Get current width (use content_width if width is not set)
            current_width = column.width if column.width else column.content_width
            if current_width is None:
                current_width = 10  # Default if we can't determine

            new_width = current_width + delta

            # Enforce min/max constraints from ColumnConfig
            new_width = max(col_config.min_width, new_width)
            if col_config.max_width is not None:
                new_width = min(col_config.max_width, new_width)

            # Apply the new width
            column.width = new_width
            table.refresh()

            logger.debug(f"Resized column {col_config.key}: {current_width} -> {new_width}")
        except Exception as exc:
            logger.warning(f"Failed to resize column {col_config.key}: {exc}")
            return False
        else:
            return True

    def reset_selected_column_width(self) -> bool:
        """Reset the selected column to its default width.

        Returns:
            True if the column was reset, False otherwise.
        """
        if not self._columns or self._selected_column_index >= len(self._columns):
            return False

        col_config = self._columns[self._selected_column_index]
        table = self.table

        try:
            column = table.columns.get(col_config.key)
            if column is None:
                return False

            # Reset to the default width from ColumnConfig
            column.width = col_config.width
            table.refresh()

            logger.debug(f"Reset column {col_config.key} to width {col_config.width}")
        except Exception as exc:
            logger.warning(f"Failed to reset column {col_config.key}: {exc}")
            return False
        else:
            return True

    def get_column_widths(self) -> dict[str, int]:
        """Get current column widths.

        Returns:
            Dictionary mapping column keys to their current widths.
        """
        widths: dict[str, int] = {}
        table = self.table

        for col_config in self._columns:
            try:
                column = table.columns.get(col_config.key)  # type: ignore[arg-type]
                if column is not None and column.width is not None:
                    widths[col_config.key] = column.width
            except Exception:
                logger.debug(f"Could not get width for column {col_config.key}")

        return widths

    def set_column_widths(self, widths: dict[str, int]) -> None:
        """Apply column widths from a saved configuration.

        Args:
            widths: Dictionary mapping column keys to widths.
        """
        table = self.table

        for col_key, col_width in widths.items():
            try:
                column = table.columns.get(col_key)  # type: ignore[arg-type]
                if column is not None:
                    # Find the column config to get min/max constraints
                    col_config = next((c for c in self._columns if c.key == col_key), None)
                    final_width = col_width
                    if col_config:
                        final_width = max(col_config.min_width, final_width)
                        if col_config.max_width is not None:
                            final_width = min(col_config.max_width, final_width)
                    column.width = final_width
            except Exception as exc:
                logger.warning(f"Failed to set width for column {col_key}: {exc}")

        table.refresh()
