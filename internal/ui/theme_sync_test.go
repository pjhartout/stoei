package ui

import (
	"sort"
	"testing"

	"github.com/pjhartout/stoei/internal/config"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// TestValidThemesMatchPalettes is the cross-package guard that pins the accepted
// theme set (config.ValidThemes, what Load validates and the settings modal
// rejects) to the implemented set (theme.Names, what the settings modal offers
// and theme.ByName can render). They MUST be equal as sets: a name config
// accepts but theme.ByName cannot render would silently fall back to oc-1, and a
// name the settings modal offers but config rejects would be clamped away on
// save. config production code cannot import the Charm-backed theme package
// (depguard), so this test-only import is the seam that keeps the two lists
// honest.
func TestValidThemesMatchPalettes(t *testing.T) {
	names := theme.Names()
	valid := config.ValidThemes

	if len(names) != len(valid) {
		t.Fatalf("theme.Names has %d entries, config.ValidThemes has %d; they must match: names=%v valid=%v",
			len(names), len(valid), names, valid)
	}

	gotNames := append([]string(nil), names...)
	gotValid := append([]string(nil), valid...)
	sort.Strings(gotNames)
	sort.Strings(gotValid)

	for i := range gotNames {
		if gotNames[i] != gotValid[i] {
			t.Fatalf("theme.Names and config.ValidThemes differ as sets: names=%v valid=%v",
				gotNames, gotValid)
		}
	}

	// Every accepted name must resolve to its own (non-fallback) palette, so
	// selecting it in the settings modal renders that theme rather than oc-1.
	for _, n := range valid {
		got := theme.ByName(n)
		if got.Name != n {
			t.Errorf("config.ValidThemes lists %q but theme.ByName(%q).Name = %q (fell back to default); the palette is unimplemented",
				n, n, got.Name)
		}
	}
}

// TestPalettesAreDistinct asserts the implemented palettes are not stubbed to a
// shared set of colors: every name must have a distinct accent color, so each
// theme renders visibly differently rather than all looking like oc-1.
func TestPalettesAreDistinct(t *testing.T) {
	seen := make(map[any]string, len(theme.Names()))
	for _, n := range theme.Names() {
		accent := theme.ByName(n).Accent.Dark
		if prev, dup := seen[accent]; dup {
			t.Errorf("themes %q and %q share accent color %v; palettes are not distinct", prev, n, accent)
			continue
		}
		seen[accent] = n
	}
}
