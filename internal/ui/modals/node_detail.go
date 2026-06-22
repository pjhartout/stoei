package modals

import (
	"context"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/spinner"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// nodeDetailLoadedMsg carries an on-demand node-detail fetch result.
type nodeDetailLoadedMsg struct {
	node   string
	detail store.JobDetail
	err    error
}

// NodeDetail is the scrollable node-detail modal opened by Enter on a Nodes row.
// It fetches client.NodeDetail in a Cmd (spinner while loading) and renders the
// "scontrol show node" fields by category.
type NodeDetail struct {
	styles theme.Styles
	client store.SlurmClient

	node string

	box     scrollBox
	spin    spinner.Model
	loading bool
}

// NewNodeDetail builds a node-detail modal for nodeName.
func NewNodeDetail(client store.SlurmClient, styles theme.Styles, nodeName string) *NodeDetail {
	sp := spinner.New()
	sp.Spinner = spinner.Dot
	n := &NodeDetail{
		styles: styles,
		client: client,
		node:   nodeName,
		box:    newScrollBox(styles),
		spin:   sp,
	}
	n.box.SetTitle("Node Details — " + nodeName)
	n.box.SetFooter("↑/↓ scroll   Esc close")
	return n
}

// Init starts the fetch and the spinner.
func (n *NodeDetail) Init() tea.Cmd {
	n.loading = true
	return tea.Batch(n.fetchCmd(), n.spin.Tick)
}

// fetchCmd loads the node detail off the main loop and reports it as a
// nodeDetailLoadedMsg.
func (n *NodeDetail) fetchCmd() tea.Cmd {
	client := n.client
	node := n.node
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), detailFetchTimeout)
		defer cancel()
		detail, err := client.NodeDetail(ctx, node)
		return nodeDetailLoadedMsg{node: node, detail: detail, err: err}
	}
}

// Update handles the fetch result, spinner ticks, scrolling, and dismissal.
func (n *NodeDetail) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	switch msg := msg.(type) {
	case nodeDetailLoadedMsg:
		if msg.node != n.node {
			return n, nil, false
		}
		n.loading = false
		if msg.err != nil {
			n.box.SetContent(n.styles.Error.Render("Error: " + msg.err.Error()))
			return n, nil, false
		}
		n.box.SetContent(formatNodeDetail(msg.detail, n.styles))
		n.box.GotoTop()
		return n, nil, false

	case spinner.TickMsg:
		if !n.loading {
			return n, nil, false
		}
		var cmd tea.Cmd
		n.spin, cmd = n.spin.Update(msg)
		return n, cmd, false

	case tea.KeyPressMsg:
		if isCloseKey(msg) {
			return n, nil, true
		}
		cmd := n.box.ScrollUpdate(msg)
		return n, cmd, false
	}
	return n, nil, false
}

// View renders the spinner while loading, otherwise the node box.
func (n *NodeDetail) View() string {
	if n.loading {
		inner := lipgloss.JoinVertical(lipgloss.Left,
			n.styles.Title.Render("Node Details — "+n.node), "",
			n.spin.View()+" Loading node information…")
		return n.styles.Modal.Render(inner)
	}
	return n.box.View()
}

// SetSize lays out the node box.
func (n *NodeDetail) SetSize(w, h int) { n.box.SetSize(w, h) }

// SetStyles re-themes the modal.
func (n *NodeDetail) SetStyles(styles theme.Styles) {
	n.styles = styles
	n.box.SetStyles(styles)
}

// ShortHelp returns the node modal's bindings.
func (n *NodeDetail) ShortHelp() []key.Binding {
	return []key.Binding{key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "close"))}
}

// FullHelp returns the expanded bindings.
func (n *NodeDetail) FullHelp() [][]key.Binding { return [][]key.Binding{n.ShortHelp()} }

// Compile-time assertion that NodeDetail satisfies Modal.
var _ Modal = (*NodeDetail)(nil)
