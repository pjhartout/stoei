"""Tests for the logging module."""


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger_instance(self) -> None:
        from stoei.logger import get_logger

        logger = get_logger("test_module")
        assert logger is not None

    def test_logger_has_bind_context(self) -> None:
        from stoei.logger import get_logger

        logger = get_logger("test_module")
        # Logger should be bound with the name
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")


class TestAddTuiSink:
    """Tests for add_tui_sink function."""

    def test_returns_sink_id(self) -> None:
        from stoei.logger import add_tui_sink, remove_tui_sink

        # Use a real callable instead of MagicMock to avoid loguru
        # treating it as a file path (MagicMock has __fspath__ and write attrs)
        def sink_func(message: object) -> None:
            pass

        sink_id = add_tui_sink(sink_func)

        assert isinstance(sink_id, int)

        # Cleanup
        remove_tui_sink(sink_id)

    def test_adds_sink_to_logger(self) -> None:
        from stoei.logger import add_tui_sink, remove_tui_sink

        messages_received: list[str] = []

        def test_sink(message: object) -> None:
            messages_received.append(str(message))

        sink_id = add_tui_sink(test_sink, level="DEBUG")

        # Log a message - it should be captured by the sink
        from loguru import logger

        logger.info("Test message for sink")

        # Cleanup
        remove_tui_sink(sink_id)

        # At least one message should have been captured
        assert len(messages_received) >= 1


class TestRemoveTuiSink:
    """Tests for remove_tui_sink function."""

    def test_removes_sink_from_logger(self) -> None:
        from stoei.logger import add_tui_sink, remove_tui_sink

        messages_after_remove: list[str] = []

        def test_sink(message: object) -> None:
            messages_after_remove.append(str(message))

        sink_id = add_tui_sink(test_sink, level="DEBUG")
        remove_tui_sink(sink_id)

        # Log a message after removing the sink
        from loguru import logger

        initial_count = len(messages_after_remove)
        logger.info("Message after sink removed")

        # No new messages should be captured by our sink
        assert len(messages_after_remove) == initial_count

    def test_stdout_handler_stays_none(self) -> None:
        from stoei.logger import _state, add_tui_sink, remove_tui_sink

        # Use a real callable instead of MagicMock to avoid loguru
        # treating it as a file path (MagicMock has __fspath__ and write attrs)
        def sink_func(message: object) -> None:
            pass

        # stdout handler should be None (not added by default to keep terminal clean)
        assert _state.stdout_handler_id is None

        # Add and remove TUI sink
        sink_id = add_tui_sink(sink_func)

        # After adding TUI sink, stdout handler should still be None
        assert _state.stdout_handler_id is None

        remove_tui_sink(sink_id)

        # After removing TUI sink, stdout handler should stay None (not restored)
        assert _state.stdout_handler_id is None


class TestLoggingState:
    """Tests for _LoggingState class."""

    def test_initial_stdout_handler_is_none(self) -> None:
        from stoei.logger import _state

        # stdout handler should be None by default to avoid interfering with TUI
        assert hasattr(_state, "stdout_handler_id")
        assert _state.stdout_handler_id is None
