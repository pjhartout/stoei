package ui

import (
	"testing"

	"github.com/pjhartout/stoei/internal/store"
)

// TestRunningJobCompletionMergesIntoHistory drives the full mid-session path: a
// job leaves the running queue, the app looks it up via the controller (the fake
// stands in for scontrol), and it appears as a completed history row — with no
// sacct/history fetch involved.
func TestRunningJobCompletionMergesIntoHistory(t *testing.T) {
	fc := &store.FakeClient{
		CompletedJobFound: true,
		CompletedJobData:  store.HistoryJob{ID: "B", Name: "job-b", State: "COMPLETED", Elapsed: "00:05:00"},
	}
	a := newTestApp(t, fc)

	// First refresh establishes the running set {A, B}.
	m, _ := a.Update(runningJobsMsg{gen: 1, jobs: []store.RunningJob{{ID: "A"}, {ID: "B"}}})
	a = m.(App)
	// Next refresh shows B gone → a completion to look up.
	m, cmd := a.Update(runningJobsMsg{gen: 2, jobs: []store.RunningJob{{ID: "A"}}})
	a = m.(App)

	msgs := drainCmd(cmd) // runs the controller lookup for B
	if fc.LastCompletedJobID != "B" {
		t.Fatalf("looked up %q, want B", fc.LastCompletedJobID)
	}
	for _, msg := range msgs {
		m, _ = a.Update(msg)
		a = m.(App)
	}

	var found bool
	for _, j := range a.store.MergedJobs() {
		if j.ID == "B" && !j.Active && j.State == "COMPLETED" {
			found = true
		}
	}
	if !found {
		t.Error("completed job B did not appear as a history row")
	}
}

// TestRunningJobsNoCompletionsNoLookup asserts a steady running set issues no
// controller lookups (no spurious scontrol traffic each tick).
func TestRunningJobsNoCompletionsNoLookup(t *testing.T) {
	fc := &store.FakeClient{}
	a := newTestApp(t, fc)

	m, _ := a.Update(runningJobsMsg{gen: 1, jobs: []store.RunningJob{{ID: "A"}}})
	a = m.(App)
	_, cmd := a.Update(runningJobsMsg{gen: 2, jobs: []store.RunningJob{{ID: "A"}}})
	drainCmd(cmd)

	if fc.LastCompletedJobID != "" {
		t.Errorf("looked up %q, want no lookup for an unchanged running set", fc.LastCompletedJobID)
	}
}

// TestMultipleCompletionsUseBulkHistory asserts two jobs vanishing together
// issue one history refresh rather than parallel per-job controller lookups.
func TestMultipleCompletionsUseBulkHistory(t *testing.T) {
	fc := &store.FakeClient{}
	a := newTestApp(t, fc)

	running := []store.RunningJob{{ID: "A"}, {ID: "B"}}
	m, _ := a.Update(runningJobsMsg{gen: 1, jobs: running})
	a = m.(App)
	_, cmd := a.Update(runningJobsMsg{gen: 2, jobs: nil})

	var sawHistory, sawCompleted bool
	for _, msg := range drainCmd(cmd) {
		switch msg.(type) {
		case historyMsg:
			sawHistory = true
		case completedJobMsg:
			sawCompleted = true
		}
	}
	if !sawHistory {
		t.Error("completion burst did not trigger one bulk history refresh")
	}
	if !fc.LastHistoryForced {
		t.Error("completion burst reused a throttled history snapshot instead of forcing one coalesced query")
	}
	if sawCompleted {
		t.Error("completion burst issued per-job controller lookups; want one bulk refresh")
	}
	if fc.LastCompletedJobID != "" {
		t.Errorf("per-job lookup happened (%q); want none for a bulk burst", fc.LastCompletedJobID)
	}
}
