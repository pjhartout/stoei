"""Tests for screen widgets."""

from pathlib import Path

import pytest

from stoei.widgets.screens import JobInfoScreen, LogViewerScreen


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
        assert "Line 0" in screen.file_contents
        assert "Line 99" in screen.file_contents

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
