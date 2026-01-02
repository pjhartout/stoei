"""Tests for the SlurmUnavailableScreen widget."""

from stoei.widgets.slurm_error_screen import SlurmUnavailableScreen


class TestSlurmUnavailableScreen:
    """Tests for the SlurmUnavailableScreen."""

    def test_screen_has_bindings(self) -> None:
        """Test that the screen has quit bindings."""
        screen = SlurmUnavailableScreen()
        binding_keys = [b[0] for b in screen.BINDINGS]
        assert "q" in binding_keys
        assert "escape" in binding_keys

    def test_screen_bindings_include_q(self) -> None:
        """Test that q binding is for quit."""
        screen = SlurmUnavailableScreen()
        q_binding = next(b for b in screen.BINDINGS if b[0] == "q")
        assert q_binding[1] == "quit"

    def test_screen_bindings_include_escape(self) -> None:
        """Test that escape binding is for quit."""
        screen = SlurmUnavailableScreen()
        esc_binding = next(b for b in screen.BINDINGS if b[0] == "escape")
        assert esc_binding[1] == "quit"

    def test_action_quit_method_exists(self) -> None:
        """Test that action_quit method exists."""
        screen = SlurmUnavailableScreen()
        assert hasattr(screen, "action_quit")
        assert callable(screen.action_quit)

    def test_compose_method_exists(self) -> None:
        """Test that compose method exists."""
        screen = SlurmUnavailableScreen()
        assert hasattr(screen, "compose")
        assert callable(screen.compose)

    def test_on_mount_method_exists(self) -> None:
        """Test that on_mount method exists."""
        screen = SlurmUnavailableScreen()
        assert hasattr(screen, "on_mount")
        assert callable(screen.on_mount)

    def test_on_button_pressed_method_exists(self) -> None:
        """Test that on_button_pressed method exists."""
        screen = SlurmUnavailableScreen()
        assert hasattr(screen, "on_button_pressed")
        assert callable(screen.on_button_pressed)
