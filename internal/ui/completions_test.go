package ui

import (
	"fmt"
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

// TestLargeCompletionBurstUsesBulkHistory asserts that when more than
// completionBulkThreshold jobs vanish in one refresh (a draining array), the app
// issues a single bulk history refresh instead of one controller lookup per job.
func TestLargeCompletionBurstUsesBulkHistory(t *testing.T) {
	fc := &store.FakeClient{}
	a := newTestApp(t, fc)

	big := make([]store.RunningJob, 0, completionBulkThreshold+2)
	for i := 0; i < completionBulkThreshold+2; i++ {
		big = append(big, store.RunningJob{ID: fmt.Sprintf("job-%d", i)})
	}
	m, _ := a.Update(runningJobsMsg{gen: 1, jobs: big})
	a = m.(App)
	_, cmd := a.Update(runningJobsMsg{gen: 2, jobs: nil}) // the whole set vanishes at once

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
		t.Error("large completion burst did not trigger a bulk history refresh")
	}
	if sawCompleted {
		t.Error("large burst issued per-job controller lookups; want one bulk refresh")
	}
	if fc.LastCompletedJobID != "" {
		t.Errorf("per-job lookup happened (%q); want none for a bulk burst", fc.LastCompletedJobID)
	}
}
