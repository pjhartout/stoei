package store

import (
	"testing"

	"github.com/pjhartout/stoei/internal/slurm"
)

// TestMergedJobsOrderDedupAndMapping covers the parity contract with
// stoei/slurm/cache.py JobCache._build_from_data (cache.py lines 182-238):
// running jobs come first, a history job duplicating a running id is dropped, and
// the remaining history jobs are appended with Nodes="" and Time from Elapsed.
func TestMergedJobsOrderDedupAndMapping(t *testing.T) {
	s := New()
	s.RunningJobs = []slurm.RunningJob{
		{ID: "A", Name: "trainA", State: "RUNNING", Time: "1:00", Nodes: "2", NodeList: "n[01-02]"},
		{ID: "B", Name: "trainB", State: "RUNNING", Time: "0:30", Nodes: "1", NodeList: "n03"},
	}
	s.HistoryJobs = []slurm.HistoryJob{
		// B also appears in history (completed) — must be deduped in favor of the
		// running entry.
		{ID: "B", Name: "trainB", State: "COMPLETED", Elapsed: "0:45", NodeList: "n03"},
		{ID: "C", Name: "trainC", State: "FAILED", Elapsed: "0:10", NodeList: "n04"},
	}

	got := s.MergedJobs()

	if len(got) != 3 {
		t.Fatalf("len(MergedJobs) = %d, want 3; rows=%+v", len(got), got)
	}

	// Order: A (running), B (running, NOT the history dup), C (failed history).
	wantOrder := []string{"A", "B", "C"}
	for i, want := range wantOrder {
		if got[i].ID != want {
			t.Errorf("row %d id = %q, want %q", i, got[i].ID, want)
		}
	}

	// B keeps the running mapping (RUNNING/0:30/Nodes=1), not the completed dup.
	b := got[1]
	if b.State != "RUNNING" || b.Time != "0:30" || b.Nodes != "1" || !b.Active {
		t.Errorf("B = %+v, want running mapping (RUNNING, 0:30, Nodes=1, Active)", b)
	}

	// C is the failed history job: present, State from sacct, Time from Elapsed,
	// Nodes empty (sacct history omits it), Active false.
	c := got[2]
	if c.State != "FAILED" {
		t.Errorf("C state = %q, want FAILED", c.State)
	}
	if c.Time != "0:10" {
		t.Errorf("C time = %q, want 0:10 (Elapsed)", c.Time)
	}
	if c.Nodes != "" {
		t.Errorf("C nodes = %q, want empty", c.Nodes)
	}
	if c.NodeList != "n04" {
		t.Errorf("C nodelist = %q, want n04", c.NodeList)
	}
	if c.Active {
		t.Error("C active = true, want false (history job)")
	}
}

// TestMergedJobsEmpty covers the degenerate inputs so a callsite can rely on a
// non-nil empty slice.
func TestMergedJobsEmpty(t *testing.T) {
	s := New()
	if got := s.MergedJobs(); len(got) != 0 {
		t.Errorf("MergedJobs on empty store = %+v, want empty", got)
	}
}

// TestMergedJobsRelabelsStaleRunningHistory covers a history job the journal
// still records as RUNNING but that has left the live queue (its completion was
// never observed). Once squeue has loaded, such a row is relabeled rather than
// shown as a frozen RUNNING; a genuinely running job stays live.
func TestMergedJobsRelabelsStaleRunningHistory(t *testing.T) {
	s := New()
	// squeue loaded successfully and still shows A running.
	g := s.NextGen(SectionRunningJobs)
	s.SetRunningJobs([]slurm.RunningJob{{ID: "A", State: "RUNNING", Time: "1:00"}}, g, nil)
	// The journal records A (still running) and B (RUNNING but gone from the queue).
	s.HistoryJobs = []slurm.HistoryJob{
		{ID: "A", State: "RUNNING"},
		{ID: "B", State: "RUNNING"},
	}

	byID := map[string]MergedJob{}
	for _, j := range s.MergedJobs() {
		byID[j.ID] = j
	}

	if a := byID["A"]; a.State != "RUNNING" || !a.Active {
		t.Errorf("A = %+v, want live RUNNING (Active)", a)
	}
	b, ok := byID["B"]
	if !ok {
		t.Fatal("B missing from merged jobs")
	}
	if b.State != "UNKNOWN" {
		t.Errorf("B state = %q, want UNKNOWN (stale RUNNING relabeled)", b.State)
	}
	if b.Active {
		t.Error("B active = true, want false (history row)")
	}
}

// TestMergedJobsKeepsHistoryRunningBeforeSqueueLoads guards the relabel: with no
// successful running-jobs fetch yet there is no trustworthy squeue snapshot, so a
// non-terminal history row must be shown verbatim, not relabeled.
func TestMergedJobsKeepsHistoryRunningBeforeSqueueLoads(t *testing.T) {
	s := New()
	s.HistoryJobs = []slurm.HistoryJob{{ID: "B", State: "RUNNING"}}
	got := s.MergedJobs()
	if len(got) != 1 || got[0].State != "RUNNING" {
		t.Errorf("before squeue loads, history state must be left as-is; got %+v", got)
	}
}
