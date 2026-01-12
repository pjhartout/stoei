"""Settings screen for updating persistent preferences."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Button, Input, Select, Static

from stoei.logger import get_logger
from stoei.settings import LOG_LEVELS, MIN_LOG_LINES, Settings
from stoei.themes import THEME_LABELS

logger = get_logger(__name__)


class SettingsScreen(Screen[Settings | None]):
    """Modal screen for editing application settings."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("ctrl+x", "cancel", "Cancel"),
        ("ctrl+s", "save_settings", "Save"),
        ("shift+tab", "focus_previous", "Previous field"),
        ("home", "focus_first", "First field"),
        ("end", "focus_last", "Last field"),
        ("t", "jump_theme", "Jump to Theme"),
        ("l", "jump_log_level", "Jump to Log Level"),
        ("m", "jump_max_lines", "Jump to Max Lines"),
    )

    # Order of focusable widgets for navigation
    FOCUS_ORDER: ClassVar[tuple[str, ...]] = (
        "#settings-theme",
        "#settings-log-level",
        "#settings-max-lines",
        "#settings-save",
        "#settings-cancel",
    )

    def __init__(self, settings: Settings) -> None:
        """Initialize the settings screen.

        Args:
            settings: Current settings values.
        """
        super().__init__()
        self._settings = settings

    def compose(self) -> ComposeResult:
        """Compose the settings screen layout."""
        with Vertical(id="settings-container"):
            yield Static("⚙️  [bold]Settings[/bold]", id="settings-title")
            yield Static("Theme", classes="settings-label")
            yield Select(
                [(label, value) for value, label in THEME_LABELS.items()],
                value=self._settings.theme,
                prompt="Select a theme",
                allow_blank=False,
                id="settings-theme",
            )
            yield Static("Log level", classes="settings-label")
            yield Select(
                [(level, level) for level in LOG_LEVELS],
                value=self._settings.log_level,
                prompt="Select log level",
                allow_blank=False,
                id="settings-log-level",
            )
            yield Static("Max log lines", classes="settings-label")
            yield Input(str(self._settings.max_log_lines), id="settings-max-lines")
            with Container(id="settings-button-row"):
                yield Button("💾 Save", variant="primary", id="settings-save")
                yield Button("✕ Cancel", variant="default", id="settings-cancel")

    def on_mount(self) -> None:
        """Focus the first setting control."""
        self.query_one("#settings-theme", Select).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event.
        """
        if event.button.id == "settings-save":
            self._save_settings()
        elif event.button.id == "settings-cancel":
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        """Handle key events for enhanced navigation.

        Args:
            event: The key event.
        """
        focused = self.focused

        # Handle Tab for forward navigation (Shift+Tab is handled by binding)
        if event.key == "tab" and event.name == "tab":
            event.stop()
            self.action_focus_next()
            return

        # Handle up/down arrows for focus navigation
        # We need to intercept these before Select widgets handle them
        if event.key in ("up", "down"):
            # If any Select dropdown is open, let it handle navigation
            # (focus moves to SelectOverlay when open, so check all Selects)
            for select in self.query(Select):
                if select.expanded:
                    return
            # Otherwise, use for focus navigation
            event.stop()
            if event.key == "down":
                self.action_focus_next()
            else:
                self.action_focus_previous()
            return

        # Handle Enter key based on focused widget
        if event.key == "enter":
            if focused is None:
                return

            # On Input, move to next field
            if isinstance(focused, Input):
                event.stop()
                self.action_focus_next()
                return

            # On Select, let default behavior handle dropdown
            # On Button, let default behavior handle activation

        # Handle left/right arrows on Select widgets to cycle options
        if event.key in ("left", "right") and isinstance(focused, Select) and not focused.expanded:
            event.stop()
            # Type narrow: we know it's a Select[str] in this screen
            select_widget: Select[str] = focused  # type: ignore[assignment]
            self._cycle_select_option(select_widget, direction=1 if event.key == "right" else -1)

    def _cycle_select_option(self, select: Select[str], direction: int) -> None:
        """Cycle through Select options without opening dropdown.

        Args:
            select: The Select widget to cycle.
            direction: 1 for next, -1 for previous.
        """
        # Get available options
        options = list(select._options)
        if not options:
            return

        current_value = select.value
        current_index = -1

        # Find current selection index
        for i, (_, value) in enumerate(options):
            if value == current_value:
                current_index = i
                break

        # Calculate new index with wrapping
        new_index = 0 if current_index == -1 else (current_index + direction) % len(options)

        # Set new value
        new_value = options[new_index][1]
        select.value = new_value

    def _get_focus_index(self) -> int:
        """Get the index of the currently focused widget in FOCUS_ORDER.

        Returns:
            Index of focused widget, or -1 if not found.
        """
        focused = self.focused
        if focused is None:
            return -1

        for i, selector in enumerate(self.FOCUS_ORDER):
            try:
                widget = self.query_one(selector)
                if widget is focused:
                    return i
            except Exception as exc:
                logger.debug(f"Failed to query widget {selector}: {exc}")
                continue
        return -1

    def _focus_by_index(self, index: int) -> None:
        """Focus the widget at the given index in FOCUS_ORDER.

        Args:
            index: Index in FOCUS_ORDER to focus.
        """
        if not self.FOCUS_ORDER:
            return

        # Wrap index to valid range
        index = index % len(self.FOCUS_ORDER)
        selector = self.FOCUS_ORDER[index]

        try:
            widget = self.query_one(selector)
            widget.focus()
        except Exception as exc:
            logger.debug(f"Failed to focus widget {selector}: {exc}")

    def action_focus_next(self) -> None:
        """Focus the next widget in the focus order."""
        current = self._get_focus_index()
        self._focus_by_index(current + 1)

    def action_focus_previous(self) -> None:
        """Focus the previous widget in the focus order."""
        current = self._get_focus_index()
        if current == -1:
            self._focus_by_index(len(self.FOCUS_ORDER) - 1)
        else:
            self._focus_by_index(current - 1)

    def action_focus_first(self) -> None:
        """Focus the first widget in the focus order."""
        self._focus_by_index(0)

    def action_focus_last(self) -> None:
        """Focus the last widget in the focus order."""
        self._focus_by_index(len(self.FOCUS_ORDER) - 1)

    def action_jump_theme(self) -> None:
        """Jump focus to the theme selector."""
        # Don't jump if currently typing in the input field
        if isinstance(self.focused, Input):
            return
        try:
            self.query_one("#settings-theme", Select).focus()
        except Exception as exc:
            logger.debug(f"Failed to focus theme selector: {exc}")

    def action_jump_log_level(self) -> None:
        """Jump focus to the log level selector."""
        # Don't jump if currently typing in the input field
        if isinstance(self.focused, Input):
            return
        try:
            self.query_one("#settings-log-level", Select).focus()
        except Exception as exc:
            logger.debug(f"Failed to focus log level selector: {exc}")

    def action_jump_max_lines(self) -> None:
        """Jump focus to the max lines input."""
        # Don't jump if currently typing in the input field
        if isinstance(self.focused, Input):
            return
        try:
            self.query_one("#settings-max-lines", Input).focus()
        except Exception as exc:
            logger.debug(f"Failed to focus max lines input: {exc}")

    def action_cancel(self) -> None:
        """Cancel and close the settings screen."""
        self.dismiss(None)

    def action_save_settings(self) -> None:
        """Save settings and close the settings screen."""
        self._save_settings()

    def _save_settings(self) -> None:
        """Validate settings and dismiss with the updated settings."""
        theme_select = self.query_one("#settings-theme", Select)
        log_level_select = self.query_one("#settings-log-level", Select)
        max_lines_input = self.query_one("#settings-max-lines", Input)

        theme_value = theme_select.value
        log_level_value = log_level_select.value

        if not isinstance(theme_value, str) or theme_value not in THEME_LABELS:
            logger.warning("Invalid theme selection")
            self.app.notify("Please select a valid theme", severity="warning")
            return

        if not isinstance(log_level_value, str) or log_level_value not in LOG_LEVELS:
            logger.warning("Invalid log level selection")
            self.app.notify("Please select a valid log level", severity="warning")
            return

        max_lines_value = max_lines_input.value.strip()
        try:
            max_lines = int(max_lines_value)
        except ValueError:
            self.app.notify("Max log lines must be a number", severity="warning")
            return

        if max_lines < MIN_LOG_LINES:
            self.app.notify(
                f"Max log lines must be at least {MIN_LOG_LINES}",
                severity="warning",
            )
            return

        updated = Settings(theme=theme_value, log_level=log_level_value, max_log_lines=max_lines)
        self.dismiss(updated)
