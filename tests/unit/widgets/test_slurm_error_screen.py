"""Tests for the SlurmUnavailableScreen widget."""

from stoei.widgets.slurm_error_screen import SlurmUnavailableScreen


class TestSlurmUnavailableScreen:
    """Tests for the SlurmUnavailableScreen."""

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
