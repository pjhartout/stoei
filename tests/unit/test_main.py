"""Tests for the __main__ entry point."""

import argparse
import os
from unittest.mock import patch

import pytest


class TestGetVersion:
    """Tests for the get_version() function."""

    def test_get_version_returns_string(self) -> None:
        """Test that get_version returns a string."""
        from stoei.__main__ import get_version

        version = get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_get_version_handles_error(self) -> None:
        """Test that get_version returns 'unknown' on error."""
        with patch("stoei.__main__.version", side_effect=Exception("Test error")):
            from stoei.__main__ import get_version

            version = get_version()
            assert version == "unknown"


class TestParseArgs:
    """Tests for the parse_args() function."""

    def test_parse_args_returns_namespace(self) -> None:
        """Test that parse_args returns an argparse.Namespace."""
        with patch("sys.argv", ["stoei"]):
            from stoei.__main__ import parse_args

            args = parse_args()
            assert isinstance(args, argparse.Namespace)

    def test_parse_args_accepts_refresh_interval(self) -> None:
        """Test that refresh interval argument is parsed."""
        with patch("sys.argv", ["stoei", "--refresh-interval", "2.5"]):
            from stoei.__main__ import parse_args

            args = parse_args()
            assert args.refresh_interval == pytest.approx(2.5)

    def test_parse_args_rejects_invalid_refresh_interval(self) -> None:
        """Test that invalid refresh interval exits."""
        with patch("sys.argv", ["stoei", "--refresh-interval", "0"]):
            from stoei.__main__ import parse_args

            with pytest.raises(SystemExit):
                parse_args()


class TestRunFunction:
    """Tests for the run() function."""

    def test_run_calls_main(self) -> None:
        """Test that run() calls the main() function."""
        with (
            patch("stoei.__main__.main") as mock_main,
            patch("stoei.__main__.parse_args", return_value=argparse.Namespace(refresh_interval=1.5)),
            patch("stoei.__main__.resolve_refresh_interval", return_value=1.5),
        ):
            from stoei.__main__ import run

            run()
            mock_main.assert_called_once_with(refresh_interval=pytest.approx(1.5))

    def test_run_handles_exception(self) -> None:
        """Test that run() handles exceptions and exits with code 1."""
        with (
            patch("stoei.__main__.main", side_effect=RuntimeError("Test error")),
            patch("stoei.__main__.parse_args", return_value=argparse.Namespace(refresh_interval=None)),
            patch("stoei.__main__.traceback.print_exc") as mock_traceback,
            patch("stoei.__main__.sys.exit") as mock_exit,
        ):
            from stoei.__main__ import run

            run()
            mock_traceback.assert_called_once()
            mock_exit.assert_called_once_with(1)

    def test_run_prints_traceback_on_error(self) -> None:
        """Test that run() prints standard traceback on error."""
        with (
            patch("stoei.__main__.main", side_effect=ValueError("Another error")),
            patch("stoei.__main__.parse_args", return_value=argparse.Namespace(refresh_interval=None)),
            patch("stoei.__main__.traceback.print_exc") as mock_traceback,
            patch("stoei.__main__.sys.exit"),
        ):
            from stoei.__main__ import run

            run()
            mock_traceback.assert_called_once()


class TestResolveRefreshInterval:
    """Tests for resolving refresh intervals."""

    def test_cli_value_takes_precedence(self) -> None:
        """CLI value should override env and default."""
        from stoei.__main__ import resolve_refresh_interval

        assert resolve_refresh_interval(3.0) == pytest.approx(3.0)

    def test_env_value_used_when_cli_missing(self) -> None:
        """Environment variable is used when CLI value missing."""
        from stoei.__main__ import ENV_REFRESH_INTERVAL, resolve_refresh_interval

        with patch.dict(os.environ, {ENV_REFRESH_INTERVAL: "4.5"}, clear=True):
            assert resolve_refresh_interval(None) == pytest.approx(4.5)

    def test_invalid_env_value_falls_back_to_default(self) -> None:
        """Invalid environment variable falls back to default."""
        from stoei.__main__ import ENV_REFRESH_INTERVAL, resolve_refresh_interval
        from stoei.app import REFRESH_INTERVAL

        with patch.dict(os.environ, {ENV_REFRESH_INTERVAL: "abc"}, clear=True):
            assert resolve_refresh_interval(None) == pytest.approx(REFRESH_INTERVAL)
