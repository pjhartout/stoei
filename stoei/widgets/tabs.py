"""Tab system widget."""

from typing import ClassVar

from textual import events
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from stoei.widgets.node_overview import NodeOverviewTab
from stoei.widgets.user_overview import UserOverviewTab


class TabSwitched(events.Message):
    """Message sent when a tab is switched."""

    def __init__(self, sender: Container, tab_name: str) -> None:
        """Initialize the TabSwitched message.

        Args:
            sender: The widget sending the message.
            tab_name: Name of the tab that was switched to.
        """
        super().__init__(sender)
        self.tab_name = tab_name


class TabContainer(Container):
    """Container widget with tab navigation."""

    DEFAULT_CSS: ClassVar[str] = """
    TabContainer {
        height: 100%;
        width: 100%;
    }

    #tab-header {
        height: auto;
        width: 100%;
        border-bottom: heavy ansi_blue;
        background: ansi_black;
    }

    #tab-buttons {
        height: auto;
        width: 100%;
    }

    .tab-button {
        width: 1fr;
        border: none;
        background: ansi_black;
        color: ansi_cyan;
    }

    .tab-button:hover {
        background: ansi_bright_black;
    }

    .tab-button.active {
        background: ansi_blue;
        color: ansi_bright_white;
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

    def compose(self) -> None:
        """Create the tab container layout."""
        with Container(id="tab-header"):
            with Horizontal(id="tab-buttons"):
                yield Button("📋 My Jobs", id="tab-jobs", classes="tab-button active")
                yield Button("🖥️  Nodes", id="tab-nodes", classes="tab-button")
                yield Button("👥 Users", id="tab-users", classes="tab-button")

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

    def switch_tab(self, tab_name: str) -> None:
        """Switch to a different tab.

        Args:
            tab_name: Name of the tab to switch to ('jobs', 'nodes', or 'users').
        """
        if tab_name == self._active_tab:
            return

        # Update button states
        for btn_id in ["tab-jobs", "tab-nodes", "tab-users"]:
            btn = self.query_one(f"#{btn_id}", Button)
            if btn_id == f"tab-{tab_name}":
                btn.add_class("active")
            else:
                btn.remove_class("active")

        self._active_tab = tab_name

        # Hide all tab contents in parent
        try:
            screen = self.screen
            for tab_id in ["tab-jobs-content", "tab-nodes-content", "tab-users-content"]:
                try:
                    tab_content = screen.query_one(f"#{tab_id}", Container)
                    tab_content.display = False
                except Exception:
                    pass

            # Show the active tab content
            active_tab_id = f"tab-{tab_name}-content"
            try:
                active_tab = screen.query_one(f"#{active_tab_id}", Container)
                active_tab.display = True
            except Exception:
                pass
        except Exception:
            pass

        # Post message for app to handle additional updates
        self.post_message(TabSwitched(self, tab_name))

    @property
    def active_tab(self) -> str:
        """Get the currently active tab name."""
        return self._active_tab


