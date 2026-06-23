package config

import (
	_ "embed"
	"errors"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// Bounds for the configurable numeric fields. Load clamps every value to these
// ranges; out-of-range or unparseable values fall back to the matching default.
const (
	// MinRefreshInterval and MaxRefreshInterval bound the fast-tier refresh in
	// seconds.
	MinRefreshInterval = 1.0
	MaxRefreshInterval = 300.0
	// DefaultRefreshInterval is the default fast-tier refresh in seconds.
	DefaultRefreshInterval = 5.0

	// MinJobHistoryDays and MaxJobHistoryDays bound the sacct history window in
	// days.
	MinJobHistoryDays = 1
	MaxJobHistoryDays = 90
	// DefaultJobHistoryDays is the default history window in days.
	DefaultJobHistoryDays = 7

	// MinLogViewerLines and MaxLogViewerLines bound the log-viewer tail window in
	// lines.
	MinLogViewerLines = 500
	MaxLogViewerLines = 100000
	// DefaultLogViewerLines is the default tail window in lines.
	DefaultLogViewerLines = 10000

	// MinEnergyHistoryMonths is the inclusive lower bound for the energy window in
	// months. There is no upper bound.
	MinEnergyHistoryMonths = 1
	// DefaultEnergyHistoryMonths is the default energy window in months.
	DefaultEnergyHistoryMonths = 6
)

// DefaultTheme is the default palette name; nord is a calm Nord-style
// frost/polar-night scheme. Must stay in sync with theme.DefaultThemeName.
const DefaultTheme = "nord"

// KeybindMode is the keybinding preset name. There are exactly two presets,
// "vim" and "emacs".
type KeybindMode = string

// Keybind modes. KeybindVim and KeybindEmacs are the two valid presets; Vim is
// the default.
const (
	KeybindVim   KeybindMode = "vim"
	KeybindEmacs KeybindMode = "emacs"
	// DefaultKeybindMode is the default keybinding preset.
	DefaultKeybindMode = KeybindVim
)

// ValidThemes lists the theme names the settings form cycles through and that
// Load validates against. It MUST stay identical (as a set) to the names
// theme.Names returns: every name here must have an implemented Go palette, and
// every implemented palette must be accepted here, otherwise the settings modal
// would offer (or config would accept) a theme that silently renders as the
// fallback. A cross-package guard test (internal/ui/theme_sync_test.go) fails if
// this list and theme.Names diverge; config itself must not import the
// Charm-backed theme package (depguard), so this list is maintained by hand and
// pinned by that test.
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

// Config is the persisted user configuration: theme, refresh interval, history
// days, log-viewer lines, keybind mode, and energy on/off plus months. This
// struct carries no UI or Charm types so the package stays a pure, testable
// seam.
type Config struct {
	// Theme is the palette name.
	Theme string `yaml:"theme"`
	// RefreshInterval is the fast-tier refresh in seconds.
	RefreshInterval float64 `yaml:"refresh_interval"`
	// JobHistoryDays is the sacct history window in days.
	JobHistoryDays int `yaml:"job_history_days"`
	// LogViewerLines is the log-viewer tail window in lines.
	LogViewerLines int `yaml:"log_viewer_lines"`
	// KeybindMode is the keybinding preset ("vim" or "emacs").
	KeybindMode string `yaml:"keybind_mode"`
	// EnergyEnabled toggles energy accounting.
	EnergyEnabled bool `yaml:"energy_enabled"`
	// EnergyHistoryMonths is the energy window in months.
	EnergyHistoryMonths int `yaml:"energy_history_months"`
}

// Default returns the configuration used when no file exists or a field is
// invalid.
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
// its valid range: out-of-range or unparseable values fall back to the field
// default. Empty input yields the defaults. It is the pure test seam; LoadFile is
// the thin file wrapper around it.
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

// clamp validates and clamps every field to its valid range, falling back to the
// field default when a value is invalid or out of range.
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
// XDG_CONFIG_HOME/stoei, then ~/.config/stoei.
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

// Path returns the full path to the config file (config.yaml) under Dir.
func Path() (string, error) {
	dir, err := Dir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "config.yaml"), nil
}
