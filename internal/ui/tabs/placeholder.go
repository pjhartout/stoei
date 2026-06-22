package tabs

import (
	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/ui/theme"
)

// Placeholder is a stand-in tab for sections not yet implemented (Nodes, Users,
// Priority, Logs land in Phase 4). It renders a centered "coming in phase 4"
// notice so the app stays fully navigable. It satisfies the same Component shape
// as the real tabs.
type Placeholder struct {
	title  string
	styles theme.Styles
	width  int
	height int
}

// NewPlaceholder returns a Placeholder tab labelled title.
func NewPlaceholder(title string, styles theme.Styles) *Placeholder {
	return &Placeholder{title: title, styles: styles}
}

// Update is a no-op: placeholders consume no input.
func (p *Placeholder) Update(_ tea.Msg) (*Placeholder, tea.Cmd) { return p, nil }

// SetSize records the available area for centering.
func (p *Placeholder) SetSize(width, height int) {
	p.width = width
	p.height = height
}

// SetStyles re-themes the placeholder.
func (p *Placeholder) SetStyles(styles theme.Styles) { p.styles = styles }

// View renders the centered notice.
func (p *Placeholder) View() string {
	msg := p.styles.Subtle.Render(p.title + " — coming in phase 4")
	if p.width <= 0 || p.height <= 0 {
		return msg
	}
	return lipgloss.Place(p.width, p.height, lipgloss.Center, lipgloss.Center, msg)
}

// ShortHelp returns no tab-local bindings.
func (p *Placeholder) ShortHelp() []key.Binding { return nil }

// FullHelp returns no tab-local bindings.
func (p *Placeholder) FullHelp() [][]key.Binding { return nil }
