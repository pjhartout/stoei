package tabs

import (
	"strings"
	"testing"

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
