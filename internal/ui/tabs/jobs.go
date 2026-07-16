package tabs

import (
	"fmt"
	"strconv"
	"strings"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/table"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// JobsKeyMap are the Jobs-tab-local bindings (filter and sort). Global
// navigation (up/down) is handled by the embedded table's own KeyMap.
type JobsKeyMap struct {
	// Filter opens the filter input.
	Filter key.Binding
	// Sort cycles the sort column/direction.
	Sort key.Binding
	// ClearFilter closes the filter input and clears the query.
	ClearFilter key.Binding
	// ScrollLeft/ScrollRight pan the table horizontally when it overflows the pane.
	ScrollLeft  key.Binding
	ScrollRight key.Binding
}

// EmacsMode is the emacs keybinding preset name, matching keys.Emacs. It is
// duplicated here as a plain string so the tabs package stays decoupled from the
// keys package while still being able to switch filter/sort bindings per preset.
const EmacsMode = "emacs"

// defaultJobsKeys returns the Jobs-tab bindings for the default (vim) preset:
// "/" to filter and "o" to cycle the sort.
func defaultJobsKeys() JobsKeyMap {
	return jobsKeysForMode("")
}

// jobsKeysForMode returns the tab-local filter/sort/clear bindings for the active
// keybinding preset. The vim preset uses "/" filter, "o" sort, and esc clear; the
// emacs preset rebinds them to ctrl+s filter, ctrl+o sort, and ctrl+g clear.
func jobsKeysForMode(mode string) JobsKeyMap {
	if mode == EmacsMode {
		return JobsKeyMap{
			Filter:      key.NewBinding(key.WithKeys("ctrl+s"), key.WithHelp("C-s", "filter")),
			Sort:        key.NewBinding(key.WithKeys("ctrl+o"), key.WithHelp("C-o", "sort")),
			ClearFilter: key.NewBinding(key.WithKeys("ctrl+g", "esc"), key.WithHelp("C-g", "clear filter")),
			ScrollLeft:  key.NewBinding(key.WithKeys("left"), key.WithHelp("←", "scroll left")),
			ScrollRight: key.NewBinding(key.WithKeys("right"), key.WithHelp("→", "scroll right")),
		}
	}
	return JobsKeyMap{
		Filter:      key.NewBinding(key.WithKeys("/"), key.WithHelp("/", "filter")),
		Sort:        key.NewBinding(key.WithKeys("o"), key.WithHelp("o", "sort")),
		ClearFilter: key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "clear filter")),
		ScrollLeft:  key.NewBinding(key.WithKeys("left", "h"), key.WithHelp("←/h", "scroll left")),
		ScrollRight: key.NewBinding(key.WithKeys("right", "l"), key.WithHelp("→/l", "scroll right")),
	}
}

// Jobs is the live running-jobs tab. It renders the shared filterTable from
// the store's RunningJobs, colors the State column via its row decorator, and
// keeps a My-Usage banner. The cursor is preserved across refreshes by
// re-selecting the previously selected job id (I6); the table is never rebuilt
// from scratch on a tick, only its rows are replaced and the cursor restored.
type Jobs struct {
	store    *store.Store
	username string
	styles   theme.Styles

	ft filterTable

	// status renders a debounced per-section spinner / error badge in place of a
	// bare empty table while the running-jobs section loads or fails.
	status   sectionStatus
	rowCount int
}

// NewJobs returns a Jobs tab bound to s for the given username, styled with
// styles. The username drives the My-Usage banner lookup.
func NewJobs(s *store.Store, username string, styles theme.Styles) *Jobs {
	ft := newFilterTable(jobColumns, styles, jobRowDecorator)
	// Jobs content-fits its columns with no per-key floor, and its filter example
	// uses a job state rather than a node state.
	ft.minWidth = nil
	ft.filter.Placeholder = "Filter… (e.g. 'state:RUNNING' or a search term)"

	j := &Jobs{
		store:    s,
		username: username,
		styles:   styles,
		ft:       ft,
		status:   newSectionStatus(),
	}
	j.Refresh()
	return j
}

// jobRowDecorator converts a plain row into a rendered table row, coloring the
// State cell. The other cells are passed through verbatim.
func jobRowDecorator(plain []string, styles theme.Styles) table.Row {
	row := make(table.Row, len(plain))
	copy(row, plain)
	if len(row) > stateColumnIndex {
		row[stateColumnIndex] = colorState(plain[stateColumnIndex], styles)
	}
	return row
}

// stateColumnIndex is the index of the State column in jobColumns.
var stateColumnIndex = columnIndex("state")

// tableStyles maps the app theme onto the bubbles table styles. Cells and the
// header use a single left pad (no right pad) so columns sit one space apart
// instead of the default two, keeping the table compact.
func tableStyles(styles theme.Styles) table.Styles {
	s := table.DefaultStyles()
	s.Cell = s.Cell.Padding(0, 0, 0, 1)
	s.Header = s.Header.Foreground(styles.Title.GetForeground()).Bold(true).Padding(0, 0, 0, 1)
	s.Selected = styles.Selection
	return s
}

// tableStylesWidth is tableStyles with the selected-row highlight padded to width
// so the bar spans the whole line rather than stopping at the cell content. A
// non-positive width leaves the selection unpadded.
func tableStylesWidth(styles theme.Styles, width int) table.Styles {
	s := tableStyles(styles)
	if width > 0 {
		// Inline keeps the selected row on a single line: Width pads a short row to
		// fill the bar, but without Inline it would *wrap* a row wider than width to
		// a second line; Inline truncates instead (the trick the table uses per cell).
		s.Selected = s.Selected.Width(width).MaxWidth(width).Inline(true)
	}
	return s
}

// SetKeyMode switches the Jobs tab's filter/sort bindings to the given preset.
func (j *Jobs) SetKeyMode(mode string) { j.ft.SetKeyMode(mode) }

// SetStyles re-themes the tab after a background/theme change.
func (j *Jobs) SetStyles(styles theme.Styles) {
	j.styles = styles
	j.ft.styles = styles
	j.Refresh()
}

// SetSize informs the tab of the available area, reserving rows for the banner.
func (j *Jobs) SetSize(width, height int) {
	j.ft.SetSize(width, height-bannerReservedRows)
}

const (
	// bannerReservedRows is the vertical space reserved for the My-Usage banner
	// and its surrounding blank line.
	bannerReservedRows = 2
	// filterReservedRows is the extra space reserved when the filter input is
	// open.
	filterReservedRows = 1
)

// Update handles tab-local input and refreshes. The root routes input here only
// when no modal is active and the Jobs tab is selected.
func (j *Jobs) Update(msg tea.Msg) (*Jobs, tea.Cmd) {
	return j, j.ft.Update(msg)
}

// Refresh rebuilds the table rows from the store, preserving the cursor by job
// id (I6). It is called on every fast tick (the store already holds freshly
// fetched running jobs) and after a filter/sort change.
func (j *Jobs) Refresh() {
	plain := j.plainRows()
	j.ft.SetRows(plain)

	// Track loading/error state of the running-jobs section so View can show a
	// debounced spinner or error badge instead of a bare empty table. "hasData" is
	// the unfiltered merged count so an empty-but-loaded list (the user simply has
	// no jobs) is not mistaken for a still-loading section.
	j.rowCount = len(plain)
	j.status.observe(j.store.State(store.SectionRunningJobs), j.rowCount > 0)
}

// plainRows builds the markup-free cell values for the merged running-plus-history
// job list in store order (the default status grouping — pending, running, then
// finished — newest start first within each group). The first column (job id) is
// the stable key used for filtering, sorting and cursor restoration.
func (j *Jobs) plainRows() [][]string {
	jobs := j.store.MergedJobs()
	rows := make([][]string, 0, len(jobs))
	for _, job := range jobs {
		rows = append(rows, []string{
			job.ID,
			job.Name,
			job.State,
			job.Time,
			job.Nodes,
			job.NodeList,
			job.Timeline(),
		})
	}
	return rows
}

// SelectedJob returns the id, state, and active flag of the currently selected
// job, looked up in the merged job list by id. ok is false when no row is
// selected or the id is no longer present. The root uses this to open a job
// detail (with the live state for cache-evict) or a cancel-confirm modal.
func (j *Jobs) SelectedJob() (id, state string, active, ok bool) {
	id = j.ft.SelectedKey()
	if id == "" {
		return "", "", false, false
	}
	for _, job := range j.store.MergedJobs() {
		if job.ID == id {
			return job.ID, job.State, job.Active, true
		}
	}
	// The id is selected but no longer merged; report it with an unknown state so
	// the caller can still attempt a fresh lookup.
	return id, "", false, true
}

// SelectedJobName returns the name of the currently selected job (the Name
// column, markup-stripped), or "" when no row is selected. The root passes it to
// the cancel-confirm modal for display.
func (j *Jobs) SelectedJobName() string {
	return j.ft.SelectedCell(columnIndex("name"))
}

// reselect restores the table cursor to the row whose stable first-column key
// matches id. When the id is no longer present the prior cursor index is clamped
// into range, so restoration falls back from by-key to by-position.
func reselect(t *table.Model, sorted [][]string, id string) {
	if len(sorted) == 0 {
		return
	}
	// A table that was previously emptied leaves the cursor at -1 (bubbles
	// SetRows sets cursor = len-1 on an empty set and does not raise it back when
	// rows reappear). Clamp a negative cursor up so the first row is selectable
	// after the initial data load, even when there is no prior selection to
	// restore.
	if t.Cursor() < 0 {
		t.SetCursor(0)
	}
	if id == "" {
		return
	}
	for i, row := range sorted {
		if len(row) > 0 && row[0] == id {
			t.SetCursor(i)
			return
		}
	}
	cur := t.Cursor()
	if cur >= len(sorted) {
		t.SetCursor(len(sorted) - 1)
	}
}

// View renders the My-Usage banner, the optional filter input, and the table.
func (j *Jobs) View() string {
	banner := j.styles.Subtle.Render(j.banner())
	// When the last squeue fetch failed but prior rows are still on screen, mark
	// them stale: SetRunningJobs keeps the previous snapshot on error, so without
	// this the list looks live while it is frozen at the last good fetch.
	if j.store.State(store.SectionRunningJobs) == store.StateError && len(j.store.RunningJobs) > 0 {
		banner += "  " + j.styles.Error.Render("⚠ squeue failed — showing last known jobs")
	}

	parts := []string{banner, ""}
	if j.ft.filtering {
		parts = append(parts, j.styles.Text.Render(j.ft.filter.View()))
	}
	if line, ok := j.status.statusLine(
		j.store.State(store.SectionRunningJobs), j.rowCount > 0,
		j.store.SectionErr(store.SectionRunningJobs), j.styles,
	); ok {
		parts = append(parts, line)
	}
	parts = append(parts, hscrollWindow(j.ft.table.View(), j.ft.xOffset, tableContentWidth(j.ft.table.Columns()), j.ft.width))

	return lipgloss.JoinVertical(lipgloss.Left, parts...)
}

// banner renders the compact usage strip for the current user: a username chip
// followed by labeled CPU / memory / GPU / node / task segments, with the GPU
// segment breaking usage down by hardware model and noting how many job rows
// requested generic (typeless) GPUs.
func (j *Jobs) banner() string {
	chip := j.styles.Chip.Render(j.username)
	mine, ok := store.FindUserStats(j.store.RunningUserStats(), j.username)
	if !ok {
		return chip + " " + j.styles.Subtle.Render("no running jobs")
	}

	// Labels are plain text rather than pictographs: they render in every
	// terminal font.
	seg := func(label, val string) string {
		return j.styles.Subtle.Render(label+" ") + j.styles.Text.Render(val)
	}
	parts := []string{
		chip,
		seg("cpu", strconv.Itoa(mine.TotalCPUs)),
		seg("mem", compactGB(mine.TotalMemoryGB)),
	}
	if mine.TotalGPUs > 0 {
		// The breakdown lists hardware models only; unresolved generic requests
		// are conveyed by the "Nj generic gpu" note, not a pseudo-type.
		hw := compactGPUTypes(mine.GPUTypes)
		if hw == "" {
			hw = strconv.Itoa(mine.TotalGPUs)
		}
		parts = append(parts, seg("gpu", hw))
	}
	parts = append(parts,
		seg("node", strconv.Itoa(mine.TotalNodes)),
		seg("task", fmt.Sprintf("%d (%dA·%dJ)", mine.JobCount, mine.ArrayCount, mine.PlainJobCount)),
	)
	if mine.GenericGPUJobs > 0 {
		parts = append(parts, j.styles.Subtle.Render(
			fmt.Sprintf("%dj generic gpu", mine.GenericGPUJobs)))
	}
	return strings.Join(parts, "  ")
}

// compactGB renders a GB amount tersely: "90G", "1.5T".
func compactGB(gb float64) string {
	if gb >= 1024 {
		return fmt.Sprintf("%.1fT", gb/1024)
	}
	return fmt.Sprintf("%.0fG", gb)
}

// compactGPUTypes tightens a FormatGPUTypes string ("2x H100, 1x GPU") into the
// banner's per-model breakdown ("2×H100"), dropping the generic pseudo-type.
func compactGPUTypes(types string) string {
	var parts []string
	for _, p := range strings.Split(types, ", ") {
		if p == "" || strings.EqualFold(strings.TrimLeft(p, "0123456789x "), "gpu") {
			continue
		}
		parts = append(parts, strings.Replace(p, "x ", "×", 1))
	}
	return strings.Join(parts, " ")
}

// CapturesInput reports whether the tab is currently capturing raw text input
// (the filter bar is open and focused). The root consults this so global keys
// like 'q' are routed to the filter instead of quitting the app while the user
// is typing a query.
func (j *Jobs) CapturesInput() bool { return j.ft.CapturesInput() }

// ShortHelp returns the condensed help bindings.
func (j *Jobs) ShortHelp() []key.Binding { return j.ft.ShortHelp() }
