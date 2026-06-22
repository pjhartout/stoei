package modals

import (
	"context"
	"time"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// CancelRequestedMsg is emitted when the user confirms a cancellation. The root
// handles it by triggering a data refresh on success and toasting the outcome.
type CancelRequestedMsg struct {
	// JobID is the job that was asked to be cancelled.
	JobID string
	// Err is the scancel error, or nil on success.
	Err error
}

// confirmChoice is the focused button in the confirm modal.
type confirmChoice int

const (
	// choiceNo is the safe default (keep the job); it is focused on open.
	choiceNo confirmChoice = iota
	// choiceYes confirms the cancellation.
	choiceYes
)

// CancelConfirm is the yes/no confirmation modal opened with "c" on an active
// job. It defaults focus to the safe option (No), refuses to cancel completed/
// failed jobs (the root checks before opening), and on confirm issues a
// client.CancelJob Cmd. Ports CancelConfirmScreen.
type CancelConfirm struct {
	styles theme.Styles
	client store.SlurmClient

	jobID   string
	jobName string
	choice  confirmChoice

	width  int
	height int
}

// NewCancelConfirm builds the confirm modal for jobID/jobName. Focus defaults to
// No (the safe option), matching CancelConfirmScreen.on_mount.
func NewCancelConfirm(client store.SlurmClient, styles theme.Styles, jobID, jobName string) *CancelConfirm {
	return &CancelConfirm{
		styles:  styles,
		client:  client,
		jobID:   jobID,
		jobName: jobName,
		choice:  choiceNo,
	}
}

// Init has nothing to start for the confirm modal.
func (c *CancelConfirm) Init() tea.Cmd { return nil }

// Update handles the confirm/abort navigation and activation. Esc aborts (safe),
// left/right/tab move focus, and Enter activates the focused choice. Ports the
// CancelConfirmScreen bindings.
func (c *CancelConfirm) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	km, ok := msg.(tea.KeyPressMsg)
	if !ok {
		return c, nil, false
	}
	switch km.String() {
	case "esc", "q":
		return c, nil, true
	case "left", "right", "tab", "shift+tab":
		if c.choice == choiceNo {
			c.choice = choiceYes
		} else {
			c.choice = choiceNo
		}
		return c, nil, false
	case "y":
		return c, c.cancelCmd(), true
	case "n":
		return c, nil, true
	case "enter":
		if c.choice == choiceYes {
			return c, c.cancelCmd(), true
		}
		return c, nil, true
	}
	return c, nil, false
}

// cancelCmd returns a Cmd that runs scancel for the job and reports the outcome
// as a CancelRequestedMsg (I1: the IO happens in the Cmd closure, not Update).
func (c *CancelConfirm) cancelCmd() tea.Cmd {
	client := c.client
	jobID := c.jobID
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), cancelTimeout)
		defer cancel()
		err := client.CancelJob(ctx, jobID)
		return CancelRequestedMsg{JobID: jobID, Err: err}
	}
}

// cancelTimeout bounds the scancel command.
const cancelTimeout = 10 * time.Second

// View renders the confirm dialog with the focused button highlighted. Ports
// CancelConfirmScreen.compose.
func (c *CancelConfirm) View() string {
	title := c.styles.Error.Render("Cancel Job?")

	info := c.styles.Text.Render("Job ID: ") + c.styles.Title.Render(c.jobID)
	if c.jobName != "" {
		info += "\n" + c.styles.Text.Render("Job Name: ") + c.styles.Text.Bold(true).Render(c.jobName)
	}
	warning := c.styles.Subtle.Render("This action cannot be undone.")

	yes := c.button("Yes, Cancel", c.choice == choiceYes, c.styles.Error)
	no := c.button("No, Keep It", c.choice == choiceNo, c.styles.Success)
	buttons := lipgloss.JoinHorizontal(lipgloss.Top, yes, "  ", no)

	inner := lipgloss.JoinVertical(lipgloss.Left, title, "", info, "", warning, "", buttons)
	return c.styles.Modal.Render(inner)
}

// button renders one focusable button, reversed when focused.
func (c *CancelConfirm) button(label string, focused bool, style lipgloss.Style) string {
	s := style.Padding(0, 2)
	if focused {
		s = s.Reverse(true).Bold(true)
	}
	return s.Render(label)
}

// SetSize records the terminal size (the modal is content-sized, not stretched).
func (c *CancelConfirm) SetSize(w, h int) { c.width, c.height = w, h }

// SetStyles re-themes the modal.
func (c *CancelConfirm) SetStyles(styles theme.Styles) { c.styles = styles }

// ShortHelp returns the confirm modal's bindings.
func (c *CancelConfirm) ShortHelp() []key.Binding {
	return []key.Binding{
		key.NewBinding(key.WithKeys("left", "right"), key.WithHelp("←/→", "choose")),
		key.NewBinding(key.WithKeys("enter"), key.WithHelp("enter", "activate")),
		key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "abort")),
	}
}

// FullHelp returns the expanded bindings.
func (c *CancelConfirm) FullHelp() [][]key.Binding { return [][]key.Binding{c.ShortHelp()} }

// Compile-time assertion that CancelConfirm satisfies Modal.
var _ Modal = (*CancelConfirm)(nil)
