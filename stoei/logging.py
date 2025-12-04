"""Logging configuration using loguru.

Logs are stored in the logs/ folder and kept for 1 week.
Output goes to both stdout and file.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import loguru

# Remove default handler
logger.remove()

# Define log directory
LOG_DIR = Path.home() / ".stoei" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Configure stdout handler with colors
STDOUT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
logger.add(
    sys.stdout,
    level="INFO",
    format=STDOUT_FORMAT,
    colorize=True,
)

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
