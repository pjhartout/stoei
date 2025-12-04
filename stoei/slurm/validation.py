"""Validation utilities for SLURM-related inputs."""

import getpass
import re
import shutil

# Patterns for input validation
SAFE_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_JOBID_PATTERN = re.compile(r"^[0-9]+(_[0-9]+)?$")  # Matches "12345" or "12345_0" for array jobs


class ValidationError(Exception):
    """Raised when input validation fails."""


def validate_username(username: str) -> bool:
    """Validate that a username is safe for CLI usage.

    Args:
        username: The username to validate.

    Returns:
        True if the username is safe.

    Raises:
        ValidationError: If the username contains unsafe characters.
    """
    if not username:
        raise ValidationError("Username cannot be empty")
    if not SAFE_USERNAME_PATTERN.fullmatch(username):
        raise ValidationError(f"Unsafe characters detected in username: {username!r}")
    return True


def validate_job_id(job_id: str) -> bool:
    """Validate that a job ID has a safe format.

    Args:
        job_id: The job ID to validate.

    Returns:
        True if the job ID is safe.

    Raises:
        ValidationError: If the job ID format is invalid.
    """
    if not job_id:
        raise ValidationError("Job ID cannot be empty")
    if not SAFE_JOBID_PATTERN.fullmatch(job_id):
        raise ValidationError(f"Invalid job ID format: {job_id!r}. Expected format: 12345 or 12345_0")
    return True


def get_current_username() -> str:
    """Return a sanitized username suitable for CLI usage.

    Returns:
        The current user's username.

    Raises:
        ValidationError: If the username cannot be determined or is unsafe.
    """
    username = getpass.getuser()
    if not username:
        raise ValidationError("Unable to determine the current username")
    validate_username(username)
    return username


def resolve_executable(executable: str) -> str:
    """Return the absolute path to an executable.

    Args:
        executable: The name of the executable to find.

    Returns:
        The absolute path to the executable.

    Raises:
        FileNotFoundError: If the executable is not found on PATH.
    """
    resolved = shutil.which(executable)
    if resolved is None:
        raise FileNotFoundError(f"Executable {executable!r} was not found on PATH")
    return resolved
