"""Tests for SLURM validation utilities."""

import pytest
from stoei.slurm.validation import (
    ValidationError,
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
