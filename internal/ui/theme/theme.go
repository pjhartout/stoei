// Package theme defines the color palette and prebuilt lipgloss styles for the
// UI. Lipgloss v2 has no AdaptiveColor type: colors are plain image/color.Color
// values and light/dark selection happens at render time via lipgloss.LightDark.
// We model that by storing a light and a dark variant for each role in an
// AdaptiveColor pair and resolving them once in BuildStyles, so the rest of the
// UI works with concrete, already-resolved styles.
package theme

import (
	"image/color"
	"strings"

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
	// Success is the foreground for healthy/running states (green).
	Success AdaptiveColor
	// Warning is the foreground for pending/transitional states (yellow).
	Warning AdaptiveColor
	// Muted is the dimmed foreground for cancelled/inactive states.
	Muted AdaptiveColor
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
	// Success styles healthy/running text (green).
	Success lipgloss.Style
	// Warning styles pending/transitional text (yellow).
	Warning lipgloss.Style
	// Muted styles cancelled/inactive text.
	Muted lipgloss.Style

	// Accent and AccentAlt are the resolved gradient stop colors for the current
	// background, kept so the UI can render an accent gradient (GradientText)
	// without re-resolving the palette per frame.
	Accent    color.Color
	AccentAlt color.Color
}

// TitleGradient renders s with the resolved accent→accentAlt per-rune gradient,
// bold, matching the Title style's weight. It is the convenience entry point the
// chrome uses for the "stoei" title.
func (s Styles) TitleGradient(text string) string {
	return GradientText(text, s.Accent, s.AccentAlt, true)
}

// DefaultThemeName is the default palette name, matching config.DefaultTheme.
// nord is a calm Nord-style frost/polar-night scheme.
const DefaultThemeName = "nord"

// solid wraps a single hex color as an AdaptiveColor whose light and dark
// variants are identical. The ported OpenCode palettes are dark-first single
// colors (themes.py uses dark=True with one value per role), so light and dark
// resolve to the same color; the charm palette keeps distinct light/dark pairs.
func solid(hex string) AdaptiveColor {
	c := lipgloss.Color(hex)
	return AdaptiveColor{Light: c, Dark: c}
}

// palettes is the registry of named themes, keyed by theme id. It is built from
// the OpenCode palettes ported from themes.py plus the original charm palette.
// Roles map from the OpenCode palette: Accent←primary, AccentAlt←accent,
// Text←text_base, Subtle←text_muted, Border←border, Error/Success/Warning from
// the semantic colors, Muted←secondary.
var palettes = func() map[string]Theme {
	ts := []Theme{
		Charm(),
		opencode("oc-1", "#fab283", "#034cff", "#f5f5f5", "#b8b0b0", "#3a3333", "#fc533a", "#12c905", "#fcd53a", "#716c6b"),
		opencode("tokyonight", "#7aa2f7", "#7aa2f7", "#c0caf5", "#7a88cf", "#3a3e57", "#f7768e", "#9ece6a", "#e0af68", "#1a1b26"),
		opencode("dracula", "#bd93f9", "#bd93f9", "#f8f8f2", "#b6b9e4", "#3f415a", "#ff5555", "#50fa7b", "#ffb86c", "#1d1e28"),
		opencode("monokai", "#ae81ff", "#ae81ff", "#f8f8f2", "#c5c5c0", "#494a3a", "#f92672", "#a6e22e", "#fd971f", "#272822"),
		opencode("solarized", "#6c71c4", "#6c71c4", "#93a1a1", "#6c7f80", "#31505b", "#dc322f", "#859900", "#b58900", "#002b36"),
		opencode("nord", "#88c0d0", "#88c0d0", "#e5e9f0", "#d8dee9", "#4c566a", "#bf616a", "#a3be8c", "#ebcb8b", "#2e3440"),
		opencode("catppuccin", "#b4befe", "#b4befe", "#cdd6f4", "#a6adc8", "#4a4763", "#f38ba8", "#a6d189", "#f4b8e4", "#1e1e2e"),
		opencode("ayu", "#39bae6", "#39bae6", "#ced0d6", "#8f9aa5", "#3d4555", "#ff8f77", "#7fd962", "#ebb062", "#0f1419"),
		opencode("onedarkpro", "#61afef", "#61afef", "#abb2bf", "#818899", "#4a5164", "#e06c75", "#98c379", "#e5c07b", "#1e222a"),
		opencode("shadesofpurple", "#c792ff", "#c792ff", "#f5f0ff", "#c9b6ff", "#4d3a73", "#ff7ac6", "#7be0b0", "#ffd580", "#1a102b"),
		opencode("nightowl", "#82aaff", "#82aaff", "#d6deeb", "#5f7e97", "#3a5a75", "#ef5350", "#c5e478", "#ecc48d", "#011627"),
		opencode("vesper", "#ffc799", "#ffc799", "#ffffff", "#a0a0a0", "#282828", "#ff8080", "#99ffe4", "#ffc799", "#101010"),
		opencode("gruvbox", "#fabd2f", "#83a598", "#ebdbb2", "#a89984", "#504945", "#fb4934", "#b8bb26", "#fe8019", "#928374"),
	}
	m := make(map[string]Theme, len(ts))
	for _, t := range ts {
		m[t.Name] = t
	}
	return m
}()

// opencode builds a Theme from an OpenCode-style palette of single hex colors
// (dark-first; light and dark variants are identical). Ports
// themes.OpencodeThemePalette → role mapping.
func opencode(name, primary, accent, text, muted, border, errc, success, warning, secondary string) Theme {
	return Theme{
		Name:      name,
		Accent:    solid(primary),
		AccentAlt: solid(accent),
		Text:      solid(text),
		Subtle:    solid(muted),
		Border:    solid(border),
		Error:     solid(errc),
		Success:   solid(success),
		Warning:   solid(warning),
		Muted:     solid(secondary),
	}
}

// ByName returns the named palette, falling back to the default (oc-1) for an
// unknown name. Ports the THEME_LABELS lookup with the DEFAULT_THEME_NAME
// fallback in settings.from_mapping.
func ByName(name string) Theme {
	if t, ok := palettes[name]; ok {
		return t
	}
	return palettes[DefaultThemeName]
}

// Names returns the registered theme names in a stable, registry-insertion-free
// order matching the config ValidThemes/cycling order the settings form uses.
func Names() []string {
	return []string{
		"oc-1",
		"tokyonight",
		"dracula",
		"monokai",
		"solarized",
		"nord",
		"catppuccin",
		"ayu",
		"onedarkpro",
		"shadesofpurple",
		"nightowl",
		"vesper",
		"gruvbox",
		"charm",
	}
}

// Charm returns the default charm.land-flavored palette. It retains distinct
// light/dark variants (the only adaptive palette); the ported OpenCode palettes
// are dark-first.
func Charm() Theme {
	return Theme{
		Name:      "charm",
		Accent:    AdaptiveColor{Light: lipgloss.Color("#7D56F4"), Dark: lipgloss.Color("#A78BFA")},
		AccentAlt: AdaptiveColor{Light: lipgloss.Color("#43BF6D"), Dark: lipgloss.Color("#6EE7A7")},
		Text:      AdaptiveColor{Light: lipgloss.Color("#1A1A1A"), Dark: lipgloss.Color("#EAEAEA")},
		Subtle:    AdaptiveColor{Light: lipgloss.Color("#6C6C6C"), Dark: lipgloss.Color("#9B9B9B")},
		Border:    AdaptiveColor{Light: lipgloss.Color("#B0B0B0"), Dark: lipgloss.Color("#3A3A3A")},
		Error:     AdaptiveColor{Light: lipgloss.Color("#D7263D"), Dark: lipgloss.Color("#FF5C72")},
		Success:   AdaptiveColor{Light: lipgloss.Color("#43BF6D"), Dark: lipgloss.Color("#A3BE8C")},
		Warning:   AdaptiveColor{Light: lipgloss.Color("#C7951B"), Dark: lipgloss.Color("#EBCB8B")},
		Muted:     AdaptiveColor{Light: lipgloss.Color("#8A8A8A"), Dark: lipgloss.Color("#6C7086")},
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
	success := t.Success.Resolve(dark)
	warning := t.Warning.Resolve(dark)
	muted := t.Muted.Resolve(dark)

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
		Success: lipgloss.NewStyle().
			Foreground(success),
		Warning: lipgloss.NewStyle().
			Foreground(warning),
		Muted: lipgloss.NewStyle().
			Foreground(muted),
		Accent:    accent,
		AccentAlt: accentAlt,
	}
}

// Default percent-color thresholds, mirroring colors.ThemeColors.pct_color.
const (
	// PctHighThreshold is the high/critical threshold (default 90%).
	PctHighThreshold = 90.0
	// PctMidThreshold is the medium/warning threshold (default 70%).
	PctMidThreshold = 70.0
	// SidebarGreenThreshold is the sidebar's "good" threshold for free resources.
	SidebarGreenThreshold = 50.0
	// SidebarYellowThreshold is the sidebar's "warning" threshold for free
	// resources.
	SidebarYellowThreshold = 25.0
)

// PctStyle returns the style for a percentage given high/mid thresholds. When
// invert is false high values are bad (>=high error, >=mid warning, else
// success); when invert is true high values are good (the reverse). Ports
// colors.ThemeColors.pct_color.
func (s Styles) PctStyle(pct, high, mid float64, invert bool) lipgloss.Style {
	if invert {
		switch {
		case pct >= high:
			return s.Success
		case pct >= mid:
			return s.Warning
		default:
			return s.Error
		}
	}
	switch {
	case pct >= high:
		return s.Error
	case pct >= mid:
		return s.Warning
	default:
		return s.Success
	}
}

// StateRoleStyle maps a semantic state role (as returned by store.StateRole:
// "success", "warning", "error", "muted", or "" for the default) to the matching
// style, so the tables and detail modals color a given Slurm state identically.
func (s Styles) StateRoleStyle(role string) lipgloss.Style {
	switch role {
	case "success":
		return s.Success
	case "warning":
		return s.Warning
	case "error":
		return s.Error
	case "muted":
		return s.Muted
	default:
		return s.Text
	}
}

// AccentGradient returns steps colors blended from Accent to AccentAlt for the
// given mode, suitable for a per-rune gradient on the title or tab bar. It is a
// thin wrapper over lipgloss.Blend1D, the v2 gradient primitive.
func AccentGradient(t Theme, dark bool, steps int) []color.Color {
	return lipgloss.Blend1D(steps, t.Accent.Resolve(dark), t.AccentAlt.Resolve(dark))
}

// GradientText renders s with a per-rune accent→accentAlt gradient (the
// charm.land "rainbow title" look), preserving the runes verbatim. The gradient
// is computed once over the rune count via lipgloss.Blend1D. When s has fewer
// than two runes the accent color is applied flat. The text is bold to match the
// Title style. Whitespace runes are emitted uncolored so spaces don't carry
// stray styling.
func GradientText(s string, accent, accentAlt color.Color, bold bool) string {
	runes := []rune(s)
	if len(runes) == 0 {
		return ""
	}
	base := lipgloss.NewStyle().Bold(bold)
	if len(runes) == 1 {
		return base.Foreground(accent).Render(string(runes))
	}
	colors := lipgloss.Blend1D(len(runes), accent, accentAlt)
	var b strings.Builder
	for i, r := range runes {
		if r == ' ' {
			b.WriteRune(r)
			continue
		}
		b.WriteString(base.Foreground(colors[i]).Render(string(r)))
	}
	return b.String()
}
