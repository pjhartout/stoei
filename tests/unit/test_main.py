"""Tests for the __main__ entry point."""

import argparse
import os
from unittest.mock import MagicMock, patch


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


class TestRunFunction:
    """Tests for the run() function."""

    def test_run_calls_main(self) -> None:
        """Test that run() calls the main() function."""
        with (
            patch("stoei.__main__.main") as mock_main,
            patch("stoei.__main__._ensure_truecolor"),
            patch("stoei.__main__.parse_args", return_value=MagicMock()),
        ):
            from stoei.__main__ import run

            run()
            mock_main.assert_called_once()

    def test_run_handles_exception(self) -> None:
        """Test that run() handles exceptions and exits with code 1."""
        with (
            patch("stoei.__main__.main", side_effect=RuntimeError("Test error")),
            patch("stoei.__main__._ensure_truecolor"),
            patch("stoei.__main__.parse_args", return_value=MagicMock()),
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
            patch("stoei.__main__._ensure_truecolor"),
            patch("stoei.__main__.parse_args", return_value=MagicMock()),
            patch("stoei.__main__.traceback.print_exc") as mock_traceback,
            patch("stoei.__main__.sys.exit"),
        ):
            from stoei.__main__ import run

            run()
            mock_traceback.assert_called_once()


class TestEnsureTruecolor:
    """Tests for the _ensure_truecolor() function."""

    def test_sets_truecolor_when_not_set(self) -> None:
        """Test that COLORTERM is set to truecolor when not set."""
        from stoei.__main__ import _ensure_truecolor

        with patch.dict(os.environ, {"COLORTERM": ""}, clear=False):
            _ensure_truecolor()
            assert os.environ.get("COLORTERM") == "truecolor"

    def test_sets_truecolor_when_set_to_1(self) -> None:
        """Test that COLORTERM is set to truecolor when set to '1'."""
        from stoei.__main__ import _ensure_truecolor

        with patch.dict(os.environ, {"COLORTERM": "1"}, clear=False):
            _ensure_truecolor()
            assert os.environ.get("COLORTERM") == "truecolor"

    def test_preserves_truecolor_value(self) -> None:
        """Test that COLORTERM=truecolor is preserved."""
        from stoei.__main__ import _ensure_truecolor

        with patch.dict(os.environ, {"COLORTERM": "truecolor"}, clear=False):
            _ensure_truecolor()
            assert os.environ.get("COLORTERM") == "truecolor"

    def test_preserves_24bit_value(self) -> None:
        """Test that COLORTERM=24bit is preserved."""
        from stoei.__main__ import _ensure_truecolor

        with patch.dict(os.environ, {"COLORTERM": "24bit"}, clear=False):
            _ensure_truecolor()
            assert os.environ.get("COLORTERM") == "24bit"

    def test_case_insensitive_check(self) -> None:
        """Test that the check is case-insensitive."""
        from stoei.__main__ import _ensure_truecolor

        with patch.dict(os.environ, {"COLORTERM": "TRUECOLOR"}, clear=False):
            _ensure_truecolor()
            # Should preserve the original value
            assert os.environ.get("COLORTERM") == "TRUECOLOR"
