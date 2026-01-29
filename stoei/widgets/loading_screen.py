"""Loading screen widget with progress bar and step logging."""

import time
from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Label, ProgressBar, Static

from stoei.colors import get_theme_colors
from stoei.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LoadingStep:
    """A single loading step."""

    name: str
    description: str
    weight: float = 1.0  # Relative weight for progress calculation


class LoadingScreen(Screen[None]):
    """Loading screen with progress bar, animation, and step logging.

    Shows:
    - Animated spinner to confirm app isn't stalled
    - Progress bar showing overall loading progress
    - Current step description
    - Log of completed steps with timing
    """

    DEFAULT_CSS: ClassVar[str] = """
    LoadingScreen {
        align: center middle;
        background: $background;
    }

    #loading-container {
        width: 80%;
        max-width: 80;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: heavy $accent;
        padding: 2;
    }

    #loading-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        color: $primary;
    }

    #spinner-container {
        height: 3;
        align: center middle;
        margin-bottom: 1;
    }

    #spinner {
        text-align: center;
        text-style: bold;
        color: $accent;
    }

    #current-step {
        text-align: center;
        margin-bottom: 1;
        color: $foreground;
    }

    #progress-bar {
        margin-bottom: 1;
        color: $success;
        background: $panel;
    }

    #progress-label {
        text-align: center;
        margin-bottom: 1;
        color: $text-muted;
    }

    #step-log-container {
        height: 12;
        border: round $border;
        padding: 0 1;
        margin-top: 1;
        background: $background;
    }

    #step-log-title {
        text-style: bold;
        margin-bottom: 0;
        color: $primary;
    }

    #step-log {
        height: 100%;
        scrollbar-gutter: stable;
        color: $foreground;
    }

    .step-entry {
        margin: 0;
    }

    .step-completed {
        color: $success;
    }

    .step-in-progress {
        color: $warning;
    }

    .step-error {
        color: $error;
    }
    """

    SPINNER_FRAMES: ClassVar[tuple[str, ...]] = (
        "⠋",
        "⠙",
        "⠹",
        "⠸",
        "⠼",
        "⠴",
        "⠦",
        "⠧",
        "⠇",
        "⠏",
    )

    def __init__(
        self,
        steps: list[LoadingStep],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the loading screen.

        Args:
            steps: List of loading steps to display.
            name: The name of the screen.
            id: The ID of the screen.
            classes: CSS classes for the screen.
        """
        super().__init__(name=name, id=id, classes=classes)
        self.steps = steps
        self.total_weight = sum(step.weight for step in steps)
        self._current_step_index = 0
        self._completed_weight = 0.0
        self._spinner_frame = 0
        self._spinner_timer: Timer | None = None
        self._step_start_times: dict[int, float] = {}
        self._step_log_entries: list[str] = []

    def compose(self) -> ComposeResult:
        """Create the loading screen layout."""
        # Use plain text in compose - CSS will style it
        with Container(id="loading-container"):
            yield Label("[bold]STOEI Loading[/bold]", id="loading-title")

            with Container(id="spinner-container"):
                yield Static(self.SPINNER_FRAMES[0], id="spinner")

            yield Label("Initializing...", id="current-step")
            yield ProgressBar(id="progress-bar", total=100, show_eta=False)
            yield Label("0%", id="progress-label")

            yield Label("[bold]Loading Steps:[/bold]", id="step-log-title")
            with VerticalScroll(id="step-log-container"):
                yield Static("", id="step-log")

    def on_mount(self) -> None:
        """Start the spinner animation."""
        self._start_time = time.time()
        self._spinner_timer = self.set_interval(0.1, self._animate_spinner)
        logger.info("Loading screen mounted")

    def _animate_spinner(self) -> None:
        """Animate the spinner."""
        self._spinner_frame = (self._spinner_frame + 1) % len(self.SPINNER_FRAMES)
        try:
            colors = get_theme_colors(self.app)
            spinner = self.query_one("#spinner", Static)
            spinner.update(
                f"[bold {colors.accent}]{self.SPINNER_FRAMES[self._spinner_frame]}[/bold {colors.accent}] Loading..."
            )
        except Exception as exc:
            logger.debug(f"Spinner update failed: {exc}")

    def start_step(self, step_index: int) -> None:
        """Mark a step as starting.

        Args:
            step_index: Index of the step starting.
        """
        if step_index >= len(self.steps):
            return

        self._current_step_index = step_index
        self._step_start_times[step_index] = time.time()

        step = self.steps[step_index]
        logger.info(f"Loading step {step_index + 1}/{len(self.steps)}: {step.name}")

        # Update UI
        try:
            colors = get_theme_colors(self.app)
            current_step_label = self.query_one("#current-step", Label)
            current_step_label.update(f"[{colors.warning}]●[/{colors.warning}] {step.description}")

            # Add to log
            self._add_log_entry(f"[{colors.warning}]▶[/{colors.warning}] {step.name}...")
        except Exception as exc:
            logger.debug(f"Failed to update loading UI: {exc}")

    def complete_step(self, step_index: int, message: str | None = None) -> None:
        """Mark a step as completed.

        Args:
            step_index: Index of the completed step.
            message: Optional completion message with details.
        """
        if step_index >= len(self.steps):
            return

        step = self.steps[step_index]
        elapsed = 0.0
        if step_index in self._step_start_times:
            elapsed = time.time() - self._step_start_times[step_index]

        self._completed_weight += step.weight
        progress_pct = (self._completed_weight / self.total_weight) * 100

        detail = f" ({message})" if message else ""
        logger.info(f"Completed step {step_index + 1}: {step.name}{detail} in {elapsed:.2f}s")

        # Update UI
        try:
            colors = get_theme_colors(self.app)
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_bar.update(progress=progress_pct)

            progress_label = self.query_one("#progress-label", Label)
            progress_label.update(f"{progress_pct:.0f}%")

            # Update log with completion
            time_str = f"[{colors.text_muted}]{elapsed:.1f}s[/{colors.text_muted}]"
            detail_str = f" - [{colors.text_muted}]{message}[/{colors.text_muted}]" if message else ""
            self._add_log_entry(f"[{colors.success}]✓[/{colors.success}] {step.name}{detail_str} {time_str}")
        except Exception as exc:
            logger.debug(f"Failed to update loading UI: {exc}")

    def fail_step(self, step_index: int, error: str) -> None:
        """Mark a step as failed.

        Args:
            step_index: Index of the failed step.
            error: Error message.
        """
        if step_index >= len(self.steps):
            return

        step = self.steps[step_index]
        logger.error(f"Failed step {step_index + 1}: {step.name} - {error}")

        # Update log with failure
        try:
            colors = get_theme_colors(self.app)
            self._add_log_entry(
                f"[{colors.error}]✗[/{colors.error}] {step.name}: [{colors.error}]{error}[/{colors.error}]"
            )
        except Exception as exc:
            logger.debug(f"Failed to update loading UI: {exc}")

    def skip_step(self, step_index: int, reason: str) -> None:
        """Mark a step as skipped.

        Args:
            step_index: Index of the skipped step.
            reason: Reason for skipping (e.g., "Disabled - enable in Settings (s)").
        """
        if step_index >= len(self.steps):
            return

        step = self.steps[step_index]

        # Skipped steps still count toward progress
        self._completed_weight += step.weight
        progress_pct = (self._completed_weight / self.total_weight) * 100

        logger.info(f"Skipped step {step_index + 1}: {step.name} - {reason}")

        # Update UI
        try:
            colors = get_theme_colors(self.app)
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_bar.update(progress=progress_pct)

            progress_label = self.query_one("#progress-label", Label)
            progress_label.update(f"{progress_pct:.0f}%")

            # Update log with skip indicator
            self._add_log_entry(
                f"[{colors.text_muted}]⊘[/{colors.text_muted}] {step.name}: "
                f"[{colors.text_muted}]{reason}[/{colors.text_muted}]"
            )
        except Exception as exc:
            logger.debug(f"Failed to update loading UI: {exc}")

    def _add_log_entry(self, entry: str) -> None:
        """Add an entry to the step log.

        Args:
            entry: Log entry with Rich markup.
        """
        self._step_log_entries.append(entry)

        try:
            step_log = self.query_one("#step-log", Static)
            step_log.update("\n".join(self._step_log_entries))

            # Scroll to bottom
            scroll_container = self.query_one("#step-log-container", VerticalScroll)
            scroll_container.scroll_end(animate=False)
        except Exception as exc:
            logger.debug(f"Failed to update step log: {exc}")

    def set_complete(self) -> None:
        """Mark loading as fully complete."""
        total_time = time.time() - self._start_time
        logger.info(f"Loading complete in {total_time:.2f}s")

        try:
            colors = get_theme_colors(self.app)
            current_step_label = self.query_one("#current-step", Label)
            current_step_label.update(f"[{colors.success}]✓[/{colors.success}] Loading complete!")

            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_bar.update(progress=100)

            progress_label = self.query_one("#progress-label", Label)
            progress_label.update(f"[{colors.success}]100%[/{colors.success}] - {total_time:.1f}s total")

            spinner = self.query_one("#spinner", Static)
            spinner.update(f"[bold {colors.success}]✓[/bold {colors.success}] Ready!")
        except Exception as exc:
            logger.debug(f"Failed to update loading UI: {exc}")

        # Stop spinner
        if self._spinner_timer:
            self._spinner_timer.stop()
