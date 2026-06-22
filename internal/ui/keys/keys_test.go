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
