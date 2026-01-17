"""Persistent settings for the stoei TUI."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from stoei.keybindings import DEFAULT_PRESET, KeybindingConfig
from stoei.logger import get_logger
from stoei.themes import DEFAULT_THEME_NAME, THEME_LABELS

logger = get_logger(__name__)

LOG_LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
KEYBIND_MODES: tuple[str, ...] = ("vim", "emacs")
DEFAULT_KEYBIND_MODE = DEFAULT_PRESET
MIN_LOG_LINES = 200
DEFAULT_MAX_LOG_LINES = 2000

# Log viewer settings (for viewing job log files)
MIN_LOG_VIEWER_LINES = 500
MAX_LOG_VIEWER_LINES = 100000
DEFAULT_LOG_VIEWER_LINES = 10000

# Refresh interval settings (in seconds)
MIN_REFRESH_INTERVAL = 1.0
MAX_REFRESH_INTERVAL = 300.0
DEFAULT_REFRESH_INTERVAL = 5.0

# Job history settings (in days)
MIN_JOB_HISTORY_DAYS = 1
MAX_JOB_HISTORY_DAYS = 90
DEFAULT_JOB_HISTORY_DAYS = 7


@dataclass(frozen=True)
class Settings:
    """User-configurable settings stored on disk."""

    theme: str = DEFAULT_THEME_NAME
    log_level: str = "WARNING"
    max_log_lines: int = DEFAULT_MAX_LOG_LINES
    refresh_interval: float = DEFAULT_REFRESH_INTERVAL
    job_history_days: int = DEFAULT_JOB_HISTORY_DAYS
    log_viewer_lines: int = DEFAULT_LOG_VIEWER_LINES
    keybind_mode: str = DEFAULT_KEYBIND_MODE
    # Store keybinding overrides as tuple of (action, key) pairs (hashable for frozen dataclass)
    keybind_overrides: tuple[tuple[str, str], ...] = ()

    def get_keybindings(self) -> KeybindingConfig:
        """Get the keybinding configuration.

        Returns:
            KeybindingConfig with the current preset and overrides.
        """
        return KeybindingConfig(
            preset=self.keybind_mode,
            overrides=dict(self.keybind_overrides),
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Settings:
        """Create settings from a mapping, applying defaults for invalid values.

        Args:
            data: Mapping containing raw settings values.

        Returns:
            A Settings instance with validated values.
        """
        theme_value = _coerce_str(data.get("theme"))
        theme = theme_value if theme_value is not None and theme_value in THEME_LABELS else DEFAULT_THEME_NAME

        log_level_value = _coerce_str(data.get("log_level"))
        log_level = log_level_value if log_level_value is not None and log_level_value in LOG_LEVELS else "WARNING"

        max_log_lines = _coerce_int(data.get("max_log_lines"))
        if max_log_lines is None or max_log_lines < MIN_LOG_LINES:
            max_log_lines = DEFAULT_MAX_LOG_LINES

        refresh_interval = _coerce_float(data.get("refresh_interval"))
        if (
            refresh_interval is None
            or refresh_interval < MIN_REFRESH_INTERVAL
            or refresh_interval > MAX_REFRESH_INTERVAL
        ):
            refresh_interval = DEFAULT_REFRESH_INTERVAL

        job_history_days = _coerce_int(data.get("job_history_days"))
        if (
            job_history_days is None
            or job_history_days < MIN_JOB_HISTORY_DAYS
            or job_history_days > MAX_JOB_HISTORY_DAYS
        ):
            job_history_days = DEFAULT_JOB_HISTORY_DAYS

        log_viewer_lines = _coerce_int(data.get("log_viewer_lines"))
        if (
            log_viewer_lines is None
            or log_viewer_lines < MIN_LOG_VIEWER_LINES
            or log_viewer_lines > MAX_LOG_VIEWER_LINES
        ):
            log_viewer_lines = DEFAULT_LOG_VIEWER_LINES

        keybind_mode_value = _coerce_str(data.get("keybind_mode"))
        keybind_mode = (
            keybind_mode_value
            if keybind_mode_value is not None and keybind_mode_value in KEYBIND_MODES
            else DEFAULT_KEYBIND_MODE
        )

        # Parse keybind overrides
        keybind_overrides: tuple[tuple[str, str], ...] = ()
        raw_overrides = data.get("keybind_overrides")
        if isinstance(raw_overrides, dict):
            parsed: list[tuple[str, str]] = []
            for action, key in raw_overrides.items():
                if isinstance(action, str) and isinstance(key, str):
                    parsed.append((action, key))
            keybind_overrides = tuple(parsed)

        return cls(
            theme=theme,
            log_level=log_level,
            max_log_lines=max_log_lines,
            refresh_interval=refresh_interval,
            job_history_days=job_history_days,
            log_viewer_lines=log_viewer_lines,
            keybind_mode=keybind_mode,
            keybind_overrides=keybind_overrides,
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize settings to a dictionary.

        Returns:
            Dictionary representation of settings.
        """
        return {
            "theme": self.theme,
            "log_level": self.log_level,
            "max_log_lines": self.max_log_lines,
            "refresh_interval": self.refresh_interval,
            "job_history_days": self.job_history_days,
            "log_viewer_lines": self.log_viewer_lines,
            "keybind_mode": self.keybind_mode,
            "keybind_overrides": dict(self.keybind_overrides),
        }


def get_config_dir() -> Path:
    """Get the directory used for persistent configuration.

    Returns:
        Path to the configuration directory.
    """
    override_dir = os.environ.get("STOEI_CONFIG_DIR")
    if override_dir:
        return Path(override_dir).expanduser()

    base_dir = os.environ.get("XDG_CONFIG_HOME")
    if base_dir:
        return Path(base_dir).expanduser() / "stoei"

    return Path.home() / ".config" / "stoei"


def get_settings_path() -> Path:
    """Get the full path to the settings file.

    Returns:
        Path to the settings JSON file.
    """
    return get_config_dir() / "settings.json"


def load_settings() -> Settings:
    """Load settings from disk.

    Returns:
        Loaded settings, or defaults if none exist.
    """
    settings_path = get_settings_path()
    if not settings_path.exists():
        return Settings()

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning(f"Failed to parse settings file {settings_path}: {exc}")
        return Settings()
    except OSError as exc:
        logger.warning(f"Failed to read settings file {settings_path}: {exc}")
        return Settings()

    if not isinstance(raw, dict):
        logger.warning(f"Settings file {settings_path} contains invalid data")
        return Settings()

    return Settings.from_mapping(raw)


def save_settings(settings: Settings) -> None:
    """Persist settings to disk.

    Args:
        settings: Settings to persist.
    """
    settings_path = get_settings_path()
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"Failed to save settings to {settings_path}: {exc}")


def _coerce_str(value: object) -> str | None:
    """Coerce a value into a string if possible.

    Args:
        value: Raw value to coerce.

    Returns:
        String value or None.
    """
    if isinstance(value, str):
        return value
    return None


def _coerce_int(value: object) -> int | None:
    """Coerce a value into an integer if possible.

    Args:
        value: Raw value to coerce.

    Returns:
        Integer value or None.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: object) -> float | None:
    """Coerce a value into a float if possible.

    Args:
        value: Raw value to coerce.

    Returns:
        Float value or None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
