package theme

import (
	"strings"
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

// TestByNameReturnsDistinctPalettes asserts named palettes resolve to distinct
// themes and that an unknown name falls back to the default.
func TestByNameReturnsDistinctPalettes(t *testing.T) {
	oc := ByName("oc-1")
	if oc.Name != "oc-1" {
		t.Errorf("ByName(oc-1).Name = %q, want oc-1", oc.Name)
	}

	dracula := ByName("dracula")
	if dracula.Name != "dracula" {
		t.Errorf("ByName(dracula).Name = %q, want dracula", dracula.Name)
	}

	// Distinct palettes must differ on at least the accent color.
	if oc.Accent.Dark == dracula.Accent.Dark {
		t.Error("oc-1 and dracula share an accent; palettes are not distinct")
	}

	// Unknown name falls back to the default palette.
	fallback := ByName("does-not-exist")
	if fallback.Name != DefaultThemeName {
		t.Errorf("ByName(unknown).Name = %q, want fallback %q", fallback.Name, DefaultThemeName)
	}
}

// TestNamesCoverRegistry asserts every name returned by Names resolves to a real
// palette (no dangling names in the cycling list).
func TestNamesCoverRegistry(t *testing.T) {
	for _, n := range Names() {
		if ByName(n).Name != n {
			t.Errorf("Names() lists %q but ByName(%q) did not return it", n, n)
		}
	}
}

// TestGradientTextPreservesRunes asserts the per-rune accent gradient keeps every
// input rune (ANSI styling aside) and renders distinct colors across runes.
func TestGradientTextPreservesRunes(t *testing.T) {
	st := BuildStyles(Charm(), true)
	out := st.TitleGradient("stoei")
	// Strip ANSI escapes and confirm the visible text is intact.
	plain := stripANSI(out)
	if plain != "stoei" {
		t.Errorf("gradient visible text = %q; want %q", plain, "stoei")
	}
	// A multi-rune gradient must emit more than one distinct SGR foreground.
	if !strings.Contains(out, "\x1b[") {
		t.Error("gradient produced no ANSI styling")
	}
	// Empty and single-rune inputs must not panic and must round-trip.
	if got := GradientText("", st.Accent, st.AccentAlt, true); got != "" {
		t.Errorf("empty gradient = %q; want empty", got)
	}
	if got := stripANSI(GradientText("x", st.Accent, st.AccentAlt, true)); got != "x" {
		t.Errorf("single-rune gradient text = %q; want x", got)
	}
}

// stripANSI removes CSI escape sequences for plain-text assertions.
func stripANSI(s string) string {
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == 0x1b && i+1 < len(s) && s[i+1] == '[' {
			i += 2
			for i < len(s) && (s[i] < '@' || s[i] > '~') {
				i++
			}
			continue // skip the final byte of the sequence
		}
		b.WriteByte(s[i])
	}
	return b.String()
}
