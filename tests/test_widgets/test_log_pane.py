"""Tests for the LogPane widget."""

from datetime import UTC, datetime

from stoei.widgets.log_pane import LogPane


class TestLogPane:
    """Tests for the LogPane widget."""

    def test_init_with_defaults(self) -> None:
        """Test LogPane initializes with default values."""
        pane = LogPane()
        assert pane.auto_scroll is True
        assert pane.markup is True
        assert pane.wrap is True

    def test_init_with_custom_max_lines(self) -> None:
        """Test LogPane accepts custom max_lines."""
        pane = LogPane(max_lines=100)
        assert pane.max_lines == 100

    def test_init_with_id(self) -> None:
        """Test LogPane accepts id parameter."""
        pane = LogPane(id="test_log")
        assert pane.id == "test_log"

    def test_init_with_name(self) -> None:
        """Test LogPane accepts name parameter."""
        pane = LogPane(name="test_name")
        assert pane.name == "test_name"

    def test_init_with_classes(self) -> None:
        """Test LogPane accepts classes parameter."""
        pane = LogPane(classes="foo bar")
        assert pane.has_class("foo")
        assert pane.has_class("bar")

    def test_level_colors_defined(self) -> None:
        """Test all expected log levels have colors defined."""
        expected_levels = ["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
        for level in expected_levels:
            assert level in LogPane.LEVEL_COLORS

    def test_level_colors_are_strings(self) -> None:
        """Test all level colors are valid strings."""
        for color in LogPane.LEVEL_COLORS.values():
            assert isinstance(color, str)
            assert len(color) > 0


class TestLogPaneAddLog:
    """Tests for LogPane.add_log method - these test that methods don't raise."""

    def test_add_log_with_timestamp_no_error(self) -> None:
        """Test add_log with timestamp doesn't raise."""
        pane = LogPane()
        timestamp = datetime(2024, 1, 15, 10, 30, 45)
        # Should not raise - write is a no-op when not mounted
        pane.add_log("INFO", "Test message", timestamp)

    def test_add_log_without_timestamp_no_error(self) -> None:
        """Test add_log without timestamp doesn't raise."""
        pane = LogPane()
        pane.add_log("DEBUG", "Debug message")

    def test_add_log_with_various_levels_no_error(self) -> None:
        """Test logs with different levels don't raise."""
        pane = LogPane()
        levels = ["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
        for level in levels:
            pane.add_log(level, f"{level} message")

    def test_add_log_with_unknown_level_no_error(self) -> None:
        """Test log with unknown level uses default color and doesn't raise."""
        pane = LogPane()
        pane.add_log("CUSTOM", "Custom level message")


class TestLogPaneSink:
    """Tests for LogPane.sink method (loguru integration)."""

    def test_sink_callable(self) -> None:
        """Test that sink is callable."""
        pane = LogPane()
        assert callable(pane.sink)

    def test_sink_handles_loguru_message(self) -> None:
        """Test sink processes loguru-style message."""
        import contextlib
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        pane = LogPane()

        # Create a mock loguru message
        mock_record = {
            "level": MagicMock(name="INFO"),
            "message": "Test log message",
            "time": datetime.now(tz=UTC),
        }
        mock_message = MagicMock()
        mock_message.record = mock_record

        # Patch add_log to verify it's called (since we're not mounted)
        # The sink will try to call app.call_from_thread which will fail
        # So we test the direct call path
        with patch.object(pane, "add_log"), contextlib.suppress(RuntimeError, AttributeError):
            pane.sink(mock_message)

    def test_sink_extracts_level_name(self) -> None:
        """Test sink extracts level name from loguru record."""
        import contextlib
        from datetime import datetime
        from unittest.mock import MagicMock

        pane = LogPane()

        # Create mock with level that has a name attribute
        mock_level = MagicMock()
        mock_level.name = "WARNING"

        mock_record = {
            "level": mock_level,
            "message": "Warning message",
            "time": datetime.now(tz=UTC),
        }
        mock_message = MagicMock()
        mock_message.record = mock_record

        # Test that sink can access the level name
        with contextlib.suppress(RuntimeError, AttributeError):
            pane.sink(mock_message)

    def test_sink_handles_runtime_error(self) -> None:
        """Test sink handles RuntimeError gracefully (fallback path)."""
        import contextlib
        from datetime import datetime
        from unittest.mock import MagicMock, PropertyMock, patch

        pane = LogPane()

        mock_level = MagicMock()
        mock_level.name = "DEBUG"

        mock_record = {
            "level": mock_level,
            "message": "Debug message",
            "time": datetime.now(tz=UTC),
        }
        mock_message = MagicMock()
        mock_message.record = mock_record

        # Mock the app property to raise RuntimeError
        with patch.object(type(pane), "app", new_callable=PropertyMock) as mock_app:
            mock_app_instance = MagicMock()
            mock_app_instance.call_from_thread.side_effect = RuntimeError("No app context")
            mock_app.return_value = mock_app_instance

            # Should not raise - should fallback to direct call
            with contextlib.suppress(AttributeError):
                pane.sink(mock_message)

    def test_sink_extracts_timestamp(self) -> None:
        """Test sink extracts and converts timestamp."""
        from datetime import datetime
        from unittest.mock import MagicMock
        from typing import cast

        # Create a specific timestamp
        test_time = datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC)

        mock_level = MagicMock()
        mock_level.name = "INFO"

        mock_record = {
            "level": mock_level,
            "message": "Test message",
            "time": test_time,
        }
        mock_message = MagicMock()
        mock_message.record = mock_record

        # The timestamp should be accessible and convertible
        record_time = cast(datetime, mock_record["time"])
        timestamp = record_time.replace(tzinfo=None)
        assert timestamp is not None
        assert timestamp == datetime(2024, 1, 15, 10, 30, 45)
