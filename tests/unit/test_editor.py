"""Tests for the editor module."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from stoei.editor import DEFAULT_EDITORS, get_editor, open_in_editor


class TestGetEditor:
    """Tests for get_editor function."""

    def test_uses_editor_env_variable(self) -> None:
        """Test that $EDITOR environment variable is used if set."""
        with (
            patch.dict(os.environ, {"EDITOR": "vim"}),
            patch("shutil.which") as mock_which,
        ):
            mock_which.return_value = "/usr/bin/vim"
            result = get_editor()
            assert result == "vim"
            mock_which.assert_called_with("vim")

    def test_editor_not_found_falls_back(self) -> None:
        """Test fallback to default editors when $EDITOR not executable."""
        with (
            patch.dict(os.environ, {"EDITOR": "nonexistent"}),
            patch("shutil.which") as mock_which,
        ):
            # First call for EDITOR returns None (not found)
            # Second call for first default editor returns path
            mock_which.side_effect = [None, "/usr/bin/vim"]
            result = get_editor()
            assert result == "vim"

    def test_uses_first_available_default_editor(self) -> None:
        """Test that first available default editor is used."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shutil.which") as mock_which,
        ):
            # Simulate less and more not found, vim found
            def which_side_effect(editor: str) -> str | None:
                if editor == "vim":
                    return "/usr/bin/vim"
                return None

            mock_which.side_effect = which_side_effect
            result = get_editor()
            assert result == "vim"

    def test_returns_none_when_no_editor_found(self) -> None:
        """Test that None is returned when no editor is found."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shutil.which") as mock_which,
        ):
            mock_which.return_value = None
            result = get_editor()
            assert result is None

    def test_default_editors_are_checked_in_order(self) -> None:
        """Test that default editors are checked in order."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shutil.which") as mock_which,
        ):
            mock_which.return_value = None
            get_editor()
            # Verify all default editors were checked
            calls = [call[0][0] for call in mock_which.call_args_list]
            assert calls == DEFAULT_EDITORS


class TestOpenInEditor:
    """Tests for open_in_editor function."""

    def test_returns_error_when_no_filepath(self) -> None:
        """Test that error is returned when filepath is None."""
        success, message = open_in_editor(None)
        assert success is False
        assert "No file path provided" in message

    def test_returns_error_when_filepath_empty(self) -> None:
        """Test that error is returned when filepath is empty string."""
        success, message = open_in_editor("")
        assert success is False
        assert "No file path provided" in message

    def test_returns_error_when_file_not_exists(self, tmp_path: Path) -> None:
        """Test that error is returned when file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.txt"
        success, message = open_in_editor(str(nonexistent))
        assert success is False
        assert "does not exist" in message

    def test_returns_error_when_path_is_directory(self, tmp_path: Path) -> None:
        """Test that error is returned when path is a directory."""
        success, message = open_in_editor(str(tmp_path))
        assert success is False
        assert "Not a regular file" in message

    def test_returns_error_when_file_not_readable(self, tmp_path: Path) -> None:
        """Test that error is returned when file is not readable."""
        test_file = tmp_path / "unreadable.txt"
        test_file.write_text("test")
        test_file.chmod(0o000)  # Remove all permissions
        try:
            success, message = open_in_editor(str(test_file))
            assert success is False
            assert "not readable" in message
        finally:
            test_file.chmod(0o644)  # Restore permissions for cleanup

    def test_returns_error_when_no_editor_available(self, tmp_path: Path) -> None:
        """Test that error is returned when no editor is available."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with patch("stoei.editor.get_editor") as mock_get_editor:
            mock_get_editor.return_value = None
            success, message = open_in_editor(str(test_file))
            assert success is False
            assert "No editor available" in message
            assert "$EDITOR" in message or "vim/nano" in message

    def test_opens_file_successfully(self, tmp_path: Path) -> None:
        """Test that file is opened successfully in editor."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with (
            patch("stoei.editor.get_editor") as mock_get_editor,
            patch("subprocess.run") as mock_run,
        ):
            mock_get_editor.return_value = "vim"
            mock_run.return_value = MagicMock(returncode=0)

            success, message = open_in_editor(str(test_file))

            assert success is True
            assert "Opened" in message
            assert "vim" in message
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == ["vim", str(test_file)]

    def test_returns_error_when_editor_fails(self, tmp_path: Path) -> None:
        """Test that error is returned when editor exits with non-zero code."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with (
            patch("stoei.editor.get_editor") as mock_get_editor,
            patch("subprocess.run") as mock_run,
        ):
            mock_get_editor.return_value = "vim"
            mock_run.return_value = MagicMock(returncode=1)

            success, message = open_in_editor(str(test_file))

            assert success is False
            assert "exited with code" in message

    def test_handles_file_not_found_error(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is handled."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with (
            patch("stoei.editor.get_editor") as mock_get_editor,
            patch("subprocess.run") as mock_run,
        ):
            mock_get_editor.return_value = "nonexistent_editor"
            mock_run.side_effect = FileNotFoundError("Editor not found")

            success, message = open_in_editor(str(test_file))

            assert success is False
            assert "not found" in message.lower()

    def test_handles_subprocess_error(self, tmp_path: Path) -> None:
        """Test that SubprocessError is handled."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with (
            patch("stoei.editor.get_editor") as mock_get_editor,
            patch("subprocess.run") as mock_run,
        ):
            mock_get_editor.return_value = "vim"
            mock_run.side_effect = subprocess.SubprocessError("Process error")

            success, message = open_in_editor(str(test_file))

            assert success is False
            assert "error" in message.lower()

    def test_handles_os_error(self, tmp_path: Path) -> None:
        """Test that OSError is handled."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with (
            patch("stoei.editor.get_editor") as mock_get_editor,
            patch("subprocess.run") as mock_run,
        ):
            mock_get_editor.return_value = "vim"
            mock_run.side_effect = OSError("OS error")

            success, message = open_in_editor(str(test_file))

            assert success is False
            assert "error" in message.lower()

    def test_always_returns_tuple(self, tmp_path: Path) -> None:
        """Test that function always returns a tuple, never None."""
        test_cases = [
            None,  # No filepath
            "",  # Empty filepath
            str(tmp_path / "nonexistent.txt"),  # Non-existent file
            str(tmp_path),  # Directory instead of file
        ]

        for filepath in test_cases:
            result = open_in_editor(filepath)
            assert isinstance(result, tuple), f"Expected tuple for {filepath}, got {type(result)}"
            assert len(result) == 2, f"Expected 2-tuple for {filepath}, got {len(result)}"
            assert isinstance(result[0], bool), f"First element should be bool for {filepath}"
            assert isinstance(result[1], str), f"Second element should be str for {filepath}"
