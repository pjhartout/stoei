"""Full-screen screens for job information display."""

import asyncio
import contextlib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

from rich.errors import MarkupError
from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Container, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Button, Input, Static

from stoei.editor import open_in_editor
from stoei.logger import get_logger

logger = get_logger(__name__)

# Timeout for file loading operations (in seconds)
FILE_LOAD_TIMEOUT = 1.0


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

    # Spinner frames for loading indicator
    SPINNER_FRAMES: ClassVar[tuple[str, ...]] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

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
        self._use_markup: bool = True  # Whether to use Rich markup (fallback to False on errors)
        # Search state
        self._search_term: str = ""
        self._search_active: bool = False
        self._match_lines: list[int] = []  # Line numbers with matches
        self._current_match_index: int = -1
        # Loading state
        self._is_loading: bool = True
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None
        self._load_timed_out: bool = False

    def compose(self) -> ComposeResult:
        """Create the log viewer layout.

        Yields:
            The widgets that make up the log viewer.
        """
        # Don't load file in compose - do it asynchronously in on_mount
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

            # Loading indicator (visible initially)
            with Container(id="log-loading-container"):
                yield Static(
                    f"{self.SPINNER_FRAMES[0]} Loading file...",
                    id="log-loading-spinner",
                )

            # Error container (hidden initially)
            with Container(id="log-error-container", classes="hidden"):
                yield Static("", id="log-error-text")

            # Content scroll (hidden initially)
            with VerticalScroll(id="log-content-scroll", classes="hidden"):
                yield Static("", id="log-content-text", markup=True)

            # Search bar (hidden by default)
            with Container(id="log-search-container", classes="hidden"):
                yield Input(placeholder="Search...", id="log-search-input")
                yield Static("", id="log-search-status")

            with Container(id="log-viewer-footer"):
                hint = "[b]g/G[/b] ↕ [b]/[/b] Search [b]n/N[/b] Next/Prev [b]l[/b] Line# [b]Esc[/b]"
                yield Static(hint, id="log-hint-text")
                yield Button("📝 Open in $EDITOR", variant="primary", id="editor-button")
                yield Button("✕ Close", variant="default", id="log-close-button")

    def _escape_markup(self, text: str) -> str:
        """Escape Rich markup in text to prevent interpretation.

        IMPORTANT: This function should only be called on RAW content (not already escaped).
        This escapes ALL opening brackets to prevent markup interpretation.

        Note: We cannot use rich_escape() here because it only escapes brackets that look
        like valid Rich markup tags (e.g., [bold]). Unmatched brackets like ['value are
        NOT escaped by rich_escape(), but they can still cause MarkupError when parsed
        by Textual/Rich because the parser tries to interpret them as tags with attributes.

        Args:
            text: Text that may contain Rich markup (should be raw, unescaped content).

        Returns:
            Text with all opening brackets escaped.
        """
        # Escape ALL opening brackets to prevent any markup interpretation
        # This is more aggressive than rich_escape() but necessary for safety
        return text.replace("[", "\\[")

    def _format_plain_with_line_numbers(self, content: str, start_line: int = 1) -> str:
        """Add plain line numbers to content (no markup styling).

        Args:
            content: The file content to format.
            start_line: Starting line number (useful for truncated files).

        Returns:
            Content with line numbers prepended, no markup.
        """
        if not content:
            return content

        lines = content.split("\n")
        total_lines = start_line + len(lines) - 1
        width = len(str(total_lines))

        numbered_lines = []
        for i, line in enumerate(lines):
            line_num = start_line + i
            numbered_lines.append(f"{line_num:>{width}} │ {line}")

        return "\n".join(numbered_lines)

    def _format_with_line_numbers(self, content: str, start_line: int = 1) -> str:
        """Add line numbers to content.

        Args:
            content: The file content to format (should already be escaped for markup safety).
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
            # Content should already be escaped by _get_display_content() before calling this.
            # We use it directly to avoid double-escaping (which causes issues with rich_escape).
            # The escaping in _get_display_content() ensures all [/dim] patterns are escaped.
            numbered_lines.append(f"[dim]{line_num:>{width}}[/dim] │ {line}")

        return "\n".join(numbered_lines)

    def _get_display_content(self, use_markup: bool = True) -> str:
        """Get the content to display, with or without line numbers.

        Args:
            use_markup: Whether to use Rich markup styling.

        Returns:
            The formatted content for display.
        """
        if not self._raw_contents:
            return self._raw_contents

        if use_markup:
            # Escape content to prevent markup interpretation of log content
            lines = self._raw_contents.split("\n")
            escaped_lines = [self._escape_markup(line) for line in lines]
            escaped_content = "\n".join(escaped_lines)

            if self._show_line_numbers:
                return self._format_with_line_numbers(escaped_content, self._start_line)
            return escaped_content
        else:
            # Plain text mode - no escaping needed, just add line numbers
            if self._show_line_numbers:
                return self._format_plain_with_line_numbers(self._raw_contents, self._start_line)
            return self._raw_contents

    def _get_safe_display_content(self) -> tuple[str, bool]:
        """Get content with fallback to plain text if markup fails.

        Returns:
            Tuple of (content, use_markup) where use_markup indicates
            whether the content should be rendered with markup=True.
        """
        logger.debug(f"Getting safe display content for {self.filepath}")

        if not self._raw_contents:
            logger.debug("Raw contents empty, returning placeholder")
            return "[bright_black](empty)[/bright_black]", True

        logger.debug(f"Raw content size: {len(self._raw_contents)} bytes")

        # Generate content with markup (escaped)
        content_with_markup = self._get_display_content(use_markup=True)
        logger.debug(f"Generated markup content size: {len(content_with_markup)} bytes")

        # Add truncation header if needed
        if self.truncated:
            truncated_size_mb = Path(self.filepath).stat().st_size / (1024 * 1024)
            truncate_header = (
                f"[bold yellow]⚠ File truncated (showing last ~{self.MAX_FILE_SIZE // 1024} KB "
                f"of {truncated_size_mb:.1f} MB)[/bold yellow]\n"
                f"[bright_black]{'─' * 60}[/bright_black]\n\n"
            )
            content_with_markup = truncate_header + content_with_markup
            logger.debug("Added truncation header")

        # Return content with markup enabled - errors will be caught at widget level
        logger.debug("Returning content with markup=True")
        return content_with_markup, True

    def _get_plain_display_content(self) -> str:
        """Get content as plain text without any markup.

        Returns:
            Plain text content with line numbers (if enabled).
        """
        logger.debug(f"Getting plain display content for {self.filepath}")

        if not self._raw_contents:
            return "(empty)"

        content_plain = self._get_display_content(use_markup=False)

        # Add plain truncation header if needed
        if self.truncated:
            truncated_size_mb = Path(self.filepath).stat().st_size / (1024 * 1024)
            truncate_header = (
                f"⚠ File truncated (showing last ~{self.MAX_FILE_SIZE // 1024} KB "
                f"of {truncated_size_mb:.1f} MB)\n"
                f"{'─' * 60}\n\n"
            )
            content_plain = truncate_header + content_plain

        return content_plain

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
        logger.debug(f"Loading truncated file: {path} (size: {file_size} bytes)")
        self.truncated = True

        logger.debug("Counting total lines in file")
        total_line_count = self._count_total_lines(path)
        logger.debug(f"Total line count: {total_line_count}")

        logger.debug(f"Seeking to position {file_size - self.MAX_FILE_SIZE}")
        with path.open("rb") as f:
            f.seek(file_size - self.MAX_FILE_SIZE)
            tail_bytes = f.read()
        logger.debug(f"Read {len(tail_bytes)} tail bytes")

        tail_text = tail_bytes.decode("utf-8", errors="replace")
        first_newline = tail_text.find("\n")
        skipped_partial_lines = 0
        if first_newline != -1:
            tail_text = tail_text[first_newline + 1 :]
            skipped_partial_lines = 1
            logger.debug("Skipped partial first line")

        tail_line_count = tail_text.count("\n") + 1
        self._start_line = max(1, total_line_count - tail_line_count + 2 - skipped_partial_lines)
        logger.debug(f"Tail contains {tail_line_count} lines, starting at line {self._start_line}")

        self._raw_contents = tail_text
        logger.debug(f"Raw contents: {len(self._raw_contents)} characters")

        # Use the safe display content method
        logger.debug("Generating display content for truncated file")
        self.file_contents, self._use_markup = self._get_safe_display_content()
        logger.debug(f"Display content: {len(self.file_contents)} chars, markup={self._use_markup}")

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
        logger.debug(f"Loading file: {self.filepath}")
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
            logger.debug(f"File size: {file_size} bytes")

            if file_size == 0:
                logger.debug("File is empty")
                self._raw_contents = ""
                self.file_contents = "[bright_black](empty file)[/bright_black]"
                self._use_markup = True
                logger.info(f"Loaded empty log file: {self.filepath}")
                return

            if file_size <= self.MAX_FILE_SIZE:
                logger.debug(f"File within size limit ({self.MAX_FILE_SIZE} bytes), reading entire file")
                # Read raw file content - this may contain markup-like text
                self._raw_contents = path.read_text()
                logger.debug(f"Read {len(self._raw_contents)} characters from file")
                self._start_line = 1
                # Generate display content
                logger.debug("Generating display content")
                self.file_contents, self._use_markup = self._get_safe_display_content()
                logger.debug(f"Display content generated: {len(self.file_contents)} chars, markup={self._use_markup}")
            else:
                logger.debug("File exceeds size limit, loading truncated")
                self._load_truncated_file(path, file_size)
                return

            logger.info(f"Loaded log file: {self.filepath} ({file_size} bytes)")
        except PermissionError:
            self.load_error = f"Permission denied: {self.filepath}"
            logger.warning(self.load_error)
        except OSError as exc:
            self.load_error = f"Error reading file: {exc}"
            logger.warning(self.load_error)
        except Exception as exc:
            self.load_error = f"Unexpected error reading file: {exc}"
            logger.exception(f"Unexpected error loading {self.filepath}")

    def on_mount(self) -> None:
        """Start loading the file asynchronously with a spinner."""
        logger.debug(f"LogViewerScreen mounted for {self.filepath}")
        # Start spinner animation
        self._spinner_timer = self.set_interval(0.1, self._animate_spinner)
        # Start async file loading
        self.run_worker(self._async_load_file, exclusive=True)

    def _animate_spinner(self) -> None:
        """Animate the loading spinner."""
        if not self._is_loading:
            return
        self._spinner_frame = (self._spinner_frame + 1) % len(self.SPINNER_FRAMES)
        try:
            spinner = self.query_one("#log-loading-spinner", Static)
            spinner.update(f"{self.SPINNER_FRAMES[self._spinner_frame]} Loading file...")
        except Exception as exc:
            logger.debug(f"Spinner update failed: {exc}")

    async def _async_load_file(self) -> None:
        """Load file asynchronously with timeout."""
        logger.debug(f"Starting async file load for {self.filepath}")
        loop = asyncio.get_running_loop()

        try:
            # Run file loading in a thread pool with timeout
            with ThreadPoolExecutor(max_workers=1) as executor:
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(executor, self._load_file),
                        timeout=FILE_LOAD_TIMEOUT,
                    )
                    logger.debug(f"File loaded successfully: {self.filepath}")
                except TimeoutError:
                    self._load_timed_out = True
                    self.load_error = (
                        f"File loading timed out after {FILE_LOAD_TIMEOUT}s. "
                        "The file may be on a slow filesystem. Press 'r' to retry."
                    )
                    logger.warning(f"File loading timed out for {self.filepath}")
        except Exception as exc:
            self.load_error = f"Unexpected error: {exc}"
            logger.exception(f"Error loading file: {self.filepath}")
        finally:
            self._is_loading = False
            # Stop spinner
            if self._spinner_timer:
                self._spinner_timer.stop()
                self._spinner_timer = None
            # Update UI - we're already on the main event loop
            self._on_load_complete()

    def _on_load_complete(self) -> None:
        """Called when file loading completes (success or failure)."""
        logger.debug(f"Load complete for {self.filepath}, error={self.load_error}")

        try:
            # Hide loading indicator
            try:
                loading_container = self.query_one("#log-loading-container", Container)
                loading_container.add_class("hidden")
            except NoMatches:
                logger.debug("Log loading container not found")

            if self.load_error:
                # Show error
                try:
                    error_container = self.query_one("#log-error-container", Container)
                    error_container.remove_class("hidden")
                    error_text = self.query_one("#log-error-text", Static)
                    error_text.update(f"⚠️  {self.load_error}")
                    # Focus close button
                    self.query_one("#log-close-button", Button).focus()
                except NoMatches:
                    logger.debug("Log error container not found")
                    return
                # Show notification for timeout
                if self._load_timed_out:
                    self.app.notify(
                        "File loading timed out. Press 'r' to retry.",
                        severity="warning",
                        timeout=5,
                    )
            else:
                # Show content
                try:
                    content_scroll = self.query_one("#log-content-scroll", VerticalScroll)
                    content_scroll.remove_class("hidden")
                    content_widget = self.query_one("#log-content-text", Static)
                except NoMatches:
                    logger.debug("Log content widgets not found")
                    return
                content_widget._render_markup = self._use_markup
                content_widget.update(self.file_contents)
                # Focus scroll area and scroll to bottom
                content_scroll.focus()
                self.call_after_refresh(self._scroll_to_bottom)
                logger.debug("Content displayed, scrolling to bottom")
        except Exception:
            logger.exception("Error updating UI after load")

    def _handle_markup_error(self, error: Exception) -> None:
        """Handle a MarkupError by switching to plain text mode.

        Args:
            error: The exception that was raised.
        """
        logger.warning(f"Markup error for {self.filepath}: {error}")
        logger.info("Switching to plain text mode")
        self._use_markup = False
        try:
            content_widget = self.query_one("#log-content-text", Static)
            content_widget._render_markup = False
            plain_content = self._get_plain_display_content()
            logger.debug(f"Plain content size: {len(plain_content)} chars")
            content_widget.update(plain_content)
            self.file_contents = plain_content
            self.app.notify("Switched to plain text mode due to markup error", severity="warning")
        except Exception:
            logger.exception("Failed to switch to plain text mode")

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
        """Reload the file contents asynchronously."""
        logger.debug(f"Reloading file: {self.filepath}")
        # Reset state for reload
        self._is_loading = True
        self._load_timed_out = False
        self.load_error = None

        try:
            # Show loading indicator
            loading_container = self.query_one("#log-loading-container", Container)
            loading_container.remove_class("hidden")
            # Hide content/error
            content_scroll = self.query_one("#log-content-scroll", VerticalScroll)
            content_scroll.add_class("hidden")
            error_container = self.query_one("#log-error-container", Container)
            error_container.add_class("hidden")
        except Exception as exc:
            logger.debug(f"Failed to update UI state for reload: {exc}")

        # Restart spinner
        if self._spinner_timer:
            self._spinner_timer.stop()
        self._spinner_timer = self.set_interval(0.1, self._animate_spinner)

        # Start async reload
        self.run_worker(self._async_reload_file, exclusive=True)
        self.app.notify("Reloading file...", timeout=2)

    async def _async_reload_file(self) -> None:
        """Reload file asynchronously with timeout."""
        logger.debug(f"Starting async reload for {self.filepath}")
        loop = asyncio.get_running_loop()

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(executor, self._load_file),
                        timeout=FILE_LOAD_TIMEOUT,
                    )
                    logger.debug(f"File reloaded successfully: {self.filepath}")
                except TimeoutError:
                    self._load_timed_out = True
                    self.load_error = (
                        f"File loading timed out after {FILE_LOAD_TIMEOUT}s. "
                        "The file may be on a slow filesystem. Press 'r' to retry."
                    )
                    logger.warning(f"File reload timed out for {self.filepath}")
        except Exception as exc:
            self.load_error = f"Unexpected error: {exc}"
            logger.exception(f"Error reloading file: {self.filepath}")
        finally:
            self._is_loading = False
            if self._spinner_timer:
                self._spinner_timer.stop()
                self._spinner_timer = None
            # Update UI - we're already on the main event loop
            self._on_reload_complete()

    def _on_reload_complete(self) -> None:
        """Called when file reload completes."""
        logger.debug(f"Reload complete for {self.filepath}, error={self.load_error}")

        try:
            # Hide loading indicator
            loading_container = self.query_one("#log-loading-container", Container)
            loading_container.add_class("hidden")

            if self.load_error:
                # Show error
                error_container = self.query_one("#log-error-container", Container)
                error_container.remove_class("hidden")
                error_text = self.query_one("#log-error-text", Static)
                error_text.update(f"⚠️  {self.load_error}")
                # Hide content
                content_scroll = self.query_one("#log-content-scroll", VerticalScroll)
                content_scroll.add_class("hidden")
                self.query_one("#log-close-button", Button).focus()
                if self._load_timed_out:
                    self.app.notify(
                        "File reload timed out. Press 'r' to retry.",
                        severity="warning",
                        timeout=5,
                    )
            else:
                # Show content
                error_container = self.query_one("#log-error-container", Container)
                error_container.add_class("hidden")
                content_scroll = self.query_one("#log-content-scroll", VerticalScroll)
                content_scroll.remove_class("hidden")
                content_widget = self.query_one("#log-content-text", Static)
                content_widget._render_markup = self._use_markup
                content_widget.update(self.file_contents)
                content_scroll.focus()
                self.app.notify("File reloaded")
                logger.info(f"Reloaded log file: {self.filepath}")
        except MarkupError as exc:
            self._handle_markup_error(exc)
        except Exception:
            logger.exception("Failed to update content after reload")

    def action_toggle_line_numbers(self) -> None:
        """Toggle line number display."""
        self._show_line_numbers = not self._show_line_numbers
        state = "on" if self._show_line_numbers else "off"
        logger.debug(f"Toggling line numbers: {state}")

        try:
            content_widget = self.query_one("#log-content-text", Static)
            if self.load_error:
                logger.debug("Load error exists, not toggling")
                return

            # Regenerate content with/without line numbers
            logger.debug("Regenerating display content")
            self.file_contents, self._use_markup = self._get_safe_display_content()
            content_widget._render_markup = self._use_markup
            logger.debug(f"Updating widget with {len(self.file_contents)} chars, markup={self._use_markup}")
            content_widget.update(self.file_contents)

            self.app.notify(f"Line numbers {state}")
            logger.debug(f"Line numbers toggled: {state}")
        except MarkupError as exc:
            self._handle_markup_error(exc)
        except Exception:
            logger.exception("Failed to toggle line numbers")

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
        logger.debug(f"Highlighting matches for search term: {self._search_term}")

        if not self._search_term:
            logger.debug("No search term, skipping highlight")
            return

        # If we're not using markup, we can't highlight - just show the content
        if not self._use_markup:
            logger.debug("Markup disabled, refreshing display without highlights")
            self._refresh_display()
            return

        try:
            content_widget = self.query_one("#log-content-text", Static)
            # Regenerate content with highlighted search term
            # Escape line-by-line for consistency
            logger.debug("Escaping content for highlighting")
            lines = self._raw_contents.split("\n")
            escaped_lines = [self._escape_markup(line) for line in lines]
            escaped_content = "\n".join(escaped_lines)

            # Highlight matches (case-insensitive)
            # Search in the escaped content, but the search term itself doesn't need escaping
            # since we're looking for literal text
            search_escaped = self._escape_markup(self._search_term)
            pattern = re.compile(re.escape(search_escaped), re.IGNORECASE)
            logger.debug(f"Searching for pattern: {pattern.pattern}")

            def highlight_match(match: re.Match[str]) -> str:
                # The matched text is already escaped, just wrap it
                return f"[on yellow]{match.group()}[/on yellow]"

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

            logger.debug(f"Updating widget with highlighted content ({len(display_content)} chars)")
            content_widget.update(display_content)
            self.file_contents = display_content
        except MarkupError as exc:
            logger.warning(f"Markup error during highlighting: {exc}")
            self._handle_markup_error(exc)
        except Exception:
            logger.exception("Failed to highlight matches")
            # On any error, just refresh without highlights
            self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the display content without search highlights."""
        logger.debug("Refreshing display")
        try:
            content_widget = self.query_one("#log-content-text", Static)
            self.file_contents, self._use_markup = self._get_safe_display_content()
            logger.debug(f"Got content: {len(self.file_contents)} chars, markup={self._use_markup}")
            content_widget._render_markup = self._use_markup
            content_widget.update(self.file_contents)
            logger.debug("Display refreshed")
        except MarkupError as exc:
            self._handle_markup_error(exc)
        except Exception:
            logger.exception("Failed to refresh display")

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
                yield Button("🗑️ Yes, Cancel", variant="error", id="confirm-cancel-btn")
                yield Button("✓ No, Keep It", variant="default", id="abort-cancel-btn")

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
