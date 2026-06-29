package store

import (
	"errors"
	"testing"

	"github.com/pjhartout/stoei/internal/slurm"
)

func TestSetRunningJobsReportsVanished(t *testing.T) {
	s := New()
	g1 := s.NextGen(SectionRunningJobs)
	if v := s.SetRunningJobs([]slurm.RunningJob{{ID: "A"}, {ID: "B"}}, g1, nil); len(v) != 0 {
		t.Errorf("first set vanished = %v, want none (no prior set)", v)
	}
	g2 := s.NextGen(SectionRunningJobs)
	v := s.SetRunningJobs([]slurm.RunningJob{{ID: "A"}}, g2, nil)
	if len(v) != 1 || v[0] != "B" {
		t.Errorf("vanished = %v, want [B]", v)
	}
}

func TestSetRunningJobsNoVanishOnErrorOrStale(t *testing.T) {
	s := New()
	g1 := s.NextGen(SectionRunningJobs)
	s.SetRunningJobs([]slurm.RunningJob{{ID: "A"}}, g1, nil)

	g2 := s.NextGen(SectionRunningJobs)
	if v := s.SetRunningJobs(nil, g2, errors.New("squeue down")); v != nil {
		t.Errorf("error result vanished = %v, want nil (prev preserved, no false completions)", v)
	}
	// A stale (superseded) result is dropped entirely.
	if v := s.SetRunningJobs(nil, g1, nil); v != nil {
		t.Errorf("stale result vanished = %v, want nil", v)
	}
}

func TestAddCompletedJobMergesAndSacctAbsorbs(t *testing.T) {
	s := New()
	g1 := s.NextGen(SectionHistory)
	s.SetHistory([]slurm.HistoryJob{{ID: "old"}}, slurm.HistoryStats{}, g1, nil)

	s.AddCompletedJob(slurm.HistoryJob{ID: "new", State: "COMPLETED", Elapsed: "overlay"})
	if len(s.HistoryJobs) != 2 || s.HistoryJobs[0].ID != "new" || s.HistoryJobs[1].ID != "old" {
		t.Fatalf("history = %+v, want overlay [new] before base [old]", s.HistoryJobs)
	}

	// A later journal refresh that now carries "new" in a terminal state is
	// authoritative: the overlay copy is pruned and the base record shown (no dup).
	// The terminal base record (Elapsed "base") must replace the overlay copy,
	// which exercises the terminal-prune branch in rebuildHistory.
	g2 := s.NextGen(SectionHistory)
	s.SetHistory([]slurm.HistoryJob{
		{ID: "new", State: "COMPLETED", Elapsed: "base"},
		{ID: "old", State: "COMPLETED", Elapsed: "base"},
	}, slurm.HistoryStats{}, g2, nil)
	if len(s.HistoryJobs) != 2 {
		t.Fatalf("after the journal absorbs the completion, history len = %d, want 2 (no dup)", len(s.HistoryJobs))
	}
	for _, j := range s.HistoryJobs {
		if j.ID == "new" && j.Elapsed != "base" {
			t.Errorf("job new Elapsed = %q, want \"base\" (terminal base must prune and replace the overlay copy)", j.Elapsed)
		}
	}
}

// TestHistoryRefreshHealsStaleRunningToTerminal asserts a periodic history refresh
// promotes a job the merge had relabeled UNKNOWN (a stale RUNNING base snapshot for
// a job no longer in the queue) to its real terminal state — i.e. the slow-tick
// history reconcile fixes a completion the overlay missed, without a manual refresh.
func TestHistoryRefreshHealsStaleRunningToTerminal(t *testing.T) {
	s := New()
	// squeue has loaded (relabel active) and the job is no longer running.
	s.SetRunningJobs(nil, s.NextGen(SectionRunningJobs), nil)
	// The startup history snapshot still has the job as RUNNING.
	s.SetHistory([]slurm.HistoryJob{{ID: "7", State: "RUNNING"}}, slurm.HistoryStats{}, s.NextGen(SectionHistory), nil)
	if got := mergedStateByID(s, "7"); got != "UNKNOWN" {
		t.Fatalf("pre-reconcile state for job 7 = %q, want UNKNOWN", got)
	}

	// A later history refresh observes the terminal record.
	s.SetHistory([]slurm.HistoryJob{{ID: "7", State: "COMPLETED", Elapsed: "1:00"}}, slurm.HistoryStats{}, s.NextGen(SectionHistory), nil)
	if got := mergedStateByID(s, "7"); got != "COMPLETED" {
		t.Errorf("post-reconcile state for job 7 = %q, want COMPLETED (history refresh must heal the stale row)", got)
	}
}

func mergedStateByID(s *Store, id string) string {
	for _, j := range s.MergedJobs() {
		if j.ID == id {
			return j.State
		}
	}
	return ""
}

// TestAddCompletedJobSupersedesRunningBase covers the journal-era case: the
// history base (sourced from the scontrol journal) carries a job that was
// RUNNING when it was snapshotted. When that job finishes, the freshly observed
// terminal record (overlay) must win over the stale RUNNING base record, so the
// job flips to COMPLETED instead of staying frozen as RUNNING.
func TestAddCompletedJobSupersedesRunningBase(t *testing.T) {
	s := New()
	g1 := s.NextGen(SectionHistory)
	// The journal base snapshotted job 123 while it was still running.
	s.SetHistory([]slurm.HistoryJob{{ID: "123", State: "RUNNING", Elapsed: "1:00:00"}}, slurm.HistoryStats{}, g1, nil)

	// Job 123 finishes; the controller lookup reports the terminal record.
	s.AddCompletedJob(slurm.HistoryJob{ID: "123", State: "COMPLETED", Elapsed: "1:05:00"})

	if len(s.HistoryJobs) != 1 {
		t.Fatalf("history = %+v, want a single row for job 123 (no dup)", s.HistoryJobs)
	}
	if got := s.HistoryJobs[0].State; got != "COMPLETED" {
		t.Errorf("job 123 state = %q, want COMPLETED (overlay must win over stale RUNNING base)", got)
	}
}
