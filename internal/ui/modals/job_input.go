package modals

import (
	"strings"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/textinput"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/ui/theme"
)

// JobIDSubmittedMsg is emitted when the user submits a job id in the input
// prompt. The root opens a job-detail modal for the id.
type JobIDSubmittedMsg struct {
	// JobID is the entered (trimmed) job id.
	JobID string
}

// JobInput is the small modal that prompts for a job id, opened with "i". On
// Enter it emits a JobIDSubmittedMsg and closes; Esc cancels.
type JobInput struct {
	styles theme.Styles
	input  textinput.Model
}

// NewJobInput builds the job-id prompt with the input focused.
func NewJobInput(styles theme.Styles) *JobInput {
	ti := textinput.New()
	ti.Placeholder = "Job ID (e.g. 12345 or 12345_0)"
	ti.Focus()
	return &JobInput{styles: styles, input: ti}
}

// Init starts the input cursor blink.
func (j *JobInput) Init() tea.Cmd { return textinput.Blink }

// Update handles the input editing, submission, and cancellation.
func (j *JobInput) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	if km, ok := msg.(tea.KeyPressMsg); ok {
		switch km.String() {
		case "esc":
			return j, nil, true
		case "enter":
			id := strings.TrimSpace(j.input.Value())
			if id == "" {
				return j, nil, true
			}
			return j, submitJobID(id), true
		}
	}
	var cmd tea.Cmd
	j.input, cmd = j.input.Update(msg)
	return j, cmd, false
}

// submitJobID returns a Cmd emitting a JobIDSubmittedMsg.
func submitJobID(id string) tea.Cmd {
	return func() tea.Msg { return JobIDSubmittedMsg{JobID: id} }
}

// View renders the prompt box.
func (j *JobInput) View() string {
	inner := lipgloss.JoinVertical(lipgloss.Left,
		j.styles.Title.Render("Job Information Lookup"),
		j.styles.Subtle.Render("Enter a SLURM job ID to view detailed information"),
		"",
		j.styles.Text.Render(j.input.View()),
		"",
		j.styles.Subtle.Render("Enter to show   Esc to cancel"),
	)
	return j.styles.Modal.Render(inner)
}

// SetSize sets the input width.
func (j *JobInput) SetSize(w, _ int) {
	mw, _ := modalSize(w, 24)
	j.input.SetWidth(max(mw-modalChromeWidth, 10))
}

// SetStyles re-themes the prompt.
func (j *JobInput) SetStyles(styles theme.Styles) { j.styles = styles }

// ShortHelp returns the prompt bindings.
func (j *JobInput) ShortHelp() []key.Binding {
	return []key.Binding{
		key.NewBinding(key.WithKeys("enter"), key.WithHelp("enter", "show")),
		key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "cancel")),
	}
}

// FullHelp returns the expanded bindings.
func (j *JobInput) FullHelp() [][]key.Binding { return [][]key.Binding{j.ShortHelp()} }

// Compile-time assertion that JobInput satisfies Modal.
var _ Modal = (*JobInput)(nil)
