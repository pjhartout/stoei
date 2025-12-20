"""Tests for SLURM validation utilities."""

from unittest.mock import patch

import pytest
from stoei.slurm.validation import (
    ValidationError,
    get_current_username,
    resolve_executable,
    validate_job_id,
    validate_username,
)


class TestValidateUsername:
    """Tests for username validation."""

    def test_valid_usernames(self, valid_usernames: list[str]) -> None:
        for username in valid_usernames:
            assert validate_username(username) is True

    def test_invalid_usernames(self, invalid_usernames: list[str]) -> None:
        for username in invalid_usernames:
            with pytest.raises(ValidationError):
                validate_username(username)

    def test_username_with_numbers(self) -> None:
        assert validate_username("user123") is True

    def test_username_with_underscore(self) -> None:
        assert validate_username("test_user") is True

    def test_username_with_dot(self) -> None:
        assert validate_username("test.user") is True

    def test_username_with_hyphen(self) -> None:
        assert validate_username("test-user") is True


class TestValidateJobId:
    """Tests for job ID validation."""

    def test_valid_job_ids(self, valid_job_ids: list[str]) -> None:
        for job_id in valid_job_ids:
            assert validate_job_id(job_id) is True

    def test_invalid_job_ids(self, invalid_job_ids: list[str]) -> None:
        for job_id in invalid_job_ids:
            with pytest.raises(ValidationError):
                validate_job_id(job_id)

    def test_simple_numeric_job_id(self) -> None:
        assert validate_job_id("12345") is True

    def test_array_job_id(self) -> None:
        assert validate_job_id("12345_0") is True

    def test_array_job_id_large_index(self) -> None:
        assert validate_job_id("12345_999") is True

    def test_job_id_with_letters_raises(self) -> None:
        with pytest.raises(ValidationError):
            validate_job_id("abc123")

    def test_empty_job_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            validate_job_id("")


class TestGetCurrentUsername:
    """Tests for get_current_username function."""

    def test_returns_username(self) -> None:
        """Test that it returns a username."""
        username = get_current_username()
        assert isinstance(username, str)
        assert len(username) > 0

    def test_returns_validated_username(self) -> None:
        """Test that the returned username is valid."""
        username = get_current_username()
        # Should not raise
        validate_username(username)

    def test_handles_empty_username(self) -> None:
        """Test handling of empty username from getpass."""
        with (
            patch("stoei.slurm.validation.getpass.getuser", return_value=""),
            pytest.raises(ValidationError, match="Unable to determine"),
        ):
            get_current_username()


class TestResolveExecutable:
    """Tests for resolve_executable function."""

    def test_finds_python(self) -> None:
        """Test finding an executable that should exist."""
        # Python should always be available
        result = resolve_executable("python3")
        assert result is not None
        assert "python" in result

    def test_raises_for_nonexistent(self) -> None:
        """Test that nonexistent executable raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not found on PATH"):
            resolve_executable("definitely_nonexistent_command_12345")

    def test_returns_absolute_path(self) -> None:
        """Test that result is an absolute path."""
        from pathlib import Path

        result = resolve_executable("python3")
        assert Path(result).is_absolute()


class TestValidationError:
    """Tests for ValidationError class."""

    def test_is_exception(self) -> None:
        """Test that ValidationError is an Exception."""
        assert issubclass(ValidationError, Exception)

    def test_can_be_raised_with_message(self) -> None:
        """Test that ValidationError can be raised with a message."""
        error = ValidationError("Test error")
        with pytest.raises(ValidationError, match="Test error"):
            raise error

    def test_message_preserved(self) -> None:
        """Test that the error message is preserved."""
        error = ValidationError("Custom message")
        assert str(error) == "Custom message"
