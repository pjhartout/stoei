package slurm

import (
	"os"
	"path/filepath"
	"testing"
)

func TestParseControllerJobs(t *testing.T) {
	jobs := ParseControllerJobs(loadFixture(t, "scontrol_jobs.txt"))
	if len(jobs) != 4 {
		t.Fatalf("got %d jobs, want 4", len(jobs))
	}
	j := jobs[0]
	if j.ID != "1001" || j.User != "alice" || j.Name != "train" || j.State != "COMPLETED" ||
		j.Partition != "gpu" || j.Elapsed != "04:00:00" || j.Restart != "2" || j.NCPUS != "32" ||
		j.AllocTRES != "cpu=32,mem=256G,node=4,gres/gpu=16" ||
		j.Start != "2024-01-15T06:05:00" || j.End != "2024-01-15T10:05:00" {
		t.Errorf("job[0] = %+v", j)
	}
}

func TestParseControllerJobsArrayTaskID(t *testing.T) {
	// A dispatched array task: scontrol reports a distinct per-task JobId, but
	// squeue %i (and the completion overlay) key it as "<ArrayJobId>_<ArrayTaskId>".
	// ParseControllerJobs must use the squeue-style id so the journal/history row
	// dedups against the live running row instead of leaving a frozen duplicate.
	raw := "JobId=12350 ArrayJobId=12345 ArrayTaskId=3 JobName=train\n" +
		"   UserId=alice(1000) GroupId=alice(1000)\n" +
		"   JobState=RUNNING Reason=None\n" +
		"   RunTime=00:10:00 SubmitTime=2024-01-15T10:30:00 StartTime=2024-01-15T10:35:00 EndTime=Unknown\n" +
		"   Partition=gpu NumNodes=1 NumCPUs=8\n" +
		"   NodeList=gpu-node-05"
	jobs := ParseControllerJobs(raw)
	if len(jobs) != 1 {
		t.Fatalf("got %d jobs, want 1", len(jobs))
	}
	if jobs[0].ID != "12345_3" {
		t.Errorf("array task ID = %q, want 12345_3 (squeue-style, not the raw per-task JobId)", jobs[0].ID)
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

func mustUpsert(t *testing.T, j *jobJournal, jobs ...ControllerJob) {
	t.Helper()
	if err := j.upsert(jobs); err != nil {
		t.Fatalf("upsert: %v", err)
	}
}
