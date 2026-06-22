package keys

import (
	"testing"

	"charm.land/bubbles/v2/help"
)

// Compile-time check that KeyMap satisfies the bubbles/help.KeyMap interface.
var _ help.KeyMap = KeyMap{}

func TestDefaultBindingsArePopulated(t *testing.T) {
	k := Default()

	if len(k.ShortHelp()) == 0 {
		t.Error("ShortHelp returned no bindings")
	}
	if len(k.FullHelp()) == 0 {
		t.Error("FullHelp returned no binding groups")
	}

	if got := k.Quit.Keys(); len(got) != 2 || got[0] != "q" || got[1] != "ctrl+c" {
		t.Errorf("Quit keys = %v, want [q ctrl+c]", got)
	}
}

// TestBuildKeyMapPresetsDiffer asserts vim and emacs rebind the global actions
// (so the footer/help reflect the active preset) while keeping ctrl+c on quit.
func TestBuildKeyMapPresetsDiffer(t *testing.T) {
	vim := BuildKeyMap(Vim)
	emacs := BuildKeyMap(Emacs)

	if got := vim.Quit.Keys(); got[0] != "q" {
		t.Errorf("vim quit primary = %q, want q", got[0])
	}
	if got := emacs.Quit.Keys(); got[0] != "ctrl+q" {
		t.Errorf("emacs quit primary = %q, want ctrl+q", got[0])
	}

	if vim.Help.Keys()[0] == emacs.Help.Keys()[0] {
		t.Error("vim and emacs share a help key; presets do not differ")
	}
	if vim.Settings.Keys()[0] == emacs.Settings.Keys()[0] {
		t.Error("vim and emacs share a settings key; presets do not differ")
	}
	if vim.Refresh.Keys()[0] == emacs.Refresh.Keys()[0] {
		t.Error("vim and emacs share a refresh key; presets do not differ")
	}

	for _, km := range []KeyMap{vim, emacs} {
		found := false
		for _, k := range km.Quit.Keys() {
			if k == "ctrl+c" {
				found = true
			}
		}
		if !found {
			t.Error("quit must always include ctrl+c")
		}
	}
}

// TestBuildKeyMapUnknownFallsBackToVim asserts an unknown mode yields the vim
// preset (keybindings.DEFAULT_PRESET).
func TestBuildKeyMapUnknownFallsBackToVim(t *testing.T) {
	got := BuildKeyMap("qwerty")
	if got.Help.Keys()[0] != BuildKeyMap(Vim).Help.Keys()[0] {
		t.Error("unknown mode should fall back to vim")
	}
}

// TestHelpReflectsActiveMode asserts the help bar bindings carry the active
// preset's keys, so the footer reflects the mode automatically.
func TestHelpReflectsActiveMode(t *testing.T) {
	emacs := BuildKeyMap(Emacs)
	if emacs.ShortHelp()[0].Keys()[0] != "ctrl+h" {
		t.Errorf("emacs ShortHelp help key = %q, want ctrl+h", emacs.ShortHelp()[0].Keys()[0])
	}
}
