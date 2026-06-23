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

	s.AddCompletedJob(slurm.HistoryJob{ID: "new", State: "COMPLETED"})
	if len(s.HistoryJobs) != 2 || s.HistoryJobs[0].ID != "new" || s.HistoryJobs[1].ID != "old" {
		t.Fatalf("history = %+v, want overlay [new] before base [old]", s.HistoryJobs)
	}

	// A later sacct refresh that now includes "new" must not duplicate it.
	g2 := s.NextGen(SectionHistory)
	s.SetHistory([]slurm.HistoryJob{{ID: "new"}, {ID: "old"}}, slurm.HistoryStats{}, g2, nil)
	if len(s.HistoryJobs) != 2 {
		t.Errorf("after sacct absorbs the completion, history len = %d, want 2 (no dup)", len(s.HistoryJobs))
	}
}
