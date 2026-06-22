package modals

import (
	"context"
	"time"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/spinner"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// detailFetchTimeout bounds the on-demand job-detail lookup.
const detailFetchTimeout = 15 * time.Second

// OpenLogMsg asks the root to push a log viewer for a job's stdout/stderr path.
// The job-detail modal emits it when the user presses o/e; the root pushes the
// log viewer over the detail modal so both are on the stack.
type OpenLogMsg struct {
	// Path is the log file to open.
	Path string
	// Label is "stdout" or "stderr", shown in the viewer title.
	Label string
}

// jobDetailLoadedMsg carries the result of an on-demand job-detail fetch back
// into the modal. It is tagged with the job id so a stale result for a different
// job (after a re-open) is ignored.
type jobDetailLoadedMsg struct {
	jobID  string
	detail store.JobDetail
	err    error
}

// JobDetail is the scrollable job-detail modal opened by Enter on a Jobs row or
// by the "i" job-id prompt. It fetches client.JobDetail in a Cmd (non-blocking,
// spinner while loading), renders the scontrol/sacct fields by category, and
// offers o/e to open the job's stdout/stderr in the log viewer. The cache and the
// live job state are supplied by the root so the modal stays a pure view of one
// job.
type JobDetail struct {
	styles theme.Styles
	client store.SlurmClient
	cache  *JobDetailCache

	jobID string
	// state is the job's live state, used as the cache key suffix so a state
	// change forces a re-fetch.
	state string

	box     scrollBox
	spin    spinner.Model
	loading bool

	stdout string
	stderr string
	errMsg string
}

// NewJobDetail builds a job-detail modal for jobID at live state. The cache is
// consulted on Init: a fresh entry for the same state shows instantly, otherwise
// a fetch Cmd runs with a spinner.
func NewJobDetail(client store.SlurmClient, cache *JobDetailCache, styles theme.Styles, jobID, state string) *JobDetail {
	sp := spinner.New()
	sp.Spinner = spinner.Dot

	d := &JobDetail{
		styles: styles,
		client: client,
		cache:  cache,
		jobID:  jobID,
		state:  state,
		box:    newScrollBox(styles),
		spin:   sp,
	}
	d.box.SetTitle("Job Details — " + jobID)
	d.box.SetFooter("o stdout   e stderr   ↑/↓ scroll   Esc close")
	return d
}

// Init returns the Cmd the modal needs after it is pushed: either nothing (a
// cache hit already populated the box) or a fetch Cmd plus the spinner tick. The
// root calls this once when pushing the modal.
func (d *JobDetail) Init() tea.Cmd {
	if e, ok := d.cache.Get(d.jobID, d.state); ok {
		d.applyEntry(e)
		return nil
	}
	d.loading = true
	d.box.SetContent("")
	return tea.Batch(d.fetchCmd(), d.spin.Tick)
}

// fetchCmd loads the job detail off the main loop and reports it as a
// jobDetailLoadedMsg.
func (d *JobDetail) fetchCmd() tea.Cmd {
	client := d.client
	jobID := d.jobID
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), detailFetchTimeout)
		defer cancel()
		detail, err := client.JobDetail(ctx, jobID)
		return jobDetailLoadedMsg{jobID: jobID, detail: detail, err: err}
	}
}

// applyEntry populates the modal from a cached detail entry.
func (d *JobDetail) applyEntry(e cachedDetail) {
	d.loading = false
	d.stdout, d.stderr, d.errMsg = e.stdout, e.stderr, e.err
	if e.err != "" {
		d.box.SetContent(d.styles.Error.Render("Error: " + e.err))
		return
	}
	d.box.SetContent(e.content)
	d.box.GotoTop()
}

// Update handles the fetch result, the spinner tick, scrolling, opening logs,
// and dismissal.
func (d *JobDetail) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	switch msg := msg.(type) {
	case jobDetailLoadedMsg:
		if msg.jobID != d.jobID {
			return d, nil, false // stale result for a different job
		}
		d.applyLoaded(msg)
		return d, nil, false

	case spinner.TickMsg:
		if !d.loading {
			return d, nil, false
		}
		var cmd tea.Cmd
		d.spin, cmd = d.spin.Update(msg)
		return d, cmd, false

	case tea.KeyPressMsg:
		switch msg.String() {
		case "esc", "q":
			return d, nil, true
		case "o":
			return d, d.openLog(d.stdout, "stdout"), false
		case "e":
			return d, d.openLog(d.stderr, "stderr"), false
		}
		cmd := d.box.ScrollUpdate(msg)
		return d, cmd, false
	}
	return d, nil, false
}

// applyLoaded renders a freshly fetched detail, caches it under the live state,
// and extracts the log paths. A fetch error is cached too (keyed by state) so a
// failed lookup is not re-attempted on every open while the state is unchanged.
func (d *JobDetail) applyLoaded(msg jobDetailLoadedMsg) {
	d.loading = false
	if msg.err != nil {
		d.errMsg = msg.err.Error()
		d.box.SetContent(d.styles.Error.Render("Error: " + d.errMsg))
		d.cache.Put(d.jobID, cachedDetail{state: d.state, err: d.errMsg})
		return
	}
	content := formatJobDetail(msg.detail, d.styles)
	d.stdout, d.stderr = stdoutStderrPaths(msg.detail.Fields)
	d.errMsg = ""
	d.box.SetContent(content)
	d.box.GotoTop()
	d.cache.Put(d.jobID, cachedDetail{
		content: content,
		stdout:  d.stdout,
		stderr:  d.stderr,
		source:  msg.detail.Source,
		state:   d.state,
	})
}

// openLog emits an OpenLogMsg for path. When the path is empty it emits an
// OpenLogMsg with an empty Path so the root can toast "no path" rather than
// pushing an empty viewer.
func (d *JobDetail) openLog(path, label string) tea.Cmd {
	p := firstNonEmpty(path)
	if p == "" {
		return func() tea.Msg { return OpenLogMsg{Path: "", Label: label} }
	}
	return func() tea.Msg { return OpenLogMsg{Path: p, Label: label} }
}

// View renders the spinner while loading, otherwise the detail box.
func (d *JobDetail) View() string {
	if d.loading {
		body := d.spin.View() + " Loading job information…"
		inner := lipgloss.JoinVertical(lipgloss.Left,
			d.styles.Title.Render("Job Details — "+d.jobID), "", body)
		return d.styles.Modal.Render(inner)
	}
	return d.box.View()
}

// SetSize lays out the detail box.
func (d *JobDetail) SetSize(w, h int) { d.box.SetSize(w, h) }

// SetStyles re-themes the modal.
func (d *JobDetail) SetStyles(styles theme.Styles) {
	d.styles = styles
	d.box.SetStyles(styles)
}

// ShortHelp returns the detail modal's bindings.
func (d *JobDetail) ShortHelp() []key.Binding {
	return []key.Binding{
		key.NewBinding(key.WithKeys("o"), key.WithHelp("o", "stdout")),
		key.NewBinding(key.WithKeys("e"), key.WithHelp("e", "stderr")),
		key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "close")),
	}
}

// FullHelp returns the expanded bindings.
func (d *JobDetail) FullHelp() [][]key.Binding { return [][]key.Binding{d.ShortHelp()} }

// Compile-time assertion that JobDetail satisfies Modal.
var _ Modal = (*JobDetail)(nil)
