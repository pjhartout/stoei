// Package theme defines the color palette and prebuilt lipgloss styles for the
// UI. Lipgloss v2 has no AdaptiveColor type: colors are plain image/color.Color
// values and light/dark selection happens at render time via lipgloss.LightDark.
// We model that by storing a light and a dark variant for each role in an
// AdaptiveColor pair and resolving them once in BuildStyles, so the rest of the
// UI works with concrete, already-resolved styles.
package theme

import (
	"image/color"

	"charm.land/lipgloss/v2"
)

// AdaptiveColor is a light/dark color pair. It is the v2 replacement for the
// removed lipgloss.AdaptiveColor: the active variant is chosen by Resolve using
// the terminal's detected background.
type AdaptiveColor struct {
	Light color.Color
	Dark  color.Color
}

// Resolve returns the variant matching the terminal background. When dark is
// true the Dark variant is returned, otherwise the Light variant.
func (a AdaptiveColor) Resolve(dark bool) color.Color {
	return lipgloss.LightDark(dark)(a.Light, a.Dark)
}

// Theme is a pure data palette. It carries no lipgloss styles itself so it can
// be defined as a plain value (including future config-loaded themes) without
// committing to a light or dark rendering.
type Theme struct {
	// Name identifies the palette (e.g. "charm").
	Name string

	// Accent is the primary brand color used for titles and the active tab.
	Accent AdaptiveColor
	// AccentAlt is the secondary gradient stop paired with Accent.
	AccentAlt AdaptiveColor
	// Text is the default foreground.
	Text AdaptiveColor
	// Subtle is a dimmed foreground for secondary text and help.
	Subtle AdaptiveColor
	// Border is the default border color.
	Border AdaptiveColor
	// Error is the foreground used for error states.
	Error AdaptiveColor
}

// Styles holds prebuilt lipgloss styles with all adaptive colors already
// resolved for a single light/dark mode. The UI renders from these and never
// re-resolves colors per frame.
type Styles struct {
	// Title styles the application title bar.
	Title lipgloss.Style
	// TabActive styles the selected tab.
	TabActive lipgloss.Style
	// TabInactive styles unselected tabs.
	TabInactive lipgloss.Style
	// Text is the default body text style.
	Text lipgloss.Style
	// Subtle styles secondary/help text.
	Subtle lipgloss.Style
	// Modal styles the bordered overlay box.
	Modal lipgloss.Style
	// Error styles error messages.
	Error lipgloss.Style
}

// Charm returns the default charm.land-flavored palette.
func Charm() Theme {
	return Theme{
		Name:      "charm",
		Accent:    AdaptiveColor{Light: lipgloss.Color("#7D56F4"), Dark: lipgloss.Color("#A78BFA")},
		AccentAlt: AdaptiveColor{Light: lipgloss.Color("#43BF6D"), Dark: lipgloss.Color("#6EE7A7")},
		Text:      AdaptiveColor{Light: lipgloss.Color("#1A1A1A"), Dark: lipgloss.Color("#EAEAEA")},
		Subtle:    AdaptiveColor{Light: lipgloss.Color("#6C6C6C"), Dark: lipgloss.Color("#9B9B9B")},
		Border:    AdaptiveColor{Light: lipgloss.Color("#B0B0B0"), Dark: lipgloss.Color("#3A3A3A")},
		Error:     AdaptiveColor{Light: lipgloss.Color("#D7263D"), Dark: lipgloss.Color("#FF5C72")},
	}
}

// BuildStyles resolves t for the given background mode and returns prebuilt
// styles. Call this once per theme/background change (for example on a
// BackgroundColorMsg), not on every frame.
func BuildStyles(t Theme, dark bool) Styles {
	accent := t.Accent.Resolve(dark)
	accentAlt := t.AccentAlt.Resolve(dark)
	text := t.Text.Resolve(dark)
	subtle := t.Subtle.Resolve(dark)
	border := t.Border.Resolve(dark)
	errc := t.Error.Resolve(dark)

	return Styles{
		Title: lipgloss.NewStyle().
			Bold(true).
			Foreground(accent).
			Padding(0, 1),
		TabActive: lipgloss.NewStyle().
			Bold(true).
			Foreground(accentAlt).
			Padding(0, 1),
		TabInactive: lipgloss.NewStyle().
			Foreground(subtle).
			Padding(0, 1),
		Text: lipgloss.NewStyle().
			Foreground(text),
		Subtle: lipgloss.NewStyle().
			Foreground(subtle),
		Modal: lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(border).
			Foreground(text).
			Padding(1, 2),
		Error: lipgloss.NewStyle().
			Bold(true).
			Foreground(errc),
	}
}

// AccentGradient returns steps colors blended from Accent to AccentAlt for the
// given mode, suitable for a per-rune gradient on the title or tab bar. It is a
// thin wrapper over lipgloss.Blend1D, the v2 gradient primitive.
func AccentGradient(t Theme, dark bool, steps int) []color.Color {
	return lipgloss.Blend1D(steps, t.Accent.Resolve(dark), t.AccentAlt.Resolve(dark))
}
