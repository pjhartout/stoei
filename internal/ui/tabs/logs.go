package tabs

import (
	"strings"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/ui/components"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// logTimeLayout is the compact HH:MM:SS time format shown per log line.
const logTimeLayout = "15:04:05"

// Logs renders the application's own log lines from an in-memory ring buffer into
// a scrollable viewport, coloring each line by level. It is kept deliberately
// minimal. The ring is owned by the app and shared by pointer; the tab only reads
// it.
type Logs struct {
	ring   *components.LogRing
	styles theme.Styles
	vp     viewport.Model
	width  int
	height int
}

// NewLogs returns a Logs tab reading from ring.
func NewLogs(ring *components.LogRing, styles theme.Styles) *Logs {
	l := &Logs{ring: ring, styles: styles, vp: viewport.New()}
	l.Refresh()
	return l
}

// SetStyles re-themes the tab and re-renders the buffered lines.
func (l *Logs) SetStyles(styles theme.Styles) {
	l.styles = styles
	l.Refresh()
}

// SetSize resizes the viewport.
func (l *Logs) SetSize(width, height int) {
	l.width = width
	l.height = height
	l.vp.SetWidth(width)
	l.vp.SetHeight(max(height, 1))
}

// Update forwards scroll keys to the viewport.
func (l *Logs) Update(msg tea.Msg) (*Logs, tea.Cmd) {
	var cmd tea.Cmd
	l.vp, cmd = l.vp.Update(msg)
	return l, cmd
}

// Refresh rebuilds the viewport content from the ring's most-recent lines and
// pins the view to the bottom so the latest line stays visible.
func (l *Logs) Refresh() {
	entries := l.ring.Last(components.DefaultMaxLogLines)
	if len(entries) == 0 {
		l.vp.SetContent(l.styles.Subtle.Render("No log entries yet."))
		return
	}
	lines := make([]string, len(entries))
	for i, e := range entries {
		ts := l.styles.Subtle.Render(e.Time.Format(logTimeLayout))
		level := l.levelStyle(e.Level).Render(padLevel(e.Level))
		lines[i] = ts + " " + level + " " + e.Message
	}
	l.vp.SetContent(strings.Join(lines, "\n"))
	l.vp.GotoBottom()
}

// levelStyle returns the style for a log level: INFO/SUCCESS green, WARNING
// yellow, ERROR/CRITICAL red, DEBUG muted, and any other level the default text
// style.
func (l *Logs) levelStyle(level string) lipgloss.Style {
	switch strings.ToUpper(level) {
	case "INFO", "SUCCESS":
		return l.styles.Success
	case "WARNING":
		return l.styles.Warning
	case "ERROR", "CRITICAL":
		return l.styles.Error
	case "DEBUG":
		return l.styles.Muted
	default:
		return l.styles.Text
	}
}

// padLevel renders the level centered within a bracketed, 8-wide field (e.g.
// "[  INFO  ]"), so the tags align in a column.
func padLevel(level string) string {
	const width = 8
	if len(level) >= width {
		return "[" + level + "]"
	}
	total := width - len(level)
	left := total / 2
	right := total - left
	return "[" + strings.Repeat(" ", left) + level + strings.Repeat(" ", right) + "]"
}

// View renders the viewport.
func (l *Logs) View() string { return l.vp.View() }

// CapturesInput reports that the Logs tab never captures raw text input.
func (l *Logs) CapturesInput() bool { return false }

// ShortHelp returns the scroll bindings.
func (l *Logs) ShortHelp() []key.Binding {
	return []key.Binding{l.vp.KeyMap.Up, l.vp.KeyMap.Down}
}

// FullHelp returns the scroll bindings grouped.
func (l *Logs) FullHelp() [][]key.Binding {
	return [][]key.Binding{{l.vp.KeyMap.Up, l.vp.KeyMap.Down, l.vp.KeyMap.PageUp, l.vp.KeyMap.PageDown}}
}
