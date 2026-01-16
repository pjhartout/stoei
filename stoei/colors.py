"""Theme-aware color utilities for Rich markup.

This module provides functions to get consistent hex colors from the current
theme for use in Rich markup. This ensures colors look the same regardless
of terminal settings or tmux configuration.

Usage:
    from stoei.colors import get_theme_colors, ThemeColors

    # In a widget or app method:
    colors = get_theme_colors(self.app)
    markup = f"[{colors.success}]Success![/{colors.success}]"
    bold_error = f"[bold {colors.error}]Error![/bold {colors.error}]"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


# Fallback colors when theme is not available (using sensible defaults)
FALLBACK_COLORS = {
    "primary": "#88c0d0",
    "accent": "#88c0d0",
    "secondary": "#2e3440",
    "success": "#a3be8c",
    "warning": "#ebcb8b",
    "error": "#bf616a",
    "foreground": "#e5e9f0",
    "background": "#2e3440",
    "surface": "#3b4252",
    "panel": "#2e3440",
    "text_muted": "#d8dee9",
    "border": "#4c566a",
}


@dataclass(frozen=True)
class ThemeColors:
    """Container for theme colors with semantic names.

    All colors are hex strings like '#a3be8c'.
    Use these directly in Rich markup: f"[{colors.success}]text[/{colors.success}]"
    """

    # Semantic colors
    success: str
    warning: str
    error: str
    primary: str
    accent: str
    secondary: str

    # Text colors
    foreground: str
    text_muted: str

    # Background colors
    background: str
    surface: str
    panel: str

    # UI colors
    border: str

    def state_color(self, state: str) -> str:
        """Get color for a job/node state.

        Args:
            state: State string (e.g., 'RUNNING', 'PENDING', 'FAILED').

        Returns:
            Hex color string for the state.
        """
        state_upper = state.upper().split()[0]  # Handle "RUNNING by 12345" etc.

        state_map = {
            # Running/active states -> success (green)
            "RUNNING": self.success,
            "COMPLETING": self.success,
            "COMPLETED": self.success,
            # Pending/waiting states -> warning (yellow)
            "PENDING": self.warning,
            "PREEMPTED": self.warning,
            "SUSPENDED": self.warning,
            "REQUEUED": self.warning,
            # Error/failure states -> error (red)
            "FAILED": self.error,
            "TIMEOUT": self.error,
            "NODE_FAIL": self.error,
            "OUT_OF_MEMORY": self.error,
            # Cancelled -> muted
            "CANCELLED": self.text_muted,
            # Node states
            "IDLE": self.success,
            "ALLOCATED": self.warning,
            "MIXED": self.warning,
            "DOWN": self.error,
            "DRAIN": self.error,
            "DRAINED": self.error,
        }

        return state_map.get(state_upper, self.foreground)

    def pct_color(
        self,
        pct: float,
        *,
        high_threshold: float = 90.0,
        mid_threshold: float = 70.0,
        invert: bool = False,
    ) -> str:
        """Get color for a percentage value.

        Args:
            pct: Percentage value (0-100).
            high_threshold: Threshold for high/critical (default 90%).
            mid_threshold: Threshold for medium/warning (default 70%).
            invert: If True, high values are good (green), low are bad (red).
                   Default False means high values are bad (red).

        Returns:
            Hex color string based on the percentage.
        """
        if invert:
            # High is good (e.g., free resources percentage)
            if pct >= high_threshold:
                return self.success
            if pct >= mid_threshold:
                return self.warning
            return self.error
        else:
            # High is bad (e.g., usage percentage)
            if pct >= high_threshold:
                return self.error
            if pct >= mid_threshold:
                return self.warning
            return self.success

    def level_color(self, level: str) -> str:
        """Get color for a log level.

        Args:
            level: Log level string (DEBUG, INFO, WARNING, ERROR, etc.).

        Returns:
            Hex color string for the log level.
        """
        level_upper = level.upper()

        level_map = {
            "DEBUG": self.text_muted,
            "INFO": self.success,
            "SUCCESS": self.success,
            "WARNING": self.warning,
            "ERROR": self.error,
            "CRITICAL": self.error,
        }

        return level_map.get(level_upper, self.foreground)


def get_theme_colors(app: Any) -> ThemeColors:
    """Get theme colors from the current application theme.

    Args:
        app: The Textual App instance, or None for fallback colors.

    Returns:
        ThemeColors instance with hex colors from the current theme.
    """
    if app is None:
        return ThemeColors(
            success=FALLBACK_COLORS["success"],
            warning=FALLBACK_COLORS["warning"],
            error=FALLBACK_COLORS["error"],
            primary=FALLBACK_COLORS["primary"],
            accent=FALLBACK_COLORS["accent"],
            secondary=FALLBACK_COLORS["secondary"],
            foreground=FALLBACK_COLORS["foreground"],
            text_muted=FALLBACK_COLORS["text_muted"],
            background=FALLBACK_COLORS["background"],
            surface=FALLBACK_COLORS["surface"],
            panel=FALLBACK_COLORS["panel"],
            border=FALLBACK_COLORS["border"],
        )

    theme = app.current_theme

    # Get colors from theme, with fallbacks
    def get_color(attr: str, fallback_key: str) -> str:
        """Get color from theme attribute or fallback."""
        value = getattr(theme, attr, None)
        if value is not None:
            # Handle both Color objects and string values
            if hasattr(value, "hex"):
                return value.hex
            # Already a string (hex color)
            return str(value)
        return FALLBACK_COLORS[fallback_key]

    def get_variable(name: str, fallback_key: str) -> str:
        """Get color from theme variables or fallback."""
        variables = getattr(theme, "variables", {}) or {}
        value = variables.get(name)
        if value is not None:
            # Variables are already strings
            return str(value)
        return FALLBACK_COLORS[fallback_key]

    return ThemeColors(
        success=get_color("success", "success"),
        warning=get_color("warning", "warning"),
        error=get_color("error", "error"),
        primary=get_color("primary", "primary"),
        accent=get_color("accent", "accent"),
        secondary=get_color("secondary", "secondary"),
        foreground=get_color("foreground", "foreground"),
        text_muted=get_variable("text-muted", "text_muted"),
        background=get_color("background", "background"),
        surface=get_color("surface", "surface"),
        panel=get_color("panel", "panel"),
        border=get_variable("border", "border"),
    )
