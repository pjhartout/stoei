package store

import (
	"errors"
	"testing"
	"time"

	"github.com/pjhartout/stoei/internal/slurm"
)

func TestNextGenMonotonic(t *testing.T) {
	s := New()
	if g := s.NextGen(SectionRunningJobs); g != 1 {
		t.Errorf("first NextGen = %d; want 1", g)
	}
	if g := s.NextGen(SectionRunningJobs); g != 2 {
		t.Errorf("second NextGen = %d; want 2", g)
	}
	// Independent per section.
	if g := s.NextGen(SectionNodes); g != 1 {
		t.Errorf("nodes NextGen = %d; want 1", g)
	}
	if s.Gen(SectionRunningJobs) != 2 {
		t.Errorf("Gen running = %d; want 2", s.Gen(SectionRunningJobs))
	}
}

func TestSetRunningJobsStateTransitions(t *testing.T) {
	s := New()
	fixed := time.Date(2024, 1, 1, 12, 0, 0, 0, time.UTC)
	s.SetClock(func() time.Time { return fixed })

	if s.State(SectionRunningJobs) != StateIdle {
		t.Fatalf("initial state = %v; want idle", s.State(SectionRunningJobs))
	}

	gen := s.NextGen(SectionRunningJobs)
	s.SetLoading(SectionRunningJobs, gen)
	if s.State(SectionRunningJobs) != StateLoading {
		t.Fatalf("after SetLoading state = %v; want loading", s.State(SectionRunningJobs))
	}

	jobs := []slurm.RunningJob{{ID: "1"}}
	s.SetRunningJobs(jobs, gen, nil)
	if s.State(SectionRunningJobs) != StateLoaded {
		t.Fatalf("after success state = %v; want loaded", s.State(SectionRunningJobs))
	}
	if len(s.RunningJobs) != 1 || s.RunningJobs[0].ID != "1" {
		t.Fatalf("data not applied: %+v", s.RunningJobs)
	}
	if !s.RunningJobsMeta.LastUpdated.Equal(fixed) {
		t.Errorf("LastUpdated = %v; want %v", s.RunningJobsMeta.LastUpdated, fixed)
	}
	if s.RunningJobsMeta.Err != nil {
		t.Errorf("Err = %v; want nil", s.RunningJobsMeta.Err)
	}
}

func TestSetRunningJobsErrorKeepsData(t *testing.T) {
	s := New()
	gen := s.NextGen(SectionRunningJobs)
	s.SetRunningJobs([]slurm.RunningJob{{ID: "1"}}, gen, nil)

	// A subsequent error must record StateError, the error, and keep prior data.
	gen2 := s.NextGen(SectionRunningJobs)
	wantErr := errors.New("boom")
	s.SetRunningJobs(nil, gen2, wantErr)

	if s.State(SectionRunningJobs) != StateError {
		t.Errorf("state = %v; want error", s.State(SectionRunningJobs))
	}
	if !errors.Is(s.RunningJobsMeta.Err, wantErr) {
		t.Errorf("Err = %v; want %v", s.RunningJobsMeta.Err, wantErr)
	}
	if len(s.RunningJobs) != 1 {
		t.Errorf("data cleared on error: %+v; want prior data kept", s.RunningJobs)
	}
}

func TestStaleResultDropped(t *testing.T) {
	s := New()

	// Dispatch gen 1, then supersede with gen 2.
	gen1 := s.NextGen(SectionRunningJobs)
	gen2 := s.NextGen(SectionRunningJobs)

	// Newer result (gen2) lands first.
	s.SetRunningJobs([]slurm.RunningJob{{ID: "new"}}, gen2, nil)
	// Stale result (gen1) arrives late and must be dropped.
	s.SetRunningJobs([]slurm.RunningJob{{ID: "old"}}, gen1, nil)

	if len(s.RunningJobs) != 1 || s.RunningJobs[0].ID != "new" {
		t.Errorf("stale result not dropped: %+v", s.RunningJobs)
	}
}

func TestStaleErrorDropped(t *testing.T) {
	s := New()
	gen1 := s.NextGen(SectionHistory)
	gen2 := s.NextGen(SectionHistory)

	s.SetHistory([]slurm.HistoryJob{{ID: "ok"}}, slurm.HistoryStats{TotalJobs: 1}, gen2, nil)
	// A stale error from gen1 must not flip the section into error state.
	s.SetHistory(nil, slurm.HistoryStats{}, gen1, errors.New("late failure"))

	if s.State(SectionHistory) != StateLoaded {
		t.Errorf("state = %v; want loaded (stale error dropped)", s.State(SectionHistory))
	}
	if s.HistoryStats.TotalJobs != 1 {
		t.Errorf("stats overwritten by stale: %+v", s.HistoryStats)
	}
}

func TestSetNodesRecomputesClusterStats(t *testing.T) {
	s := New()
	genN := s.NextGen(SectionNodes)
	s.SetNodes([]slurm.Node{
		{State: "IDLE", CPUTot: "10", CPUAlloc: "0", RealMem: "1024", AllocMem: "0", CfgTRES: "cpu=10"},
	}, genN, nil)

	if s.ClusterStats.TotalNodes != 1 || s.ClusterStats.TotalCPUs != 10 {
		t.Errorf("cluster stats not recomputed: %+v", s.ClusterStats)
	}

	// Adding all-users pending jobs recomputes pending resources too.
	genA := s.NextGen(SectionAllUsersJobs)
	s.SetAllUsersJobs([]slurm.AllUsersJob{
		{ID: "1", User: "x", Partition: "p", State: "PENDING", TRES: "cpu=4"},
	}, genA, nil)
	if s.ClusterStats.PendingCPUs != 4 {
		t.Errorf("pending not recomputed: %+v", s.ClusterStats)
	}
}

func TestSetLoadingStaleIgnored(t *testing.T) {
	s := New()
	gen1 := s.NextGen(SectionNodes)
	s.NextGen(SectionNodes) // bump to gen 2

	// A stale loading mark for gen1 must not move the state.
	s.SetLoading(SectionNodes, gen1)
	if s.State(SectionNodes) != StateIdle {
		t.Errorf("stale SetLoading applied: state = %v; want idle", s.State(SectionNodes))
	}
}

func TestDerivedAccessors(t *testing.T) {
	s := New()
	genA := s.NextGen(SectionAllUsersJobs)
	s.SetAllUsersJobs([]slurm.AllUsersJob{
		{ID: "1", User: "alice", Partition: "gpu", State: "RUNNING", NumNodes: "1", NodeList: "n01", TRES: "cpu=8"},
	}, genA, nil)
	if us := s.RunningUserStats(); len(us) != 1 || us[0].Username != "alice" {
		t.Errorf("RunningUserStats = %+v", us)
	}
}
