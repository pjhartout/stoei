"""Settings screen for updating persistent preferences."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Button, Input, Select, Static

from stoei.logger import get_logger
from stoei.settings import (
    KEYBIND_MODES,
    LOG_LEVELS,
    MAX_JOB_HISTORY_DAYS,
    MAX_REFRESH_INTERVAL,
    MIN_JOB_HISTORY_DAYS,
    MIN_LOG_LINES,
    MIN_REFRESH_INTERVAL,
    Settings,
)
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
        ("r", "jump_refresh", "Jump to Refresh Interval"),
        ("h", "jump_history", "Jump to History Days"),
        ("k", "jump_keybind", "Jump to Keybind Mode"),
    )

    # Order of focusable widgets for navigation
    FOCUS_ORDER: ClassVar[tuple[str, ...]] = (
        "#settings-theme",
        "#settings-log-level",
        "#settings-max-lines",
        "#settings-refresh-interval",
        "#settings-job-history-days",
        "#settings-keybind-mode",
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
            yield Static(
                f"Refresh interval (seconds, {MIN_REFRESH_INTERVAL:.0f}-{MAX_REFRESH_INTERVAL:.0f})",
                classes="settings-label",
            )
            yield Input(str(self._settings.refresh_interval), id="settings-refresh-interval")
            yield Static(
                f"Job history days ({MIN_JOB_HISTORY_DAYS}-{MAX_JOB_HISTORY_DAYS})",
                classes="settings-label",
            )
            yield Input(str(self._settings.job_history_days), id="settings-job-history-days")
            yield Static("Keybind mode", classes="settings-label")
            yield Select(
                [(mode.capitalize(), mode) for mode in KEYBIND_MODES],
                value=self._settings.keybind_mode,
                prompt="Select keybind mode",
                allow_blank=False,
                id="settings-keybind-mode",
            )
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

    def action_jump_refresh(self) -> None:
        """Jump focus to the refresh interval input."""
        # Don't jump if currently typing in the input field
        if isinstance(self.focused, Input):
            return
        try:
            self.query_one("#settings-refresh-interval", Input).focus()
        except Exception as exc:
            logger.debug(f"Failed to focus refresh interval input: {exc}")

    def action_jump_history(self) -> None:
        """Jump focus to the job history days input."""
        # Don't jump if currently typing in the input field
        if isinstance(self.focused, Input):
            return
        try:
            self.query_one("#settings-job-history-days", Input).focus()
        except Exception as exc:
            logger.debug(f"Failed to focus job history days input: {exc}")

    def action_cancel(self) -> None:
        """Cancel and close the settings screen."""
        self.dismiss(None)

    def action_save_settings(self) -> None:
        """Save settings and close the settings screen."""
        self._save_settings()

    def _save_settings(self) -> None:
        """Validate settings and dismiss with the updated settings."""
        validated = self._validate_all_settings()
        if validated is not None:
            self.dismiss(validated)

    def _validate_all_settings(self) -> Settings | None:  # noqa: PLR0911
        """Validate all settings fields and return Settings if valid, None otherwise."""
        theme = self._validate_theme()
        if theme is None:
            return None

        log_level = self._validate_log_level()
        if log_level is None:
            return None

        max_lines = self._validate_max_lines()
        if max_lines is None:
            return None

        refresh_interval = self._validate_refresh_interval()
        if refresh_interval is None:
            return None

        job_history_days = self._validate_job_history_days()
        if job_history_days is None:
            return None

        keybind_mode = self._validate_keybind_mode()
        if keybind_mode is None:
            return None

        return Settings(
            theme=theme,
            log_level=log_level,
            max_log_lines=max_lines,
            refresh_interval=refresh_interval,
            job_history_days=job_history_days,
            keybind_mode=keybind_mode,
        )

    def _validate_theme(self) -> str | None:
        """Validate and return theme selection."""
        theme_select = self.query_one("#settings-theme", Select)
        theme_value = theme_select.value
        if not isinstance(theme_value, str) or theme_value not in THEME_LABELS:
            logger.warning("Invalid theme selection")
            self.app.notify("Please select a valid theme", severity="warning")
            return None
        return theme_value

    def _validate_log_level(self) -> str | None:
        """Validate and return log level selection."""
        log_level_select = self.query_one("#settings-log-level", Select)
        log_level_value = log_level_select.value
        if not isinstance(log_level_value, str) or log_level_value not in LOG_LEVELS:
            logger.warning("Invalid log level selection")
            self.app.notify("Please select a valid log level", severity="warning")
            return None
        return log_level_value

    def _validate_max_lines(self) -> int | None:
        """Validate and return max log lines value."""
        max_lines_input = self.query_one("#settings-max-lines", Input)
        max_lines_value = max_lines_input.value.strip()
        try:
            max_lines = int(max_lines_value)
        except ValueError:
            self.app.notify("Max log lines must be a number", severity="warning")
            return None
        if max_lines < MIN_LOG_LINES:
            self.app.notify(f"Max log lines must be at least {MIN_LOG_LINES}", severity="warning")
            return None
        return max_lines

    def _validate_refresh_interval(self) -> float | None:
        """Validate and return refresh interval value."""
        refresh_interval_input = self.query_one("#settings-refresh-interval", Input)
        refresh_interval_value = refresh_interval_input.value.strip()
        try:
            refresh_interval = float(refresh_interval_value)
        except ValueError:
            self.app.notify("Refresh interval must be a number", severity="warning")
            return None
        if refresh_interval < MIN_REFRESH_INTERVAL or refresh_interval > MAX_REFRESH_INTERVAL:
            self.app.notify(
                f"Refresh interval must be between {MIN_REFRESH_INTERVAL:.0f} and {MAX_REFRESH_INTERVAL:.0f} seconds",
                severity="warning",
            )
            return None
        return refresh_interval

    def _validate_job_history_days(self) -> int | None:
        """Validate and return job history days value."""
        job_history_days_input = self.query_one("#settings-job-history-days", Input)
        job_history_days_value = job_history_days_input.value.strip()
        try:
            job_history_days = int(job_history_days_value)
        except ValueError:
            self.app.notify("Job history days must be a number", severity="warning")
            return None
        if job_history_days < MIN_JOB_HISTORY_DAYS or job_history_days > MAX_JOB_HISTORY_DAYS:
            self.app.notify(
                f"Job history days must be between {MIN_JOB_HISTORY_DAYS} and {MAX_JOB_HISTORY_DAYS}",
                severity="warning",
            )
            return None
        return job_history_days

    def _validate_keybind_mode(self) -> str | None:
        """Validate and return keybind mode selection."""
        keybind_select = self.query_one("#settings-keybind-mode", Select)
        keybind_value = keybind_select.value
        if not isinstance(keybind_value, str) or keybind_value not in KEYBIND_MODES:
            logger.warning("Invalid keybind mode selection")
            self.app.notify("Please select a valid keybind mode", severity="warning")
            return None
        return keybind_value

    def action_jump_keybind(self) -> None:
        """Jump focus to the keybind mode selector."""
        # Don't jump if currently typing in the input field
        if isinstance(self.focused, Input):
            return
        try:
            self.query_one("#settings-keybind-mode", Select).focus()
        except Exception as exc:
            logger.debug(f"Failed to focus keybind mode selector: {exc}")
