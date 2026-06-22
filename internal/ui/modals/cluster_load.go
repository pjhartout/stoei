package modals

import (
	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/components"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// ClusterLoad is a scrollable modal showing the full cluster-load statistics —
// the same content as the sidebar — so all of it is reachable when the sidebar
// is taller than the screen. It is dismissed with esc or q.
type ClusterLoad struct {
	box    scrollBox
	stats  store.ClusterStats
	loaded bool
}

// NewClusterLoad builds the cluster-load modal from the current stats. loaded is
// false before the first nodes fetch, which shows a loading placeholder.
func NewClusterLoad(stats store.ClusterStats, loaded bool, styles theme.Styles) *ClusterLoad {
	c := &ClusterLoad{box: newScrollBox(styles), stats: stats, loaded: loaded}
	c.box.SetTitle("Cluster Load")
	c.box.SetFooter("↑/↓ PgUp/PgDn scroll   g/G top/bottom   Esc to close")
	c.box.SetContent(components.ClusterLoadContent(stats, styles, loaded))
	return c
}

// Init has nothing to start for the cluster-load modal.
func (c *ClusterLoad) Init() tea.Cmd { return nil }

// Update closes on esc/q and otherwise forwards scrolling keys to the box.
func (c *ClusterLoad) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	if km, ok := msg.(tea.KeyPressMsg); ok && isCloseKey(km) {
		return c, nil, true
	}
	cmd := c.box.ScrollUpdate(msg)
	return c, cmd, false
}

// View renders the scrollable box.
func (c *ClusterLoad) View() string { return c.box.View() }

// SetSize lays out the box.
func (c *ClusterLoad) SetSize(w, height int) { c.box.SetSize(w, height) }

// SetStyles re-themes the box and re-renders the cluster-load content.
func (c *ClusterLoad) SetStyles(styles theme.Styles) {
	c.box.SetStyles(styles)
	c.box.SetContent(components.ClusterLoadContent(c.stats, styles, c.loaded))
}

// ShortHelp returns the modal's dismissal binding.
func (c *ClusterLoad) ShortHelp() []key.Binding {
	return []key.Binding{key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "close"))}
}

// FullHelp returns the expanded bindings.
func (c *ClusterLoad) FullHelp() [][]key.Binding { return [][]key.Binding{c.ShortHelp()} }

// Compile-time assertion that ClusterLoad satisfies Modal.
var _ Modal = (*ClusterLoad)(nil)
