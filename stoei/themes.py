"""Theme definitions for the stoei TUI."""

from __future__ import annotations

from dataclasses import dataclass

from textual.theme import Theme

TERMINAL_THEME_NAME = "textual-ansi"

OC1_THEME_NAME = "oc-1"
TOKYONIGHT_THEME_NAME = "tokyonight"
DRACULA_THEME_NAME = "dracula"
MONOKAI_THEME_NAME = "monokai"
SOLARIZED_THEME_NAME = "solarized"
NORD_THEME_NAME = "nord"
CATPPUCCIN_THEME_NAME = "catppuccin"
AYU_THEME_NAME = "ayu"
ONEDARKPRO_THEME_NAME = "onedarkpro"
SHADESOFPURPLE_THEME_NAME = "shadesofpurple"
NIGHTOWL_THEME_NAME = "nightowl"
VESPER_THEME_NAME = "vesper"

DEFAULT_THEME_NAME = OC1_THEME_NAME


@dataclass(frozen=True)
class OpencodeThemePalette:
    """Palette values derived from OpenCode themes."""

    name: str
    theme_id: str
    primary: str
    secondary: str
    accent: str
    warning: str
    error: str
    success: str
    background_weak: str
    background_strong: str
    background_stronger: str
    border: str
    border_muted: str
    text_base: str
    text_muted: str
    text_strong: str


OPENCODE_THEME_PALETTES = (
    OpencodeThemePalette(
        name="OC-1",
        theme_id=OC1_THEME_NAME,
        primary="#fab283",
        secondary="#716c6b",
        accent="#034cff",
        warning="#fcd53a",
        error="#fc533a",
        success="#12c905",
        background_weak="#1c1717",
        background_strong="#151313",
        background_stronger="#191515",
        border="#3a3333",
        border_muted="#2a2424",
        text_base="#f5f5f5",
        text_muted="#b8b0b0",
        text_strong="#ffffff",
    ),
    OpencodeThemePalette(
        name="Tokyo Night",
        theme_id=TOKYONIGHT_THEME_NAME,
        primary="#7aa2f7",
        secondary="#1a1b26",
        accent="#7aa2f7",
        warning="#e0af68",
        error="#f7768e",
        success="#9ece6a",
        background_weak="#111428",
        background_strong="#101324",
        background_stronger="#13172a",
        border="#3a3e57",
        border_muted="#25283b",
        text_base="#c0caf5",
        text_muted="#7a88cf",
        text_strong="#eaeaff",
    ),
    OpencodeThemePalette(
        name="Dracula",
        theme_id=DRACULA_THEME_NAME,
        primary="#bd93f9",
        secondary="#1d1e28",
        accent="#bd93f9",
        warning="#ffb86c",
        error="#ff5555",
        success="#50fa7b",
        background_weak="#181926",
        background_strong="#161722",
        background_stronger="#191a26",
        border="#3f415a",
        border_muted="#2d2f3c",
        text_base="#f8f8f2",
        text_muted="#b6b9e4",
        text_strong="#ffffff",
    ),
    OpencodeThemePalette(
        name="Monokai",
        theme_id=MONOKAI_THEME_NAME,
        primary="#ae81ff",
        secondary="#272822",
        accent="#ae81ff",
        warning="#fd971f",
        error="#f92672",
        success="#a6e22e",
        background_weak="#27281f",
        background_strong="#25261f",
        background_stronger="#292a23",
        border="#494a3a",
        border_muted="#343528",
        text_base="#f8f8f2",
        text_muted="#c5c5c0",
        text_strong="#ffffff",
    ),
    OpencodeThemePalette(
        name="Solarized",
        theme_id=SOLARIZED_THEME_NAME,
        primary="#6c71c4",
        secondary="#002b36",
        accent="#6c71c4",
        warning="#b58900",
        error="#dc322f",
        success="#859900",
        background_weak="#022733",
        background_strong="#01222b",
        background_stronger="#032830",
        border="#31505b",
        border_muted="#20373f",
        text_base="#93a1a1",
        text_muted="#6c7f80",
        text_strong="#fdf6e3",
    ),
    OpencodeThemePalette(
        name="Nord",
        theme_id=NORD_THEME_NAME,
        primary="#88c0d0",  # nord8 - bright primary accent (ice)
        secondary="#2e3440",  # nord0 - origin polar night
        accent="#88c0d0",  # nord8 - bright primary accent
        warning="#ebcb8b",  # nord13 - yellow (official warning color)
        error="#bf616a",  # nord11 - red
        success="#a3be8c",  # nord14 - green
        background_weak="#3b4252",  # nord1 - brighter shade
        background_strong="#2e3440",  # nord0 - origin polar night
        background_stronger="#2e3440",  # nord0 - origin polar night
        border="#4c566a",  # nord3 - brightest polar night shade
        border_muted="#434c5e",  # nord2 - even brighter shade
        text_base="#e5e9f0",  # nord5 - brighter snow storm shade
        text_muted="#d8dee9",  # nord4 - origin snow storm
        text_strong="#eceff4",  # nord6 - brightest snow storm
    ),
    OpencodeThemePalette(
        name="Catppuccin",
        theme_id=CATPPUCCIN_THEME_NAME,
        primary="#b4befe",
        secondary="#1e1e2e",
        accent="#b4befe",
        warning="#f4b8e4",
        error="#f38ba8",
        success="#a6d189",
        background_weak="#211f31",
        background_strong="#1c1c29",
        background_stronger="#191926",
        border="#4a4763",
        border_muted="#35324a",
        text_base="#cdd6f4",
        text_muted="#a6adc8",
        text_strong="#f4f2ff",
    ),
    OpencodeThemePalette(
        name="Ayu",
        theme_id=AYU_THEME_NAME,
        primary="#39bae6",
        secondary="#0f1419",
        accent="#39bae6",
        warning="#ebb062",
        error="#ff8f77",
        success="#7fd962",
        background_weak="#121920",
        background_strong="#0d1116",
        background_stronger="#0a0e13",
        border="#3d4555",
        border_muted="#262c34",
        text_base="#ced0d6",
        text_muted="#8f9aa5",
        text_strong="#f6f7f9",
    ),
    OpencodeThemePalette(
        name="One Dark Pro",
        theme_id=ONEDARKPRO_THEME_NAME,
        primary="#61afef",
        secondary="#1e222a",
        accent="#61afef",
        warning="#e5c07b",
        error="#e06c75",
        success="#98c379",
        background_weak="#212631",
        background_strong="#1b1f27",
        background_stronger="#171b23",
        border="#4a5164",
        border_muted="#323848",
        text_base="#abb2bf",
        text_muted="#818899",
        text_strong="#f6f7fb",
    ),
    OpencodeThemePalette(
        name="Shades of Purple",
        theme_id=SHADESOFPURPLE_THEME_NAME,
        primary="#c792ff",
        secondary="#1a102b",
        accent="#c792ff",
        warning="#ffd580",
        error="#ff7ac6",
        success="#7be0b0",
        background_weak="#1f1434",
        background_strong="#1c122f",
        background_stronger="#170e26",
        border="#4d3a73",
        border_muted="#352552",
        text_base="#f5f0ff",
        text_muted="#c9b6ff",
        text_strong="#ffffff",
    ),
    OpencodeThemePalette(
        name="Night Owl",
        theme_id=NIGHTOWL_THEME_NAME,
        primary="#82aaff",
        secondary="#011627",
        accent="#82aaff",
        warning="#ecc48d",
        error="#ef5350",
        success="#c5e478",
        background_weak="#0b253a",
        background_strong="#001122",
        background_stronger="#000c17",
        border="#3a5a75",
        border_muted="#1d3b53",
        text_base="#d6deeb",
        text_muted="#5f7e97",
        text_strong="#ffffff",
    ),
    OpencodeThemePalette(
        name="Vesper",
        theme_id=VESPER_THEME_NAME,
        primary="#ffc799",
        secondary="#101010",
        accent="#ffc799",
        warning="#ffc799",
        error="#ff8080",
        success="#99ffe4",
        background_weak="#141414",
        background_strong="#0c0c0c",
        background_stronger="#080808",
        border="#282828",
        border_muted="#1c1c1c",
        text_base="#ffffff",
        text_muted="#a0a0a0",
        text_strong="#ffffff",
    ),
)


def _is_hex_color(value: str) -> bool:
    """Check if a string is a hex color.

    Args:
        value: Value to check.

    Returns:
        True if value is a hex color string.
    """
    return value.startswith("#") and len(value) in {4, 7}


def _normalize_color(value: str, fallback: str) -> str:
    """Normalize a color value to a hex string.

    Args:
        value: Candidate color value.
        fallback: Fallback color when value is not a hex color.

    Returns:
        Hex color string.
    """
    return value if _is_hex_color(value) else fallback


def _theme_from_palette(palette: OpencodeThemePalette) -> Theme:
    """Build a Textual Theme from an OpenCode palette.

    Args:
        palette: OpenCode palette data.

    Returns:
        A Textual Theme instance.
    """
    background = _normalize_color(palette.background_strong, "#0c0c0e")
    surface = _normalize_color(palette.background_weak, background)
    panel = _normalize_color(palette.background_stronger, surface)
    foreground = _normalize_color(palette.text_base, "#e0e0e0")
    text_muted = _normalize_color(palette.text_muted, foreground)
    text_strong = _normalize_color(palette.text_strong, foreground)
    border = _normalize_color(palette.border, surface)
    border_muted = _normalize_color(palette.border_muted, surface)

    return Theme(
        name=palette.theme_id,
        primary=palette.primary,
        secondary=palette.secondary,
        accent=palette.accent,
        warning=palette.warning,
        error=palette.error,
        success=palette.success,
        foreground=foreground,
        background=background,
        surface=surface,
        panel=panel,
        dark=True,
        variables={
            "border": border,
            "border-muted": border_muted,
            "text-muted": text_muted,
            "text-subtle": text_muted,
            "accent-hover": palette.accent,
            "accent-active": palette.accent,
            "text-on-accent": text_strong,
            "text-on-error": text_strong,
            "text-on-warning": text_strong,
            "text-on-success": text_strong,
        },
    )


REGISTERED_THEMES = tuple(_theme_from_palette(palette) for palette in OPENCODE_THEME_PALETTES)

THEME_LABELS: dict[str, str] = {
    TERMINAL_THEME_NAME: "Terminal (ANSI)",
    **{palette.theme_id: palette.name for palette in OPENCODE_THEME_PALETTES},
}
