"""Tests for SettingsScreen keyboard navigation."""

from __future__ import annotations

import pytest
from stoei.settings import Settings
from stoei.themes import THEME_LABELS
from stoei.widgets.settings_screen import SettingsScreen
from textual.app import App
from textual.widgets import Button, Input, Select


@pytest.fixture
def default_settings() -> Settings:
    """Create default settings for testing."""
    return Settings()


class TestSettingsScreenInApp:
    """Functional tests for settings screen running in an app context."""

    @pytest.mark.asyncio
    async def test_settings_screen_composes(self, default_settings: Settings) -> None:
        """Test that SettingsScreen composes correctly."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = app.screen
            # Verify all controls exist
            theme_select = screen.query_one("#settings-theme", Select)
            assert theme_select is not None
            log_level_select = screen.query_one("#settings-log-level", Select)
            assert log_level_select is not None
            max_lines_input = screen.query_one("#settings-max-lines", Input)
            assert max_lines_input is not None
            refresh_interval_input = screen.query_one("#settings-refresh-interval", Input)
            assert refresh_interval_input is not None
            job_history_days_input = screen.query_one("#settings-job-history-days", Input)
            assert job_history_days_input is not None
            save_btn = screen.query_one("#settings-save", Button)
            assert save_btn is not None
            cancel_btn = screen.query_one("#settings-cancel", Button)
            assert cancel_btn is not None

    @pytest.mark.asyncio
    async def test_initial_focus_on_theme(self, default_settings: Settings) -> None:
        """Theme selector should be focused on mount."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

    @pytest.mark.asyncio
    async def test_down_arrow_cycles_focus(self, default_settings: Settings) -> None:
        """Down arrow should move focus to next field."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Start on theme selector
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            # Press down, should move to log level
            await pilot.press("down")
            log_level_select = app.screen.query_one("#settings-log-level", Select)
            assert app.screen.focused is log_level_select

    @pytest.mark.asyncio
    async def test_up_arrow_cycles_focus(self, default_settings: Settings) -> None:
        """Up arrow should move focus to previous field."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Focus the log level selector
            log_level_select = app.screen.query_one("#settings-log-level", Select)
            log_level_select.focus()
            await pilot.pause()

            # Press up, should move to theme
            await pilot.press("up")
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

    @pytest.mark.asyncio
    async def test_tab_moves_focus_forward(self, default_settings: Settings) -> None:
        """Tab should move focus to next field."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            await pilot.press("tab")
            log_level_select = app.screen.query_one("#settings-log-level", Select)
            assert app.screen.focused is log_level_select

    @pytest.mark.asyncio
    async def test_shift_tab_moves_focus_backward(self, default_settings: Settings) -> None:
        """Shift+Tab should move focus to previous field."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Focus the log level selector
            log_level_select = app.screen.query_one("#settings-log-level", Select)
            log_level_select.focus()
            await pilot.pause()

            await pilot.press("shift+tab")
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

    @pytest.mark.asyncio
    async def test_home_focuses_first_field(self, default_settings: Settings) -> None:
        """Home should focus the first field."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Focus the cancel button
            cancel_btn = app.screen.query_one("#settings-cancel", Button)
            cancel_btn.focus()
            await pilot.pause()

            await pilot.press("home")
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

    @pytest.mark.asyncio
    async def test_end_focuses_last_field(self, default_settings: Settings) -> None:
        """End should focus the last field."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            await pilot.press("end")
            cancel_btn = app.screen.query_one("#settings-cancel", Button)
            assert app.screen.focused is cancel_btn

    @pytest.mark.asyncio
    async def test_t_jumps_to_theme(self, default_settings: Settings) -> None:
        """'t' should jump focus to theme selector."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Focus the cancel button
            cancel_btn = app.screen.query_one("#settings-cancel", Button)
            cancel_btn.focus()
            await pilot.pause()

            await pilot.press("t")
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

    @pytest.mark.asyncio
    async def test_l_jumps_to_log_level(self, default_settings: Settings) -> None:
        """'l' should jump focus to log level selector."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            await pilot.press("l")
            log_level_select = app.screen.query_one("#settings-log-level", Select)
            assert app.screen.focused is log_level_select

    @pytest.mark.asyncio
    async def test_m_jumps_to_max_lines(self, default_settings: Settings) -> None:
        """'m' should jump focus to max lines input."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            await pilot.press("m")
            max_lines_input = app.screen.query_one("#settings-max-lines", Input)
            assert app.screen.focused is max_lines_input

    @pytest.mark.asyncio
    async def test_letter_shortcuts_ignored_in_input(self, default_settings: Settings) -> None:
        """Letter shortcuts should not jump when typing in input field."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            max_lines_input = app.screen.query_one("#settings-max-lines", Input)
            max_lines_input.focus()
            await pilot.pause()

            # Type 't' - should stay in input, not jump to theme
            await pilot.press("t")
            assert app.screen.focused is max_lines_input

    @pytest.mark.asyncio
    async def test_right_arrow_cycles_theme_forward(self, default_settings: Settings) -> None:
        """Right arrow should cycle to next theme option."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select
            initial_value = theme_select.value

            await pilot.press("right")
            # Value should have changed (unless only one theme)
            if len(THEME_LABELS) > 1:
                assert theme_select.value != initial_value

    @pytest.mark.asyncio
    async def test_left_arrow_cycles_theme_backward(self, default_settings: Settings) -> None:
        """Left arrow should cycle to previous theme option."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select
            initial_value = theme_select.value

            await pilot.press("left")
            # Value should have changed (wraps to last)
            if len(THEME_LABELS) > 1:
                assert theme_select.value != initial_value

    @pytest.mark.asyncio
    async def test_arrow_keys_work_in_open_dropdown(self, default_settings: Settings) -> None:
        """Arrow keys should navigate options when dropdown is open."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            # Open the dropdown with Enter
            await pilot.press("enter")
            await pilot.pause()

            # Dropdown should be expanded
            assert theme_select.expanded

            # Press down - should navigate within dropdown, not change focus
            await pilot.press("down")
            await pilot.pause()

            # Dropdown should still be open (not closed by focus navigation)
            assert theme_select.expanded

    @pytest.mark.asyncio
    async def test_enter_on_input_moves_to_next_field(self, default_settings: Settings) -> None:
        """Enter on input field should move to next field."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Focus job history days - now keybind mode is between this and save
            history_days_input = app.screen.query_one("#settings-job-history-days", Input)
            history_days_input.focus()
            await pilot.pause()

            await pilot.press("enter")
            # Enter on input should move to next field (keybind mode)
            keybind_select = app.screen.query_one("#settings-keybind-mode", Select)
            assert app.screen.focused is keybind_select

    @pytest.mark.asyncio
    async def test_focus_wraps_from_last_to_first(self, default_settings: Settings) -> None:
        """Focus should wrap from last element to first."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Focus the cancel button (last element)
            cancel_btn = app.screen.query_one("#settings-cancel", Button)
            cancel_btn.focus()
            await pilot.pause()

            # Press down, should wrap to theme
            await pilot.press("down")
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

    @pytest.mark.asyncio
    async def test_focus_wraps_from_first_to_last(self, default_settings: Settings) -> None:
        """Focus should wrap from first element to last."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Start on theme selector (first element)
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            # Press up, should wrap to cancel button
            await pilot.press("up")
            cancel_btn = app.screen.query_one("#settings-cancel", Button)
            assert app.screen.focused is cancel_btn

    @pytest.mark.asyncio
    async def test_r_jumps_to_refresh_interval(self, default_settings: Settings) -> None:
        """'r' should jump focus to refresh interval input."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            await pilot.press("r")
            refresh_input = app.screen.query_one("#settings-refresh-interval", Input)
            assert app.screen.focused is refresh_input

    @pytest.mark.asyncio
    async def test_h_jumps_to_history_days(self, default_settings: Settings) -> None:
        """'h' should jump focus to job history days input."""

        class TestApp(App[None]):
            def __init__(self, settings: Settings) -> None:
                super().__init__()
                self._settings = settings

            def on_mount(self) -> None:
                self.push_screen(SettingsScreen(self._settings))

        app = TestApp(default_settings)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            theme_select = app.screen.query_one("#settings-theme", Select)
            assert app.screen.focused is theme_select

            await pilot.press("h")
            history_input = app.screen.query_one("#settings-job-history-days", Input)
            assert app.screen.focused is history_input
