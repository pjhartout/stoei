package modals

import (
	"context"
	"strings"
	"time"

	"charm.land/bubbles/v2/textinput"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// OpenModifyMsg asks the root to push the job-modify modal for a job. The
// job-detail modal emits it when the user presses "m"; the root refuses it for a
// finished job (toast) and otherwise pushes the modal over the detail.
type OpenModifyMsg struct {
	// JobID is the job to modify.
	JobID string
	// Fields is the job's parsed scontrol detail, used to pre-fill current values.
	Fields map[string]string
}

// ModifyRequestedMsg is emitted after a modification was attempted. The root
// toasts the outcome and, on success, evicts the detail cache and refreshes.
type ModifyRequestedMsg struct {
	// JobID is the job the modification targeted.
	JobID string
	// Desc describes the applied change (e.g. "Partition=p.hpcl91" or "hold").
	Desc string
	// Err is the scontrol error, or nil on success.
	Err error
}

// modifyTimeout bounds the scontrol update/hold/release command.
const modifyTimeout = 10 * time.Second

// modifyRowKind classifies a row of the modify picker.
type modifyRowKind int

const (
	// rowField edits one curated scontrol field via the input step.
	rowField modifyRowKind = iota
	// rowHold holds the job immediately (no input step).
	rowHold
	// rowRelease releases a held job immediately (no input step).
	rowRelease
	// rowRaw is the freeform Key=Value fallback for any other scontrol field.
	rowRaw
)

// modifyRow is one selectable entry in the modify picker.
type modifyRow struct {
	kind modifyRowKind
	// key is the scontrol field name (rowField only).
	key string
	// value is the field's current value, pre-filled into the input.
	value string
	// target overrides the job id the update applies to (the array leader for
	// ArrayTaskThrottle); empty means the modal's job id.
	target string
}

// label returns the row's display name.
func (r modifyRow) label() string {
	switch r.kind {
	case rowHold:
		return "Hold"
	case rowRelease:
		return "Release"
	case rowRaw:
		return "Other…"
	default:
		return r.key
	}
}

// curatedFields are the scontrol update fields offered to every job, in display
// order. ArrayTaskThrottle is prepended for array jobs only.
var curatedFields = []string{"Partition", "TimeLimit", "QOS", "Nice", "JobName"}

// jobHeld reports whether the job is held (zero priority or a JobHeld* reason).
func jobHeld(fields map[string]string) bool {
	return fields["Priority"] == "0" || strings.Contains(fields["Reason"], "JobHeld")
}

// modifyRows builds the picker rows for a job from its scontrol fields.
func modifyRows(fields map[string]string) []modifyRow {
	var rows []modifyRow
	if fields["ArrayJobId"] != "" {
		// Throttle lives on the array leader, so the update targets it, not a task.
		rows = append(rows, modifyRow{
			kind:   rowField,
			key:    "ArrayTaskThrottle",
			value:  fields["ArrayTaskThrottle"],
			target: fields["ArrayJobId"],
		})
	}
	for _, k := range curatedFields {
		rows = append(rows, modifyRow{kind: rowField, key: k, value: fields[k]})
	}
	if jobHeld(fields) {
		rows = append(rows, modifyRow{kind: rowRelease})
	} else {
		rows = append(rows, modifyRow{kind: rowHold})
	}
	rows = append(rows, modifyRow{kind: rowRaw})
	return rows
}

// JobModify is the two-step modify modal opened with "m" from the job detail:
// pick a field (current values shown), then edit its value in a pre-filled
// input. Hold/Release rows apply immediately, and the "Other…" row accepts a
// freeform Key=Value for any scontrol field not in the curated list. The
// scontrol IO runs in a Cmd off the update loop; scontrol is the validator and
// its error becomes the outcome toast.
type JobModify struct {
	styles theme.Styles
	client store.SlurmClient

	jobID   string
	rows    []modifyRow
	cursor  int
	editing bool
	input   textinput.Model
	errMsg  string
}

// NewJobModify builds the modify picker for jobID from its scontrol fields.
func NewJobModify(client store.SlurmClient, styles theme.Styles, jobID string, fields map[string]string) *JobModify {
	return &JobModify{
		styles: styles,
		client: client,
		jobID:  jobID,
		rows:   modifyRows(fields),
		input:  textinput.New(),
	}
}

// Init has nothing to start until a field is picked.
func (m *JobModify) Init() tea.Cmd { return nil }

// Update handles picker navigation, the input step, and applying the change.
func (m *JobModify) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	km, ok := msg.(tea.KeyPressMsg)
	if !ok {
		// Non-key messages (paste, cursor blink) belong to the input while it
		// is focused; dropping them would swallow pasted text.
		if m.editing {
			var cmd tea.Cmd
			m.input, cmd = m.input.Update(msg)
			return m, cmd, false
		}
		return m, nil, false
	}
	if m.editing {
		return m.updateEditing(km)
	}
	switch km.String() {
	case "esc", "q":
		return m, nil, true
	case "up", "k":
		if m.cursor > 0 {
			m.cursor--
		}
		return m, nil, false
	case "down", "j":
		if m.cursor < len(m.rows)-1 {
			m.cursor++
		}
		return m, nil, false
	case "enter":
		return m.activate()
	}
	return m, nil, false
}

// activate acts on the selected row: hold/release apply immediately, field and
// raw rows open the input step.
func (m *JobModify) activate() (Modal, tea.Cmd, bool) {
	row := m.rows[m.cursor]
	switch row.kind {
	case rowHold:
		return m, m.applyHold(true), true
	case rowRelease:
		return m, m.applyHold(false), true
	case rowRaw:
		m.startEditing("", "Key=Value (e.g. Requeue=1)")
	default:
		m.startEditing(row.value, "New value for "+row.key)
	}
	return m, textinput.Blink, false
}

// startEditing switches to the input step, pre-filled with value.
func (m *JobModify) startEditing(value, placeholder string) {
	m.editing = true
	m.errMsg = ""
	m.input.SetValue(value)
	m.input.CursorEnd()
	m.input.Placeholder = placeholder
	m.input.Focus()
}

// updateEditing handles keys during the input step: esc steps back to the
// picker, enter applies, anything else edits the input.
func (m *JobModify) updateEditing(km tea.KeyPressMsg) (Modal, tea.Cmd, bool) {
	switch km.String() {
	case "esc":
		m.editing = false
		m.input.Blur()
		return m, nil, false
	case "enter":
		return m.submit()
	}
	var cmd tea.Cmd
	m.input, cmd = m.input.Update(km)
	return m, cmd, false
}

// submit validates the typed value and issues the update Cmd. An empty or
// unchanged value steps back to the picker; a raw entry without "=" shows an
// inline error and stays in the input.
func (m *JobModify) submit() (Modal, tea.Cmd, bool) {
	row := m.rows[m.cursor]
	val := strings.TrimSpace(m.input.Value())
	if val == "" || (row.kind == rowField && val == row.value) {
		m.editing = false
		m.input.Blur()
		return m, nil, false
	}
	key := row.key
	target := row.target
	if row.kind == rowRaw {
		var found bool
		key, val, found = strings.Cut(val, "=")
		key, val = strings.TrimSpace(key), strings.TrimSpace(val)
		if !found || key == "" || val == "" {
			m.errMsg = "Enter as Key=Value"
			return m, nil, false
		}
	}
	if target == "" {
		target = m.jobID
	}
	return m, m.applyUpdate(target, key, val), true
}

// applyUpdate returns a Cmd that runs the scontrol update off the update loop
// and reports the outcome as a ModifyRequestedMsg.
func (m *JobModify) applyUpdate(target, key, value string) tea.Cmd {
	client, jobID := m.client, m.jobID
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), modifyTimeout)
		defer cancel()
		err := client.UpdateJob(ctx, target, key, value)
		return ModifyRequestedMsg{JobID: jobID, Desc: key + "=" + value, Err: err}
	}
}

// applyHold returns a Cmd that holds or releases the job off the update loop
// and reports the outcome as a ModifyRequestedMsg.
func (m *JobModify) applyHold(hold bool) tea.Cmd {
	client, jobID := m.client, m.jobID
	desc := "release"
	if hold {
		desc = "hold"
	}
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), modifyTimeout)
		defer cancel()
		err := client.HoldJob(ctx, jobID, hold)
		return ModifyRequestedMsg{JobID: jobID, Desc: desc, Err: err}
	}
}

// View renders the picker list or the input step.
func (m *JobModify) View() string {
	title := m.styles.Title.Render("Modify Job — " + m.jobID)
	var body string
	if m.editing {
		row := m.rows[m.cursor]
		prompt := "New value for " + row.key
		if row.kind == rowRaw {
			prompt = "scontrol field as Key=Value"
		}
		lines := []string{m.styles.Text.Render(prompt), "", m.styles.Text.Render(m.input.View())}
		if m.errMsg != "" {
			lines = append(lines, "", m.styles.Error.Render(m.errMsg))
		}
		lines = append(lines, "", m.styles.Subtle.Render("Enter to apply   Esc back"))
		body = lipgloss.JoinVertical(lipgloss.Left, lines...)
	} else {
		lines := make([]string, 0, len(m.rows)+2)
		for i, row := range m.rows {
			label := row.label()
			if row.kind == rowField && row.value != "" {
				label += "  " + m.styles.Subtle.Render("("+row.value+")")
			}
			if i == m.cursor {
				lines = append(lines, m.styles.Selection.Render("> "+label))
			} else {
				lines = append(lines, m.styles.Text.Render("  "+label))
			}
		}
		lines = append(lines, "", m.styles.Subtle.Render("↑/↓ choose   Enter select   Esc close"))
		body = lipgloss.JoinVertical(lipgloss.Left, lines...)
	}
	return m.styles.Modal.Render(lipgloss.JoinVertical(lipgloss.Left, title, "", body))
}

// SetSize sets the input width.
func (m *JobModify) SetSize(w, _ int) {
	mw, _ := modalSize(w, 24)
	m.input.SetWidth(max(mw-modalChromeWidth, 10))
}

// SetStyles re-themes the modal.
func (m *JobModify) SetStyles(styles theme.Styles) { m.styles = styles }

// Compile-time assertion that JobModify satisfies Modal.
var _ Modal = (*JobModify)(nil)
