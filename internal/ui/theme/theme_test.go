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

// TestContrastFgPicksReadableText asserts light fills get dark text and dark
// fills get light text.
func TestContrastFgPicksReadableText(t *testing.T) {
	if got := ContrastFg(lipgloss.Color("#ffffff")); got != lipgloss.Color("#1A1A1A") {
		t.Errorf("ContrastFg(white) = %v; want dark text", got)
	}
	if got := ContrastFg(lipgloss.Color("#101010")); got != lipgloss.Color("#F5F5F5") {
		t.Errorf("ContrastFg(near-black) = %v; want light text", got)
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

// TestBrandChipPreservesRunes asserts the gradient-background chip keeps the
// visible text intact (with its padding spaces) and actually styles it.
func TestBrandChipPreservesRunes(t *testing.T) {
	st := BuildStyles(Charm(), true)
	out := st.BrandChip("stoei")
	if plain := stripANSI(out); plain != " stoei " {
		t.Errorf("chip visible text = %q; want %q", plain, " stoei ")
	}
	if !strings.Contains(out, "\x1b[") {
		t.Error("chip produced no ANSI styling")
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
