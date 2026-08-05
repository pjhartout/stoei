package store

import (
	"testing"

	"github.com/pjhartout/stoei/internal/slurm"
)

func TestAggregatePendingUserStatsArrayExpanded(t *testing.T) {
	jobs := []slurm.AllUsersJob{
		// A pending array of 100 tasks for bob, each requesting 4 CPUs + 1 GPU.
		{ID: "5000_[0-99]", User: "bob", State: "PENDING", Reason: "Priority", TRES: "cpu=4,mem=8G,gres/gpu:A100=1"},
		// A running job for bob must be ignored by the pending aggregation.
		{ID: "4000", User: "bob", State: "RUNNING", Reason: "None", TRES: "cpu=8,mem=16G"},
		// A pending single job for alice.
		{ID: "5001", User: "alice", State: "PD", Reason: "Resources", TRES: "cpu=2,mem=4G"},
	}
	got := AggregatePendingUserStats(jobs)
	if len(got) != 2 {
		t.Fatalf("got %d users; want 2", len(got))
	}

	// Sorted by pending CPUs descending: bob (400) before alice (2).
	if got[0].Username != "bob" {
		t.Fatalf("first user = %q; want bob (heaviest)", got[0].Username)
	}
	bob := got[0]
	if bob.PendingJobCount != 100 {
		t.Errorf("bob pending jobs = %d; want 100 (array expanded)", bob.PendingJobCount)
	}
	if bob.PendingCPUs != 400 {
		t.Errorf("bob pending CPUs = %d; want 400", bob.PendingCPUs)
	}
	if bob.PendingGPUs != 100 {
		t.Errorf("bob pending GPUs = %d; want 100", bob.PendingGPUs)
	}
	if bob.PendingGPUTypes != "100x A100" {
		t.Errorf("bob GPU types = %q; want %q", bob.PendingGPUTypes, "100x A100")
	}
	if bob.PendingReasons != "100x Priority" {
		t.Errorf("bob reasons = %q; want %q", bob.PendingReasons, "100x Priority")
	}
}

func TestAggregatePendingUserStatsReasonCounts(t *testing.T) {
	jobs := []slurm.AllUsersJob{
		{ID: "1", User: "u", State: "PENDING", Reason: "Resources", TRES: "cpu=1"},
		{ID: "2", User: "u", State: "PENDING", Reason: "Priority", TRES: "cpu=1"},
		{ID: "3", User: "u", State: "PENDING", Reason: "Priority", TRES: "cpu=1"},
		// The node-availability detail suffix collapses into the base reason.
		{ID: "4", User: "u", State: "PENDING", Reason: "ReqNodeNotAvail, UnavailableNodes:gpu-node-[01-04]", TRES: "cpu=1"},
		// A job without a reason contributes no bucket.
		{ID: "5", User: "u", State: "PENDING", TRES: "cpu=1"},
	}
	got := AggregatePendingUserStats(jobs)
	if len(got) != 1 {
		t.Fatalf("got %d users; want 1", len(got))
	}
	// Most frequent first, ties broken alphabetically.
	want := "2x Priority, 1x ReqNodeNotAvail, 1x Resources"
	if got[0].PendingReasons != want {
		t.Errorf("reasons = %q; want %q", got[0].PendingReasons, want)
	}
}

func TestRunningUserJobsExcludesPending(t *testing.T) {
	jobs := []slurm.AllUsersJob{
		{ID: "1", User: "a", State: "RUNNING"},
		{ID: "2", User: "a", State: "PENDING"},
		{ID: "3", User: "b", State: "PD"},
	}
	got := RunningUserJobs(jobs)
	if len(got) != 1 || got[0].ID != "1" {
		t.Errorf("RunningUserJobs = %+v; want only the RUNNING job", got)
	}
}
