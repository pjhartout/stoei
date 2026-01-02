"""Tests for the __main__ entry point."""

from unittest.mock import patch


class TestRunFunction:
    """Tests for the run() function."""

    def test_run_calls_main(self) -> None:
        """Test that run() calls the main() function."""
        with patch("stoei.__main__.main") as mock_main:
            from stoei.__main__ import run

            run()
            mock_main.assert_called_once()

    def test_run_handles_exception(self) -> None:
        """Test that run() handles exceptions and exits with code 1."""
        with (
            patch("stoei.__main__.main", side_effect=RuntimeError("Test error")),
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
            patch("stoei.__main__.traceback.print_exc") as mock_traceback,
            patch("stoei.__main__.sys.exit"),
        ):
            from stoei.__main__ import run

            run()
            mock_traceback.assert_called_once()
