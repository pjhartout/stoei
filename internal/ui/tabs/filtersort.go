package tabs

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// column identifies a table column by its stable key. The slice order matches the
// rendered table.
type column struct {
	// key is the lowercase filter token (e.g. "state").
	key string
	// title is the rendered header label.
	title string
	// numeric marks columns whose sort is numeric-aware (parsed as a float when
	// possible).
	numeric bool
	// width is the rendered column width in characters. Zero means "derive a
	// default from the key" (filterTableColumnWidth).
	width int
	// noSort marks a column the "o" sort cycle skips while it remains filterable
	// (the Jobs-tab Timeline column).
	noSort bool
}

// jobColumns are the Jobs-tab columns in render order: JobID, Name, State, Time,
// Nodes, NodeList, and Timeline. Timeline is filterable but not sortable.
var jobColumns = []column{
	{key: "jobid", title: "Job ID", numeric: true},
	{key: "name", title: "Name"},
	{key: "state", title: "State"},
	{key: "time", title: "Time"},
	{key: "nodes", title: "Nodes", numeric: true},
	{key: "nodelist", title: "Node List"},
	{key: "timeline", title: "Timeline", noSort: true},
}

// columnIndex maps a column key to its index in jobColumns, or -1 if unknown.
func columnIndex(key string) int {
	return columnIndexIn(jobColumns, key)
}

// columnIndexIn maps a column key to its index in the given column set, or -1 if
// unknown. It is the column-set-aware form used by the reusable filter table.
func columnIndexIn(cols []column, key string) int {
	for i, c := range cols {
		if c.key == key {
			return i
		}
	}
	return -1
}

// filterState is the parsed form of a filter query: column-scoped filters plus a
// general substring applied across all columns. All values are lowercased for
// case-insensitive matching.
type filterState struct {
	// query is the raw query as typed.
	query string
	// columnFilters maps a column key to its required (lowercased) substring.
	columnFilters map[string]string
	// general is the lowercased substring that must appear in some column.
	general string
	// columns is the column set this filter resolves keys against. When nil it
	// defaults to jobColumns so the Jobs tab keeps working unchanged.
	columns []column
}

// cols returns the column set the filter resolves against, defaulting to
// jobColumns for the Jobs tab.
func (f filterState) cols() []column {
	if f.columns == nil {
		return jobColumns
	}
	return f.columns
}

// colValuePattern matches a "column:value" token in a filter query.
var colValuePattern = regexp.MustCompile(`(\w+):(\S+)`)

// parseFilter parses a raw query into a filterState. Tokens of the form
// "key:value" whose key names a known column become column filters; everything
// else is collapsed into the general substring.
func parseFilter(query string) filterState {
	return parseFilterWith(query, jobColumns)
}

// parseFilterWith parses a raw query against an explicit column set, so tabs
// other than Jobs can reuse the column-scoped filter logic.
func parseFilterWith(query string, cols []column) filterState {
	columnFilters := map[string]string{}
	remaining := query

	for _, m := range colValuePattern.FindAllStringSubmatch(query, -1) {
		colName := strings.ToLower(m[1])
		colValue := m[2]
		if columnIndexIn(cols, colName) >= 0 {
			columnFilters[colName] = strings.ToLower(colValue)
			remaining = strings.Replace(remaining, m[0], "", 1)
		}
	}

	general := strings.ToLower(strings.Join(strings.Fields(remaining), " "))

	return filterState{
		query:         query,
		columnFilters: columnFilters,
		general:       general,
		columns:       cols,
	}
}

// matches reports whether a row (the plain, markup-free cell values in column
// order) satisfies the filter. An empty query matches everything.
func (f filterState) matches(row []string) bool {
	if f.query == "" {
		return true
	}

	for colKey, want := range f.columnFilters {
		idx := columnIndexIn(f.cols(), colKey)
		if idx < 0 || idx >= len(row) {
			continue
		}
		if !strings.Contains(strings.ToLower(row[idx]), want) {
			return false
		}
	}

	if f.general != "" {
		found := false
		for _, cell := range row {
			if strings.Contains(strings.ToLower(cell), f.general) {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}

	return true
}

// sortDirection is the tri-state sort direction.
type sortDirection int

const (
	// sortNone leaves rows in their incoming (display) order.
	sortNone sortDirection = iota
	// sortAsc sorts ascending.
	sortAsc
	// sortDesc sorts descending.
	sortDesc
)

// sortState is the current sort selection: a column index (-1 when unsorted) and
// a direction.
type sortState struct {
	columnIdx int
	direction sortDirection
}

// cycle advances the sort state over the sortable columns only (a noSort column
// such as Timeline is skipped): none -> asc on the first sortable column; asc ->
// desc on the same column; desc -> asc on the next sortable column; wrapping past
// the last sortable column clears the sort.
func (s sortState) cycle(cols []column) sortState {
	sortable := make([]int, 0, len(cols))
	for i, c := range cols {
		if !c.noSort {
			sortable = append(sortable, i)
		}
	}
	if len(sortable) == 0 {
		return sortState{columnIdx: -1, direction: sortNone}
	}
	switch s.direction {
	case sortNone:
		return sortState{columnIdx: sortable[0], direction: sortAsc}
	case sortAsc:
		return sortState{columnIdx: s.columnIdx, direction: sortDesc}
	case sortDesc:
		pos := indexOf(sortable, s.columnIdx)
		next := pos + 1
		if pos < 0 || next >= len(sortable) {
			return sortState{columnIdx: -1, direction: sortNone}
		}
		return sortState{columnIdx: sortable[next], direction: sortAsc}
	default:
		return sortState{columnIdx: sortable[0], direction: sortAsc}
	}
}

// indexOf returns the position of v in xs, or -1 when absent.
func indexOf(xs []int, v int) int {
	for i, x := range xs {
		if x == v {
			return i
		}
	}
	return -1
}

// rankedKey is a precomputed, comparable sort key for one row. rank orders
// present (0) vs missing (±1) cells; kind orders numeric (0) before text (1)
// before empty (2); num/text hold the typed value. Input order for equal keys is
// preserved by sort.SliceStable, so no explicit tiebreaker field is needed.
type rankedKey struct {
	rank int
	kind int
	num  float64
	text string
}

// sortRows returns rows sorted per the sort state. When unsorted it returns rows
// unchanged. The key is numeric-aware: cells that parse as floats compare
// numerically and rank ahead of non-numeric text; empty cells sort last (or
// first when descending).
func (s sortState) sortRows(rows [][]string) [][]string {
	if s.direction == sortNone || s.columnIdx < 0 {
		return rows
	}
	idx := s.columnIdx
	reverse := s.direction == sortDesc

	missingRank := 1
	if reverse {
		missingRank = -1
	}

	key := func(row []string) rankedKey {
		raw := ""
		if idx < len(row) {
			raw = strings.TrimSpace(row[idx])
		}
		if raw == "" {
			return rankedKey{rank: missingRank, kind: 2}
		}
		if n, err := strconv.ParseFloat(strings.ReplaceAll(raw, ",", ""), 64); err == nil {
			return rankedKey{rank: 0, kind: 0, num: n}
		}
		return rankedKey{rank: 0, kind: 1, text: strings.ToLower(raw)}
	}

	// Pair each row with its precomputed key and sort the pairs together, so the
	// key always tracks the row across swaps.
	type pair struct {
		row []string
		key rankedKey
	}
	pairs := make([]pair, len(rows))
	for i, row := range rows {
		pairs[i] = pair{row: row, key: key(row)}
	}

	sort.SliceStable(pairs, func(a, b int) bool {
		if reverse {
			// Descending: compare with operands swapped so equal elements keep
			// their input order under the stable sort.
			return lessRanked(pairs[b].key, pairs[a].key)
		}
		return lessRanked(pairs[a].key, pairs[b].key)
	})

	out := make([][]string, len(pairs))
	for i, p := range pairs {
		out[i] = p.row
	}
	return out
}

// lessRanked reports whether ranked key a sorts before b, comparing field by
// field (rank, then kind, then the typed value).
func lessRanked(a, b rankedKey) bool {
	if a.rank != b.rank {
		return a.rank < b.rank
	}
	if a.kind != b.kind {
		return a.kind < b.kind
	}
	switch a.kind {
	case 0:
		return a.num < b.num
	case 1:
		return a.text < b.text
	default:
		return false
	}
}
