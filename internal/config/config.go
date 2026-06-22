package config

import (
	_ "embed"
	"errors"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// Bounds for the configurable numeric fields, ported verbatim from the Python
// stoei/settings.py module constants. The pure Load function clamps every value
// to these ranges (out-of-range or unparseable values fall back to the default).
const (
	// MinRefreshInterval and MaxRefreshInterval bound the fast-tier refresh in
	// seconds (settings.py MIN_REFRESH_INTERVAL / MAX_REFRESH_INTERVAL).
	MinRefreshInterval = 1.0
	MaxRefreshInterval = 300.0
	// DefaultRefreshInterval is the default fast-tier refresh (settings.py
	// DEFAULT_REFRESH_INTERVAL).
	DefaultRefreshInterval = 5.0

	// MinJobHistoryDays and MaxJobHistoryDays bound the sacct history window in
	// days (settings.py MIN_JOB_HISTORY_DAYS / MAX_JOB_HISTORY_DAYS).
	MinJobHistoryDays = 1
	MaxJobHistoryDays = 90
	// DefaultJobHistoryDays is the default history window (settings.py
	// DEFAULT_JOB_HISTORY_DAYS).
	DefaultJobHistoryDays = 7

	// MinLogViewerLines and MaxLogViewerLines bound the log-viewer tail window
	// (settings.py MIN_LOG_VIEWER_LINES / MAX_LOG_VIEWER_LINES).
	MinLogViewerLines = 500
	MaxLogViewerLines = 100000
	// DefaultLogViewerLines is the default tail window (settings.py
	// DEFAULT_LOG_VIEWER_LINES).
	DefaultLogViewerLines = 10000

	// MinEnergyHistoryMonths is the inclusive lower bound for the energy window in
	// months (settings.py clamps energy_history_months to >= 1, no upper bound).
	MinEnergyHistoryMonths = 1
	// DefaultEnergyHistoryMonths is the default energy window (settings.py
	// DEFAULT_ENERGY_HISTORY_MONTHS).
	DefaultEnergyHistoryMonths = 6
)

// DefaultTheme is the default palette name (settings.py DEFAULT_THEME_NAME =
// themes.OC1_THEME_NAME).
const DefaultTheme = "oc-1"

// KeybindMode is the keybinding preset name. The Python keybindings module
// defines exactly two presets.
type KeybindMode = string

// Keybind modes, ported from keybindings.KEYBIND_MODES. Vim is the default
// (keybindings.DEFAULT_PRESET).
const (
	KeybindVim   KeybindMode = "vim"
	KeybindEmacs KeybindMode = "emacs"
	// DefaultKeybindMode is the default preset (keybindings.DEFAULT_PRESET).
	DefaultKeybindMode = KeybindVim
)

// ValidThemes lists the theme names the settings form cycles through and that
// Load validates against. It MUST stay identical (as a set) to the names
// theme.Names returns: every name here must have an implemented Go palette, and
// every implemented palette must be accepted here, otherwise the settings modal
// would offer (or config would accept) a theme that silently renders as the
// fallback. The 12 Python themes (themes.THEME_LABELS keys) plus the Go-only
// gruvbox and charm palettes. A cross-package guard test
// (internal/ui/theme_sync_test.go) fails if this list and theme.Names diverge;
// config itself must not import the Charm-backed theme package (depguard), so
// this list is maintained by hand and pinned by that test.
var ValidThemes = []string{
	"oc-1",
	"tokyonight",
	"dracula",
	"monokai",
	"solarized",
	"nord",
	"catppuccin",
	"ayu",
	"onedarkpro",
	"shadesofpurple",
	"nightowl",
	"vesper",
	"gruvbox",
	"charm",
}

// Config is the persisted user configuration. It mirrors the subset of the
// Python Settings dataclass the Go app consumes (theme, refresh interval,
// history days, log-viewer lines, keybind mode, energy on/off + months). The
// column-width and sidebar-width Python fields are deferred (their features are
// not yet ported). This struct carries no UI or Charm types so the package is a
// pure, testable seam.
type Config struct {
	// Theme is the palette name (settings.py Settings.theme).
	Theme string `yaml:"theme"`
	// RefreshInterval is the fast-tier refresh in seconds
	// (settings.py refresh_interval).
	RefreshInterval float64 `yaml:"refresh_interval"`
	// JobHistoryDays is the sacct history window in days
	// (settings.py job_history_days).
	JobHistoryDays int `yaml:"job_history_days"`
	// LogViewerLines is the log-viewer tail window (settings.py log_viewer_lines).
	LogViewerLines int `yaml:"log_viewer_lines"`
	// KeybindMode is the keybinding preset (settings.py keybind_mode).
	KeybindMode string `yaml:"keybind_mode"`
	// EnergyEnabled toggles energy accounting (settings.py energy_loading_enabled).
	EnergyEnabled bool `yaml:"energy_enabled"`
	// EnergyHistoryMonths is the energy window in months
	// (settings.py energy_history_months).
	EnergyHistoryMonths int `yaml:"energy_history_months"`
}

// Default returns the configuration matching the Python Settings defaults.
func Default() Config {
	return Config{
		Theme:               DefaultTheme,
		RefreshInterval:     DefaultRefreshInterval,
		JobHistoryDays:      DefaultJobHistoryDays,
		LogViewerLines:      DefaultLogViewerLines,
		KeybindMode:         DefaultKeybindMode,
		EnergyEnabled:       false,
		EnergyHistoryMonths: DefaultEnergyHistoryMonths,
	}
}

//go:embed default.yaml
var embeddedDefault []byte

// EmbeddedDefault returns the embedded default configuration bytes. It is parsed
// through the same Load path, so a malformed embed still yields Default().
func EmbeddedDefault() []byte { return embeddedDefault }

// Load parses YAML config bytes and returns a Config with every field clamped to
// the Python bounds: out-of-range or unparseable values fall back to the field
// default (matching settings.py from_mapping). Empty input yields the defaults.
// It is the pure test seam; LoadFile is the thin file wrapper around it.
func Load(data []byte) (Config, error) {
	cfg := Default()
	if len(data) > 0 {
		var raw Config
		if err := yaml.Unmarshal(data, &raw); err != nil {
			return Default(), err
		}
		cfg = raw
	}
	return clamp(cfg), nil
}

// clamp validates and clamps every field to the Python bounds, falling back to
// the field default when a value is invalid or out of range.
func clamp(c Config) Config {
	d := Default()

	if !validTheme(c.Theme) {
		c.Theme = d.Theme
	}
	if c.RefreshInterval < MinRefreshInterval || c.RefreshInterval > MaxRefreshInterval {
		c.RefreshInterval = d.RefreshInterval
	}
	if c.JobHistoryDays < MinJobHistoryDays || c.JobHistoryDays > MaxJobHistoryDays {
		c.JobHistoryDays = d.JobHistoryDays
	}
	if c.LogViewerLines < MinLogViewerLines || c.LogViewerLines > MaxLogViewerLines {
		c.LogViewerLines = d.LogViewerLines
	}
	if c.KeybindMode != KeybindVim && c.KeybindMode != KeybindEmacs {
		c.KeybindMode = d.KeybindMode
	}
	if c.EnergyHistoryMonths < MinEnergyHistoryMonths {
		c.EnergyHistoryMonths = d.EnergyHistoryMonths
	}
	return c
}

// validTheme reports whether name is one of the known palettes.
func validTheme(name string) bool {
	for _, t := range ValidThemes {
		if t == name {
			return true
		}
	}
	return false
}

// Marshal serializes c to YAML. The config is clamped first so a programmatically
// constructed out-of-range Config never persists an invalid value.
func Marshal(c Config) ([]byte, error) {
	return yaml.Marshal(clamp(c))
}

// LoadFile reads the config file at path and parses it with Load. A missing file
// returns the defaults with a nil error (the app runs on defaults until the user
// saves settings); other read errors are returned.
func LoadFile(path string) (Config, error) {
	data, err := os.ReadFile(path) //nolint:gosec // path is the resolved XDG config path
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return Default(), nil
		}
		return Default(), err
	}
	return Load(data)
}

// Save marshals c and writes it to path, creating parent directories as needed.
func Save(path string, c Config) error {
	data, err := Marshal(c)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644) //nolint:gosec // user config, not a secret
}

// Dir resolves the configuration directory, honoring STOEI_CONFIG_DIR, then
// XDG_CONFIG_HOME/stoei, then ~/.config/stoei. Ports settings.get_config_dir.
func Dir() (string, error) {
	if override := os.Getenv("STOEI_CONFIG_DIR"); override != "" {
		return override, nil
	}
	if base := os.Getenv("XDG_CONFIG_HOME"); base != "" {
		return filepath.Join(base, "stoei"), nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".config", "stoei"), nil
}

// Path returns the full path to the config file under Dir. Ports
// settings.get_settings_path (the file is config.yaml here, settings.json there).
func Path() (string, error) {
	dir, err := Dir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "config.yaml"), nil
}
