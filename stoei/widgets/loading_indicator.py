"""Small loading indicator widget."""

from typing import ClassVar

from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static


class LoadingIndicator(Static):
    """A small loading indicator widget that shows a spinner."""

    DEFAULT_CSS: ClassVar[str] = """
    LoadingIndicator {
        width: 14;
        height: 1;
        content-align: center middle;
        color: $accent;
    }
    """

    SPINNER_FRAMES: ClassVar[tuple[str, ...]] = (
        "⠋",
        "⠙",
        "⠹",
        "⠸",
        "⠼",
        "⠴",
        "⠦",
        "⠧",
        "⠇",
        "⠏",
    )

    loading = reactive(False)

    def __init__(self, **kwargs) -> None:
        """Initialize the loading indicator.

        Args:
            **kwargs: Keyword arguments for the widget.
        """
        super().__init__("", **kwargs)
        self._spinner_frame = 0
        self._timer: Timer | None = None

    def watch_loading(self, loading: bool) -> None:
        """Watch the loading reactive."""
        if loading:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        """Start the spinner."""
        if self._timer is None:
            self._timer = self.set_interval(0.1, self._animate)  # type: ignore
            self.display = True
            self.update(f"{self.SPINNER_FRAMES[0]} Working...")

    def _stop(self) -> None:
        """Stop the spinner."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.update("")
        self.display = False

    def _animate(self) -> None:
        """Animate the spinner."""
        self._spinner_frame = (self._spinner_frame + 1) % len(self.SPINNER_FRAMES)
        self.update(f"{self.SPINNER_FRAMES[self._spinner_frame]} Working...")
