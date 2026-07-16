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
	toastError
	// toastSuccess is a recovery/success notice (success-bordered).
	toastSuccess
)

// toastTTL is how many toast ticks a toast remains visible before it auto-expires.
// At the 10s toast cadence this keeps a transient notice on screen ~20s — long
// enough to read, short enough not to linger after the action it reported.
const toastTTL = 2

// toastItem is one transient on-screen toast: its text, severity level, the
// number of toast ticks remaining before it auto-expires, and an optional tag so
// a progress toast (e.g. the manual-refresh notice) can be dropped early by the
// event it was waiting on.
type toastItem struct {
	text  string
	level toastLevel
	ticks int
	tag   string
}

// refreshToastTag marks the manual-refresh progress toast: it animates a spinner
// while the fetch is in flight and is dropped the moment the result lands.
const refreshToastTag = "refresh"

// toastBorderColor maps a toast level to its border color from the styles.
func toastBorderColor(level toastLevel, styles theme.Styles) lipgloss.Style {
	switch level {
	case toastError:
		return styles.Error
	case toastSuccess:
		return styles.Success
	default:
		// Info toasts are manual-action feedback; the accent border keeps them
		// distinct from passive subtle text.
		return lipgloss.NewStyle().Foreground(styles.Accent)
	}
}

// toastSpinnerFrames are the braille frames prefixed to an in-flight progress
// toast, advanced by the chrome animation phase.
var toastSpinnerFrames = []string{"⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"}

// toastSpinnerDivisor slows the toast spinner relative to the ~30 fps anim
// phase so it turns at the classic ~7 fps braille cadence.
const toastSpinnerDivisor = 4

// toastChrome is the horizontal space a toast's rounded border (2) and
// horizontal padding (2) consume around its text.
const toastChrome = 4

// renderToasts renders the toast stack as charm-style boxed, accent/error/
// success-bordered transient notices. An empty stack renders to "". Each box is
// capped to maxWidth so a long message (e.g. a slurmdbd connection-refused
// notice) wraps inside the border instead of overflowing the terminal. phase is
// the chrome animation phase: a tagged progress toast gets a spinner frame from
// it, so the spinner turns while the anim tier runs.
func renderToasts(toasts []toastItem, maxWidth int, styles theme.Styles, phase int) string {
	if len(toasts) == 0 {
		return ""
	}
	boxes := make([]string, len(toasts))
	for i, t := range toasts {
		accent := toastBorderColor(t.level, styles)
		// A toast on its final tick fades to the muted tone before expiring, so
		// it dims out instead of popping off screen. This rides the existing
		// toast tick — no extra animation frames. Progress toasts stay bright:
		// they are dropped by their completion event, not by fading.
		if t.ticks <= 1 && t.tag == "" {
			accent = styles.Muted
		}
		text := t.text
		if t.tag != "" {
			text = toastSpinnerFrames[phase/toastSpinnerDivisor%len(toastSpinnerFrames)] + " " + text
		}
		box := lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(accent.GetForeground()).
			Padding(0, 1)
		if inner := maxWidth - toastChrome; inner > 0 && lipgloss.Width(text) > inner {
			box = box.Width(inner)
		}
		boxes[i] = box.Render(accent.Render(text))
	}
	return strings.Join(boxes, "\n")
}
