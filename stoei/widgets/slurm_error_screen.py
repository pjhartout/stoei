"""Full-screen error screen for SLURM availability issues."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from stoei.logger import get_logger

logger = get_logger(__name__)


class SlurmUnavailableScreen(Screen[None]):
    """Full-screen error screen displayed when SLURM is not available."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
    )

    def compose(self) -> ComposeResult:
        """Create the error screen layout.

        Yields:
            The widgets that make up the error screen.
        """
        with Vertical(id="slurm-error-container"):
            with Container(id="slurm-error-header"):
                yield Static("[bold red]SLURM Controller Not Available[/bold red]", id="error-title")

            with Container(id="slurm-error-content"):
                yield Static(
                    "Stoei requires a SLURM controller to function properly.\n\n"
                    "The SLURM controller is not installed or not accessible on this system.\n\n"
                    "To use Stoei, you need:\n"
                    "  • A SLURM cluster with a controller node\n"
                    "  • SLURM commands (squeue, sacct, scontrol) available in your PATH\n"
                    "  • Network access to the SLURM controller (if running remotely)\n\n"
                    "[bright_black]Note: Stoei cannot function without access to SLURM commands.[/bright_black]",
                    id="error-message",
                )

            with Container(id="slurm-error-footer"):
                yield Button("Quit", variant="default", id="quit-button")

    def on_mount(self) -> None:
        """Focus the quit button on mount."""
        self.query_one("#quit-button", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press.

        Args:
            event: The button press event.
        """
        if event.button.id == "quit-button":
            self.action_quit()

    def action_quit(self) -> None:
        """Quit the application."""
        logger.info("User quit due to SLURM unavailability")
        self.app.exit()
