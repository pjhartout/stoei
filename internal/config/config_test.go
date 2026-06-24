package config

import (
	"reflect"
	"testing"
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
