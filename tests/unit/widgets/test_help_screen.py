"""Tests for help screen widget."""

from stoei.widgets.help_screen import HelpScreen


class TestHelpScreen:
    """Tests for HelpScreen."""

    def test_bindings_defined(self) -> None:
        """Test that bindings are defined."""
        assert len(HelpScreen.BINDINGS) > 0

    def test_bindings_include_escape(self) -> None:
        """Test that escape binding exists."""
        binding_keys = [b[0] for b in HelpScreen.BINDINGS]
        assert "escape" in binding_keys

    def test_bindings_include_close(self) -> None:
        """Test that q and ? bindings exist for close."""
        binding_keys = [b[0] for b in HelpScreen.BINDINGS]
        assert "q" in binding_keys
        assert "?" in binding_keys

    def test_get_help_content_not_empty(self) -> None:
        """Test that help content is generated."""
        screen = HelpScreen()
        content = screen._get_help_content()
        assert content
        assert len(content) > 0

    def test_get_help_content_has_sections(self) -> None:
        """Test that help content has expected sections."""
        screen = HelpScreen()
        content = screen._get_help_content()
        assert "Navigation" in content
        assert "Jobs Tab" in content
        assert "General" in content

    def test_get_help_content_has_keybindings(self) -> None:
        """Test that help content has keybindings."""
        screen = HelpScreen()
        content = screen._get_help_content()
        # Check for some expected keybindings
        assert "Quit" in content
        assert "Refresh" in content
        assert "Open settings" in content

    def test_format_section(self) -> None:
        """Test _format_section method."""
        screen = HelpScreen()
        section = screen._format_section("Test Section", [("a", "Action A"), ("b", "Action B")])
        assert "Test Section" in section
        assert "Action A" in section
        assert "Action B" in section


class TestHelpScreenActions:
    """Tests for HelpScreen action methods."""

    def test_action_close_method_exists(self) -> None:
        """Test action_close method exists."""
        screen = HelpScreen()
        assert hasattr(screen, "action_close")
        assert callable(screen.action_close)


class TestHelpScreenInApp:
    """Functional tests for help screen running in an app context."""

    async def test_help_screen_composes(self) -> None:
        """Test that HelpScreen composes correctly."""
        from textual.app import App
        from textual.widgets import Button

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(HelpScreen())

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            close_btn = screen.query_one("#help-close-button", Button)
            assert close_btn is not None

    async def test_help_screen_has_content(self) -> None:
        """Test that HelpScreen has help content."""
        from textual.app import App
        from textual.widgets import Static

        class TestApp(App[None]):
            def on_mount(self) -> None:
                self.push_screen(HelpScreen())

        app = TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            help_text = screen.query_one("#help-text", Static)
            assert help_text is not None
