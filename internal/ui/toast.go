package ui

import (
	"strings"

	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/ui/theme"
)

// toastLevel classifies a transient toast for color treatment. It is distinct
// from the health machine's toastKind: it is the rendered severity, derived from
// the kind for health toasts and defaulting to info for manual feedback.
type toastLevel int

const (
	// toastInfo is a neutral, accent-bordered notice (manual feedback).
	toastInfo toastLevel = iota
	// toastError is a failure notice (error-bordered).
	toastErrorLevel
	// toastSuccess is a recovery/success notice (success-bordered).
	toastSuccess
)

// toastTTL is how many fast ticks a toast remains visible before it auto-expires.
// At the default ~5s fast interval this keeps a toast on screen for a few cycles
// without lingering indefinitely.
const toastTTL = 3

// toastItem is one transient on-screen toast: its text, severity level, and the
// number of fast ticks remaining before it auto-expires.
type toastItem struct {
	text  string
	level toastLevel
	ticks int
}

// toastBorderColor maps a toast level to its border color from the styles.
func toastBorderColor(level toastLevel, styles theme.Styles) lipgloss.Style {
	switch level {
	case toastErrorLevel:
		return styles.Error
	case toastSuccess:
		return styles.Success
	default:
		return styles.Subtle
	}
}

// toastChrome is the horizontal space a toast's rounded border (2) and
// horizontal padding (2) consume around its text.
const toastChrome = 4

// renderToasts renders the toast stack as charm-style boxed, accent/error/
// success-bordered transient notices. An empty stack renders to "". Each box is
// capped to maxWidth so a long message (e.g. a slurmdbd connection-refused
// notice) wraps inside the border instead of overflowing the terminal.
func renderToasts(toasts []toastItem, maxWidth int, styles theme.Styles) string {
	if len(toasts) == 0 {
		return ""
	}
	boxes := make([]string, len(toasts))
	for i, t := range toasts {
		accent := toastBorderColor(t.level, styles)
		box := lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(accent.GetForeground()).
			Padding(0, 1)
		if inner := maxWidth - toastChrome; inner > 0 && lipgloss.Width(t.text) > inner {
			box = box.Width(inner)
		}
		boxes[i] = box.Render(accent.Render(t.text))
	}
	return strings.Join(boxes, "\n")
}
