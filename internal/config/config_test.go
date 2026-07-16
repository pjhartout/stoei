package config

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"

	"gopkg.in/yaml.v3"
)

// TestLoadEmptyYieldsDefaults asserts empty input returns the Python defaults.
func TestLoadEmptyYieldsDefaults(t *testing.T) {
	got, err := Load(nil)
	if err != nil {
		t.Fatalf("Load(nil) error: %v", err)
	}
	if !reflect.DeepEqual(got, Default()) {
		t.Errorf("Load(nil) = %+v, want defaults %+v", got, Default())
	}
}

// TestEmbeddedDefaultParsesToDefaults asserts the embedded default.yaml parses to
// exactly the Default() config.
func TestEmbeddedDefaultParsesToDefaults(t *testing.T) {
	got, err := Load(EmbeddedDefault())
	if err != nil {
		t.Fatalf("Load(embedded) error: %v", err)
	}
	if !reflect.DeepEqual(got, Default()) {
		t.Errorf("embedded default = %+v, want %+v", got, Default())
	}
}

// TestLoadRoundTrips asserts an in-range config survives Load unchanged.
func TestLoadRoundTrips(t *testing.T) {
	in := Config{
		Theme:           "dracula",
		RefreshInterval: 12.5,
		JobHistoryDays:  30,
		LogViewerLines:  20000,
		KeybindMode:     KeybindEmacs,
	}
	data, err := Marshal(in)
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}
	got, err := Load(data)
	if err != nil {
		t.Fatalf("Load error: %v", err)
	}
	if !reflect.DeepEqual(got, in) {
		t.Errorf("round-trip = %+v, want %+v", got, in)
	}
}

// TestLoadClampsOutOfRange asserts every out-of-range field falls back to its
// Python default per from_mapping.
func TestLoadClampsOutOfRange(t *testing.T) {
	in := Config{
		Theme:           "no-such-theme",
		RefreshInterval: 0.0,  // below MinRefreshInterval
		JobHistoryDays:  9999, // above MaxJobHistoryDays
		LogViewerLines:  1,    // below MinLogViewerLines
		KeybindMode:     "qwerty",
	}
	// Bypass Marshal (which clamps) by serializing directly via Load on raw bytes.
	data, err := rawYAML(in)
	if err != nil {
		t.Fatalf("rawYAML error: %v", err)
	}
	got, err := Load(data)
	if err != nil {
		t.Fatalf("Load error: %v", err)
	}

	d := Default()
	if got.Theme != d.Theme {
		t.Errorf("Theme = %q, want clamped default %q", got.Theme, d.Theme)
	}
	if got.RefreshInterval != d.RefreshInterval {
		t.Errorf("RefreshInterval = %v, want %v", got.RefreshInterval, d.RefreshInterval)
	}
	if got.JobHistoryDays != d.JobHistoryDays {
		t.Errorf("JobHistoryDays = %v, want %v", got.JobHistoryDays, d.JobHistoryDays)
	}
	if got.LogViewerLines != d.LogViewerLines {
		t.Errorf("LogViewerLines = %v, want %v", got.LogViewerLines, d.LogViewerLines)
	}
	if got.KeybindMode != d.KeybindMode {
		t.Errorf("KeybindMode = %q, want %q", got.KeybindMode, d.KeybindMode)
	}
}

// TestClampPreservesBoundaryValues asserts inclusive bounds are not clamped.
func TestClampPreservesBoundaryValues(t *testing.T) {
	in := Config{
		Theme:           "vesper",
		RefreshInterval: MaxRefreshInterval,
		JobHistoryDays:  MinJobHistoryDays,
		LogViewerLines:  MaxLogViewerLines,
		KeybindMode:     KeybindVim,
	}
	data, err := rawYAML(in)
	if err != nil {
		t.Fatalf("rawYAML error: %v", err)
	}
	got, err := Load(data)
	if err != nil {
		t.Fatalf("Load error: %v", err)
	}
	if !reflect.DeepEqual(got, in) {
		t.Errorf("boundary config altered: got %+v, want %+v", got, in)
	}
}

// TestLoadInvalidYAMLReturnsDefaults asserts malformed YAML yields defaults+err.
func TestLoadInvalidYAMLReturnsDefaults(t *testing.T) {
	got, err := Load([]byte("this: : : not yaml"))
	if err == nil {
		t.Error("expected error for malformed YAML")
	}
	if !reflect.DeepEqual(got, Default()) {
		t.Errorf("malformed Load = %+v, want defaults", got)
	}
}

// TestSaveLoadFileRoundTrips asserts Save persists through its temp+rename path
// and LoadFile reads the same config back, leaving no temp litter behind.
func TestSaveLoadFileRoundTrips(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nested", "config.yaml")
	in := Config{
		Theme:           "dracula",
		RefreshInterval: 12.5,
		JobHistoryDays:  30,
		LogViewerLines:  20000,
		KeybindMode:     KeybindEmacs,
	}
	if err := Save(path, in); err != nil {
		t.Fatalf("Save error: %v", err)
	}
	got, err := LoadFile(path)
	if err != nil {
		t.Fatalf("LoadFile error: %v", err)
	}
	if !reflect.DeepEqual(got, in) {
		t.Errorf("round-trip = %+v, want %+v", got, in)
	}
	leftovers, err := filepath.Glob(filepath.Join(dir, "nested", "*.tmp"))
	if err != nil || len(leftovers) != 0 {
		t.Errorf("temp files left behind: %v (err %v)", leftovers, err)
	}
}

// TestLoadFileMissingReturnsDefaults asserts a missing config file yields the defaults with a nil error.
func TestLoadFileMissingReturnsDefaults(t *testing.T) {
	got, err := LoadFile(filepath.Join(t.TempDir(), "absent", "config.yaml"))
	if err != nil {
		t.Fatalf("LoadFile(missing) error: %v", err)
	}
	if !reflect.DeepEqual(got, Default()) {
		t.Errorf("LoadFile(missing) = %+v, want defaults", got)
	}
}

// TestLoadFileReadErrorReturnsDefaults asserts a non-ErrNotExist read failure surfaces the error alongside defaults.
func TestLoadFileReadErrorReturnsDefaults(t *testing.T) {
	got, err := LoadFile(t.TempDir()) // a directory opens fine but cannot be read
	if err == nil {
		t.Fatal("expected read error for a directory path")
	}
	if !reflect.DeepEqual(got, Default()) {
		t.Errorf("LoadFile(dir) = %+v, want defaults", got)
	}
}

// TestLoadFileMalformedYAMLReturnsDefaults asserts a corrupt config file yields defaults plus the parse error.
func TestLoadFileMalformedYAMLReturnsDefaults(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte("this: : : not yaml"), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := LoadFile(path)
	if err == nil {
		t.Error("expected error for a malformed config file")
	}
	if !reflect.DeepEqual(got, Default()) {
		t.Errorf("LoadFile(malformed) = %+v, want defaults", got)
	}
}

// TestSaveErrorsWhenParentIsFile asserts Save surfaces MkdirAll failing on a parent that is a regular file.
func TestSaveErrorsWhenParentIsFile(t *testing.T) {
	block := filepath.Join(t.TempDir(), "block")
	if err := os.WriteFile(block, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := Save(filepath.Join(block, "config.yaml"), Default()); err == nil {
		t.Error("expected error when the parent directory cannot be created")
	}
}

// TestSaveErrorsWhenDirUnwritable asserts a CreateTemp failure surfaces instead of silently losing the config.
func TestSaveErrorsWhenDirUnwritable(t *testing.T) {
	if runtime.GOOS == "windows" || os.Getuid() == 0 {
		t.Skip("permission bits are not enforced here")
	}
	dir := filepath.Join(t.TempDir(), "locked")
	if err := os.Mkdir(dir, 0o555); err != nil {
		t.Fatal(err)
	}
	if err := Save(filepath.Join(dir, "config.yaml"), Default()); err == nil {
		t.Error("expected error when the temp file cannot be created")
	}
}

// TestSaveErrorsWhenDestinationIsDirectory asserts the atomic rename fails rather than clobbering a directory.
func TestSaveErrorsWhenDestinationIsDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.Mkdir(path, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := Save(path, Default()); err == nil {
		t.Error("expected rename error when the destination is a directory")
	}
}

// TestMarshalClampsOutOfRange asserts Marshal never persists out-of-range values.
func TestMarshalClampsOutOfRange(t *testing.T) {
	data, err := Marshal(Config{
		Theme:           "no-such-theme",
		RefreshInterval: MaxRefreshInterval + 1,
		JobHistoryDays:  0,
		LogViewerLines:  MaxLogViewerLines + 1,
		KeybindMode:     "qwerty",
	})
	if err != nil {
		t.Fatalf("Marshal error: %v", err)
	}
	var raw Config
	if err := yaml.Unmarshal(data, &raw); err != nil {
		t.Fatalf("Unmarshal error: %v", err)
	}
	if !reflect.DeepEqual(raw, Default()) {
		t.Errorf("persisted config = %+v, want clamped defaults %+v", raw, Default())
	}
}

// TestDirPrecedence asserts STOEI_CONFIG_DIR beats XDG_CONFIG_HOME, which beats the home fallback.
func TestDirPrecedence(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("home fallback relies on $HOME")
	}
	home := t.TempDir()
	xdg := filepath.Join(home, "xdg")
	cases := []struct {
		name, stoei, xdgEnv, want string
	}{
		{"explicit override wins", "/custom/dir", xdg, "/custom/dir"},
		{"xdg config home second", "", xdg, filepath.Join(xdg, "stoei")},
		{"home fallback last", "", "", filepath.Join(home, ".config", "stoei")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			t.Setenv("STOEI_CONFIG_DIR", c.stoei)
			t.Setenv("XDG_CONFIG_HOME", c.xdgEnv)
			t.Setenv("HOME", home)
			got, err := Dir()
			if err != nil {
				t.Fatalf("Dir error: %v", err)
			}
			if got != c.want {
				t.Errorf("Dir = %q, want %q", got, c.want)
			}
		})
	}
}

// TestDirErrorsWithoutHome asserts Dir and Path fail when no override and no home directory exist.
func TestDirErrorsWithoutHome(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("relies on $HOME")
	}
	t.Setenv("STOEI_CONFIG_DIR", "")
	t.Setenv("XDG_CONFIG_HOME", "")
	t.Setenv("HOME", "")
	if _, err := Dir(); err == nil {
		t.Error("Dir: expected error with no home directory")
	}
	if _, err := Path(); err == nil {
		t.Error("Path: expected error with no home directory")
	}
}

// TestPathAppendsConfigYAML asserts Path joins config.yaml onto the resolved directory.
func TestPathAppendsConfigYAML(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("STOEI_CONFIG_DIR", dir)
	got, err := Path()
	if err != nil {
		t.Fatalf("Path error: %v", err)
	}
	if want := filepath.Join(dir, "config.yaml"); got != want {
		t.Errorf("Path = %q, want %q", got, want)
	}
}
