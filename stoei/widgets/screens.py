"""Modal screens for job information display."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class JobInputScreen(ModalScreen[str | None]):
    """Modal screen to input a job ID."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (("escape", "cancel", "Cancel"),)

    def compose(self) -> ComposeResult:
        """Create the input dialog layout.

        Yields:
            The widgets that make up the input dialog.
        """
        with Vertical():
            yield Static("🔍  [bold]Job Information Lookup[/bold]", id="input-title")
            yield Static("Enter a SLURM job ID to view detailed information", id="input-hint")
            yield Input(placeholder="Job ID (e.g., 12345 or 12345_0)", id="job-id-input")
            with Container(id="button-row"):
                yield Button("🔎 Show Info", variant="primary", id="submit-btn")
                yield Button("✕ Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        """Focus the input field on mount."""
        self.query_one("#job-id-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input field.

        Args:
            event: The input submission event.
        """
        job_id = event.value.strip()
        if job_id:
            self.dismiss(job_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press.

        Args:
            event: The button press event.
        """
        if event.button.id == "submit-btn":
            job_id = self.query_one("#job-id-input", Input).value.strip()
            if job_id:
                self.dismiss(job_id)
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel and close the modal."""
        self.dismiss(None)


class JobInfoScreen(ModalScreen[None]):
    """Modal screen to display job information."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    )

    def __init__(self, job_id: str, job_info: str, error: str | None = None) -> None:
        """Initialize the job info screen.

        Args:
            job_id: The SLURM job ID being displayed.
            job_info: Formatted job information string.
            error: Optional error message if job info couldn't be retrieved.
        """
        super().__init__()
        self.job_id = job_id
        self.job_info = job_info
        self.error = error

    def compose(self) -> ComposeResult:
        """Create the job info display layout.

        Yields:
            The widgets that make up the job info display.
        """
        with Vertical():
            with Container(id="job-info-header"):
                yield Static("📋  [bold]Job Details[/bold]", id="job-info-title")
                yield Static(f"Job ID: [bold cyan]{self.job_id}[/bold cyan]", id="job-info-subtitle")

            if self.error:
                with Container(id="error-container"):
                    yield Static("⚠️  [bold]Error[/bold]", id="error-icon")
                    yield Static(self.error, id="error-text")
            else:
                with VerticalScroll(id="job-info-content"):
                    yield Static(self.job_info, id="job-info-text")

            with Container(id="job-info-footer"):
                yield Static("Press [bold]Esc[/bold] or [bold]Q[/bold] to close", id="hint-text")
                yield Button("✕ Close", variant="default", id="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press.

        Args:
            event: The button press event.
        """
        if event.button.id == "close-button":
            self.dismiss(None)

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)
