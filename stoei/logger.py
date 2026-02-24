"""Logging configuration using loguru.

Logs are stored in the logs/ folder and kept for 1 week.
Output goes to file only by default (to avoid interfering with TUI).
"""

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from loguru import logger

if TYPE_CHECKING:
    import loguru


class LoguruLevel(Protocol):
    """Protocol for loguru level object."""

    name: str


class LoguruRecord(Protocol):
    """Protocol for loguru record dictionary."""

    def __getitem__(self, key: str) -> object:
        """Allow dictionary-like access to record fields."""
        ...

    @property
    def level(self) -> LoguruLevel:
        """Log level object."""
        ...

    @property
    def message(self) -> str:
        """Log message string."""
        ...

    @property
    def time(self) -> datetime:
        """Log timestamp."""
        ...


class LoguruMessage(Protocol):
    """Protocol for loguru message object passed to sinks."""

    @property
    def record(self) -> LoguruRecord:
        """Access the log record."""
        ...


# Remove default handler
logger.remove()

# Define log directory (default ~/.local/share/stoei/logs, overridable via STOEI_LOG_DIR)
_default_log_dir = Path.home() / ".local" / "share" / "stoei" / "logs"
LOG_DIR = Path(os.environ.get("STOEI_LOG_DIR", str(_default_log_dir))).expanduser().resolve()
LOG_DIR.mkdir(parents=True, exist_ok=True)


class _LoggingState:
    """Internal state tracker for logging configuration.

    Note: stdout handler is NOT added by default to avoid interfering with TUI.
    Logs go to file only during normal operation.
    """

    def __init__(self) -> None:
        """Initialize logging state without stdout handler."""
        self.stdout_handler_id: int | None = None


_state = _LoggingState()

# Configure file handler with rotation and retention
logger.add(
    LOG_DIR / "stoei_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    rotation="00:00",  # New file at midnight
    retention="1 week",  # Keep logs for 1 week
    compression="gz",  # Compress old logs
    backtrace=True,
    diagnose=False,
)


def get_logger(name: str) -> "loguru.Logger":
    """Get a logger instance with the given name.

    Args:
        name: The name for the logger (typically __name__).

    Returns:
        A configured logger instance.
    """
    return logger.bind(name=name)


def add_tui_sink(sink_func: Callable[[object], None], level: str = "WARNING") -> int:
    """Add a TUI sink for displaying logs in the application.

    This also removes the stdout handler to prevent logs from interfering
    with the TUI display.

    Args:
        sink_func: A callable that accepts loguru message objects.
        level: Minimum log level for the TUI sink.

    Returns:
        The sink ID that can be used to remove the sink later.
    """
    # Remove stdout handler to prevent it from interfering with TUI
    if _state.stdout_handler_id is not None:
        logger.remove(_state.stdout_handler_id)
        _state.stdout_handler_id = None

    # Add the TUI sink
    return logger.add(sink_func, level=level, format="{message}")


def remove_tui_sink(sink_id: int) -> None:
    """Remove the TUI sink.

    Note: stdout logging is NOT restored to keep terminal clean.

    Args:
        sink_id: The sink ID returned by add_tui_sink.
    """
    logger.remove(sink_id)
