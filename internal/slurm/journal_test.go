package slurm

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// TestCompletedJobRecordPersistsToJournal asserts a mid-session completion observed
// via "scontrol show jobid" is written to the durable journal, so its terminal
// state survives a restart instead of reverting to the last RUNNING snapshot.
func TestCompletedJobRecordPersistsToJournal(t *testing.T) {
	path := filepath.Join(t.TempDir(), "jobs.jsonl")
	out := "JobId=777 JobName=train UserId=alice(1000) JobState=COMPLETED " +
		"ExitCode=0:0 Restarts=0 RunTime=01:00:00 NodeList=n01 " +
		"SubmitTime=2024-01-15T06:00:00 StartTime=2024-01-15T06:05:00 EndTime=2024-01-15T07:05:00"
	r := &fixtureRunner{outputs: map[string]string{"scontrol": out}}
	c := NewClient(r, WithUsername("alice"), WithJournal(path))

	if _, found, err := c.CompletedJobRecord(context.Background(), "777"); err != nil || !found {
		t.Fatalf("CompletedJobRecord: found=%v err=%v", found, err)
	}

	// Re-read the journal from disk, as a restart would.
	var rec *ControllerJob
	for _, j := range newJobJournal(path).all() {
		if j.ID == "777" {
			j := j
			rec = &j
		}
	}
	if rec == nil {
		t.Fatal("job 777 was not persisted to the journal (its completion is lost on restart)")
	}
	if !IsTerminalState(rec.State) {
		t.Errorf("journal state for 777 = %q, want a terminal state", rec.State)
	}
}

// journalWidths are the per-column widths of JournalSqueueFormat.
var journalWidths = []int{30, 20, 20, 15, 50, 20, 15, 25, 25, 25, 15, 10, 10, 10, 80, 200, 256}

// journalRow renders one fixed-width squeue -O line in JournalSqueueFormat
// order. Trailing columns may be omitted and render empty, so tests that do
// not exercise the log-path columns stay terse.
func journalRow(t *testing.T, cols ...string) string {
	t.Helper()
	if len(cols) > len(journalWidths)+1 {
		t.Fatalf("journalRow takes at most %d columns, got %d", len(journalWidths)+1, len(cols))
	}
	var b strings.Builder
	for i, w := range journalWidths {
		col := ""
		if i < len(cols) {
			col = cols[i]
		}
		fmt.Fprintf(&b, "%-*s", w, col)
	}
	if len(cols) == len(journalWidths)+1 {
		b.WriteString(cols[len(journalWidths)])
	}
	return b.String()
}

func TestParseJournalJobs(t *testing.T) {
	raw := journalRow(t,
		"1001", "1001", "N/A", "alice", "train", "COMPLETED", "gpu",
		"2024-01-15T06:00:00", "2024-01-15T06:05:00", "2024-01-15T10:05:00",
		"4:00:00", "0:0", "2", "32", "gpu-node-[01-04]", "cpu=32,mem=256G,node=4,gres/gpu=16",
	) + "\n" + journalRow(t,
		"1002", "1002", "N/A", "alice", "eval", "RUNNING", "cpu",
		"2024-01-15T11:00:00", "2024-01-15T11:05:00", "N/A",
		"0:30:00", "0:0", "0", "8", "cpu-node-05", "cpu=8,mem=32G,node=1",
	)
	jobs := ParseJournalJobs(raw)
	if len(jobs) != 2 {
		t.Fatalf("got %d jobs, want 2", len(jobs))
	}
	j := jobs[0]
	if j.ID != "1001" || j.User != "alice" || j.Name != "train" || j.State != "COMPLETED" ||
		j.Partition != "gpu" || j.Elapsed != "4:00:00" || j.ExitCode != "0:0" || j.Restart != "2" ||
		j.NCPUS != "32" || j.NodeList != "gpu-node-[01-04]" ||
		j.AllocTRES != "cpu=32,mem=256G,node=4,gres/gpu=16" ||
		j.Submit != "2024-01-15T06:00:00" || j.Start != "2024-01-15T06:05:00" || j.End != "2024-01-15T10:05:00" {
		t.Errorf("job[0] = %+v", j)
	}
}

func TestParseJournalJobsArrayIDs(t *testing.T) {
	// Dispatched array tasks must normalize to the %i "<ArrayJobId>_<TaskId>"
	// form so journal rows dedup against live rows; leaders keep the raw id.
	raw := journalRow(t,
		"12350", "12345", "3", "alice", "train", "RUNNING", "gpu",
		"2024-01-15T10:30:00", "2024-01-15T10:35:00", "N/A",
		"0:10:00", "0:0", "0", "8", "gpu-node-05", "cpu=8",
	) + "\n" + journalRow(t,
		"12400", "12400", "0-99%4", "alice", "sweep", "PENDING", "gpu",
		"2024-01-15T10:30:00", "N/A", "N/A",
		"0:00", "0:0", "0", "8", "", "cpu=8",
	)
	jobs := ParseJournalJobs(raw)
	if len(jobs) != 2 {
		t.Fatalf("got %d jobs, want 2", len(jobs))
	}
	if jobs[0].ID != "12345_3" {
		t.Errorf("array task ID = %q, want 12345_3 (squeue %%i form, not the raw per-task JobId)", jobs[0].ID)
	}
	if jobs[1].ID != "12400" {
		t.Errorf("pending array leader ID = %q, want raw 12400", jobs[1].ID)
	}
}

func TestJournalPersistsAndKeepsTerminalFinal(t *testing.T) {
	path := filepath.Join(t.TempDir(), "jobs.jsonl")
	j := newJobJournal(path)

	// A job seen running, then finishing.
	mustUpsert(t, j, ControllerJob{ID: "7", State: "RUNNING", Name: "a", Elapsed: "00:10:00"})
	mustUpsert(t, j, ControllerJob{ID: "7", State: "COMPLETED", Name: "a", Elapsed: "00:30:00"})
	// A later (stale) observation must not overwrite the terminal record.
	mustUpsert(t, j, ControllerJob{ID: "7", State: "RUNNING", Name: "a", Elapsed: "00:05:00"})

	// Reopening at the same path proves persistence across sessions.
	reopened := newJobJournal(path)
	all := reopened.all()
	if len(all) != 1 {
		t.Fatalf("got %d jobs, want 1", len(all))
	}
	if all[0].State != "COMPLETED" || all[0].Elapsed != "00:30:00" {
		t.Errorf("terminal record was overwritten: %+v", all[0])
	}
	if _, err := os.Stat(path); err != nil {
		t.Errorf("journal file missing: %v", err)
	}
}

// TestJournalConcurrentUpsertsLoseNothing drives two journal handles (as two
// stoei processes would) upserting disjoint jobs into the same file
// concurrently. The cross-process lock must serialize each read-merge-write
// cycle so neither handle's whole-file rewrite discards the other's records.
func TestJournalConcurrentUpsertsLoseNothing(t *testing.T) {
	path := filepath.Join(t.TempDir(), "jobs.jsonl")
	handles := []*jobJournal{newJobJournal(path), newJobJournal(path)}
	var wg sync.WaitGroup
	for i, h := range handles {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for k := range 20 {
				id := fmt.Sprintf("%d-%d", i, k)
				if err := h.upsert([]ControllerJob{{ID: id, State: "COMPLETED"}}); err != nil {
					t.Errorf("upsert %s: %v", id, err)
				}
			}
		}()
	}
	wg.Wait()
	if got := len(newJobJournal(path).all()); got != 40 {
		t.Errorf("journal has %d records after concurrent upserts, want 40 (records lost)", got)
	}
}

func mustUpsert(t *testing.T, j *jobJournal, jobs ...ControllerJob) {
	t.Helper()
	if err := j.upsert(jobs); err != nil {
		t.Fatalf("upsert: %v", err)
	}
}

// TestJournalPrunesRecordsBeyondRetention asserts an upsert drops records last
// seen beyond the 90-day retention (the job_history_days ceiling), so the file
// cannot grow without bound.
func TestJournalPrunesRecordsBeyondRetention(t *testing.T) {
	path := filepath.Join(t.TempDir(), "jobs.jsonl")
	j := newJobJournal(path)
	t0 := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

	j.now = func() time.Time { return t0 }
	mustUpsert(t, j, ControllerJob{ID: "old", State: "COMPLETED"})

	j.now = func() time.Time { return t0.Add(journalRetention + 24*time.Hour) }
	mustUpsert(t, j, ControllerJob{ID: "new", State: "RUNNING"})

	all := j.all()
	if len(all) != 1 || all[0].ID != "new" {
		t.Errorf("journal after retention pruning = %+v, want only the new record", all)
	}
}

// TestParseJournalJobsCapturesLogPaths asserts the journal query's path
// columns land on the record with the sbatch patterns expanded from the row's
// own fields, and that a missing stderr defaults to the stdout file.
func TestParseJournalJobsCapturesLogPaths(t *testing.T) {
	raw := journalRow(t,
		"12350", "12345", "3", "alice", "train", "RUNNING", "gpu",
		"2024-01-15T10:30:00", "2024-01-15T10:35:00", "N/A",
		"0:10:00", "0:0", "0", "8", "gpu-node-05", "cpu=8",
		"/logs/train_%A_%a.err", "/logs/train_%j_%u_%x.out",
	)
	jobs := ParseJournalJobs(raw)
	if len(jobs) != 1 {
		t.Fatalf("got %d jobs, want 1", len(jobs))
	}
	if jobs[0].StdOut != "/logs/train_12350_alice_train.out" {
		t.Errorf("StdOut = %q (raw id, user, and name must expand)", jobs[0].StdOut)
	}
	if jobs[0].StdErr != "/logs/train_12345_3.err" {
		t.Errorf("StdErr = %q (array master/task must expand)", jobs[0].StdErr)
	}

	merged := ParseJournalJobs(journalRow(t,
		"1002", "1002", "N/A", "alice", "eval", "RUNNING", "cpu",
		"2024-01-15T11:00:00", "2024-01-15T11:05:00", "N/A",
		"0:30:00", "0:0", "0", "8", "cpu-node-05", "cpu=8",
		"", "/logs/eval.out",
	))
	if len(merged) != 1 || merged[0].StdErr != "/logs/eval.out" {
		t.Errorf("empty stderr must default to the stdout file, got %+v", merged)
	}
}

// TestJournalUpsertPathRules pins the log-path merge rules: a pathless source
// must never wipe recorded paths, and a terminal record written before stoei
// captured paths gains them from a later observation without its final state
// being disturbed.
func TestJournalUpsertPathRules(t *testing.T) {
	j := newJobJournal(filepath.Join(t.TempDir(), "jobs.jsonl"))
	mustUpsert(t, j, ControllerJob{ID: "7", State: "RUNNING", StdOut: "/l/out.log", StdErr: "/l/err.log"})
	mustUpsert(t, j, ControllerJob{ID: "7", State: "RUNNING"})
	mustUpsert(t, j, ControllerJob{ID: "8", State: "COMPLETED"})
	mustUpsert(t, j, ControllerJob{ID: "8", State: "FAILED", StdOut: "/l/8.out", StdErr: "/l/8.err"})

	got := map[string]ControllerJob{}
	for _, job := range j.all() {
		got[job.ID] = job
	}
	if got["7"].StdOut != "/l/out.log" || got["7"].StdErr != "/l/err.log" {
		t.Errorf("pathless upsert wiped recorded paths: %+v", got["7"])
	}
	if got["8"].State != "COMPLETED" {
		t.Errorf("path backfill disturbed the final state: %+v", got["8"])
	}
	if got["8"].StdOut != "/l/8.out" || got["8"].StdErr != "/l/8.err" {
		t.Errorf("terminal record did not gain paths: %+v", got["8"])
	}
}
