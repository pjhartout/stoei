package ui

import (
	"os"
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/config"
	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/modals"
)

// TestSettingsKeyOpensModal asserts the settings key ("s" in vim) opens the
// settings modal.
func TestSettingsKeyOpensModal(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})
	a.width, a.height = 100, 30

	a = updateApp(a, tea.KeyPressMsg{Code: 's', Text: "s"})
	if len(a.modals) != 1 {
		t.Fatalf("s should open the settings modal; have %d", len(a.modals))
	}
}

// TestApplyConfigSwapsThemeKeymapIntervals asserts a SettingsAppliedMsg applies
// the new theme, keymap, and refresh intervals live.
func TestApplyConfigSwapsThemeKeymapIntervals(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})
	a.width, a.height = 100, 30

	// Capture the pre-apply state to prove it changed.
	beforeTheme := a.theme.Name
	beforeQuit := a.keys.Quit.Keys()[0]
	beforeFast := a.intervals.Fast
	beforeStyles := a.styles.Title.Render("x")

	newCfg := config.Config{
		Theme:           "dracula",
		RefreshInterval: 30,
		JobHistoryDays:  14,
		LogViewerLines:  20000,
		KeybindMode:     config.KeybindEmacs,
	}

	a = updateApp(a, modals.SettingsAppliedMsg{Config: newCfg})

	if a.theme.Name == beforeTheme {
		t.Errorf("theme not swapped; still %q", a.theme.Name)
	}
	if a.theme.Name != "dracula" {
		t.Errorf("theme = %q, want dracula", a.theme.Name)
	}
	if a.styles.Title.Render("x") == beforeStyles {
		t.Error("styles not rebuilt after theme swap")
	}
	if a.keys.Quit.Keys()[0] == beforeQuit {
		t.Error("keymap not swapped (quit key unchanged)")
	}
	if a.keys.Quit.Keys()[0] != "ctrl+q" {
		t.Errorf("emacs quit key = %q, want ctrl+q", a.keys.Quit.Keys()[0])
	}
	if a.intervals.Fast == beforeFast {
		t.Error("intervals not updated")
	}
	if a.cfg != newCfg {
		t.Errorf("cfg not stored: %+v", a.cfg)
	}
}

// TestApplyConfigSavesFromCmd asserts the config write happens inside the
// returned Cmd (never on the Update path) and actually reaches disk.
func TestApplyConfigSavesFromCmd(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})
	a.configPath = filepath.Join(t.TempDir(), "config.yaml")

	m, cmd := a.Update(modals.SettingsAppliedMsg{Config: config.Default()})
	a = m.(App)

	if _, err := os.Stat(a.configPath); err == nil {
		t.Fatal("config written during Update; the write must happen inside the Cmd")
	}
	var saw bool
	for _, msg := range drainCmd(cmd) {
		if sm, ok := msg.(settingsSavedMsg); ok {
			saw = true
			if sm.err != nil {
				t.Errorf("save failed: %v", sm.err)
			}
		}
	}
	if !saw {
		t.Fatal("applyConfig returned no save Cmd")
	}
	if _, err := os.Stat(a.configPath); err != nil {
		t.Errorf("config not written after draining the Cmd: %v", err)
	}
}

// TestApplyConfigDrivesHistoryWindow asserts the new history-days window is used
// on the refresh dispatched by applyConfig.
func TestApplyConfigDrivesHistoryWindow(t *testing.T) {
	fc := &store.FakeClient{UsernameStr: "alice"}
	a := newTestApp(t, fc)
	a.width, a.height = 100, 30

	newCfg := config.Default()
	newCfg.JobHistoryDays = 21

	m, cmd := a.Update(modals.SettingsAppliedMsg{Config: newCfg})
	a = m.(App)
	if a.cfg.JobHistoryDays != 21 {
		t.Fatalf("history days = %d, want 21", a.cfg.JobHistoryDays)
	}
	// Draining the refresh cmd issues the fetches; the fake records the history
	// window it was asked for.
	drainCmd(cmd)
	if fc.LastHistoryDays != 21 {
		t.Errorf("history fetched with %d days, want 21", fc.LastHistoryDays)
	}
}
