package slurm

import (
	"context"
	"errors"
	"testing"
)

func TestCompletedJobRecordMapsTerminalJob(t *testing.T) {
	out := "JobId=999 JobName=train JobState=COMPLETED Restarts=1 ExitCode=0:0 " +
		"RunTime=00:10:00 SubmitTime=2024-01-15T08:00:00 StartTime=2024-01-15T08:01:00 " +
		"EndTime=2024-01-15T08:11:00 NodeList=node01 StdOut=/l/train_%j.out"
	c := NewClient(&FakeRunner{Outputs: map[string][]byte{"scontrol": []byte(out)}})

	job, found, err := c.CompletedJobRecord(context.Background(), "999")
	if err != nil || !found {
		t.Fatalf("found=%v err=%v, want true/nil", found, err)
	}
	if job.ID != "999" || job.Name != "train" || job.State != "COMPLETED" ||
		job.Restart != "1" || job.Elapsed != "00:10:00" || job.NodeList != "node01" ||
		job.Start != "2024-01-15T08:01:00" || job.End != "2024-01-15T08:11:00" {
		t.Errorf("mapped record = %+v", job)
	}
	if job.StdOut != "/l/train_999.out" || job.StdErr != "/l/train_999.out" {
		t.Errorf("paths = %q / %q, want expanded stdout with stderr defaulting to it", job.StdOut, job.StdErr)
	}
}

func TestCompletedJobRecordSkipsStillActive(t *testing.T) {
	out := "JobId=999 JobName=train JobState=RUNNING RunTime=00:01:00"
	c := NewClient(&FakeRunner{Outputs: map[string][]byte{"scontrol": []byte(out)}})

	_, found, err := c.CompletedJobRecord(context.Background(), "999")
	if err != nil || found {
		t.Errorf("found=%v err=%v, want false/nil (still running, not a completion)", found, err)
	}
}

func TestCompletedJobRecordCancelledIsTerminal(t *testing.T) {
	out := "JobId=999 JobName=train JobState=CANCELLED ExitCode=0:15 EndTime=2024-01-15T08:11:00"
	c := NewClient(&FakeRunner{Outputs: map[string][]byte{"scontrol": []byte(out)}})

	_, found, err := c.CompletedJobRecord(context.Background(), "999")
	if err != nil || !found {
		t.Errorf("found=%v err=%v, want true (CANCELLED is terminal)", found, err)
	}
}

// TestCompletedJobRecordArrayStillActive verifies an array job with running or
// pending tasks is not treated as finished just because a completed task record
// appears in the multi-record scontrol output.
func TestCompletedJobRecordArrayStillActive(t *testing.T) {
	out := "JobId=999 ArrayJobId=999 ArrayTaskId=1 JobState=COMPLETED EndTime=2024-01-15T08:11:00\n" +
		"JobId=1000 ArrayJobId=999 ArrayTaskId=2 JobState=RUNNING RunTime=00:01:00"
	c := NewClient(&FakeRunner{Outputs: map[string][]byte{"scontrol": []byte(out)}})

	_, found, err := c.CompletedJobRecord(context.Background(), "999")
	if err != nil || found {
		t.Errorf("found=%v err=%v, want false/nil (array still has a running task)", found, err)
	}
}

func TestCompletedJobRecordPropagatesError(t *testing.T) {
	c := NewClient(&FakeRunner{Errs: map[string]error{"scontrol": errors.New("boom")}})

	_, found, err := c.CompletedJobRecord(context.Background(), "999")
	if found || err == nil {
		t.Errorf("found=%v err=%v, want false + error", found, err)
	}
}
