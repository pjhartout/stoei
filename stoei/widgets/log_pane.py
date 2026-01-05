"""Log pane widget for displaying application logs in the TUI."""

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.widgets import RichLog

if TYPE_CHECKING:
    pass


class LogPane(RichLog):
    """Widget to display application logs in real-time."""

    DEFAULT_CSS: ClassVar[str] = """
    LogPane {
        height: auto;
        width: 100%;
        scrollbar-size: 1 1;
    }
    """

    # Log level to color mapping
    LEVEL_COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "dim cyan",
        "INFO": "green",
        "SUCCESS": "bold green",
        "WARNING": "yellow",
        "ERROR": "bold red",
        "CRITICAL": "bold white on red",
    }

    def __init__(
        self,
        max_lines: int | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """Initialize the LogPane widget.

        Args:
            max_lines: Maximum number of log lines to retain (None for unlimited).
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled.
        """
        super().__init__(
            highlight=True,
            markup=True,
            wrap=True,
            max_lines=max_lines,
            auto_scroll=True,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )

    def add_log(self, level: str, message: str, timestamp: datetime | None = None) -> None:
        """Add a log entry to the pane.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR, etc.).
            message: The log message.
            timestamp: Optional timestamp (defaults to now).
        """
        if timestamp is None:
            timestamp = datetime.now()

        time_str = timestamp.strftime("%H:%M:%S")
        level_upper = level.upper()
        color = self.LEVEL_COLORS.get(level_upper, "white")

        # Build styled text
        log_text = Text()
        log_text.append(f"{time_str} ", style="dim")
        log_text.append(f"[{level_upper:^8}] ", style=color)
        log_text.append(message)

        self.write(log_text)

    def sink(self, message: object) -> None:
        """Loguru sink function to receive log messages.

        This method can be added to loguru as a sink to capture logs.

        Args:
            message: Loguru message object.
        """
        # Extract record from loguru message
        # Type narrowing: we know this is a LoguruMessage at runtime
        if not hasattr(message, "record"):
            return
        record = message.record  # type: ignore[union-attr]
        level_obj = record["level"]  # type: ignore[index]
        level = level_obj.name  # type: ignore[union-attr]
        msg = record["message"]  # type: ignore[index]
        timestamp_obj = record["time"]  # type: ignore[index]
        timestamp = timestamp_obj.replace(tzinfo=None)  # type: ignore[union-attr]

        # Call from app thread if available
        try:
            self.app.call_from_thread(self.add_log, level, str(msg), timestamp)
        except RuntimeError:
            # Not in a thread context, call directly
            self.add_log(level, str(msg), timestamp)
