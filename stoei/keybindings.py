"""Configurable keybinding system with vim/emacs presets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from stoei.logger import get_logger

logger = get_logger(__name__)


# Action names (used as keys in binding maps)
class Actions:
    """Constants for all bindable actions in the application."""

    # Global actions
    QUIT = "quit"
    HELP = "help"
    REFRESH = "refresh"
    SETTINGS = "settings"

    # Tab navigation
    TAB_JOBS = "tab_jobs"
    TAB_NODES = "tab_nodes"
    TAB_USERS = "tab_users"
    TAB_LOGS = "tab_logs"
    TAB_PREV = "tab_prev"
    TAB_NEXT = "tab_next"

    # Table navigation
    NAV_UP = "nav_up"
    NAV_DOWN = "nav_down"
    NAV_TOP = "nav_top"
    NAV_BOTTOM = "nav_bottom"
    NAV_PAGE_UP = "nav_page_up"
    NAV_PAGE_DOWN = "nav_page_down"
    SELECT = "select"

    # Table filtering and sorting
    FILTER_SHOW = "filter_show"
    FILTER_HIDE = "filter_hide"
    FILTER_CLEAR = "filter_clear"
    SORT_CYCLE = "sort_cycle"

    # Job actions
    JOB_INFO = "job_info"
    JOB_CANCEL = "cancel_job"

    # Log viewer
    LOG_TOP = "log_top"
    LOG_BOTTOM = "log_bottom"
    LOG_LINE_NUMBERS = "log_line_numbers"
    LOG_RELOAD = "log_reload"
    LOG_EDITOR = "log_editor"
    LOG_SEARCH = "log_search"

    # Dialog actions
    CLOSE = "close"
    CONFIRM = "confirm"
    CANCEL = "cancel"

    # Job detail actions
    OPEN_STDOUT = "open_stdout"
    OPEN_STDERR = "open_stderr"

    # Column width actions
    COLUMN_SELECT_NEXT = "column_select_next"
    COLUMN_SELECT_PREV = "column_select_prev"
    COLUMN_WIDTH_INCREASE = "column_width_increase"
    COLUMN_WIDTH_DECREASE = "column_width_decrease"
    COLUMN_WIDTH_RESET = "column_width_reset"


@dataclass
class KeyBinding:
    """A single keybinding configuration.

    Attributes:
        key: The key or key combination (e.g., "q", "ctrl+s", "escape").
        description: Human-readable description shown in footer/help.
        show_in_footer: Whether to show this binding in the footer.
    """

    key: str
    description: str
    show_in_footer: bool = False


@dataclass
class KeybindingPreset:
    """A complete set of keybindings for a mode (vim/emacs).

    Attributes:
        name: Preset name (e.g., "vim", "emacs").
        bindings: Mapping of action names to KeyBinding objects.
    """

    name: str
    bindings: dict[str, KeyBinding] = field(default_factory=dict)

    def get_key(self, action: str) -> str | None:
        """Get the key for an action.

        Args:
            action: The action name.

        Returns:
            The key string, or None if not bound.
        """
        binding = self.bindings.get(action)
        return binding.key if binding else None

    def get_binding(self, action: str) -> KeyBinding | None:
        """Get the full binding for an action.

        Args:
            action: The action name.

        Returns:
            The KeyBinding, or None if not bound.
        """
        return self.bindings.get(action)


def _create_vim_preset() -> KeybindingPreset:
    """Create the vim-style keybinding preset.

    Returns:
        KeybindingPreset with vim-style bindings.
    """
    return KeybindingPreset(
        name="vim",
        bindings={
            # Global (shown in footer)
            Actions.QUIT: KeyBinding("q", "Quit", show_in_footer=True),
            Actions.HELP: KeyBinding("question_mark", "Help", show_in_footer=True),
            Actions.REFRESH: KeyBinding("r", "Refresh", show_in_footer=True),
            Actions.SETTINGS: KeyBinding("s", "Settings", show_in_footer=True),
            # Tab navigation (hidden - use numbers)
            Actions.TAB_JOBS: KeyBinding("1", "Jobs Tab"),
            Actions.TAB_NODES: KeyBinding("2", "Nodes Tab"),
            Actions.TAB_USERS: KeyBinding("3", "Users Tab"),
            Actions.TAB_LOGS: KeyBinding("4", "Logs Tab"),
            Actions.TAB_PREV: KeyBinding("left", "Previous Tab"),
            Actions.TAB_NEXT: KeyBinding("right", "Next Tab"),
            # Table navigation (vim style: j/k)
            Actions.NAV_UP: KeyBinding("k", "Up"),
            Actions.NAV_DOWN: KeyBinding("j", "Down"),
            Actions.NAV_TOP: KeyBinding("g", "Go to top"),
            Actions.NAV_BOTTOM: KeyBinding("G", "Go to bottom"),
            Actions.NAV_PAGE_UP: KeyBinding("ctrl+u", "Page up"),
            Actions.NAV_PAGE_DOWN: KeyBinding("ctrl+d", "Page down"),
            Actions.SELECT: KeyBinding("enter", "Select"),
            # Filter/sort (vim style: / for search)
            Actions.FILTER_SHOW: KeyBinding("slash", "Filter", show_in_footer=True),
            Actions.FILTER_HIDE: KeyBinding("escape", "Hide filter"),
            Actions.FILTER_CLEAR: KeyBinding("escape", "Clear filter"),
            Actions.SORT_CYCLE: KeyBinding("o", "Sort", show_in_footer=True),
            # Job actions
            Actions.JOB_INFO: KeyBinding("i", "Job Info"),
            Actions.JOB_CANCEL: KeyBinding("c", "Cancel Job"),
            # Log viewer (vim style)
            Actions.LOG_TOP: KeyBinding("g", "Go to top"),
            Actions.LOG_BOTTOM: KeyBinding("G", "Go to bottom"),
            Actions.LOG_LINE_NUMBERS: KeyBinding("l", "Line numbers"),
            Actions.LOG_RELOAD: KeyBinding("r", "Reload"),
            Actions.LOG_EDITOR: KeyBinding("e", "Open in editor"),
            Actions.LOG_SEARCH: KeyBinding("slash", "Search"),
            # Dialog
            Actions.CLOSE: KeyBinding("escape", "Close"),
            Actions.CONFIRM: KeyBinding("enter", "Confirm"),
            Actions.CANCEL: KeyBinding("escape", "Cancel"),
            # Job detail
            Actions.OPEN_STDOUT: KeyBinding("o", "Open stdout"),
            Actions.OPEN_STDERR: KeyBinding("e", "Open stderr"),
            # Column width
            Actions.COLUMN_SELECT_NEXT: KeyBinding("bracketright", "Select next column"),
            Actions.COLUMN_SELECT_PREV: KeyBinding("bracketleft", "Select prev column"),
            Actions.COLUMN_WIDTH_INCREASE: KeyBinding("plus", "Increase column width"),
            Actions.COLUMN_WIDTH_DECREASE: KeyBinding("minus", "Decrease column width"),
            Actions.COLUMN_WIDTH_RESET: KeyBinding("0", "Reset column width"),
        },
    )


def _create_emacs_preset() -> KeybindingPreset:
    """Create the emacs-style keybinding preset.

    Returns:
        KeybindingPreset with emacs-style bindings.
    """
    return KeybindingPreset(
        name="emacs",
        bindings={
            # Global (shown in footer)
            Actions.QUIT: KeyBinding("ctrl+q", "Quit", show_in_footer=True),
            Actions.HELP: KeyBinding("ctrl+h", "Help", show_in_footer=True),
            Actions.REFRESH: KeyBinding("ctrl+r", "Refresh", show_in_footer=True),
            Actions.SETTINGS: KeyBinding("ctrl+comma", "Settings", show_in_footer=True),
            # Tab navigation
            Actions.TAB_JOBS: KeyBinding("1", "Jobs Tab"),
            Actions.TAB_NODES: KeyBinding("2", "Nodes Tab"),
            Actions.TAB_USERS: KeyBinding("3", "Users Tab"),
            Actions.TAB_LOGS: KeyBinding("4", "Logs Tab"),
            Actions.TAB_PREV: KeyBinding("left", "Previous Tab"),
            Actions.TAB_NEXT: KeyBinding("right", "Next Tab"),
            # Table navigation (emacs style: ctrl+n/p)
            Actions.NAV_UP: KeyBinding("ctrl+p", "Up"),
            Actions.NAV_DOWN: KeyBinding("ctrl+n", "Down"),
            Actions.NAV_TOP: KeyBinding("alt+less", "Go to top"),
            Actions.NAV_BOTTOM: KeyBinding("alt+greater", "Go to bottom"),
            Actions.NAV_PAGE_UP: KeyBinding("alt+v", "Page up"),
            Actions.NAV_PAGE_DOWN: KeyBinding("ctrl+v", "Page down"),
            Actions.SELECT: KeyBinding("enter", "Select"),
            # Filter/sort (emacs style: ctrl+s for search)
            Actions.FILTER_SHOW: KeyBinding("ctrl+s", "Filter", show_in_footer=True),
            Actions.FILTER_HIDE: KeyBinding("ctrl+g", "Hide filter"),
            Actions.FILTER_CLEAR: KeyBinding("ctrl+g", "Clear filter"),
            Actions.SORT_CYCLE: KeyBinding("ctrl+o", "Sort", show_in_footer=True),
            # Job actions
            Actions.JOB_INFO: KeyBinding("ctrl+i", "Job Info"),
            Actions.JOB_CANCEL: KeyBinding("ctrl+c", "Cancel Job"),
            # Log viewer (emacs style)
            Actions.LOG_TOP: KeyBinding("alt+less", "Go to top"),
            Actions.LOG_BOTTOM: KeyBinding("alt+greater", "Go to bottom"),
            Actions.LOG_LINE_NUMBERS: KeyBinding("ctrl+l", "Line numbers"),
            Actions.LOG_RELOAD: KeyBinding("ctrl+r", "Reload"),
            Actions.LOG_EDITOR: KeyBinding("ctrl+x_ctrl+e", "Open in editor"),
            Actions.LOG_SEARCH: KeyBinding("ctrl+s", "Search"),
            # Dialog
            Actions.CLOSE: KeyBinding("ctrl+g", "Close"),
            Actions.CONFIRM: KeyBinding("enter", "Confirm"),
            Actions.CANCEL: KeyBinding("ctrl+g", "Cancel"),
            # Job detail
            Actions.OPEN_STDOUT: KeyBinding("ctrl+o", "Open stdout"),
            Actions.OPEN_STDERR: KeyBinding("ctrl+e", "Open stderr"),
            # Column width
            Actions.COLUMN_SELECT_NEXT: KeyBinding("bracketright", "Select next column"),
            Actions.COLUMN_SELECT_PREV: KeyBinding("bracketleft", "Select prev column"),
            Actions.COLUMN_WIDTH_INCREASE: KeyBinding("plus", "Increase column width"),
            Actions.COLUMN_WIDTH_DECREASE: KeyBinding("minus", "Decrease column width"),
            Actions.COLUMN_WIDTH_RESET: KeyBinding("0", "Reset column width"),
        },
    )


# Preset registry
PRESETS: dict[str, KeybindingPreset] = {
    "vim": _create_vim_preset(),
    "emacs": _create_emacs_preset(),
}

DEFAULT_PRESET = "vim"


@dataclass
class KeybindingConfig:
    """User's keybinding configuration with optional overrides.

    Attributes:
        preset: Base preset name ("vim" or "emacs").
        overrides: User-defined overrides for specific actions.
    """

    preset: str = DEFAULT_PRESET
    overrides: dict[str, str] = field(default_factory=dict)

    # Class variable for valid presets
    VALID_PRESETS: ClassVar[tuple[str, ...]] = ("vim", "emacs")

    def get_key(self, action: str) -> str | None:
        """Get the key for an action, checking overrides first.

        Args:
            action: The action name.

        Returns:
            The key string, or None if not bound.
        """
        # Check overrides first
        if action in self.overrides:
            return self.overrides[action]

        # Fall back to preset
        preset = PRESETS.get(self.preset, PRESETS[DEFAULT_PRESET])
        return preset.get_key(action)

    def get_binding(self, action: str) -> KeyBinding | None:
        """Get the full binding for an action.

        Args:
            action: The action name.

        Returns:
            The KeyBinding (with override key if applicable), or None.
        """
        preset = PRESETS.get(self.preset, PRESETS[DEFAULT_PRESET])
        base_binding = preset.get_binding(action)

        if base_binding is None:
            return None

        # Apply override if exists
        if action in self.overrides:
            return KeyBinding(
                key=self.overrides[action],
                description=base_binding.description,
                show_in_footer=base_binding.show_in_footer,
            )

        return base_binding

    def get_all_bindings(self) -> dict[str, KeyBinding]:
        """Get all bindings with overrides applied.

        Returns:
            Dictionary of action names to KeyBinding objects.
        """
        preset = PRESETS.get(self.preset, PRESETS[DEFAULT_PRESET])
        result = dict(preset.bindings)

        # Apply overrides
        for action, key in self.overrides.items():
            if action in result:
                base = result[action]
                result[action] = KeyBinding(
                    key=key,
                    description=base.description,
                    show_in_footer=base.show_in_footer,
                )
            else:
                # New binding not in preset
                result[action] = KeyBinding(key=key, description=action)

        return result

    def to_dict(self) -> dict[str, object]:
        """Serialize to dictionary for storage.

        Returns:
            Dictionary representation.
        """
        return {
            "preset": self.preset,
            "overrides": self.overrides,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> KeybindingConfig:
        """Create from dictionary, with validation.

        Args:
            data: Dictionary with preset and optional overrides.

        Returns:
            KeybindingConfig instance.
        """
        if data is None:
            return cls()

        preset = data.get("preset", DEFAULT_PRESET)
        if not isinstance(preset, str) or preset not in cls.VALID_PRESETS:
            preset = DEFAULT_PRESET

        overrides_raw = data.get("overrides", {})
        overrides: dict[str, str] = {}
        if isinstance(overrides_raw, dict):
            for key, value in overrides_raw.items():
                if isinstance(key, str) and isinstance(value, str):
                    overrides[key] = value

        return cls(preset=preset, overrides=overrides)


def get_default_config(mode: str = "vim") -> KeybindingConfig:
    """Get a default keybinding configuration for a mode.

    Args:
        mode: The keybind mode ("vim" or "emacs").

    Returns:
        KeybindingConfig with the specified preset.
    """
    if mode not in KeybindingConfig.VALID_PRESETS:
        mode = DEFAULT_PRESET
    return KeybindingConfig(preset=mode)
