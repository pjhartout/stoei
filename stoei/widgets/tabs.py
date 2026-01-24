"""Tab system widget."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.widgets import Button

from stoei.logger import get_logger

logger = get_logger(__name__)


class TabSwitched(Message):
    """Message sent when a tab is switched."""

    def __init__(self, tab_name: str) -> None:
        """Initialize the TabSwitched message.

        Args:
            tab_name: Name of the tab that was switched to.
        """
        super().__init__()
        self.tab_name = tab_name


class TabContainer(Container):
    """Container widget with tab navigation."""

    DEFAULT_CSS: ClassVar[str] = """
    TabContainer {
        height: auto;
        width: 100%;
    }

    #tab-header {
        height: 1;
        width: 100%;
        border-bottom: heavy $accent;
        background: $panel;
    }

    #tab-buttons {
        height: 1;
        width: 100%;
    }

    .tab-button {
        width: 1fr;
        height: 1;
        border: none;
        background: $panel;
        color: $accent;
        padding: 0;
    }

    .tab-button:hover {
        background: $surface;
    }

    .tab-button.active {
        background: $accent;
        color: $text-on-accent;
    }

    /* Compact tabs for narrow windows */
    .tab-button.compact {
        min-width: 8;
        padding: 0 1;
    }

    #tab-content {
        height: 1fr;
        width: 100%;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the TabContainer."""
        super().__init__(*args, **kwargs)
        self._active_tab: str = "jobs"
        self._tabs: dict[str, Container] = {}
        self._is_compact: bool = False
        self._tab_labels: dict[str, tuple[str, str]] = {
            "tab-jobs": ("📋 My Jobs", "Jobs"),
            "tab-nodes": ("🖥️  Nodes", "Nodes"),
            "tab-users": ("👥 Users", "Users"),
            "tab-priority": ("⚖️  Priority", "Prior"),
            "tab-logs": ("📝 Logs", "Logs"),
        }

    def compose(self) -> ComposeResult:
        """Create the tab container layout."""
        with Container(id="tab-header"), Horizontal(id="tab-buttons"):
            yield Button("📋 My Jobs", id="tab-jobs", classes="tab-button active")
            yield Button("🖥️  Nodes", id="tab-nodes", classes="tab-button")
            yield Button("👥 Users", id="tab-users", classes="tab-button")
            yield Button("⚖️  Priority", id="tab-priority", classes="tab-button")
            yield Button("📝 Logs", id="tab-logs", classes="tab-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle tab button presses.

        Args:
            event: The button press event.
        """
        if event.button.id == "tab-jobs":
            self.switch_tab("jobs")
        elif event.button.id == "tab-nodes":
            self.switch_tab("nodes")
        elif event.button.id == "tab-users":
            self.switch_tab("users")
        elif event.button.id == "tab-priority":
            self.switch_tab("priority")
        elif event.button.id == "tab-logs":
            self.switch_tab("logs")

    def switch_tab(self, tab_name: str) -> None:
        """Switch to a different tab.

        Args:
            tab_name: Name of the tab to switch to ('jobs', 'nodes', 'users', 'priority', or 'logs').
        """
        if tab_name == self._active_tab:
            return

        # Update button states
        for btn_id in ["tab-jobs", "tab-nodes", "tab-users", "tab-priority", "tab-logs"]:
            btn = self.query_one(f"#{btn_id}", Button)
            if btn_id == f"tab-{tab_name}":
                btn.add_class("active")
            else:
                btn.remove_class("active")

        self._active_tab = tab_name

        # Hide all tab contents in parent
        try:
            screen = self.screen
            tab_content_ids = [
                "tab-jobs-content",
                "tab-nodes-content",
                "tab-users-content",
                "tab-priority-content",
                "tab-logs-content",
            ]
            for tab_id in tab_content_ids:
                try:
                    tab_content = screen.query_one(f"#{tab_id}", Container)
                    tab_content.display = False
                except Exception as exc:
                    logger.debug(f"Failed to hide tab {tab_id}: {exc}")

            # Show the active tab content
            active_tab_id = f"tab-{tab_name}-content"
            try:
                active_tab = screen.query_one(f"#{active_tab_id}", Container)
                active_tab.display = True
            except Exception as exc:
                logger.debug(f"Failed to show tab {active_tab_id}: {exc}")
        except Exception as exc:
            logger.debug(f"Failed to switch tab UI: {exc}")

        # Post message for app to handle additional updates
        self.post_message(TabSwitched(tab_name))

    @property
    def active_tab(self) -> str:
        """Get the currently active tab name."""
        return self._active_tab

    def set_compact(self, compact: bool) -> None:
        """Set compact mode for tabs (shorter labels, no emojis).

        Args:
            compact: Whether to use compact mode.
        """
        if self._is_compact == compact:
            return

        self._is_compact = compact

        try:
            for btn_id, (full_label, compact_label) in self._tab_labels.items():
                btn = self.query_one(f"#{btn_id}", Button)
                if compact:
                    btn.label = compact_label
                    btn.add_class("compact")
                else:
                    btn.label = full_label
                    btn.remove_class("compact")
        except Exception as exc:
            logger.debug(f"Failed to update tab labels: {exc}")
