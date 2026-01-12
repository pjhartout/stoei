"""Tests for settings persistence."""

import json
from pathlib import Path

from stoei.settings import (
    DEFAULT_JOB_HISTORY_DAYS,
    DEFAULT_MAX_LOG_LINES,
    DEFAULT_REFRESH_INTERVAL,
    Settings,
    load_settings,
    save_settings,
)
from stoei.themes import DEFAULT_THEME_NAME, OC1_THEME_NAME


def test_load_settings_defaults_when_missing(tmp_path: Path, monkeypatch) -> None:
    """Defaults are returned when no settings file exists."""
    monkeypatch.setenv("STOEI_CONFIG_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.theme == DEFAULT_THEME_NAME
    assert settings.log_level == "WARNING"
    assert settings.max_log_lines == DEFAULT_MAX_LOG_LINES
    assert settings.refresh_interval == DEFAULT_REFRESH_INTERVAL
    assert settings.job_history_days == DEFAULT_JOB_HISTORY_DAYS


def test_save_settings_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """Settings are persisted and reloaded correctly."""
    monkeypatch.setenv("STOEI_CONFIG_DIR", str(tmp_path))
    original = Settings(
        theme=OC1_THEME_NAME,
        log_level="ERROR",
        max_log_lines=500,
        refresh_interval=10.0,
        job_history_days=14,
    )
    save_settings(original)
    loaded = load_settings()
    assert loaded == original


def test_load_settings_invalid_values(tmp_path: Path, monkeypatch) -> None:
    """Invalid settings fall back to defaults."""
    monkeypatch.setenv("STOEI_CONFIG_DIR", str(tmp_path))
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "theme": "unknown",
                "log_level": "NOPE",
                "max_log_lines": 10,
                "refresh_interval": 0.5,  # Below minimum
                "job_history_days": 100,  # Above maximum
            }
        )
    )
    settings = load_settings()
    assert settings.theme == DEFAULT_THEME_NAME
    assert settings.log_level == "WARNING"
    assert settings.max_log_lines == DEFAULT_MAX_LOG_LINES
    assert settings.refresh_interval == DEFAULT_REFRESH_INTERVAL
    assert settings.job_history_days == DEFAULT_JOB_HISTORY_DAYS


def test_load_settings_valid_refresh_interval(tmp_path: Path, monkeypatch) -> None:
    """Valid refresh interval values are loaded correctly."""
    monkeypatch.setenv("STOEI_CONFIG_DIR", str(tmp_path))
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"refresh_interval": 30.0}))
    settings = load_settings()
    assert settings.refresh_interval == 30.0


def test_load_settings_valid_job_history_days(tmp_path: Path, monkeypatch) -> None:
    """Valid job history days values are loaded correctly."""
    monkeypatch.setenv("STOEI_CONFIG_DIR", str(tmp_path))
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"job_history_days": 30}))
    settings = load_settings()
    assert settings.job_history_days == 30


def test_load_settings_refresh_interval_from_string(tmp_path: Path, monkeypatch) -> None:
    """Refresh interval can be parsed from string."""
    monkeypatch.setenv("STOEI_CONFIG_DIR", str(tmp_path))
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"refresh_interval": "15.5"}))
    settings = load_settings()
    assert settings.refresh_interval == 15.5


def test_load_settings_job_history_days_from_string(tmp_path: Path, monkeypatch) -> None:
    """Job history days can be parsed from string."""
    monkeypatch.setenv("STOEI_CONFIG_DIR", str(tmp_path))
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"job_history_days": "21"}))
    settings = load_settings()
    assert settings.job_history_days == 21
