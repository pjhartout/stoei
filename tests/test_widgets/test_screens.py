"""Tests for screen widgets."""

from pathlib import Path

import pytest
from stoei.widgets.screens import CancelConfirmScreen, JobInfoScreen, JobInputScreen, LogViewerScreen


class TestJobInfoScreen:
    """Tests for JobInfoScreen."""

    def test_init_stores_job_id(self) -> None:
        """Test that job_id is stored on initialization."""
        screen = JobInfoScreen("12345", "Job info content")
        assert screen.job_id == "12345"

    def test_init_stores_job_info(self) -> None:
        """Test that job_info is stored on initialization."""
        screen = JobInfoScreen("12345", "Job info content")
        assert screen.job_info == "Job info content"

    def test_init_log_paths_none_by_default(self) -> None:
        """Test that log paths are None by default."""
        screen = JobInfoScreen("12345", "Job info content")
        assert screen.stdout_path is None
        assert screen.stderr_path is None

    def test_init_with_log_paths(self) -> None:
        """Test initialization with log paths."""
        screen = JobInfoScreen(
            "12345",
            "Job info content",
            stdout_path="/path/to/stdout.out",
            stderr_path="/path/to/stderr.err",
        )
        assert screen.stdout_path == "/path/to/stdout.out"
        assert screen.stderr_path == "/path/to/stderr.err"

    def test_init_with_error(self) -> None:
        """Test initialization with error message."""
        screen = JobInfoScreen("12345", "", error="Job not found")
        assert screen.error == "Job not found"

    def test_bindings_defined(self) -> None:
        """Test that bindings are defined."""
        assert len(JobInfoScreen.BINDINGS) > 0

    def test_bindings_include_escape(self) -> None:
        """Test that escape binding exists."""
        binding_keys = [b[0] for b in JobInfoScreen.BINDINGS]
        assert "escape" in binding_keys

    def test_bindings_include_close(self) -> None:
        """Test that q binding exists for close."""
        binding_keys = [b[0] for b in JobInfoScreen.BINDINGS]
        assert "q" in binding_keys

    def test_bindings_include_log_viewers(self) -> None:
        """Test that log viewer bindings exist."""
        binding_keys = [b[0] for b in JobInfoScreen.BINDINGS]
        assert "o" in binding_keys  # stdout
        assert "e" in binding_keys  # stderr


class TestLogViewerScreen:
    """Tests for LogViewerScreen."""

    def test_init_stores_parameters(self) -> None:
        """Test that parameters are stored on initialization."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert screen.filepath == "/path/to/log.out"
        assert screen.log_type == "stdout"

    def test_init_stderr_type(self) -> None:
        """Test initialization with stderr type."""
        screen = LogViewerScreen("/path/to/log.err", "stderr")
        assert screen.log_type == "stderr"

    def test_init_empty_file_contents(self) -> None:
        """Test that file_contents is empty initially."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert screen.file_contents == ""

    def test_init_no_load_error(self) -> None:
        """Test that load_error is None initially."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert screen.load_error is None

    def test_init_not_truncated(self) -> None:
        """Test that truncated is False initially."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert screen.truncated is False

    def test_init_line_numbers_enabled(self) -> None:
        """Test that line numbers are enabled by default."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert screen._show_line_numbers is True

    def test_init_start_line(self) -> None:
        """Test that start line is 1 initially."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert screen._start_line == 1

    def test_init_search_state(self) -> None:
        """Test that search state is initialized correctly."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert screen._search_term == ""
        assert screen._search_active is False
        assert screen._match_lines == []
        assert screen._current_match_index == -1

    def test_bindings_defined(self) -> None:
        """Test that bindings are defined."""
        assert len(LogViewerScreen.BINDINGS) > 0

    def test_bindings_include_navigation(self) -> None:
        """Test that navigation bindings exist."""
        binding_keys = [b[0] for b in LogViewerScreen.BINDINGS]
        assert "g" in binding_keys  # top
        assert "G" in binding_keys  # bottom
        assert "r" in binding_keys  # reload
        assert "escape" in binding_keys  # close
        assert "q" in binding_keys  # close

    def test_bindings_include_editor(self) -> None:
        """Test that editor binding exists."""
        binding_keys = [b[0] for b in LogViewerScreen.BINDINGS]
        assert "e" in binding_keys  # open in editor

    def test_bindings_include_line_numbers(self) -> None:
        """Test that line numbers toggle binding exists."""
        binding_keys = [b[0] for b in LogViewerScreen.BINDINGS]
        assert "l" in binding_keys  # toggle line numbers

    def test_bindings_include_search(self) -> None:
        """Test that search bindings exist."""
        binding_keys = [b[0] for b in LogViewerScreen.BINDINGS]
        assert "slash" in binding_keys  # search
        assert "n" in binding_keys  # next match
        assert "N" in binding_keys  # previous match


class TestLogViewerLineNumbers:
    """Tests for LogViewerScreen line number functionality."""

    def test_format_with_line_numbers_basic(self) -> None:
        """Test basic line number formatting."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        content = "line1\nline2\nline3"
        result = screen._format_with_line_numbers(content, start_line=1)
        assert "[dim]1[/dim] │ line1" in result
        assert "[dim]2[/dim] │ line2" in result
        assert "[dim]3[/dim] │ line3" in result

    def test_format_with_line_numbers_start_offset(self) -> None:
        """Test line number formatting with start offset."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        content = "lineA\nlineB"
        result = screen._format_with_line_numbers(content, start_line=50)
        assert "[dim]50[/dim] │ lineA" in result
        assert "[dim]51[/dim] │ lineB" in result

    def test_format_with_line_numbers_padding(self) -> None:
        """Test line number padding for multi-digit lines."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        # Create content that ends at line 100+
        content = "line1\nline2"
        result = screen._format_with_line_numbers(content, start_line=99)
        # Should have proper padding for 3-digit numbers
        assert "[dim] 99[/dim] │ line1" in result
        assert "[dim]100[/dim] │ line2" in result

    def test_format_with_line_numbers_empty(self) -> None:
        """Test line number formatting with empty content."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        result = screen._format_with_line_numbers("", start_line=1)
        assert result == ""

    def test_get_display_content_with_line_numbers(self) -> None:
        """Test _get_display_content with line numbers enabled."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        screen._raw_contents = "line1\nline2"
        screen._show_line_numbers = True
        screen._start_line = 1
        result = screen._get_display_content()
        assert "[dim]1[/dim] │" in result

    def test_get_display_content_without_line_numbers(self) -> None:
        """Test _get_display_content with line numbers disabled."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        screen._raw_contents = "line1\nline2"
        screen._show_line_numbers = False
        screen._start_line = 1
        result = screen._get_display_content()
        assert "[dim]" not in result
        assert "line1" in result

    def test_get_display_content_escapes_markup(self) -> None:
        """Test that _get_display_content escapes markup characters."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        screen._raw_contents = "[bold]not bold[/bold]"
        screen._show_line_numbers = True
        screen._start_line = 1
        result = screen._get_display_content()
        # The [bold] should be escaped (Rich escape uses single backslash)
        # and [dim] for line numbers should still work
        assert "\\[bold]" in result  # Escaped markup
        assert "[dim]" in result  # Line number markup still present


class TestLogViewerFileLoading:
    """Tests for LogViewerScreen file loading."""

    @pytest.fixture
    def temp_log_file(self, tmp_path: Path) -> Path:
        """Create a temporary log file with numbered lines."""
        log_file = tmp_path / "test.log"
        lines = [f"Line {i}\n" for i in range(100)]
        log_file.write_text("".join(lines))
        return log_file

    def test_load_file_success(self, temp_log_file: Path) -> None:
        """Test that _load_file loads file contents."""
        screen = LogViewerScreen(str(temp_log_file), "stdout")
        screen._load_file()
        assert screen.load_error is None
        # Should have line numbers by default
        assert "[dim]" in screen.file_contents
        assert "Line 0" in screen.file_contents
        assert "Line 99" in screen.file_contents

    def test_load_file_success_with_line_numbers(self, temp_log_file: Path) -> None:
        """Test that _load_file includes line numbers."""
        screen = LogViewerScreen(str(temp_log_file), "stdout")
        screen._load_file()
        assert screen.load_error is None
        # Check for line number formatting
        assert "[dim]" in screen.file_contents
        assert "│" in screen.file_contents

    def test_load_file_not_found(self, tmp_path: Path) -> None:
        """Test _load_file with non-existent file."""
        log_file = tmp_path / "nonexistent.log"
        screen = LogViewerScreen(str(log_file), "stdout")
        screen._load_file()
        assert screen.load_error is not None
        assert "does not exist" in screen.load_error

    def test_load_file_empty(self, tmp_path: Path) -> None:
        """Test _load_file with empty file."""
        log_file = tmp_path / "empty.log"
        log_file.write_text("")
        screen = LogViewerScreen(str(log_file), "stdout")
        screen._load_file()
        assert screen.load_error is None
        assert "(empty file)" in screen.file_contents

    def test_load_file_directory(self, tmp_path: Path) -> None:
        """Test _load_file with directory path."""
        screen = LogViewerScreen(str(tmp_path), "stdout")
        screen._load_file()
        assert screen.load_error is not None
        assert "Not a regular file" in screen.load_error

    def test_load_file_large_truncates(self, tmp_path: Path) -> None:
        """Test _load_file truncates large files to the tail."""
        log_file = tmp_path / "large.log"
        # Create a file larger than MAX_FILE_SIZE (512 KB)
        # Write 600 KB of content
        line = "This is a test line with some content for the log file.\n"
        num_lines = (600 * 1024) // len(line) + 1
        content = line * num_lines
        log_file.write_text(content)

        screen = LogViewerScreen(str(log_file), "stdout")
        screen._load_file()

        assert screen.load_error is None
        assert screen.truncated is True
        assert "File truncated" in screen.file_contents
        # Should contain lines from the end
        assert "This is a test line" in screen.file_contents
        # Raw content should be significantly smaller than original
        # (file_contents may be larger due to line number markup)
        assert len(screen._raw_contents) < len(content)

    def test_load_file_small_not_truncated(self, temp_log_file: Path) -> None:
        """Test _load_file does not truncate small files."""
        screen = LogViewerScreen(str(temp_log_file), "stdout")
        screen._load_file()
        assert screen.load_error is None
        assert screen.truncated is False
        assert "File truncated" not in screen.file_contents

    def test_load_file_permission_denied(self, tmp_path: Path) -> None:
        """Test _load_file handles permission errors."""
        log_file = tmp_path / "protected.log"
        log_file.write_text("Secret content")
        # Make file unreadable
        log_file.chmod(0o000)

        try:
            screen = LogViewerScreen(str(log_file), "stdout")
            screen._load_file()
            # Should have an error or be empty
            # (Behavior may vary based on environment)
            assert screen.load_error is not None or screen.file_contents == ""
        finally:
            # Restore permissions for cleanup
            log_file.chmod(0o644)

    def test_load_file_with_markup_special_chars(self, tmp_path: Path) -> None:
        """Test that files with markup-like characters don't cause MarkupError."""
        # Content that would cause MarkupError if markup is enabled
        # This simulates the error from the user's report
        problematic_content = (
            "=3', 'model=test', 'loaders.train.batch_size=128', "
            "'training.accumulate_grad_batches=4', 'training.schedule_type=cosine', "
            "'training.validate_before_training=false', 'training.max_epochs=2', "
            "'compute.devices=1', 'debug.enable=true', '+debug.limit_val_batches=0', "
            "'logs.wandb.name=gpu_scaling_2g_2t1d', 'training.warmup_iters=500']\n"
        )
        log_file = tmp_path / "error.log"
        log_file.write_text(problematic_content)

        screen = LogViewerScreen(str(log_file), "stderr")
        screen._load_file()

        # Should load without error
        assert screen.load_error is None
        assert problematic_content.strip() in screen.file_contents


class TestCancelConfirmScreen:
    """Tests for CancelConfirmScreen."""

    def test_init_stores_job_id(self) -> None:
        """Test that job_id is stored on initialization."""
        screen = CancelConfirmScreen("12345")
        assert screen.job_id == "12345"

    def test_init_stores_job_name(self) -> None:
        """Test that job_name is stored on initialization."""
        screen = CancelConfirmScreen("12345", "test_job")
        assert screen.job_name == "test_job"

    def test_init_job_name_optional(self) -> None:
        """Test that job_name is optional."""
        screen = CancelConfirmScreen("12345")
        assert screen.job_name is None

    def test_bindings_defined(self) -> None:
        """Test that bindings are defined."""
        assert len(CancelConfirmScreen.BINDINGS) > 0

    def test_bindings_include_escape(self) -> None:
        """Test that escape binding exists."""
        binding_keys = [b[0] for b in CancelConfirmScreen.BINDINGS]
        assert "escape" in binding_keys

    def test_bindings_include_enter(self) -> None:
        """Test that enter binding exists."""
        binding_keys = [b[0] for b in CancelConfirmScreen.BINDINGS]
        assert "enter" in binding_keys

    def test_bindings_include_navigation(self) -> None:
        """Test that navigation bindings exist."""
        binding_keys = [b[0] for b in CancelConfirmScreen.BINDINGS]
        assert "left" in binding_keys
        assert "right" in binding_keys
        assert "tab" in binding_keys
        assert "shift+tab" in binding_keys


class TestJobInputScreen:
    """Tests for JobInputScreen."""

    def test_bindings_defined(self) -> None:
        """Test that bindings are defined."""
        assert len(JobInputScreen.BINDINGS) > 0

    def test_bindings_include_escape(self) -> None:
        """Test that escape binding exists."""
        binding_keys = [b[0] for b in JobInputScreen.BINDINGS]
        assert "escape" in binding_keys


class TestJobInfoScreenNavigation:
    """Tests for JobInfoScreen navigation helpers."""

    def test_get_button_order_returns_list(self) -> None:
        """Test _get_button_order method signature."""
        screen = JobInfoScreen("12345", "Job info content")
        # This method requires the screen to be composed, so we just verify it exists
        assert hasattr(screen, "_get_button_order")
        assert callable(screen._get_button_order)

    def test_is_button_focused_method_exists(self) -> None:
        """Test _is_button_focused method exists."""
        screen = JobInfoScreen("12345", "Job info content")
        assert hasattr(screen, "_is_button_focused")
        assert callable(screen._is_button_focused)

    def test_focus_first_button_method_exists(self) -> None:
        """Test _focus_first_button method exists."""
        screen = JobInfoScreen("12345", "Job info content")
        assert hasattr(screen, "_focus_first_button")
        assert callable(screen._focus_first_button)

    def test_get_focused_button_index_method_exists(self) -> None:
        """Test _get_focused_button_index method exists."""
        screen = JobInfoScreen("12345", "Job info content")
        assert hasattr(screen, "_get_focused_button_index")
        assert callable(screen._get_focused_button_index)


class TestLogViewerScreenMethods:
    """Tests for LogViewerScreen methods."""

    def test_scroll_to_bottom_method_exists(self) -> None:
        """Test _scroll_to_bottom method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "_scroll_to_bottom")
        assert callable(screen._scroll_to_bottom)

    def test_open_in_editor_method_exists(self) -> None:
        """Test _open_in_editor method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "_open_in_editor")
        assert callable(screen._open_in_editor)


class TestJobInfoScreenActions:
    """Tests for JobInfoScreen action methods."""

    def test_action_close_method_exists(self) -> None:
        """Test action_close method exists."""
        screen = JobInfoScreen("12345", "Job info")
        assert hasattr(screen, "action_close")
        assert callable(screen.action_close)

    def test_action_open_stdout_method_exists(self) -> None:
        """Test action_open_stdout method exists."""
        screen = JobInfoScreen("12345", "Job info")
        assert hasattr(screen, "action_open_stdout")
        assert callable(screen.action_open_stdout)

    def test_action_open_stderr_method_exists(self) -> None:
        """Test action_open_stderr method exists."""
        screen = JobInfoScreen("12345", "Job info")
        assert hasattr(screen, "action_open_stderr")
        assert callable(screen.action_open_stderr)

    def test_action_focus_content_method_exists(self) -> None:
        """Test action_focus_content method exists."""
        screen = JobInfoScreen("12345", "Job info")
        assert hasattr(screen, "action_focus_content")
        assert callable(screen.action_focus_content)

    def test_action_focus_buttons_method_exists(self) -> None:
        """Test action_focus_buttons method exists."""
        screen = JobInfoScreen("12345", "Job info")
        assert hasattr(screen, "action_focus_buttons")
        assert callable(screen.action_focus_buttons)

    def test_action_focus_next_method_exists(self) -> None:
        """Test action_focus_next method exists."""
        screen = JobInfoScreen("12345", "Job info")
        assert hasattr(screen, "action_focus_next")
        assert callable(screen.action_focus_next)

    def test_action_focus_previous_method_exists(self) -> None:
        """Test action_focus_previous method exists."""
        screen = JobInfoScreen("12345", "Job info")
        assert hasattr(screen, "action_focus_previous")
        assert callable(screen.action_focus_previous)


class TestLogViewerScreenActions:
    """Tests for LogViewerScreen action methods."""

    def test_action_close_method_exists(self) -> None:
        """Test action_close method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_close")
        assert callable(screen.action_close)

    def test_action_open_in_editor_method_exists(self) -> None:
        """Test action_open_in_editor method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_open_in_editor")
        assert callable(screen.action_open_in_editor)

    def test_action_scroll_top_method_exists(self) -> None:
        """Test action_scroll_top method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_scroll_top")
        assert callable(screen.action_scroll_top)

    def test_action_scroll_bottom_method_exists(self) -> None:
        """Test action_scroll_bottom method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_scroll_bottom")
        assert callable(screen.action_scroll_bottom)

    def test_action_reload_method_exists(self) -> None:
        """Test action_reload method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_reload")
        assert callable(screen.action_reload)

    def test_action_toggle_line_numbers_method_exists(self) -> None:
        """Test action_toggle_line_numbers method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_toggle_line_numbers")
        assert callable(screen.action_toggle_line_numbers)

    def test_action_start_search_method_exists(self) -> None:
        """Test action_start_search method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_start_search")
        assert callable(screen.action_start_search)

    def test_action_next_match_method_exists(self) -> None:
        """Test action_next_match method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_next_match")
        assert callable(screen.action_next_match)

    def test_action_previous_match_method_exists(self) -> None:
        """Test action_previous_match method exists."""
        screen = LogViewerScreen("/path/to/log.out", "stdout")
        assert hasattr(screen, "action_previous_match")
        assert callable(screen.action_previous_match)


class TestCancelConfirmScreenActions:
    """Tests for CancelConfirmScreen action methods."""

    def test_action_cancel_method_exists(self) -> None:
        """Test action_cancel method exists."""
        screen = CancelConfirmScreen("12345")
        assert hasattr(screen, "action_cancel")
        assert callable(screen.action_cancel)

    def test_action_activate_focused_method_exists(self) -> None:
        """Test action_activate_focused method exists."""
        screen = CancelConfirmScreen("12345")
        assert hasattr(screen, "action_activate_focused")
        assert callable(screen.action_activate_focused)

    def test_action_focus_next_method_exists(self) -> None:
        """Test action_focus_next method exists."""
        screen = CancelConfirmScreen("12345")
        assert hasattr(screen, "action_focus_next")
        assert callable(screen.action_focus_next)

    def test_action_focus_previous_method_exists(self) -> None:
        """Test action_focus_previous method exists."""
        screen = CancelConfirmScreen("12345")
        assert hasattr(screen, "action_focus_previous")
        assert callable(screen.action_focus_previous)


class TestJobInputScreenActions:
    """Tests for JobInputScreen action methods."""

    def test_action_cancel_method_exists(self) -> None:
        """Test action_cancel method exists."""
        screen = JobInputScreen()
        assert hasattr(screen, "action_cancel")
        assert callable(screen.action_cancel)


class TestScreensInApp:
    """Functional tests for screens running in an app context."""

    async def test_job_info_screen_composes(self) -> None:
        """Test that JobInfoScreen composes correctly."""
        from textual.app import App
        from textual.widgets import Button

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(JobInfoScreen("12345", "Test job info"))

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Query through the screen stack
            screen = app.screen
            close_btn = screen.query_one("#close-button", Button)
            assert close_btn is not None

    async def test_job_info_screen_with_error_composes(self) -> None:
        """Test that JobInfoScreen with error composes correctly."""
        from textual.app import App

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(JobInfoScreen("12345", "", error="Job not found"))

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            error_text = screen.query_one("#error-text")
            assert error_text is not None

    async def test_cancel_confirm_screen_composes(self) -> None:
        """Test that CancelConfirmScreen composes correctly."""
        from textual.app import App
        from textual.widgets import Button

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(CancelConfirmScreen("12345", "test_job"))

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            confirm_btn = screen.query_one("#confirm-cancel-btn", Button)
            abort_btn = screen.query_one("#abort-cancel-btn", Button)
            assert confirm_btn is not None
            assert abort_btn is not None

    async def test_cancel_confirm_abort_button_focused(self) -> None:
        """Test that abort button is focused by default (safer option)."""
        from textual.app import App
        from textual.widgets import Button

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(CancelConfirmScreen("12345"))

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            abort_btn = screen.query_one("#abort-cancel-btn", Button)
            assert abort_btn.has_focus

    async def test_job_input_screen_composes(self) -> None:
        """Test that JobInputScreen composes correctly."""
        from textual.app import App
        from textual.widgets import Button, Input

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(JobInputScreen())

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            input_widget = screen.query_one("#job-id-input", Input)
            submit_btn = screen.query_one("#submit-btn", Button)
            cancel_btn = screen.query_one("#cancel-btn", Button)
            assert input_widget is not None
            assert submit_btn is not None
            assert cancel_btn is not None

    async def test_job_input_screen_input_focused(self) -> None:
        """Test that input field is focused on mount."""
        from textual.app import App
        from textual.widgets import Input

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(JobInputScreen())

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            input_widget = screen.query_one("#job-id-input", Input)
            assert input_widget.has_focus

    async def test_log_viewer_screen_composes_with_file(self, tmp_path: Path) -> None:
        """Test that LogViewerScreen composes with a real file."""
        from textual.app import App
        from textual.widgets import Button

        log_file = tmp_path / "test.log"
        log_file.write_text("Line 1\nLine 2\nLine 3\n")

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(LogViewerScreen(str(log_file), "stdout"))

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            close_btn = screen.query_one("#log-close-button", Button)
            editor_btn = screen.query_one("#editor-button", Button)
            assert close_btn is not None
            assert editor_btn is not None

    async def test_log_viewer_screen_composes_with_missing_file(self) -> None:
        """Test that LogViewerScreen handles missing file."""
        from textual.app import App

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(LogViewerScreen("/nonexistent/path.log", "stdout"))

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            # Should still compose with error message
            close_btn = screen.query_one("#log-close-button")
            assert close_btn is not None
            error_text = screen.query_one("#log-error-text")
            assert error_text is not None

    async def test_log_viewer_screen_renders_markup_special_chars(self, tmp_path: Path) -> None:
        """Test that LogViewerScreen renders files with markup-like characters without error."""
        from textual.app import App
        from textual.widgets import Static

        # Content that would cause MarkupError if markup is enabled
        problematic_content = (
            "=3', 'model=test', 'loaders.train.batch_size=128', "
            "'training.accumulate_grad_batches=4', 'training.schedule_type=cosine', "
            "'training.validate_before_training=false', 'training.max_epochs=2', "
            "'compute.devices=1', 'debug.enable=true', '+debug.limit_val_batches=0', "
            "'logs.wandb.name=gpu_scaling_2g_2t1d', 'training.warmup_iters=500']\n"
        )
        log_file = tmp_path / "error.log"
        log_file.write_text(problematic_content)

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(LogViewerScreen(str(log_file), "stderr"))

        app = TestApp()
        # This should not raise MarkupError
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            # Verify the content widget exists and renders without MarkupError
            content_widget = screen.query_one("#log-content-text", Static)
            assert content_widget is not None
            # The key test: rendering should not raise MarkupError
            # This would have failed before the fix
            rendered = content_widget.render()
            assert rendered is not None
            # Verify content is displayed
            rendered_str = str(rendered)
            assert problematic_content.strip() in rendered_str or problematic_content in rendered_str
