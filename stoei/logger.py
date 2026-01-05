"""Logging configuration using loguru.

Logs are stored in the logs/ folder and kept for 1 week.
Output goes to both stdout and file.
"""

import sys
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

# Define log directory
LOG_DIR = Path.home() / ".stoei" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Configure stdout handler with colors (only when not in TUI mode)
STDOUT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


class _LoggingState:
    """Internal state tracker for logging configuration."""

    def __init__(self) -> None:
        """Initialize logging state with stdout handler."""
        self.stdout_handler_id: int | None = logger.add(
            sys.stdout,
            level="INFO",
            format=STDOUT_FORMAT,
            colorize=True,
        )


_state = _LoggingState()

# Configure file handler with rotation and retention
logger.add(
    LOG_DIR / "stoei_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    rotation="00:00",  # New file at midnight
    retention="1 week",  # Keep logs for 1 week
    compression="gz",  # Compress old logs
)


def get_logger(name: str) -> "loguru.Logger":
    """Get a logger instance with the given name.

    Args:
        name: The name for the logger (typically __name__).

    Returns:
        A configured logger instance.
    """
    return logger.bind(name=name)


def add_tui_sink(sink_func: Callable[[object], None], level: str = "INFO") -> int:
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
    """Remove the TUI sink and restore stdout logging.

    Args:
        sink_id: The sink ID returned by add_tui_sink.
    """
    logger.remove(sink_id)

    # Restore stdout handler
    if _state.stdout_handler_id is None:
        _state.stdout_handler_id = logger.add(
            sys.stdout,
            level="INFO",
            format=STDOUT_FORMAT,
            colorize=True,
        )
