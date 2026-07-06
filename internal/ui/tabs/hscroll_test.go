package tabs

import (
	"strings"
	"testing"

	"github.com/pjhartout/stoei/internal/store"
)

func TestHScrollWindowPassthroughWhenContentFits(t *testing.T) {
	view := "abc\ndef"
	if got := hscrollWindow(view, 0, 10, 20); got != view {
		t.Errorf("expected passthrough, got %q", got)
	}
}

func TestHScrollWindowCutsEveryLineToPane(t *testing.T) {
	view := "0123456789\nabcdefghij"
	got := hscrollWindow(view, 4, 10, 4)
	want := "4567\nefgh"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
	for _, line := range strings.Split(got, "\n") {
		if len(line) > 4 {
			t.Errorf("line %q wider than pane", line)
		}
	}
}

// TestSortedColumnHeaderShowsDirection asserts the active sort column's header
// carries the direction arrow so the user can see what orders the table.
func TestSortedColumnHeaderShowsDirection(t *testing.T) {
	j, _ := seedJobs(t, []store.RunningJob{
		{ID: "1001", Name: "a", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "n01"},
	})
	if v := j.View(); strings.Contains(v, "↑") || strings.Contains(v, "↓") {
		t.Errorf("unsorted table should carry no sort arrow:\n%s", v)
	}

	j.sortState = sortState{columnIdx: 0, direction: sortAsc}
	j.Refresh()
	if !strings.Contains(j.View(), "Job ID ↑") {
		t.Errorf("ascending sort arrow missing from header:\n%s", j.View())
	}

	j.sortState = sortState{columnIdx: 0, direction: sortDesc}
	j.Refresh()
	if !strings.Contains(j.View(), "Job ID ↓") {
		t.Errorf("descending sort arrow missing from header:\n%s", j.View())
	}

	j.sortState = sortState{columnIdx: -1, direction: sortNone}
	j.Refresh()
	if v := j.View(); strings.Contains(v, "↑") || strings.Contains(v, "↓") {
		t.Errorf("cleared sort should remove the arrow:\n%s", v)
	}
}

func TestClampHScroll(t *testing.T) {
	if got := clampHScroll(100, 30, 20); got != 10 {
		t.Errorf("over-scroll: got %d, want 10", got)
	}
	if got := clampHScroll(-5, 30, 20); got != 0 {
		t.Errorf("negative: got %d, want 0", got)
	}
	if got := clampHScroll(8, 20, 40); got != 0 {
		t.Errorf("content fits: got %d, want 0", got)
	}
}
