// Package tabs holds the per-tab screen components rendered by the root model.
// Each tab implements the ui.Component contract indirectly: the concrete types
// here expose Update/View/SetSize/SetStyles/ShortHelp/FullHelp with the same
// shapes, and the ui package adapts them where needed.
package tabs

import (
	"regexp"
	"strings"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/table"
	"charm.land/bubbles/v2/textinput"
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
}

// defaultJobsKeys returns the Jobs-tab bindings, porting the "/" filter and "o"
// sort bindings from filterable_table.BINDINGS.
func defaultJobsKeys() JobsKeyMap {
	return JobsKeyMap{
		Filter: key.NewBinding(
			key.WithKeys("/"),
			key.WithHelp("/", "filter"),
		),
		Sort: key.NewBinding(
			key.WithKeys("o"),
			key.WithHelp("o", "sort"),
		),
		ClearFilter: key.NewBinding(
			key.WithKeys("esc"),
			key.WithHelp("esc", "clear filter"),
		),
	}
}

// markupPattern strips any leftover bracket markup from a cell before it is used
// for filtering or sorting, mirroring filterable_table._RICH_MARKUP_PATTERN.
var markupPattern = regexp.MustCompile(`\[.*?\]`)

// Jobs is the live running-jobs tab. It renders a bubbles/v2 table from the
// store's RunningJobs, colors the State column, keeps a My-Usage banner, and
// supports column-scoped filtering and numeric-aware sorting. The cursor is
// preserved across refreshes by re-selecting the previously selected job id
// (I6); the table is never rebuilt from scratch on a tick, only its rows are
// replaced and the cursor restored.
type Jobs struct {
	store    *store.Store
	username string
	styles   theme.Styles
	keys     JobsKeyMap

	table  table.Model
	filter textinput.Model

	// filtering is true while the filter input is open and focused.
	filtering   bool
	filterState filterState
	sortState   sortState

	width  int
	height int
}

// NewJobs returns a Jobs tab bound to s for the given username, styled with
// styles. The username drives the My-Usage banner lookup.
func NewJobs(s *store.Store, username string, styles theme.Styles) *Jobs {
	cols := make([]table.Column, len(jobColumns))
	for i, c := range jobColumns {
		cols[i] = table.Column{Title: c.title, Width: defaultColumnWidth(c.key)}
	}

	t := table.New(
		table.WithColumns(cols),
		table.WithFocused(true),
	)
	t.SetStyles(tableStyles(styles))

	fi := textinput.New()
	fi.Placeholder = "Filter… (e.g. 'state:RUNNING' or a search term)"

	j := &Jobs{
		store:       s,
		username:    username,
		styles:      styles,
		keys:        defaultJobsKeys(),
		table:       t,
		filter:      fi,
		filterState: parseFilter(""),
		sortState:   sortState{columnIdx: -1, direction: sortNone},
	}
	j.Refresh()
	return j
}

// defaultColumnWidth returns a sensible initial width per column key.
func defaultColumnWidth(key string) int {
	switch key {
	case "jobid":
		return 12
	case "name":
		return 24
	case "state":
		return 12
	case "time":
		return 12
	case "nodes":
		return 6
	case "nodelist":
		return 20
	default:
		return 10
	}
}

// tableStyles maps the app theme onto the bubbles table styles.
func tableStyles(styles theme.Styles) table.Styles {
	s := table.DefaultStyles()
	s.Header = s.Header.Foreground(styles.Title.GetForeground()).Bold(true)
	s.Selected = s.Selected.Foreground(styles.TabActive.GetForeground()).Bold(true)
	return s
}

// SetStyles re-themes the tab after a background/theme change.
func (j *Jobs) SetStyles(styles theme.Styles) {
	j.styles = styles
	j.table.SetStyles(tableStyles(styles))
	j.Refresh()
}

// SetSize informs the tab of the available area and resizes the inner table,
// reserving rows for the banner and (when open) the filter input.
func (j *Jobs) SetSize(width, height int) {
	j.width = width
	j.height = height
	j.filter.SetWidth(max(width-2, 10))

	tableHeight := height - bannerReservedRows
	if j.filtering {
		tableHeight -= filterReservedRows
	}
	if tableHeight < 1 {
		tableHeight = 1
	}
	j.table.SetWidth(width)
	j.table.SetHeight(tableHeight)
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
	switch msg := msg.(type) {
	case tea.KeyPressMsg:
		if j.filtering {
			return j.updateFiltering(msg)
		}
		switch {
		case key.Matches(msg, j.keys.Filter):
			j.filtering = true
			j.filter.Focus()
			j.SetSize(j.width, j.height)
			return j, textinput.Blink
		case key.Matches(msg, j.keys.Sort):
			j.sortState = j.sortState.cycle(len(jobColumns))
			j.Refresh()
			return j, nil
		}
	}

	var cmd tea.Cmd
	j.table, cmd = j.table.Update(msg)
	return j, cmd
}

// updateFiltering handles input while the filter bar is open: Esc clears and
// closes, Enter closes but keeps the query, and every other key edits the query
// and re-applies the filter live.
func (j *Jobs) updateFiltering(msg tea.KeyPressMsg) (*Jobs, tea.Cmd) {
	switch {
	case key.Matches(msg, j.keys.ClearFilter):
		j.filtering = false
		j.filter.SetValue("")
		j.filter.Blur()
		j.filterState = parseFilter("")
		j.SetSize(j.width, j.height)
		j.Refresh()
		return j, nil
	case msg.String() == "enter":
		j.filtering = false
		j.filter.Blur()
		j.SetSize(j.width, j.height)
		return j, nil
	}

	var cmd tea.Cmd
	j.filter, cmd = j.filter.Update(msg)
	j.filterState = parseFilter(j.filter.Value())
	j.Refresh()
	return j, cmd
}

// Refresh rebuilds the table rows from the store, preserving the cursor by job
// id (I6). It is called on every fast tick (the store already holds freshly
// fetched running jobs) and after a filter/sort change. The cursor is restored
// by id; when the previously selected job is gone the index is clamped.
func (j *Jobs) Refresh() {
	selectedID := j.selectedJobID()

	plain := j.plainRows()
	filtered := plain[:0:0]
	for _, row := range plain {
		if j.filterState.matches(row) {
			filtered = append(filtered, row)
		}
	}
	sorted := j.sortState.sortRows(filtered)

	rows := make([]table.Row, len(sorted))
	for i, row := range sorted {
		rows[i] = j.displayRow(row)
	}
	j.table.SetRows(rows)

	reselect(&j.table, sorted, selectedID)
}

// plainRows builds the markup-free cell values for the merged running-plus-history
// job list in store order (running/pending jobs first, then deduped completed/
// failed history jobs). The first column (job id) is the stable key used for
// filtering, sorting and cursor restoration.
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
		})
	}
	return rows
}

// displayRow converts a plain row into a rendered table row, coloring the State
// cell. The other cells are passed through verbatim.
func (j *Jobs) displayRow(plain []string) table.Row {
	row := make(table.Row, len(plain))
	copy(row, plain)
	if len(row) > stateColumnIndex {
		row[stateColumnIndex] = colorState(plain[stateColumnIndex], j.styles)
	}
	return row
}

// stateColumnIndex is the index of the State column in jobColumns.
var stateColumnIndex = columnIndex("state")

// selectedJobID returns the job id (first cell, markup-stripped) of the
// currently selected table row, or "" when the table is empty.
func (j *Jobs) selectedJobID() string {
	row := j.table.SelectedRow()
	if len(row) == 0 {
		return ""
	}
	return strings.TrimSpace(markupPattern.ReplaceAllString(row[0], ""))
}

// reselect restores the table cursor to the row whose job id matches id (I6).
// When the id is no longer present the prior cursor index is clamped into range,
// matching filterable_table's by-key-then-by-position restoration.
func reselect(t *table.Model, sorted [][]string, id string) {
	if id == "" || len(sorted) == 0 {
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

	parts := []string{banner, ""}
	if j.filtering {
		parts = append(parts, j.styles.Text.Render(j.filter.View()))
	}
	parts = append(parts, j.table.View())

	return lipgloss.JoinVertical(lipgloss.Left, parts...)
}

// banner renders the "My Usage" summary line for the current user from the
// store's running-user statistics. Ports TableController.update_my_usage_summary.
func (j *Jobs) banner() string {
	return store.MyUsageSummary(j.store.RunningUserStats(), j.username)
}

// CapturesInput reports whether the tab is currently capturing raw text input
// (the filter bar is open and focused). The root consults this so global keys
// like 'q' are routed to the filter instead of quitting the app while the user
// is typing a query.
func (j *Jobs) CapturesInput() bool { return j.filtering }

// ShortHelp returns the condensed help bindings.
func (j *Jobs) ShortHelp() []key.Binding {
	return []key.Binding{j.keys.Filter, j.keys.Sort}
}

// FullHelp returns the expanded help bindings.
func (j *Jobs) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{j.table.KeyMap.LineUp, j.table.KeyMap.LineDown},
		{j.keys.Filter, j.keys.Sort, j.keys.ClearFilter},
	}
}
