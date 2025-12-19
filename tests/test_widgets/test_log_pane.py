"""Tests for the LogPane widget."""

from datetime import datetime

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
