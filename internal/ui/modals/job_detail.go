package modals

import (
	"context"
	"strings"
	"time"

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

// jobUsageLoadedMsg carries the result of the efficiency lookup that follows a
// detail fetch, tagged with the job id like jobDetailLoadedMsg.
type jobUsageLoadedMsg struct {
	jobID string
	usage store.JobUsage
	err   error
}

// JobDetail is the scrollable job-detail modal opened by Enter on a Jobs row or
// by the "i" job-id prompt. It fetches client.JobDetail in a Cmd (non-blocking,
// spinner while loading), renders the scontrol fields by category, and
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
	// fallback is the journal-sourced record the root supplies for jobs it has
	// history for; rendered when the controller lookup fails (the controller
	// retains a finished job only for MinJobAge, but its logs live on).
	fallback store.JobDetail

	box     scrollBox
	spin    spinner.Model
	loading bool

	stdout string
	stderr string
	errMsg string
	// fields is the parsed scontrol detail, kept so "m" can open the modify
	// modal with current values pre-filled.
	fields map[string]string
	// content is the rendered detail fields; usage is the rendered Efficiency
	// section appended below them once the usage lookup lands.
	content string
	usage   string
}

// NewJobDetail builds a job-detail modal for jobID at live state. The cache is
// consulted on Init: a fresh entry for the same state shows instantly, otherwise
// a fetch Cmd runs with a spinner. fallback is the journal-sourced record shown
// when the controller lookup fails (zero value: no fallback, errors render).
func NewJobDetail(client store.SlurmClient, cache *JobDetailCache, styles theme.Styles, jobID, state string, fallback store.JobDetail) *JobDetail {
	sp := spinner.New()
	sp.Spinner = spinner.Dot

	d := &JobDetail{
		styles:   styles,
		client:   client,
		cache:    cache,
		jobID:    jobID,
		state:    state,
		fallback: fallback,
		box:      newScrollBox(styles),
		spin:     sp,
	}
	d.box.SetTitle("Job Details — " + jobID)
	d.box.SetFooter("o stdout   e stderr   m modify   ↑/↓ scroll   Esc close")
	return d
}

// Init shows cached details immediately and refreshes live usage asynchronously.
// A cache miss fetches the detail with a spinner; the root calls this once when
// pushing the modal.
func (d *JobDetail) Init() tea.Cmd {
	if e, ok := d.cache.Get(d.jobID, d.state); ok {
		d.applyEntry(e)
		return d.usageInitCmd(e)
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
	d.fields = e.fields
	if e.err != "" {
		d.box.SetContent(d.styles.Error.Render("Error: " + e.err))
		return
	}
	d.content, d.usage = e.content, e.usage
	d.box.SetContent(composedContent(d.content, d.usage))
	d.box.GotoTop()
}

// usageInitCmd refreshes the detail before sampling a live job so fresh counters
// are not divided by a cached RunTime or allocation. Finished jobs only fetch
// usage if their cached section has not arrived yet.
func (d *JobDetail) usageInitCmd(e cachedDetail) tea.Cmd {
	if e.err != "" {
		return nil
	}
	state := d.currentState()
	if state == "" || strings.HasPrefix(state, "PENDING") {
		return nil
	}
	if !store.IsTerminalState(state) && d.ownJob() {
		return d.fetchCmd()
	}
	if e.usage != "" && store.IsTerminalState(state) {
		return nil
	}
	return d.startUsageFetch()
}

// Update handles the fetch result, the spinner tick, scrolling, opening logs,
// and dismissal.
func (d *JobDetail) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	switch msg := msg.(type) {
	case jobDetailLoadedMsg:
		if msg.jobID != d.jobID {
			return d, nil, false // stale result for a different job
		}
		return d, d.applyLoaded(msg), false

	case jobUsageLoadedMsg:
		if msg.jobID != d.jobID {
			return d, nil, false // stale result for a different job
		}
		d.applyUsage(msg)
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
		case "m":
			return d, d.openModify(), false
		}
		cmd := d.box.ScrollUpdate(msg)
		return d, cmd, false
	}
	return d, nil, false
}

// applyLoaded renders a freshly fetched detail, caches it under the live state,
// extracts the log paths, and starts the follow-up usage lookup. A fetch error
// is cached too (keyed by state) so a failed lookup is not re-attempted on
// every open while the state is unchanged.
func (d *JobDetail) applyLoaded(msg jobDetailLoadedMsg) tea.Cmd {
	d.loading = false
	if msg.err != nil {
		if len(d.fallback.Fields) > 0 {
			return d.applyFallback()
		}
		d.errMsg = msg.err.Error()
		d.box.SetContent(d.styles.Error.Render("Error: " + d.errMsg))
		d.cache.Put(d.jobID, cachedDetail{state: d.state, err: d.errMsg})
		return nil
	}
	content := formatJobDetail(msg.detail, d.styles)
	d.stdout, d.stderr = stdoutStderrPaths(msg.detail.Fields)
	d.fields = msg.detail.Fields
	d.errMsg = ""
	d.content, d.usage = content, ""
	d.box.SetContent(content)
	d.box.GotoTop()
	d.cache.Put(d.jobID, cachedDetail{
		content: content,
		stdout:  d.stdout,
		stderr:  d.stderr,
		source:  msg.detail.Source,
		state:   d.state,
		fields:  msg.detail.Fields,
	})
	return d.startUsageFetch()
}

// applyFallback renders the journal-sourced record in place of a failed
// controller lookup and caches it like a fetched detail, so o/e (and the log
// viewer behind them) keep working for jobs the controller no longer knows.
// The journal only holds finished jobs, so the usage lookup proceeds via
// accounting.
func (d *JobDetail) applyFallback() tea.Cmd {
	note := d.styles.Subtle.Render("Controller no longer has this job — showing the journal record.")
	content := note + "\n\n" + formatJobDetail(d.fallback, d.styles)
	d.stdout, d.stderr = stdoutStderrPaths(d.fallback.Fields)
	d.fields = d.fallback.Fields
	d.errMsg = ""
	d.content, d.usage = content, ""
	d.box.SetContent(content)
	d.box.GotoTop()
	d.cache.Put(d.jobID, cachedDetail{
		content: content,
		stdout:  d.stdout,
		stderr:  d.stderr,
		source:  d.fallback.Source,
		state:   d.state,
		fields:  d.fallback.Fields,
	})
	return d.startUsageFetch()
}

// currentState returns the freshest known job state: the fetched scontrol
// JobState when available, otherwise the live-list state the root supplied.
func (d *JobDetail) currentState() string {
	if s := d.fields["JobState"]; s != "" {
		return s
	}
	return d.state
}

// ownJob reports whether the loaded job belongs to the current user. The
// scontrol UserId is "name(uid)"; a missing field means the record came from
// the per-user journal, which only ever holds the user's own jobs.
func (d *JobDetail) ownJob() bool {
	user, _, _ := strings.Cut(d.fields["UserId"], "(")
	if user == "" {
		return true
	}
	return user == d.client.Username()
}

// startUsageFetch launches the efficiency lookup for the loaded job, or
// renders an immediate note when no lookup can succeed: a pending job has no
// usage yet, and slurmstepd answers live queries only for the caller's own
// jobs.
func (d *JobDetail) startUsageFetch() tea.Cmd {
	state := d.currentState()
	if state == "" || strings.HasPrefix(state, "PENDING") {
		return nil
	}
	running := !store.IsTerminalState(state)
	if running && !d.ownJob() {
		d.setUsage(formatUsageNote(usageForeignNote, d.styles))
		return nil
	}
	client, jobID := d.client, d.jobID
	usageID := jobID
	if running {
		// squeue identifies array tasks as "<ArrayJobId>_<ArrayTaskId>", but
		// sstat reports their steps under scontrol's distinct numeric JobId.
		// Querying that controller ID selects the task instead of every sibling
		// and gives the parser the same prefix sstat returns.
		if id := strings.TrimSpace(d.fields["JobId"]); id != "" {
			usageID = id
		}
	}
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), detailFetchTimeout)
		defer cancel()
		usage, err := client.JobUsage(ctx, usageID, running)
		return jobUsageLoadedMsg{jobID: jobID, usage: usage, err: err}
	}
}

// applyUsage renders the efficiency lookup result below the detail fields. A
// lookup error renders as a subdued note rather than replacing the detail.
func (d *JobDetail) applyUsage(msg jobUsageLoadedMsg) {
	if msg.err != nil {
		d.setUsage(formatUsageNote("usage unavailable: "+msg.err.Error(), d.styles))
		return
	}
	d.setUsage(formatUsageSection(store.DeriveJobEfficiency(msg.usage, d.fields), d.styles))
}

// setUsage swaps the rendered usage section into the box content and mirrors
// it into the cache entry so a reopen of a finished job is instant.
func (d *JobDetail) setUsage(section string) {
	d.usage = section
	d.box.SetContent(composedContent(d.content, d.usage))
	d.cache.SetUsage(d.jobID, d.state, section)
}

// composedContent joins the detail render and the usage section with the same
// blank separator line formatCategorized puts between its categories (the
// section strings start with a single newline, the detail ends without one).
func composedContent(content, usage string) string {
	if usage == "" {
		return content
	}
	return content + "\n" + usage
}

// openModify emits an OpenModifyMsg carrying the loaded scontrol fields so the
// root can push the modify modal with current values. Before the detail has
// loaded (or after a failed fetch) there is nothing to modify, so it is a no-op.
func (d *JobDetail) openModify() tea.Cmd {
	if d.fields == nil {
		return nil
	}
	jobID, fields := d.jobID, d.fields
	return func() tea.Msg { return OpenModifyMsg{JobID: jobID, Fields: fields} }
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

// Compile-time assertion that JobDetail satisfies Modal.
var _ Modal = (*JobDetail)(nil)
