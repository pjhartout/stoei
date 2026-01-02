"""Validation utilities for SLURM-related inputs."""

import getpass
import re
import shutil

# Patterns for input validation
SAFE_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
SAFE_JOBID_PATTERN = re.compile(r"^[0-9]+(_[0-9]+)?$")  # Matches "12345" or "12345_0" for array jobs


class ValidationError(Exception):
    """Raised when input validation fails."""

    def __init__(self, message: str) -> None:
        """Initialize validation error with message.

        Args:
            message: Error message describing the validation failure.
        """
        super().__init__(message)
        self.message = message


class UsernameValidationError(ValidationError):
    """Raised when username validation fails."""

    EMPTY_MESSAGE = "Username cannot be empty"
    UNSAFE_MESSAGE_TEMPLATE = "Unsafe characters detected in username: {username!r}"


class JobIdValidationError(ValidationError):
    """Raised when job ID validation fails."""

    EMPTY_MESSAGE = "Job ID cannot be empty"
    INVALID_FORMAT_MESSAGE_TEMPLATE = "Invalid job ID format: {job_id!r}. Expected format: 12345 or 12345_0"


class UsernameRetrievalError(ValidationError):
    """Raised when username cannot be retrieved."""

    MESSAGE = "Unable to determine the current username"


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
        raise UsernameValidationError(UsernameValidationError.EMPTY_MESSAGE)
    if not SAFE_USERNAME_PATTERN.fullmatch(username):
        raise UsernameValidationError(UsernameValidationError.UNSAFE_MESSAGE_TEMPLATE.format(username=username))
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
        raise JobIdValidationError(JobIdValidationError.EMPTY_MESSAGE)
    if not SAFE_JOBID_PATTERN.fullmatch(job_id):
        raise JobIdValidationError(JobIdValidationError.INVALID_FORMAT_MESSAGE_TEMPLATE.format(job_id=job_id))
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
        raise UsernameRetrievalError(UsernameRetrievalError.MESSAGE)
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
        error_msg = f"Executable {executable!r} was not found on PATH"
        raise FileNotFoundError(error_msg)
    return resolved


def check_slurm_available() -> tuple[bool, str | None]:
    """Check if SLURM controller commands are available on the system.

    Checks for the presence of key SLURM commands (squeue, scontrol, sacct)
    that are required for stoei to function.

    Returns:
        Tuple of (is_available, error_message).
        is_available: True if SLURM commands are found, False otherwise.
        error_message: None if available, otherwise a descriptive error message.
    """
    required_commands = ["squeue", "scontrol", "sacct"]
    missing_commands = []

    for cmd in required_commands:
        if shutil.which(cmd) is None:
            missing_commands.append(cmd)

    if missing_commands:
        missing_str = ", ".join(missing_commands)
        return False, f"SLURM commands not found: {missing_str}. Please ensure SLURM is installed and accessible."

    return True, None
