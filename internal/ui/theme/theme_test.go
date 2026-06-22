package theme

import (
	"testing"

	"charm.land/lipgloss/v2"
)

func TestResolvePicksVariantByMode(t *testing.T) {
	c := AdaptiveColor{
		Light: lipgloss.Color("#000000"),
		Dark:  lipgloss.Color("#ffffff"),
	}
	if got := c.Resolve(true); got != c.Dark {
		t.Errorf("Resolve(dark) = %v, want %v", got, c.Dark)
	}
	if got := c.Resolve(false); got != c.Light {
		t.Errorf("Resolve(light) = %v, want %v", got, c.Light)
	}
}

func TestBuildStylesRendersDistinctModes(t *testing.T) {
	th := Charm()
	dark := BuildStyles(th, true)
	light := BuildStyles(th, false)

	// Styles must produce non-empty output and differ between modes (the accent
	// colors differ), proving the adaptive resolution actually flows through.
	d := dark.Title.Render("stoei")
	l := light.Title.Render("stoei")
	if d == "" || l == "" {
		t.Fatal("rendered title is empty")
	}
	if d == l {
		t.Error("dark and light titles render identically; adaptive color not applied")
	}
}

func TestAccentGradientReturnsRequestedSteps(t *testing.T) {
	g := AccentGradient(Charm(), true, 5)
	if len(g) != 5 {
		t.Fatalf("gradient steps = %d, want 5", len(g))
	}
}
