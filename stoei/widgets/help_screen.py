"""Help screen displaying keybindings."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from stoei.keybindings import Actions, KeybindingConfig, get_default_config

# Key display names for prettier formatting
KEY_DISPLAY_NAMES: dict[str, str] = {
    "question_mark": "?",
    "slash": "/",
    "escape": "Esc",
    "ctrl+q": "Ctrl+Q",
    "ctrl+h": "Ctrl+H",
    "ctrl+r": "Ctrl+R",
    "ctrl+s": "Ctrl+S",
    "ctrl+o": "Ctrl+O",
    "ctrl+g": "Ctrl+G",
    "ctrl+comma": "Ctrl+,",
    "ctrl+i": "Ctrl+I",
    "ctrl+c": "Ctrl+C",
    "ctrl+n": "Ctrl+N",
    "ctrl+p": "Ctrl+P",
    "ctrl+u": "Ctrl+U",
    "ctrl+d": "Ctrl+D",
    "ctrl+v": "Ctrl+V",
    "alt+v": "Alt+V",
    "alt+less": "Alt+<",
    "alt+greater": "Alt+>",
}


def _format_key(key: str | None) -> str:
    """Format a key for display.

    Args:
        key: The key string from keybindings.

    Returns:
        Human-readable key display.
    """
    if key is None:
        return ""
    return KEY_DISPLAY_NAMES.get(key, key)


class HelpScreen(Screen[None]):
    """Modal screen displaying all keybindings."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("?", "close", "Close"),
    )

    def __init__(
        self,
        keybindings: KeybindingConfig | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the help screen.

        Args:
            keybindings: Optional keybinding configuration to display.
            name: The name of the screen.
            id: The ID of the screen.
            classes: CSS classes for the screen.
        """
        super().__init__(name=name, id=id, classes=classes)
        self._keybindings = keybindings or get_default_config()

    def compose(self) -> ComposeResult:
        """Create the help screen layout.

        Yields:
            The widgets that make up the help screen.
        """
        mode_display = self._keybindings.preset.upper()
        with Vertical(id="help-container"):
            with Container(id="help-header"):
                yield Static(
                    f"[bold]Keyboard Shortcuts[/bold] [dim]({mode_display} mode)[/dim]",
                    id="help-title",
                )

            with VerticalScroll(id="help-content"):
                yield Static(self._get_help_content(), id="help-text")

            with Container(id="help-footer"):
                yield Static(
                    "[bold]?[/bold] or [bold]Esc[/bold] to close",
                    id="help-hint",
                )
                yield Button("Close", variant="default", id="help-close-button")

    def _get_help_content(self) -> str:
        """Generate the help content with keybindings.

        Returns:
            Formatted help text with keybindings.
        """
        kb = self._keybindings

        sections = [
            self._format_section(
                "Navigation",
                [
                    ("1", "Switch to Jobs tab"),
                    ("2", "Switch to Nodes tab"),
                    ("3", "Switch to Users tab"),
                    ("4", "Switch to Logs tab"),
                    ("←/→", "Previous/Next tab"),
                    ("Tab", "Next tab"),
                    ("Shift+Tab", "Previous tab"),
                ],
            ),
            self._format_section(
                "Table Filtering & Sorting",
                [
                    (_format_key(kb.get_key(Actions.FILTER_SHOW)), "Show filter bar"),
                    (_format_key(kb.get_key(Actions.FILTER_HIDE)), "Hide filter / Clear"),
                    (_format_key(kb.get_key(Actions.SORT_CYCLE)), "Cycle sort order"),
                    ("", "Filter syntax: 'state:RUNNING'"),
                    ("", "or general search terms"),
                ],
            ),
            self._format_section(
                "Column Width",
                [
                    (_format_key(kb.get_key(Actions.COLUMN_SELECT_NEXT)), "Select next column"),
                    (_format_key(kb.get_key(Actions.COLUMN_SELECT_PREV)), "Select previous column"),
                    (_format_key(kb.get_key(Actions.COLUMN_WIDTH_INCREASE)), "Increase column width"),
                    (_format_key(kb.get_key(Actions.COLUMN_WIDTH_DECREASE)), "Decrease column width"),
                    (_format_key(kb.get_key(Actions.COLUMN_WIDTH_RESET)), "Reset column to default"),
                ],
            ),
            self._format_section(
                "Jobs Tab",
                [
                    ("↑/↓", "Navigate jobs list"),
                    ("Enter", "View selected job details"),
                    (_format_key(kb.get_key(Actions.JOB_INFO)), "Input job ID to view"),
                    (_format_key(kb.get_key(Actions.JOB_CANCEL)), "Cancel selected job"),
                ],
            ),
            self._format_section(
                "Nodes Tab",
                [
                    ("↑/↓", "Navigate nodes list"),
                    ("Enter", "View selected node details"),
                ],
            ),
            self._format_section(
                "Job/Node Details",
                [
                    (_format_key(kb.get_key(Actions.OPEN_STDOUT)), "Open stdout log (jobs only)"),
                    (_format_key(kb.get_key(Actions.OPEN_STDERR)), "Open stderr log (jobs only)"),
                    ("↑/↓", "Scroll content"),
                    ("Esc/q", "Close dialog"),
                ],
            ),
            self._format_section(
                "Log Viewer",
                [
                    (_format_key(kb.get_key(Actions.LOG_TOP)), "Go to top"),
                    (_format_key(kb.get_key(Actions.LOG_BOTTOM)), "Go to bottom"),
                    (_format_key(kb.get_key(Actions.LOG_LINE_NUMBERS)), "Toggle line numbers"),
                    (_format_key(kb.get_key(Actions.LOG_RELOAD)), "Reload file"),
                    (_format_key(kb.get_key(Actions.LOG_EDITOR)), "Open in $EDITOR"),
                    (_format_key(kb.get_key(Actions.LOG_SEARCH)), "Search"),
                    ("Esc/q", "Close viewer"),
                ],
            ),
            self._format_section(
                "Settings Screen",
                [
                    ("↑/↓", "Navigate between fields"),
                    ("Tab", "Next field"),
                    ("Shift+Tab", "Previous field"),
                    ("←/→", "Cycle dropdown options"),
                    ("Enter", "Confirm selection / Next field"),
                    ("Home/End", "First / Last field"),
                    ("t/l/m/k", "Jump to Theme/Level/Max/Keybind"),
                    ("Ctrl+S", "Save settings"),
                    ("Esc/q", "Cancel and close"),
                ],
            ),
            self._format_section(
                "General",
                [
                    (_format_key(kb.get_key(Actions.REFRESH)), "Refresh data now"),
                    (_format_key(kb.get_key(Actions.SETTINGS)), "Open settings"),
                    (_format_key(kb.get_key(Actions.HELP)), "Show this help screen"),
                    (_format_key(kb.get_key(Actions.QUIT)), "Quit application"),
                ],
            ),
        ]

        return "\n\n".join(sections)

    def _format_section(self, title: str, bindings: list[tuple[str, str]]) -> str:
        """Format a section of keybindings.

        Args:
            title: Section title.
            bindings: List of (key, description) tuples.

        Returns:
            Formatted section string.
        """
        lines = [f"[bold cyan]{title}[/bold cyan]", "[bright_black]" + "─" * 40 + "[/bright_black]"]
        for key, description in bindings:
            # Pad key to align descriptions
            key_display = f"[bold]{key:>12}[/bold]"
            lines.append(f"  {key_display}  {description}")
        return "\n".join(lines)

    def on_mount(self) -> None:
        """Focus the scroll area for keyboard navigation."""
        try:
            scroll = self.query_one("#help-content", VerticalScroll)
            scroll.focus()
        except Exception:
            self.query_one("#help-close-button", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press.

        Args:
            event: The button press event.
        """
        if event.button.id == "help-close-button":
            self.dismiss(None)

    def action_close(self) -> None:
        """Close the help screen."""
        self.dismiss(None)
