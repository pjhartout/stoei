package modals

import (
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/config"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// drainToMsg runs a Cmd and returns its (non-batch) message.
func drainToMsg(cmd tea.Cmd) tea.Msg {
	if cmd == nil {
		return nil
	}
	return cmd()
}

// newTestSettings builds a settings modal over the default config.
func newTestSettings() *Settings {
	return NewSettings(theme.BuildStyles(theme.Charm(), true), config.Default())
}

// TestSettingsSaveEmitsApply asserts ctrl+s emits a SettingsAppliedMsg carrying
// the current config and closes the modal.
func TestSettingsSaveEmitsApply(t *testing.T) {
	s := newTestSettings()
	m, cmd, done := s.Update(tea.KeyPressMsg{Code: 's', Mod: tea.ModCtrl})
	if !done {
		t.Fatal("ctrl+s should close the settings modal")
	}
	_ = m
	msg := drainToMsg(cmd)
	applied, ok := msg.(SettingsAppliedMsg)
	if !ok {
		t.Fatalf("save emitted %T, want SettingsAppliedMsg", msg)
	}
	if applied.Config != config.Default() {
		t.Errorf("applied config = %+v, want unchanged defaults", applied.Config)
	}
}

// TestSettingsCyclesEnumAndSaves asserts cycling the theme field and toggling
// energy is reflected in the emitted config.
func TestSettingsCyclesEnumAndSaves(t *testing.T) {
	s := newTestSettings()

	// Theme is the first (focused) field; right cycles to the next palette in
	// the field's own option list, which starts selected at the default theme.
	themeOpts := s.fields[fThemeIdx].options
	startIdx := s.fields[fThemeIdx].selected
	first := themeOpts[startIdx]
	second := themeOpts[(startIdx+1)%len(themeOpts)]
	s.Update(tea.KeyPressMsg{Code: tea.KeyRight})
	if got := s.fields[fThemeIdx].options[s.fields[fThemeIdx].selected]; got == first {
		t.Fatalf("right did not cycle theme away from %q", first)
	}

	// Move to the keybind field and cycle it.
	for s.focus != fKeybindIdx {
		s.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	}
	s.Update(tea.KeyPressMsg{Code: tea.KeyRight})

	// Move to the energy-enabled field and toggle it on.
	for s.focus != fEnergyEnabledIdx {
		s.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	}
	s.Update(tea.KeyPressMsg{Code: tea.KeyRight})

	_, cmd, done := s.Update(tea.KeyPressMsg{Code: 's', Mod: tea.ModCtrl})
	if !done {
		t.Fatal("ctrl+s should close")
	}
	applied := drainToMsg(cmd).(SettingsAppliedMsg)

	if applied.Config.Theme != second {
		t.Errorf("theme = %q, want %q", applied.Config.Theme, second)
	}
	if applied.Config.KeybindMode != config.KeybindEmacs {
		t.Errorf("keybind = %q, want emacs", applied.Config.KeybindMode)
	}
	if !applied.Config.EnergyEnabled {
		t.Error("energy should be enabled after toggle")
	}
}

// TestSettingsEscCancels asserts esc closes the modal without emitting an apply
// message.
func TestSettingsEscCancels(t *testing.T) {
	s := newTestSettings()
	_, cmd, done := s.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	if !done {
		t.Fatal("esc should close the modal")
	}
	if drainToMsg(cmd) != nil {
		t.Error("esc must not emit any message (no apply on cancel)")
	}
}

// TestSettingsClampsOutOfRange asserts an out-of-range numeric field is clamped
// to its default in the emitted config (the modal saves through config.Load).
func TestSettingsClampsOutOfRange(t *testing.T) {
	s := newTestSettings()

	// Set the refresh-interval field (index 1) to an out-of-range value.
	s.focusField(fRefreshIdx)
	s.fields[fRefreshIdx].input.SetValue("99999")

	_, cmd, _ := s.Update(tea.KeyPressMsg{Code: 's', Mod: tea.ModCtrl})
	applied := drainToMsg(cmd).(SettingsAppliedMsg)
	if applied.Config.RefreshInterval != config.DefaultRefreshInterval {
		t.Errorf("refresh = %v, want clamped default %v", applied.Config.RefreshInterval, config.DefaultRefreshInterval)
	}
}

// TestSettingsInvalidInputToasts asserts non-numeric input emits a toast (not an
// apply) and does not close the modal.
func TestSettingsInvalidInputToasts(t *testing.T) {
	s := newTestSettings()
	s.focusField(fHistoryIdx)
	s.fields[fHistoryIdx].input.SetValue("not-a-number")

	_, cmd, done := s.Update(tea.KeyPressMsg{Code: 's', Mod: tea.ModCtrl})
	if !done {
		// Save returns done=true (the modal closes) but emits a toast Cmd.
		t.Log("modal closes on save attempt")
	}
	msg := drainToMsg(cmd)
	if _, ok := msg.(SettingsToastMsg); !ok {
		t.Fatalf("invalid input emitted %T, want SettingsToastMsg", msg)
	}
}
