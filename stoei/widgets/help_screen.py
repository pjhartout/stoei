"""Help screen displaying keybindings."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static


class HelpScreen(Screen[None]):
    """Modal screen displaying all keybindings."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("?", "close", "Close"),
    )

    def compose(self) -> ComposeResult:
        """Create the help screen layout.

        Yields:
            The widgets that make up the help screen.
        """
        with Vertical(id="help-container"):
            with Container(id="help-header"):
                yield Static(
                    "❓  [bold]Keyboard Shortcuts[/bold]",
                    id="help-title",
                )

            with VerticalScroll(id="help-content"):
                yield Static(self._get_help_content(), id="help-text")

            with Container(id="help-footer"):
                yield Static(
                    "[bold]?[/bold] or [bold]Esc[/bold] to close",
                    id="help-hint",
                )
                yield Button("✕ Close", variant="default", id="help-close-button")

    def _get_help_content(self) -> str:
        """Generate the help content with keybindings.

        Returns:
            Formatted help text with keybindings.
        """
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
                "Jobs Tab",
                [
                    ("↑/↓", "Navigate jobs list"),
                    ("Enter", "View selected job details"),
                    ("i", "Input job ID to view"),
                    ("c", "Cancel selected job"),
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
                    ("o", "Open stdout log (jobs only)"),
                    ("e", "Open stderr log (jobs only)"),
                    ("↑/↓", "Scroll content"),
                    ("Esc/q", "Close dialog"),
                ],
            ),
            self._format_section(
                "Log Viewer",
                [
                    ("g", "Go to top"),
                    ("G", "Go to bottom"),
                    ("l", "Toggle line numbers"),
                    ("r", "Reload file"),
                    ("e", "Open in $EDITOR"),
                    ("/", "Search (if available)"),
                    ("Esc/q", "Close viewer"),
                ],
            ),
            self._format_section(
                "General",
                [
                    ("r", "Refresh data now"),
                    ("?", "Show this help screen"),
                    ("q", "Quit application"),
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
