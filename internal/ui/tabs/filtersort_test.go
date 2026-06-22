package tabs

import (
	"reflect"
	"testing"
)

func TestParseFilterColumnScoped(t *testing.T) {
	fs := parseFilter("state:RUNNING")
	if got := fs.columnFilters["state"]; got != "running" {
		t.Errorf("state filter = %q; want %q", got, "running")
	}
	if fs.general != "" {
		t.Errorf("general = %q; want empty", fs.general)
	}
}

func TestParseFilterColumnAndGeneral(t *testing.T) {
	fs := parseFilter("name:train alpha")
	if got := fs.columnFilters["name"]; got != "train" {
		t.Errorf("name filter = %q; want %q", got, "train")
	}
	if fs.general != "alpha" {
		t.Errorf("general = %q; want %q", fs.general, "alpha")
	}
}

func TestParseFilterUnknownColumnFallsToGeneral(t *testing.T) {
	// "foo" is not a column, so the whole token becomes general substring.
	fs := parseFilter("foo:bar")
	if len(fs.columnFilters) != 0 {
		t.Errorf("columnFilters = %v; want empty", fs.columnFilters)
	}
	if fs.general != "foo:bar" {
		t.Errorf("general = %q; want %q", fs.general, "foo:bar")
	}
}

func TestFilterMatchesColumnScoped(t *testing.T) {
	fs := parseFilter("state:RUNNING")
	running := []string{"1001", "train", "RUNNING", "1:00", "1", "node01"}
	pending := []string{"1002", "eval", "PENDING", "0:00", "2", ""}

	if !fs.matches(running) {
		t.Error("running row should match state:RUNNING")
	}
	if fs.matches(pending) {
		t.Error("pending row should not match state:RUNNING")
	}
}

func TestFilterMatchesGeneralSubstring(t *testing.T) {
	fs := parseFilter("node01")
	row := []string{"1001", "train", "RUNNING", "1:00", "1", "node01"}
	other := []string{"1002", "eval", "PENDING", "0:00", "2", "node99"}

	if !fs.matches(row) {
		t.Error("row containing node01 should match")
	}
	if fs.matches(other) {
		t.Error("row without node01 should not match")
	}
}

func TestEmptyFilterMatchesEverything(t *testing.T) {
	fs := parseFilter("")
	if !fs.matches([]string{"anything"}) {
		t.Error("empty filter should match every row")
	}
}

func TestSortRowsNumericAware(t *testing.T) {
	// Sort by the Nodes column (index 4), ascending. "2" must come before "10"
	// numerically, not lexically.
	rows := [][]string{
		{"a", "", "", "", "10", ""},
		{"b", "", "", "", "2", ""},
		{"c", "", "", "", "1", ""},
	}
	s := sortState{columnIdx: 4, direction: sortAsc}
	got := s.sortRows(rows)

	order := []string{got[0][0], got[1][0], got[2][0]}
	want := []string{"c", "b", "a"}
	if !reflect.DeepEqual(order, want) {
		t.Errorf("numeric asc order = %v; want %v", order, want)
	}
}

func TestSortRowsDescending(t *testing.T) {
	rows := [][]string{
		{"a", "", "", "", "1", ""},
		{"b", "", "", "", "10", ""},
		{"c", "", "", "", "2", ""},
	}
	s := sortState{columnIdx: 4, direction: sortDesc}
	got := s.sortRows(rows)

	order := []string{got[0][0], got[1][0], got[2][0]}
	want := []string{"b", "c", "a"}
	if !reflect.DeepEqual(order, want) {
		t.Errorf("numeric desc order = %v; want %v", order, want)
	}
}

func TestSortNoneLeavesOrder(t *testing.T) {
	rows := [][]string{{"a"}, {"b"}, {"c"}}
	s := sortState{columnIdx: -1, direction: sortNone}
	got := s.sortRows(rows)
	if !reflect.DeepEqual(got, rows) {
		t.Errorf("sortNone changed order: %v", got)
	}
}

func TestSortCycle(t *testing.T) {
	s := sortState{columnIdx: -1, direction: sortNone}

	s = s.cycle(jobColumns)
	if s.columnIdx != 0 || s.direction != sortAsc {
		t.Fatalf("first cycle = %+v; want col 0 asc", s)
	}
	s = s.cycle(jobColumns)
	if s.columnIdx != 0 || s.direction != sortDesc {
		t.Fatalf("second cycle = %+v; want col 0 desc", s)
	}
	s = s.cycle(jobColumns)
	if s.columnIdx != 1 || s.direction != sortAsc {
		t.Fatalf("third cycle = %+v; want col 1 asc", s)
	}
}

func TestSortCycleWrapsToCleared(t *testing.T) {
	// Starting at the last SORTABLE column descending, cycling clears the sort.
	// The Timeline column (noSort) is skipped, so the last sortable column is the
	// one before it.
	last := lastSortableIndex(jobColumns)
	s := sortState{columnIdx: last, direction: sortDesc}
	s = s.cycle(jobColumns)
	if s.columnIdx != -1 || s.direction != sortNone {
		t.Errorf("wrap cycle = %+v; want cleared", s)
	}
}

// TestSortCycleSkipsNonSortable verifies the "o" cycle never lands on a noSort
// column (Timeline). Ports the [c for c in columns if c.sortable] filter in
// filterable_table.action_cycle_sort.
func TestSortCycleSkipsNonSortable(t *testing.T) {
	timelineIdx := columnIndex("timeline")
	if timelineIdx < 0 {
		t.Fatal("timeline column missing from jobColumns")
	}
	s := sortState{columnIdx: -1, direction: sortNone}
	// Walk the full cycle and assert the cursor is never the Timeline column.
	for i := 0; i < 3*len(jobColumns); i++ {
		s = s.cycle(jobColumns)
		if s.direction != sortNone && s.columnIdx == timelineIdx {
			t.Fatalf("cycle landed on non-sortable Timeline column at step %d", i)
		}
	}
}

// lastSortableIndex returns the index of the last sortable column.
func lastSortableIndex(cols []column) int {
	last := -1
	for i, c := range cols {
		if !c.noSort {
			last = i
		}
	}
	return last
}
