"""Full-screen screens for job information display."""

import contextlib
import re
from pathlib import Path
from typing import ClassVar

from rich.markup import escape
from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Static

from stoei.editor import open_in_editor
from stoei.logger import get_logger

logger = get_logger(__name__)


class LogViewerScreen(Screen[None]):
    """Modal screen to display log file contents."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "close_or_cancel_search", "Close"),
        ("q", "close", "Close"),
        ("e", "open_in_editor", "Open in $EDITOR"),
        ("g", "scroll_top", "Go to top"),
        ("G", "scroll_bottom", "Go to bottom"),
        ("r", "reload", "Reload file"),
        ("l", "toggle_line_numbers", "Toggle line numbers"),
        ("slash", "start_search", "Search"),
        ("n", "next_match", "Next match"),
        ("N", "previous_match", "Previous match"),
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
        self._raw_contents: str = ""  # Store raw content without line numbers
        self.load_error: str | None = None
        self.truncated: bool = False
        self._start_line: int = 1  # Starting line number (for truncated files)
        self._show_line_numbers: bool = True  # Line numbers shown by default
        # Search state
        self._search_term: str = ""
        self._search_active: bool = False
        self._match_lines: list[int] = []  # Line numbers with matches
        self._current_match_index: int = -1

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
                    # Use markup=True for line number styling, but escape content properly
                    yield Static(self.file_contents, id="log-content-text", markup=True)

            # Search bar (hidden by default)
            with Container(id="log-search-container", classes="hidden"):
                yield Input(placeholder="Search...", id="log-search-input")
                yield Static("", id="log-search-status")

            with Container(id="log-viewer-footer"):
                hint = "[b]g/G[/b] ↕ [b]/[/b] Search [b]n/N[/b] Next/Prev [b]l[/b] Line# [b]Esc[/b]"
                yield Static(hint, id="log-hint-text")
                yield Button("📝 Open in $EDITOR", variant="primary", id="editor-button")
                yield Button("✕ Close", variant="default", id="log-close-button")

    def _format_with_line_numbers(self, content: str, start_line: int = 1) -> str:
        """Add line numbers to content.

        Args:
            content: The file content to format (should be escaped for markup safety).
            start_line: Starting line number (useful for truncated files).

        Returns:
            Content with line numbers prepended and markup for styling.
        """
        if not content:
            return content

        lines = content.split("\n")
        total_lines = start_line + len(lines) - 1
        width = len(str(total_lines))

        numbered_lines = []
        for i, line in enumerate(lines):
            line_num = start_line + i
            # Defensive escape: ensure line content is safe for Rich markup
            # escape() is idempotent, so already-escaped content is unchanged
            safe_line = escape(line)
            numbered_lines.append(f"[dim]{line_num:>{width}}[/dim] │ {safe_line}")

        return "\n".join(numbered_lines)

    def _get_display_content(self) -> str:
        """Get the content to display, with or without line numbers.

        Returns:
            The formatted content for display.
        """
        if not self._raw_contents:
            return self._raw_contents

        # Escape content to prevent markup interpretation of log content
        escaped_content = escape(self._raw_contents)

        if self._show_line_numbers:
            return self._format_with_line_numbers(escaped_content, self._start_line)
        return escaped_content

    def _count_total_lines(self, path: Path) -> int:
        """Count total lines in a file efficiently.

        Args:
            path: Path to the file.

        Returns:
            Total number of lines in the file.
        """
        total_line_count = 0
        with path.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                total_line_count += chunk.count(b"\n")
        return total_line_count

    def _load_truncated_file(self, path: Path, file_size: int) -> None:
        """Load a truncated version of a large file.

        Args:
            path: Path to the file.
            file_size: Total size of the file in bytes.
        """
        self.truncated = True
        total_line_count = self._count_total_lines(path)

        with path.open("rb") as f:
            f.seek(file_size - self.MAX_FILE_SIZE)
            tail_bytes = f.read()

        tail_text = tail_bytes.decode("utf-8", errors="replace")
        first_newline = tail_text.find("\n")
        skipped_partial_lines = 0
        if first_newline != -1:
            tail_text = tail_text[first_newline + 1 :]
            skipped_partial_lines = 1

        tail_line_count = tail_text.count("\n") + 1
        self._start_line = max(1, total_line_count - tail_line_count + 2 - skipped_partial_lines)

        truncated_size_mb = file_size / (1024 * 1024)
        truncate_header = (
            f"[bold yellow]⚠ File truncated (showing last ~{self.MAX_FILE_SIZE // 1024} KB "
            f"of {truncated_size_mb:.1f} MB)[/bold yellow]\n"
            f"[bright_black]{'─' * 60}[/bright_black]\n\n"
        )

        self._raw_contents = tail_text
        escaped_content = escape(tail_text)
        if self._show_line_numbers:
            self.file_contents = truncate_header + self._format_with_line_numbers(escaped_content, self._start_line)
        else:
            self.file_contents = truncate_header + escaped_content

        logger.info(
            f"Loaded log file (truncated): {self.filepath} "
            f"({file_size} bytes, showing last {self.MAX_FILE_SIZE} bytes, "
            f"starting at line {self._start_line})"
        )

    def _load_file(self) -> None:
        """Load the file contents.

        For large files, only the last MAX_FILE_SIZE bytes are loaded
        to maintain UI responsiveness.
        """
        path = Path(self.filepath)
        self.truncated = False
        self._start_line = 1

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
                self._raw_contents = ""
                self.file_contents = "[bright_black](empty file)[/bright_black]"
                logger.info(f"Loaded log file: {self.filepath}")
                return

            if file_size <= self.MAX_FILE_SIZE:
                self._raw_contents = path.read_text()
                self._start_line = 1
                self.file_contents = self._get_display_content()
            else:
                self._load_truncated_file(path, file_size)
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
        try:
            with self.app.suspend():
                success, message = open_in_editor(self.filepath)

            if success:
                self.app.notify("Opened in editor")
            else:
                self.app.notify(f"Failed: {message}", severity="error")
        except SuspendNotSupported:
            error_msg = "Cannot suspend app in this environment (terminal not available)"
            logger.warning(error_msg)
            self.app.notify(error_msg, severity="error")

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
                # Update with markup enabled for line numbers styling
                content_widget.update(self.file_contents)
            self.app.notify("File reloaded")
            logger.info(f"Reloaded log file: {self.filepath}")
        except Exception as exc:
            logger.warning(f"Failed to update content after reload: {exc}")

    def action_toggle_line_numbers(self) -> None:
        """Toggle line number display."""
        self._show_line_numbers = not self._show_line_numbers
        try:
            content_widget = self.query_one("#log-content-text", Static)
            if self.load_error:
                return

            # Escape content to prevent markup interpretation
            escaped_content = escape(self._raw_contents)

            # Regenerate content with/without line numbers
            if self.truncated:
                truncated_size_mb = Path(self.filepath).stat().st_size / (1024 * 1024)
                truncate_header = (
                    f"[bold yellow]⚠ File truncated (showing last ~{self.MAX_FILE_SIZE // 1024} KB "
                    f"of {truncated_size_mb:.1f} MB)[/bold yellow]\n"
                    f"[bright_black]{'─' * 60}[/bright_black]\n\n"
                )
                if self._show_line_numbers:
                    self.file_contents = truncate_header + self._format_with_line_numbers(
                        escaped_content, self._start_line
                    )
                else:
                    self.file_contents = truncate_header + escaped_content
            else:
                self.file_contents = self._get_display_content()

            content_widget.update(self.file_contents)
            state = "on" if self._show_line_numbers else "off"
            self.app.notify(f"Line numbers {state}")
            logger.debug(f"Toggled line numbers: {state}")
        except Exception as exc:
            logger.warning(f"Failed to toggle line numbers: {exc}")

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)

    def action_close_or_cancel_search(self) -> None:
        """Close the search bar if active, otherwise close the modal."""
        if self._search_active:
            self._hide_search()
        else:
            self.dismiss(None)

    def action_start_search(self) -> None:
        """Show the search input."""
        if self.load_error:
            return
        self._show_search()

    def _show_search(self) -> None:
        """Show the search input and focus it."""
        try:
            container = self.query_one("#log-search-container", Container)
            container.remove_class("hidden")
            search_input = self.query_one("#log-search-input", Input)
            search_input.value = self._search_term
            search_input.focus()
            self._search_active = True
        except Exception as exc:
            logger.warning(f"Failed to show search: {exc}")

    def _hide_search(self) -> None:
        """Hide the search input."""
        try:
            container = self.query_one("#log-search-container", Container)
            container.add_class("hidden")
            self._search_active = False
            # Refocus the scroll area
            scroll = self.query_one("#log-content-scroll", VerticalScroll)
            scroll.focus()
        except Exception as exc:
            logger.warning(f"Failed to hide search: {exc}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission.

        Args:
            event: The input submission event.
        """
        if event.input.id == "log-search-input":
            self._search_term = event.value.strip()
            if self._search_term:
                self._perform_search()
            else:
                self._clear_search()
            self._hide_search()

    def _perform_search(self) -> None:
        """Perform search and highlight matches."""
        if not self._raw_contents or not self._search_term:
            return

        # Find all lines containing the search term (case-insensitive)
        lines = self._raw_contents.split("\n")
        self._match_lines = []
        search_lower = self._search_term.lower()

        for i, line in enumerate(lines):
            if search_lower in line.lower():
                self._match_lines.append(i)

        if self._match_lines:
            self._current_match_index = 0
            self._update_search_status()
            self._scroll_to_match()
            self._highlight_matches()
            self.app.notify(f"Found {len(self._match_lines)} matches")
        else:
            self._current_match_index = -1
            self.app.notify("No matches found", severity="warning")

    def _clear_search(self) -> None:
        """Clear search results and highlights."""
        self._search_term = ""
        self._match_lines = []
        self._current_match_index = -1
        # Refresh display without highlights
        self._refresh_display()

    def _highlight_matches(self) -> None:
        """Highlight search matches in the display."""
        if not self._search_term:
            return

        try:
            content_widget = self.query_one("#log-content-text", Static)
            # Regenerate content with highlighted search term
            escaped_content = escape(self._raw_contents)

            # Highlight matches (case-insensitive)
            pattern = re.compile(re.escape(self._search_term), re.IGNORECASE)

            def highlight_match(match: re.Match[str]) -> str:
                # Re-escape the matched text to prevent breaking Rich markup
                # This handles cases where the match contains markup-like characters
                matched_text = escape(match.group())
                return f"[on yellow]{matched_text}[/on yellow]"

            highlighted_content = pattern.sub(highlight_match, escaped_content)

            if self._show_line_numbers:
                display_content = self._format_with_line_numbers(highlighted_content, self._start_line)
            else:
                display_content = highlighted_content

            if self.truncated:
                truncated_size_mb = Path(self.filepath).stat().st_size / (1024 * 1024)
                truncate_header = (
                    f"[bold yellow]⚠ File truncated (showing last ~{self.MAX_FILE_SIZE // 1024} KB "
                    f"of {truncated_size_mb:.1f} MB)[/bold yellow]\n"
                    f"[bright_black]{'─' * 60}[/bright_black]\n\n"
                )
                display_content = truncate_header + display_content

            content_widget.update(display_content)
            self.file_contents = display_content
        except Exception as exc:
            logger.warning(f"Failed to highlight matches: {exc}")

    def _refresh_display(self) -> None:
        """Refresh the display content without search highlights."""
        try:
            content_widget = self.query_one("#log-content-text", Static)
            self.file_contents = self._get_display_content()

            if self.truncated:
                truncated_size_mb = Path(self.filepath).stat().st_size / (1024 * 1024)
                truncate_header = (
                    f"[bold yellow]⚠ File truncated (showing last ~{self.MAX_FILE_SIZE // 1024} KB "
                    f"of {truncated_size_mb:.1f} MB)[/bold yellow]\n"
                    f"[bright_black]{'─' * 60}[/bright_black]\n\n"
                )
                self.file_contents = truncate_header + self.file_contents

            content_widget.update(self.file_contents)
        except Exception as exc:
            logger.warning(f"Failed to refresh display: {exc}")

    def _scroll_to_match(self) -> None:
        """Scroll to the current match."""
        if not self._match_lines or self._current_match_index < 0:
            return

        try:
            scroll = self.query_one("#log-content-scroll", VerticalScroll)
            # Estimate line height and scroll to approximate position
            match_line = self._match_lines[self._current_match_index]
            # Scroll to line position (rough approximation)
            scroll.scroll_to(y=match_line, animate=False)
        except Exception as exc:
            logger.debug(f"Failed to scroll to match: {exc}")

    def _update_search_status(self) -> None:
        """Update the search status display."""
        try:
            status = self.query_one("#log-search-status", Static)
            if self._match_lines:
                current = self._current_match_index + 1
                total = len(self._match_lines)
                status.update(f"[dim]{current}/{total}[/dim]")
            else:
                status.update("")
        except Exception as exc:
            logger.debug(f"Failed to update search status: {exc}")

    def action_next_match(self) -> None:
        """Go to the next search match."""
        if not self._match_lines:
            if self._search_term:
                self.app.notify("No matches", severity="warning")
            return

        self._current_match_index = (self._current_match_index + 1) % len(self._match_lines)
        self._scroll_to_match()
        self._update_search_status()

    def action_previous_match(self) -> None:
        """Go to the previous search match."""
        if not self._match_lines:
            if self._search_term:
                self.app.notify("No matches", severity="warning")
            return

        self._current_match_index = (self._current_match_index - 1) % len(self._match_lines)
        self._scroll_to_match()
        self._update_search_status()


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
        ("enter", "activate_focused", "Activate"),
        ("left", "focus_previous", "Previous"),
        ("right", "focus_next", "Next"),
        ("tab", "focus_next", "Next"),
        ("shift+tab", "focus_previous", "Previous"),
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
                "[bright_black]This action cannot be undone.[/bright_black]",
                id="cancel-warning",
            )
            with Container(id="cancel-button-row"):
                yield Button("🗑️ Cancel Job", variant="error", id="confirm-cancel-btn")
                yield Button("✕ Keep Running", variant="default", id="abort-cancel-btn")

    def on_mount(self) -> None:
        """Focus the abort button by default (safer option)."""
        try:
            self.query_one("#abort-cancel-btn", Button).focus()
        except Exception as exc:
            # Widget may not be ready yet, ignore
            logger.debug(f"Could not focus abort button on mount: {exc}")

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
        self.action_activate_focused()

    def action_activate_focused(self) -> None:
        """Activate the currently focused button (Enter key)."""
        try:
            focused = self.focused
            if isinstance(focused, Button):
                focused.press()
            else:
                # Fallback: if nothing is focused, default to abort (safer)
                self.dismiss(False)
        except Exception as exc:
            # Screen may be dismissing or button may not exist
            logger.debug(f"Could not activate focused button - screen may be dismissing: {exc}")
            # Default to abort (safer option)
            with contextlib.suppress(Exception):
                self.dismiss(False)

    def action_focus_next(self) -> None:
        """Focus the next button (right arrow or tab)."""
        try:
            buttons = [
                self.query_one("#confirm-cancel-btn", Button),
                self.query_one("#abort-cancel-btn", Button),
            ]
            focused = self.focused
            current_idx = None
            for idx, btn in enumerate(buttons):
                if btn is focused:
                    current_idx = idx
                    break

            if current_idx is None:
                # No button focused, focus the first one
                buttons[0].focus()
            else:
                # Focus the next button (wraps around)
                next_idx = (current_idx + 1) % len(buttons)
                buttons[next_idx].focus()
        except Exception as exc:
            # Screen may be dismissing or widgets may not exist
            logger.debug(f"Could not focus next button - screen may be dismissing: {exc}")

    def action_focus_previous(self) -> None:
        """Focus the previous button (left arrow or shift+tab)."""
        try:
            buttons = [
                self.query_one("#confirm-cancel-btn", Button),
                self.query_one("#abort-cancel-btn", Button),
            ]
            focused = self.focused
            current_idx = None
            for idx, btn in enumerate(buttons):
                if btn is focused:
                    current_idx = idx
                    break

            if current_idx is None:
                # No button focused, focus the last one
                buttons[-1].focus()
            else:
                # Focus the previous button (wraps around)
                prev_idx = (current_idx - 1) % len(buttons)
                buttons[prev_idx].focus()
        except Exception as exc:
            # Screen may be dismissing or widgets may not exist
            logger.debug(f"Could not focus previous button - screen may be dismissing: {exc}")


class NodeInfoScreen(Screen[None]):
    """Modal screen to display node information."""

    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    )

    def __init__(
        self,
        node_name: str,
        node_info: str,
        error: str | None = None,
    ) -> None:
        """Initialize the node info screen.

        Args:
            node_name: The node name being displayed.
            node_info: Formatted node information string.
            error: Optional error message if node info couldn't be retrieved.
        """
        super().__init__()
        self.node_name = node_name
        self.node_info = node_info
        self.error = error

    def compose(self) -> ComposeResult:
        """Create the node info display layout.

        Yields:
            The widgets that make up the node info display.
        """
        with Vertical():
            with Container(id="node-info-header"):
                yield Static("🖥️  [bold]Node Details[/bold]", id="node-info-title")
                yield Static(f"Node: [bold cyan]{self.node_name}[/bold cyan]", id="node-info-subtitle")

            if self.error:
                with Container(id="error-container"):
                    yield Static("⚠️  [bold]Error[/bold]", id="error-icon")
                    yield Static(self.error, id="error-text")
            else:
                with VerticalScroll(id="node-info-content"):
                    yield Static(self.node_info, id="node-info-text")

            with Container(id="node-info-footer"):
                yield Static(
                    "[bold]↑↓[/bold] Scroll | [bold]Esc[/bold] Close",
                    id="hint-text",
                )
                yield Button("✕ Close", variant="default", id="close-button")

    def on_mount(self) -> None:
        """Focus the content area on mount for scrolling."""
        try:
            content = self.query_one("#node-info-content", VerticalScroll)
            content.focus()
        except Exception:
            # If no content (error case), focus the close button
            self.query_one("#close-button", Button).focus()

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
