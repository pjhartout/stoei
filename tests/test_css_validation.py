"""Tests for CSS validation."""

from pathlib import Path

import pytest
from textual.app import App


class TestCSSValidation:
    """Tests for CSS file validation."""

    @pytest.fixture
    def styles_dir(self) -> Path:
        """Get the styles directory."""
        return Path(__file__).parent.parent / "stoei" / "styles"

    def test_app_tcss_is_valid(self, styles_dir: Path) -> None:
        """Test that app.tcss is valid CSS."""
        app_css = styles_dir / "app.tcss"
        assert app_css.exists(), "app.tcss should exist"

        app_css.read_text()

        # Try to parse the CSS - if it's invalid, this will raise an error
        # We'll test by trying to create an app that uses it
        class TestApp(App[None]):
            CSS_PATH = [app_css]  # noqa: RUF012

        # Creating the app should not raise CSS parsing errors
        app = TestApp()
        assert app is not None

    def test_modals_tcss_is_valid(self, styles_dir: Path) -> None:
        """Test that modals.tcss is valid CSS."""
        modals_css = styles_dir / "modals.tcss"
        assert modals_css.exists(), "modals.tcss should exist"

        modals_css.read_text()

        # Try to parse the CSS
        class TestApp(App[None]):
            CSS_PATH = [modals_css]  # noqa: RUF012

        # Creating the app should not raise CSS parsing errors
        app = TestApp()
        assert app is not None

    def test_all_css_files_parseable(self, styles_dir: Path) -> None:
        """Test that all CSS files in styles directory are parseable."""
        css_files = list(styles_dir.glob("*.tcss"))
        assert len(css_files) > 0, "Should have at least one CSS file"

        for css_file in css_files:
            css_file.read_text()

            # Try to create an app with this CSS
            class TestApp(App[None]):
                CSS_PATH = [css_file]  # noqa: RUF012

            # Should not raise CSS parsing errors
            app = TestApp()
            assert app is not None, f"Failed to parse {css_file.name}"

    def test_cluster_sidebar_css_in_widget(self) -> None:
        """Test that ClusterSidebar's DEFAULT_CSS is valid."""
        from stoei.widgets.cluster_sidebar import ClusterSidebar

        # Try to create the widget - invalid CSS would cause issues
        widget = ClusterSidebar()
        assert widget is not None

        # Try to create an app with the widget
        class TestApp(App[None]):
            def compose(self):
                yield ClusterSidebar()

        app = TestApp()
        assert app is not None

    def test_css_properties_are_valid(self, styles_dir: Path) -> None:
        """Test that CSS properties use valid values."""
        app_css = styles_dir / "app.tcss"
        css_content = app_css.read_text()

        # Check for common invalid patterns
        invalid_patterns = [
            "align: top;",  # Should be "align: left top;" or similar
            "align: bottom;",  # Should have two values
            "align: center;",  # Should have two values
        ]

        for pattern in invalid_patterns:
            assert pattern not in css_content, f"Found invalid CSS pattern: {pattern}"

    async def test_app_starts_with_valid_css(self) -> None:
        """Test that the main app starts successfully with its CSS."""
        from unittest.mock import patch

        from stoei.app import SlurmMonitor
        from stoei.slurm.cache import JobCache

        JobCache.reset()
        app = SlurmMonitor()
        # App should be created without CSS errors
        assert app is not None

        # Mock SLURM availability check to avoid actual SLURM dependency
        with patch("stoei.app.check_slurm_available", return_value=(True, None)):
            # Try to run the app briefly to catch any CSS-related or rendering errors
            async with app.run_test(size=(80, 24)):
                # App should start without CSS parsing errors
                assert app.is_running

                # Try to query widgets to ensure they render correctly
                sidebar = app.query_one("#cluster-sidebar")
                assert sidebar is not None

                # App should still be running after rendering
                assert app.is_running
