"""Tests for the LoadingScreen widget."""

import pytest
from stoei.widgets.loading_screen import LoadingScreen, LoadingStep


class TestLoadingStep:
    """Tests for the LoadingStep dataclass."""

    def test_loading_step_creation(self) -> None:
        """Test creating a LoadingStep with basic parameters."""
        step = LoadingStep("test_step", "Test description")
        assert step.name == "test_step"
        assert step.description == "Test description"
        assert step.weight == 1.0  # Default weight

    def test_loading_step_with_custom_weight(self) -> None:
        """Test creating a LoadingStep with custom weight."""
        step = LoadingStep("heavy_step", "Heavy operation", weight=3.0)
        assert step.name == "heavy_step"
        assert step.description == "Heavy operation"
        assert step.weight == 3.0


class TestLoadingScreen:
    """Tests for the LoadingScreen widget."""

    @pytest.fixture
    def steps(self) -> list[LoadingStep]:
        """Create a list of loading steps for testing."""
        return [
            LoadingStep("step1", "Step 1 description", weight=1.0),
            LoadingStep("step2", "Step 2 description", weight=2.0),
            LoadingStep("step3", "Step 3 description", weight=1.0),
        ]

    def test_loading_screen_initialization(self, steps: list[LoadingStep]) -> None:
        """Test LoadingScreen initialization."""
        screen = LoadingScreen(steps)
        assert screen.steps == steps
        assert screen.total_weight == 4.0  # 1.0 + 2.0 + 1.0
        assert screen._current_step_index == 0
        assert screen._completed_weight == 0.0
        assert screen._spinner_frame == 0
        assert screen._spinner_timer is None

    def test_loading_screen_total_weight_calculation(self) -> None:
        """Test that total weight is calculated correctly."""
        steps = [
            LoadingStep("a", "A", weight=0.5),
            LoadingStep("b", "B", weight=1.5),
            LoadingStep("c", "C", weight=2.0),
        ]
        screen = LoadingScreen(steps)
        assert screen.total_weight == 4.0

    def test_loading_screen_with_empty_steps(self) -> None:
        """Test LoadingScreen with empty steps list."""
        screen = LoadingScreen([])
        assert screen.steps == []
        assert screen.total_weight == 0.0

    def test_spinner_frames_exist(self) -> None:
        """Test that spinner frames are defined."""
        assert len(LoadingScreen.SPINNER_FRAMES) > 0
        # All frames should be non-empty strings
        for frame in LoadingScreen.SPINNER_FRAMES:
            assert isinstance(frame, str)
            assert len(frame) > 0

    def test_loading_screen_has_default_css(self) -> None:
        """Test that LoadingScreen has DEFAULT_CSS defined."""
        assert LoadingScreen.DEFAULT_CSS is not None
        assert "LoadingScreen" in LoadingScreen.DEFAULT_CSS
        assert "#loading-container" in LoadingScreen.DEFAULT_CSS
        assert "#spinner" in LoadingScreen.DEFAULT_CSS
        assert "#progress-bar" in LoadingScreen.DEFAULT_CSS

    def test_loading_screen_step_log_tracking(self, steps: list[LoadingStep]) -> None:
        """Test that step log entries are tracked."""
        screen = LoadingScreen(steps)
        assert screen._step_log_entries == []

    def test_loading_screen_step_start_times_tracking(self, steps: list[LoadingStep]) -> None:
        """Test that step start times are tracked."""
        screen = LoadingScreen(steps)
        assert screen._step_start_times == {}


class TestLoadingScreenMethods:
    """Tests for LoadingScreen methods that don't require mounting."""

    @pytest.fixture
    def screen(self) -> LoadingScreen:
        """Create a LoadingScreen for testing."""
        steps = [
            LoadingStep("step1", "Step 1", weight=1.0),
            LoadingStep("step2", "Step 2", weight=1.0),
        ]
        return LoadingScreen(steps)

    def test_start_step_out_of_range(self, screen: LoadingScreen) -> None:
        """Test start_step with index out of range."""
        # This should not raise, just return early
        screen.start_step(999)
        assert screen._current_step_index == 0

    def test_complete_step_out_of_range(self, screen: LoadingScreen) -> None:
        """Test complete_step with index out of range."""
        initial_weight = screen._completed_weight
        # This should not raise, just return early
        screen.complete_step(999)
        assert screen._completed_weight == initial_weight

    def test_fail_step_out_of_range(self, screen: LoadingScreen) -> None:
        """Test fail_step with index out of range."""
        initial_entries = len(screen._step_log_entries)
        # This should not raise, just return early
        screen.fail_step(999, "error")
        # No log entry should be added since step is out of range
        assert len(screen._step_log_entries) == initial_entries
