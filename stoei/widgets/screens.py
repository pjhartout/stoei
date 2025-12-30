"""Full-screen screens for job information display."""

from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from stoei.editor import open_in_editor
from stoei.logger import get_logger

logger = get_logger(__name__)


class LogViewerScreen(Screen[None]):
    """Modal screen to display log file contents."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("e", "open_in_editor", "Open in $EDITOR"),
        ("g", "scroll_top", "Go to top"),
        ("G", "scroll_bottom", "Go to bottom"),
        ("r", "reload", "Reload file"),
    )

    # Maximum file size to load (in bytes) - larger files are truncated from the start
    MAX_FILE_SIZE: ClassVar[int] = 512 * 1024  # 512 KB

    def __init__(self, filepath: str, log_type: str) -> None:
        """Initialize the log viewer screen.

        Args:
            filepath: Path to the log file.
            log_type: Type of log (e.g., "stdout" or "stderr").
        """
        super().__init__()
        self.filepath = filepath
        self.log_type = log_type
        self.file_contents: str = ""
        self.load_error: str | None = None
        self.truncated: bool = False

    def compose(self) -> ComposeResult:
        """Create the log viewer layout.

        Yields:
            The widgets that make up the log viewer.
        """
        # Load file contents
        self._load_file()

        with Vertical(id="log-viewer-container"):
            with Container(id="log-viewer-header"):
                yield Static(
                    f"📄  [bold]{self.log_type.upper()} Log[/bold]",
                    id="log-viewer-title",
                )
                yield Static(
                    self.filepath,
                    id="log-viewer-path",
                )

            if self.load_error:
                with Container(id="log-error-container"):
                    yield Static(f"⚠️  {self.load_error}", id="log-error-text")
            else:
                with VerticalScroll(id="log-content-scroll"):
                    yield Static(self.file_contents, id="log-content-text")

            with Container(id="log-viewer-footer"):
                yield Static(
                    "[bold]g/G[/bold] Top/Bottom  [bold]r[/bold] Reload  [bold]e[/bold] Editor  [bold]Esc[/bold] Close",
                    id="log-hint-text",
                )
                yield Button("📝 Open in $EDITOR", variant="primary", id="editor-button")
                yield Button("✕ Close", variant="default", id="log-close-button")

    def _load_file(self) -> None:
        """Load the file contents.

        For large files, only the last MAX_FILE_SIZE bytes are loaded
        to maintain UI responsiveness.
        """
        path = Path(self.filepath)
        self.truncated = False

        if not path.exists():
            self.load_error = f"File does not exist: {self.filepath}"
            logger.warning(self.load_error)
            return

        if not path.is_file():
            self.load_error = f"Not a regular file: {self.filepath}"
            logger.warning(self.load_error)
            return

        try:
            file_size = path.stat().st_size

            if file_size == 0:
                self.file_contents = "[dim](empty file)[/dim]"
                logger.info(f"Loaded log file: {self.filepath}")
                return

            if file_size <= self.MAX_FILE_SIZE:
                # Small file - read entirely
                self.file_contents = path.read_text()
            else:
                # Large file - read only the tail for performance
                self.truncated = True
                with path.open("rb") as f:
                    # Seek to position near end, leaving room for MAX_FILE_SIZE bytes
                    f.seek(file_size - self.MAX_FILE_SIZE)
                    # Read from that position to end
                    tail_bytes = f.read()

                # Decode and skip the first partial line (may be cut off)
                tail_text = tail_bytes.decode("utf-8", errors="replace")
                first_newline = tail_text.find("\n")
                if first_newline != -1:
                    tail_text = tail_text[first_newline + 1 :]

                truncated_size_mb = file_size / (1024 * 1024)
                self.file_contents = (
                    f"[bold yellow]⚠ File truncated (showing last ~{self.MAX_FILE_SIZE // 1024} KB "
                    f"of {truncated_size_mb:.1f} MB)[/bold yellow]\n"
                    f"[dim]{'─' * 60}[/dim]\n\n"
                    f"{tail_text}"
                )
                logger.info(
                    f"Loaded log file (truncated): {self.filepath} "
                    f"({file_size} bytes, showing last {self.MAX_FILE_SIZE} bytes)"
                )
                return

            logger.info(f"Loaded log file: {self.filepath}")
        except PermissionError:
            self.load_error = f"Permission denied: {self.filepath}"
            logger.warning(self.load_error)
        except OSError as exc:
            self.load_error = f"Error reading file: {exc}"
            logger.warning(self.load_error)

    def on_mount(self) -> None:
        """Focus the scroll area and scroll to bottom for keyboard navigation."""
        try:
            scroll = self.query_one("#log-content-scroll", VerticalScroll)
            scroll.focus()
            # Scroll to bottom to show latest log entries
            self.call_after_refresh(self._scroll_to_bottom)
        except Exception:
            # If no scroll area (error case), focus the close button
            self.query_one("#log-close-button", Button).focus()

    def _scroll_to_bottom(self) -> None:
        """Scroll the content to the bottom."""
        try:
            scroll = self.query_one("#log-content-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)
        except Exception:
            # Scroll area may not exist in error state
            logger.debug("Could not scroll to bottom - scroll area not found")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press.

        Args:
            event: The button press event.
        """
        if event.button.id == "log-close-button":
            self.dismiss(None)
        elif event.button.id == "editor-button":
            self._open_in_editor()

    def action_open_in_editor(self) -> None:
        """Open the log file in $EDITOR."""
        self._open_in_editor()

    def _open_in_editor(self) -> None:
        """Open the file in the user's editor."""
        # Don't allow opening if there was a load error
        if self.load_error:
            self.app.notify(f"Cannot open file: {self.load_error}", severity="error")
            return

        # Validate filepath before attempting to open
        if not self.filepath or not self.filepath.strip():
            self.app.notify("No file path available", severity="error")
            return

        logger.info(f"Opening {self.filepath} in external editor")
        with self.app.suspend():
            success, message = open_in_editor(self.filepath)

        if success:
            self.app.notify("Opened in editor")
        else:
            self.app.notify(f"Failed: {message}", severity="error")

    def action_scroll_top(self) -> None:
        """Scroll to the top of the log content."""
        try:
            scroll = self.query_one("#log-content-scroll", VerticalScroll)
            scroll.scroll_home(animate=False)
        except Exception:
            # Scroll area may not exist in error state
            logger.debug("Could not scroll to top - scroll area not found")

    def action_scroll_bottom(self) -> None:
        """Scroll to the bottom of the log content."""
        self._scroll_to_bottom()

    def action_reload(self) -> None:
        """Reload the file contents."""
        self._load_file()
        try:
            content_widget = self.query_one("#log-content-text", Static)
            if self.load_error:
                content_widget.update(f"⚠️  {self.load_error}")
            else:
                content_widget.update(self.file_contents)
            self.app.notify("File reloaded")
            logger.info(f"Reloaded log file: {self.filepath}")
        except Exception as exc:
            logger.warning(f"Failed to update content after reload: {exc}")

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)


class JobInputScreen(Screen[str | None]):
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


class JobInfoScreen(Screen[None]):
    """Modal screen to display job information."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("o", "open_stdout", "Open StdOut"),
        ("e", "open_stderr", "Open StdErr"),
        ("left", "focus_previous", "Previous"),
        ("right", "focus_next", "Next"),
        ("up", "focus_content", "Content"),
        ("down", "focus_buttons", "Buttons"),
    )

    def __init__(
        self,
        job_id: str,
        job_info: str,
        error: str | None = None,
        stdout_path: str | None = None,
        stderr_path: str | None = None,
    ) -> None:
        """Initialize the job info screen.

        Args:
            job_id: The SLURM job ID being displayed.
            job_info: Formatted job information string.
            error: Optional error message if job info couldn't be retrieved.
            stdout_path: Optional path to the job's stdout log file.
            stderr_path: Optional path to the job's stderr log file.
        """
        super().__init__()
        self.job_id = job_id
        self.job_info = job_info
        self.error = error
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path

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
                yield Static(
                    "[bold]↑↓[/bold] Nav | [bold]←→[/bold] Buttons | [bold]O/E[/bold] Logs | [bold]Esc[/bold] Close",
                    id="hint-text",
                )
                with Container(id="log-buttons"):
                    yield Button(
                        "📄 Open StdOut",
                        variant="primary",
                        id="stdout-button",
                        disabled=not self.stdout_path,
                    )
                    yield Button(
                        "📄 Open StdErr",
                        variant="warning",
                        id="stderr-button",
                        disabled=not self.stderr_path,
                    )
                yield Button("✕ Close", variant="default", id="close-button")

    def on_mount(self) -> None:
        """Focus the content area on mount for scrolling."""
        try:
            content = self.query_one("#job-info-content", VerticalScroll)
            content.focus()
        except Exception:
            # If no content (error case), focus the first button
            self._focus_first_button()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press.

        Args:
            event: The button press event.
        """
        if event.button.id == "close-button":
            self.dismiss(None)
        elif event.button.id == "stdout-button":
            self._open_log(self.stdout_path, "stdout")
        elif event.button.id == "stderr-button":
            self._open_log(self.stderr_path, "stderr")

    def _get_button_order(self) -> list[Button]:
        """Get buttons in navigation order.

        Returns:
            List of buttons in left-to-right order.
        """
        return [
            self.query_one("#stdout-button", Button),
            self.query_one("#stderr-button", Button),
            self.query_one("#close-button", Button),
        ]

    def _get_focused_button_index(self, buttons: list[Button]) -> int | None:
        """Get the index of the currently focused button.

        Args:
            buttons: List of buttons to search.

        Returns:
            Index of focused button, or None if no button is focused.
        """
        focused = self.focused
        for idx, btn in enumerate(buttons):
            if btn is focused:
                return idx
        return None

    def _focus_first_button(self) -> None:
        """Focus the first enabled button."""
        buttons = self._get_button_order()
        for btn in buttons:
            if not btn.disabled:
                btn.focus()
                return
        # Fallback to close button
        self.query_one("#close-button", Button).focus()

    def _is_button_focused(self) -> bool:
        """Check if any button is currently focused."""
        buttons = self._get_button_order()
        return self._get_focused_button_index(buttons) is not None

    def action_focus_content(self) -> None:
        """Focus the content area (up arrow)."""
        try:
            content = self.query_one("#job-info-content", VerticalScroll)
            content.focus()
        except Exception:
            # No content area available (error state), ignore
            logger.debug("No content area to focus")

    def action_focus_buttons(self) -> None:
        """Focus the button area (down arrow)."""
        self._focus_first_button()

    def action_focus_next(self) -> None:
        """Focus the next element (right arrow)."""
        if not self._is_button_focused():
            # If not on buttons, go to buttons
            self._focus_first_button()
            return

        buttons = self._get_button_order()
        current_idx = self._get_focused_button_index(buttons)

        if current_idx is None:
            self._focus_first_button()
            return

        # Find next enabled button
        for i in range(1, len(buttons)):
            next_idx = (current_idx + i) % len(buttons)
            if not buttons[next_idx].disabled:
                buttons[next_idx].focus()
                return

    def action_focus_previous(self) -> None:
        """Focus the previous element (left arrow)."""
        if not self._is_button_focused():
            # If not on buttons, go to buttons (last one)
            buttons = self._get_button_order()
            for btn in reversed(buttons):
                if not btn.disabled:
                    btn.focus()
                    return
            return

        buttons = self._get_button_order()
        current_idx = self._get_focused_button_index(buttons)

        if current_idx is None:
            self._focus_first_button()
            return

        # Find previous enabled button
        for i in range(1, len(buttons)):
            prev_idx = (current_idx - i) % len(buttons)
            if not buttons[prev_idx].disabled:
                buttons[prev_idx].focus()
                return

    def _open_log(self, path: str | None, log_type: str) -> None:
        """Open the log viewer screen for a log file.

        Args:
            path: Path to the log file.
            log_type: Type of log (stdout or stderr).
        """
        # Check if path is None, empty, or whitespace-only
        if not path or (isinstance(path, str) and not path.strip()):
            self.app.notify(f"No {log_type} path available", severity="warning")
            return

        logger.info(f"Viewing {log_type} log: {path}")
        self.app.push_screen(LogViewerScreen(path, log_type))

    def action_open_stdout(self) -> None:
        """Open the stdout log file."""
        self._open_log(self.stdout_path, "stdout")

    def action_open_stderr(self) -> None:
        """Open the stderr log file."""
        self._open_log(self.stderr_path, "stderr")

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)


class CancelConfirmScreen(Screen[bool]):
    """Modal screen to confirm job cancellation."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
    )

    def __init__(self, job_id: str, job_name: str | None = None) -> None:
        """Initialize the cancel confirmation screen.

        Args:
            job_id: The SLURM job ID to cancel.
            job_name: Optional job name for display.
        """
        super().__init__()
        self.job_id = job_id
        self.job_name = job_name

    def compose(self) -> ComposeResult:
        """Create the confirmation dialog layout."""
        with Vertical(id="cancel-confirm-container"):
            yield Static("⚠️  [bold]Cancel Job?[/bold]", id="cancel-title")
            job_display = f"Job ID: [bold cyan]{self.job_id}[/bold cyan]"
            if self.job_name:
                job_display += f"\nJob Name: [bold]{self.job_name}[/bold]"
            yield Static(job_display, id="cancel-job-info")
            yield Static(
                "[dim]This action cannot be undone.[/dim]",
                id="cancel-warning",
            )
            with Container(id="cancel-button-row"):
                yield Button("🗑️ Cancel Job", variant="error", id="confirm-cancel-btn")
                yield Button("✕ Keep Running", variant="default", id="abort-cancel-btn")

    def on_mount(self) -> None:
        """Focus the abort button by default (safer option)."""
        self.query_one("#abort-cancel-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "confirm-cancel-btn":
            self.dismiss(True)
        elif event.button.id == "abort-cancel-btn":
            self.dismiss(False)

    def action_cancel(self) -> None:
        """Abort the cancellation (Escape key)."""
        self.dismiss(False)

    def action_confirm(self) -> None:
        """Confirm the cancellation (Enter key)."""
        self.dismiss(True)
