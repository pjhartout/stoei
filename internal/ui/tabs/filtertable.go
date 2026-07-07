package tabs

import (
	"strings"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/table"
	"charm.land/bubbles/v2/textinput"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/ui/theme"
)

// rowDecorator turns a plain (markup-free) row into a display row with theme
// coloring applied. The plain row is what filtering, sorting, and cursor
// restoration operate on; the decorated row is only for rendering. Returning the
// input unchanged yields an undecorated table.
type rowDecorator func(plain []string, styles theme.Styles) table.Row

// filterTable is a reusable filterable, sortable bubbles/v2 table shared by the
// Nodes, Users, and Priority tabs. It factors out the Jobs-tab pattern: a table
// fed plain rows, a column-scoped "/" filter, an "o" sort cycle, and cursor
// restoration by the stable first-column key. Each owning tab supplies the
// columns, the plain rows (rebuilt from the store), and a row decorator.
type filterTable struct {
	styles theme.Styles
	keys   JobsKeyMap

	columns   []column
	decorator rowDecorator

	table  table.Model
	filter textinput.Model

	filtering   bool
	filterState filterState
	sortState   sortState

	// rows is the current plain (undecorated) row set, kept so a re-theme or
	// re-sort can rebuild the display rows without the owner re-supplying them.
	rows [][]string

	width  int
	height int

	// xOffset is the horizontal scroll position, engaged only when the fitted
	// columns overflow the pane.
	xOffset int
}

// newFilterTable builds a filterTable for the given columns and decorator. The
// decorator may be nil for an undecorated table.
func newFilterTable(columns []column, styles theme.Styles, decorator rowDecorator) filterTable {
	cols := make([]table.Column, len(columns))
	for i, c := range columns {
		cols[i] = table.Column{Title: c.title, Width: filterTableColumnWidth(c)}
	}

	t := table.New(table.WithColumns(cols), table.WithFocused(true))
	t.SetStyles(tableStyles(styles))

	fi := textinput.New()
	fi.Placeholder = "Filter… (e.g. 'state:idle' or a search term)"

	if decorator == nil {
		decorator = func(plain []string, _ theme.Styles) table.Row {
			row := make(table.Row, len(plain))
			copy(row, plain)
			return row
		}
	}

	return filterTable{
		styles:      styles,
		keys:        defaultJobsKeys(),
		columns:     columns,
		decorator:   decorator,
		table:       t,
		filter:      fi,
		filterState: parseFilterWith("", columns),
		sortState:   sortState{columnIdx: -1, direction: sortNone},
	}
}

// filterTableColumnWidth returns the column's explicit width when set, otherwise
// a default derived from the key (wider for list/name-style columns).
func filterTableColumnWidth(c column) int {
	if c.width > 0 {
		return c.width
	}
	switch {
	case strings.Contains(c.key, "list"), strings.Contains(c.key, "name"),
		strings.Contains(c.key, "node"), strings.Contains(c.key, "types"),
		strings.Contains(c.key, "reason"), c.key == "account", c.key == "partitions":
		return 18
	default:
		return 12
	}
}

// SetKeyMode switches the table's filter/sort/clear bindings to the given
// keybinding preset (vim default or emacs).
func (ft *filterTable) SetKeyMode(mode string) { ft.keys = jobsKeysForMode(mode) }

// SetStyles re-themes the table and rebuilds the display rows.
func (ft *filterTable) SetStyles(styles theme.Styles) {
	ft.styles = styles
	ft.rebuild()
}

// syncWidth sizes the inner table to the full fitted-content width so the
// bubbles viewport never truncates rows itself; View windows the result back to
// the pane.
func (ft *filterTable) syncWidth() {
	content := tableContentWidth(ft.table.Columns())
	w := max(ft.width, content)
	ft.table.SetWidth(w)
	ft.table.SetStyles(tableStylesWidth(ft.styles, w))
	ft.xOffset = clampHScroll(ft.xOffset, content, ft.width)
}

// SetSize resizes the inner table, reserving a row for the filter input when it
// is open.
func (ft *filterTable) SetSize(width, height int) {
	ft.width = width
	ft.height = height
	ft.filter.SetWidth(max(width-2, 10))

	h := height
	if ft.filtering {
		h -= filterReservedRows
	}
	if h < 1 {
		h = 1
	}
	ft.table.SetHeight(h)
	ft.syncWidth()
}

// SetRows replaces the plain row set and rebuilds the table, preserving the
// cursor by the stable first-column key (I6).
func (ft *filterTable) SetRows(rows [][]string) {
	ft.rows = rows
	ft.rebuild()
}

// rebuild re-applies the filter and sort to the plain rows and pushes decorated
// rows into the table, restoring the cursor by stable key.
func (ft *filterTable) rebuild() {
	selected := ft.selectedKey()

	filtered := make([][]string, 0, len(ft.rows))
	for _, row := range ft.rows {
		if ft.filterState.matches(row) {
			filtered = append(filtered, row)
		}
	}
	sorted := ft.sortState.sortRows(filtered)

	fitTableColumns(&ft.table, sortedColumns(ft.columns, ft.sortState), sorted, filterTableColumnWidth)
	ft.syncWidth()

	display := make([]table.Row, len(sorted))
	for i, row := range sorted {
		display[i] = ft.decorator(row, ft.styles)
	}
	ft.table.SetRows(display)

	reselect(&ft.table, sorted, selected)
}

// selectedKey returns the stable first-column key of the selected row, or "" when
// the table is empty.
func (ft *filterTable) selectedKey() string {
	row := ft.table.SelectedRow()
	if len(row) == 0 {
		return ""
	}
	return strings.TrimSpace(row[0])
}

// SelectedKey returns the stable first-column key of the selected row (markup
// stripped), or "" when the table is empty. It is exported so the root can open a
// detail modal for the highlighted row.
func (ft *filterTable) SelectedKey() string { return ft.selectedKey() }

// SelectedCell returns the value of column col in the selected row, or "" when the
// table is empty or col is out of range. The Priority tab uses it because its
// detail target is not always the first column.
func (ft *filterTable) SelectedCell(col int) string {
	row := ft.table.SelectedRow()
	if col < 0 || col >= len(row) {
		return ""
	}
	return strings.TrimSpace(row[col])
}

// Update handles table-local input: "/" opens the filter, "o" cycles the sort,
// and otherwise the message is forwarded to the embedded table (navigation).
func (ft *filterTable) Update(msg tea.Msg) tea.Cmd {
	if km, ok := msg.(tea.KeyPressMsg); ok {
		if ft.filtering {
			return ft.updateFiltering(km)
		}
		switch {
		case key.Matches(km, ft.keys.Filter):
			ft.filtering = true
			ft.filter.Focus()
			ft.SetSize(ft.width, ft.height)
			return textinput.Blink
		case key.Matches(km, ft.keys.Sort):
			ft.sortState = ft.sortState.cycle(ft.columns)
			ft.rebuild()
			return nil
		case key.Matches(km, ft.keys.ScrollLeft):
			ft.xOffset = clampHScroll(ft.xOffset-hscrollStep, tableContentWidth(ft.table.Columns()), ft.width)
			return nil
		case key.Matches(km, ft.keys.ScrollRight):
			ft.xOffset = clampHScroll(ft.xOffset+hscrollStep, tableContentWidth(ft.table.Columns()), ft.width)
			return nil
		}
	}

	var cmd tea.Cmd
	ft.table, cmd = ft.table.Update(msg)
	return cmd
}

// updateFiltering handles input while the filter bar is open.
func (ft *filterTable) updateFiltering(msg tea.KeyPressMsg) tea.Cmd {
	switch {
	case key.Matches(msg, ft.keys.ClearFilter):
		ft.filtering = false
		ft.filter.SetValue("")
		ft.filter.Blur()
		ft.filterState = parseFilterWith("", ft.columns)
		ft.SetSize(ft.width, ft.height)
		ft.rebuild()
		return nil
	case msg.String() == "enter":
		ft.filtering = false
		ft.filter.Blur()
		ft.SetSize(ft.width, ft.height)
		return nil
	}

	var cmd tea.Cmd
	ft.filter, cmd = ft.filter.Update(msg)
	ft.filterState = parseFilterWith(ft.filter.Value(), ft.columns)
	ft.rebuild()
	return cmd
}

// CapturesInput reports whether the filter bar is open and consuming text.
func (ft *filterTable) CapturesInput() bool { return ft.filtering }

// View renders the optional filter input above the table.
func (ft *filterTable) View() string {
	tbl := hscrollWindow(ft.table.View(), ft.xOffset, tableContentWidth(ft.table.Columns()), ft.width)
	if !ft.filtering {
		return tbl
	}
	return lipgloss.JoinVertical(lipgloss.Left,
		ft.styles.Text.Render(ft.filter.View()),
		tbl,
	)
}

// ShortHelp returns the filter/sort bindings.
func (ft *filterTable) ShortHelp() []key.Binding {
	return []key.Binding{ft.keys.Filter, ft.keys.Sort}
}

// FullHelp returns the table navigation plus filter/sort bindings.
func (ft *filterTable) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{ft.table.KeyMap.LineUp, ft.table.KeyMap.LineDown, ft.keys.ScrollLeft, ft.keys.ScrollRight},
		{ft.keys.Filter, ft.keys.Sort, ft.keys.ClearFilter},
	}
}
