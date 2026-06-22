package tabs

import (
	"regexp"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// seedJobs builds a Jobs tab over a store seeded with the given running jobs.
func seedJobs(t *testing.T, jobs []store.RunningJob) (*Jobs, *store.Store) {
	t.Helper()
	st := store.New()
	st.SetRunningJobs(jobs, st.NextGen(store.SectionRunningJobs), nil)
	j := NewJobs(st, "alice", theme.BuildStyles(theme.Charm(), true))
	j.SetSize(100, 30)
	return j, st
}

// TestColumnsFitLongValues asserts columns grow to fit long job IDs and names so
// they render in full rather than being truncated with "…".
func TestColumnsFitLongValues(t *testing.T) {
	j, _ := seedJobs(t, []store.RunningJob{
		{ID: "5098106_[0-99%10]", Name: "very-long-experiment-name-v3", State: "PENDING", Time: "0:00", Nodes: "1", NodeList: "n01"},
	})
	out := j.View()
	if !strings.Contains(out, "5098106_[0-99%10]") {
		t.Errorf("long job id truncated:\n%s", out)
	}
	if !strings.Contains(out, "very-long-experiment-name-v3") {
		t.Errorf("long job name truncated:\n%s", out)
	}
	if strings.Contains(out, "…") {
		t.Errorf("unexpected ellipsis in jobs view:\n%s", out)
	}
}

// TestSelectedRowHighlightSpansLine asserts the selected-row highlight bar spans
// the whole line: it must fill the full table width, and the colored State cell
// must use a foreground-only reset (ESC[39m) so the background is not cleared
// mid-line (which previously left only the leading columns highlighted).
func TestSelectedRowHighlightSpansLine(t *testing.T) {
	j, _ := seedJobs(t, []store.RunningJob{
		{ID: "5098105", Name: "train", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "n01"},
	})
	j.SetSize(60, 12)

	var row string
	for _, ln := range strings.Split(j.View(), "\n") {
		if strings.Contains(ln, "5098105") {
			row = ln
		}
	}
	if row == "" {
		t.Fatal("selected row not found")
	}
	if !strings.Contains(row, "\x1b[39m") {
		t.Errorf("State cell should end with a foreground-only reset (ESC[39m):\n%q", row)
	}
	plain := regexp.MustCompile(`\x1b\[[0-9;]*m`).ReplaceAllString(row, "")
	if w := len([]rune(plain)); w != 60 {
		t.Errorf("selected row width = %d; want 60 (bar spans the full line)", w)
	}
}

// TestCursorPreservedAcrossReorder asserts I6: after the running-jobs list is
// reordered/changed, the cursor stays on the same job id.
func TestCursorPreservedAcrossReorder(t *testing.T) {
	jobs := []store.RunningJob{
		{ID: "1001", Name: "a", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "n01"},
		{ID: "1002", Name: "b", State: "RUNNING", Time: "2:00", Nodes: "1", NodeList: "n02"},
		{ID: "1003", Name: "c", State: "RUNNING", Time: "3:00", Nodes: "1", NodeList: "n03"},
	}
	j, st := seedJobs(t, jobs)

	// Move the cursor to job "1003" (index 2).
	j.table.SetCursor(2)
	if got := j.selectedJobID(); got != "1003" {
		t.Fatalf("setup: selected = %q; want 1003", got)
	}

	// Reorder: 1003 now first, plus a brand-new job and one removed.
	reordered := []store.RunningJob{
		{ID: "1003", Name: "c", State: "RUNNING", Time: "3:05", Nodes: "1", NodeList: "n03"},
		{ID: "1004", Name: "d", State: "PENDING", Time: "0:00", Nodes: "2", NodeList: ""},
		{ID: "1001", Name: "a", State: "RUNNING", Time: "1:05", Nodes: "1", NodeList: "n01"},
	}
	st.SetRunningJobs(reordered, st.NextGen(store.SectionRunningJobs), nil)
	j.Refresh()

	if got := j.selectedJobID(); got != "1003" {
		t.Errorf("after reorder: selected = %q; want 1003 (cursor must follow id)", got)
	}
}

// TestLiveTimeUpdatesWithoutMovingCursor asserts that a refresh that only changes
// the elapsed Time column updates the displayed value while keeping the cursor.
func TestLiveTimeUpdatesWithoutMovingCursor(t *testing.T) {
	jobs := []store.RunningJob{
		{ID: "1001", Name: "a", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "n01"},
		{ID: "1002", Name: "b", State: "RUNNING", Time: "2:00", Nodes: "1", NodeList: "n02"},
	}
	j, st := seedJobs(t, jobs)
	j.table.SetCursor(1)

	advanced := []store.RunningJob{
		{ID: "1001", Name: "a", State: "RUNNING", Time: "1:05", Nodes: "1", NodeList: "n01"},
		{ID: "1002", Name: "b", State: "RUNNING", Time: "2:05", Nodes: "1", NodeList: "n02"},
	}
	st.SetRunningJobs(advanced, st.NextGen(store.SectionRunningJobs), nil)
	j.Refresh()

	if got := j.selectedJobID(); got != "1002" {
		t.Errorf("cursor moved: selected = %q; want 1002", got)
	}
	if !strings.Contains(j.table.View(), "2:05") {
		t.Errorf("live Time not updated; view:\n%s", j.table.View())
	}
}

// TestFilterNarrowsRows asserts the filter applies live through Refresh.
func TestFilterNarrowsRows(t *testing.T) {
	jobs := []store.RunningJob{
		{ID: "1001", Name: "train", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "n01"},
		{ID: "1002", Name: "eval", State: "PENDING", Time: "0:00", Nodes: "2", NodeList: ""},
	}
	j, _ := seedJobs(t, jobs)

	j.filterState = parseFilter("state:RUNNING")
	j.Refresh()

	view := j.table.View()
	if !strings.Contains(view, "train") {
		t.Errorf("running job missing after filter; view:\n%s", view)
	}
	if strings.Contains(view, "eval") {
		t.Errorf("pending job should be filtered out; view:\n%s", view)
	}
}

// TestBannerUsesUsername asserts the My-Usage banner reflects the configured
// username's running jobs derived from the all-users data.
func TestBannerUsesUsername(t *testing.T) {
	st := store.New()
	st.SetAllUsersJobs([]store.AllUsersJob{
		{ID: "1001", User: "alice", State: "RUNNING", NumNodes: "1", NodeList: "n01", TRES: "cpu=4,mem=8G"},
	}, st.NextGen(store.SectionAllUsersJobs), nil)
	j := NewJobs(st, "alice", theme.BuildStyles(theme.Charm(), true))

	if got := j.banner(); !strings.Contains(got, "My Usage") {
		t.Errorf("banner = %q; want a My Usage summary", got)
	}
}

// TestHistoryJobsRenderInTable asserts Fix B end-to-end at the tab level: a
// completed/failed history job that is not currently running is merged into the
// Jobs table and shown alongside running jobs.
func TestHistoryJobsRenderInTable(t *testing.T) {
	j, st := seedJobs(t, []store.RunningJob{
		{ID: "1001", Name: "running_job", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "n01"},
	})
	st.SetHistory([]store.HistoryJob{
		{ID: "2002", Name: "done_job", State: "COMPLETED", Elapsed: "0:42", NodeList: "n02"},
		{ID: "2003", Name: "broke_job", State: "FAILED", Elapsed: "0:05", NodeList: "n03"},
	}, store.HistoryStats{}, st.NextGen(store.SectionHistory), nil)
	j.Refresh()

	view := j.table.View()
	for _, want := range []string{"1001", "running_job", "2002", "done_job", "2003", "broke_job"} {
		if !strings.Contains(view, want) {
			t.Errorf("merged table view missing %q; view:\n%s", want, view)
		}
	}
}

// TestEmacsModeRebindsFilterSort asserts the emacs preset rebinds the Jobs-tab
// filter to ctrl+s and sort to ctrl+o, while the vim default keeps "/" and "o".
// Ports the FILTER_SHOW=ctrl+s / SORT_CYCLE=ctrl+o emacs rebinding.
func TestEmacsModeRebindsFilterSort(t *testing.T) {
	j, _ := seedJobs(t, []store.RunningJob{
		{ID: "1", Name: "a", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "n1"},
	})

	// Default (vim): "/" opens the filter.
	if !slashOpensFilter(t, j) {
		t.Fatal("vim mode: '/' did not open the filter")
	}

	// Switch to emacs: ctrl+s opens the filter, "/" no longer does.
	j.SetKeyMode(EmacsMode)
	if slashOpensFilter(t, j) {
		t.Error("emacs mode: '/' should not open the filter")
	}
	_, _ = j.Update(tea.KeyPressMsg{Code: 's', Mod: tea.ModCtrl})
	if !j.filtering {
		t.Error("emacs mode: ctrl+s did not open the filter")
	}
}

// slashOpensFilter feeds "/" to a fresh-from-filter Jobs tab and reports whether
// the filter opened, then closes it so the tab is reusable.
func slashOpensFilter(t *testing.T, j *Jobs) bool {
	t.Helper()
	_, _ = j.Update(tea.KeyPressMsg{Code: '/', Text: "/"})
	opened := j.filtering
	if opened {
		_, _ = j.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	}
	return opened
}
