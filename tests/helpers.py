"""Shared helpers for the test suite."""

from stoei.colors import FALLBACK_COLORS


def has_color(result: str, color_name: str) -> bool:
    """Check if result contains a color (either name or hex value).

    Args:
        result: The formatted string to check.
        color_name: Semantic color name (success, warning, error) or ANSI name (green, yellow, red).

    Returns:
        True if the result contains a color markup.
    """
    ansi_to_semantic = {
        "green": "success",
        "yellow": "warning",
        "red": "error",
    }
    semantic_name = ansi_to_semantic.get(color_name, color_name)

    if f"[{color_name}]" in result:
        return True
    return bool(semantic_name in FALLBACK_COLORS and FALLBACK_COLORS[semantic_name] in result)
