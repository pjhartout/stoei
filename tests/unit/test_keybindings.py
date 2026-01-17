"""Unit tests for the keybindings module."""

from stoei.keybindings import (
    PRESETS,
    Actions,
    KeyBinding,
    KeybindingConfig,
    KeybindingPreset,
    get_default_config,
)


class TestKeyBinding:
    """Tests for KeyBinding dataclass."""

    def test_keybinding_creation(self) -> None:
        """Test creating a KeyBinding."""
        binding = KeyBinding(key="q", description="Quit")
        assert binding.key == "q"
        assert binding.description == "Quit"
        assert binding.show_in_footer is False

    def test_keybinding_with_show_in_footer(self) -> None:
        """Test creating a KeyBinding with show_in_footer."""
        binding = KeyBinding(key="q", description="Quit", show_in_footer=True)
        assert binding.show_in_footer is True


class TestKeybindingPreset:
    """Tests for KeybindingPreset class."""

    def test_preset_creation(self) -> None:
        """Test creating a preset."""
        preset = KeybindingPreset(name="test", bindings={})
        assert preset.name == "test"
        assert preset.bindings == {}

    def test_preset_get_key(self) -> None:
        """Test getting a key from a preset."""
        preset = KeybindingPreset(
            name="test",
            bindings={
                Actions.QUIT: KeyBinding("q", "Quit"),
                Actions.HELP: KeyBinding("?", "Help"),
            },
        )
        assert preset.get_key(Actions.QUIT) == "q"
        assert preset.get_key(Actions.HELP) == "?"
        assert preset.get_key("nonexistent") is None

    def test_preset_get_binding(self) -> None:
        """Test getting a binding from a preset."""
        quit_binding = KeyBinding("q", "Quit", show_in_footer=True)
        preset = KeybindingPreset(
            name="test",
            bindings={Actions.QUIT: quit_binding},
        )
        assert preset.get_binding(Actions.QUIT) == quit_binding
        assert preset.get_binding("nonexistent") is None


class TestKeybindingConfig:
    """Tests for KeybindingConfig class."""

    def test_config_default_preset(self) -> None:
        """Test default config uses vim preset."""
        config = KeybindingConfig()
        assert config.preset == "vim"
        assert config.overrides == {}

    def test_config_emacs_preset(self) -> None:
        """Test config with emacs preset."""
        config = KeybindingConfig(preset="emacs")
        assert config.preset == "emacs"

    def test_config_get_key_from_preset(self) -> None:
        """Test getting a key from the preset."""
        config = KeybindingConfig(preset="vim")
        # vim preset uses 'q' for quit
        assert config.get_key(Actions.QUIT) == "q"

        config_emacs = KeybindingConfig(preset="emacs")
        # emacs preset uses 'ctrl+q' for quit
        assert config_emacs.get_key(Actions.QUIT) == "ctrl+q"

    def test_config_get_key_with_override(self) -> None:
        """Test getting a key with an override."""
        config = KeybindingConfig(
            preset="vim",
            overrides={Actions.QUIT: "x"},
        )
        # Override should take precedence
        assert config.get_key(Actions.QUIT) == "x"

    def test_config_get_binding_with_override(self) -> None:
        """Test getting a binding with an override."""
        config = KeybindingConfig(
            preset="vim",
            overrides={Actions.QUIT: "x"},
        )
        binding = config.get_binding(Actions.QUIT)
        assert binding is not None
        assert binding.key == "x"
        # Description should come from preset
        assert binding.description == "Quit"

    def test_config_get_all_bindings(self) -> None:
        """Test getting all bindings with overrides applied."""
        config = KeybindingConfig(
            preset="vim",
            overrides={Actions.QUIT: "x"},
        )
        all_bindings = config.get_all_bindings()
        assert Actions.QUIT in all_bindings
        assert all_bindings[Actions.QUIT].key == "x"
        # Other bindings should be from preset
        assert all_bindings[Actions.HELP].key == "question_mark"

    def test_config_to_dict(self) -> None:
        """Test serializing config to dict."""
        config = KeybindingConfig(
            preset="emacs",
            overrides={Actions.QUIT: "x"},
        )
        d = config.to_dict()
        assert d["preset"] == "emacs"
        assert d["overrides"] == {Actions.QUIT: "x"}

    def test_config_from_dict(self) -> None:
        """Test creating config from dict."""
        d = {
            "preset": "emacs",
            "overrides": {Actions.QUIT: "x"},
        }
        config = KeybindingConfig.from_dict(d)
        assert config.preset == "emacs"
        assert config.overrides == {Actions.QUIT: "x"}

    def test_config_from_dict_none(self) -> None:
        """Test creating config from None returns defaults."""
        config = KeybindingConfig.from_dict(None)
        assert config.preset == "vim"
        assert config.overrides == {}

    def test_config_from_dict_invalid_preset(self) -> None:
        """Test creating config with invalid preset uses default."""
        d = {"preset": "invalid"}
        config = KeybindingConfig.from_dict(d)
        assert config.preset == "vim"

    def test_config_from_dict_invalid_overrides(self) -> None:
        """Test creating config with invalid overrides ignores them."""
        d = {
            "preset": "vim",
            "overrides": {
                Actions.QUIT: "x",  # valid
                123: "y",  # invalid key
                "action": 456,  # invalid value
            },
        }
        config = KeybindingConfig.from_dict(d)
        assert config.overrides == {Actions.QUIT: "x"}


class TestPresets:
    """Tests for preset definitions."""

    def test_vim_preset_exists(self) -> None:
        """Test vim preset is defined."""
        assert "vim" in PRESETS
        vim = PRESETS["vim"]
        assert vim.name == "vim"

    def test_emacs_preset_exists(self) -> None:
        """Test emacs preset is defined."""
        assert "emacs" in PRESETS
        emacs = PRESETS["emacs"]
        assert emacs.name == "emacs"

    def test_vim_preset_has_expected_bindings(self) -> None:
        """Test vim preset has expected key bindings."""
        vim = PRESETS["vim"]
        assert vim.get_key(Actions.QUIT) == "q"
        assert vim.get_key(Actions.HELP) == "question_mark"
        assert vim.get_key(Actions.REFRESH) == "r"
        assert vim.get_key(Actions.FILTER_SHOW) == "slash"
        assert vim.get_key(Actions.SORT_CYCLE) == "o"

    def test_emacs_preset_has_expected_bindings(self) -> None:
        """Test emacs preset has expected key bindings."""
        emacs = PRESETS["emacs"]
        assert emacs.get_key(Actions.QUIT) == "ctrl+q"
        assert emacs.get_key(Actions.HELP) == "ctrl+h"
        assert emacs.get_key(Actions.REFRESH) == "ctrl+r"
        assert emacs.get_key(Actions.FILTER_SHOW) == "ctrl+s"
        assert emacs.get_key(Actions.SORT_CYCLE) == "ctrl+o"

    def test_vim_preset_filter_shown_in_footer(self) -> None:
        """Test vim preset shows filter in footer."""
        vim = PRESETS["vim"]
        binding = vim.get_binding(Actions.FILTER_SHOW)
        assert binding is not None
        assert binding.show_in_footer is True

    def test_emacs_preset_filter_shown_in_footer(self) -> None:
        """Test emacs preset shows filter in footer."""
        emacs = PRESETS["emacs"]
        binding = emacs.get_binding(Actions.FILTER_SHOW)
        assert binding is not None
        assert binding.show_in_footer is True


class TestGetDefaultConfig:
    """Tests for get_default_config function."""

    def test_get_vim_config(self) -> None:
        """Test getting vim default config."""
        config = get_default_config("vim")
        assert config.preset == "vim"
        assert config.overrides == {}

    def test_get_emacs_config(self) -> None:
        """Test getting emacs default config."""
        config = get_default_config("emacs")
        assert config.preset == "emacs"
        assert config.overrides == {}

    def test_get_invalid_mode_returns_vim(self) -> None:
        """Test getting config with invalid mode returns vim."""
        config = get_default_config("invalid")
        assert config.preset == "vim"


class TestActions:
    """Tests for Actions constants."""

    def test_action_constants_exist(self) -> None:
        """Test that all action constants are defined."""
        # Global actions
        assert Actions.QUIT == "quit"
        assert Actions.HELP == "help"
        assert Actions.REFRESH == "refresh"
        assert Actions.SETTINGS == "settings"

        # Table actions
        assert Actions.FILTER_SHOW == "filter_show"
        assert Actions.FILTER_HIDE == "filter_hide"
        assert Actions.SORT_CYCLE == "sort_cycle"

        # Navigation
        assert Actions.NAV_UP == "nav_up"
        assert Actions.NAV_DOWN == "nav_down"
